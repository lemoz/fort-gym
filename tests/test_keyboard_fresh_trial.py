"""Synthetic independent starts and real checkpoint machinery; no model/game calls."""

from copy import deepcopy
import json

import pytest

from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent, initial_usage
from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.agent.keyboard_prompt import BASE_PROMPT, MEMORY_PROMPT, effective_prompt
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_trial import run_keyboard_trial
from tests.test_campaign_codex_keyboard import decision, admission_denied
from tests.test_keyboard_runtime import CONDITION, environment
from tests.test_keyboard_rejection import rejected

MODELS = ("gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra")
SEED = "a" * 64


def config(model="gpt-6-astra", profile=MEMORY_PROMPT):
    return {
        **CONDITION,
        "schema_version": "fortgym.codex-keyboard-condition/v3",
        "condition_id": "fixture-independent-start",
        "model": model,
        "prompt_profile": profile,
    }


def policy(condition, callback=decision):
    def selected(*args):
        value = callback(*args)
        if value["transport_receipt"].get("dispatched") is True:
            value["transport_receipt"].update(
                model_requested=condition["model"],
                reasoning_effort_requested=condition["reasoning_effort"],
            )
        value["prompt_profile"] = condition["prompt_profile"]
        return value

    return CodexKeyboardAgent(
        decision=selected,
        **{
            key: condition[key]
            for key in (
                "max_dispatches",
                "max_total_tokens",
                "max_advance_ticks",
                "model",
                "reasoning_effort",
            )
        },
    )


def start(output, condition=None, callback=decision, **changes):
    condition = condition or config()
    env, agent = environment(), policy(condition, callback)
    arguments = dict(
        agent=agent,
        environment=env,
        snapshotter=env,
        output=output,
        condition=condition,
        campaign_id="independent-fixture",
        steps=3,
        source_snapshot_receipt_sha256=SEED,
        loaded_boundary={"year": 30, "year_tick": env.tick, "paused": True},
        revision="fixture",
    )
    result = run_keyboard_trial(**{**arguments, **changes})
    return result, agent, env


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("profile", [BASE_PROMPT, MEMORY_PROMPT])
def test_fresh_models_start_empty_then_continue_without_reset(tmp_path, model, profile):
    condition, seen = config(model, profile), []

    def observe(*args):
        seen.append(deepcopy(args))
        return decision(*args)

    output = tmp_path / "trial"
    result, agent, env = start(output, condition, observe)
    assert result["status"] == "bounded_segment_complete" and result["checkpoint_verified"] is True
    assert result["first_step"] == 0 and result["next_step"] == 3
    assert result["committed_elapsed_ticks"] == 30
    assert seen[0][1:] == ("", None)
    assert "hidden" not in json.dumps(seen)
    initial = read(output / "agent-before.json")
    assert initial["memory"] == "" and initial["usage"] == initial_usage()
    assert len(initial["prompt_changes"]) == 1
    origin = initial["prompt_changes"][0]
    assert origin["source_snapshot_receipt_sha256"] == SEED
    assert origin["schema_version"] == "fortgym.keyboard-prompt-origin/v1"
    assert "checkpoint_sha256" not in origin
    assert read(output / "history-before.json") == {"discontinuities": []}
    checkpoint = output / "checkpoint"
    manifest = verify_checkpoint(checkpoint)
    assert manifest["payload"]["next_step"] == 3
    restored = policy(condition)
    resumed = run_keyboard_segment(
        agent=restored,
        environment=env,
        snapshotter=env,
        output=tmp_path / "resumed",
        condition=condition,
        checkpoint=checkpoint,
        latest_usage=output / "loop/usage.jsonl",
        steps=2,
        expected_cursor=3,
        revision="fixture",
    )
    assert resumed["checkpoint_verified"] is True and resumed["next_step"] == 5
    assert restored.prompt_profile == profile and restored.prompt_changes == agent.prompt_changes
    assert restored.memory == "xxxxx" and restored.usage["total_tokens"] == 500
    assert len(env.actions) == 5
    assert (
        (tmp_path / "resumed/loop/trace.jsonl")
        .read_bytes()
        .startswith((output / "loop/trace.jsonl").read_bytes())
    )


def test_zero_call_admission_pause_does_not_fabricate_a_checkpoint(tmp_path):
    result, agent, env = start(tmp_path / "trial", callback=admission_denied)
    assert result["status"] == "budget_limited_pause" and result["initial_snapshot_only"] is True
    assert result["checkpoint_verified"] is False and result["next_step"] == 0
    assert result["recovery_requires_reconciliation"] is False
    assert agent.usage == initial_usage() and not env.actions
    assert not (tmp_path / "trial/checkpoint").exists()


