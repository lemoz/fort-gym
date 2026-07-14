"""Contract tests for the frozen provisional Fort-Eval Easy P1 manifest."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from fort_gym.bench.eval.fort_eval_easy_p1 import (
    MODEL_ARMS,
    P1_MAX_STEPS,
    P1_PROTOCOL,
    P1_SEED_SAVE,
    P1_SEED_WORLD_SHA256,
    P1_TICKS_PER_STEP,
)
from fort_gym.bench.experiment.config import load_experiment_config

MANIFEST_PATH = Path("experiments/fort_eval_easy_p1_g7_v4.yaml")
V5_MANIFEST_PATH = Path("experiments/fort_eval_easy_p1_g7_v5.yaml")


def _manifest() -> dict[str, object]:
    raw = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _v5_manifest() -> dict[str, object]:
    raw = yaml.safe_load(V5_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_fort_eval_easy_p1_g7_v4_freezes_requested_condition() -> None:
    manifest = _manifest()
    task = manifest["task"]
    condition = manifest["benchmark_condition"]
    assert isinstance(task, dict)
    assert isinstance(condition, dict)

    assert manifest["manifest_id"] == "fort-eval-easy-p1-g7-v4"
    assert manifest["status"] == "provisional"
    assert task["task_id"] == "g7_survival"
    assert task["task_version"] == "g7-v4"
    assert task["seed"] == "seed_region3_fresh"
    assert condition["observation"]["vision_enabled"] is True
    assert condition["knowledge"]["condition"] == "none"
    assert condition["memory"]["mode"] == "off"
    assert condition["budget"] == {
        "max_steps": 200,
        "ticks_per_step": 2500,
        "max_ticks": 500000,
    }
    assert condition["score"]["version"] == "score-v5"
    assert "duration_ticks_min" not in task["success_predicates"]
    assert "population_min" not in task["success_predicates"]
    assert "score_min" not in task["success_predicates"]
    assert task["diagnostics"]["duration_ticks"]["affects_gate_status"] is False
    assert task["diagnostics"]["population"]["affects_gate_status"] is False
    assert (
        task["diagnostics"]["population"]["comparison_scope"] == "matched_cohort_only"
    )
    assert task["diagnostics"]["scalar_score"]["affects_gate_status"] is False
    assert (
        task["diagnostics"]["scalar_score"]["comparison_scope"] == "matched_cohort_only"
    )


def test_fort_eval_easy_p1_declares_two_arms_with_shared_generation_contract() -> None:
    manifest = _manifest()
    model_arms = manifest["model_arms"]
    assert isinstance(model_arms, dict)
    arms = model_arms["arms"]
    assert isinstance(arms, list)
    assert [arm["model_arm"] for arm in arms] == [
        "dfhack-governed-llm-fable5",
        "dfhack-governed-llm-gpt56-sol",
    ]
    assert all(arm["provider_route"] == "openrouter" for arm in arms)
    assert all(arm["vision_enabled"] is True for arm in arms)
    assert all(arm["memory_mode"] == "off" for arm in arms)
    assert all(arm["generation"]["reasoning_effort"] == "max" for arm in arms)
    assert all(arm["generation"]["max_completion_tokens"] == 128000 for arm in arms)
    assert all(
        arm["generation"]["sticky_routing"] == "per_run_session_id" for arm in arms
    )
    by_name = {arm["model_arm"]: arm for arm in arms}
    assert (
        by_name["dfhack-governed-llm-fable5"]["generation"]["prompt_cache"]
        == "explicit_system_ephemeral"
    )
    assert (
        by_name["dfhack-governed-llm-gpt56-sol"]["generation"]["prompt_cache"]
        == "automatic"
    )


def test_fort_eval_p1_separates_condition_fields_from_arm_identity() -> None:
    manifest = _manifest()
    comparability = manifest["comparability"]
    assert isinstance(comparability, dict)
    condition_fields = comparability["benchmark_condition_fields"]
    arm_identity = comparability["model_arm_identity"]
    assert isinstance(condition_fields, list)
    assert isinstance(arm_identity, dict)
    assert "model_arm" not in condition_fields
    assert arm_identity["field"] == "model_arm"
    assert arm_identity["is_benchmark_condition_field"] is False
    assert (
        comparability["run_identity_key_format"]
        == "{condition_key}|model_arm={model_arm}"
    )


def test_fort_eval_p1_records_provider_exception_cost_policy_and_failures() -> None:
    manifest = _manifest()
    provider_policy = manifest["provider_policy"]
    cost = manifest["cost_and_kill"]
    publication = manifest["publication"]
    assert isinstance(provider_policy, dict)
    assert isinstance(cost, dict)
    assert isinstance(publication, dict)

    assert provider_policy["legacy_direct_anthropic_api"] == "prohibited"
    exception = provider_policy["openrouter_fable_exception"]
    assert exception["model_arm"] == "dfhack-governed-llm-fable5"
    assert exception["provider_route"] == "openrouter"
    assert exception["direct_anthropic_api"] is False
    assert cost["expenditure_cap"] == {
        "enabled": False,
        "per_run_usd": None,
        "per_cell_usd": None,
    }
    assert publication["valid_failures_publishable"] is True


def test_fort_eval_p1_runtime_contract_matches_manifest() -> None:
    manifest = _v5_manifest()
    task = manifest["task"]
    budget = manifest["benchmark_condition"]["budget"]
    arms = manifest["model_arms"]["arms"]

    assert manifest["manifest_id"] == P1_PROTOCOL
    assert task["seed"] == P1_SEED_SAVE
    assert task["seed_world_sha256"] == P1_SEED_WORLD_SHA256
    assert budget["max_steps"] == P1_MAX_STEPS
    assert budget["ticks_per_step"] == P1_TICKS_PER_STEP
    assert {arm["model_arm"] for arm in arms} == set(MODEL_ARMS)


def test_g7_v5_replaces_scalar_rubric_with_owned_outcome_vector() -> None:
    manifest = _v5_manifest()
    task = manifest["task"]
    score = manifest["benchmark_condition"]["score"]

    assert manifest["status"] == "calibration"
    assert task["task_version"] == "g7-v5"
    assert task["success_predicates"] == {
        "exact_owned_operational_farm_plots_min": 1,
        "exact_owned_completed_stills_min": 1,
        "exact_governed_brew_output_units_min": 1,
        "authoritatively_classified_preventable_deaths_max": 0,
        "final_owned_accessible_layout_rooms_min": 3,
        "exact_owned_completed_beds_min": 3,
    }
    assert score["version"] == "outcome-vector-v1"
    assert score["diagnostic_scalar_version"] == "score-v5"
    assert task["outcome_vector"]["numeric_composite"] is False
    assert task["outcome_vector"]["action_variety_credit"] is False
    assert task["outcome_vector"]["objective_text_credit"] is False


def test_fort_eval_p1_links_passing_provider_preflight() -> None:
    manifest = _manifest()
    evidence_path = Path(manifest["provider_preflight_evidence"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert evidence["protocol"] == manifest["provider_preflight_inherits_from"]
    assert evidence["ok"] is True
    assert {result["arm"] for result in evidence["results"]} == set(MODEL_ARMS)
    assert all(result["transport_verified"] for result in evidence["results"])
    assert all(result["cache_verified"] for result in evidence["results"])
    assert all(
        call["action_type"] == "WAIT" and call["advance_ticks"] == P1_TICKS_PER_STEP
        for result in evidence["results"]
        for call in result["calls"]
    )


def test_fort_eval_p1_is_executable_by_experiment_runner() -> None:
    config = load_experiment_config(MANIFEST_PATH)

    assert config.base_config.seed_save == P1_SEED_SAVE
    assert config.base_config.preserve_save is False
    assert config.base_config.ticks_per_step == P1_TICKS_PER_STEP
    assert config.base_config.runtime_save == "region1"
    assert [variant.model for variant in config.variants] == [
        "dfhack-governed-llm-fable5",
        "dfhack-governed-llm-gpt56-sol",
    ]
