"""Predeclared equal conditions across models; no native or model calls."""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "experiments/keyboard_binding_comparison_20260911"


def read(name):
    return json.loads((PLAN / name).read_text())


def test_six_fresh_attempts_have_two_replicates_of_each_declared_model():
    cohort = read("cohort.json")
    rows = cohort["sequence"]
    assert len(rows) == len({row["id"] for row in rows}) == 6
    assert Counter(row["model"] for row in rows) == {"astra": 2, "sol": 2, "terra": 2}
    for model in cohort["models"]:
        assert {row["replicate"] for row in rows if row["model"] == model} == {1, 2}
    assert (
        cohort["native_source_revision"] == "d22f28d99f4fd103188979e964e148139d3f3efd"
    )
    assert cohort["common_decision_boundaries"] == [64, 128]
    assert cohort["strong_ranking_claims_allowed"] is False
    assert cohort["historical_astra_is_context_not_a_new_replicate"] is True


def test_models_are_the_only_agent_condition_difference():
    cohort = read("cohort.json")
    shared = []
    trials = []
    for name, model in cohort["models"].items():
        value = read(name + "-condition.json")
        assert value.pop("model") == model
        assert (
            value.pop("condition_id")
            == "binding-comparison-" + name + "-medium-native-keyboard-120x40"
        )
        assert value["reasoning_effort"] == "medium"
        assert value["steps_per_segment"] == 64
        assert value["control_profile"] == "native_keyboard_bindings/v1"
        assert value["observation_profile"] == "native_screen_text/v1"
        assert value["max_dispatches"] == 1280 and value["max_total_tokens"] == 40000000
        assert value["maximum_included_usage_percent"] == 98
        assert value["actual_charge_usd"] is None
        assert all(
            value[key] is False
            for key in (
                "api_fallback",
                "automatic_credit_purchase",
                "automatic_reset_consumption",
            )
        )
        shared.append(value)
        trial = read(name + "-trial.json")
        assert trial.pop("original_condition") == name + "-condition.json"
        assert trial["source_snapshot_receipt_sha256"] == cohort["seed_receipt_sha256"]
        assert trial["initial_memory"] == "empty"
        assert trial["strategy_intervention"] is False
        assert trial["steps_per_segment"] == 64
        trials.append(trial)
    assert shared[0] == shared[1] == shared[2]
    assert trials[0] == trials[1] == trials[2]


def test_cohort_preserves_limits_and_historical_conditions():
    cohort = read("cohort.json")
    assert cohort["maximum_concurrent_vms"] == cohort["maximum_concurrent_games"] == 1
    assert cohort["cloud_vms_to_create"] == 0
    assert cohort["mandatory_vm_teardown"] is True
    assert cohort["retained_prior_campaigns_unchanged"] is True
    assert cohort["human_gameplay_rescue"] is False
    assert cohort["shortcut_condition_included"] is False
    assert cohort["shortcut_pair_comparison_remains_separate"] is True
    assert cohort["comparison"]["budget_limited_pause_is_not_gameplay_collapse"] is True
    assert cohort["comparison"]["protocol_changes_require_new_version"] is True
