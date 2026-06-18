"""Evaluation metric helpers."""

from __future__ import annotations

from typing import Any, Dict

UTILITY_WORKSHOP_PROGRESS = 5
PRODUCTION_WORKSHOP_PROGRESS = 5
COMPLEXITY_SPACE_PROGRESS = 5


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def work_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute bounded target-region work deltas from live work snapshots."""

    current = current_work or {}
    baseline = baseline_work or {}
    designations_delta = max(
        0,
        _to_int(current.get("target_dig_designations"))
        - _to_int(baseline.get("target_dig_designations")),
    )
    floor_delta = max(
        0,
        _to_int(current.get("target_floor_tiles"))
        - _to_int(baseline.get("target_floor_tiles")),
    )
    wall_delta = max(
        0,
        _to_int(baseline.get("target_wall_tiles"))
        - _to_int(current.get("target_wall_tiles")),
    )
    active_dig_jobs_delta = max(
        0,
        _to_int(current.get("active_dig_jobs")) - _to_int(baseline.get("active_dig_jobs")),
    )
    designation_progress = designations_delta + active_dig_jobs_delta
    completion_progress = max(floor_delta, wall_delta)
    return {
        "target_dig_designations_delta": designations_delta,
        "target_floor_tiles_delta": floor_delta,
        "target_wall_tiles_delta": wall_delta,
        "active_dig_jobs_delta": active_dig_jobs_delta,
        "designation_progress": designation_progress,
        "completion_progress": completion_progress,
        "work_progress": max(designation_progress, completion_progress),
    }


def ui_work_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute progress inside a fixed live UI rectangle.

    The caller is responsible for passing snapshots from the same rectangle. If
    the rectangle changes, return zero progress to avoid scoring camera motion.
    """

    current = current_work or {}
    baseline = baseline_work or {}
    target_rect = current.get("target_rect")
    if target_rect is None or target_rect != baseline.get("target_rect"):
        return {
            "ui_target_dig_designations_delta": 0,
            "ui_target_floor_tiles_delta": 0,
            "ui_target_floor_removed_delta": 0,
            "ui_target_wall_tiles_delta": 0,
            "ui_designation_progress": 0,
            "ui_completion_progress": 0,
            "ui_excavation_progress": 0,
            "ui_work_progress": 0,
        }

    designations_delta = max(
        0,
        _to_int(current.get("target_dig_designations"))
        - _to_int(baseline.get("target_dig_designations")),
    )
    floor_delta = max(
        0,
        _to_int(current.get("target_floor_tiles"))
        - _to_int(baseline.get("target_floor_tiles")),
    )
    wall_delta = max(
        0,
        _to_int(baseline.get("target_wall_tiles"))
        - _to_int(current.get("target_wall_tiles")),
    )
    floor_removed_delta = max(
        0,
        _to_int(baseline.get("target_floor_tiles"))
        - _to_int(current.get("target_floor_tiles")),
    )
    excavation_progress = max(wall_delta, floor_removed_delta)
    completion_progress = max(floor_delta, excavation_progress)
    return {
        "ui_target_dig_designations_delta": designations_delta,
        "ui_target_floor_tiles_delta": floor_delta,
        "ui_target_floor_removed_delta": floor_removed_delta,
        "ui_target_wall_tiles_delta": wall_delta,
        "ui_designation_progress": designations_delta,
        "ui_completion_progress": completion_progress,
        "ui_excavation_progress": excavation_progress,
        "ui_work_progress": max(designations_delta, completion_progress),
    }


