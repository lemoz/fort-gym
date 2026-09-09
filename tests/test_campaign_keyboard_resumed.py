"""A saved resumed window must not erase failed-branch usage or unknown time."""

import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_keyboard_resumed import DIGESTS, resumed_window
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


def publication(root):
    path = root / "experiments/evidence" / records.RESUMED_WINDOWS[0]
    return path, json.loads(path.read_bytes())


def test_saved_window_retains_failed_parent_usage_and_unknown_loss():
    data = records.keyboard_campaign_records()
    row, parent = data["resumed_windows"][-1], data["oom_failures"][-1]
    assert row["parent_record"] == parent["failure_id"]
    assert row["checkpoint_cursor"] == 775
    assert row["progress"]["retained_elapsed_ticks"] == 198600
    assert row["progress"]["cumulative_model_responses"] == 906
    assert row["progress"]["native_save_loss_restarts"] == 4
    assert row["progress"]["confirmed_discarded_native_ticks"] == 35091
    assert row["progress"]["discarded_native_ticks"] is None
    assert row["usage"]["all_attempt_tokens"] == 28980051
    assert row["usage"]["reported_charge_usd"] is None
    assert row["new_restart_performed"] is True
    assert row["final_checkpoint_fresh_reload_verified"] is False
    assert row["outcome_counts"]["advancing_decisions"] == 3
    assert row["outcome_counts"]["counts"]["drink_units"] == {"start": 337, "end": 411}
    assert row["food_inventory"]["final_units"] is None
    assert row["food_inventory"]["unknown_measurements"] == 2
    assert row["operator_observation_warning"]["command_exit_code"] == 1
    assert data["continuation_events"][-2] == {"kind": "resumed", "id": row["resumed_id"]}


@pytest.mark.parametrize("field,value", [
    ("parent_record", "missing"), ("parent_checkpoint_cursor", 738),
    ("checkpoint_cursor", 776), ("retained_elapsed_ticks", 203800),
    ("cumulative_model_responses", 775), ("new_model_calls", True),
    ("native_save_loss_restarts", 3), ("confirmed_discarded_native_ticks", 29891),
    ("discarded_native_ticks", 35091), ("discarded_native_ticks_complete", True),
    ("new_lost_uncommitted_ticks", 0), ("campaign_tokens", 26990171),
    ("reported_charge_usd", 0), ("all_prior_usage_retained", False),
    ("historical_failed_run_reclassified_as_success", True),
    ("final_checkpoint_fresh_reload_verified", True), ("teardown_verified", 1),
    ("new_elapsed_ticks", 128001), ("new_accepted_decisions", 65),
])
def test_inconsistent_lineage_rejected(evidence_root, field, value):
    path, source = publication(evidence_root)
    source[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("field", DIGESTS)
def test_audit_bindings_required(evidence_root, field):
    path, source = publication(evidence_root)
    source[field] = "invalid"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("mutation", ["warning", "food", "outcome", "execution"])
def test_measurements_and_warning_must_reconcile(evidence_root, mutation):
    path, source = publication(evidence_root)
    if mutation == "warning":
        source["operator_observation_warning"]["command_exit_code"] = 128
    elif mutation == "food":
        source["food_inventory"]["unknown_measurements"] = 0
    elif mutation == "outcome":
        source["outcome_counts"]["zero_tick_decisions"] = 64
    else:
        source["execution_counts"]["model_input_rejections"] = 1
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversized", "wrong_parent"])
def test_bounded_publication_and_parent_required(evidence_root, kind):
    parents = records.keyboard_campaign_records(evidence_root)["oom_failures"]
    path, source = publication(evidence_root)
    if kind == "missing":
        path.unlink()
    elif kind == "symlink":
        target = path.with_suffix(".original")
        path.rename(target)
        path.symlink_to(target)
    elif kind == "oversized":
        source["padding"] = "x" * 65536
        path.write_text(json.dumps(source))
    else:
        parents = []
    with pytest.raises(ValueError):
        resumed_window(evidence_root, records.RESUMED_WINDOWS[0], parents)


def test_private_fields_not_projected_and_unlisted_record_not_loaded(evidence_root, monkeypatch):
    before = records.keyboard_campaign_records(evidence_root)
    path, source = publication(evidence_root)
    source["private_memory"] = source["outcome_counts"]["screen"] = "private-sentinel"
    path.write_text(json.dumps(source))
    assert records.keyboard_campaign_records(evidence_root) == before
    monkeypatch.setattr(records, "RESUMED_WINDOWS", ())
    monkeypatch.setattr(records, "PROMPT_TRIALS", ())
    after = records.keyboard_campaign_records(evidence_root)
    assert after["resumed_windows"] == []
    assert after["continuation_events"] == before["continuation_events"][:-2]
    assert after["oom_failures"] == before["oom_failures"]
