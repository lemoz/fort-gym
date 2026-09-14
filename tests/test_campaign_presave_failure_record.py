"""A failed pre-save attempt must never masquerade as checkpointed progress."""

import json
from pathlib import Path

from fort_gym.bench.api.campaign_keyboard_records import keyboard_campaign_records

ROOT = Path(__file__).resolve().parents[1]


def test_presave_failure_keeps_last_checkpoint_and_all_spent_usage():
    folder = ROOT / "experiments/evidence"
    value = json.loads((folder / "astra_native_keyboard_presave_failure_20260908.json").read_text())
    parent = json.loads((folder / (value["parent_record"] + ".json")).read_text())
    assert value["schema_version"] == "fortgym.native-keyboard-presave-failure-summary/v1"
    assert value["status"] == "failed" and value["independent_failure_audit_passed"] is True
    assert value["last_verified_checkpoint_cursor"] == parent["checkpoints"][-1]["cursor"] == 631
    assert value["last_verified_checkpoint_sha256"] == parent["checkpoints"][-1]["sha256"]
    assert value["new_checkpoint_created"] is value["new_restart_performed"] is False
    assert value["original_checkpoint_unchanged"] is value["original_failure_preserved"] is True
    progress, usage = value["progress"], value["usage"]
    assert progress["observed_trace_next_step"] == 631 + progress["new_model_calls"] == 695
    assert progress["checkpointed_elapsed_ticks"] == parent["retained_elapsed_ticks"] == 143400
    assert progress["observed_trace_elapsed_ticks"] == 143400 + progress["unsaved_new_native_ticks"] == 164600
    assert progress["new_accepted_decisions"] == 64 and progress["new_rejected_decisions"] == 0
    assert progress["accounted_model_responses"] == parent["cumulative_model_responses"] + 64 == 711
    assert usage["campaign_tokens"] == parent["campaign_tokens"] + usage["new_tokens"] == 22819077
    assert usage["all_attempt_tokens"] == parent["all_attempt_tokens"] + usage["new_tokens"] == 22888081
    assert usage["reported_charge_usd"] is None
    assert value["failure"]["native_save_requested"] is False
    assert value["failure"]["stage"] == "identity_probe_before_native_save_request"
    assert value["failure"]["underlying_stack_cause"] == "unverified"
    assert value["teardown_verified"] is True
    observed = value["observed_unsaved_outcomes"]
    assert observed["counts"]["food_stock"] == {"start": 82, "end": 43}
    assert observed["food_complete_measurements"] + observed["food_unknown_measurements"] == 65
    assert observed["food_unknown_measurements"] == 2
    assert observed["food_final_observation_is_saved"] is False
    # Failure data has not been added to the completed-continuation allowlist.
    continuations = keyboard_campaign_records(ROOT)["continuations"]
    assert all(row["continuation_id"] != "astra_native_keyboard_presave_failure_20260908"
               for row in continuations)
    public_parent = next(row for row in continuations if row["continuation_id"] == value["parent_record"])
    assert public_parent["checkpoint_cursor"] == 631
