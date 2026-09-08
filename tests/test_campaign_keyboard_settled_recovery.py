import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def test_settled_recovery_preserves_latest_progress_and_original_failure(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CHECKPOINT_RECOVERIES[0]
    source = json.loads(path.read_text())
    source["private_save"] = "secret-save"
    source["model_memory"] = "secret-memory"
    source["screen"] = "secret-screen"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["checkpoint_recoveries"][0]
    assert row["checkpoint_cursor"] == 216
    assert row["returned_model_decisions"] == 232
    assert row["elapsed_native_ticks"] == 47200
    assert row["usage"]["campaign_tokens"] == 7706555
    assert row["usage"]["all_attempt_tokens"] == 7775559
    assert row["usage"]["reported_charge_usd"] is None
    assert row["model_calls_to_recover"] == row["native_keys_to_recover"] == 0
    assert row["native_ticks_to_recover"] == 0
    assert row["fresh_native_reload_verified"] is row["teardown_verified"] is True
    assert row["new_discontinuity_created"] is False
    assert data["checkpoint_reviews"][0]["checkpoint_verified"] is False
    assert data["checkpoint_failures"][0]["newer_native_state_resumable"] is False
    assert data["live_tracking"] is False
    assert "secret-" not in json.dumps(data)


@pytest.mark.parametrize("field,value", [
    ("original_review", "unknown"),
    ("parent_checkpoint_sha256", "a" * 64),
    ("checkpoint_sha256", "bad"),
    ("snapshot_profile", "native_menu_preserving_save/v1"),
    ("independent_retained_evidence_audit_passed", 1),
    ("fresh_native_reload_verified", False),
    ("semantic_snapshot_verified", False),
    ("source_and_trace_bytes_unchanged", False),
    ("model_memory_and_usage_unchanged", False),
    ("inherited_discontinuity_unchanged", False),
    ("new_discontinuity_created", True),
    ("historical_failed_run_reclassified_as_success", True),
    ("teardown_verified", False),
    ("screen_unchanged", 0),
    ("checkpoint_cursor", 200),
    ("parent_checkpoint_cursor", 184),
    ("elapsed_native_ticks", 48000),
    ("cumulative_model_responses", 216),
    ("model_calls_to_recover", 1),
    ("native_keys_to_recover", 1),
    ("native_ticks_to_recover", False),
    ("campaign_tokens", 6984036),
    ("all_attempt_tokens", 7706555),
    ("reported_charge_usd", 0),
])
def test_settled_recovery_cannot_reset_usage_or_invent_proof(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CHECKPOINT_RECOVERIES[0]
    source = json.loads(path.read_text())
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)
