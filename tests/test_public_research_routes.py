"""Focused coverage for public Fort Labs results and protocol routes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def _add_public_run(
    *,
    protocol: str,
    summary_protocol: str | None = None,
    scopes: list[str] | None = None,
    model: str = "agent-a",
    backend: str = "dfhack",
    status: str = "completed",
    complete_provenance: bool = True,
    replay_artifact: bool = True,
) -> str:
    from fort_gym.bench.run.storage import RUN_REGISTRY

    run = RUN_REGISTRY.create(
        backend=backend,
        model=model,
        max_steps=10,
        ticks_per_step=200,
        seed_save="fixed-seed-pilot",
        evaluation_protocol=protocol,
    )
    RUN_REGISTRY.create_share(run.run_id, scope=scopes or ["live", "replay", "export"])
    summary = {
        "evaluation_protocol": summary_protocol or protocol,
        "score_version": 5,
        "total_score": 10.0,
        "task_id": "easy_substrate_control",
        "task_version": "easy-v1",
        "seed_split": "fixed_seed_pilot",
        "mechanics_digest": "dfhack-mechanics-1",
        "observation_digest": "governed_structured_state_v1",
        "action_digest": "legal_semantic_dfhack_v1",
        "budget_digest": "max_steps_10_ticks_per_step_200",
        "model_digest": model,
        "prompt_digest": "prompt-1",
        "memory_digest": "window-20",
        "fort_gym_commit": "commit-easy",
        "df_version": "df-51.11",
        "evaluator_version": "fort-eval-1",
    }
    if not complete_provenance:
        summary.pop("prompt_digest")
    RUN_REGISTRY.set_summary(run.run_id, summary)
    if replay_artifact:
        assert run.trace_path is not None
        trace_path = Path(run.trace_path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text('{"step": 0}\n', encoding="utf-8")
    RUN_REGISTRY.set_status(run.run_id, status=status, ended_at=datetime.utcnow())
    return run.run_id


def test_public_results_filters_protocol_and_reports_full_eligibility() -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    try:
        valid_ids = [
            _add_public_run(protocol="fort-eval-easy-v1", model=f"agent-{index % 2}")
            for index in range(55)
        ]
        mismatched_id = _add_public_run(
            protocol="fort-eval-easy-v1", summary_protocol="fort-eval-hard-v1"
        )
        live_only_id = _add_public_run(
            protocol="fort-eval-easy-v1", scopes=["live"], model="agent-live-only"
        )
        _add_public_run(protocol="fort-eval-hard-v1", model="hard-agent")
        failed_id = _add_public_run(protocol="fort-eval-easy-v1", status="failed")
        fake_id = _add_public_run(protocol="fort-eval-easy-v1", backend="fake")
        missing_artifact_id = _add_public_run(
            protocol="fort-eval-easy-v1", replay_artifact=False
        )
        incomplete_id = _add_public_run(
            protocol="fort-eval-easy-v1", complete_provenance=False
        )

        conn = RUN_REGISTRY._ensure_conn()  # noqa: SLF001 - test-only provenance setup
        conn.executemany(
            "UPDATE runs SET git_sha = ? WHERE run_id = ?",
            [("commit-easy", run_id) for run_id in valid_ids]
            + [
                ("commit-easy", run_id)
                for run_id in (
                    mismatched_id,
                    live_only_id,
                    failed_id,
                    fake_id,
                    missing_artifact_id,
                    incomplete_id,
                )
            ],
        )
        conn.commit()

        with patch.object(
            RUN_REGISTRY,
            "list_public",
            side_effect=AssertionError("results must use the bounded protocol query"),
        ):
            response = TestClient(server.app).get(
                "/public/results", params={"evaluation_protocol": "fort-eval-easy-v1"}
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "experimental"
        assert payload["protocol"] == "fort-eval-easy-v1"
        assert payload["candidate_run_count"] == 61
        assert payload["eligible_run_count"] == 55
        assert payload["excluded_run_count"] == 6
        assert sum(
            result["run_count"]
            for group in payload["comparison_groups"]
            for result in group["model_results"]
        ) == 55
        assert all(
            group["comparability"]["evaluation_protocol"] == "fort-eval-easy-v1"
            for group in payload["comparison_groups"]
        )
        protocol = TestClient(server.app).get(
            "/public/protocols/fort-eval-easy-v1"
        ).json()
        assert set(protocol["comparability_fields"]).issubset(
            payload["comparability_fields"]
        )
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_results_requires_a_valid_protocol_query() -> None:
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    assert client.get("/public/results").status_code == 422
    assert client.get("/public/results?evaluation_protocol=not%20a%20protocol").status_code == 422
    assert client.get("/public/results?evaluation_protocol=unknown-v1").status_code == 404


def test_public_results_refuses_a_truncated_protocol_cohort() -> None:
    from fort_gym.bench.api import server

    with patch.object(server.RUN_REGISTRY, "list_public_for_protocol", return_value=([], True)):
        response = TestClient(server.app).get(
            "/public/results?evaluation_protocol=fort-eval-easy-v1"
        )
    assert response.status_code == 503


def test_historical_leaderboard_limit_is_bounded() -> None:
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    assert client.get("/public/leaderboard?limit=0").status_code == 422
    assert client.get("/public/leaderboard?limit=5001").status_code == 422


def test_public_protocol_catalog_is_allowlisted_and_uses_declared_status_wording() -> None:
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    catalog = client.get("/public/protocols")

    assert catalog.status_code == 200
    payload = catalog.json()
    assert [entry["slug"] for entry in payload] == [
        "fort-eval-easy-v1",
        "fort-eval-hard-v1",
        "fort-eval-discovery-v1",
    ]
    by_slug = {entry["slug"]: entry for entry in payload}
    assert "provisional p0/substrate" in by_slug["fort-eval-easy-v1"]["summary"].lower()
    assert "planned" in by_slug["fort-eval-hard-v1"]["result_status"].lower()
    assert "no results" in by_slug["fort-eval-hard-v1"]["result_status"].lower()
    assert "research-horizon" in by_slug["fort-eval-discovery-v1"]["result_status"].lower()
    assert "no results" in by_slug["fort-eval-discovery-v1"]["result_status"].lower()
    assert client.get("/public/protocols/not-a-real-protocol").status_code == 404
    assert client.get("/protocols/not-a-real-protocol").status_code == 404


def test_public_research_html_routes_are_registered() -> None:
    from fort_gym.bench.api.server import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert {"/results", "/protocols", "/protocols/{slug}"}.issubset(paths)
