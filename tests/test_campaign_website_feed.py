"""Read-only campaign website coverage; no model or game runner is included."""

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


def feed(root, segment_id="first"):
    initialize_feed(root)
    return CampaignFeed(
        root,
        campaign_id="campaign",
        segment_id=segment_id,
        model="test-model",
        config={"condition_id": "test-condition", "models": ["test-model"]},
        revision="a" * 40,
    )


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
