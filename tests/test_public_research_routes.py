"""Focused coverage for public Fort Labs results and protocol routes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


P1_PROTOCOL = "fort-eval-easy-p1-g7-v3"


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
    public_eligibility: str = "eligible",
    public_label: str = "Fable",
    task_verdict: str | None = None,
    g7_status: str | None = "fail",
    g7_evidence_status: str = "pass",
    integrity_status: str = "pass",
    integrity_terminal_reason: dict | None = None,
    model_digest: str | None = None,
) -> str:
    from fort_gym.bench.run.storage import RUN_REGISTRY

    p1 = protocol == P1_PROTOCOL
    run = RUN_REGISTRY.create(
        backend=backend,
        model=model,
        max_steps=200 if p1 else 10,
        ticks_per_step=2500 if p1 else 200,
        seed_save="seed_region3_fresh" if p1 else "fixed-seed-pilot",
        evaluation_protocol=protocol,
    )
    RUN_REGISTRY.create_share(run.run_id, scope=scopes or ["live", "replay", "export"])
    summary = {
        "evaluation_protocol": summary_protocol or protocol,
        "score_version": 5,
        "total_score": 10.0,
        "task_id": "g7_survival" if p1 else "easy_substrate_control",
        "task_version": "g7-v3" if p1 else "easy-v1",
        "seed_split": "fixed_seed_pilot",
        "mechanics_digest": (
            "df-51.11+governed-semantic-dfhack-v1" if p1 else "dfhack-mechanics-1"
        ),
        "observation_digest": (
            "governed_structured_state_v1+fort_minimap_vision_v1"
            if p1
            else "governed_structured_state_v1"
        ),
        "action_digest": "legal_semantic_dfhack_v1",
        "budget_digest": (
            "max_steps_200_ticks_per_step_2500"
            if p1
            else "max_steps_10_ticks_per_step_200"
        ),
        "model_digest": model_digest or model,
        "prompt_digest": "prompt-1",
        "memory_digest": "memory_off" if p1 else "window-20",
        "fort_gym_commit": "commit-easy",
        "df_version": "df-51.11",
        "evaluator_version": "score-v5+g7-v3" if p1 else "fort-eval-1",
        "public_eligibility": public_eligibility,
        "public_label": public_label,
        "integrity_attestation": {
            "status": integrity_status,
            "terminal_reason": integrity_terminal_reason,
        },
    }
    if g7_status is not None:
        summary["g7"] = {
            "status": g7_status,
            "criteria": {"evidence": {"status": g7_evidence_status}},
        }
    if task_verdict is not None:
        summary["task_verdict"] = task_verdict
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
            _add_public_run(
                protocol=P1_PROTOCOL,
                model=f"agent-{index % 2}",
                model_digest=(
                    "anthropic/claude-fable-5"
                    if index < 30
                    else "openai/gpt-5.6-sol"
                ),
                public_label="Claude Fable 5" if index < 30 else "GPT-5.6 Sol",
                g7_status="fail" if index < 30 else "unknown",
            )
            for index in range(55)
        ]
        mismatched_id = _add_public_run(
            protocol=P1_PROTOCOL, summary_protocol="fort-eval-hard-v1"
        )
        live_only_id = _add_public_run(
            protocol=P1_PROTOCOL, scopes=["live"], model="agent-live-only"
        )
        _add_public_run(protocol="fort-eval-hard-v1", model="hard-agent")
        failed_id = _add_public_run(
            protocol=P1_PROTOCOL,
            status="failed",
            model_digest="anthropic/claude-fable-5",
            public_label="Claude Fable 5",
            g7_status="fail",
        )
        fake_id = _add_public_run(protocol=P1_PROTOCOL, backend="fake")
        missing_artifact_id = _add_public_run(
            protocol=P1_PROTOCOL, replay_artifact=False
        )
        incomplete_id = _add_public_run(
            protocol=P1_PROTOCOL, complete_provenance=False
        )
        ineligible_id = _add_public_run(
            protocol=P1_PROTOCOL, public_eligibility="ineligible"
        )
        integrity_failed_id = _add_public_run(
            protocol=P1_PROTOCOL,
            integrity_status="fail",
            integrity_terminal_reason={"code": "tick_request_attestation_failed"},
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
                    ineligible_id,
                    integrity_failed_id,
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
                "/public/results", params={"evaluation_protocol": P1_PROTOCOL}
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "experimental"
        assert payload["protocol"] == P1_PROTOCOL
        assert payload["publication_stage"] == "P1 discovery"
        assert payload["candidate_run_count"] == 63
        assert payload["eligible_run_count"] == 56
        assert payload["excluded_run_count"] == 7
        assert sum(
            result["run_count"]
            for group in payload["comparison_groups"]
            for result in group["model_results"]
        ) == 56
        assert all(
            group["comparability"]["evaluation_protocol"] == P1_PROTOCOL
            for group in payload["comparison_groups"]
        )
        model_results = [
            result
            for group in payload["comparison_groups"]
            for result in group["model_results"]
        ]
        assert {
            (result["model_digest"], result["public_label"])
            for result in model_results
        } == {
            ("anthropic/claude-fable-5", "Claude Fable 5"),
            ("openai/gpt-5.6-sol", "GPT-5.6 Sol"),
        }
        by_label = {result["public_label"]: result for result in model_results}
        assert by_label["Claude Fable 5"]["task_verdict"] == "fail"
        assert by_label["Claude Fable 5"]["g7_outcomes"] == {"fail": 31}
        assert by_label["GPT-5.6 Sol"]["task_verdict"] == "unknown"
        assert by_label["GPT-5.6 Sol"]["g7_outcomes"] == {"unknown": 25}
        protocol = TestClient(server.app).get(
            f"/public/protocols/{P1_PROTOCOL}"
        ).json()
        assert set(protocol["comparability_fields"]).issubset(
            payload["comparability_fields"]
        )
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_results_keeps_legacy_p0_independent_of_p1_eligibility() -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    try:
        run_id = _add_public_run(
            protocol="fort-eval-easy-v1",
            public_eligibility="ineligible",
            g7_status=None,
        )
        conn = RUN_REGISTRY._ensure_conn()  # noqa: SLF001 - test-only provenance setup
        conn.execute("UPDATE runs SET git_sha = ? WHERE run_id = ?", ("commit-easy", run_id))
        conn.commit()

        response = TestClient(server.app).get(
            "/public/results?evaluation_protocol=fort-eval-easy-v1"
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["eligible_run_count"] == 1
        result = payload["comparison_groups"][0]["model_results"][0]
        assert result["model"] == "agent-a"
        assert "public_label" not in result
        assert "g7_outcomes" not in result
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
            f"/public/results?evaluation_protocol={P1_PROTOCOL}"
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
        P1_PROTOCOL,
        "fort-eval-hard-v1",
        "fort-eval-discovery-v1",
    ]
    by_slug = {entry["slug"]: entry for entry in payload}
    assert "provisional p0/substrate" in by_slug["fort-eval-easy-v1"]["summary"].lower()
    assert "p1" in by_slug[P1_PROTOCOL]["result_status"].lower()
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
