"""Built-in mock scenario packs and assertion evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ScenarioAssertion:
    """A simple assertion against a dotted result path."""

    path: str
    op: str
    value: Any
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "op": self.op,
            "value": self.value,
            "description": self.description,
        }


@dataclass(frozen=True)
class MockScenario:
    """A deterministic mock-environment scenario pack."""

    name: str
    description: str
    initial_state: Mapping[str, Any]
    assertions: tuple[ScenarioAssertion, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "initial_state": dict(self.initial_state),
            "assertions": [assertion.to_dict() for assertion in self.assertions],
        }


DRINK_SCARCITY = MockScenario(
    name="drink-scarcity",
    description=(
        "Starts the mock fortress below the safe drink threshold so the run "
        "exercises low-availability scoring and scenario assertions."
    ),
    initial_state={
        "stocks": {"food": 80, "drink": 12},
        "risks": ["drink stock below safe threshold"],
        "reminders": ["Queue brewing before long jobs"],
    },
    assertions=(
        ScenarioAssertion(
            path="summary.scenario",
            op="eq",
            value="drink-scarcity",
            description="summary records the scenario pack",
        ),
        ScenarioAssertion(
            path="summary.backend",
            op="eq",
            value="mock",
            description="scenario runs on the mock backend",
        ),
        ScenarioAssertion(
            path="summary.steps",
            op="gte",
            value=3,
            description="run completed the short scenario horizon",
        ),
        ScenarioAssertion(
            path="summary.availability_score",
            op="eq",
            value=0.0,
            description="drink scarcity is reflected in availability scoring",
        ),
        ScenarioAssertion(
            path="summary.total_score",
            op="lte",
            value=10.0,
            description="scarcity scenario produces a low baseline score",
        ),
    ),
)


BUILTIN_MOCK_SCENARIOS: dict[str, MockScenario] = {
    DRINK_SCARCITY.name: DRINK_SCARCITY,
}


def list_mock_scenarios() -> list[MockScenario]:
    return [BUILTIN_MOCK_SCENARIOS[name] for name in sorted(BUILTIN_MOCK_SCENARIOS)]


def get_mock_scenario(name: str) -> MockScenario:
    try:
        return BUILTIN_MOCK_SCENARIOS[name]
    except KeyError as exc:
        available = ", ".join(sorted(BUILTIN_MOCK_SCENARIOS))
        raise ValueError(f"Unknown mock scenario '{name}'. Available: {available}") from exc


def evaluate_scenario_assertions(
    scenario: MockScenario,
    *,
    summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    context = {"summary": summary}
    return [_evaluate_assertion(assertion, context) for assertion in scenario.assertions]


def _evaluate_assertion(
    assertion: ScenarioAssertion,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    actual = _resolve_path(context, assertion.path)
    ok = _compare(actual, assertion.op, assertion.value)
    return {
        "path": assertion.path,
        "op": assertion.op,
        "expected": assertion.value,
        "actual": actual,
        "ok": ok,
        "description": assertion.description,
    }


def _resolve_path(context: Mapping[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if isinstance(value, Mapping):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "eq":
        return actual == expected
    if op in {"gt", "gte", "lt", "lte"}:
        try:
            left = float(actual)
            right = float(expected)
        except (TypeError, ValueError):
            return False
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        return left <= right
    raise ValueError(f"Unsupported scenario assertion op: {op}")


__all__ = [
    "BUILTIN_MOCK_SCENARIOS",
    "DRINK_SCARCITY",
    "MockScenario",
    "ScenarioAssertion",
    "evaluate_scenario_assertions",
    "get_mock_scenario",
    "list_mock_scenarios",
]
