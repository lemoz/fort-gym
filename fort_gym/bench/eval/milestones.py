"""Milestone detection stubs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def detect(prev_state: Optional[Dict[str, Any]], curr_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return milestone dictionaries detected between two snapshots."""

    milestones: List[Dict[str, Any]] = []
    prev = prev_state or {}

    prev_pop = prev.get("pop") or prev.get("population") or 0
    curr_pop = curr_state.get("pop") or curr_state.get("population") or 0
    if curr_pop >= 10 and prev_pop < 10:
        milestones.append({"k": "POP_10", "ts": curr_state.get("time", 0)})

    prev_drink = prev.get("drink")
    if prev_drink is None and "stocks" in prev:
        prev_drink = prev.get("stocks", {}).get("drink")
    prev_drink = prev_drink if isinstance(prev_drink, (int, float)) else 0

    curr_drink = curr_state.get("drink")
    if curr_drink is None and "stocks" in curr_state:
        curr_drink = curr_state.get("stocks", {}).get("drink")
    curr_drink = curr_drink if isinstance(curr_drink, (int, float)) else 0
    if curr_drink >= 50 and prev_drink < 50:
        milestones.append({"k": "DRINK_50", "ts": curr_state.get("time", 0)})

    prev_hostiles = bool(prev.get("hostiles") or False)
    curr_hostiles = bool(curr_state.get("hostiles") or False)
    if curr_hostiles and not prev_hostiles:
        milestones.append({"k": "HOSTILES", "ts": curr_state.get("time", 0)})

    return milestones
