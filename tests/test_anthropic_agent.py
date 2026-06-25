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
    KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
    KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT,
    KEYSTROKE_SYSTEM_PROMPT,
    KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT,
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

    def __init__(self, api_key: str, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.timeout = timeout
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

    def __init__(self, api_key: str, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.messages = _SequencedMessages(list(self.responses))
        _SequencedAnthropicClient.last_instance = self


def _messages_text(messages: Any) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
            return
        if isinstance(value, dict):
            for nested in value.values():
                walk(nested)
            return
        if isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(messages)
    return "\n".join(parts)


class _FakeRateLimitError(Exception):
    status_code = 429


class _FakeTimeoutError(Exception):
    pass


class _RateLimitOnceMessages:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            raise _FakeRateLimitError("rate limited")
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "recover after rate limit",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        )


class _RateLimitOnceAnthropicClient:
    last_instance: "_RateLimitOnceAnthropicClient | None" = None

    def __init__(self, api_key: str, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.messages = _RateLimitOnceMessages()
        _RateLimitOnceAnthropicClient.last_instance = self


class _TimeoutOnceMessages:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            raise _FakeTimeoutError("request timed out")
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "recover after timeout",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        )


class _TimeoutOnceAnthropicClient:
    last_instance: "_TimeoutOnceAnthropicClient | None" = None

    def __init__(self, api_key: str, timeout: float | None = None) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.messages = _TimeoutOnceMessages()
        _TimeoutOnceAnthropicClient.last_instance = self


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
    monkeypatch.setenv("ANTHROPIC_TIMEOUT_SECONDS", "17.5")
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
    assert _FakeAnthropicClient.last_instance.timeout == 17.5
    request = _FakeAnthropicClient.last_instance.messages.requests[0]
    assert request["model"] == "claude-sonnet-4-6"


def test_keystroke_prompt_is_action_first() -> None:
    assert "FRESH TARGET RULE" in KEYSTROKE_SYSTEM_PROMPT
    assert "MAINTAIN YOUR OWN MAP MEMORY" in KEYSTROKE_SYSTEM_PROMPT
    assert "D_DESIGNATE" in KEYSTROKE_SYSTEM_PROMPT
    assert "D_BUILDING" in KEYSTROKE_SYSTEM_PROMPT
    assert "HOTKEY_BUILDING_WORKSHOP_CARPENTER" in KEYSTROKE_SYSTEM_PROMPT
    assert "STOCKPILE_WOOD" in KEYSTROKE_SYSTEM_PROMPT
    assert "not STRING_A119" in KEYSTROKE_SYSTEM_PROMPT
    assert "cursor_inactive=(-30000,...)" in KEYSTROKE_SYSTEM_PROMPT
    assert "not proof" in KEYSTROKE_SYSTEM_PROMPT
    assert "future cursor movement" in KEYSTROKE_SYSTEM_PROMPT
    assert "subtracting `selection_rect` from `window`" in KEYSTROKE_SYSTEM_PROMPT
    assert "not a manual cursor-navigation recipe" in KEYSTROKE_SYSTEM_PROMPT
    assert "use `STRING_A032`; do not" in KEYSTROKE_SYSTEM_PROMPT
    assert "use `PAUSE`" in KEYSTROKE_SYSTEM_PROMPT
    assert "complete a work designation" in KEYSTROKE_SYSTEM_PROMPT
    assert "advance_ticks to 500+" in KEYSTROKE_SYSTEM_PROMPT
    assert "advance_ticks\": 500" in KEYSTROKE_SYSTEM_PROMPT
    assert "Do not" in KEYSTROKE_SYSTEM_PROMPT
    assert "repeat the same key sequence" in KEYSTROKE_SYSTEM_PROMPT
    assert "expected_visible_result" in KEYSTROKE_SYSTEM_PROMPT
    assert "expected_simulation_result" in KEYSTROKE_SYSTEM_PROMPT


def test_poi_review_prompt_requires_memory_review() -> None:
    assert "Mandatory POI/Task Review Variant" in KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT
    assert "Before EVERY submit_action" in KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT
    assert "query_memory" in KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT
    assert "remember_failed_attempt" in KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT


def test_plan_review_prompt_requires_periodic_plan_reviews() -> None:
    assert "Periodic Gameplay Plan Review Variant" in KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT
    assert "write_gameplay_plan" in KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT
    assert "review_gameplay_plan" in KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT
    assert "every five submitted actions" in KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT
    assert "plan_step" in KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT
    assert "post-workshop branch" in KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT


def test_perception_review_prompt_requires_agent_owned_verification() -> None:
    assert "Agent-Owned Perception and Verification Contract" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "screen_read" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "last_action_review" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "record_screen_read" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "review_last_action" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "The harness only" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "does not classify menus" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "Distinguish a visible X cursor" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    assert "`selection_rect` and `window` alone do not satisfy" in (
        KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT
    )
    assert "should_retry_same_path" in KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT


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


def test_keystroke_agent_records_memory_tool_before_returning_action(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="remember_poi",
                    id="toolu_memory",
                    input={
                        "label": "carpenter workshop",
                        "kind": "building",
                        "x": 99,
                        "y": 96,
                        "z": 177,
                        "status": "built",
                        "evidence": "carpenter_workshops increased",
                    },
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "return to map",
                        "advance_ticks": 0,
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        )
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
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert any(event.get("tool") == "remember_poi" for event in events)
    assert "carpenter workshop" in agent._memory.get_context()


def test_keystroke_agent_retries_rate_limit(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setattr("fort_gym.bench.agent.llm_anthropic.time.sleep", lambda _: None)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_RateLimitOnceAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicKeystrokeAgent()
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["intent"] == "recover after rate limit"
    assert any(event.get("tool") == "anthropic.rate_limit_retry" for event in events)
    assert _RateLimitOnceAnthropicClient.last_instance is not None
    assert len(_RateLimitOnceAnthropicClient.last_instance.messages.requests) == 2


def test_keystroke_agent_retries_timeout(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MAX_ATTEMPTS", "2")
    monkeypatch.setattr("fort_gym.bench.agent.llm_anthropic.time.sleep", lambda _: None)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_TimeoutOnceAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicKeystrokeAgent()
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["intent"] == "recover after timeout"
    assert any(event.get("tool") == "anthropic.request_retry" for event in events)
    assert _TimeoutOnceAnthropicClient.last_instance is not None
    assert len(_TimeoutOnceAnthropicClient.last_instance.messages.requests) == 2


def test_keystroke_agent_retries_malformed_params(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_bad_params",
                    input={
                        "type": "KEYSTROKE",
                        "params": "LEAVESCREEN",
                        "intent": "malformed params should be retried",
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
                    id="toolu_good_params",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "recover with valid params",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
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

    assert action["params"]["keys"] == ["LEAVESCREEN"]
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry_messages = _messages_text(requests[1]["messages"])
    assert "KEYSTROKE action requires a non-empty keys list" in retry_messages


def test_poi_review_agent_retries_without_query_memory(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_no_review",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "escape",
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
                    name="query_memory",
                    id="toolu_query",
                    input={"query": "current objective", "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "escape after memory review",
                        "objective": "recover to main map",
                        "expected_visible_result": "main map visible",
                        "expected_simulation_result": "none; UI-only paused planning action",
                        "memory_update": "queried current objective memory",
                        "advance_ticks": 0,
                    },
                ),
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT,
            require_memory_review=True,
        )
        action = agent.decide("mock screen", {})
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert action["objective"] == "recover to main map"
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry = requests[1]["messages"][2]["content"][0]
    assert retry["tool_use_id"] == "toolu_no_review"
    assert "Mandatory pre-action review missing" in retry["content"]


def test_poi_review_agent_requires_failed_attempt_memory_after_no_progress(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_1",
                    input={"query": "blocked workshop placement", "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_no_failure",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_BUILDING"]},
                        "intent": "retry workshop placement",
                        "advance_ticks": 0,
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_2",
                    input={"query": "blocked workshop placement", "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="remember_failed_attempt",
                    id="toolu_failed",
                    input={
                        "label": "blocked workshop placement",
                        "reason": "no_progress_streak reached 2",
                        "evidence": "last action changed no tracked tiles",
                    },
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_DESIGNATE", "DESIGNATE_DIG"]},
                        "intent": "switch to digging after failed placement",
                        "objective": "make productive progress",
                        "expected_visible_result": "dig designation menu opens",
                        "expected_simulation_result": "none until area is selected",
                        "memory_update": "recorded failed workshop placement",
                        "advance_ticks": 0,
                    },
                ),
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT,
            require_memory_review=True,
        )
        action = agent.decide(
            "== STATUS ==\nLive UI feedback: last_action_work_delta=0, no_progress_streak=2\n",
            {},
        )
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["intent"] == "switch to digging after failed placement"
    assert any(event.get("tool") == "remember_failed_attempt" for event in events)


def test_poi_review_agent_rejects_repeated_workshop_placement(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_1",
                    input={"query": "workshop placement", "limit": 5},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_workshop",
                    input={
                        "type": "KEYSTROKE",
                        "params": {
                            "keys": [
                                "D_BUILDING",
                                "HOTKEY_BUILDING_WORKSHOP",
                                "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
                                "SELECT",
                            ]
                        },
                        "intent": "retry carpenter workshop placement",
                        "advance_ticks": 0,
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_2",
                    input={"query": "fresh target", "limit": 5},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_DESIGNATE", "DESIGNATE_DIG"]},
                        "intent": "switch away from failed workshop placement",
                        "objective": "make productive digging progress",
                        "expected_visible_result": "designation menu opens",
                        "expected_simulation_result": "none until area selected",
                        "memory_update": "reviewed failed workshop placement and switched strategy",
                        "advance_ticks": 0,
                    },
                ),
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

    obs = (
        "== MEMORY ==\n"
        "Recent Failed Attempts:\n"
        "- failed workshop placement: blocked cursor, no tracked state change\n"
        "== RECENT ACTION OUTCOMES ==\n"
        "Step 13: Carpenter workshop placement outcome=keys_sent_without_tracked_state_change; changed=none\n"
        "Step 14: Carpenter workshop placement outcome=keys_sent_without_tracked_state_change; changed=none\n"
    )
    try:
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_POI_REVIEW_SYSTEM_PROMPT,
            require_memory_review=True,
        )
        action = agent.decide(obs, {})
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["intent"] == "switch away from failed workshop placement"
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry = requests[1]["messages"][2]["content"][1]
    assert retry["tool_use_id"] == "toolu_workshop"
    assert "Workshop placement loop detected" in retry["content"]


def test_plan_review_agent_requires_initial_plan(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_1",
                    input={"query": "current objective", "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_no_plan",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_DESIGNATE"]},
                        "intent": "start digging without plan",
                        "objective": "dig",
                        "advance_ticks": 0,
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_2",
                    input={"query": "current objective", "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="write_gameplay_plan",
                    id="toolu_plan",
                    input={
                        "objective": "complete useful fortress space",
                        "phase": "starter excavation",
                        "steps": [
                            "dig reachable starter access",
                            "acquire usable building material",
                            "place one carpenter workshop",
                            "finish planned room or stockpile",
                        ],
                        "current_step": "dig reachable starter access",
                        "reason": "initial hill-climbing plan",
                        "evidence": "first observation",
                    },
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_DESIGNATE"]},
                        "intent": "start planned digging",
                        "objective": "dig reachable starter access",
                        "expected_visible_result": "designation menu opens",
                        "expected_simulation_result": "none until area selected",
                        "memory_update": "queried current objective",
                        "plan_step": "dig reachable starter access",
                        "plan_review": "initial plan written",
                        "advance_ticks": 0,
                    },
                ),
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT,
            require_memory_review=True,
            require_plan_review=True,
        )
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["plan_step"] == "dig reachable starter access"
    assert any(event.get("tool") == "write_gameplay_plan" for event in events)
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry = requests[1]["messages"][2]["content"][1]
    assert retry["tool_use_id"] == "toolu_no_plan"
    assert "Mandatory gameplay plan missing" in retry["content"]


def test_plan_review_agent_requires_checkpoint_review(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_1",
                    input={"query": "plan checkpoint", "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_no_review",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "continue without plan review",
                        "objective": "recover",
                        "advance_ticks": 0,
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query_2",
                    input={"query": "plan checkpoint", "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="review_gameplay_plan",
                    id="toolu_review",
                    input={
                        "status": "needs_revision",
                        "evidence": "checkpoint after five submitted actions",
                        "completed_steps": ["place one carpenter workshop"],
                        "blockers": ["workshop loop risk"],
                        "next_step": "complete planned room space",
                        "revised_steps": [
                            "exit build menu",
                            "designate room completion target",
                            "advance ticks",
                        ],
                        "reason": "post-workshop phase should not place more workshops",
                    },
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "exit build menu before room work",
                        "objective": "complete planned room space",
                        "expected_visible_result": "main view visible",
                        "expected_simulation_result": "none; UI-only recovery",
                        "memory_update": "queried checkpoint memory",
                        "plan_step": "complete planned room space",
                        "plan_review": "checkpoint review revised post-workshop branch",
                        "advance_ticks": 0,
                    },
                ),
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT,
            require_memory_review=True,
            require_plan_review=True,
            plan_review_interval=5,
        )
        agent._memory.write_gameplay_plan(
            objective="complete useful fortress space",
            steps=["place one carpenter workshop", "complete planned room space"],
            current_step="complete planned room space",
        )
        agent._completed_actions = 5
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["plan_review"] == "checkpoint review revised post-workshop branch"
    assert any(event.get("tool") == "review_gameplay_plan" for event in events)
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry = requests[1]["messages"][2]["content"][1]
    assert retry["tool_use_id"] == "toolu_no_review"
    assert "Mandatory gameplay plan review missing" in retry["content"]


def test_plan_review_agent_falls_back_if_model_stops_submitting_after_gate(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_candidate",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "candidate action missing reviews",
                        "objective": "recover",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        *[
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="query_memory",
                        id=f"toolu_query_{index}",
                        input={"query": "recover", "limit": 3},
                    )
                ],
                usage=SimpleNamespace(input_tokens=11 + index, output_tokens=2),
            )
            for index in range(4)
        ],
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_SequencedAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PLAN_REVIEW_SYSTEM_PROMPT,
            require_memory_review=True,
            require_plan_review=True,
        )
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["intent"] == "candidate action missing reviews"
    assert any(event.get("tool") == "plan_review_gate_warning" for event in events)
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 5


