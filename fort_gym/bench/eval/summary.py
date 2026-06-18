"""Trace summarisation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .scoring import (
    AVAIL_WEIGHT,
    COMPLETION_WEIGHT,
    SURVIVAL_WEIGHT,
    TARGET_COMPLETION_PROGRESS,
    TARGET_SURVIVAL_TICKS,
    TARGET_UTILITY_PROGRESS,
    TARGET_WORK_PROGRESS,
    TARGET_PRODUCTION_PROGRESS,
    TARGET_COMPLEXITY_PROGRESS,
    UTILITY_WEIGHT,
    WORK_WEIGHT,
    PRODUCTION_WEIGHT,
    COMPLEXITY_WEIGHT,
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
    completion_score: float = 0.0
    utility_score: float = 0.0
    production_score: float = 0.0
    complexity_score: float = 0.0
    work_progress: int = 0
    designation_progress: int = 0
    completion_progress: int = 0
    utility_progress: int = 0
    production_progress: int = 0
    complexity_progress: int = 0
    ui_work_progress: int = 0
    ui_designation_progress: int = 0
    ui_completion_progress: int = 0
    ui_excavation_progress: int = 0
    ui_target_dig_designations_delta: int = 0
    ui_target_floor_tiles_delta: int = 0
    ui_target_floor_removed_delta: int = 0
    ui_target_wall_tiles_delta: int = 0
    target_dig_designations_delta: int = 0
    target_floor_tiles_delta: int = 0
    target_wall_tiles_delta: int = 0
    active_dig_jobs_delta: int = 0
    utility_action_progress: int = 0
    complexity_floor_tiles_delta: int = 0
    complexity_wall_tiles_delta: int = 0
    complexity_spaces_delta: int = 0
    manager_orders_delta: int = 0
    manager_order_quantity_delta: int = 0
    carpenter_workshops_delta: int = 0
    production_workshops_delta: int = 0
    manager_orders_count: int = 0
    manager_orders_amount_left: int = 0
    carpenter_workshops: int = 0
    target_hidden_tiles: int = 0
    citizens_total: int = 0
    miners_total: int = 0
    citizens_on_target_z: int = 0
    target_z: int = 0
    window_z: int = 0
    fortress_plan_name: Optional[str] = None
    fortress_connector_floor_tiles: int = 0
    fortress_workshop_room_floor_tiles: int = 0
    fortress_complexity_floor_tiles: int = 0
    fortress_complexity_wall_tiles: int = 0
    fortress_complexity_spaces_completed: int = 0
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
    score_duration_blocked = False
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
    designation_progress = 0
    completion_progress = 0
    utility_progress = 0
    production_progress = 0
    complexity_progress = 0
    ui_work_progress = 0
    ui_designation_progress = 0
    ui_completion_progress = 0
    ui_excavation_progress = 0
    ui_target_dig_designations_delta = 0
    ui_target_floor_tiles_delta = 0
    ui_target_floor_removed_delta = 0
    ui_target_wall_tiles_delta = 0
    target_dig_designations_delta = 0
    target_floor_tiles_delta = 0
    target_wall_tiles_delta = 0
    active_dig_jobs_delta = 0
    utility_action_progress = 0
    complexity_floor_tiles_delta = 0
    complexity_wall_tiles_delta = 0
    complexity_spaces_delta = 0
    manager_orders_delta = 0
    manager_order_quantity_delta = 0
    carpenter_workshops_delta = 0
    production_workshops_delta = 0
    manager_orders_count = 0
    manager_orders_amount_left = 0
    carpenter_workshops = 0
    target_hidden_tiles = 0
    citizens_total = 0
    miners_total = 0
    citizens_on_target_z = 0
    target_z = 0
    window_z = 0
    fortress_plan_name: Optional[str] = None
    fortress_connector_floor_tiles = 0
    fortress_workshop_room_floor_tiles = 0
    fortress_complexity_floor_tiles = 0
    fortress_complexity_wall_tiles = 0
    fortress_complexity_spaces_completed = 0

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
            if "score_duration_blocked" in metrics_snapshot:
                score_duration_blocked = metrics_snapshot.get("score_duration_blocked") is True
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
            designation_progress = max(
                designation_progress,
                _to_int(metrics_snapshot.get("designation_progress")),
            )
            completion_progress = max(
                completion_progress,
                _to_int(metrics_snapshot.get("completion_progress")),
            )
            utility_progress = max(
                utility_progress,
                _to_int(metrics_snapshot.get("utility_progress")),
            )
            production_progress = max(
                production_progress,
                _to_int(metrics_snapshot.get("production_progress")),
            )
            complexity_progress = max(
                complexity_progress,
                _to_int(metrics_snapshot.get("complexity_progress")),
            )
            ui_work_progress = max(
                ui_work_progress,
                _to_int(metrics_snapshot.get("ui_work_progress")),
            )
            ui_designation_progress = max(
                ui_designation_progress,
                _to_int(metrics_snapshot.get("ui_designation_progress")),
            )
            ui_completion_progress = max(
                ui_completion_progress,
                _to_int(metrics_snapshot.get("ui_completion_progress")),
            )
            ui_excavation_progress = max(
                ui_excavation_progress,
                _to_int(metrics_snapshot.get("ui_excavation_progress")),
            )
            ui_target_dig_designations_delta = max(
                ui_target_dig_designations_delta,
                _to_int(metrics_snapshot.get("ui_target_dig_designations_delta")),
            )
            ui_target_floor_tiles_delta = max(
                ui_target_floor_tiles_delta,
                _to_int(metrics_snapshot.get("ui_target_floor_tiles_delta")),
            )
            ui_target_floor_removed_delta = max(
                ui_target_floor_removed_delta,
                _to_int(metrics_snapshot.get("ui_target_floor_removed_delta")),
            )
            ui_target_wall_tiles_delta = max(
                ui_target_wall_tiles_delta,
                _to_int(metrics_snapshot.get("ui_target_wall_tiles_delta")),
            )
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
            utility_action_progress = max(
                utility_action_progress,
                _to_int(metrics_snapshot.get("utility_action_progress")),
            )
            complexity_floor_tiles_delta = max(
                complexity_floor_tiles_delta,
                _to_int(metrics_snapshot.get("complexity_floor_tiles_delta")),
            )
            complexity_wall_tiles_delta = max(
                complexity_wall_tiles_delta,
                _to_int(metrics_snapshot.get("complexity_wall_tiles_delta")),
            )
            complexity_spaces_delta = max(
                complexity_spaces_delta,
                _to_int(metrics_snapshot.get("complexity_spaces_delta")),
            )
            manager_orders_delta = max(
                manager_orders_delta,
                _to_int(metrics_snapshot.get("manager_orders_delta")),
            )
            manager_order_quantity_delta = max(
                manager_order_quantity_delta,
                _to_int(metrics_snapshot.get("manager_order_quantity_delta")),
            )
            carpenter_workshops_delta = max(
                carpenter_workshops_delta,
                _to_int(metrics_snapshot.get("carpenter_workshops_delta")),
            )
            production_workshops_delta = max(
                production_workshops_delta,
                _to_int(metrics_snapshot.get("production_workshops_delta")),
            )
            work_snapshot = metrics_snapshot.get("work")
            if isinstance(work_snapshot, dict):
                target_hidden_tiles = max(
                    target_hidden_tiles,
                    _to_int(work_snapshot.get("target_hidden_tiles")),
                )
                citizens_total = max(citizens_total, _to_int(work_snapshot.get("citizens_total")))
                miners_total = max(miners_total, _to_int(work_snapshot.get("miners_total")))
                citizens_on_target_z = max(
                    citizens_on_target_z,
                    _to_int(work_snapshot.get("citizens_on_target_z")),
                )
                target_z = _to_int(work_snapshot.get("target_z"), target_z)
                window_z = _to_int(work_snapshot.get("window_z"), window_z)
                manager_orders_count = max(
                    manager_orders_count,
                    _to_int(work_snapshot.get("manager_orders_count")),
                )
                manager_orders_amount_left = max(
                    manager_orders_amount_left,
                    _to_int(work_snapshot.get("manager_orders_amount_left")),
                )
                carpenter_workshops = max(
                    carpenter_workshops,
                    _to_int(work_snapshot.get("carpenter_workshops")),
                )
                if work_snapshot.get("fortress_plan_name"):
                    fortress_plan_name = str(work_snapshot.get("fortress_plan_name"))
                fortress_connector_floor_tiles = max(
                    fortress_connector_floor_tiles,
                    _to_int(work_snapshot.get("fortress_connector_floor_tiles")),
                )
                fortress_workshop_room_floor_tiles = max(
                    fortress_workshop_room_floor_tiles,
                    _to_int(work_snapshot.get("fortress_workshop_room_floor_tiles")),
                )
                fortress_complexity_floor_tiles = max(
                    fortress_complexity_floor_tiles,
                    _to_int(work_snapshot.get("fortress_complexity_floor_tiles")),
                )
                fortress_complexity_wall_tiles = _to_int(
                    work_snapshot.get("fortress_complexity_wall_tiles"),
                    fortress_complexity_wall_tiles,
                )
                fortress_complexity_spaces_completed = max(
                    fortress_complexity_spaces_completed,
                    _to_int(work_snapshot.get("fortress_complexity_spaces_completed")),
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

    if score_duration_blocked:
        duration = 0
    elif max_elapsed_ticks > 0:
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
        "completion_progress": completion_progress,
        "utility_progress": utility_progress,
        "production_progress": production_progress,
        "complexity_progress": complexity_progress,
        "casualty_spike": casualty_spike,
        "hostiles_present": hostiles_present,
    }

    survival_score = (min(duration, TARGET_SURVIVAL_TICKS) / TARGET_SURVIVAL_TICKS) * SURVIVAL_WEIGHT
    availability_score = drink_availability * AVAIL_WEIGHT
    work_score = (min(work_progress, TARGET_WORK_PROGRESS) / TARGET_WORK_PROGRESS) * WORK_WEIGHT
    completion_score = (
        min(completion_progress, TARGET_COMPLETION_PROGRESS) / TARGET_COMPLETION_PROGRESS
    ) * COMPLETION_WEIGHT
    utility_score = (
        min(utility_progress, TARGET_UTILITY_PROGRESS) / TARGET_UTILITY_PROGRESS
    ) * UTILITY_WEIGHT
    production_score = (
        min(production_progress, TARGET_PRODUCTION_PROGRESS) / TARGET_PRODUCTION_PROGRESS
    ) * PRODUCTION_WEIGHT
    complexity_score = (
        min(complexity_progress, TARGET_COMPLEXITY_PROGRESS) / TARGET_COMPLEXITY_PROGRESS
    ) * COMPLEXITY_WEIGHT
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
        completion_score=round(completion_score, 2),
        utility_score=round(utility_score, 2),
        production_score=round(production_score, 2),
        complexity_score=round(complexity_score, 2),
        work_progress=work_progress,
        designation_progress=designation_progress,
        completion_progress=completion_progress,
        utility_progress=utility_progress,
        production_progress=production_progress,
        complexity_progress=complexity_progress,
        ui_work_progress=ui_work_progress,
        ui_designation_progress=ui_designation_progress,
        ui_completion_progress=ui_completion_progress,
        ui_excavation_progress=ui_excavation_progress,
        ui_target_dig_designations_delta=ui_target_dig_designations_delta,
        ui_target_floor_tiles_delta=ui_target_floor_tiles_delta,
        ui_target_floor_removed_delta=ui_target_floor_removed_delta,
        ui_target_wall_tiles_delta=ui_target_wall_tiles_delta,
        target_dig_designations_delta=target_dig_designations_delta,
        target_floor_tiles_delta=target_floor_tiles_delta,
        target_wall_tiles_delta=target_wall_tiles_delta,
        active_dig_jobs_delta=active_dig_jobs_delta,
        utility_action_progress=utility_action_progress,
        complexity_floor_tiles_delta=complexity_floor_tiles_delta,
        complexity_wall_tiles_delta=complexity_wall_tiles_delta,
        complexity_spaces_delta=complexity_spaces_delta,
        manager_orders_delta=manager_orders_delta,
        manager_order_quantity_delta=manager_order_quantity_delta,
        carpenter_workshops_delta=carpenter_workshops_delta,
        production_workshops_delta=production_workshops_delta,
        manager_orders_count=manager_orders_count,
        manager_orders_amount_left=manager_orders_amount_left,
        carpenter_workshops=carpenter_workshops,
        target_hidden_tiles=target_hidden_tiles,
        citizens_total=citizens_total,
        miners_total=miners_total,
        citizens_on_target_z=citizens_on_target_z,
        target_z=target_z,
        window_z=window_z,
        fortress_plan_name=fortress_plan_name,
        fortress_connector_floor_tiles=fortress_connector_floor_tiles,
        fortress_workshop_room_floor_tiles=fortress_workshop_room_floor_tiles,
        fortress_complexity_floor_tiles=fortress_complexity_floor_tiles,
        fortress_complexity_wall_tiles=fortress_complexity_wall_tiles,
        fortress_complexity_spaces_completed=fortress_complexity_spaces_completed,
        total_score=total_score,
        milestones=milestones,
    )

    summary_path = trace_path.with_name("summary.json")
    summary_path.write_text(json.dumps(_model_dump(summary), indent=2), encoding="utf-8")
    return summary


__all__ = ["RunSummary", "summarize"]
