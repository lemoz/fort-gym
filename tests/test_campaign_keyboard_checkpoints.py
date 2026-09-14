import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def test_checkpoint_failure_keeps_lost_progress_and_usage_separate(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CHECKPOINT_FAILURES[0]
    value = json.loads(path.read_text())
    value["raw_screen"] = "private-screen"
    value["progress"]["native_path"] = "private-path"
    value["usage"]["account"] = "private-account"
    path.write_text(json.dumps(value))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["checkpoint_failures"][0]
    assert row["progress"]["retained_trace_cursor"] == 200
    assert row["progress"]["returned_model_responses"] == 200
    assert row["progress"]["new_accepted_model_responses"] == 16
    assert row["progress"]["last_resumable_checkpoint_cursor"] == 184
    assert row["progress"]["unsaved_new_native_ticks"] == 2000
    assert row["newer_native_state_resumable"] is False
    assert row["usage"]["new_tokens"] == 531913
    assert row["usage"]["all_attempt_tokens"] == 6534871
    assert row["usage"]["reported_charge_usd"] is None
    assert "private-" not in json.dumps(data)
    assert len(data["recoveries"]) == 2 and data["live_tracking"] is False


@pytest.mark.parametrize(
    "section,field,value",
    [
        (None, "checkpoint_verified", True),
        (None, "teardown_verified", False),
        (None, "independent_retained_evidence_audit_passed", 1),
        (None, "original_failed_window_preserved", False),
        (None, "terminal_reason", "fortress_collapse"),
        ("progress", "newer_native_state_resumable", True),
        ("progress", "new_native_save_matches_prior_checkpoint", False),
        ("progress", "retained_trace_cursor", 184),
        ("progress", "returned_model_responses", 201),
        ("progress", "new_accepted_model_responses", 0),
        ("progress", "last_resumable_checkpoint_cursor", 200),
        ("progress", "last_saved_elapsed_ticks", 46000),
        ("progress", "unsaved_new_native_ticks", False),
        ("usage", "new_tokens", 0),
        ("usage", "campaign_tokens", 5933954),
        ("usage", "all_attempt_tokens", 6002958),
        ("usage", "historical_failed_delivery_tokens", 0),
        ("usage", "reported_charge_usd", 0),
    ],
)
def test_save_failure_cannot_hide_loss_or_discard_usage(evidence_root, section, field, value):
    path = evidence_root / "experiments/evidence" / records.CHECKPOINT_FAILURES[0]
    source = json.loads(path.read_text())
    (source[section] if section else source)[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)
