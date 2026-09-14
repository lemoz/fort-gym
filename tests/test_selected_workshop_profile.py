"""The new control condition must not change observation or historical play."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from fort_gym.bench.agent import keyboard_decision as decision_module
from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import validate_request
from fort_gym.bench.agent.standard_input import parse_response, response_schema
from fort_gym.bench.env.display_key_catalog import BINDING_PROFILE
from fort_gym.bench.env.screen_observation import TEXT_PROFILE
from fort_gym.bench.env.workshop_job_profile import (
    CONTROL_PROFILE, PROMPT_PROFILE, ACTION_TYPE,
)
from fort_gym.bench.run import campaign_environment
from fort_gym.bench.run.keyboard_config import validate_condition
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_trial import run_keyboard_trial
from tests.test_campaign_codex_keyboard import decision
from tests.test_keyboard_binding_profile import condition as keyboard_condition
from tests.test_keyboard_binding_profile import selected_request as keyboard_request
from tests.test_keyboard_runtime import environment, request


def condition():
    return {
        **keyboard_condition(),
        "schema_version": "fortgym.codex-keyboard-condition/v5",
        "condition_id": "fixture-selected-workshop",
        "control_profile": CONTROL_PROFILE,
        "prompt_profile": PROMPT_PROFILE,
    }


def selected_request():
    return {
        **keyboard_request(),
        "schema_version": "fortgym.keyboard-exchange-request/v5",
        "control_profile": CONTROL_PROFILE, "prompt_profile": PROMPT_PROFILE,
    }


def job_action():
    return {
        "type": ACTION_TYPE, "params": {"item": "bed", "quantity": 2},
        "advance_ticks": 100, "intent": "Queue two beds", "memory_update": "x",
    }


def policy():
    def selected(screen, memory, feedback):
        result = decision(screen, memory, feedback)
        result.update(control_profile=CONTROL_PROFILE, prompt_profile=PROMPT_PROFILE)
        result["action"] = {**job_action(), "memory_update": memory + "x"}
        return result

    config = condition()
    return CodexKeyboardAgent(decision=selected, **{
        key: config[key] for key in (
            "model", "reasoning_effort", "control_profile",
            "max_dispatches", "max_total_tokens", "max_advance_ticks",
        )
    })


@pytest.mark.parametrize("profile", ["native_keyboard/v1", "native_keyboard/v2", BINDING_PROFILE])
def test_historical_profiles_reject_job_shortcut(profile):
    with pytest.raises(ValueError):
        parse_response(job_action(), max_advance_ticks=2000, control_profile=profile)
    assert response_schema(max_advance_ticks=2000, control_profile=profile)["properties"]["type"]["enum"] == ["KEYSTROKE"]


@pytest.mark.parametrize("params", [
    {"item": "bed", "quantity": True}, {"item": "bed", "quantity": 0},
    {"item": "bed", "quantity": 6}, {"item": "bed", "quantity": "2"},
    {"item": "bed", "quantity": 1.0}, {"item": "magma", "quantity": 1},
    {"item": "bed", "quantity": 1, "workshop_id": 5},
    {"item": "bed", "quantity": 1, "keys": ["q"]},
    {"keys": ["q"]}, {"item": [], "quantity": 1},
])
def test_malformed_or_mixed_shortcut_never_coerced(params):
    with pytest.raises(ValueError):
        parse_response({**job_action(), "params": params},
                       max_advance_ticks=2000, control_profile=CONTROL_PROFILE)


def test_both_routes_are_strict_and_leave_payload_untouched():
    shortcut = job_action()
    keyboard = {**shortcut, "type": "KEYSTROKE", "params": {"keys": ["q", "SYM:0:Enter"]}}
    schema = response_schema(max_advance_ticks=2000, control_profile=CONTROL_PROFILE)
    assert schema["properties"]["type"]["enum"] == ["KEYSTROKE", ACTION_TYPE]
    assert len(schema["properties"]["params"]["anyOf"]) == 2
    for action in (shortcut, keyboard):
        before = deepcopy(action)
        actual = parse_response(action, max_advance_ticks=2000, control_profile=CONTROL_PROFILE)
        assert actual == action == before and actual is not action
    with pytest.raises(ValueError):
        parse_response({**keyboard, "params": shortcut["params"]},
                       max_advance_ticks=2000, control_profile=CONTROL_PROFILE)


@pytest.mark.parametrize("change", [
    {"schema_version": "fortgym.codex-keyboard-condition/v4"},
    {"control_profile": BINDING_PROFILE},
    {"prompt_profile": keyboard_condition()["prompt_profile"]},
    {"bindings_sha256": "0" * 64},
])
def test_new_condition_cannot_be_silently_relabelled(change):
    validate_condition(condition())
    with pytest.raises(ValueError):
        validate_condition({**condition(), **change})
    with pytest.raises(ValueError):
        validate_condition({**keyboard_condition(), "prompt_profile": PROMPT_PROFILE})


@pytest.mark.parametrize("change", [
    {"schema_version": "fortgym.keyboard-exchange-request/v4"},
    {"control_profile": BINDING_PROFILE},
    {"prompt_profile": keyboard_condition()["prompt_profile"]},
    {"bindings_sha256": "0" * 64},
])
def test_exchange_identity_is_verified_before_model_contact(tmp_path, change):
    validate_request(selected_request())
    with pytest.raises(ValueError):
        answer_request(
            {**selected_request(), **change}, directory=tmp_path,
            condition=condition(), executable=Path("/unused"),
            decision=lambda *a, **kw: pytest.fail("model contacted"),
        )
    assert not list(tmp_path.iterdir())


def test_same_screen_and_memory_with_only_explicit_control_instructions_changed(tmp_path, monkeypatch):
    prompts = []

    def respond(prompt, schema, **kwargs):
        prompts.append(prompt)
        action = job_action() if len(prompts) == 2 else {
            **job_action(), "type": "KEYSTROKE", "params": {"keys": ["q"]},
        }
        return {"response": action, "run_directory": str(kwargs["artifact_root"])}

    monkeypatch.setattr(decision_module, "request_decision", respond)
    for config in (keyboard_condition(), condition()):
        target = tmp_path / config["condition_id"]
        target.mkdir()
        result = decision_module.request_keyboard_decision(
            request()["screen"], executable=Path("/unused"), artifact_root=target,
            allowance_check=lambda: {}, memory="identical retained memory",
            feedback={"accepted": True}, control_profile=config["control_profile"],
            prompt_profile=config["prompt_profile"], observation_profile=TEXT_PROFILE,
        )
        assert result["native_action_dispatched"] is False
    assert prompts[0].split("Your retained memory:")[1] == prompts[1].split("Your retained memory:")[1]
    assert "Direct DFHack build/order\nshortcuts are not available" in prompts[0]
    assert "WORKSHOP_JOB" in prompts[1] and "No workshop is found or selected for you" in prompts[1]
    assert "Return one KEYSTROKE or WORKSHOP_JOB response" in prompts[1]
    assert "completely replaces" in prompts[1]


def test_workshop_campaign_saves_and_resumes_same_controls_usage_and_memory(tmp_path):
    env, agent = environment(), policy()
    env.control_profile = CONTROL_PROFILE
    fresh = tmp_path / "fresh"
    result = run_keyboard_trial(
        agent=agent, environment=env, snapshotter=env, output=fresh,
        condition=condition(), campaign_id="workshop-fixture", steps=2,
        source_snapshot_receipt_sha256="a" * 64,
        loaded_boundary={"year": 30, "year_tick": env.tick, "paused": True},
        revision="fixture",
    )
    assert result["checkpoint_verified"] and result["next_step"] == 2
    before, restored = deepcopy(agent.export_campaign_state()), policy()
    resumed = run_keyboard_segment(
        agent=restored, environment=env, snapshotter=env,
        output=tmp_path / "continued", condition=condition(),
        checkpoint=fresh / "checkpoint", latest_usage=fresh / "loop/usage.jsonl",
        steps=1, expected_cursor=2, revision="fixture",
    )
    assert resumed["checkpoint_verified"] and resumed["next_step"] == 3
    assert restored.memory == "xxx" and restored.usage["total_tokens"] == 300
    assert restored.configuration == before["configuration"]
    assert restored.prompt_changes == before["prompt_changes"]
    rows = [json.loads(line) for line in (tmp_path / "continued/loop/trace.jsonl").read_text().splitlines()]
    assert [row["action"]["type"] for row in rows] == [ACTION_TYPE] * 3


@pytest.mark.parametrize("profile", [CONTROL_PROFILE, BINDING_PROFILE])
def test_native_adapter_routes_only_explicitly_enabled_shortcut(monkeypatch, profile):
    env = campaign_environment.NativeCampaignEnvironment.__new__(
        campaign_environment.NativeCampaignEnvironment
    )
    env.control_profile, env.expected_dfroot = profile, Path("/isolated")
    env._verify_runtime = lambda: None
    monkeypatch.setattr(campaign_environment, "read_binding_index", lambda root: None)
    calls = []
    monkeypatch.setattr(campaign_environment, "execute_workshop_job",
                        lambda params, **kw: calls.append(params) or {"accepted": True})
    result = env.apply(job_action(), {"year": 30, "year_tick": 123})
    assert result["accepted"] is (profile == CONTROL_PROFILE)
    assert calls == ([job_action()["params"]] if profile == CONTROL_PROFILE else [])


def test_declared_pair_has_identical_observation_memory_seed_and_budgets():
    from fort_gym.bench.run.keyboard_trial_config import load_trial

    root = Path(__file__).resolve().parents[1] / "experiments/selected_workshop_study_v1"
    baseline, baseline_trial = load_trial(root / "keyboard-condition.json", root / "keyboard-trial.json")
    shortcut, shortcut_trial = load_trial(root / "shortcuts-condition.json", root / "shortcuts-trial.json")
    changed = {key for key in baseline.keys() | shortcut.keys() if baseline.get(key) != shortcut.get(key)}
    assert changed == {"schema_version", "condition_id", "control_profile", "prompt_profile"}
    assert {key for key in baseline_trial if baseline_trial[key] != shortcut_trial[key]} == {"original_condition"}
    assert baseline["max_dispatches"] == 128 and baseline["max_total_tokens"] == 8_000_000
    assert baseline_trial["steps_per_segment"] == 64 and baseline_trial["initial_memory"] == "empty"
