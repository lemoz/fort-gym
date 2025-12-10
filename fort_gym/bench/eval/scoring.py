"""Composite scoring heuristics for fort-gym."""

from __future__ import annotations

from typing import Dict, Optional


TARGET_SURVIVAL_TICKS = 2400
POP_CAP = 50
SURVIVAL_WEIGHT = 30.0
POP_WEIGHT = 25.0
AVAIL_WEIGHT = 20.0
WEALTH_WEIGHT = 15.0
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


def composite_score(summary: Dict[str, float]) -> float:
    """Compute a heuristic composite score from summary aggregates.

    Accepts both summary format (duration_ticks, peak_pop, drink_availability, created_wealth)
    and metrics format (time, pop, drink, wealth).
    """

    # Accept both field name formats
    duration = _to_float(summary.get("duration_ticks") or summary.get("time"))
    peak_pop = _to_float(summary.get("peak_pop") or summary.get("pop"))

    # drink_availability is a fraction (0-1), drink is absolute count
    drink_avail = summary.get("drink_availability")
    if drink_avail is not None:
        drink_fraction = max(0.0, min(1.0, _to_float(drink_avail)))
    else:
        # Convert absolute drink count to availability (>= 20 = good)
        drink_count = _to_float(summary.get("drink"))
        drink_fraction = min(1.0, drink_count / DRINK_THRESHOLD) if drink_count > 0 else 0.0

    wealth_value = _to_float(summary.get("created_wealth") or summary.get("wealth"))

    survival_component = (min(duration, TARGET_SURVIVAL_TICKS) / TARGET_SURVIVAL_TICKS) * SURVIVAL_WEIGHT
    pop_component = (min(peak_pop, POP_CAP) / POP_CAP) * POP_WEIGHT
    availability_component = drink_fraction * AVAIL_WEIGHT
    wealth_component = (min(wealth_value, 100000.0) / 100000.0) * WEALTH_WEIGHT

    penalties = 0.0
    if summary.get("casualty_spike"):
        penalties += CASUALTY_PENALTY
    if summary.get("hostiles_present"):
        penalties += HOSTILES_PENALTY

    total = survival_component + pop_component + availability_component + wealth_component - penalties
    return round(total, 2)


__all__ = [
    "composite_score",
    "TARGET_SURVIVAL_TICKS",
    "POP_CAP",
    "DRINK_THRESHOLD",
    "SURVIVAL_WEIGHT",
    "AVAIL_WEIGHT",
    "WEALTH_WEIGHT",
]
