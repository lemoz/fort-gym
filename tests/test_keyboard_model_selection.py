"""Offline model-selection contracts; no model availability or gameplay claim."""

import json
import sys
from pathlib import Path

import pytest

from fort_gym.bench.agent import codex_transport as transport
from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.keyboard_courier import answer_request
from fort_gym.bench.agent.keyboard_exchange import digest, read, request_selection, validate_request
from fort_gym.bench.env.screen_observation import TEXT_PROFILE
from fort_gym.bench.run.campaign_loop import CampaignLoop
from fort_gym.bench.run.keyboard_config import validate_condition
from fort_gym.bench.run.keyboard_segment import run_keyboard_segment
from tests.test_campaign_codex_keyboard import Environment, decision
from tests.test_codex_transport import FakeProcess, events
from tests.test_keyboard_rejection import rejected
from tests.test_keyboard_runtime import CONDITION, environment, request

MODELS = ("gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra")


def condition(model="gpt-5.6-sol", effort="medium"):
    return {
        **CONDITION,
        "schema_version": "fortgym.codex-keyboard-condition/v2",
        "condition_id": "offline-model-selection",
        "model": model,
        "reasoning_effort": effort,
    }


def selected_request(model="gpt-5.6-sol", effort="medium"):
    return {
        **request(),
        "schema_version": "fortgym.keyboard-exchange-request/v2",
        "model": model,
        "reasoning_effort": effort,
    }


def policy(model="gpt-5.6-sol", effort="medium", callback=decision):
    def selected(*args):
        result = callback(*args)
        result["transport_receipt"].update(
            model_requested=model, reasoning_effort_requested=effort,
        )
        return result

    return CodexKeyboardAgent(
        decision=selected, max_dispatches=8, max_total_tokens=10000,
        model=model, reasoning_effort=effort,
    )


@pytest.mark.parametrize("model", MODELS)
def test_explicit_condition_selects_model_without_changing_other_controls(model):
    selected = validate_condition(condition(model))
    assert selected["model"] == model
    for key in CONDITION.keys() - {"schema_version", "condition_id", "model"}:
        assert selected[key] == CONDITION[key]


@pytest.mark.parametrize("field,value", [("model", "gpt-5.6-sol"), ("reasoning_effort", "high")])
def test_legacy_condition_cannot_be_reinterpreted(field, value):
    assert validate_condition(CONDITION) == CONDITION
    with pytest.raises(ValueError, match="identity"):
        validate_condition({**CONDITION, field: value})
    assert request_selection(request()) == ("gpt-6-astra", "medium")


@pytest.mark.parametrize("model,effort", [
    (None, "medium"), (True, "medium"), ([], "medium"), ("", "medium"),
    ("gpt-6-astra ", "medium"), ("--oss", "medium"), ("ollama/model", "medium"),
    ("gpt-6-astra\n--oss", "medium"), ("gpt-" + "a" * 129, "medium"),
    ("gpt-6-astra", None), ("gpt-6-astra", []), ("gpt-6-astra", "auto"),
    ("gpt-6-astra", 'medium"\nmodel_provider="other'),
])
def test_invalid_selection_is_rejected_before_admission_or_artifacts(tmp_path, model, effort):
    with pytest.raises(ValueError, match="model or reasoning"):
        transport.request_decision(
            "Offline fixture", {}, executable=Path(sys.executable), artifact_root=tmp_path,
            allowance_check=lambda: pytest.fail("Invalid model reached allowance check"),
            model=model, reasoning_effort=effort,
        )
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError):
        validate_condition(condition(model, effort))


@pytest.mark.parametrize("model", MODELS)
def test_courier_transports_exact_selection_and_retains_receipt(tmp_path, monkeypatch, model):
    calls = []
    response_action = decision(request()["screen"], "", None)["action"]
    raw = "\n".join(json.dumps(event) for event in events(response=response_action))

    def spawn(command, **kwargs):
        process = FakeProcess(command, output=raw, **kwargs)
        calls.append(process)
        return process

    monkeypatch.setattr(transport.subprocess, "Popen", spawn)
    response, summary = answer_request(
        selected_request(model, "high"), directory=tmp_path,
        condition=condition(model, "high"), executable=Path(sys.executable),
        allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
    )
    assert len(calls) == 1
    command = calls[0].command
    assert command[command.index("--model") + 1] == model
    assert 'model_reasoning_effort="high"' in command
    assert 'forced_login_method="chatgpt"' in command
    assert "--oss" not in command and "--ignore-user-config" in command
    receipt = response["result"]["transport_receipt"]
    assert receipt["model_requested"] == model
    assert receipt["reasoning_effort_requested"] == "high"
    retained = read(Path(receipt["run_directory"]) / "request.json")
    assert retained["model_requested"] == model
    assert retained["reasoning_effort_requested"] == "high"
    assert response["result"]["action"] == response_action
    assert summary["total_tokens"] == 110 and summary["reported_charge_usd"] is None
    assert response["request_sha256"] == digest(selected_request(model, "high"))


@pytest.mark.parametrize("change", [
    {"model": "gpt-5.6-terra"}, {"reasoning_effort": "high"},
    {"schema_version": "fortgym.codex-keyboard-condition/v1", "model": "gpt-6-astra"},
])
def test_mismatched_courier_condition_never_dispatches(tmp_path, change):
    with pytest.raises(ValueError, match="model differs"):
        answer_request(
            selected_request(), directory=tmp_path, condition={**condition(), **change},
            executable=Path(sys.executable),
            decision=lambda *args, **kwargs: pytest.fail("Mismatched model dispatched"),
        )
    assert not list(tmp_path.iterdir())


