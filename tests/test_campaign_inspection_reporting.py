"""Synthetic reporting fixtures only, not native/model acceptance evidence."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.agent.governed_llm import GOVERNED_ACTION_TYPES
from fort_gym.bench.eval.campaign_public import public_snapshot
from fort_gym.bench.run.campaign_config import load_segment_config
from fort_gym.bench.run.campaign_feed import read_feed
from scripts.campaign_profile import report_segment
from tests.test_campaign_feed import REVISION, feed
from tests.test_campaign_profile import profile, row
from tests.test_campaign_segment import CONFIG, MODEL


def inspection(step=0, accepted=True):
    result = row(step=step, start=0, end=0, accepted=accepted, kind="VIEW")
    result["action"]["params"] = {"origin": [3, 8, 1], "size": [4, 4]}
    return result


def test_inspection_outcomes_are_counted_without_world_progress_or_new_runtime_controls():
    report = profile([inspection(0), inspection(1, False), inspection(2, None)])
    assert report["actions"]["by_type"] == {"VIEW": {"accepted": 1, "rejected": 1, "unknown": 1}}
    assert report["actions"]["committed_rows"] == 3
    assert report["progress"]["elapsed_ticks"] == 0
    assert report["metrics"]["completed_workshops"]["change"] == 0
    assert report["functioning_fortress"] == "not_assessed"
    assert "VIEW" not in GOVERNED_ACTION_TYPES


def test_repeated_inspection_is_not_a_changed_command_after_rejection():
    rows = [inspection(0, False), inspection(1, False), row(2, 0, 0, kind="WAIT")]
    assert profile(rows)["actions"]["changed_command_after_rejection"] == 1


@pytest.mark.parametrize("kind", ["view", "PAN", "PRIVATE"])
def test_unrecognized_controls_are_still_unknown(kind):
    assert profile([row(kind=kind)])["actions"]["by_type"] == {
        "UNKNOWN": {"accepted": 1, "rejected": 0, "unknown": 0}
    }


def test_inspection_report_reaches_http_without_exporting_parameters(tmp_path, monkeypatch):
    from fort_gym.bench.api import server

    publisher = feed(tmp_path / "public")
    publisher.start()
    output = tmp_path / "segment"
    (output / "campaign").mkdir(parents=True)
    rows = [inspection(0), inspection(1, False)]
    rows[0]["action"]["params"]["private_note"] = "PRIVATE-GAME-CONTENT"
    segment = {
        **publisher.identity,
        "schema_version": "fortgym.campaign-segment/v1",
        "configuration": load_segment_config(CONFIG, MODEL),
        "status": "bounded_segment_complete",
        "native_final": rows[-1]["state_after_advance"],
    }
    sources = {
        output / "campaign-segment.json": json.dumps(segment),
        output
        / "result.json": json.dumps(
            {
                "schema_version": "fortgym.isolated-experiment-runtime/v1",
                "code_revision": REVISION,
                "cleanup_verified": True,
                "native_load_verified": True,
            }
        ),
        output / "campaign/trace.jsonl": "".join(json.dumps(item) + "\n" for item in rows),
    }
    for path, content in sources.items():
        path.write_text(content)
    report = report_segment(output)
    publisher.finish(output, report)
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(publisher.root)),
    )
    response = TestClient(server.app).get("/public/campaign-feed")
    assert response.status_code == 200
    result = next(
        item for item in response.json()["campaigns"] if item["campaign_id"] == "campaign"
    )
    assert result["actions"]["by_type"]["VIEW"] == {"accepted": 1, "rejected": 1, "unknown": 0}
    assert result["elapsed_ticks"] == 0
    assert result["functioning_fortress"] == "not_assessed"
    assert "PRIVATE-GAME-CONTENT" not in json.dumps(result)
    assert "params" not in json.dumps(result["actions"])
    assert public_snapshot(public_snapshot(result)) == public_snapshot(result)
    assert all(path.read_text() == content for path, content in sources.items())


def test_old_unknown_aggregate_is_not_reinterpreted_as_inspection(tmp_path):
    publisher = feed(tmp_path / "public")
    publisher.start()
    record = read_feed(publisher.root)["campaigns"][0]
    record["actions"] = {"by_type": {"UNKNOWN": {"accepted": 3, "rejected": 0, "unknown": 0}}}
    assert public_snapshot(record)["actions"]["by_type"] == record["actions"]["by_type"]
