"""Validate the declared pilot with real runner code and synthetic decisions."""

from collections import Counter
from pathlib import Path

import pytest

from fort_gym.bench.agent.campaign_keyboard import initial_usage
from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_trial_config import load_trial
from tests.test_keyboard_fresh_trial import start

PROJECT = Path(__file__).resolve().parents[1]
DIRECTORY = PROJECT / "experiments/keyboard_matched_pilot_20260910"
COHORT = read(DIRECTORY / "cohort.json")
ROWS = COHORT["execution_order"]


def selected(row):
    return load_trial(DIRECTORY / row["condition"], DIRECTORY / row["trial"])


def test_cohort_is_a_plan_with_six_unique_balanced_independent_starts():
    assert COHORT["schema_version"] == "fortgym.keyboard-matched-cohort-plan/v1"
    assert COHORT["artifact_kind"] == "experiment_plan"
    assert COHORT["model_results_included"] is False
    assert len(ROWS) == len({row["campaign_id"] for row in ROWS}) == 6
    assert Counter(row["model"] for row in ROWS) == {
        "gpt-6-astra": 2, "gpt-5.6-sol": 2, "gpt-5.6-terra": 2,
    }
    assert [row["model"] for row in ROWS[:3]] == [
        row["model"] for row in reversed(ROWS[3:])
    ]
    for model in {row["model"] for row in ROWS}:
        assert {row["replicate"] for row in ROWS if row["model"] == model} == {1, 2}
    assert COHORT["outcome_policy"]["strong_ranking_claims"] is False
    assert COHORT["outcome_policy"]["world_generalization"] is False


def test_only_model_identity_and_labels_vary_between_declared_conditions():
    conditions, trials = [], []
    for row in ROWS:
        condition, trial = selected(row)
        assert condition["model"] == row["model"]
        assert condition["reasoning_effort"] == "medium"
        assert trial["source_snapshot_receipt_sha256"] == COHORT["source_snapshot_receipt_sha256"]
        assert trial["initial_memory"] == "empty"
        assert trial["strategy_intervention"] is False
        conditions.append({k: v for k, v in condition.items() if k not in {"model", "condition_id"}})
        trials.append({k: v for k, v in trial.items() if k != "original_condition"})
    assert all(condition == conditions[0] for condition in conditions)
    assert all(trial == trials[0] for trial in trials)
    assert conditions[0]["control_profile"] == "native_keyboard/v2"
    assert conditions[0]["observation_profile"] == "native_screen_text/v1"
    assert conditions[0]["screen_size"] == [120, 40]
    assert conditions[0]["max_dispatches"] == 1280
    assert conditions[0]["max_total_tokens"] == 40000000
    assert conditions[0]["max_advance_ticks"] == 2000
    assert sum(trial["steps_per_segment"] for trial in trials) == 192
    assert COHORT["stages"]["pilot_total_response_ceiling"] == 192


def test_shared_seed_is_the_declared_native_acceptance_source_not_astra_save():
    fixture = read(PROJECT / "experiments/evidence/scripted_native_keyboard_fresh_trial_20260910.json")
    assert COHORT["source_snapshot_receipt_sha256"] == fixture["source_snapshot_receipt_sha256"]
    assert fixture["proof_boundary"]["autonomous_gameplay"] is False
    assert fixture["fixture_outcome"]["real_model_calls"] == 0


@pytest.mark.parametrize("row", ROWS, ids=[row["campaign_id"] for row in ROWS])
def test_each_declared_start_saves_exact_model_memory_and_usage_offline(tmp_path, row):
    condition, trial = selected(row)
    output = tmp_path / row["campaign_id"]
    result, agent, _ = start(
        output, condition=condition, campaign_id=row["campaign_id"],
        steps=trial["steps_per_segment"],
        source_snapshot_receipt_sha256=trial["source_snapshot_receipt_sha256"],
    )
    assert result["checkpoint_verified"] is True
    assert result["campaign_id"] == row["campaign_id"]
    assert (result["first_step"], result["next_step"]) == (0, 32)
    initial = read(output / "agent-before.json")
    assert initial["usage"] == initial_usage() and initial["memory"] == ""
    saved = read(output / "checkpoint/agent.json")
    assert saved["configuration"]["model"] == row["model"]
    assert saved["configuration"]["reasoning_effort"] == "medium"
    assert saved["usage"]["accounted_responses"] == 32
    assert saved["usage"]["total_tokens"] == 3200  # Synthetic, not provider usage.
    assert saved["memory"] == agent.memory == "x" * 32
    assert saved["prompt_changes"][0]["source_snapshot_receipt_sha256"] == (
        COHORT["source_snapshot_receipt_sha256"]
    )


@pytest.mark.parametrize("row", ROWS[:3], ids=[row["model"] for row in ROWS[:3]])
def test_trial_cannot_be_relabelled_as_another_model_condition(tmp_path, row):
    original = read(DIRECTORY / row["trial"])
    wrong = {**original, "original_condition": "different-model-condition.json"}
    # The regular public loader, not an experiment-specific substitute, rejects it.
    from fort_gym.bench.agent.keyboard_exchange import publish

    path = tmp_path / "mismatched-trial.json"
    publish(path, wrong)
    with pytest.raises(ValueError, match="independent"):
        load_trial(DIRECTORY / row["condition"], path)
