from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from fort_gym.bench.agent.llm_openrouter import OpenRouterKeystrokeAgent
from fort_gym.bench.api.server import _get_agent_factory
from fort_gym.bench.config import get_settings


class _FakeOpenRouterCompletions:
    def __init__(self, *, content: str | None = None, tool_calls: list[Any] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.content = content
        self.tool_calls = tool_calls

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        tool_calls = self.tool_calls
        if tool_calls is None and self.content is None:
            tool_calls = [
                SimpleNamespace(
                    id="call_submit",
                    function=SimpleNamespace(
                        name="submit_action",
                        arguments=json.dumps(
                            {
                                "type": "KEYSTROKE",
                                "params": {"keys": ["LEAVESCREEN"]},
                                "intent": "exit one menu",
                                "advance_ticks": 0,
                            }
                        ),
                    ),
                )
            ]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=self.content,
                        tool_calls=tool_calls,
                    )
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
            ),
        )


class _FakeOpenRouterChat:
    def __init__(self, *, content: str | None = None, tool_calls: list[Any] | None = None) -> None:
        self.completions = _FakeOpenRouterCompletions(
            content=content,
            tool_calls=tool_calls,
        )


class _FakeOpenRouterClient:
    last_instance: "_FakeOpenRouterClient | None" = None
    content: str | None = None
    tool_calls: list[Any] | None = None

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        max_retries: int = 2,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.max_retries = max_retries
        self.timeout = timeout
        self.chat = _FakeOpenRouterChat(content=self.content, tool_calls=self.tool_calls)
        _FakeOpenRouterClient.last_instance = self


def test_openrouter_defaults_to_glm_5_2(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        assert get_settings().OPENROUTER_MODEL == "z-ai/glm-5.2"
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_openrouter_keystroke_agent_uses_openrouter_client(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "z-ai/glm-5.2")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_TIMEOUT_SECONDS", "12.5")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide("mock observation", {"pause_state": True})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert _FakeOpenRouterClient.last_instance is not None
    assert _FakeOpenRouterClient.last_instance.api_key == "or-test-key"
    assert _FakeOpenRouterClient.last_instance.base_url == "https://openrouter.ai/api/v1"
    assert _FakeOpenRouterClient.last_instance.max_retries == 0
    assert _FakeOpenRouterClient.last_instance.timeout == 12.5
    request = _FakeOpenRouterClient.last_instance.chat.completions.requests[0]
    assert request["model"] == "z-ai/glm-5.2"
    assert request["tools"][0]["function"]["name"] == "submit_action"
    assert events[0] == {
        "tool": "openrouter.chat.completions.create",
        "input": {"model": "z-ai/glm-5.2", "max_tokens": 512, "temperature": 0.1},
        "output": {"usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
    }


def test_openrouter_agent_accepts_json_content_when_tool_call_missing(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "z-ai/glm-5.2")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.content = (
        "```json\n"
        "{\"type\":\"KEYSTROKE\",\"params\":{\"keys\":[\"LEAVESCREEN\"]},"
        "\"intent\":\"exit menu\",\"advance_ticks\":0}"
        "\n```"
    )
    _FakeOpenRouterClient.tool_calls = []

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide("mock observation", {"pause_state": True})
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.content = None
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert action["params"]["keys"] == ["LEAVESCREEN"]
    assert events[-1]["tool"] == "openrouter.content_action"


def test_openrouter_agent_uses_content_fallback_for_empty_submit_args(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.content = json.dumps(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["SELECT"]},
            "intent": "confirm visible menu",
            "advance_ticks": 0,
        }
    )
    _FakeOpenRouterClient.tool_calls = [
        SimpleNamespace(
            id="call_submit",
            function=SimpleNamespace(name="submit_action", arguments="{}"),
        )
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide("mock observation", {"pause_state": True})
    finally:
        _FakeOpenRouterClient.content = None
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["SELECT"]


def test_openrouter_action_only_repairs_zero_tick_space_wait(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        SimpleNamespace(
            id="call_submit",
            function=SimpleNamespace(
                name="submit_action",
                arguments=json.dumps(
                    {
                        "type": "KEYSTROKE",
                        "params": {"keys": ["STRING_A032"]},
                        "intent": "Unpause the game and let dwarves work on existing dig designations",
                        "objective": "Let miners complete the starter excavation",
                        "advance_ticks": 0,
                    }
                ),
            ),
        )
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide("mock observation", {"pause_state": True})
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["STRING_A032"]
    assert action["advance_ticks"] == 500
    assert any(event["tool"] == "advance_ticks_contract_repaired" for event in events)


def test_openrouter_content_action_repairs_zero_tick_wait(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.content = json.dumps(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["STANDARDSCROLL_PAGEDOWN"]},
            "intent": "Advance time to let dwarves work on existing designations",
            "objective": "Wait for mining jobs to complete",
            "advance_ticks": 0,
        }
    )
    _FakeOpenRouterClient.tool_calls = []

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide("mock observation", {"pause_state": True})
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.content = None
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["STANDARDSCROLL_PAGEDOWN"]
    assert action["advance_ticks"] == 500
    assert any(event["tool"] == "advance_ticks_contract_repaired" for event in events)


def test_openrouter_agent_logs_no_tool_responses(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MAX_TOOL_ROUNDS", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.content = "I need to inspect the map before acting."
    _FakeOpenRouterClient.tool_calls = []

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        with pytest.raises(RuntimeError, match="model did not call a tool"):
            agent.decide("mock observation", {"pause_state": True})
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.content = None
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    no_tool_events = [
        event for event in events if event["tool"] == "openrouter.no_tool_response"
    ]
    assert no_tool_events
    assert no_tool_events[0]["output"]["content"] == "I need to inspect the map before acting."


def test_anthropic_models_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FORT_GYM_ENABLE_ANTHROPIC", raising=False)

    try:
        _get_agent_factory("anthropic-keystroke")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Anthropic models are disabled" in str(exc.detail)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("anthropic model unexpectedly enabled")
