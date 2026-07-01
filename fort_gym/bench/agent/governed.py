"""Scripted DFHack-governed fortress agent.

This agent is intentionally deterministic. Its job is to validate the governed
action substrate before an LLM policy uses the same legal action surface.
"""

from __future__ import annotations

from typing import Any, Dict

from ..env.actions import parse_action
from .base import Agent, register_agent


ORDER_PLAN = ("bed", "door", "table", "chair", "barrel", "bin")


def _work(obs_json: Dict[str, Any]) -> Dict[str, Any]:
    value = obs_json.get("work")
    return value if isinstance(value, dict) else {}


def _work_int(work: Dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(work.get(key, default) or 0)
    except (TypeError, ValueError):
        return default


def _rect_action_params(rect: Any) -> Dict[str, Any] | None:
    if not isinstance(rect, (list, tuple)) or len(rect) < 6:
        return None
    try:
        x1, y1, z1, x2, y2, z2 = [int(value) for value in rect[:6]]
    except (TypeError, ValueError):
        return None
    if z1 != z2:
        return None
    return {
        "area": [min(x1, x2), min(y1, y2), z1],
        "size": [abs(x2 - x1) + 1, abs(y2 - y1) + 1, 1],
    }


class DFHackGovernedScriptedAgent(Agent):
    """Pursue the starter two-room workshop plan through structured actions."""

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        work = _work(obs_json)
        target_rect = work.get("target_rect") or [50, 35, 0, 54, 39, 0]
        connector_rect = work.get("fortress_connector_rect")
        workshop_room_rect = work.get("fortress_workshop_room_rect")

        target_tiles = max(1, _work_int(work, "target_tiles", 25))
        target_floor_tiles = _work_int(work, "target_floor_tiles")
        target_dig_designations = _work_int(work, "target_dig_designations")
        active_dig_jobs = _work_int(work, "active_dig_jobs")
        connector_tiles = max(1, _work_int(work, "fortress_connector_tiles", 3))
        connector_floor_tiles = _work_int(work, "fortress_connector_floor_tiles")
        workshop_room_tiles = max(1, _work_int(work, "fortress_workshop_room_tiles", 25))
        workshop_room_floor_tiles = _work_int(work, "fortress_workshop_room_floor_tiles")
        carpenter_workshops = _work_int(work, "carpenter_workshops")
        usable_workshops = _work_int(work, "carpenter_workshops_usable")
        manager_orders_count = _work_int(work, "manager_orders_count")
        active_jobs = _work_int(work, "active_jobs")

        if target_floor_tiles < target_tiles:
            if target_dig_designations <= 0 and active_dig_jobs <= 0:
                params = _rect_action_params(target_rect) or {
                    "area": [50, 35, 0],
                    "size": [5, 5, 1],
                }
                return parse_action(
                    {
                        "type": "DIG",
                        "params": params,
                        "intent": "designate the starter room for miners",
                        "objective": "Open safe interior shelter before production.",
                        "expected_simulation_result": "Miner job starts and wall tiles become floors.",
                        "advance_ticks": 1000,
                    }
                )
            return self._wait("starter room is already designated; let miners work")

        if connector_floor_tiles < connector_tiles:
            params = _rect_action_params(connector_rect)
            if params is not None and target_dig_designations <= 0 and active_dig_jobs <= 0:
                return parse_action(
                    {
                        "type": "DIG",
                        "params": params,
                        "intent": "dig the east connector toward the workshop room",
                        "objective": "Broaden the fortress layout beyond the starter room.",
                        "expected_simulation_result": "Connector wall tiles become walkable floor.",
                        "advance_ticks": 1000,
                    }
                )
            return self._wait("connector mining is pending or metrics are not ready")

        if workshop_room_floor_tiles < workshop_room_tiles:
            params = _rect_action_params(workshop_room_rect)
            if params is not None and target_dig_designations <= 0 and active_dig_jobs <= 0:
                return parse_action(
                    {
                        "type": "DIG",
                        "params": params,
                        "intent": "dig the workshop room east of the connector",
                        "objective": "Create a distinct production space.",
                        "expected_simulation_result": "Workshop-room wall tiles become floor.",
                        "advance_ticks": 1000,
                    }
                )
            return self._wait("workshop room mining is pending or metrics are not ready")

        if carpenter_workshops <= 0:
            workshop_room_params = _rect_action_params(workshop_room_rect)
            if workshop_room_params is not None:
                wx, wy, wz = workshop_room_params["area"]
            else:
                wx, wy, wz = 58, 35, 0
            return parse_action(
                {
                    "type": "BUILD",
                    "params": {"kind": "CarpenterWorkshop", "x": wx, "y": wy, "z": wz},
                    "intent": "place a carpenter workshop in the completed workshop room",
                    "objective": "Start real production in the new room.",
                    "expected_simulation_result": "A construct-building job appears, then a usable workshop.",
                    "advance_ticks": 1000,
                }
            )

        if usable_workshops <= 0 and active_jobs > 0:
            return self._wait("carpenter workshop is placed but not usable yet")

        if manager_orders_count < len(ORDER_PLAN):
            job = ORDER_PLAN[manager_orders_count]
            return parse_action(
                {
                    "type": "ORDER",
                    "params": {"job": job, "quantity": 2},
                    "intent": f"queue a small {job} order through the manager order helper",
                    "objective": "Prove production demand after workshop placement.",
                    "expected_simulation_result": "Manager/workshop jobs appear and consume material through dwarf labor.",
                    "advance_ticks": 1000,
                }
            )

        return self._wait("plan has rooms, a workshop, and a varied production queue")

    def _wait(self, reason: str) -> Dict[str, Any]:
        return parse_action(
            {
                "type": "WAIT",
                "params": {},
                "intent": reason,
                "objective": "Advance live simulation so dwarves can resolve queued work.",
                "expected_simulation_result": "Existing jobs progress without issuing another command.",
                "advance_ticks": 1000,
            }
        )


register_agent("dfhack-governed-scripted", lambda: DFHackGovernedScriptedAgent())


__all__ = ["DFHackGovernedScriptedAgent", "ORDER_PLAN"]
