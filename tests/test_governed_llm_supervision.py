from __future__ import annotations

import json
import math
from types import SimpleNamespace
from typing import Any

import pytest

from fort_gym.bench.agent.governed_llm import (
    DFHackGovernedLLMAgent,
    GovernedBudgetCapError,
    GovernedDecisionError,
    GovernedProviderIdentityError,
    GovernedProviderPinError,
    GovernedUsageAccountingError,
)


def _response(
    *,
    total_tokens: int | None = 5,
    cost: float | None = 0.1,
    generation_id: str | None = "gen-test",
    choices: list[Any] | None = None,
) -> Any:
    if choices is None:
        choices = [
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="submit_action",
                                arguments=json.dumps(
                                    {
                                        "type": "WAIT",
                                        "params": {},
                                        "intent": "bounded fake decision",
                                        "advance_ticks": 1000,
                                    }
                                ),
                            )
                        )
                    ],
                )
            )
        ]
    usage_fields: dict[str, Any] = {}
    if total_tokens is not None:
        usage_fields["total_tokens"] = total_tokens
    if cost is not None:
        usage_fields["cost"] = cost
    return SimpleNamespace(
        id=generation_id,
        model="openai/test-model",
        choices=choices,
        usage=SimpleNamespace(**usage_fields),
    )


class _FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _agent(
    outcomes: list[Any],
    *,
    provider_name: str | None = "OpenAI",
    strict_supervised: bool = True,
    max_attempts: int = 1,
    max_total_tokens: int = 100,
    max_cost_usd: float = 1.0,
) -> tuple[DFHackGovernedLLMAgent, _FakeCompletions]:
    agent = DFHackGovernedLLMAgent(
        api_key="fake-key",
        memory_path=None,
        model_override="openai/test-model",
        provider_name=provider_name,
        strict_supervised=strict_supervised,
        max_attempts=max_attempts,
        max_total_tokens=max_total_tokens,
        max_cost_usd=max_cost_usd,
    )
    completions = _FakeCompletions(outcomes)
    agent._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    agent._generation_metadata = lambda generation_id: {
        "status": "available",
        "provider_name": provider_name,
        "model": "openai/test-model",
        "generation_id": generation_id,
    }
    return agent, completions


def test_strict_route_pins_exact_provider_and_disables_fallbacks() -> None:
    agent, completions = _agent([_response()])
    agent.set_run_context(run_id="route-test")

    action = agent.decide("observation", {})

    assert action["type"] == "WAIT"
    assert len(completions.requests) == 1
    assert completions.requests[0]["extra_body"]["provider"] == {
        "order": ["OpenAI"],
        "allow_fallbacks": False,
    }
    usage = next(
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "openrouter.chat.completions.create"
    )
    assert usage["input"]["provider_route"] == "openrouter"
    assert usage["input"]["provider_name"] == "OpenAI"
    assert usage["output"]["accounting"]["status"] == "accounted"


def test_strict_missing_provider_pin_fails_before_dispatch() -> None:
    agent, completions = _agent([_response()], provider_name=None)

    with pytest.raises(GovernedProviderPinError) as exc_info:
        agent.decide("observation", {})

    assert isinstance(exc_info.value, GovernedDecisionError)
    assert exc_info.value.terminal_code == "provider_pin_missing"
    assert completions.requests == []


@pytest.mark.parametrize(
    ("generation", "response_model", "mismatch"),
    [
        (
            {"status": "unavailable", "reason": "not_found"},
            "openai/test-model",
            "generation_metadata",
        ),
        (
            {
                "status": "available",
                "provider_name": "Fallback Provider",
                "model": "openai/test-model",
            },
            "openai/test-model",
            "provider_name",
        ),
        (
            {
                "status": "available",
                "provider_name": "OpenAI",
                "model": "openai/other-model",
            },
            "openai/test-model",
            "generation_model",
        ),
        (
            {
                "status": "available",
                "provider_name": "OpenAI",
                "model": "openai/test-model",
            },
            "openai/other-model",
            "response_model",
        ),
    ],
)
def test_strict_returned_provider_identity_fails_closed_without_retry(
    generation: dict[str, Any],
    response_model: str,
    mismatch: str,
) -> None:
    response = _response()
    response.model = response_model
    agent, completions = _agent([response], max_attempts=3)
    agent._generation_metadata = lambda _generation_id: generation

    with pytest.raises(GovernedProviderIdentityError) as exc_info:
        agent.decide("observation", {})

    assert exc_info.value.terminal_code == "provider_identity_unverified"
    assert mismatch in exc_info.value.terminal_details["mismatches"]
    assert len(completions.requests) == 1
    usage = next(
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "openrouter.chat.completions.create"
    )
    assert usage["output"]["accounting"]["status"] == "accounted"
    assert usage["output"]["identity_validation"]["status"] == "rejected"


