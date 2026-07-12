from __future__ import annotations

from datetime import datetime
import uuid

from fastapi.testclient import TestClient


def test_public_routes_exist() -> None:
    from fort_gym.bench.api.server import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/r/{token}" in paths
    assert "/replay/{token}" in paths
    assert "/public/runs" in paths
    assert "/public/worlds" in paths
    assert "/public/overview" in paths
    assert "/public/leaderboard" in paths
    assert "/public/runs/{token}" in paths
    assert "/public/runs/{token}/summary" in paths
    assert "/public/runs/{token}/preview" in paths
    assert "/public/runs/{token}/events/stream" in paths
    assert "/public/runs/{token}/events/replay" in paths


def test_public_html_entrypoints_are_not_cached() -> None:
    from fort_gym.bench.api.server import app

    client = TestClient(app)

    for path in ("/", "/r/example-token", "/replay/example-token", "/leaderboard"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert response.headers["Pragma"] == "no-cache"


def test_public_screenshot_recovers_stale_dfhack_client(monkeypatch) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    class BrokenScreenshotClient:
        closed = False

        def get_screen(self):
            raise BrokenPipeError(32, "Broken pipe")

        def close(self) -> None:
            self.closed = True

    class WorkingScreenshotClient:
        def get_screen(self):
            return {"width": 1, "height": 1, "tiles": [[46, 7, 0]]}

    RUN_REGISTRY.reset_for_tests()
    server._screenshot_client = None
    try:
        run_id = uuid.uuid4().hex
        RUN_REGISTRY.create(
            backend="dfhack",
            model="fake",
            max_steps=1,
            ticks_per_step=10,
            run_id=run_id,
        )
        share = RUN_REGISTRY.create_share(run_id, scope=["live"])

        broken = BrokenScreenshotClient()
        working = WorkingScreenshotClient()
        clients = [broken, working]

        def get_screenshot_client():
            return clients.pop(0)

        server._screenshot_client = broken
        monkeypatch.setattr(server, "_get_screenshot_client", get_screenshot_client)

        client = TestClient(server.app)
        response = client.get(f"/public/runs/{share.token}/screenshot")

        assert response.status_code == 200
        assert response.json() == {"width": 1, "height": 1, "tiles": [[46, 7, 0]]}
        assert broken.closed is True
    finally:
        server._screenshot_client = None
        RUN_REGISTRY.reset_for_tests()


def test_public_overview_groups_only_protocol_scoped_model_results() -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    try:
        active = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-a",
            max_steps=20,
            ticks_per_step=100,
            seed_save="seed-a",
            evaluation_protocol="fort-eval-v1",
        )
        active_share = RUN_REGISTRY.create_share(active.run_id, scope=["live"])
        assert RUN_REGISTRY.claim_pending_run(active.run_id, started_at=datetime.utcnow())

        official_run_ids = []
        terminal_tokens = []
        for score in (40.0, 60.0):
            run = RUN_REGISTRY.create(
                backend="dfhack",
                model="agent-a",
                max_steps=20,
                ticks_per_step=100,
                seed_save="seed-a",
                evaluation_protocol="fort-eval-v1",
            )
            share = RUN_REGISTRY.create_share(run.run_id, scope=["live", "replay", "export"])
            RUN_REGISTRY.set_summary(
                run.run_id,
                {
                    "evaluation_protocol": "fort-eval-v1",
                    "total_score": score,
                    "score_version": 5,
                    "rubric": {"rubric_score": 70},
                },
            )
            RUN_REGISTRY.set_status(run.run_id, status="completed", ended_at=datetime.utcnow())
            official_run_ids.append(run.run_id)
            terminal_tokens.append(share.token)

        agent_b = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-b",
            max_steps=20,
            ticks_per_step=100,
            seed_save="seed-a",
            evaluation_protocol="fort-eval-v1",
        )
        agent_b_share = RUN_REGISTRY.create_share(
            agent_b.run_id, scope=["live", "replay", "export"]
        )
        RUN_REGISTRY.set_summary(
            agent_b.run_id,
            {"evaluation_protocol": "fort-eval-v1", "total_score": 100.0, "score_version": 5},
        )
        RUN_REGISTRY.set_status(agent_b.run_id, status="completed", ended_at=datetime.utcnow())
        official_run_ids.append(agent_b.run_id)

        # Legacy evidence stays public but cannot become an official comparison.
        legacy = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-a",
            max_steps=20,
            ticks_per_step=100,
            seed_save="seed-a",
            evaluation_protocol="fort-eval-v1",
        )
        legacy_share = RUN_REGISTRY.create_share(legacy.run_id, scope=["live"])
        RUN_REGISTRY.set_summary(legacy.run_id, {"total_score": 999.0, "score_version": 5})
        RUN_REGISTRY.set_status(legacy.run_id, status="failed", ended_at=datetime.utcnow())

        missing_sha = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-c",
            max_steps=20,
            ticks_per_step=100,
            seed_save="seed-a",
        )
        missing_sha_share = RUN_REGISTRY.create_share(missing_sha.run_id, scope=["live"])
        RUN_REGISTRY.set_summary(
            missing_sha.run_id,
            {"evaluation_protocol": "fort-eval-v1", "total_score": 200.0, "score_version": 5},
        )

        conn = RUN_REGISTRY._ensure_conn()  # noqa: SLF001 - test-only provenance setup
        conn.executemany(
            "UPDATE runs SET git_sha = ? WHERE run_id = ?",
            [("commit-a", run_id) for run_id in official_run_ids] + [(None, missing_sha.run_id)],
        )
        conn.commit()
        RUN_REGISTRY.set_status(missing_sha.run_id, status="completed", ended_at=datetime.utcnow())

        mismatched_protocol = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-d",
            max_steps=20,
            ticks_per_step=100,
            seed_save="seed-a",
            evaluation_protocol="fort-eval-v2",
        )
        mismatched_share = RUN_REGISTRY.create_share(mismatched_protocol.run_id, scope=["live"])
        RUN_REGISTRY.set_summary(
            mismatched_protocol.run_id,
            {"evaluation_protocol": "fort-eval-v1", "total_score": 300.0, "score_version": 5},
        )
        RUN_REGISTRY.set_status(
            mismatched_protocol.run_id, status="completed", ended_at=datetime.utcnow()
        )

        live_only = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-e",
            max_steps=20,
            ticks_per_step=100,
            seed_save="seed-a",
            evaluation_protocol="fort-eval-v1",
        )
        live_only_share = RUN_REGISTRY.create_share(live_only.run_id, scope=["live"])
        RUN_REGISTRY.set_summary(
            live_only.run_id,
            {"evaluation_protocol": "fort-eval-v1", "total_score": 500.0, "score_version": 5},
        )
        conn.execute("UPDATE runs SET git_sha = ? WHERE run_id = ?", ("commit-a", live_only.run_id))
        conn.commit()
        RUN_REGISTRY.set_status(live_only.run_id, status="completed", ended_at=datetime.utcnow())

        response = TestClient(server.app).get("/public/overview")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["active_runs"]) == 1
        assert payload["active_runs"][0]["run_id"] == active.run_id
        assert payload["active_runs"][0]["token"] == active_share.token
        assert {item["token"] for item in payload["recent_runs"]} == set(terminal_tokens) | {
            agent_b_share.token,
            legacy_share.token,
            missing_sha_share.token,
            mismatched_share.token,
            live_only_share.token,
        }
        assert payload["comparability_fields"] == [
            "evaluation_protocol",
            "backend",
            "git_sha",
            "score_version",
            "seed_save",
            "max_steps",
            "ticks_per_step",
        ]
        assert payload["comparison_groups"] == [
            {
                "comparability": {
                    "evaluation_protocol": "fort-eval-v1",
                    "backend": "dfhack",
                    "git_sha": "commit-a",
                    "score_version": 5,
                    "seed_save": "seed-a",
                    "max_steps": 20,
                    "ticks_per_step": 100,
                },
                "model_results": [
                    {
                        "model": "agent-b",
                        "run_count": 1,
                        "mean_score": 100.0,
                        "best_score": 100.0,
                        "best_token": agent_b_share.token,
                    },
                    {
                        "model": "agent-a",
                        "run_count": 2,
                        "mean_score": 50.0,
                        "best_score": 60.0,
                        "best_token": terminal_tokens[1],
                    },
                ],
            }
        ]

        limited = TestClient(server.app).get("/public/overview?recent_limit=1")
        assert len(limited.json()["recent_runs"]) == 1
        assert limited.json()["comparison_groups"] == payload["comparison_groups"]
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_run_selection_prefers_replayable_evidence_token() -> None:
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    try:
        run = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-a",
            max_steps=1,
            ticks_per_step=10,
        )
        RUN_REGISTRY.create_share(run.run_id, scope=["live"])
        evidence = RUN_REGISTRY.create_share(run.run_id, scope=["replay", "export"])

        [(selected_run, selected_share)] = RUN_REGISTRY.list_public()

        assert selected_run.run_id == run.run_id
        assert selected_share.token == evidence.token
        assert {"replay", "export"}.issubset(selected_share.scope)
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_worlds_filters_paginates_sorts_and_never_reads_traces(monkeypatch) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    monkeypatch.setattr(
        server,
        "read_trace_preview",
        lambda _path: (_ for _ in ()).throw(AssertionError("runs library read a trace")),
    )
    try:
        oldest = RUN_REGISTRY.create(
            backend="mock",
            model="Agent Alpha",
            max_steps=1,
            ticks_per_step=1,
            seed_save="seed-a",
        )
        RUN_REGISTRY.create_share(oldest.run_id)
        RUN_REGISTRY.set_status(oldest.run_id, status="completed", ended_at=datetime(2026, 1, 1))

        live_only = RUN_REGISTRY.create(
            backend="dfhack",
            model="Agent Live Only",
            max_steps=1,
            ticks_per_step=1,
            seed_save="seed-a",
        )
        RUN_REGISTRY.create_share(live_only.run_id, scope=["live"])
        RUN_REGISTRY.set_status(
            live_only.run_id, status="failed", ended_at=datetime(2026, 1, 2)
        )

        replay_only = RUN_REGISTRY.create(
            backend="dfhack",
            model="Agent Replay Only",
            max_steps=1,
            ticks_per_step=1,
            seed_save="seed-a",
        )
        RUN_REGISTRY.create_share(replay_only.run_id, scope=["replay"])
        RUN_REGISTRY.set_status(
            replay_only.run_id, status="failed", ended_at=datetime(2026, 1, 2)
        )

        legacy = RUN_REGISTRY.create(
            backend="dfhack",
            model="Agent Legacy",
            max_steps=1,
            ticks_per_step=1,
            seed_save="seed-a",
        )
        legacy_share = RUN_REGISTRY.create_share(legacy.run_id, scope=["replay", "export"])
        RUN_REGISTRY.set_status(legacy.run_id, status="failed", ended_at=datetime(2026, 1, 2))

        newest = RUN_REGISTRY.create(
            backend="dfhack",
            model="Agent Beta",
            max_steps=1,
            ticks_per_step=1,
            seed_save="seed-b",
            evaluation_protocol="fort-eval-v1",
        )
        RUN_REGISTRY.create_share(newest.run_id, scope=["live"])
        newest_share = RUN_REGISTRY.create_share(newest.run_id, scope=["replay", "export"])
        RUN_REGISTRY.set_status(newest.run_id, status="completed", ended_at=datetime(2026, 1, 3))

        active = RUN_REGISTRY.create(
            backend="dfhack",
            model="Agent Beta",
            max_steps=1,
            ticks_per_step=1,
            seed_save="seed-b",
            evaluation_protocol="fort-eval-v1",
        )
        active_share = RUN_REGISTRY.create_share(active.run_id)
        assert RUN_REGISTRY.claim_pending_run(active.run_id, started_at=datetime(2025, 1, 1))

        client = TestClient(server.app)
        response = client.get("/public/worlds?limit=2&offset=0")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 3
        assert payload["limit"] == 2
        assert payload["offset"] == 0
        assert [item["run_id"] for item in payload["items"]] == [active.run_id, newest.run_id]
        assert payload["items"][0]["token"] == active_share.token
        assert payload["items"][0]["scopes"] == ["export", "live", "replay"]
        assert payload["items"][1]["token"] == newest_share.token

        second_page = client.get("/public/worlds?limit=2&offset=2").json()
        assert [item["run_id"] for item in second_page["items"]] == [legacy.run_id]

        filtered = client.get(
            "/public/worlds?status=completed&model=Agent%20Beta&"
            "evaluation_protocol=fort-eval-v1&seed_save=seed-b&q=DFHACK"
        ).json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["run_id"] == newest.run_id

        legacy_result = client.get("/public/worlds?q=legacy").json()
        assert legacy_result["items"][0]["run_id"] == legacy.run_id
        assert legacy_result["items"][0]["evaluation_protocol"] is None
        assert legacy_result["items"][0]["token"] == legacy_share.token
        assert client.get("/public/worlds?q=alpha").json()["total"] == 0
        assert client.get("/public/worlds?q=live%20only").json()["total"] == 0
        assert client.get("/public/worlds?q=replay%20only").json()["total"] == 0

        assert client.get(f"/public/worlds?model={'x' * 201}").status_code == 422
        assert client.get("/public/worlds?offset=10001").status_code == 422

        class RejectReadLock:
            def __enter__(self):
                raise AssertionError("public archive acquired the registry write lock")

            def __exit__(self, *_args):
                return False

        with monkeypatch.context() as context:
            context.setattr(RUN_REGISTRY, "_db_lock", RejectReadLock())
            assert client.get("/public/worlds?limit=1").status_code == 200
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_run_summary_uses_persisted_usage_and_never_infers_cost() -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    try:
        run = RUN_REGISTRY.create(
            backend="dfhack",
            model="agent-a",
            max_steps=20,
            ticks_per_step=100,
            seed_save="seed-a",
        )
        share = RUN_REGISTRY.create_share(run.run_id, scope=["live"])
        RUN_REGISTRY.set_summary(
            run.run_id,
            {
                "evaluation_protocol": "fort-eval-v1",
                "score_version": 5,
                "total_score": 75.0,
                "rubric": {"rubric_score": 72.0},
                "g7_gate": {"status": "unknown"},
                "usage": {"total_tokens": 321},
            },
        )

        response = TestClient(server.app).get(f"/public/runs/{share.token}/summary")

        assert response.status_code == 200
        payload = response.json()
        assert payload["run"]["run_id"] == run.run_id
        assert payload["summary"] == {
            "evaluation_protocol": "fort-eval-v1",
            "score_version": 5,
            "total_score": 75.0,
            "rubric": {"rubric_score": 72.0},
            "g7_gate": {"status": "unknown"},
        }
        assert payload["usage"] == {"total_tokens": 321}
        assert payload["cost"] is None
        assert payload["cost_status"] == "not_reported"
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_run_summary_reports_missing_usage_and_cost() -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    try:
        run = RUN_REGISTRY.create(
            backend="mock",
            model="agent-a",
            max_steps=1,
            ticks_per_step=1,
            seed_save="seed-a",
        )
        share = RUN_REGISTRY.create_share(run.run_id, scope=["live"])

        response = TestClient(server.app).get(f"/public/runs/{share.token}/summary")

        assert response.status_code == 200
        assert response.json()["usage"] is None
        assert response.json()["cost"] is None
        assert response.json()["cost_status"] == "not_reported"
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_run_preview_returns_bounded_recorded_screen(tmp_path, monkeypatch) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    monkeypatch.setattr(server, "ARTIFACTS_ROOT", tmp_path)
    try:
        run = RUN_REGISTRY.create(
            backend="mock",
            model="fake",
            max_steps=1,
            ticks_per_step=1,
        )
        share = RUN_REGISTRY.create_share(run.run_id, scope=["replay"])
        run_dir = tmp_path / run.run_id
        run_dir.mkdir()
        (run_dir / "trace.jsonl").write_text(
            '{"step":3,"screen_text":"recorded frame","map_snapshot":{"ok":true}}\n',
            encoding="utf-8",
        )

        response = TestClient(server.app).get(f"/public/runs/{share.token}/preview")

        assert response.status_code == 200
        assert response.json() == {
            "step": 3,
            "screen_text": "recorded frame",
            "screen_status": "recorded",
            "inspected_records": 1,
        }
    finally:
        RUN_REGISTRY.reset_for_tests()