def utility_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute bounded useful-work deltas from live work snapshots."""

    current = current_work or {}
    baseline = baseline_work or {}
    manager_orders_delta = max(
        0,
        _to_int(current.get("manager_orders_count"))
        - _to_int(baseline.get("manager_orders_count")),
    )
    manager_order_quantity_delta = max(
        0,
        _to_int(current.get("manager_orders_amount_left"))
        - _to_int(baseline.get("manager_orders_amount_left")),
    )
    carpenter_workshops_delta = max(
        0,
        _to_int(current.get("carpenter_workshops"))
        - _to_int(baseline.get("carpenter_workshops")),
    )
    order_progress = max(manager_orders_delta, manager_order_quantity_delta)
    workshop_progress = carpenter_workshops_delta * UTILITY_WORKSHOP_PROGRESS
    return {
        "manager_orders_delta": manager_orders_delta,
        "manager_order_quantity_delta": manager_order_quantity_delta,
        "carpenter_workshops_delta": carpenter_workshops_delta,
        "utility_progress": order_progress + workshop_progress,
    }


def production_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute bounded production/build deltas from live work snapshots."""

    current = current_work or {}
    baseline = baseline_work or {}
    carpenter_workshops_delta = max(
        0,
        _to_int(current.get("carpenter_workshops"))
        - _to_int(baseline.get("carpenter_workshops")),
    )
    return {
        "production_workshops_delta": carpenter_workshops_delta,
        "production_progress": carpenter_workshops_delta * PRODUCTION_WORKSHOP_PROGRESS,
    }


def complexity_progress_delta(
    current_work: Dict[str, Any] | None,
    baseline_work: Dict[str, Any] | None,
) -> Dict[str, int]:
    """Compute visible fortress-layout complexity from the planned second space."""

    current = current_work or {}
    baseline = baseline_work or {}
    floor_delta = max(
        0,
        _to_int(current.get("fortress_complexity_floor_tiles"))
        - _to_int(baseline.get("fortress_complexity_floor_tiles")),
    )
    wall_delta = max(
        0,
        _to_int(baseline.get("fortress_complexity_wall_tiles"))
        - _to_int(current.get("fortress_complexity_wall_tiles")),
    )
    spaces_delta = max(
        0,
        _to_int(current.get("fortress_complexity_spaces_completed"))
        - _to_int(baseline.get("fortress_complexity_spaces_completed")),
    )
    complexity_tiles_delta = max(floor_delta, wall_delta)
    return {
        "complexity_floor_tiles_delta": floor_delta,
        "complexity_wall_tiles_delta": wall_delta,
        "complexity_spaces_delta": spaces_delta,
        "complexity_progress": complexity_tiles_delta + spaces_delta * COMPLEXITY_SPACE_PROGRESS,
    }


def utility_action_progress(action: Dict[str, Any], execute_result: Dict[str, Any]) -> Dict[str, int]:
    """Return useful-work progress proven by an accepted structured action."""

    if not execute_result.get("accepted", execute_result.get("ok", False)):
        return {"utility_action_progress": 0}

    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    action_type = action.get("type")
    if action_type == "ORDER":
        return {
            "utility_action_progress": min(
                UTILITY_WORKSHOP_PROGRESS,
                max(1, _to_int(params.get("quantity"), default=1)),
            ),
        }
    if action_type == "BUILD" and params.get("kind") == "CarpenterWorkshop":
        return {"utility_action_progress": UTILITY_WORKSHOP_PROGRESS}
    return {"utility_action_progress": 0}