@pytest.mark.parametrize(
    ("max_total_tokens", "max_cost_usd", "caps_reached"),
    [
        (5, 1.0, ["tokens"]),
        (100, 0.1, ["usd"]),
    ],
)
def test_one_response_reaches_cap_and_second_create_never_occurs(
    max_total_tokens: int,
    max_cost_usd: float,
    caps_reached: list[str],
) -> None:
    agent, completions = _agent(
        [_response(total_tokens=5, cost=0.1)],
        max_total_tokens=max_total_tokens,
        max_cost_usd=max_cost_usd,
    )

    assert agent.decide("first observation", {})["type"] == "WAIT"
    with pytest.raises(GovernedBudgetCapError) as exc_info:
        agent.decide("Last Action: accepted\nsecond observation", {})

    assert isinstance(exc_info.value, GovernedDecisionError)
    assert exc_info.value.terminal_code == "budget_cap_exceeded"
    assert exc_info.value.terminal_details["caps_reached"] == caps_reached
    assert len(completions.requests) == 1


def test_provider_response_retry_is_blocked_by_same_cap_gate(monkeypatch) -> None:
    agent, completions = _agent(
        [_response(total_tokens=5, cost=0.1, choices=[])],
        max_attempts=2,
        max_total_tokens=5,
    )
    monkeypatch.setattr(
        "fort_gym.bench.agent.governed_llm.time.sleep",
        lambda _seconds: None,
    )

    with pytest.raises(GovernedBudgetCapError) as exc_info:
        agent.decide("observation", {})

    assert exc_info.value.terminal_code == "budget_cap_exceeded"
    assert len(completions.requests) == 1


def test_strict_unaccounted_billable_response_fails_without_retry() -> None:
    agent, completions = _agent(
        [_response(total_tokens=5, cost=None, generation_id="gen-billable")],
        max_attempts=3,
    )

    with pytest.raises(GovernedUsageAccountingError) as exc_info:
        agent.decide("observation", {})

    assert exc_info.value.terminal_code == "provider_usage_unaccounted"
    assert exc_info.value.terminal_details["missing_fields"] == ["cost"]
    assert len(completions.requests) == 1
    accounting_event = next(
        event
        for event in agent.pop_tool_events()
        if event["tool"] == "openrouter.chat.completions.create"
    )
    assert accounting_event["output"]["accounting"]["status"] == "unaccounted"
    assert accounting_event["output"]["generation"] == {
        "status": "not_requested",
        "reason": "usage_accounting_failed",
    }


@pytest.mark.parametrize(
    "first_error",
    [
        RuntimeError("temporary transport failure"),
        RuntimeError("Reasoning is mandatory for this endpoint"),
        RuntimeError("Tool choice must be auto"),
    ],
)
def test_every_transport_and_degraded_retry_reenters_dispatch_gate(
    monkeypatch,
    first_error: Exception,
) -> None:
    agent, completions = _agent(
        [first_error, _response()],
        max_attempts=2,
    )
    gate_calls = 0
    original_gate = agent._pre_dispatch_gate

    def counted_gate() -> None:
        nonlocal gate_calls
        gate_calls += 1
        original_gate()

    monkeypatch.setattr(agent, "_pre_dispatch_gate", counted_gate)
    monkeypatch.setattr(
        "fort_gym.bench.agent.governed_llm.time.sleep",
        lambda _seconds: None,
    )

    assert agent.decide("observation", {})["type"] == "WAIT"
    assert gate_calls == 2
    assert len(completions.requests) == 2
    assert all(
        request["extra_body"]["provider"]
        == {"order": ["OpenAI"], "allow_fallbacks": False}
        for request in completions.requests
    )


def test_legacy_mode_keeps_missing_cost_compatible_but_tracks_tokens() -> None:
    agent, completions = _agent(
        [_response(total_tokens=7, cost=None)],
        provider_name=None,
        strict_supervised=False,
    )

    assert agent.decide("observation", {})["type"] == "WAIT"
    assert len(completions.requests) == 1
    assert agent._budget_snapshot()["total_tokens"] == 7


def test_default_caps_are_positive_and_finite() -> None:
    agent = DFHackGovernedLLMAgent(
        api_key="fake-key",
        memory_path=None,
        model_override="openai/test-model",
    )

    assert agent._max_total_tokens > 0
    assert agent._max_cost_usd > 0
    assert math.isfinite(agent._max_cost_usd)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_total_tokens": 0},
        {"max_cost_usd": 0.0},
        {"max_cost_usd": float("inf")},
        {"max_cost_usd": float("nan")},
    ],
)
def test_nonpositive_or_nonfinite_caps_are_rejected(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        DFHackGovernedLLMAgent(
            api_key="fake-key",
            memory_path=None,
            model_override="openai/test-model",
            **overrides,
        )
