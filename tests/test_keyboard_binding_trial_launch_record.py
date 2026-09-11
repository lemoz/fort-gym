"""Protect the historical startup snapshot, not claim terminal acceptance."""

import json
from pathlib import Path


def record():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "experiments/evidence/keyboard_binding_trial_launch_20260911.json"
        ).read_text()
    )


def test_launch_is_an_independent_declared_astra_condition():
    value = record()
    assert value["campaign_id"] == "bindings-20260911-astra-r1"
    assert value["model"] == "gpt-6-astra" and value["reasoning_effort"] == "medium"
    assert value["control_profile"] == "native_keyboard_bindings/v1"
    assert value["prompt_profile"] == "native_keyboard_binding_instructions/v1"
    assert value["maximum_responses"] == 32
    assert value["fresh_empty_memory_usage_history"] and value["independent_campaign"]
    assert value["shares_original_matched_pilot_snapshot"]
    assert value["borrowed_old_campaign_memory"] is False
    assert value["operator_edited_diagnostic_copy_used"] is False
    assert value["same_condition_as_historical_matched_cohort"] is False


def test_first_receipt_proof_does_not_claim_campaign_completion():
    value = record()
    assert value["status"] == "running_startup_verified"
    assert value["starting_boundary"] == {
        "year": 30,
        "year_tick": 16801,
        "paused": True,
        "screen_size": [120, 40],
    }
    startup = value["startup_review"]
    assert (
        startup["passed"] and startup["total_tokens"] == startup["first_response_tokens"] == 26434
    )
    assert startup["first_action_keys"] == ["z"] and startup["next_request_confirmed_keys"] == 1
    assert startup["first_action_ticks_advanced"] == 0
    assert not any(value["proof_limits"].values())


def test_subscription_cost_and_active_vm_are_not_hidden():
    value = record()
    costs, lifecycle = value["usage_and_cost"], value["lifecycle"]
    assert value["auth_mode"] == "chatgpt"
    assert costs["fresh_account_admission_before_each_call"]
    assert (
        costs["initial_observed_used_percent"] == 70
        and costs["maximum_included_usage_percent"] == 98
    )
    assert costs["actual_model_charge_usd"] is costs["hardware_energy_and_app_cost_usd"] is None
    for key in (
        "api_fallback",
        "local_model_fallback",
        "automatic_credit_purchase",
        "automatic_reset_consumption",
        "atomic_account_reservation",
    ):
        assert costs[key] is False
    assert lifecycle["max_simultaneous_vms"] == 1 and lifecycle["cloud_vms_created"] == 0
    assert (
        lifecycle["mandatory_teardown_in_owner"] and lifecycle["teardown_not_yet_due_running_trial"]
    )
