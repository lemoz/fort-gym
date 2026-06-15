"""Evaluation metric helpers."""

from __future__ import annotations

from typing import Any, Dict


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
    return {
        "target_dig_designations_delta": designations_delta,
        "target_floor_tiles_delta": floor_delta,
        "target_wall_tiles_delta": wall_delta,
        "active_dig_jobs_delta": active_dig_jobs_delta,
        "work_progress": max(designations_delta, floor_delta, wall_delta) + active_dig_jobs_delta,
    }


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
            "target_dig_designations": _to_int(work.get("target_dig_designations")),
            "target_floor_tiles": _to_int(work.get("target_floor_tiles")),
            "target_wall_tiles": _to_int(work.get("target_wall_tiles")),
            "target_missing_blocks": _to_int(work.get("target_missing_blocks")),
            "active_jobs": _to_int(work.get("active_jobs")),
            "active_dig_jobs": _to_int(work.get("active_dig_jobs")),
        }
    return snapshot


__all__ = ["step_snapshot", "work_progress_delta"]
