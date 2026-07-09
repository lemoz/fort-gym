"""Action executor placeholder that dispatches to the appropriate backend."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .actions import validate_action
from .dfhack_client import DFHackClient, DFHackUnavailableError
from ..dfhack_backend import build_construction as safe_build_construction
from ..dfhack_backend import build_farm_plot as safe_build_farm_plot
from ..dfhack_backend import build_workshop as safe_build_workshop
from ..dfhack_backend import complete_dig_rect as safe_complete_dig_rect
from ..dfhack_backend import designate_rect as safe_designate_rect
from ..dfhack_backend import place_furniture as safe_place_furniture
from ..dfhack_backend import queue_manager_order as safe_queue_manager_order
from ..dfhack_backend import set_labor as safe_set_labor
from ..dfhack_backend import set_farm_crop as safe_set_farm_crop
from ..dfhack_backend import unsuspend_jobs as safe_unsuspend_jobs
from .keystroke_exec import execute_keystroke_action
from .mock_env import MockEnvironment
from .state_reader import StateReader


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

            if action_type == "UNSUSPEND":
                area = params.get("area", (0, 0, 0))
                size = params.get("size", (1, 1, 1))
                x1, y1, z = map(int, area)
                width, height, _depth = map(int, size)
                x2 = x1 + max(1, width) - 1
                y2 = y1 + max(1, height) - 1
                result = safe_unsuspend_jobs(x1, y1, z, x2, y2, z)
                return {
                    "accepted": bool(result.get("ok")),
                    "why": None if result.get("ok") else result.get("error"),
                    "result": result,
                }

            if action_type == "LABOR":
                try:
                    unit_id = int(params["unit_id"])
                except (KeyError, TypeError, ValueError) as exc:
                    return {"accepted": False, "why": f"Invalid unit_id: {exc}"}
                labor = str(params.get("labor") or "").lower()
                enable = bool(params.get("enable"))
                result = safe_set_labor(unit_id, labor, enable)
                return {
                    "accepted": bool(result.get("ok")),
                    "why": None if result.get("ok") else result.get("error"),
                    "result": result,
                }

            if action_type == "FARM":
                try:
                    building_id = int(params["building_id"])
                except (KeyError, TypeError, ValueError) as exc:
                    return {"accepted": False, "why": f"Invalid building_id: {exc}"}
                crop = params.get("crop")
                if not isinstance(crop, str) or not crop.strip():
                    return {"accepted": False, "why": "FARM requires a crop token or 'clear'"}
                seasons = params.get("seasons")
                result = safe_set_farm_crop(building_id, crop, seasons)
                return {
                    "accepted": bool(result.get("ok")),
                    "why": None if result.get("ok") else result.get("error"),
                    "result": result,
                }

            if action_type == "BUILD":
                kind = params.get("kind")
                if kind not in {
                    "CarpenterWorkshop",
                    "Still",
                    "FarmPlot",
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
                            "Still, FarmPlot, furniture (Bed/Door/Table/Chair), or "
                            "construction (Wall/Floor)"
                        ),
                    }
                try:
                    x = int(params["x"])
                    y = int(params["y"])
                    z = int(params.get("z", 0))
                except (KeyError, TypeError, ValueError) as exc:
                    return {"accepted": False, "why": f"Invalid coordinates: {exc}"}
                if kind in {"Wall", "Floor", "FarmPlot"}:
                    try:
                        raw_x2 = params.get("x2")
                        raw_y2 = params.get("y2")
                        x2 = x if raw_x2 is None else int(raw_x2)
                        y2 = y if raw_y2 is None else int(raw_y2)
                    except (TypeError, ValueError) as exc:
                        return {"accepted": False, "why": f"Invalid coordinates: {exc}"}
                    if kind == "FarmPlot":
                        result = safe_build_farm_plot(x, y, z, x2, y2)
                    else:
                        result = safe_build_construction(kind, x, y, z, x2, y2)
                    return {
                        "accepted": bool(result.get("ok")),
                        "why": None if result.get("ok") else result.get("error"),
                        "result": result,
                    }
                if kind in {"CarpenterWorkshop", "Still"}:
                    result = safe_build_workshop(kind, x, y, z)
                else:
                    result = safe_place_furniture(kind, x, y, z)
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
