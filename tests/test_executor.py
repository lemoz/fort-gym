from __future__ import annotations

from typing import Any, Dict

from fort_gym.bench.env.executor import Executor


class _ConnectedDFHackClient:
    def get_state(self) -> Dict[str, Any]:
        return {
            "time": 0,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wealth": 9},
            "risks": [],
            "reminders": [],
            "recent_events": [],
            "hostiles": False,
            "dead": 0,
            "map_bounds": (100, 100, 10),
        }


def test_dfhack_build_action_uses_bounded_workshop_hook(monkeypatch) -> None:
    calls: list[tuple[str, int, int, int]] = []

    def fake_build_workshop(kind: str, x: int, y: int, z: int) -> Dict[str, Any]:
        calls.append((kind, x, y, z))
        return {"ok": True, "kind": kind, "x": x, "y": y, "z": z}

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_build_workshop", fake_build_workshop)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "CarpenterWorkshop", "x": 51, "y": 36, "z": 0}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert result["result"]["kind"] == "CarpenterWorkshop"
    assert calls == [("CarpenterWorkshop", 51, 36, 0)]
