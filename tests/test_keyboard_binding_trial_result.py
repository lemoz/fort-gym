"""Check the public saved result without requiring private model or game artifacts."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def result():
    return json.loads(
        (ROOT / "experiments/evidence/keyboard_binding_astra_r1_20260911.json").read_text()
    )


def test_completed_result_remains_distinct_from_unchanged_startup():
    value = result()
    launch = json.loads(
        (ROOT / "experiments/evidence/keyboard_binding_trial_launch_20260911.json").read_text()
    )
    assert value["campaign_id"] == launch["campaign_id"]
    assert value["status"] == "bounded_trial_complete"
    assert value["stop_reason"] == "segment_limit"
    assert launch["status"] == "running_startup_verified"
    assert launch["proof_limits"]["terminal_result"] is False
    for key, expected in value["condition"].items():
        assert expected == launch[key]
    assert value["condition"]["same_condition_as_historical_matched_cohort"] is False


def test_all_decisions_reconcile_saved_time_keys_and_subscription_tokens():
    value = result()
    rows = value["timeline"]
    assert [row["decision"] for row in rows] == list(range(1, 33))
    assert len(rows) == value["responses"] == value["usage"]["accounted_responses"] == 32
    elapsed = 0
    for row in rows:
        elapsed += row["ticks_advanced"]
        assert row["saved_elapsed_ticks"] == elapsed
        assert row["input_accepted"] is True
        assert row["confirmed_key_presses"] == len(row["keys"])
        assert 0 <= row["ticks_advanced"] <= row["requested_ticks"] <= 2000
    assert elapsed == value["saved_elapsed_ticks"] == 15500
    assert sum(row["returned_tokens"] for row in rows) == value["usage"]["total_tokens"] == 785690
    assert sum(row["confirmed_key_presses"] for row in rows) == value["confirmed_key_presses"] == 248
    start, end = value["condition"]["starting_boundary"], value["final_boundary"]
    assert (end["year"] - start["year"]) * value["ticks_per_year"] + end["year_tick"] - start["year_tick"] == elapsed
    assert rows[-1]["metrics"] == value["saved_metrics"]


def test_menu_time_rejection_is_not_hidden_as_input_failure_or_rescue():
    value = result()
    blocked, following = value["timeline"][7:9]
    assert blocked["input_accepted"] is True
    assert blocked["clock_error"] == "blocking_native_menu"
    assert blocked["requested_ticks"] == 2000 and blocked["ticks_advanced"] == 0
    assert following["keys"] == ["SYM:0:ESC", " "]
    assert following["clock_error"] is None and following["ticks_advanced"] == 2000
    assert value["clock_outcomes"] == {"blocking_native_menu": 1, "no_error": 31}
    assert value["proof_limits"]["human_gameplay_rescue"] is False


def test_observed_construction_and_food_do_not_overclaim_production():
    value = result()
    before, after = value["initial_metrics"], value["saved_metrics"]
    assert (before["completed_workshops"], before["completed_farms"]) == (0, 0)
    assert (after["completed_workshops"], after["completed_farms"], after["completed_beds"]) == (2, 1, 0)
    assert (after["population"], after["recorded_dead_citizens"]) == (7, 0)
    assert (after["food_stock"], after["drink_stock"]) == (50, 60)
    food = value["food_measurement"]
    assert food["complete_samples"] == food["samples"] == 32
    assert food["final_inventory"]["complete"] is True
    assert food["final_inventory"]["units"] == after["food_stock"]
    assert food["final_inventory"]["predicate_argument"] == 0
    assert after["stone_stock"] is after["wood_stock"] is None
    assert value["activity"]["completed_production"] is None
    assert value["activity"]["completed_consumption"] is None
    assert not any(value["proof_limits"].values())


def test_all_receipts_cleanup_and_unknown_charges_remain_inspectable():
    value = result()
    audit = value["audit"]
    assert audit["passed"] is audit["native_cleanup_verified"] is audit["vm_teardown_verified"] is True
    assert audit["provider_receipts_verified"] == len(audit["provider_receipts"]) == 32
    assert [row["decision_index"] for row in audit["provider_receipts"]] == list(range(32))
    assert sum(row["total_tokens"] for row in audit["provider_receipts"]) == value["usage"]["total_tokens"]
    assert audit["sha256"] == "a3c4614ea4a650b2311ac150eb712e1b393b38efc8d4eeba6e8daf2b7db871ba"
    assert value["checkpoint_sha256"] == "ce25bca850526f6863c2c6fb3d4ac3a048b3791898df764021d815d273db3541"
    assert audit["shutdown"]["vm_observed_stopped"] is True
    assert audit["shutdown"]["guest_poweroff_returncode"] == audit["shutdown"]["vm_stop_returncode"] == 0
    assert value["usage"]["total_cost_usd"] is None
    assert value["cost_limits"]["actual_model_charge_usd"] is None
    assert value["cost_limits"]["cloud_vms_created"] == 0
    assert value["cost_limits"]["automatic_reset_consumption"] is False
