"""Trace summarisation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .scoring import (
    AVAIL_WEIGHT,
    SURVIVAL_WEIGHT,
    TARGET_SURVIVAL_TICKS,
    TARGET_WORK_PROGRESS,
    WORK_WEIGHT,
    composite_score,
)


class RunSummary(BaseModel):
    run_id: str
    model: str = "unknown"
    backend: str = "unknown"
    scenario: Optional[str] = None
    steps: int = 0
    duration_ticks: int = 0
    peak_pop: int = 0
    end_pop: int = 0
    created_wealth: Optional[int] = None
    survival_score: float = 0.0
    availability_score: float = 0.0
    work_score: float = 0.0
    work_progress: int = 0
    target_dig_designations_delta: int = 0
    target_floor_tiles_delta: int = 0
    target_wall_tiles_delta: int = 0
    active_dig_jobs_delta: int = 0
    total_score: float = 0.0
    milestones: List[Dict[str, Any]] = Field(default_factory=list)
    scenario_assertions: List[Dict[str, Any]] = Field(default_factory=list)


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()  # type: ignore[attr-defined]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def summarize(trace_path: Path) -> RunSummary:
    """Produce a run summary from a trace JSONL file."""

    if not trace_path.exists():
        raise FileNotFoundError(trace_path)

    run_id = "unknown"
    steps_seen = -1
    duration = 0
    duration_from_tick_advance = 0
    saw_tick_advance = False
    max_elapsed_ticks = 0
    first_time_tick: Optional[int] = None
    last_time_tick: Optional[int] = None
    peak_pop = 0
    end_pop = 0
    wealth: Optional[int] = None
    drink_sufficient = 0
    casualty_spike = False
    hostiles_present = False
    milestones: List[Dict[str, Any]] = []
    work_progress = 0
    target_dig_designations_delta = 0
    target_floor_tiles_delta = 0
    target_wall_tiles_delta = 0
    active_dig_jobs_delta = 0

    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            run_id = record.get("run_id", run_id)
            step = record.get("step")
            if isinstance(step, int) and step > steps_seen:
                steps_seen = step

            metrics_snapshot = record.get("metrics") or {}
            time_tick = metrics_snapshot.get("time") or metrics_snapshot.get("time_tick")
            if time_tick is not None:
                time_value = _to_int(time_tick, default=last_time_tick or 0)
                if first_time_tick is None:
                    first_time_tick = time_value
                last_time_tick = time_value

            elapsed = metrics_snapshot.get("run_elapsed_ticks")
            if elapsed is not None:
                max_elapsed_ticks = max(max_elapsed_ticks, _to_int(elapsed, default=max_elapsed_ticks))

            work_progress = max(work_progress, _to_int(metrics_snapshot.get("work_progress")))
            target_dig_designations_delta = max(
                target_dig_designations_delta,
                _to_int(metrics_snapshot.get("target_dig_designations_delta")),
            )
            target_floor_tiles_delta = max(
                target_floor_tiles_delta,
                _to_int(metrics_snapshot.get("target_floor_tiles_delta")),
            )
            target_wall_tiles_delta = max(
                target_wall_tiles_delta,
                _to_int(metrics_snapshot.get("target_wall_tiles_delta")),
            )
            active_dig_jobs_delta = max(
                active_dig_jobs_delta,
                _to_int(metrics_snapshot.get("active_dig_jobs_delta")),
            )

            tick_advance = record.get("tick_advance") or {}
            if isinstance(tick_advance, dict) and "ticks_advanced" in tick_advance:
                saw_tick_advance = True
                duration_from_tick_advance += max(0, _to_int(tick_advance.get("ticks_advanced")))

            pop = metrics_snapshot.get("pop")
            if pop is None:
                pop = metrics_snapshot.get("population")
            if pop is not None:
                pop_val = _to_int(pop, default=end_pop)
                peak_pop = max(peak_pop, pop_val)
                end_pop = pop_val

            wealth_val = metrics_snapshot.get("wealth")
            if wealth_val is None:
                wealth_val = metrics_snapshot.get("created_wealth")
            if wealth_val is not None:
                try:
                    wealth = int(wealth_val)
                except (TypeError, ValueError):
                    try:
                        wealth = int(float(wealth_val))
                    except (TypeError, ValueError):
                        pass

            drink = metrics_snapshot.get("drink")
            if isinstance(drink, (int, float)) and drink >= 20:
                drink_sufficient += 1

            dead = metrics_snapshot.get("dead")
            if isinstance(dead, (int, float)) and dead >= 3:
                casualty_spike = True

            hostiles = metrics_snapshot.get("hostiles")
            if isinstance(hostiles, bool):
                hostiles_present = hostiles

            for event in record.get("events", []) or []:
                if event.get("type") != "score":
                    continue
                data = event.get("data", {})
                event_milestones = data.get("milestones") or []
                for item in event_milestones:
                    if isinstance(item, dict):
                        milestones.append(item)
                    else:
                        milestones.append({"k": str(item), "ts": data.get("step")})

    if max_elapsed_ticks > 0:
        duration = max_elapsed_ticks
    elif saw_tick_advance:
        duration = duration_from_tick_advance
    elif first_time_tick is not None and last_time_tick is not None:
        duration = max(0, last_time_tick - first_time_tick)

    total_steps = steps_seen + 1 if steps_seen >= 0 else 0
    drink_availability = (drink_sufficient / total_steps) if total_steps else 0.0

    summary_payload = {
        "duration_ticks": duration,
        "peak_pop": peak_pop,
        "drink_availability": drink_availability,
        "created_wealth": wealth,
        "work_progress": work_progress,
        "casualty_spike": casualty_spike,
        "hostiles_present": hostiles_present,
    }

    survival_score = (min(duration, TARGET_SURVIVAL_TICKS) / TARGET_SURVIVAL_TICKS) * SURVIVAL_WEIGHT
    availability_score = drink_availability * AVAIL_WEIGHT
    work_score = (min(work_progress, TARGET_WORK_PROGRESS) / TARGET_WORK_PROGRESS) * WORK_WEIGHT
    total_score = composite_score(summary_payload)

    summary = RunSummary(
        run_id=run_id,
        steps=total_steps,
        duration_ticks=duration,
        peak_pop=peak_pop,
        end_pop=end_pop,
        created_wealth=wealth,
        survival_score=round(survival_score, 2),
        availability_score=round(availability_score, 2),
        work_score=round(work_score, 2),
        work_progress=work_progress,
        target_dig_designations_delta=target_dig_designations_delta,
        target_floor_tiles_delta=target_floor_tiles_delta,
        target_wall_tiles_delta=target_wall_tiles_delta,
        active_dig_jobs_delta=active_dig_jobs_delta,
        total_score=total_score,
        milestones=milestones,
    )

    summary_path = trace_path.with_name("summary.json")
    summary_path.write_text(json.dumps(_model_dump(summary), indent=2), encoding="utf-8")
    return summary


__all__ = ["RunSummary", "summarize"]
