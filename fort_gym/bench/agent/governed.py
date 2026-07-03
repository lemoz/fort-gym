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


def _build_site(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        x, y, z = [int(part) for part in value[:3]]
    except (TypeError, ValueError):
        return None
    return x, y, z


def _space_complete(
    work: Dict[str, Any],
    *,
    tiles_key: str,
    floor_key: str,
    wall_key: str,
    hidden_key: str,
    missing_key: str,
    default_tiles: int,
) -> bool:
    tiles = max(1, _work_int(work, tiles_key, default_tiles))
    floor_tiles = _work_int(work, floor_key)
    wall_tiles = _work_int(work, wall_key)
    hidden_tiles = _work_int(work, hidden_key)
    missing_blocks = _work_int(work, missing_key)
    if wall_tiles <= 0 and hidden_tiles <= 0 and missing_blocks <= 0 and floor_tiles > 0:
        return True
    return floor_tiles >= tiles


class DFHackGovernedScriptedAgent(Agent):
    """Pursue the starter two-room workshop plan through structured actions."""

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        work = _work(obs_json)
        target_rect = work.get("target_rect") or [50, 35, 0, 54, 39, 0]
        connector_rect = work.get("fortress_connector_rect")
        workshop_room_rect = work.get("fortress_workshop_room_rect")

        target_dig_designations = _work_int(work, "target_dig_designations")
        active_dig_jobs = _work_int(work, "active_dig_jobs")
        carpenter_workshops = _work_int(work, "carpenter_workshops")
        usable_workshops = _work_int(work, "carpenter_workshops_usable")
        manager_orders_count = _work_int(work, "manager_orders_count")
        active_jobs = _work_int(work, "active_jobs")

        starter_complete = _space_complete(
            work,
            tiles_key="target_tiles",
            floor_key="target_floor_tiles",
            wall_key="target_wall_tiles",
            hidden_key="target_hidden_tiles",
            missing_key="target_missing_blocks",
            default_tiles=25,
        )
        connector_complete = _space_complete(
            work,
            tiles_key="fortress_connector_tiles",
            floor_key="fortress_connector_floor_tiles",
            wall_key="fortress_connector_wall_tiles",
            hidden_key="fortress_connector_hidden_tiles",
            missing_key="fortress_connector_missing_blocks",
            default_tiles=3,
        )
        workshop_room_complete = _space_complete(
            work,
            tiles_key="fortress_workshop_room_tiles",
            floor_key="fortress_workshop_room_floor_tiles",
            wall_key="fortress_workshop_room_wall_tiles",
            hidden_key="fortress_workshop_room_hidden_tiles",
            missing_key="fortress_workshop_room_missing_blocks",
            default_tiles=25,
        )
        observed_build_site = _build_site(work.get("carpenter_build_site"))

        if not starter_complete:
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

        if not connector_complete:
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

        if not workshop_room_complete and carpenter_workshops <= 0:
            if (
                observed_build_site is not None
                and active_dig_jobs <= 0
                and _work_int(work, "fortress_workshop_room_floor_tiles") >= 9
            ):
                wx, wy, wz = observed_build_site
                return parse_action(
                    {
                        "type": "BUILD",
                        "params": {"kind": "CarpenterWorkshop", "x": wx, "y": wy, "z": wz},
                        "intent": "place a carpenter workshop on an observed legal 3x3 floor site",
                        "objective": "Start production once enough usable floor exists, even if the annex still has rough edges.",
                        "expected_simulation_result": "A construct-building job appears, then a usable workshop.",
                        "advance_ticks": 1000,
                    }
                )
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
            if observed_build_site is not None:
                wx, wy, wz = observed_build_site
            else:
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
