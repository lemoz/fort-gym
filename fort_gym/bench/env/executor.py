"""Action executor placeholder that dispatches to the appropriate backend."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .actions import validate_action
from .dfhack_client import DFHackClient, DFHackUnavailableError
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

            if action_type == "DIG":
                area = params.get("area", (0, 0, 0))
                size = params.get("size", (1, 1, 1))
                x1, y1, z = area
                width, height, depth = size
                x2 = x1 + max(1, int(width)) - 1
                y2 = y1 + max(1, int(height)) - 1
                z2 = z + max(1, int(depth)) - 1
                ok, why = self._dfhack_client.designate_rect(x1, y1, z, x2, y2, z2)
                return {"accepted": bool(ok), "why": why}

            if action_type == "ORDER":
                job = params.get("job") or ""
                qty = int(params.get("quantity", 1))
                ok, why = self._dfhack_client.queue_manager_order(job, qty)
                return {"accepted": bool(ok), "why": why}

            if action_type == "BUILD":
                kind = params.get("kind")
                if kind != "CarpenterWorkshop":
                    return {
                        "accepted": False,
                        "why": "Only CarpenterWorkshop supported in beta",
                    }
                try:
                    x = int(params["x"])
                    y = int(params["y"])
                    z = int(params.get("z", 0))
                except (KeyError, TypeError, ValueError) as exc:
                    return {"accepted": False, "why": f"Invalid coordinates: {exc}"}
                ok, why = self._dfhack_client.place_building(kind, x, y, z)
                return {"accepted": bool(ok), "why": why}

            return {"accepted": False, "why": f"Unsupported DFHack action: {action_type}"}

        raise ValueError(f"Unsupported backend: {backend}")
