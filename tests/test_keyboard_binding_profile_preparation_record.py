"""Do not promote offline integration checks to native/model acceptance."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "experiments/evidence/keyboard_binding_profile_preparation_20260911.json"


def test_preparation_is_source_bound_and_preserves_native_prototype_scope():
    raw = RECORD.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "d226ae59ee890141f9ed12d6e00ae094e05cf6f28b74d3085c0f779f0e6cde5e"
    )
    value = json.loads(raw)
    assert (
        value["implementation_revision"]
        == value["regression"]["source_revision"]
        == value["ci"]["source_revision"]
    )
    assert value["regression"]["passed"] == 5032 and value["regression"]["failed"] == 0
    assert value["regression"]["skipped"] == 10 and value["focused_new_tests_passed"] == 78
    assert (
        value["supported_character_keys"] + value["supported_symbol_combinations"]
        == value["supported_keys"]
        == 405
    )
    assert (
        value["static_baseline"]["added_ruff_findings"]
        == value["static_baseline"]["added_mypy_errors"]
        == 0
    )
    assert value["static_baseline"]["global_lint_or_types_passed"] is False
    prior = value["prior_native_prototype"]
    assert hashlib.sha256((ROOT / prior["record"]).read_bytes()).hexdigest() == prior["sha256"]
    assert value["ci"]["status"] == "in_progress" and value["ci"]["conclusion"] is None


def test_prepared_condition_is_not_a_launched_or_shipped_gameplay_result():
    value = json.loads(RECORD.read_bytes())
    for field in (
        "native_integrated_profile_acceptance_verified",
        "native_navigation_text_entry_verified",
        "model_trial_started",
        "new_scored_checkpoint",
        "main_merged",
        "public_deployment",
        "full_year_two_goal_complete",
        "historical_controls_changed",
        "historical_comparison_results_changed",
    ):
        assert value[field] is False
    assert value["model_calls"] == value["cloud_vms_created"] == value["local_vms_started"] == 0
    assert value["hardware_energy_and_app_cost_usd"] is None
    assert (
        value["prepared_model"] == "gpt-6-astra" and value["prepared_reasoning_effort"] == "medium"
    )
    assert value["prepared_first_segment_responses"] == 32
