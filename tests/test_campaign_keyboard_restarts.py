import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def test_restart_preserves_branch_loss_and_full_usage_without_content(evidence_root):
    path = evidence_root / "experiments/evidence" / records.RESTARTS[0]
    source = json.loads(path.read_text())
    source["private_prompt"] = "secret-prompt"
    source["progress"]["screen"] = "secret-screen"
    source["usage"]["account"] = "secret-account"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["restarts"][0]
    assert row["progress"]["checkpoint_cursor"] == 200
    assert row["progress"]["cumulative_model_responses"] == 216
    assert row["progress"]["retained_elapsed_ticks"] == 46000
    assert row["progress"]["discarded_native_ticks"] == 2000
    assert row["usage"]["campaign_tokens"] == 6984036
    assert row["usage"]["all_attempt_tokens"] == 7053040
    assert row["usage"]["lost_tail_tokens_retained"] == 531913
    assert row["usage"]["reported_charge_usd"] is None
    assert row["uninterrupted_campaign"] is row["historical_tail_replayed"] is False
    assert row["native_checkpoint_verified"] is row["teardown_verified"] is True
    assert row["independent_comparison_attempt"] is False
    assert row["fortress_success"] == "not_assessed_in_public_operational_summary"
    assert data["checkpoint_failures"][0]["newer_native_state_resumable"] is False
    assert data["live_tracking"] is False
    assert "secret-" not in json.dumps(data)


@pytest.mark.parametrize("section,field,value", [
    (None, "original_failure", "unknown"),
    (None, "parent_checkpoint_sha256", "a" * 64),
    (None, "checkpoint_sha256", "invalid"),
    (None, "independent_retained_evidence_audit_passed", 1),
    (None, "native_checkpoint_verified", False),
    (None, "source_checkpoint_and_failed_window_unchanged", False),
    (None, "model_memory_restored_from_checkpoint", False),
    (None, "teardown_verified", False),
    (None, "uninterrupted_campaign", True),
    (None, "historical_tail_replayed", True),
    (None, "independent_comparison_attempt", True),
    ("progress", "restored_checkpoint_cursor", 200),
    ("progress", "checkpoint_cursor", 216),
    ("progress", "new_model_responses", 0),
    ("progress", "new_accepted_decisions", 17),
    ("progress", "cumulative_model_responses", 200),
    ("progress", "new_elapsed_ticks", True),
    ("progress", "retained_elapsed_ticks", 48000),
    ("progress", "discarded_native_ticks", 0),
    ("usage", "new_tokens", 0),
    ("usage", "campaign_tokens", 6465867),
    ("usage", "all_attempt_tokens", 6984036),
    ("usage", "lost_tail_tokens_retained", 0),
    ("usage", "historical_failed_delivery_tokens", 0),
    ("usage", "reported_charge_usd", 0),
])
def test_restart_cannot_hide_loss_or_reset_usage(evidence_root, section, field, value):
    path = evidence_root / "experiments/evidence" / records.RESTARTS[0]
    source = json.loads(path.read_text())
    (source[section] if section else source)[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)
