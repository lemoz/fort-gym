"""Action executor placeholder that dispatches to the appropriate backend."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .actions import validate_action
from .dfhack_client import DFHackClient, DFHackUnavailableError
from ..dfhack_backend import build_construction as safe_build_construction
from ..dfhack_backend import build_workshop as safe_build_workshop
from ..dfhack_backend import complete_dig_rect as safe_complete_dig_rect
from ..dfhack_backend import designate_rect as safe_designate_rect
from ..dfhack_backend import place_furniture as safe_place_furniture
from ..dfhack_backend import queue_manager_order as safe_queue_manager_order
from .keystroke_exec import execute_keystroke_action
from .mock_env import MockEnvironment
from .state_reader import StateReader


def _normalize_rect(value: Any) -> tuple[int, int, int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 6:
        return None
    try:
        x1, y1, z1, x2, y2, z2 = [int(v) for v in value[:6]]
    except (TypeError, ValueError):
        return None
    return (
        min(x1, x2),
        min(y1, y2),
        min(z1, z2),
        max(x1, x2),
        max(y1, y2),
        max(z1, z2),
    )


class Executor:
    """Apply actions to the configured backend while enforcing validation."""

    def __init__(
        self,
        mock_env: Optional[MockEnvironment] = None,
        dfhack_client: Optional[DFHackClient] = None,
    ) -> None:
        self._mock_env = mock_env or MockEnvironment()
        self._dfhack_client = dfhack_client

    def apply(
        self,
        action: Dict[str, Any],
        *,
        backend: str = "mock",
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate the action and forward to the selected backend."""

        if backend == "mock":
            current_state = state or StateReader.from_mock(self._mock_env)
            valid, reason = validate_action(current_state, action)
            if not valid:
                raise ValueError(f"Invalid action: {reason}")
            if action.get("type") == "WAIT":
                return {"accepted": True, "state": current_state}
            new_state = self._mock_env.apply(action)
            return {"accepted": True, "state": new_state}

        if backend == "dfhack":
            if not self._dfhack_client:
                raise DFHackUnavailableError("DFHack client not provided")
            current_state = state or StateReader.from_dfhack(self._dfhack_client)
            valid, reason = validate_action(current_state, action)
            if not valid:
                return {"accepted": False, "why": reason}

            action_type = action.get("type")
            params = action.get("params", {})

            if action_type == "WAIT":
                return {"accepted": True, "state": current_state}

            if action_type == "DIG":
                area = params.get("area", (0, 0, 0))
                size = params.get("size", (1, 1, 1))
                kind = str(params.get("kind") or "dig").lower()
                x1, y1, z = map(int, area)
                width, height, depth = map(int, size)
                x2 = x1 + max(1, width) - 1
                y2 = y1 + max(1, height) - 1
                z2 = z + max(1, depth) - 1
                result = safe_designate_rect(kind, x1, y1, z, x2, y2, z2)
                if (
                    kind == "dig"
                    and result.get("ok")
                    and os.getenv("FORT_GYM_DFHACK_COMPLETE_DIG", "0") == "1"
                ):
                    completion = safe_complete_dig_rect(x1, y1, z, x2, y2, z2)
                    result = {**result, "completion": completion}
                return {
                    "accepted": bool(result.get("ok")),
                    "why": None if result.get("ok") else result.get("error"),
                    "result": result,
                }

            if action_type == "ORDER":
                job = (params.get("job") or "").lower()
                qty = int(params.get("quantity", 1))
                result = safe_queue_manager_order(job, qty)
                return {
                    "accepted": bool(result.get("ok")),
                    "why": None if result.get("ok") else result.get("error"),
                    "result": result,
                }

            if action_type == "BUILD":
                kind = params.get("kind")
                if kind not in {
                    "CarpenterWorkshop",
                    "Bed",
                    "Door",
                    "Table",
                    "Chair",
                    "Wall",
                    "Floor",
                }:
                    return {
                        "accepted": False,
                        "why": (
                            "Unsupported BUILD kind: expected CarpenterWorkshop, "
                            "furniture (Bed/Door/Table/Chair), or construction "
                            "(Wall/Floor)"
                        ),
                    }
                try:
                    x = int(params["x"])
                    y = int(params["y"])
                    z = int(params.get("z", 0))
                except (KeyError, TypeError, ValueError) as exc:
                    return {"accepted": False, "why": f"Invalid coordinates: {exc}"}
                if kind in {"Wall", "Floor"}:
                    try:
                        x2 = int(params.get("x2", x))
                        y2 = int(params.get("y2", y))
                    except (TypeError, ValueError) as exc:
                        return {"accepted": False, "why": f"Invalid coordinates: {exc}"}
                    result = safe_build_construction(kind, x, y, z, x2, y2)
                    return {
                        "accepted": bool(result.get("ok")),
                        "why": None if result.get("ok") else result.get("error"),
                        "result": result,
                    }
                work = current_state.get("work") if isinstance(current_state, dict) else {}
                work_rect = (
                    _normalize_rect(work.get("target_rect"))
                    if isinstance(work, dict)
                    else None
                )
                extra_allowed_rects = []
                if isinstance(work, dict):
                    for key in (
                        "carpenter_build_site_rect",
                        "carpenter_build_placement_rect",
                    ):
                        rect = _normalize_rect(work.get(key))
                        if rect is not None:
                            extra_allowed_rects.append(rect)
                if kind == "CarpenterWorkshop":
                    result = safe_build_workshop(
                        kind,
                        x,
                        y,
                        z,
                        work_rect=work_rect,
                        extra_allowed_rects=extra_allowed_rects,
                    )
                else:
                    result = safe_place_furniture(
                        kind,
                        x,
                        y,
                        z,
                        work_rect=work_rect,
                        extra_allowed_rects=extra_allowed_rects,
                    )
                return {
                    "accepted": bool(result.get("ok")),
                    "why": None if result.get("ok") else result.get("error"),
                    "result": result,
                }

            if action_type == "KEYSTROKE":
                keys = params.get("keys", [])
                if not keys:
                    return {
                        "accepted": True,
                        "state": current_state,
                        "result": {
                            "ok": True,
                            "keys_sent": 0,
                            "advance_only": True,
                        },
                    }
                result = execute_keystroke_action(keys)
                return {
                    "accepted": bool(result.get("ok")),
                    "why": None if result.get("ok") else result.get("error"),
                    "result": result,
                }

            return {"accepted": False, "why": f"Unsupported DFHack action: {action_type}"}

        raise ValueError(f"Unsupported backend: {backend}")
