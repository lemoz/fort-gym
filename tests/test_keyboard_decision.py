import json
import sys
from pathlib import Path

import pytest

from fort_gym.bench.agent import keyboard_decision as decision
from fort_gym.bench.agent.codex_transport import CodexTransportError
from fort_gym.bench.env.screen_observation import TEXT_PROFILE


def response():
    return {
        "type": "KEYSTROKE",
        "params": {"keys": ["D_BUILDJOB", "BUILDJOB_ADD"]},
        "advance_ticks": 0,
        "intent": "Inspect workshop jobs",
        "memory_update": "",
    }


def test_capture_to_decision_preserves_keys_and_never_dispatches_game(tmp_path, monkeypatch):
    calls = []

    def request(prompt, schema, **kwargs):
        calls.append((prompt, schema, kwargs))
        return {
            "accepted": True,
            "response": response(),
            "run_directory": str(tmp_path),
            "usage": [{"input_tokens": 100, "output_tokens": 10}],
        }

    monkeypatch.setattr(decision, "request_decision", request)
    result = decision.request_keyboard_decision(
        {
            "width": 2,
            "height": 1,
            "tiles": [[65, 7, 0], [66, 15, 4]],
            "fort": {"hidden_fact": "must not reach model"},
        },
        executable=Path(sys.executable),
        artifact_root=tmp_path,
        allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
        memory="Remember the selected workshop",
    )
    assert result["action"] == response()
    assert result["native_action_dispatched"] is False
    assert result["control_profile"] == "native_keyboard/v1"
    assert result["observation_profile"] == "native_screen_tiles/v1"
    assert "hidden_fact" not in calls[0][0]
    assert "Remember the selected workshop" in calls[0][0]
    assert "[66, 15, 4]" in calls[0][0]
    assert json.loads((tmp_path / "keyboard-decision.json").read_text()) == result


def test_invalid_model_action_retains_transport_usage_without_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        decision,
        "request_decision",
        lambda *args, **kwargs: {
            "accepted": True,
            "response": {"type": "ORDER", "params": {"job": "bed"}},
            "usage": [{"input_tokens": 100, "output_tokens": 10}],
            "run_directory": str(tmp_path),
        },
    )
    with pytest.raises(CodexTransportError) as caught:
        decision.request_keyboard_decision(
            {"width": 1, "height": 1, "tiles": [[65, 7, 0]]},
            executable=Path(sys.executable),
            artifact_root=tmp_path,
            allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
        )
    result = caught.value.receipt
    assert result["action"] is None
    assert result["native_action_dispatched"] is False
    assert result["transport_receipt"]["usage"] == [{"input_tokens": 100, "output_tokens": 10}]


def test_bad_capture_never_calls_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        decision, "request_decision", lambda *args, **kwargs: pytest.fail("unexpected model call")
    )
    with pytest.raises(ValueError):
        decision.request_keyboard_decision(
            {}, executable=Path(sys.executable), artifact_root=tmp_path, allowance_check=lambda: {}
        )


def test_text_profile_changes_only_declared_observation_and_instructions(tmp_path, monkeypatch):
    prompts = []

    def request(prompt, schema, **kwargs):
        prompts.append(prompt)
        return {"accepted": True, "response": response(), "run_directory": str(tmp_path)}

    monkeypatch.setattr(decision, "request_decision", request)
    result = decision.request_keyboard_decision(
        {"width": 3, "height": 1, "tiles": [[65, 7, 0], [3, 15, 1], [66, 7, 0]]},
        executable=Path(sys.executable),
        artifact_root=tmp_path,
        allowance_check=lambda: {"allowed": True, "basis": "offline_fixture"},
        observation_profile=TEXT_PROFILE,
    )
    assert '"rows": ["A♥B"]' in prompts[0]
    assert '"color_spans": [[0, 1, 2, 15, 1]]' in prompts[0]
    assert "column-major tiles" not in prompts[0]
    assert "one Unicode glyph per native tile" in prompts[0]
    assert result["observation_profile"] == TEXT_PROFILE
    assert result["action"] == response()