def test_perception_review_agent_collects_screen_read_before_action(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="record_screen_read",
                    id="toolu_screen",
                    input={
                        "mode": "main_map",
                        "evidence": ["main game view visible"],
                        "cursor_or_selection": "map cursor visible",
                        "confidence": "medium",
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="review_last_action",
                    id="toolu_review",
                    input={
                        "worked": None,
                        "evidence": ["first action; no previous submitted action"],
                        "mismatch_reason": None,
                        "should_retry_same_path": False,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_DESIGNATE"]},
                        "intent": "open designations after reading the screen",
                        "objective": "dig reachable starter space",
                        "expected_visible_result": "designation menu opens",
                        "expected_simulation_result": "none until an area is selected",
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
            require_perception_review=True,
        )
        action = agent.decide("mock screen", {})
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["screen_read"]["mode"] == "main_map"
    assert action["last_action_review"]["worked"] is None
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 3
    assert {tool["name"] for tool in requests[0]["tools"]} == {"record_screen_read"}
    assert {tool["name"] for tool in requests[1]["tools"]} == {"review_last_action"}
    required_fields = requests[2]["tools"][0]["input_schema"]["required"]
    assert "screen_read" in required_fields
    assert "last_action_review" in required_fields
    assert "advance_ticks" in required_fields
    tool_names = {tool["name"] for tool in requests[2]["tools"]}
    assert {"record_screen_read", "review_last_action"}.issubset(tool_names)


def test_keystroke_perception_review_forces_submit_after_tool_only_action_phase(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="record_screen_read",
                    id="toolu_screen",
                    input={
                        "mode": "main_map",
                        "evidence": ["main map terrain visible"],
                        "cursor_or_selection": "cursor near embark",
                        "confidence": "medium",
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="review_last_action",
                    id="toolu_review",
                    input={
                        "worked": None,
                        "evidence": ["first action; no previous submitted action"],
                        "mismatch_reason": None,
                        "should_retry_same_path": False,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
        ),
        *[
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="query_memory",
                        id=f"toolu_query_{index}",
                        input={"query": "dig designation menu", "limit": 3},
                    )
                ],
                usage=SimpleNamespace(input_tokens=12 + index, output_tokens=2),
            )
            for index in range(5)
        ],
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_DESIGNATE"]},
                        "intent": "open designations after tool review",
                        "objective": "dig reachable starter space",
                        "expected_visible_result": "designation menu opens",
                        "expected_simulation_result": "none until area selection",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=20, output_tokens=3),
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
            require_perception_review=True,
        )
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["D_DESIGNATE"]
    assert action["screen_read"]["mode"] == "main_map"
    assert action["last_action_review"]["worked"] is None
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 8
    assert {tool["name"] for tool in requests[-1]["tools"]} == {"submit_action"}
    assert len(requests[-1]["messages"]) == 1
    assert "ACTION-ONLY RECOVERY" in _messages_text(requests[-1]["messages"])
    assert any(event.get("tool") == "submit_action_forced_after_tools" for event in events)


