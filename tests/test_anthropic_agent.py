from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fort_gym.bench.agent.llm_anthropic import (
    AnthropicActionAgent,
    AnthropicDigFirstAgent,
    AnthropicFortressPlanAgent,
    AnthropicKeystrokeAgent,
    DIG_FIRST_SYSTEM_PROMPT,
    FORTRESS_PLAN_SYSTEM_PROMPT,
    KEYSTROKE_SYSTEM_PROMPT,
)
from fort_gym.bench.api.schemas import RunCreateRequest
from fort_gym.bench.config import get_settings


class _FakeMessages:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    input={
                        "type": "WAIT",
                        "params": {},
                        "intent": "wait for the fortress state to advance",
                        "advance_ticks": 10,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=1234, output_tokens=56),
        )


class _FakeAnthropicClient:
    last_instance: "_FakeAnthropicClient | None" = None

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.messages = _FakeMessages()
        _FakeAnthropicClient.last_instance = self


class _SequencedMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses = responses

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self._responses.pop(0)


class _SequencedAnthropicClient:
    last_instance: "_SequencedAnthropicClient | None" = None
    responses: list[Any] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.messages = _SequencedMessages(list(self.responses))
        _SequencedAnthropicClient.last_instance = self


def test_anthropic_default_model_tracks_current_sonnet(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        assert get_settings().ANTHROPIC_MODEL == "claude-sonnet-4-6"
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_anthropic_agent_records_usage_event(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_FakeAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicActionAgent()
        action = agent.decide("mock observation", {"drink": 100})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "WAIT"
    assert events == [
        {
            "tool": "anthropic.messages.create",
            "input": {
                "model": "claude-sonnet-4-6",
                "max_tokens": 512,
                "temperature": 0.1,
            },
            "output": {"usage": {"input_tokens": 1234, "output_tokens": 56}},
        }
    ]
    assert _FakeAnthropicClient.last_instance is not None
    assert _FakeAnthropicClient.last_instance.api_key == "test-key"
    request = _FakeAnthropicClient.last_instance.messages.requests[0]
    assert request["model"] == "claude-sonnet-4-6"


def test_keystroke_prompt_is_action_first() -> None:
    assert "FRESH TARGET RULE" in KEYSTROKE_SYSTEM_PROMPT
    assert "D_DESIGNATE" in KEYSTROKE_SYSTEM_PROMPT
    assert "advance_ticks\": 500" in KEYSTROKE_SYSTEM_PROMPT
    assert "Do not" in KEYSTROKE_SYSTEM_PROMPT
    assert "repeat the same key sequence" in KEYSTROKE_SYSTEM_PROMPT


def test_keystroke_retry_pairs_invalid_tool_use_with_tool_result(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_bad",
                    input={
                        "type": "WAIT",
                        "params": {},
                        "intent": "invalid wait",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_good",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "recover",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=12, output_tokens=3),
        ),
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_SequencedAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicKeystrokeAgent()
        action = agent.decide("mock screen", {})
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry_messages = requests[1]["messages"]
    assert retry_messages[1]["role"] == "assistant"
    assert retry_messages[2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_bad",
                "content": "You must return a KEYSTROKE action.",
            }
        ],
    }


def test_dig_first_prompt_uses_structured_control() -> None:
    assert "structured action API" in DIG_FIRST_SYSTEM_PROMPT
    assert '"type":"DIG"' in DIG_FIRST_SYSTEM_PROMPT
    assert '"advance_ticks":500' in DIG_FIRST_SYSTEM_PROMPT
    assert "target_dig_designations == 0 means no dig has been designated yet" in DIG_FIRST_SYSTEM_PROMPT
    assert "target_wall_tiles > 0 means the target is still solid wall" in DIG_FIRST_SYSTEM_PROMPT
    assert "target_floor_tiles >= 25 or target_wall_tiles == 0 means the starter room is complete" in DIG_FIRST_SYSTEM_PROMPT
    assert '"type":"ORDER"' in DIG_FIRST_SYSTEM_PROMPT
    assert '"job":"bed","quantity":5' in DIG_FIRST_SYSTEM_PROMPT
    assert '"type":"BUILD"' in DIG_FIRST_SYSTEM_PROMPT
    assert '"kind":"CarpenterWorkshop","x":51,"y":36,"z":0' in DIG_FIRST_SYSTEM_PROMPT
    assert "Do not drive the Dwarf Fortress UI with keystrokes" in DIG_FIRST_SYSTEM_PROMPT


def test_fortress_plan_prompt_uses_two_room_layout() -> None:
    assert "two-room fortress plan" in FORTRESS_PLAN_SYSTEM_PROMPT
    assert '"area":[55,37,0],"size":[3,1,1]' in FORTRESS_PLAN_SYSTEM_PROMPT
    assert '"area":[58,35,0],"size":[5,5,1]' in FORTRESS_PLAN_SYSTEM_PROMPT
    assert '"kind":"CarpenterWorkshop","x":59,"y":36,"z":0' in FORTRESS_PLAN_SYSTEM_PROMPT
    assert "fortress_complexity_spaces_completed reaches 2" in FORTRESS_PLAN_SYSTEM_PROMPT


def test_dig_first_agent_uses_custom_prompt(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_FakeAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicDigFirstAgent()
        action = agent.decide("mock observation", {"drink": 100})
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "WAIT"
    assert _FakeAnthropicClient.last_instance is not None
    request = _FakeAnthropicClient.last_instance.messages.requests[0]
    assert request["system"] == DIG_FIRST_SYSTEM_PROMPT


def test_fortress_plan_agent_uses_custom_prompt(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_FakeAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicFortressPlanAgent()
        action = agent.decide("mock observation", {"drink": 100})
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "WAIT"
    assert _FakeAnthropicClient.last_instance is not None
    request = _FakeAnthropicClient.last_instance.messages.requests[0]
    assert request["system"] == FORTRESS_PLAN_SYSTEM_PROMPT


def test_api_accepts_dig_first_model() -> None:
    request = RunCreateRequest(model="anthropic-dig-first", backend="dfhack")
    assert request.model == "anthropic-dig-first"


def test_api_accepts_fortress_plan_model() -> None:
    request = RunCreateRequest(model="anthropic-fortress-plan", backend="dfhack")
    assert request.model == "anthropic-fortress-plan"