def test_uncertain_first_response_retains_usage_and_forensic_save(tmp_path):
    def missing(*args):
        return {"transport_receipt": {}}

    result, agent, env = start(tmp_path / "trial", callback=missing)
    assert result["status"] == "failed" and result["checkpoint_verified"] is False
    assert agent.usage["dispatched_requests"] == 1 and not env.actions
    assert result["recovery_requires_reconciliation"] is True
    assert (tmp_path / "trial/unreconciled-native-save").is_dir()


def test_rejected_first_inputs_are_retained_without_repair_or_memory_injection(tmp_path):
    result, agent, env = start(tmp_path / "trial", callback=rejected)
    assert result["status"] == "bounded_segment_complete" and result["checkpoint_verified"] is True
    assert result["next_step"] == 3 and not env.actions and agent.memory == ""
    assert agent.usage["accounted_responses"] == 3


def test_failed_first_segment_save_retains_usage_and_does_not_retry(tmp_path):
    env = environment()
    captures = []

    def failed(directory):
        captures.append(directory)
        raise RuntimeError("fixture save failure")

    env.capture = failed
    result, agent, _ = start(tmp_path / "trial", environment=env, snapshotter=env)
    assert result["status"] == "checkpoint_failed" and result["checkpoint_verified"] is False
    assert agent.usage["accounted_responses"] == 3 and len(captures) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("campaign_id", "prior"),
        ("memory", "prior memory"),
        ("events", [{}]),
        ("budget_extensions", [{}]),
        ("prompt_changes", [{}]),
    ],
)
def test_start_cannot_reuse_an_existing_agent(tmp_path, field, value):
    agent = policy(config())
    setattr(agent, field, value)
    before = deepcopy(agent.__dict__)
    with pytest.raises(ValueError, match="reuse or reset"):
        start(tmp_path / "trial", agent=agent)
    assert agent.__dict__ == before and not (tmp_path / "trial").exists()


def test_initial_prompt_cannot_clear_existing_usage():
    agent = policy(config())
    agent.usage["total_tokens"] = 100
    with pytest.raises(ValueError, match="fresh unused"):
        agent.initialize_prompt(profile=MEMORY_PROMPT, source_snapshot_receipt_sha256=SEED)
    assert agent.usage["total_tokens"] == 100 and agent.prompt_changes == []


@pytest.mark.parametrize(
    "boundary",
    [
        {"year": 30, "year_tick": 124, "paused": True},
        {"year": 30, "year_tick": 123, "paused": False},
    ],
)
def test_loaded_boundary_mismatch_never_reaches_model(tmp_path, boundary):
    def forbidden(*args):
        pytest.fail("Mismatched snapshot reached the model")

    if boundary["paused"] is False:
        with pytest.raises(ValueError):
            start(tmp_path / "trial", callback=forbidden, loaded_boundary=boundary)
    else:
        result, agent, env = start(tmp_path / "trial", callback=forbidden, loaded_boundary=boundary)
        assert result["status"] == "failed" and agent.usage == initial_usage() and not env.actions


def test_legacy_prompt_state_is_unchanged_and_origin_is_single_use():
    agent = policy(config())
    initial = agent.export_campaign_state()
    assert "prompt_changes" not in initial and agent.prompt_profile == BASE_PROMPT
    origin = agent.initialize_prompt(profile=MEMORY_PROMPT, source_snapshot_receipt_sha256=SEED)
    assert effective_prompt([origin], initial_usage()) == MEMORY_PROMPT
    with pytest.raises(ValueError, match="fresh unused"):
        agent.initialize_prompt(profile=BASE_PROMPT, source_snapshot_receipt_sha256=SEED)
    with pytest.raises(ValueError, match="origin"):
        effective_prompt([origin, origin], initial_usage())


@pytest.mark.parametrize(
    "key,value",
    [
        ("profile", "unknown"),
        ("source_snapshot_receipt_sha256", "bad"),
        ("usage", {"dispatched_requests": False, "total_tokens": 0}),
        ("usage", {"dispatched_requests": 1, "total_tokens": 0}),
    ],
)
def test_malformed_prompt_origins_do_not_restore(key, value):
    agent = policy(config())
    origin = agent.initialize_prompt(profile=MEMORY_PROMPT, source_snapshot_receipt_sha256=SEED)
    origin[key] = value
    with pytest.raises(ValueError):
        effective_prompt([origin], initial_usage())
