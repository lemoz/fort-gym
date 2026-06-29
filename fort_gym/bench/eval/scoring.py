"""Composite scoring heuristics for fort-gym."""

from __future__ import annotations

from typing import Dict, Optional


TARGET_SURVIVAL_TICKS = 2400
POP_CAP = 50
SURVIVAL_WEIGHT = 30.0
POP_WEIGHT = 25.0
AVAIL_WEIGHT = 20.0
WEALTH_WEIGHT = 15.0
WORK_WEIGHT = 10.0
COMPLETION_WEIGHT = 10.0
UTILITY_WEIGHT = 10.0
PRODUCTION_WEIGHT = 10.0
COMPLEXITY_WEIGHT = 15.0
TARGET_WORK_PROGRESS = 25
TARGET_COMPLETION_PROGRESS = 25
TARGET_UTILITY_PROGRESS = 5
TARGET_PRODUCTION_PROGRESS = 5
TARGET_COMPLEXITY_PROGRESS = 38
WEALTH_TARGET = 100000.0
DRINK_THRESHOLD = 20
CASUALTY_PENALTY = 10.0
HOSTILES_PENALTY = 10.0


def _to_float(value: Optional[float]) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _nonnegative(value: float) -> float:
    return max(0.0, value)


def _scaled_component(value: float, target: float, weight: float) -> float:
    if target <= 0:
        return 0.0
    return (_nonnegative(value) / target) * weight


def _bounded_scaled_component(value: float, target: float, weight: float) -> float:
    if target <= 0:
        return 0.0
    return (min(_nonnegative(value), target) / target) * weight


def score_components(summary: Dict[str, float]) -> Dict[str, float]:
    """Compute score components from observed fortress state.

    Health checks stay bounded so waiting and starting stockpiles do not dominate
    the score. Fort-growth components are open-ended: progress beyond a target
    keeps adding score as the fort digs, produces, grows, and creates wealth.
    """

    duration = _to_float(summary.get("duration_ticks") or summary.get("time"))
    peak_pop = _to_float(summary.get("peak_pop") or summary.get("pop"))

    drink_avail = summary.get("drink_availability")
    if drink_avail is not None:
        drink_fraction = max(0.0, min(1.0, _to_float(drink_avail)))
    else:
        drink_count = _to_float(summary.get("drink"))
        drink_fraction = (
            min(1.0, _nonnegative(drink_count) / DRINK_THRESHOLD) if drink_count > 0 else 0.0
        )

    wealth_value = _to_float(summary.get("created_wealth") or summary.get("wealth"))
    work_progress = _to_float(summary.get("work_progress"))
    completion_progress = _to_float(summary.get("completion_progress"))
    utility_progress = _to_float(summary.get("utility_progress"))
    production_progress = _to_float(summary.get("production_progress"))
    complexity_progress = _to_float(summary.get("complexity_progress"))

    return {
        "survival_score": _bounded_scaled_component(
            duration, TARGET_SURVIVAL_TICKS, SURVIVAL_WEIGHT
        ),
        "population_score": _bounded_scaled_component(peak_pop, POP_CAP, POP_WEIGHT),
        "availability_score": _nonnegative(drink_fraction) * AVAIL_WEIGHT,
        "wealth_score": _scaled_component(wealth_value, WEALTH_TARGET, WEALTH_WEIGHT),
        "work_score": _scaled_component(work_progress, TARGET_WORK_PROGRESS, WORK_WEIGHT),
        "completion_score": _scaled_component(
            completion_progress, TARGET_COMPLETION_PROGRESS, COMPLETION_WEIGHT
        ),
        "utility_score": _scaled_component(
            utility_progress, TARGET_UTILITY_PROGRESS, UTILITY_WEIGHT
        ),
        "production_score": _scaled_component(
            production_progress, TARGET_PRODUCTION_PROGRESS, PRODUCTION_WEIGHT
        ),
        "complexity_score": _scaled_component(
            complexity_progress, TARGET_COMPLEXITY_PROGRESS, COMPLEXITY_WEIGHT
        ),
    }


def composite_score(summary: Dict[str, float]) -> float:
    """Compute a heuristic composite score from summary aggregates.

    Accepts both summary format (duration_ticks, peak_pop, drink_availability, created_wealth)
    and metrics format (time, pop, drink, wealth).
    """

    components = score_components(summary)
    penalties = 0.0
    if summary.get("casualty_spike"):
        penalties += CASUALTY_PENALTY
    if summary.get("hostiles_present"):
        penalties += HOSTILES_PENALTY

    total = sum(components.values()) - penalties
    return round(total, 2)


__all__ = [
    "composite_score",
    "TARGET_SURVIVAL_TICKS",
    "POP_CAP",
    "DRINK_THRESHOLD",
    "WEALTH_TARGET",
    "SURVIVAL_WEIGHT",
    "AVAIL_WEIGHT",
    "WEALTH_WEIGHT",
    "WORK_WEIGHT",
    "COMPLETION_WEIGHT",
    "UTILITY_WEIGHT",
    "PRODUCTION_WEIGHT",
    "COMPLEXITY_WEIGHT",
    "TARGET_WORK_PROGRESS",
    "TARGET_COMPLETION_PROGRESS",
    "TARGET_UTILITY_PROGRESS",
    "TARGET_PRODUCTION_PROGRESS",
    "TARGET_COMPLEXITY_PROGRESS",
    "score_components",
]