def test_keystroke_perception_force_submit_warns_on_unmet_memory_gate(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="record_screen_read",
                    id="toolu_screen",
                    input={
                        "mode": "main_map",
                        "evidence": ["main map terrain visible"],
                        "cursor_or_selection": "cursor_inactive",
                        "confidence": "high",
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="review_last_action",
                    id="toolu_review",
                    input={
                        "worked": False,
                        "evidence": ["last action changed no tracked tiles"],
                        "mismatch_reason": "no_progress_streak reached 2",
                        "should_retry_same_path": False,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
        ),
        *[
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="query_memory",
                        id=f"toolu_query_{index}",
                        input={"query": "no-progress recovery", "limit": 3},
                    )
                ],
                usage=SimpleNamespace(input_tokens=12 + index, output_tokens=2),
            )
            for index in range(5)
        ],
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["STRING_A032"]},
                        "intent": "advance time after tool-only recovery",
                        "objective": "let existing work proceed",
                        "expected_visible_result": "game resumes",
                        "expected_simulation_result": "dwarves work on queued jobs",
                        "advance_ticks": 500,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=20, output_tokens=3),
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
            require_perception_review=True,
            require_memory_review=True,
        )
        action = agent.decide(
            "== STATUS ==\nLive UI feedback: last_action_work_delta=0, no_progress_streak=2\n",
            {},
        )
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["STRING_A032"]
    assert action["screen_read"]["mode"] == "main_map"
    assert action["last_action_review"]["worked"] is False
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 8
    assert {tool["name"] for tool in requests[-1]["tools"]} == {"submit_action"}
    assert any(
        event.get("tool") == "memory_review_gate_forced_warning"
        for event in events
    )
    assert any(event.get("tool") == "submit_action_forced_after_tools" for event in events)


