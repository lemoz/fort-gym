"""Public projection tests use synthetic state and fake policies, not model evidence."""

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.run.campaign_feed import (
    CampaignFeed,
    initialize_feed,
    public_snapshot,
    read_feed,
)
from scripts.campaign_profile import report_segment
from scripts.campaign_segment import load_segment_config, run_segment
from tests.test_campaign_loop import TestEnvironment
from tests.test_campaign_segment import CONFIG, MODEL, SegmentAgent

REVISION = "a" * 40


def feed(root, segment_id="first"):
    initialize_feed(root)
    return CampaignFeed(
        root,
        campaign_id="campaign",
        segment_id=segment_id,
        model=MODEL,
        config=load_segment_config(CONFIG, MODEL),
        revision=REVISION,
    )


def play(output, publisher, **kwargs):
    output.mkdir()
    environment = kwargs.pop("environment", TestEnvironment())
    environment.state["campaign_observation_quality"] = {
        "schema_version": "fortgym.campaign-observation-quality/v1",
        "native_population_resources_validated": True,
    }
    result = run_segment(
        agent=kwargs.pop("agent", SegmentAgent()),
        environment=environment,
        snapshotter=environment,
        output=output,
        config=load_segment_config(CONFIG, MODEL),
        campaign_id="campaign",
        model=MODEL,
        revision=REVISION,
        on_progress=publisher.progress,
        **kwargs,
    )
    return result


def finish(output, publisher):
    (output / "result.json").write_text(
        json.dumps(
            {
                "schema_version": "fortgym.isolated-experiment-runtime/v1",
                "code_revision": REVISION,
                "cleanup_verified": True,
                "native_load_verified": True,
                "private_path": "PRIVATE-RUNTIME",
            }
        )
    )
    publisher.finish(output, report_segment(output))


