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
    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[Any] | None = None,
        responses: list[dict[str, Any]] | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self.content = content
        self.tool_calls = tool_calls
        self.responses = list(responses or [])

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self.responses:
            response = self.responses.pop(0)
            tool_calls = response.get("tool_calls", self.tool_calls)
            content = response.get("content", self.content)
        else:
            tool_calls = self.tool_calls
            content = self.content
        if tool_calls is None and content is None:
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
                        content=content,
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
    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[Any] | None = None,
        responses: list[dict[str, Any]] | None = None,
    ) -> None:
        self.completions = _FakeOpenRouterCompletions(
            content=content,
            tool_calls=tool_calls,
            responses=responses,
        )


class _FakeOpenRouterClient:
    last_instance: "_FakeOpenRouterClient | None" = None
    content: str | None = None
    tool_calls: list[Any] | None = None
    responses: list[dict[str, Any]] | None = None

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
        self.chat = _FakeOpenRouterChat(
            content=self.content,
            tool_calls=self.tool_calls,
            responses=self.responses,
        )
        _FakeOpenRouterClient.last_instance = self


def _submit_action_call(payload: dict[str, Any], call_id: str = "call_submit") -> Any:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name="submit_action",
            arguments=json.dumps(payload),
        ),
    )


def _tool_call(name: str, payload: dict[str, Any], call_id: str) -> Any:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(payload),
        ),
    )


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
    assert request["extra_body"] == {"reasoning": {"enabled": False, "exclude": True}}
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