def test_keystroke_review_gates_count_prior_tools_in_same_decision(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="record_screen_read",
                    id="toolu_screen",
                    input={
                        "mode": "main_map",
                        "evidence": ["main map terrain visible"],
                        "cursor_or_selection": "cursor near embark",
                        "confidence": "medium",
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="review_last_action",
                    id="toolu_review",
                    input={
                        "worked": None,
                        "evidence": ["first action; no previous submitted action"],
                        "mismatch_reason": None,
                        "should_retry_same_path": False,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id="toolu_query",
                    input={"query": "starter dig", "include_failed": True, "limit": 3},
                ),
                SimpleNamespace(
                    type="tool_use",
                    name="write_gameplay_plan",
                    id="toolu_plan",
                    input={
                        "objective": "start a real fortress",
                        "phase": "access",
                        "steps": ["dig a staircase", "mine space", "build workshop"],
                        "current_step": "dig a staircase",
                        "reason": "fresh embark needs access",
                        "evidence": "main map visible",
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=12, output_tokens=5),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["D_DESIGNATE"]},
                        "intent": "open designations after reviewing memory and plan",
                        "objective": "dig reachable starter space",
                        "expected_visible_result": "designation menu opens",
                        "expected_simulation_result": "none until area selection",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=13, output_tokens=3),
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
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
            require_memory_review=True,
            require_plan_review=True,
            require_perception_review=True,
        )
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["D_DESIGNATE"]
    assert action["screen_read"]["mode"] == "main_map"
    assert action["last_action_review"]["worked"] is None
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 4
    assert not any("gate_warning" in event.get("tool", "") for event in events)


