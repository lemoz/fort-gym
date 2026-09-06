from __future__ import annotations

import json

import pytest

from fort_gym.bench.eval.campaign import (
    TICKS_PER_YEAR,
    campaign_progress,
    read_campaign_progress,
)
from fort_gym.bench.eval.scoring import SCORE_VERSION
from fort_gym.bench.eval.summary import summarize


def row(ticks, step=0, **sample):
    return {
        "run_id": "campaign-run",
        "step": step,
        "tick_advance": {"ticks_advanced": ticks, **sample},
    }


@pytest.mark.parametrize(
    "ticks, reached", [(0, False), (403199, False), (403200, True), (806400, True)]
)
def test_first_anniversary_is_elapsed_time_not_a_stop(ticks, reached):
    report = campaign_progress([row(ticks)])
    assert report["year_two_reached"] is reached
    assert report["elapsed_ticks"] == ticks
    assert report["elapsed_years"] == ticks / TICKS_PER_YEAR
    assert report["functioning_fortress"] == "not_assessed"
    assert report["autonomous_gameplay"] == "not_assessed"


def test_calendar_rollover_does_not_mean_one_elapsed_year():
    report = campaign_progress(
        [row(200, start_year=30, start_tick=403100, end_year=31, end_tick=100)]
    )
    assert report["elapsed_ticks"] == 200
    assert report["year_two_reached"] is False


def test_partial_advance_counts_actual_time_even_when_request_failed():
    report = campaign_progress([row(10, requested=403200, ok=False)])
    assert report["elapsed_ticks"] == 10
    assert report["year_two_reached"] is False


@pytest.mark.parametrize("ticks", [None, True, False, -1, "403200", 403200.0])
def test_invalid_or_missing_samples_are_not_zero_time(ticks):
    report = campaign_progress([row(10), row(ticks, step=1)])
    assert report["observed_ticks"] == 10
    assert report["elapsed_ticks"] is None
    assert report["year_two_reached"] is None
    assert report["invalid_or_missing_samples"] == 1


@pytest.mark.parametrize("records", [[], [{"step": 0}], [{"step": 0, "tick_advance": []}]])
def test_no_evidence_does_not_assert_year_one(records):
    assert campaign_progress(records)["year_two_reached"] is None


def test_duplicate_steps_are_not_double_counted():
    report = campaign_progress([row(250000), row(250000)])
    assert report["observed_ticks"] == 250000
    assert report["elapsed_ticks"] is None


@pytest.mark.parametrize("steps", [[0, 2], [2, 1], [0, None], [0, True]])
def test_missing_or_out_of_order_steps_leave_duration_unknown(steps):
    report = campaign_progress([row(100, step=step) for step in steps])
    assert report["elapsed_ticks"] is None


def test_distinct_runs_cannot_be_combined_without_checkpoint_lineage():
    first, second = row(250000), row(250000, step=1)
    second["run_id"] = "different-fort"
    report = campaign_progress([first, second])
    assert report["mixed_run_ids"] is True
    assert report["elapsed_ticks"] is None


@pytest.mark.parametrize(
    "sample",
    [
        {"start_year": 30},
        {"start_year": 30, "start_tick": 403200, "end_year": 31, "end_tick": 10},
        {"start_year": 30, "start_tick": 100, "end_year": 30, "end_tick": 105},
        {"start_year": 30, "start_tick": 100, "end_year": 29, "end_tick": 110},
    ],
)
def test_inconsistent_calendar_is_unknown(sample):
    assert campaign_progress([row(10, **sample)])["elapsed_ticks"] is None


def test_calendar_discontinuity_is_not_silent_progress():
    report = campaign_progress(
        [
            row(10, start_year=30, start_tick=100, end_year=30, end_tick=110),
            row(10, step=1, start_year=30, start_tick=200, end_year=30, end_tick=210),
        ]
    )
    assert report["time_evidence"] == "incomplete"


def test_summary_persists_campaign_time_without_changing_score_duration(tmp_path):
    record = row(403200)
    record["score_version"] = SCORE_VERSION
    record["metrics"] = {"score_version": SCORE_VERSION, "score_duration_blocked": True}
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps(record) + "\n")
    result = summarize(trace)
    assert result.duration_ticks == 0
    assert result.campaign_progress["year_two_reached"] is True
    assert result.campaign_progress["autonomous_gameplay"] == "not_assessed"


def test_public_summary_exposes_persisted_campaign_diagnostics_only():
    from fort_gym.bench.api.server import _compact_public_summary

    report = campaign_progress([row(100)])
    result = _compact_public_summary({"campaign_progress": report, "private": "excluded"})
    assert result == {"campaign_progress": report}
    assert "campaign_progress" not in _compact_public_summary({"duration_ticks": 403200})


def test_public_endpoint_returns_campaign_progress(tmp_path):
    from fastapi.testclient import TestClient

    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RunRegistry

    registry = RunRegistry(db_path=tmp_path / "campaign.sqlite3")
    original = server.RUN_REGISTRY
    server.RUN_REGISTRY = registry
    try:
        run = registry.create(backend="dfhack", model="test-model", max_steps=1, ticks_per_step=1)
        share = registry.create_share(run.run_id, scope=["replay"])
        progress = campaign_progress([row(100)])
        registry.set_summary(run.run_id, {"campaign_progress": progress})
        response = TestClient(server.app).get(f"/public/runs/{share.token}/summary")
        assert response.status_code == 200
        assert response.json()["summary"]["campaign_progress"] == progress
    finally:
        server.RUN_REGISTRY = original


def test_reader_preserves_original_trace(tmp_path):
    trace = tmp_path / "trace.jsonl"
    content = json.dumps(row(403200)) + "\n"
    trace.write_text(content)
    assert read_campaign_progress(trace)["year_two_reached"] is True
    assert trace.read_text() == content


@pytest.mark.parametrize("content", ["broken\n", "[]\n", "null\n"])
def test_reader_does_not_silently_drop_invalid_rows(tmp_path, content):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(content)
    with pytest.raises((ValueError, TypeError), match="line 1"):
        read_campaign_progress(trace)


def test_cli_reports_existing_trace_without_launching_gameplay(tmp_path, capsys):
    from fort_gym.bench.cli import campaign_report

    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps(row(500)) + "\n")
    campaign_report(trace)
    assert json.loads(capsys.readouterr().out)["elapsed_ticks"] == 500


def test_registered_cli_campaign_report(tmp_path):
    from typer.testing import CliRunner

    from fort_gym.bench.cli import app

    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps(row(403200)) + "\n")
    result = CliRunner().invoke(app, ["campaign-report", str(trace)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["year_two_reached"] is True
