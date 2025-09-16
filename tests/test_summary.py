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
    assert isinstance(summary.total_score, float)
    assert summary.milestones

    summary_path = trace_path.with_name("summary.json")
    assert summary_path.exists()