def test_segment_reports_committed_boundaries_then_terminal_teardown(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    assert read_feed(publisher.root)["campaigns"][0]["lifecycle"] == "starting"
    output = tmp_path / "first"
    result = play(output, publisher)
    current = read_feed(publisher.root)["campaigns"][0]
    assert result["status"] == "bounded_segment_complete"
    assert current["lifecycle"] == "awaiting_teardown" and current["cleanup_verified"] is None
    assert current["elapsed_ticks"] == 600 and current["committed_steps"] == 3
    assert current["current_metrics"]["population"] == 7 and current["checkpoint_verified"]
    finish(output, publisher)
    terminal = read_feed(publisher.root)["campaigns"][0]
    assert terminal["lifecycle"] == "finished" and terminal["cleanup_verified"] is True
    assert terminal["segment_status"] == "bounded_segment_complete"
    assert terminal["metric_summaries"]["population"]["start"] == 7
    assert terminal["usage"]["reported_model_cost_usd"] == "3E-13"
    assert terminal["actions"]["committed_rows"] == 3
    assert terminal["actions"]["accepted"] == 3
    assert terminal["actions"]["by_type"]["WAIT"] == {"accepted": 3, "rejected": 0, "unknown": 0}
    assert (
        terminal["source_sha256"]["campaign-segment.json"]
        == hashlib.sha256((output / "campaign-segment.json").read_bytes()).hexdigest()
    )
    assert "PRIVATE-RUNTIME" not in json.dumps(terminal)
    assert len(list((publisher.root / "recorded").glob("*.json"))) == 1


@pytest.mark.parametrize("before_pause", [0, 2])
def test_output_pause_is_published_as_accounted_non_gameplay(tmp_path, before_pause):
    from tests.test_campaign_output_pause import PausingAgent

    publisher = feed(tmp_path / "public")
    publisher.start()
    output = tmp_path / "first"
    result = play(output, publisher, agent=PausingAgent(before_pause + 1))
    assert result["status"] == "inference_output_limited_pause"
    assert result.get("public_feed_error") is None
    current = read_feed(publisher.root)["campaigns"][0]
    assert current["segment_status"] == "inference_output_limited_pause"
    assert current["elapsed_ticks"] == before_pause * 200
    assert current["failure_kind"] == "none"
    assert current["checkpoint_verified"] is True
    finish(output, publisher)
    terminal = read_feed(publisher.root)["campaigns"][0]
    assert terminal["lifecycle"] == "finished" and terminal["cleanup_verified"] is True
    assert terminal["segment_status"] == "inference_output_limited_pause"
    assert terminal["actions"]["committed_rows"] == before_pause
    assert terminal["usage"]["returned_responses"] == before_pause + 1
    assert terminal["usage"]["accounted_responses"] == before_pause + 1
    assert terminal["functioning_fortress"] == terminal["fortress_collapse"] == "not_assessed"
    assert "synthetic accounted output limit" not in json.dumps(terminal)


def test_continuation_updates_one_fortress_without_adding_cumulative_costs(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    first = play(tmp_path / "first", publisher)
    finish(tmp_path / "first", publisher)
    second = feed(publisher.root, "second")
    with pytest.raises(ValueError, match="continuation"):
        second.start()
    second.start(resume=True)
    checkpoint = Path(first["checkpoint"])
    environment = TestEnvironment()
    environment.state = json.loads((checkpoint / "game/world.sav").read_text())
    resumed = play(
        tmp_path / "second",
        second,
        environment=environment,
        checkpoint=checkpoint,
        latest_usage=tmp_path / "first/campaign/usage.jsonl",
    )
    assert resumed["next_step"] == 6
    assert read_feed(second.root)["campaigns"][0]["elapsed_ticks"] == 1200
    finish(tmp_path / "second", second)
    records = read_feed(second.root)["campaigns"]
    assert len(records) == 1 and records[0]["segment_id"] == "second"
    assert records[0]["usage"]["reported_model_cost_usd"] == "6E-13"
    assert records[0]["committed_steps"] == 6
    assert len(list((second.root / "recorded").glob("*.json"))) == 2


def test_public_projection_strips_private_nested_text_and_preserves_unknowns(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    record = read_feed(publisher.root)["campaigns"][0]
    record.update(
        secret="PRIVATE",
        functioning_fortress="success",
        comparison_rankings_available=True,
        current_metrics={"population": 0, "food_stock": True, "agent_memory": "PRIVATE"},
        usage={"total_cost_usd": "0.003462525", "api_key": "PRIVATE"},
        metric_summaries={"population": {"start": 7, "end": 0, "evidence": "PRIVATE"}},
        source_sha256={"/PRIVATE/path": "not-a-digest"},
        actions={
            "accepted": 0,
            "rejected": True,
            "agent_memory": "PRIVATE",
            "by_type": {"LABOR": {"accepted": 0, "params": "PRIVATE"}, "PRIVATE": {"accepted": 1}},
        },
    )
    public = public_snapshot(record)
    assert "PRIVATE" not in json.dumps(public)
    assert (
        public["current_metrics"]["population"] == 0
        and public["current_metrics"]["food_stock"] is None
    )
    assert public["metric_summaries"]["population"]["change"] == -7
    assert public["usage"]["reported_model_cost_usd"] == "0.003462525"
    assert public["actions"]["accepted"] == 0 and public["actions"]["rejected"] is None
    assert public["actions"]["by_type"] == {
        "LABOR": {"accepted": 0, "rejected": None, "unknown": None}
    }
    assert (
        public["functioning_fortress"] == "not_assessed"
        and not public["comparison_rankings_available"]
    )
    assert public_snapshot(public) == public


def test_timeline_is_bounded_keeps_endpoints_and_does_not_fill_missing_values(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    record = read_feed(publisher.root)["campaigns"][0]
    record["timeline"] = [
        {"boundary_index": i, "year": 30, "year_tick": i, "metrics": {"population": None}}
        for i in range(500)
    ]
    public = public_snapshot(record)
    assert len(public["timeline"]) == 128 and public["timeline_sampled"]
    assert public["timeline"][0]["boundary_index"] == 0
    assert public["timeline"][-1]["boundary_index"] == 499
    assert all(row["metrics"]["population"] is None for row in public["timeline"])


def test_stale_reports_do_not_claim_current_activity_or_gameplay_failure(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    update = read_feed(publisher.root)["campaigns"][0]
    timestamp = datetime.fromisoformat(update["updated_at"])
    stale = read_feed(publisher.root, now=timestamp + timedelta(seconds=301))["campaigns"][0]
    assert stale["freshness"] == "stale" and stale["fortress_collapse"] == "not_assessed"
    future = read_feed(publisher.root, now=timestamp - timedelta(seconds=10))["campaigns"][0]
    assert future["freshness"] == "clock_mismatch"


def test_feed_failure_does_not_change_gameplay_or_hide_reporting_fault(tmp_path):
    publisher = SimpleNamespace(
        progress=lambda *args: (_ for _ in ()).throw(OSError("private path"))
    )
    result = play(tmp_path / "first", publisher)
    assert result["status"] == "bounded_segment_complete" and result["segment_committed_steps"] == 3
    assert result["progress_reporting_error_type"] == "OSError"


def test_missing_terminal_profile_does_not_relabel_old_counts_as_terminal(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    play(tmp_path / "first", publisher)
    publisher.finish(tmp_path / "first", None)
    terminal = read_feed(publisher.root)["campaigns"][0]
    assert terminal["lifecycle"] == "awaiting_teardown" and terminal["cleanup_verified"] is None
    assert terminal["current_metrics"]["population"] is None
    assert terminal["usage"]["reported_model_cost_usd"] is None
    assert terminal["elapsed_ticks"] == 600


def test_publication_requires_a_dedicated_directory_and_rejects_symlinks(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    (private / "agent.json").write_text('{"secret":"private"}')
    with pytest.raises(ValueError, match="empty dedicated"):
        initialize_feed(private)
    publisher = feed(tmp_path / "public")
    publisher.start()
    publisher.path.unlink()
    publisher.path.symlink_to(private / "agent.json")
    with pytest.raises((ValueError, OSError)):
        read_feed(publisher.root)


def test_http_distinguishes_not_connected_from_unavailable(tmp_path, monkeypatch):
    from fort_gym.bench.api import server

    monkeypatch.setattr(
        server, "get_settings", lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=None)
    )
    client = TestClient(server.app)
    response = client.get("/public/campaign-feed")
    assert response.status_code == 200 and response.json()["configured"] is False
    assert "no-store" in response.headers["cache-control"]
    publisher = feed(tmp_path / "public")
    publisher.start()
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(publisher.root)),
    )
    response = client.get("/public/campaign-feed")
    assert response.status_code == 200
    assert any(row["campaign_id"] == "campaign" for row in response.json()["campaigns"])
    page = client.get("/campaigns")
    assert page.status_code == 200 and 'id="campaign-condition-filter"' in page.text
    assert client.get("/static/campaign-feed.js").status_code == 200
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(tmp_path / "missing-private")),
    )
    response = client.get("/public/campaign-feed")
    assert response.status_code == 503 and response.json() == {
        "detail": "Campaign tracking is unavailable"
    }


def test_frontend_unknowns_stale_status_filter_and_refresh_failure(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    publisher = feed(tmp_path / "public")
    publisher.start()
    data = read_feed(publisher.root)
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/campaign_feed_dom.cjs"),
            str(root / "web/static/campaign-feed.js"),
            json.dumps(data),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_late_prior_segment_cannot_overwrite_a_resumed_campaign_report(tmp_path):
    first = feed(tmp_path / "public")
    first.start()
    second = feed(first.root, "second")
    second.start(resume=True)
    with pytest.raises(ValueError, match="different campaign segment"):
        first.progress({"status": "started"}, None, None)
    assert read_feed(first.root)["campaigns"][0]["segment_id"] == "second"


def test_contended_public_writer_does_not_block_gameplay(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    with publisher._lock():
        result = play(tmp_path / "first", publisher)
    assert result["status"] == "bounded_segment_complete"
    assert result["progress_reporting_error_type"] == "BlockingIOError"


@pytest.mark.parametrize("cleanup", [True, False])
def test_parent_reports_runtime_failure_only_after_its_teardown_receipt(
    tmp_path, monkeypatch, cleanup
):
    from scripts import campaign_segment

    output = tmp_path / "failed"
    public = tmp_path / "public"
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "checkpoint.json").write_text("{}")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    monkeypatch.setattr(
        campaign_segment.sys,
        "argv",
        [
            "campaign_segment",
            "--config",
            str(CONFIG),
            "--model",
            MODEL,
            "--campaign-id",
            "campaign",
            "--output",
            str(output),
            "--source",
            str(tmp_path / "source"),
            "--checkpoint",
            str(checkpoint),
            "--latest-usage",
            str(tmp_path / "usage.jsonl"),
            "--public-campaign-dir",
            str(public),
        ],
    )
    monkeypatch.setattr(
        campaign_segment.subprocess,
        "check_output",
        lambda args, **kwargs: REVISION if args[1] == "rev-parse" else "",
    )

    def isolated(**kwargs):
        assert read_feed(public)["campaigns"][0]["lifecycle"] == "starting"
        output.mkdir()
        (output / "result.json").write_text(
            json.dumps(
                {
                    "schema_version": "fortgym.isolated-experiment-runtime/v1",
                    "code_revision": REVISION,
                    "cleanup_verified": cleanup,
                    "error_type": "TimeoutError",
                    "error": "PRIVATE-DIAGNOSTIC",
                }
            )
        )
        raise TimeoutError("PRIVATE-DIAGNOSTIC")

    monkeypatch.setattr(campaign_segment, "run_isolated", isolated)
    with pytest.raises(TimeoutError, match="PRIVATE-DIAGNOSTIC"):
        campaign_segment.main()
    record = read_feed(public)["campaigns"][0]
    assert record["lifecycle"] == ("finished" if cleanup else "awaiting_teardown")
    assert record["segment_status"] == "failed" and record["failure_kind"] == "runtime"
    assert record["cleanup_verified"] is cleanup
    assert "PRIVATE-DIAGNOSTIC" not in json.dumps(record)
