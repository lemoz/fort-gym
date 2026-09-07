"""Real public native snapshot through HTTP/helpers; not browser visual QA."""

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.eval.campaign_public import public_snapshot
from fort_gym.bench.run.campaign_feed import initialize_feed, read_feed

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "tests/fixtures/campaigns/live_reasoning_budget_20260907.json"


def capture():
    value = json.loads(CAPTURE.read_text())
    row = value["snapshot"]
    # Reproduce the native publisher's original serialization, not fixture formatting.
    raw = json.dumps(row, allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest() == value["source_snapshot_sha256"]
    projected = public_snapshot(row)
    # Preserve every captured field and its original digest. The newer reader
    # adds only unknown furniture observations, never retrospective measurements.
    added = {
        "current_furniture_item_records",
        "furniture_item_record_summaries",
        "furniture_item_record_scope",
    }
    assert {key: value for key, value in projected.items() if key not in added} == row
    assert projected["current_furniture_item_records"] == {
        "bed": None,
        "chair": None,
        "door": None,
        "table": None,
    }
    assert projected["furniture_item_record_summaries"] == {}
    assert projected["furniture_item_record_scope"] == {
        "source": "legacy job_metrics.goods IN_PLAY item records",
        "scan_completeness": "not_reported",
        "production_attribution": "unavailable",
        "ownership_and_accessibility": "not_reported",
    }
    return row


def captured_feed(tmp_path):
    row = capture()
    root = tmp_path / "public"
    initialize_feed(root)
    key = hashlib.sha256(row["campaign_id"].encode()).hexdigest()
    (root / f"campaign-{key}.json").write_text(json.dumps(row))
    return root, row


def test_actual_older_public_capture_cannot_roll_back_its_verified_terminal_result(
    tmp_path, monkeypatch
):
    from fort_gym.bench.api import server

    root, original = captured_feed(tmp_path)
    monkeypatch.setattr(
        server, "get_settings", lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(root))
    )
    with TestClient(server.app) as client:
        response = client.get("/public/campaign-feed")
        assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
        data = response.json()
        assert data["configured"] is True and data["published_snapshots"] == 14
        assert len(data["campaigns"]) == 14
        row = next(r for r in data["campaigns"] if r["campaign_id"] == original["campaign_id"])
        assert row["lifecycle"] == "finished" and row["freshness"] == "recorded"
        assert row["committed_steps"] == 83 and row["elapsed_ticks"] == 203339
        assert row["usage"]["total_tokens"] == 931832
        assert row["current_metrics"]["population"] == 9
        assert row["current_metrics"]["drink_stock"] == 25
        assert row["current_metrics"]["completed_workshops"] == 1
        assert row["cleanup_verified"] is True and row["checkpoint_verified"] is False
        assert row["segment_status"] == "failed"
        # The original captured feed is unchanged, including its unknown metrics.
        assert public_snapshot(read_feed(root)["campaigns"][0]) == public_snapshot(original)
        key = hashlib.sha256(original["campaign_id"].encode()).hexdigest()
        assert (root / f"campaign-{key}.json").read_bytes() == json.dumps(original).encode()
        assert original["current_metrics"]["population"] is None
        assert original["current_metrics"]["drink_stock"] is None
        assert row["functioning_fortress"] == "not_assessed"
        assert row["comparison_rankings_available"] is False
        assert client.get("/campaigns").status_code == 200
        assert client.get("/static/campaign-feed.js").status_code == 200


def test_captured_running_report_becomes_stale_without_becoming_a_game_loss(tmp_path):
    root, original = captured_feed(tmp_path)
    timestamp = datetime.fromisoformat(original["updated_at"])
    recent = read_feed(root, now=timestamp)["campaigns"][0]
    stale = read_feed(root, now=timestamp + timedelta(seconds=301))["campaigns"][0]
    assert recent["freshness"] == "recent_report" and stale["freshness"] == "stale"
    assert stale["updated_at"] == original["updated_at"]
    assert stale["lifecycle"] == "running"
    assert stale["fortress_collapse"] == "not_assessed"
    assert stale["elapsed_ticks"] == 5500


def test_live_condition_link_is_published_and_exact_digest_bound():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    subprocess.run(
        [
            node,
            "-e",
            """
const assert = require('node:assert/strict');
const helpers = require(process.argv[1]);
const row = JSON.parse(process.argv[2]);
assert.equal(helpers.configurationUrl(row),
 'https://github.com/lemoz/fort-gym/blob/ebf470d8364bf326cacd7b9985e6f5438d6d4f49/experiments/campaigns/local_native_qwen35_year_two_reasoning_budget_v1.json');
for (const configuration_sha256 of [undefined, null, '', 'a'.repeat(64)]) {
 assert.equal(helpers.configurationUrl({...row, configuration_sha256}), null);
}
assert.equal(helpers.configurationUrl({...row, code_revision:'../main'}), null);
assert.equal(helpers.number(row.current_metrics.population), 'Unknown');
assert.equal(helpers.number(row.current_metrics.drink_stock), 'Unknown');
assert.equal(helpers.number(row.current_metrics.completed_workshops), '0');
assert.equal(helpers.modelCost(row.usage), '$0 model API · self-hosted');
assert.match(helpers.duration(row.elapsed_ticks), /5,500 ticks/);
assert.match(helpers.stateLabel({...row, freshness:'recent_report'}), /Running segment/);
assert.match(helpers.stateLabel({...row, freshness:'stale'}), /current state unknown/);
""",
            str(ROOT / "web/static/campaign-feed.js"),
            json.dumps(capture()),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
