import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def test_continuation_preserves_parent_usage_and_only_exports_operational_fields(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[0]
    source = json.loads(path.read_text())
    source["model_memory"] = source["screen"] = "private-content"
    source["checkpoints"][0]["native_save"] = "private-save"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["continuations"][0]
    assert row["checkpoint_cursor"] == 296
    assert row["progress"]["cumulative_model_responses"] == 312
    assert row["progress"]["new_model_calls"] == 64
    assert row["progress"]["retained_elapsed_ticks"] == 63600
    assert row["usage"]["all_attempt_tokens"] == 10284908
    assert row["usage"]["reported_charge_usd"] is None
    assert row["final_checkpoint_fresh_reload_verified"] is False
    assert row["new_restart_performed"] is row["uninterrupted_campaign"] is False
    assert row["teardown_verified"] is True
    assert data["checkpoint_recoveries"][-1]["checkpoint_cursor"] == 232
    assert data["checkpoint_failures"][0]["newer_native_state_resumable"] is False
    assert "private-" not in json.dumps(data)


@pytest.mark.parametrize("field,value", [
    ("parent_record", "missing"), ("parent_checkpoint_sha256", "a" * 64),
    ("parent_checkpoint_cursor", 216), ("snapshot_profile", "native_menu_preserving_save/v2"),
    ("source_revision", "wrong"), ("model", "other"), ("captured_screen_size", [80, 25]),
    ("new_model_calls", True), ("new_model_calls", 63), ("new_accepted_decisions", 65),
    ("new_elapsed_ticks", 14401), ("retained_elapsed_ticks", 63601),
    ("new_tokens", 1), ("campaign_tokens", 1), ("all_attempt_tokens", 10215904),
    ("cumulative_model_responses", 296), ("discarded_native_ticks", 0),
    ("native_save_loss_restarts", 0), ("reported_charge_usd", 0),
    ("independent_retained_evidence_audit_passed", 1), ("teardown_verified", False),
    ("original_checkpoint_unchanged", False), ("inherited_discontinuity_unchanged", False),
    ("memory_and_usage_preserved_across_segments", False),
    ("reset_memory", True), ("reset_usage", True), ("strategy_intervention", True),
    ("new_restart_performed", True), ("uninterrupted_campaign", True),
    ("historical_failed_run_reclassified_as_success", True),
    ("final_checkpoint_fresh_reload_verified", True), ("steps_per_segment", False),
    ("steps_per_segment", 65), ("checkpoints", []),
])
def test_continuation_rejects_usage_reset_and_invented_proof(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[0]
    source = json.loads(path.read_text())
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("field,value", [
    ("cursor", 263), ("cursor", True), ("elapsed_native_ticks", 50000),
    ("sha256", "not-a-hash"), ("parent_sha256", "a" * 64), ("checkpoint_verified", 1),
])
def test_continuation_cannot_skip_or_reorder_checkpoint_lineage(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[0]
    source = json.loads(path.read_text())
    source["checkpoints"][1][field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_later_continuation_binds_previous_continuation_and_is_not_independent(evidence_root, monkeypatch):
    folder = evidence_root / "experiments/evidence"
    source = json.loads((folder / records.CONTINUATIONS[0]).read_text())
    parent = records.keyboard_campaign_records(evidence_root)["continuations"][0]
    source.update(
        parent_record=parent["continuation_id"], parent_checkpoint_sha256=parent["checkpoint_sha256"],
        parent_checkpoint_cursor=296, steps_per_segment=64, cumulative_model_responses=376,
        new_elapsed_ticks=1000, retained_elapsed_ticks=64600, new_tokens=100,
        campaign_tokens=10216004, all_attempt_tokens=10285008,
        checkpoints=[{"cursor": 360, "sha256": "a" * 64,
                      "parent_sha256": parent["checkpoint_sha256"],
                      "elapsed_native_ticks": 64600, "checkpoint_verified": True}],
    )
    filename = "synthetic-continuation-test.json"
    (folder / filename).write_text(json.dumps(source))
    monkeypatch.setattr(records, "CONTINUATIONS", (*records.CONTINUATIONS, filename))
    row = records.keyboard_campaign_records(evidence_root)["continuations"][-1]
    assert row["checkpoint_cursor"] == 360
    assert row["parent_record"] == parent["continuation_id"]
    assert row["progress"]["cumulative_model_responses"] == 376
    assert row["progress"]["discarded_native_ticks"] == 2000
    assert row["usage"]["all_attempt_tokens"] == 10285008
    assert row["uninterrupted_campaign"] is False


def test_completed_play_after_recovery_keeps_all_responses_and_safe_outcome_counts(evidence_root):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[1]
    source = json.loads(path.read_text())
    source["outcome_counts"]["screen"] = "private-screen"
    source["outcome_counts"]["counts"]["population"]["position"] = "private-position"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["continuations"][1]
    assert row["parent_record"] == data["tail_recoveries"][0]["recovery_id"]
    assert row["checkpoint_cursor"] == 375
    assert row["progress"]["cumulative_model_responses"] == 391
    assert row["progress"]["retained_elapsed_ticks"] == 77000
    assert row["usage"]["campaign_tokens"] == 12838159
    assert row["outcome_counts"]["counts"]["completed_farms"] == {"start": 2, "end": 4}
    assert row["outcome_counts"]["food_stock"] is None
    assert data["continuation_events"][-1] == {"kind": "continuation", "id": row["continuation_id"]}
    assert "private-" not in json.dumps(data)


@pytest.mark.parametrize("field,value", [
    ("independent_private_review_passed", False), ("food_stock", 45),
    ("advancing_decisions", True), ("zero_tick_decisions", 56),
    ("production_and_consumption", "self_sufficient"), ("sustainability", "proved"),
])
def test_outcome_summary_cannot_invent_measurement(evidence_root, field, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[1]
    source = json.loads(path.read_text())
    source["outcome_counts"][field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("value", [True, -1, "4", None])
def test_outcome_counts_require_actual_integer_values(evidence_root, value):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[1]
    source = json.loads(path.read_text())
    source["outcome_counts"]["counts"]["completed_farms"]["end"] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)
