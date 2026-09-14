"""Separate bound-input condition, transport and persistent campaign contracts."""

from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.agent import keyboard_decision as decision_module
from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import validate_request
from fort_gym.bench.agent.keyboard_prompt import BINDING_PROMPT
from fort_gym.bench.env.display_key_catalog import BINDING_PROFILE, BINDINGS_SHA256
from fort_gym.bench.env.screen_observation import TEXT_PROFILE
from fort_gym.bench.run.keyboard_config import validate_condition
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from fort_gym.bench.run.keyboard_trial import run_keyboard_trial
from tests.test_campaign_codex_keyboard import decision
from tests.test_keyboard_runtime import CONDITION, environment, request
from tests.test_keyboard_rejection import rejected


def condition():
    return {
        **CONDITION,
        "schema_version": "fortgym.codex-keyboard-condition/v4",
        "condition_id": "fixture-displayed-keys",
        "control_profile": BINDING_PROFILE,
        "bindings_sha256": BINDINGS_SHA256,
        "prompt_profile": BINDING_PROMPT,
    }


def selected_request():
    config = condition()
    return {
        **request(),
        "schema_version": "fortgym.keyboard-exchange-request/v4",
        **{
            k: config[k]
            for k in (
                "model",
                "reasoning_effort",
                "control_profile",
                "bindings_sha256",
                "prompt_profile",
            )
        },
    }


def policy(callback=decision):
    def selected(*args):
        result = callback(*args)
        result.update(control_profile=BINDING_PROFILE, prompt_profile=BINDING_PROMPT)
        if result.get("action"):
            result["action"]["params"]["keys"] = ["b", "SYM:0:Enter"]
        return result

    config = condition()
    return CodexKeyboardAgent(
        decision=selected,
        **{
            k: config[k]
            for k in (
                "model",
                "reasoning_effort",
                "max_dispatches",
                "max_total_tokens",
                "max_advance_ticks",
                "control_profile",
            )
        },
    )


@pytest.mark.parametrize(
    "change",
    [
        {"bindings_sha256": "0" * 64},
        {"control_profile": "native_keyboard/v2"},
        {"prompt_profile": "native_keyboard_memory_replacement/v1"},
        {"schema_version": "fortgym.codex-keyboard-condition/v3"},
    ],
)
def test_condition_cannot_silently_change_earlier_input_semantics(change):
    assert validate_condition(condition()) == condition()
    with pytest.raises(ValueError):
        validate_condition({**condition(), **change})
    assert validate_condition(CONDITION) == CONDITION


@pytest.mark.parametrize(
    "field,value",
    [
        ("bindings_sha256", "0" * 64),
        ("control_profile", "native_keyboard/v2"),
        ("schema_version", "fortgym.keyboard-exchange-request/v3"),
    ],
)
def test_exchange_and_courier_bind_the_new_profile_before_model_contact(tmp_path, field, value):
    validate_request(selected_request())
    altered = {**selected_request(), field: value}
    with pytest.raises(ValueError):
        validate_request(altered)
    with pytest.raises(ValueError):
        answer_request(
            altered,
            directory=tmp_path,
            condition=condition(),
            executable=Path("/unused"),
            decision=lambda *a, **k: pytest.fail("model contact"),
        )
    assert not list(tmp_path.iterdir())


def test_model_receives_displayed_key_instructions_and_returns_them_unchanged(
    tmp_path, monkeypatch
):
    calls = []
    action = decision(request()["screen"], "", None)["action"]
    action["params"]["keys"] = ["b", "SYM:0:Enter"]

    def respond(prompt, schema, **kwargs):
        calls.append(prompt)
        return {"response": action, "run_directory": str(tmp_path)}

    monkeypatch.setattr(decision_module, "request_decision", respond)
    value = decision_module.request_keyboard_decision(
        request()["screen"],
        executable=Path("/unused"),
        artifact_root=tmp_path,
        allowance_check=lambda: {},
        control_profile=BINDING_PROFILE,
        prompt_profile=BINDING_PROMPT,
        observation_profile=TEXT_PROFILE,
    )
    assert value["action"] == action and value["control_profile"] == BINDING_PROFILE
    assert "complete binding" in calls[0] and "completely replaces" in calls[0]
    assert "Your controls are native game-interface key events" not in calls[0]
    assert "Native key catalog" not in calls[0]
    assert value["native_action_dispatched"] is False


