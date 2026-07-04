from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import fort_gym.bench.agent.governed_llm  # noqa: F401 - registration side effect
from typing import get_args

from fort_gym.bench.agent.base import AGENT_FACTORIES
from fort_gym.bench.agent.governed_llm import GOVERNED_SYSTEM_PROMPT, DFHackGovernedLLMAgent
from fort_gym.bench.api.schemas import ModelType
from fort_gym.bench.api.server import OPTIONAL_AGENT_MODULES
from fort_gym.bench.run.runner import (
    GOVERNED_DFHACK_MODELS,
    _is_governed_dfhack_model,
    _is_keystroke_model,
)


def _submit_action_response(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_submit",
                            function=SimpleNamespace(
                                name="submit_action",
                                arguments=json.dumps(payload),
                            ),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


class _FakeCompletions:
    def __init__(self, responses: list[Any] | None = None, error: Exception | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses = list(responses or [])
        self.error = error

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses: list[Any] | None = None, error: Exception | None = None) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses, error))


def _agent(responses: list[Any] | None = None, error: Exception | None = None) -> DFHackGovernedLLMAgent:
    agent = DFHackGovernedLLMAgent(api_key="test-key", max_attempts=1, memory_path=None)
    agent._client = _FakeClient(responses, error)
    return agent


def test_governed_system_prompt_teaches_wall_construction() -> None:
    assert "Wall" in GOVERNED_SYSTEM_PROMPT
    assert "x2" in GOVERNED_SYSTEM_PROMPT


def test_governed_llm_is_registered_and_model_gated() -> None:
    assert "dfhack-governed-llm" in AGENT_FACTORIES
    assert "dfhack-governed-llm" in GOVERNED_DFHACK_MODELS
    assert OPTIONAL_AGENT_MODULES["dfhack-governed-llm"] == "fort_gym.bench.agent.governed_llm"
    assert "dfhack-governed-llm" in get_args(ModelType)
    assert _is_governed_dfhack_model("dfhack-governed-llm") is True
    assert _is_keystroke_model("dfhack-governed-llm") is False


def test_decide_returns_normalized_governed_action_and_writes_plan() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "DIG",
                    "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
                    "intent": "designate the starter room",
                    "objective": "Open interior shelter",
                    "plan_step": "dig starter room",
                    "advance_ticks": 800,
                }
            )
        ]
    )
    action = agent.decide("Time: tick 100", {"work": {}})
    assert action["type"] == "DIG"
    assert action["params"]["area"] == [50, 35, 0]
    assert action["advance_ticks"] == 800
    assert agent._memory.gameplay_plan["objective"] == "Open interior shelter"
    assert agent._memory.gameplay_plan["current_step"] == "dig starter room"
    request = agent._client.chat.completions.requests[0]
    assert request["tool_choice"] == {"type": "function", "function": {"name": "submit_action"}}


def test_order_qty_alias_and_missing_advance_ticks_normalized() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "ORDER",
                    "params": {"job": "bed", "qty": 2},
                    "intent": "queue beds",
                }
            )
        ]
    )
    action = agent.decide("obs", {})
    assert action["type"] == "ORDER"
    assert action["params"]["quantity"] == 2
    assert action["advance_ticks"] == 1000


def test_illegal_action_type_falls_back_to_wait() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "KEYSTROKE",
                    "params": {"keys": ["LEAVESCREEN"]},
                    "intent": "press a key",
                    "advance_ticks": 0,
                }
            )
        ]
    )
    action = agent.decide("obs", {})
    assert action["type"] == "WAIT"
    assert action["advance_ticks"] == 1000
    assert agent._memory.failed_attempts


def test_llm_call_failure_falls_back_to_wait() -> None:
    agent = _agent(error=RuntimeError("boom"))
    action = agent.decide("obs", {})
    assert action["type"] == "WAIT"
    assert action["advance_ticks"] == 1000
    events = agent.pop_tool_events()
    assert any(event["tool"] == "governed_llm.fallback_wait" for event in events)


def test_previous_outcome_recorded_in_memory() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "DIG",
                    "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
                    "intent": "designate the starter room",
                    "advance_ticks": 1000,
                }
            ),
            _submit_action_response(
                {
                    "type": "WAIT",
                    "params": {},
                    "intent": "let miners work",
                    "advance_ticks": 1000,
                }
            ),
        ]
    )
    agent.decide("Time: tick 100", {})
    agent.decide("Last Action: REJECTED - tile not accessible\nTime: tick 1100", {})
    assert len(agent._memory.recent_steps) == 1
    assert agent._memory.recent_steps[0].result.startswith("Last Action: REJECTED")
    assert any("rejected" in item["label"].lower() for item in agent._memory.failed_attempts)


def test_memory_update_with_coordinates_becomes_poi() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "BUILD",
                    "params": {"kind": "CarpenterWorkshop", "x": 58, "y": 35, "z": 0},
                    "intent": "place workshop",
                    "memory_update": "workshop site @ 58,35,0: flat observed floor",
                    "advance_ticks": 1000,
                }
            )
        ]
    )
    action = agent.decide("obs", {})
    assert action["type"] == "BUILD"
    assert agent._memory.pois
    poi = agent._memory.pois[-1]
    assert poi["label"] == "workshop site"
    assert (poi["x"], poi["y"], poi["z"]) == (58, 35, 0)


