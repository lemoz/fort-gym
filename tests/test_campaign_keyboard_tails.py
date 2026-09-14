"""Published continuation recovery preserves the lost-branch response offset."""

import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def test_tail_records_bind_recovery_without_resetting_usage_or_exposing_content(evidence_root):
    for filename in (records.TAIL_INTERRUPTION, *records.TAIL_RECOVERIES):
        path = evidence_root / "experiments/evidence" / filename
        source = json.loads(path.read_text())
        source["private_screen"] = "secret-screen"
        source["model_memory"] = "secret-memory"
        path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    assert "secret-" not in json.dumps(data)
    failure, recovery = data["tail_interruptions"][0], data["tail_recoveries"][0]
    assert failure["progress"]["trace_cursor"] == 310
    assert failure["progress"]["cumulative_model_responses"] == 327
    assert failure["progress"]["latest_verified_checkpoint_cursor"] == 296
    assert failure["recovery_requires_reconciliation"] is True
    assert recovery["checkpoint_cursor"] == 311
    assert recovery["returned_model_decisions"] == 327
    assert recovery["elapsed_native_ticks"] == 65600
    assert recovery["fresh_native_checkpoint_reload_verified"] is True
    assert (
        recovery["usage"]["all_attempt_tokens"]
        == failure["usage"]["all_attempt_tokens"]
        == 10765958
    )
    assert recovery["usage"]["reported_charge_usd"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("parent_record", "unknown"),
        ("parent_checkpoint_sha256", "0" * 64),
        ("trace_cursor", 311),
        ("cumulative_model_responses", 311),
        ("new_returned_model_decisions", 14),
        ("new_elapsed_ticks", False),
        ("latest_verified_checkpoint_cursor", 310),
        ("trace_elapsed_ticks", 63600),
        ("campaign_tokens", 10215904),
        ("all_attempt_tokens", 10696954),
        ("reported_charge_usd", 0),
        ("forensic_save_is_resumable_checkpoint", True),
        ("historical_failed_run_reclassified_as_success", True),
        ("inherited_discontinuity_unchanged", False),
        ("teardown_verified", False),
    ],
)
def test_tail_cannot_invent_checkpoint_or_discard_usage(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.TAIL_INTERRUPTION
    source = json.loads(path.read_text())
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_interruption", "unknown"),
        ("parent_checkpoint_sha256", "0" * 64),
        ("checkpoint_sha256", "bad"),
        ("checkpoint_cursor", 327),
        ("returned_model_decisions", 311),
        ("elapsed_native_ticks", 63600),
        ("native_keys_to_recover", 1),
        ("model_calls_to_recover", False),
        ("native_ticks_to_recover", 1),
        ("campaign_tokens", 10215904),
        ("reported_charge_usd", 0),
        ("fresh_native_checkpoint_reload_verified", False),
        ("inherited_discontinuity_unchanged", False),
        ("new_discontinuity_created", True),
        ("original_failed_run_reclassified_as_success", True),
        ("teardown_verified", False),
    ],
)
def test_recovery_cannot_relabel_failures_or_claim_new_play(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.TAIL_RECOVERIES[0]
    source = json.loads(path.read_text())
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)