@pytest.mark.parametrize("rejection", [False, True])
def test_new_profile_fresh_start_checkpoint_and_continuation_keep_memory_and_usage(
    tmp_path, rejection
):
    env = environment()
    env.control_profile = BINDING_PROFILE
    agent = policy(rejected if rejection else decision)
    config = condition()
    output = tmp_path / "fresh"
    result = run_keyboard_trial(
        agent=agent,
        environment=env,
        snapshotter=env,
        output=output,
        condition=config,
        campaign_id="binding-profile-fixture",
        steps=2,
        source_snapshot_receipt_sha256="a" * 64,
        loaded_boundary={"year": 30, "year_tick": env.tick, "paused": True},
        revision="fixture",
    )
    assert result["checkpoint_verified"] and result["next_step"] == 2
    assert agent.configuration["bindings_sha256"] == BINDINGS_SHA256
    assert len(env.actions) == (0 if rejection else 2)
    assert agent.memory == ("" if rejection else "xx")
    before = deepcopy(agent.export_campaign_state())
    restored = policy()
    continued = run_keyboard_segment(
        agent=restored,
        environment=env,
        snapshotter=env,
        output=tmp_path / "continued",
        condition=config,
        checkpoint=output / "checkpoint",
        latest_usage=output / "loop/usage.jsonl",
        steps=1,
        expected_cursor=2,
        revision="fixture",
    )
    assert continued["checkpoint_verified"] and continued["next_step"] == 3
    assert restored.usage["total_tokens"] == 300
    assert restored.prompt_changes == before["prompt_changes"]
    assert restored.configuration == before["configuration"]
    assert restored.memory == before["memory"] + "x"
    assert (
        (tmp_path / "continued/loop/trace.jsonl")
        .read_bytes()
        .startswith((output / "loop/trace.jsonl").read_bytes())
    )


def test_old_agent_cannot_load_new_profile_state():
    new = policy()
    new.set_campaign_context(campaign_id="fixture")
    old = CodexKeyboardAgent(decision=decision, max_dispatches=8, max_total_tokens=10000)
    with pytest.raises(ValueError, match="configuration"):
        old.restore_campaign_state(new.export_campaign_state(), campaign_id="fixture")


def test_prepared_trial_is_separate_but_keeps_non_input_conditions():
    import json
    from fort_gym.bench.run.keyboard_trial_config import load_trial

    root = Path(__file__).resolve().parents[1] / "experiments"
    old = json.loads((root / "keyboard_matched_pilot_20260910/astra-condition.json").read_bytes())
    config, trial = load_trial(
        root / "keyboard_bindings_20260911/astra-condition.json",
        root / "keyboard_bindings_20260911/astra-trial.json",
    )
    expected_changes = {
        "schema_version",
        "condition_id",
        "control_profile",
        "prompt_profile",
        "bindings_sha256",
    }
    assert {
        key for key in old.keys() | config.keys() if old.get(key) != config.get(key)
    } == expected_changes
    assert trial["steps_per_segment"] == 32 and trial["initial_memory"] == "empty"
    assert trial["strategy_intervention"] is False
    assert config["model"] == "gpt-6-astra" and config["reasoning_effort"] == "medium"
    assert config["actual_charge_usd"] is None and config["api_fallback"] is False


def test_v4_courier_sends_declared_profile_and_prompt(tmp_path):
    calls = []

    def respond(screen, **kwargs):
        calls.append(kwargs)
        return {
            "action": {"type": "KEYSTROKE", "params": {"keys": ["b"]}},
            "action_grammar_valid": True,
            "transport_receipt": {"dispatched": False},
        }

    answer_request(
        selected_request(),
        directory=tmp_path,
        condition=condition(),
        executable=Path("/unused"),
        decision=respond,
        allowance_check=lambda: {},
    )
    assert len(calls) == 1
    assert calls[0]["control_profile"] == BINDING_PROFILE
    assert calls[0]["prompt_profile"] == BINDING_PROMPT


def test_actual_exchange_emitter_binds_profile_and_digest(tmp_path, monkeypatch):
    from fort_gym.bench.agent import keyboard_exchange as exchange

    original = exchange.publish
    seen = []

    def deliver(path, value):
        original(path, value)
        if path.name == "request.json":
            seen.append(value)
            original(
                path.with_name("response.json"),
                {"request_sha256": exchange.digest(value), "result": {"fixture": True}},
            )

    monkeypatch.setattr(exchange, "publish", deliver)
    result = exchange.exchange_decision(
        tmp_path,
        request()["screen"],
        "memory",
        None,
        model="gpt-6-astra",
        reasoning_effort="medium",
        prompt_profile=BINDING_PROMPT,
        control_profile=BINDING_PROFILE,
    )
    assert result == {"fixture": True} and len(seen) == 1
    assert seen[0]["schema_version"] == "fortgym.keyboard-exchange-request/v4"
    assert seen[0]["bindings_sha256"] == BINDINGS_SHA256
    assert seen[0]["control_profile"] == BINDING_PROFILE
