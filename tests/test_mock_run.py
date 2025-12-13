from __future__ import annotations

import json
import shutil
from pathlib import Path

from fort_gym.bench.agent.base import RandomAgent
from fort_gym.bench.run.runner import run_once


def test_mock_run_produces_trace() -> None:
    run_id = run_once(RandomAgent(), env="mock", max_steps=3, ticks_per_step=10)

    artifacts_root = Path(__file__).resolve().parents[1] / "fort_gym" / "artifacts"
    artifact_dir = artifacts_root / run_id
    trace_path = artifact_dir / "trace.jsonl"

    assert artifact_dir.is_dir()
    assert trace_path.is_file()

    with trace_path.open("r", encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh if line.strip()]

    assert len(lines) >= 3

    state_events = 0
    action_events = 0
    steps = []
    for record in lines:
        steps.append(record["step"])
        events = record.get("events", [])
        state_events += sum(1 for evt in events if evt.get("type") == "state")
        action_events += sum(1 for evt in events if evt.get("type") == "action")

    assert state_events >= 3
    assert action_events >= 3
    assert steps == sorted(steps)

    shutil.rmtree(artifact_dir, ignore_errors=True)
