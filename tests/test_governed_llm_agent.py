from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import fort_gym.bench.agent.governed_llm  # noqa: F401 - registration side effect
from fort_gym.bench.agent.base import AGENT_FACTORIES
from fort_gym.bench.agent.governed_llm import DFHackGovernedLLMAgent
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
    agent = DFHackGovernedLLMAgent(api_key="test-key", max_attempts=1)
    agent._client = _FakeClient(responses, error)
    return agent


def test_governed_llm_is_registered_and_model_gated() -> None:
    assert "dfhack-governed-llm" in AGENT_FACTORIES
    assert "dfhack-governed-llm" in GOVERNED_DFHACK_MODELS
    assert OPTIONAL_AGENT_MODULES["dfhack-governed-llm"] == "fort_gym.bench.agent.governed_llm"
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
