from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from fort_gym.bench.agent.governed_llm import DFHackGovernedLLMAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.runner import run_once
from fort_gym.bench.run.storage import RunRegistry


class _OneResponseFakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    @staticmethod
    def _payload(observation: str) -> dict[str, Any]:
        request_match = re.search(
            r"AGENT PLAN CONTROL: review_due=yes request_id=([^\s]+)",
            observation,
        )
        previous_match = re.search(
            r"Required last_action_review\.evidence id: (E\d+)",
            observation,
        )
        evidence = {
            match.group(1): match.group(2)
            for match in re.finditer(
                r"^- (?:- )?(E\d+): (.+)$", observation, re.MULTILINE
            )
        }
        assert request_match is not None
        assert previous_match is not None
        control_evidence = next(
            key
            for key, text in evidence.items()
            if text.startswith("AGENT PLAN CONTROL:")
        )
        current_evidence = next(
            key
            for key, text in evidence.items()
            if text.startswith(("Time:", "Population:", "Food:"))
        )
        return {
            "type": "WAIT",
            "params": {},
            "intent": "advance one bounded synthetic step",
            "objective": "Observe one bounded state transition.",
            "plan_step": "Wait for one state transition.",
            "expected_simulation_result": "The mock clock advances once.",
            "last_action_review": {
                "previous_step": -1,
                "verdict": "unknown",
                "evidence": [previous_match.group(1)],
                "retry_same_action": False,
                "lesson": "There is no prior action to assess.",
            },
            "plan_review": {
                "request_id": request_match.group(1),
                "decision": "establish",
                "prior_objective": "",
                "objective": "Observe one bounded state transition.",
                "evidence": [control_evidence, current_evidence],
                "reason": "Initial state establishes the bounded objective.",
                "steps": ["Wait once.", "Re-observe."],
            },
            "advance_ticks": 1,
        }

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if len(self.requests) != 1:
            raise AssertionError("the budget gate must block a second fake dispatch")
        observation = kwargs["messages"][-1]["content"]
        assert isinstance(observation, str)
        payload = self._payload(observation)
        return SimpleNamespace(
            id="synthetic-cap-generation",
            model="openai/synthetic-cap-model",
            usage=SimpleNamespace(total_tokens=5, cost=0.1),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="submit_action",
                                    arguments=json.dumps(payload),
                                )
                            )
                        ],
                    )
                )
            ],
        )


def test_cap_fake_contract_clarifies_zero_remaining_positive_cap() -> None:
    acceptance_path = Path(__file__).resolve().parents[1] / "infra/m1b/acceptance.yaml"
    acceptance = yaml.safe_load(acceptance_path.read_text(encoding="utf-8"))
    amendment = next(
        item
        for item in acceptance["amendments"]
        if item.get("type") == "procedure_clarification"
        and item.get("gate") == "CAP-FAKE"
    )
    gate = next(item for item in acceptance["gates"] if item["id"] == "CAP-FAKE")

    assert amendment["outcome_dependent"] is False
    assert amendment["production_positive_cap_validation"] == "unchanged"
    assert amendment["gate_changes"] == "none"
    assert amendment["threshold_changes"] == "none"
    assert "zero budget remaining" in amendment["scope"]
    assert "positive configured test cap" in gate["procedure"]
    assert "zero remaining budget" in gate["procedure"]


def test_one_fake_response_reaches_positive_cap_and_persists_terminal_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_root = (tmp_path / "artifacts").resolve()
    db_path = (tmp_path / "registry.sqlite3").resolve()
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    for name in (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    network_attempts: list[tuple[Any, ...]] = []

    def forbidden_socket(*args: Any, **kwargs: Any) -> Any:
        network_attempts.append((*args, kwargs))
        raise AssertionError("CAP-FAKE must not create a network socket")

    monkeypatch.setattr(socket, "socket", forbidden_socket)

    completions = _OneResponseFakeCompletions()
    agent = DFHackGovernedLLMAgent(
        api_key="synthetic-local-transport-only",
        memory_path=None,
        model_override="openai/synthetic-cap-model",
        provider_name="Synthetic Provider",
        strict_supervised=True,
        max_attempts=1,
        max_total_tokens=5,
        max_cost_usd=1.0,
    )
    agent._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    agent._generation_metadata = lambda generation_id: {
        "status": "available",
        "provider_name": "Synthetic Provider",
        "model": "openai/synthetic-cap-model",
        "generation_id": generation_id,
    }

    registry = RunRegistry(
        db_path=db_path,
        artifacts_root=artifacts_root,
        recover_interrupted=False,
    )
    record = registry.create(
        run_id="cap-fake-end-to-end",
        backend="mock",
        model="dfhack-governed-llm",
        max_steps=2,
        ticks_per_step=1,
    )

    result = run_once(
        agent,
        backend="mock",
        model=record.model,
        max_steps=record.max_steps,
        ticks_per_step=record.ticks_per_step,
        run_id=record.run_id,
        registry=registry,
    )

    assert result == record.run_id
    assert len(completions.requests) == 1
    assert completions.requests[0]["extra_body"]["provider"] == {
        "order": ["Synthetic Provider"],
        "allow_fallbacks": False,
    }
    assert network_attempts == []

    persisted = RunRegistry(
        db_path=db_path,
        artifacts_root=artifacts_root,
        recover_interrupted=False,
    ).get(record.run_id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.ended_at is not None
    reason = persisted.metadata["terminal_reason"]
    assert reason["code"] == "budget_cap_exceeded"
    assert reason["stage"] == "agent_decide"
    assert reason["caps_reached"] == ["tokens"]
    assert reason["budget"] == {
        "returned_responses": 1,
        "accounted_responses": 1,
        "total_tokens": 5,
        "total_cost_usd": 0.1,
        "max_total_tokens": 5,
        "max_cost_usd": 1.0,
    }
    assert persisted.latest_summary is not None
    trace_path = artifacts_root / record.run_id / "trace.jsonl"
    trace = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provider_events = [
        event
        for row in trace
        for event in row.get("events", [])
        if event.get("type") == "tool_call"
        and event.get("data", {}).get("tool")
        == "openrouter.chat.completions.create"
    ]
    assert len(provider_events) == 1
    assert any(
        event.get("type") == "terminal"
        and event.get("data", {}).get("terminal_reason", {}).get("code")
        == "budget_cap_exceeded"
        for row in trace
        for event in row.get("events", [])
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]
