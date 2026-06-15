from __future__ import annotations

import json
from pathlib import Path

from fort_gym.bench.eval.summary import RunSummary, summarize


def test_summarize_creates_summary(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-1",
            "step": 0,
            "metrics": {"time": 100, "pop": 7, "drink": 25, "food": 40, "wealth": 5000, "dead": 0, "hostiles": False},
            "tick_advance": {"ticks_advanced": 10},
            "events": [
                {
                    "type": "score",
                    "data": {"run_id": "run-1", "step": 0, "value": 5.0, "milestones": [{"k": "DRINK_50", "ts": 100}]},
                }
            ],
        },
        {
            "run_id": "run-1",
            "step": 1,
            "metrics": {"time": 200, "pop": 9, "drink": 10, "food": 35, "wealth": 8000, "dead": 3, "hostiles": True},
            "tick_advance": {"ticks_advanced": 20},
            "events": [
                {
                    "type": "score",
                    "data": {"run_id": "run-1", "step": 1, "value": 6.0, "milestones": [{"k": "HOSTILES", "ts": 200}]},
                }
            ],
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)
    assert isinstance(summary, RunSummary)
    assert summary.run_id == "run-1"
    assert summary.steps == 2
    assert summary.duration_ticks == 30
    assert isinstance(summary.total_score, float)
    assert summary.milestones

    summary_path = trace_path.with_name("summary.json")
    assert summary_path.exists()


def test_summarize_prefers_run_elapsed_ticks(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-2",
            "step": 0,
            "metrics": {
                "time": 16801,
                "run_elapsed_ticks": 0,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
            },
            "tick_advance": {"ticks_advanced": 0},
            "events": [],
        },
        {
            "run_id": "run-2",
            "step": 1,
            "metrics": {
                "time": 17001,
                "run_elapsed_ticks": 200,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
            },
            "tick_advance": {"ticks_advanced": 200},
            "events": [],
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)

    assert summary.duration_ticks == 200
    assert summary.survival_score == 2.5
    assert summary.total_score < 53.5
