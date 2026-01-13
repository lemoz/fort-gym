from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fort_gym.bench.agent.base import Agent
from fort_gym.bench.config import get_settings
from fort_gym.bench.env.actions import parse_action
from fort_gym.bench.run.runner import run_once


class ToolLoggingAgent(Agent):
    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self._events.append(
            {
                "tool": "df_wiki",
                "input": {"question": "how to dig"},
                "output": "dig using designations",
            }
        )
        action = {
            "type": "DIG",
            "params": {"area": [0, 0, 0], "size": [1, 1, 1]},
            "intent": "dig a starter room",
        }
        return parse_action(action)

    def pop_tool_events(self) -> List[Dict[str, Any]]:
        events = list(self._events)
        self._events.clear()
        return events


def test_trace_records_tool_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    get_settings()

    run_id = run_once(ToolLoggingAgent(), env="mock", max_steps=1, ticks_per_step=0)
    trace_path = Path(tmp_path) / run_id / "trace.jsonl"
    assert trace_path.is_file()

    records = []
    with trace_path.open("r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]

    tool_events = [
        event
        for record in records
        for event in record.get("events", [])
        if event.get("type") == "tool_call"
    ]
    assert tool_events
    payload = tool_events[0]["data"]
    assert payload["tool"] == "df_wiki"
    assert payload["input"]["question"] == "how to dig"
    get_settings.cache_clear()  # type: ignore[attr-defined]
