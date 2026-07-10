from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.runner import run_once
from fort_gym.bench.run.storage import RunRegistry


class ExplodingAgent(Agent):
    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        raise AssertionError("stopped run should not call the agent")


class StopDuringDecideAgent(Agent):
    def __init__(self, registry: RunRegistry, run_id: str) -> None:
        self._registry = registry
        self._run_id = run_id

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        assert self._registry.request_stop(self._run_id) is True
        return {
            "type": "DIG",
            "params": {"area": [1, 1, 0], "size": [1, 1, 1]},
            "intent": "this action must not execute after stop",
        }


def test_run_once_honors_stop_before_agent_decide(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="mock",
        model="fake",
        max_steps=5,
        ticks_per_step=10,
    )
    assert registry.request_stop(created.run_id) is True

    run_id = run_once(
        ExplodingAgent(),
        env="mock",
        model="fake",
        max_steps=5,
        ticks_per_step=10,
        run_id=created.run_id,
        registry=registry,
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "stopped"

    trace_path = Path(tmp_path) / run_id / "trace.jsonl"
    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]

    assert rows == [
        {
            "run_id": run_id,
            "step": 0,
            "score_version": 5,
            "stopped": {"reason": "stop_requested"},
            "events": [
                {
                    "type": "stopped",
                    "data": {
                        "run_id": run_id,
                        "step": 0,
                        "reason": "stop_requested",
                    },
                }
            ],
        }
    ]
    assert (Path(tmp_path) / run_id / "summary.json").is_file()

    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_run_once_honors_stop_after_agent_decide_before_execute(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    created = registry.create(
        backend="mock",
        model="fake",
        max_steps=5,
        ticks_per_step=10,
    )

    run_id = run_once(
        StopDuringDecideAgent(registry, created.run_id),
        env="mock",
        model="fake",
        max_steps=5,
        ticks_per_step=10,
        run_id=created.run_id,
        registry=registry,
    )

    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "stopped"

    trace_path = Path(tmp_path) / run_id / "trace.jsonl"
    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]

    assert len(rows) == 1
    assert rows[0]["score_version"] == 5
    assert rows[0]["raw_action"]["intent"] == "this action must not execute after stop"
    assert rows[0]["stopped"]["reason"] == "stop_requested_after_agent_decide"
    assert "execute" not in rows[0]
    assert not any(event.get("type") == "execute" for event in rows[0].get("events", []))

    get_settings.cache_clear()  # type: ignore[attr-defined]
