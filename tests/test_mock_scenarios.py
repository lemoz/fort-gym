from __future__ import annotations

import json

from fort_gym.bench.agent.base import RandomAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.env.mock_env import MockEnvironment
from fort_gym.bench.env.scenarios import get_mock_scenario
from fort_gym.bench.run.runner import run_once


def test_default_mock_environment_preserves_baseline_state() -> None:
    env = MockEnvironment()
    env.reset(seed=123)

    state = env.observe()

    assert state["scenario"] is None
    assert state["population"] == 7
    assert state["stocks"] == {"food": 100, "drink": 80}
    assert state["risks"] == []


def test_drink_scarcity_scenario_persists_assertions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    run_id = run_once(
        RandomAgent(),
        backend="mock",
        model="random",
        max_steps=3,
        ticks_per_step=10,
        scenario="drink-scarcity",
    )

    trace_path = tmp_path / run_id / "trace.jsonl"
    summary_path = tmp_path / run_id / "summary.json"
    first_record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert first_record["observation"]["scenario"] == "drink-scarcity"
    assert first_record["observation"]["stocks"]["drink"] == 12
    assert "drink stock below safe threshold" in first_record["observation"]["risks"]
    assert summary["scenario"] == "drink-scarcity"
    assert summary["backend"] == "mock"
    assert summary["availability_score"] == 0.0
    assert summary["total_score"] <= 10.0
    assert summary["scenario_assertions"]
    assert all(item["ok"] for item in summary["scenario_assertions"])

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_scenario_rejects_non_mock_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    try:
        run_once(RandomAgent(), backend="dfhack", scenario="drink-scarcity")
    except ValueError as exc:
        assert "mock backend" in str(exc)
    else:
        raise AssertionError("dfhack scenario should fail before backend startup")

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unknown_mock_scenario_lists_available() -> None:
    try:
        get_mock_scenario("missing")
    except ValueError as exc:
        assert "drink-scarcity" in str(exc)
    else:
        raise AssertionError("missing scenario should fail")