def test_v2_condition_requires_explicit_exchange_identity(tmp_path):
    with pytest.raises(ValueError, match="model differs"):
        answer_request(
            request(), directory=tmp_path, condition=condition("gpt-6-astra"),
            executable=Path(sys.executable),
        )
    assert not list(tmp_path.iterdir())
    for field in ("model", "reasoning_effort"):
        value = selected_request()
        del value[field]
        with pytest.raises(ValueError):
            validate_request(value)
        assert digest(selected_request()) != digest(value)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("callback", [decision, rejected])
def test_selected_model_keeps_checkpoint_identity_usage_and_rejection(tmp_path, model, callback):
    agent = policy(model, callback=callback)
    env = Environment()
    loop = CampaignLoop(
        campaign_id="offline-model-test", agent=agent, environment=env,
        output=tmp_path / "first", observation_profile=TEXT_PROFILE,
    )
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=env, code_revision="offline")
    if callback is rejected:
        assert not env.actions and agent.memory == ""
    else:
        assert len(env.actions) == 1 and agent.memory == "x"
    restored_env = Environment()
    restored_env.tick = env.tick
    resumed = CampaignLoop.resume(
        checkpoint, agent=policy(model, callback=callback), environment=restored_env,
        output=tmp_path / "second", latest_usage_path=loop.journal,
    )
    assert resumed.agent.export_campaign_state() == agent.export_campaign_state()
    resumed.step()
    assert resumed.agent.usage["total_tokens"] == 200
    assert resumed.agent.usage["total_cost_usd"] is None


@pytest.mark.parametrize("model,effort", [("gpt-5.6-terra", "medium"), ("gpt-5.6-sol", "high")])
def test_resume_cannot_change_model_or_effort(model, effort):
    original = policy()
    original.set_campaign_context(campaign_id="same-campaign")
    with pytest.raises(ValueError, match="configuration or identity"):
        policy(model, effort).restore_campaign_state(
            original.export_campaign_state(), campaign_id="same-campaign",
        )


def test_wrong_model_receipt_is_counted_but_never_executed(tmp_path):
    agent = policy()
    agent.decision = decision  # The legacy fixture claims Astra, not selected Sol.
    env = Environment()
    loop = CampaignLoop(
        campaign_id="offline-mismatch", agent=agent, environment=env,
        output=tmp_path / "first", observation_profile=TEXT_PROFILE,
    )
    with pytest.raises(transport.CodexTransportError, match="identity"):
        loop.step()
    assert not env.actions and agent.memory == ""
    assert agent.usage["total_tokens"] == 100


def test_segment_checks_condition_before_reading_game_or_checkpoint(tmp_path):
    with pytest.raises(ValueError, match="agent differs"):
        run_keyboard_segment(
            agent=policy(), environment=None, snapshotter=None, output=tmp_path / "out",
            condition=condition("gpt-5.6-terra"), checkpoint=tmp_path / "absent",
            latest_usage=tmp_path / "absent-usage", steps=1, expected_cursor=1,
            revision="offline",
        )
    assert not list(tmp_path.iterdir())


def test_explicit_condition_resumes_as_a_native_segment_with_same_model(tmp_path):
    env = environment()
    loop = CampaignLoop(
        campaign_id="offline-segment", agent=policy(), environment=env,
        output=tmp_path / "first", observation_profile=TEXT_PROFILE,
        advance_policy=CONDITION["advance_policy"],
    )
    loop.step()
    checkpoint = tmp_path / "checkpoint"
    loop.checkpoint(checkpoint, snapshotter=env, code_revision="offline")
    selected = {**condition(), "max_dispatches": 8, "max_total_tokens": 10000}
    agent = policy()
    result = run_keyboard_segment(
        agent=agent, environment=env, snapshotter=env, output=tmp_path / "segment",
        condition=selected, checkpoint=checkpoint, latest_usage=loop.journal,
        steps=1, expected_cursor=1, revision="offline",
    )
    assert result["checkpoint_verified"] and result["status"] == "bounded_segment_complete"
    assert result["next_step"] == 2 and agent.memory == "xx"
    assert agent.configuration["model"] == "gpt-5.6-sol"


def test_provider_rejects_selection_without_retry_or_replacement(tmp_path, monkeypatch):
    calls = []
    raw = json.dumps({"type": "turn.failed", "error": {"message": "Unavailable model fixture"}})

    def spawn(command, **kwargs):
        calls.append(command)
        return FakeProcess(command, output=raw, **kwargs)

    monkeypatch.setattr(transport.subprocess, "Popen", spawn)
    with pytest.raises(transport.CodexTransportError) as caught:
        transport.request_decision(
            "Offline", {}, executable=Path(sys.executable), artifact_root=tmp_path,
            allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
            model="gpt-unavailable-fixture", reasoning_effort="low",
        )
    assert len(calls) == 1
    assert calls[0][calls[0].index("--model") + 1] == "gpt-unavailable-fixture"
    receipt = caught.value.receipt
    assert receipt["dispatched"] and not receipt["accepted"]
    assert receipt["model_requested"] == "gpt-unavailable-fixture"
    assert receipt["reported_charge_usd"] is None
