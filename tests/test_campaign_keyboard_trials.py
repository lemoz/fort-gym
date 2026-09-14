"""Prompt experiment publication keeps unsaved progress and measured usage distinct."""

import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_trials import prompt_trial
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / records.PROMPT_TRIALS[0]
    return path, json.loads(path.read_bytes())


def test_failed_prompt_experiment_follows_last_saved_checkpoint():
    data = records.keyboard_campaign_records()
    trial = data["prompt_trials"][-1]
    assert trial["status"] == "failed" and trial["teardown_verified"] is True
    assert {"kind": "prompt_trial", "id": trial["trial_id"]} in data["continuation_events"]
    assert trial["progress"]["parent_checkpoint_cursor"] == 775
    assert trial["progress"]["new_committed_unsaved_ticks"] == 614
    assert trial["progress"]["checkpointed_elapsed_ticks"] == 198600
    assert trial["progress"]["new_responses"] == 18
    assert trial["progress"]["committed_decisions"] == 17
    assert trial["progress"]["memory_clears"] == 0
    assert trial["usage"]["campaign_tokens"] == 29418907
    assert trial["usage"]["all_attempt_tokens"] == 29487911
    assert trial["usage"]["reported_charge_usd"] is None
    assert trial["counts"]["population"]["end"] == 12


@pytest.mark.parametrize("field,value", [
    ("status", "completed"), ("parent_record", "missing"), ("parent_checkpoint_cursor", 792),
    ("checkpointed_elapsed_ticks", 199214), ("new_responses", True), ("new_responses", 17),
    ("committed_trace_cursor", 793), ("uncommitted_ticks", None), ("uncommitted_ticks", 1),
    ("existing_loss_records", 0), ("existing_known_lost_ticks", 0),
    ("existing_lost_ticks_complete", True), ("campaign_tokens", 28911047),
    ("all_attempt_tokens", 29418907), ("new_tokens", 0), ("reported_charge_usd", 0),
    ("new_checkpoint_created", True), ("model_performance_improvement_established", True),
    ("matched_comparison", True), ("teardown_verified", False),
    ("memory_handoff_verified", False), ("prompt_receipts_verified", False),
    ("independent_audit_sha256", "invalid"), ("source_revision", "invalid"),
    ("new_committed_unsaved_ticks", 128001), ("memory_clears", 19),
    ("zero_tick_committed_decisions", 17), ("food_stock", 70),
])
def test_inconsistent_trial_rejected(evidence_root, field, value):
    path, value_before = publication(evidence_root)
    value_before[field] = value
    path.write_text(json.dumps(value_before))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_private_trial_fields_never_projected(evidence_root, monkeypatch):
    before = records.keyboard_campaign_records(evidence_root)
    path, value = publication(evidence_root)
    value["prompt"] = value["counts"]["memory"] = "private-sentinel"
    path.write_text(json.dumps(value))
    assert records.keyboard_campaign_records(evidence_root) == before
    monkeypatch.setattr(records, "PROMPT_TRIALS", ())
    monkeypatch.setattr(records, "MODAL_TRIALS", ())
    monkeypatch.setattr(records, "SAVED_SEGMENTS", ())
    monkeypatch.setattr(records, "COMPLETED_WINDOWS", ())
    monkeypatch.setattr(records, "PAUSED_WINDOWS", ())
    after = records.keyboard_campaign_records(evidence_root)
    assert after["prompt_trials"] == []
    assert after["continuation_events"] == [event for event in before["continuation_events"]
                                            if event["kind"] not in {"prompt_trial", "modal_trial", "saved_segment", "completed_window", "paused_window"}]


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "wrong_parent"])
def test_trial_file_and_parent_boundaries(evidence_root, kind):
    parents = records.keyboard_campaign_records(evidence_root)["resumed_windows"]
    path, value = publication(evidence_root)
    if kind == "missing":
        path.unlink()
    elif kind == "symlink":
        target = path.with_suffix(".retained")
        path.rename(target)
        path.symlink_to(target)
    elif kind == "oversized":
        value["padding"] = "x" * 65536
        path.write_text(json.dumps(value))
    else:
        parents = []
    with pytest.raises(ValueError):
        prompt_trial(evidence_root, records.PROMPT_TRIALS[0], parents)