def test_keystroke_agent_rejects_advance_intent_with_zero_ticks(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_bad_wait",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["STANDARDSCROLL_PAGEDOWN"]},
                        "intent": "Advance time to let dwarves work on existing designations",
                        "objective": "let dwarves work",
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
                    id="toolu_good_wait",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["STANDARDSCROLL_PAGEDOWN"]},
                        "intent": "Advance time to let dwarves work on existing designations",
                        "objective": "let dwarves work",
                        "advance_ticks": 500,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
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

    assert action["advance_ticks"] == 500
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry_messages = _messages_text(requests[1]["messages"])
    assert "Action contract mismatch" in retry_messages


def test_keystroke_agent_rejects_completed_designation_with_zero_ticks(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    designation_keys = [
        "D_DESIGNATE",
        "DESIGNATE_CHOP",
        "SELECT",
        "CURSOR_RIGHT",
        "SELECT",
        "LEAVESCREEN",
    ]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_bad_designation",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": designation_keys},
                        "intent": "mark a chop designation on visible trees",
                        "objective": "create woodcutting work",
                        "expected_visible_result": "tree tiles are marked for chopping",
                        "expected_simulation_result": "dwarves chop trees for logs",
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
                    id="toolu_good_designation",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": designation_keys},
                        "intent": "mark a chop designation on visible trees",
                        "objective": "create woodcutting work",
                        "expected_visible_result": "tree tiles are marked for chopping",
                        "expected_simulation_result": "dwarves chop trees for logs",
                        "advance_ticks": 500,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
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

    assert action["advance_ticks"] == 500
    assert _SequencedAnthropicClient.last_instance is not None
    requests = _SequencedAnthropicClient.last_instance.messages.requests
    assert len(requests) == 2
    retry_messages = _messages_text(requests[1]["messages"])
    assert "completes a dig/chop/stair designation" in retry_messages


