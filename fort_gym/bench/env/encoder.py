"""Observation encoding utilities."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def redact_noise(state: Dict[str, Any]) -> Dict[str, Any]:
    """Placeholder hook to strip non-deterministic noise from raw state."""
    return state


def encode_observation(state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return (text_summary, machine_state) tuple for a given environment state."""
    clean_state = redact_noise(state)

    time_tick = clean_state.get("time", 0)
    population = clean_state.get("population", 0)
    stocks = clean_state.get("stocks", {})
    risks = clean_state.get("risks", [])
    reminders = clean_state.get("reminders", [])

    bullets = [
        f"- Time: tick {time_tick}",
        f"- Population: {population} dwarves",
        f"- Stocks: food={stocks.get('food', 0)}, drink={stocks.get('drink', 0)}",
    ]

    if risks:
        bullets.append("- Risks: " + ", ".join(risks))
    else:
        bullets.append("- Risks: none detected")

    if reminders:
        bullets.append("- Reminders: " + "; ".join(reminders))
    else:
        bullets.append("- Reminders: none")

    summary_text = "\n".join(bullets)
    return summary_text, clean_state