def test_openrouter_agent_unwraps_nested_action_tool_payload(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        _submit_action_call(
            {
                "action": {
                    "type": "KEYSTROKE",
                    "params": {"keys": ["SELECT"]},
                    "intent": "confirm visible menu",
                    "advance_ticks": 0,
                }
            }
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

    assert action["params"]["keys"] == ["SELECT"]
    assert any(event["tool"] == "action_contract_repaired" for event in events)


def test_openrouter_agent_recovers_empty_nested_action_with_plain_json(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MAX_TOOL_ROUNDS", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.responses = [
        {"tool_calls": [_submit_action_call({"action": {}})]},
        {
            "tool_calls": [],
            "content": json.dumps(
                {
                    "type": "KEYSTROKE",
                    "params": {"keys": ["LEAVESCREEN"]},
                    "intent": "recover from malformed tool call",
                    "advance_ticks": 0,
                }
            ),
        },
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide("mock observation", {"pause_state": True})
        events = agent.pop_tool_events()
        requests = _FakeOpenRouterClient.last_instance.chat.completions.requests
    finally:
        _FakeOpenRouterClient.responses = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["LEAVESCREEN"]
    assert "tools" not in requests[-1]
    assert any(event["tool"] == "openrouter.plain_json_action" for event in events)


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


def test_openrouter_action_only_repairs_escape_tick_advance(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        _submit_action_call(
            {
                "type": "KEYSTROKE",
                "params": {"keys": ["LEAVESCREEN", "LEAVESCREEN"]},
                "intent": "Escape from the repeated blocked menu path",
                "objective": "Return to the main map before choosing another route",
                "advance_ticks": 500,
            }
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

    assert action["params"]["keys"] == ["LEAVESCREEN", "LEAVESCREEN"]
    assert action["advance_ticks"] == 0
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


def test_openrouter_agent_repairs_missing_keystroke_type(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        SimpleNamespace(
            id="call_submit",
            function=SimpleNamespace(
                name="submit_action",
                arguments=json.dumps(
                    {
                        "params": {"keys": ["STRING_A032"]},
                        "intent": "Advance time so dwarves can work the queued bed order",
                        "objective": "Let dwarves work the queued bed production order",
                        "expected_visible_result": "Main map view with time advanced",
                        "expected_simulation_result": "order_qty_left should decrease",
                        "advance_ticks": 1000,
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

    assert action["type"] == "KEYSTROKE"
    assert action["params"]["keys"] == ["STRING_A032"]
    assert action["advance_ticks"] == 1000
    assert any(event["tool"] == "action_contract_repaired" for event in events)


def test_openrouter_agent_repairs_review_only_escape_action(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        SimpleNamespace(
            id="call_submit",
            function=SimpleNamespace(
                name="submit_action",
                arguments=json.dumps(
                    {
                        "intent": (
                            "Exit the current unit info screen and return to the main map. "
                            "I have been stuck in the Nobles screen loop."
                        ),
                        "expected_visible_result": "Should see the main map again",
                        "expected_simulation_result": "none - UI navigation only",
                        "last_action_review": {
                            "worked": False,
                            "should_retry_same_path": False,
                            "mismatch_reason": (
                                "The current screen is a unit info screen, not the Nobles list."
                            ),
                        },
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

    assert action["type"] == "KEYSTROKE"
    assert action["params"]["keys"] == ["LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN"]
    assert action["advance_ticks"] == 0
    assert any(
        event["tool"] == "action_contract_repaired"
        and event["input"]["missing"] == "type_and_keys"
        for event in events
    )


def test_openrouter_agent_repairs_compound_action_after_menu_loop(monkeypatch) -> None:
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
                        "params": {
                            "keys": ["LEAVESCREEN", "LEAVESCREEN", "D_NOBLES"]
                        },
                        "intent": "Escape, then open Nobles again to appoint manager",
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
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "recent_progress_summary": {
                    "do_not_repeat_menu_path": True,
                    "escape_recovery_attempted": False,
                    "repeated_menu_family": "manager_nobles_menu",
                    "repeated_key_fingerprint": "D_NOBLES CURSOR_DOWN SELECT",
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert action["params"]["keys"] == ["LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN"]
    assert action["intent"].startswith("Recover from repeated no-progress menu loop")
    assert any(event["tool"] == "menu_loop_recovery_repaired" for event in events)


def test_openrouter_agent_rejects_blocked_menu_family_after_escape(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    blocked_workshop_retry = {
        "type": "KEYSTROKE",
        "params": {
            "keys": [
                "LEAVESCREEN",
                "D_BUILDING",
                "HOTKEY_BUILDING_WORKSHOP",
                "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
            ]
        },
        "intent": "Reopen carpenter workshop placement after escaping",
        "advance_ticks": 0,
    }
    alternate_designation = {
        "type": "KEYSTROKE",
        "params": {
            "keys": [
                "D_DESIGNATE",
                "DESIGNATE_CHOP",
                "SELECT",
                "CURSOR_RIGHT",
                "SELECT",
                "LEAVESCREEN",
            ]
        },
        "intent": "Use a different branch by acquiring more wood before retrying workshop placement",
        "advance_ticks": 500,
    }
    _FakeOpenRouterClient.responses = [
        {"tool_calls": [_submit_action_call(blocked_workshop_retry, "call_blocked")]},
        {"tool_calls": [_submit_action_call(alternate_designation, "call_alt")]},
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "recent_progress_summary": {
                    "do_not_repeat_menu_path": True,
                    "escape_recovery_attempted": True,
                    "repeated_menu_family": "workshop_task_menu",
                    "repeated_key_fingerprint": "D_BUILDJOB BUILDJOB_ADD SELECT",
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.responses = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert action["params"]["keys"][0] == "D_DESIGNATE"
    assert any(event["tool"] == "blocked_menu_path_rejected" for event in events)


def test_openrouter_agent_falls_back_when_blocked_menu_family_repeats(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MAX_TOOL_ROUNDS", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        _submit_action_call(
            {
                "type": "KEYSTROKE",
                "params": {
                    "keys": [
                        "LEAVESCREEN",
                        "D_BUILDING",
                        "HOTKEY_BUILDING_WORKSHOP",
                        "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
                    ]
                },
                "intent": "Reopen carpenter workshop placement after escaping",
                "advance_ticks": 0,
            }
        )
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "recent_progress_summary": {
                    "do_not_repeat_menu_path": True,
                    "escape_recovery_attempted": True,
                    "repeated_menu_family": "building_placement_menu",
                    "repeated_key_fingerprint": "D_BUILDING HOTKEY_BUILDING_WORKSHOP",
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN"]
    assert any(event["tool"] == "blocked_menu_path_fallback" for event in events)


def test_openrouter_agent_repairs_missing_screen_read_from_classifier(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        _submit_action_call(
            {
                "type": "KEYSTROKE",
                "params": {"keys": ["D_NOBLES"]},
                "intent": "Open Nobles and Administrators to appoint a manager",
                "objective": "Resolve the visible manager-required production blocker",
                "expected_visible_result": "Nobles and Administrators screen opens",
                "advance_ticks": 0,
            }
        )
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "screen_state": {
                    "mode": "manager_required",
                    "confidence": "high",
                    "evidence": ["visible text says a manager is required"],
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["D_NOBLES"]
    assert action["screen_read"]["mode"] == "manager_required"
    assert action["screen_read"]["evidence"] == ["visible text says a manager is required"]
    assert any(event["tool"] == "screen_read_contract_repaired" for event in events)


def test_openrouter_agent_repairs_string_review_metadata(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        _submit_action_call(
            {
                "type": "KEYSTROKE",
                "params": {"keys": ["LEAVESCREEN", "LEAVESCREEN", "D_NOBLES"]},
                "intent": "Exit manager orders and open Nobles to appoint a manager",
                "screen_read": "The screen says a manager is required.",
                "last_action_review": (
                    "UNITJOB_MANAGER worked as navigation but exposed a missing "
                    "manager blocker."
                ),
                "advance_ticks": 0,
            }
        )
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "screen_state": {
                    "mode": "manager_required",
                    "confidence": "high",
                    "evidence": ["visible text says a manager is required"],
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["LEAVESCREEN", "LEAVESCREEN", "D_NOBLES"]
    assert action["screen_read"]["mode"] == "manager_required"
    assert action["last_action_review"]["evidence"] == [
        "UNITJOB_MANAGER worked as navigation but exposed a missing manager blocker."
    ]
    assert any(
        event["tool"] == "action_contract_repaired"
        and event["input"]["metadata_fields"] == {
            "screen_read": "str",
            "last_action_review": "str",
        }
        for event in events
    )


def test_openrouter_agent_rejects_ignoring_fresh_material_target(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    recommended_payload = {
        "type": "KEYSTROKE",
        "params": {
            "keys": [
                "D_DESIGNATE",
                "DESIGNATE_CHOP",
                "SELECT",
                "CURSOR_RIGHT",
                "SELECT",
                "LEAVESCREEN",
            ]
        },
        "intent": "Copy the fresh material target keys to acquire logs",
        "advance_ticks": 1000,
    }
    _FakeOpenRouterClient.responses = [
        {
            "tool_calls": [
                _submit_action_call(
                    {
                        "type": "KEYSTROKE",
                        "params": {
                            "keys": [
                                "D_BUILDING",
                                "HOTKEY_BUILDING_WORKSHOP",
                                "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
                            ]
                        },
                        "intent": "Try workshop placement with starter wood",
                        "advance_ticks": 0,
                    },
                    "call_bad",
                )
            ]
        },
        {"tool_calls": [_submit_action_call(recommended_payload, "call_good")]},
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "ui_run_progress": {"total_material_delta": 0},
                "ui_target_setup": {
                    "target_mode": "material",
                    "show_recommended_keys": True,
                    "recommended_keys": recommended_payload["params"]["keys"],
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.responses = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == recommended_payload["params"]["keys"]
    assert any(event["tool"] == "material_target_contract_rejected" for event in events)


def test_openrouter_agent_rejects_short_tree_chop_tick_advance(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    keys = [
        "D_DESIGNATE",
        "DESIGNATE_CHOP",
        "SELECT",
        "CURSOR_RIGHT",
        "SELECT",
        "LEAVESCREEN",
    ]
    _FakeOpenRouterClient.responses = [
        {
            "tool_calls": [
                _submit_action_call(
                    {
                        "type": "KEYSTROKE",
                        "params": {"keys": keys},
                        "intent": "Copy the fresh material target keys to acquire logs",
                        "advance_ticks": 500,
                    },
                    "call_short",
                )
            ]
        },
        {
            "tool_calls": [
                _submit_action_call(
                    {
                        "type": "KEYSTROKE",
                        "params": {"keys": keys},
                        "intent": "Copy the fresh material target keys and wait longer",
                        "advance_ticks": 1000,
                    },
                    "call_long",
                )
            ]
        },
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "ui_run_progress": {"total_material_delta": 0},
                "ui_target_setup": {
                    "target_mode": "material",
                    "show_recommended_keys": True,
                    "recommended_keys": keys,
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.responses = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["advance_ticks"] == 1000
    assert any(
        event["tool"] == "material_target_contract_rejected"
        and "advance_ticks must be at least 1000" in event["output"]
        for event in events
    )


def test_openrouter_agent_allows_ui_only_buildjob_with_zero_ticks(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _FakeOpenRouterClient.tool_calls = [
        _submit_action_call(
            {
                "type": "KEYSTROKE",
                "params": {"keys": ["D_BUILDJOB"]},
                "intent": "Open building task interface for the carpenter workshop",
                "objective": "Start direct workshop production by opening the UI",
                "expected_visible_result": "Building task interface opens",
                "expected_simulation_result": (
                    "No simulation time passes; this is a UI mode change."
                ),
                "advance_ticks": 0,
            }
        )
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent()
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "screen_state": {"mode": "main_map", "confidence": "medium"},
            },
        )
    finally:
        _FakeOpenRouterClient.tool_calls = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["D_BUILDJOB"]
    assert action["advance_ticks"] == 0


def test_openrouter_agent_rejects_production_screen_read_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    bad_payload = {
        "type": "KEYSTROKE",
        "params": {"keys": ["SELECT"]},
        "intent": "select the visible workshop task",
        "objective": "queue a carpenter workshop task",
        "expected_visible_result": "task is queued",
        "screen_read": {
            "mode": "main_map",
            "evidence": ["I think the main map is visible"],
            "confidence": "low",
        },
        "last_action_review": {
            "worked": None,
            "evidence": ["first action"],
            "should_retry_same_path": False,
        },
        "advance_ticks": 0,
    }
    good_payload = {
        **bad_payload,
        "screen_read": {
            "mode": "workshop_add_task_list",
            "evidence": ["Carpenter's Workshop", "highlighted Construct Bed (b)"],
            "cursor_or_selection": "Construct Bed (b)",
            "confidence": "high",
        },
    }
    _FakeOpenRouterClient.responses = [
        {
            "tool_calls": [
                _tool_call(
                    "query_memory",
                    {"query": "workshop task", "include_failed": True},
                    "call_memory",
                ),
                _tool_call(
                    "write_gameplay_plan",
                    {
                        "objective": "create production",
                        "steps": ["queue a workshop task"],
                    },
                    "call_plan",
                ),
                _tool_call(
                    "record_screen_read",
                    {
                        "mode": "main_map",
                        "evidence": ["incorrectly read as map"],
                        "confidence": "low",
                    },
                    "call_read",
                ),
                _tool_call(
                    "review_last_action",
                    {
                        "worked": None,
                        "evidence": ["first action"],
                        "should_retry_same_path": False,
                    },
                    "call_review",
                ),
                _submit_action_call(bad_payload),
            ]
        },
        {"tool_calls": [_submit_action_call(good_payload, call_id="call_submit_2")]},
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "openai"
        return SimpleNamespace(OpenAI=_FakeOpenRouterClient)

    monkeypatch.setattr("fort_gym.bench.agent.llm_openrouter.import_module", fake_import_module)

    try:
        agent = OpenRouterKeystrokeAgent(
            require_memory_review=True,
            require_plan_review=True,
            require_perception_review=True,
        )
        action = agent.decide(
            "mock observation",
            {
                "pause_state": True,
                "screen_state": {
                    "mode": "workshop_add_task_list",
                    "confidence": "high",
                    "highlighted": "Construct Bed (b)",
                },
            },
        )
        events = agent.pop_tool_events()
    finally:
        _FakeOpenRouterClient.responses = None
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["SELECT"]
    assert action["screen_read"]["mode"] == "workshop_add_task_list"
    assert any(event["tool"] == "screen_read_contract_rejected" for event in events)


def test_anthropic_models_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FORT_GYM_ENABLE_ANTHROPIC", raising=False)

    try:
        _get_agent_factory("anthropic-keystroke")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Anthropic models are disabled" in str(exc.detail)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("anthropic model unexpectedly enabled")