def test_keystroke_opus_model_omits_temperature(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_OPUS_MODEL", "claude-opus-4-8")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="record_screen_read",
                    id="toolu_screen",
                    input={
                        "mode": "unknown",
                        "evidence": ["mock screen has no visible detail"],
                        "cursor_or_selection": "unknown",
                        "confidence": "low",
                    },
                ),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="review_last_action",
                    id="toolu_review",
                    input={
                        "worked": None,
                        "evidence": ["first action; no previous submitted action"],
                        "mismatch_reason": None,
                        "should_retry_same_path": False,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=11, output_tokens=2),
        ),
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_action",
                    id="toolu_action",
                    input={
                        "type": "KEYSTROKE",
                        "params": {"keys": ["LEAVESCREEN"]},
                        "intent": "recover after screen review",
                        "objective": "return to main map",
                        "advance_ticks": 0,
                    },
                )
            ],
            usage=SimpleNamespace(input_tokens=12, output_tokens=3),
        )
    ]

    def fake_import_module(name: str) -> Any:
        assert name == "anthropic"
        return SimpleNamespace(Anthropic=_SequencedAnthropicClient)

    monkeypatch.setattr(
        "fort_gym.bench.agent.llm_anthropic.import_module",
        fake_import_module,
    )

    try:
        agent = AnthropicKeystrokeAgent(
            system_prompt=KEYSTROKE_PERCEPTION_REVIEW_SYSTEM_PROMPT,
            require_perception_review=True,
            model_override=get_settings().ANTHROPIC_OPUS_MODEL,
        )
        action = agent.decide("mock screen", {})
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["params"]["keys"] == ["LEAVESCREEN"]
    assert _SequencedAnthropicClient.last_instance is not None
    request = _SequencedAnthropicClient.last_instance.messages.requests[0]
    assert request["model"] == "claude-opus-4-8"
    assert "temperature" not in request
    assert events[0]["input"] == {
        "model": "claude-opus-4-8",
        "max_tokens": 512,
    }


def test_keystroke_agent_falls_back_after_tool_only_responses(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _SequencedAnthropicClient.responses = [
        SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="query_memory",
                    id=f"toolu_query_{index}",
                    input={"query": "stockpile menu", "limit": 3},
                )
            ],
            usage=SimpleNamespace(input_tokens=10 + index, output_tokens=2),
        )
        for index in range(5)
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
        events = agent.pop_tool_events()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert action["type"] == "KEYSTROKE"
    assert action["params"]["keys"] == ["LEAVESCREEN"]
    assert action["intent"].startswith("fallback:")
    assert any(event.get("tool") == "submit_action_fallback" for event in events)
    assert _SequencedAnthropicClient.last_instance is not None
    assert len(_SequencedAnthropicClient.last_instance.messages.requests) == 5


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