def test_memory_persists_across_agent_instances(tmp_path: Any) -> None:
    memory_file = tmp_path / "governed_llm_memory.json"

    agent_a = DFHackGovernedLLMAgent(
        api_key="test-key", max_attempts=1, memory_path=str(memory_file)
    )
    agent_a._client = _FakeClient(
        [
            _submit_action_response(
                {
                    "type": "BUILD",
                    "params": {"kind": "CarpenterWorkshop", "x": 1, "y": 2, "z": 3},
                    "intent": "place workshop",
                    "memory_update": "site @ 1,2,3: good floor",
                    "advance_ticks": 1000,
                }
            )
        ]
    )
    agent_a.decide("obs", {})
    assert memory_file.is_file()

    agent_b = DFHackGovernedLLMAgent(
        api_key="test-key", max_attempts=1, memory_path=str(memory_file)
    )
    context = agent_b._memory.get_context()
    assert "site" in context


def test_failed_attempt_labels_carry_kind_and_position() -> None:
    agent = _agent(
        [
            _submit_action_response(
                {
                    "type": "BUILD",
                    "params": {"kind": "Wall", "x": 94, "y": 91, "z": 177},
                    "intent": "wall the bedroom",
                    "advance_ticks": 1000,
                }
            ),
            _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "wait", "advance_ticks": 1000}
            ),
        ]
    )
    agent.decide("Time: tick 100", {})
    agent.decide("Last Action: REJECTED - too_far_from_fort\nTime: tick 1100", {})
    labels = [item["label"] for item in agent._memory.failed_attempts]
    assert any("BUILD Wall at (94,91) rejected" == label for label in labels)


def test_vision_agent_attaches_minimap_image() -> None:
    agent = DFHackGovernedLLMAgent(
        api_key="test-key", max_attempts=1, memory_path=None, vision=True
    )
    agent._client = _FakeClient(
        [
            _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "look around", "advance_ticks": 1000}
            )
        ]
    )

    agent.decide(
        "obs",
        {"fort": {"map_rows": ["..WWW..", "..W.W.."], "map_origin": [90, 87, 177]}},
    )

    request = agent._client.chat.completions.requests[0]
    content = request["messages"][1]["content"]
    assert isinstance(content, list)
    kinds = [part.get("type") for part in content]
    assert kinds == ["text", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_variants_registered_in_all_gates() -> None:
    for name in (
        "dfhack-governed-llm-glm5v",
        "dfhack-governed-llm-gpt55-vision",
        "dfhack-governed-llm-kimi-vision",
        "dfhack-governed-llm-minimax-vision",
    ):
        assert name in AGENT_FACTORIES
        assert name in GOVERNED_DFHACK_MODELS
        assert name in get_args(ModelType)
        assert OPTIONAL_AGENT_MODULES[name] == "fort_gym.bench.agent.governed_llm"
        assert _is_keystroke_model(name) is False


def test_tool_choice_degrades_to_auto_on_provider_rejection() -> None:
    class _PickyCompletions:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> Any:
            self.requests.append(kwargs)
            if kwargs.get("tool_choice") != "auto":
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': 'Tool choice must be auto'}}"
                )
            return _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "ok", "advance_ticks": 1000}
            )

    agent = DFHackGovernedLLMAgent(api_key="test-key", max_attempts=1, memory_path=None)
    picky = _PickyCompletions()
    agent._client = SimpleNamespace(chat=SimpleNamespace(completions=picky))

    action = agent.decide("obs", {})

    assert action["type"] == "WAIT"
    assert action["intent"] == "ok"  # real model response, not a fallback
    assert picky.requests[0]["tool_choice"] != "auto"
    assert picky.requests[1]["tool_choice"] == "auto"
    events = agent.pop_tool_events()
    assert any(e["tool"] == "governed_llm.tool_choice_degraded" for e in events)


def test_reasoning_disable_degrades_when_provider_requires_reasoning() -> None:
    class _ReasoningCompletions:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> Any:
            self.requests.append(kwargs)
            if "extra_body" in kwargs:
                raise RuntimeError(
                    "Error code: 400 - Reasoning is mandatory for this endpoint"
                )
            return _submit_action_response(
                {"type": "WAIT", "params": {}, "intent": "ok", "advance_ticks": 1000}
            )

    agent = DFHackGovernedLLMAgent(api_key="test-key", max_attempts=1, memory_path=None)
    picky = _ReasoningCompletions()
    agent._client = SimpleNamespace(chat=SimpleNamespace(completions=picky))

    action = agent.decide("obs", {})

    assert action["intent"] == "ok"
    assert "extra_body" in picky.requests[0]
    assert "extra_body" not in picky.requests[1]
    events = agent.pop_tool_events()
    assert any(e["tool"] == "governed_llm.reasoning_enabled_degraded" for e in events)