def step_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract normalized metrics from a raw environment state."""

    stocks = state.get("stocks") or {}
    hazards = state.get("hazards") or {}

    food = _to_int(stocks.get("food"))
    drink = _to_int(stocks.get("drink"))
    wealth = stocks.get("wealth")
    if wealth is None:
        wealth = state.get("wealth")
    wealth_value = _to_int(wealth, default=0) if wealth is not None else None

    hostiles_raw = state.get("hostiles")
    if hostiles_raw is None:
        risks = state.get("risks") or []
        hostiles_raw = any("hostile" in str(r).lower() for r in risks)
    if hostiles_raw is None:
        hostiles_raw = bool(hazards.get("hostiles"))

    snapshot = {
        "time": _to_int(state.get("time")),
        "pop": _to_int(state.get("population")),
        "food": food,
        "drink": drink,
        "wealth": wealth_value,
        "hostiles": bool(hostiles_raw),
        "dead": _to_int(state.get("dead"), default=0),
    }
    work = state.get("work")
    if isinstance(work, dict):
        snapshot["work"] = {
            "ok": bool(work.get("ok", False)),
            "target_rect": work.get("target_rect"),
            "target_tiles": _to_int(work.get("target_tiles")),
            "target_z": _to_int(work.get("target_z")),
            "window_x": _to_int(work.get("window_x")),
            "window_y": _to_int(work.get("window_y")),
            "window_z": _to_int(work.get("window_z")),
            "cursor_x": _to_int(work.get("cursor_x")),
            "cursor_y": _to_int(work.get("cursor_y")),
            "cursor_z": _to_int(work.get("cursor_z")),
            "target_dig_designations": _to_int(work.get("target_dig_designations")),
            "target_floor_tiles": _to_int(work.get("target_floor_tiles")),
            "target_wall_tiles": _to_int(work.get("target_wall_tiles")),
            "target_hidden_tiles": _to_int(work.get("target_hidden_tiles")),
            "target_visible_tiles": _to_int(work.get("target_visible_tiles")),
            "target_missing_blocks": _to_int(work.get("target_missing_blocks")),
            "active_jobs": _to_int(work.get("active_jobs")),
            "active_dig_jobs": _to_int(work.get("active_dig_jobs")),
            "citizens_total": _to_int(work.get("citizens_total")),
            "miners_total": _to_int(work.get("miners_total")),
            "citizens_on_target_z": _to_int(work.get("citizens_on_target_z")),
            "manager_orders_count": _to_int(work.get("manager_orders_count")),
            "manager_orders_amount_left": _to_int(work.get("manager_orders_amount_left")),
            "carpenter_workshops": _to_int(work.get("carpenter_workshops")),
            "fortress_plan_name": work.get("fortress_plan_name"),
            "fortress_connector_floor_tiles": _to_int(
                work.get("fortress_connector_floor_tiles")
            ),
            "fortress_connector_wall_tiles": _to_int(
                work.get("fortress_connector_wall_tiles")
            ),
            "fortress_workshop_room_floor_tiles": _to_int(
                work.get("fortress_workshop_room_floor_tiles")
            ),
            "fortress_workshop_room_wall_tiles": _to_int(
                work.get("fortress_workshop_room_wall_tiles")
            ),
            "fortress_complexity_tiles": _to_int(work.get("fortress_complexity_tiles")),
            "fortress_complexity_floor_tiles": _to_int(
                work.get("fortress_complexity_floor_tiles")
            ),
            "fortress_complexity_wall_tiles": _to_int(
                work.get("fortress_complexity_wall_tiles")
            ),
            "fortress_complexity_spaces_completed": _to_int(
                work.get("fortress_complexity_spaces_completed")
            ),
        }
    ui_work = state.get("ui_work")
    if isinstance(ui_work, dict):
        snapshot["ui_work"] = {
            "ok": bool(ui_work.get("ok", False)),
            "target_rect": ui_work.get("target_rect"),
            "target_tiles": _to_int(ui_work.get("target_tiles")),
            "target_z": _to_int(ui_work.get("target_z")),
            "target_dig_designations": _to_int(ui_work.get("target_dig_designations")),
            "target_floor_tiles": _to_int(ui_work.get("target_floor_tiles")),
            "target_wall_tiles": _to_int(ui_work.get("target_wall_tiles")),
            "target_hidden_tiles": _to_int(ui_work.get("target_hidden_tiles")),
            "target_visible_tiles": _to_int(ui_work.get("target_visible_tiles")),
            "target_missing_blocks": _to_int(ui_work.get("target_missing_blocks")),
        }
    return snapshot


__all__ = [
    "step_snapshot",
    "complexity_progress_delta",
    "production_progress_delta",
    "ui_work_progress_delta",
    "utility_action_progress",
    "utility_progress_delta",
    "work_progress_delta",
]
