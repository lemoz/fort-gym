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


def test_summarize_tracks_work_progress(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-work",
            "step": 0,
            "metrics": {
                "time": 100,
                "run_elapsed_ticks": 500,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
                "work_progress": 10,
                "designation_progress": 10,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "target_dig_designations_delta": 10,
                "target_floor_tiles_delta": 0,
                "target_wall_tiles_delta": 0,
                "active_dig_jobs_delta": 1,
                "utility_action_progress": 0,
                "manager_orders_delta": 0,
                "manager_order_quantity_delta": 0,
                "carpenter_workshops_delta": 0,
                "production_workshops_delta": 0,
                "work": {
                    "target_hidden_tiles": 25,
                    "citizens_total": 7,
                    "miners_total": 1,
                    "citizens_on_target_z": 0,
                    "target_z": 0,
                    "window_z": 177,
                    "manager_orders_count": 0,
                    "manager_orders_amount_left": 0,
                    "carpenter_workshops": 0,
                },
            },
            "tick_advance": {"ticks_advanced": 500},
            "events": [],
        },
        {
            "run_id": "run-work",
            "step": 1,
            "metrics": {
                "time": 600,
                "run_elapsed_ticks": 1000,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
                "work_progress": 25,
                "designation_progress": 25,
                "completion_progress": 8,
                "utility_progress": 5,
                "production_progress": 5,
                "target_dig_designations_delta": 25,
                "target_floor_tiles_delta": 8,
                "target_wall_tiles_delta": 8,
                "active_dig_jobs_delta": 1,
                "utility_action_progress": 5,
                "manager_orders_delta": 1,
                "manager_order_quantity_delta": 5,
                "carpenter_workshops_delta": 1,
                "production_workshops_delta": 1,
                "work": {
                    "target_hidden_tiles": 0,
                    "citizens_total": 7,
                    "miners_total": 1,
                    "citizens_on_target_z": 0,
                    "target_z": 0,
                    "window_z": 177,
                    "manager_orders_count": 1,
                    "manager_orders_amount_left": 5,
                    "carpenter_workshops": 1,
                },
            },
            "tick_advance": {"ticks_advanced": 500},
            "events": [],
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)

    assert summary.work_progress == 25
    assert summary.work_score == 10.0
    assert summary.designation_progress == 25
    assert summary.completion_progress == 8
    assert summary.completion_score == 3.2
    assert summary.utility_progress == 5
    assert summary.utility_score == 10.0
    assert summary.production_progress == 5
    assert summary.production_score == 10.0
    assert summary.target_dig_designations_delta == 25
    assert summary.target_floor_tiles_delta == 8
    assert summary.target_wall_tiles_delta == 8
    assert summary.active_dig_jobs_delta == 1
    assert summary.utility_action_progress == 5
    assert summary.manager_orders_delta == 1
    assert summary.manager_order_quantity_delta == 5
    assert summary.carpenter_workshops_delta == 1
    assert summary.production_workshops_delta == 1
    assert summary.manager_orders_count == 1
    assert summary.manager_orders_amount_left == 5
    assert summary.carpenter_workshops == 1
    assert summary.target_hidden_tiles == 25
    assert summary.citizens_total == 7
    assert summary.miners_total == 1
    assert summary.citizens_on_target_z == 0
    assert summary.target_z == 0
    assert summary.window_z == 177
