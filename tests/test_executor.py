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

    def fake_build_workshop(
        kind: str,
        x: int,
        y: int,
        z: int,
        *,
        work_rect=None,
        extra_allowed_rects=None,
    ) -> Dict[str, Any]:
        calls.append((kind, x, y, z))
        return {"ok": True, "kind": kind, "x": x, "y": y, "z": z, "work_rect": work_rect}

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_build_workshop", fake_build_workshop)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "CarpenterWorkshop", "x": 51, "y": 36, "z": 0}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert result["result"]["kind"] == "CarpenterWorkshop"
    assert result["result"]["work_rect"] is None
    assert calls == [("CarpenterWorkshop", 51, 36, 0)]


def test_dfhack_build_action_uses_state_work_rect(monkeypatch) -> None:
    seen: list[tuple[int, int, int, int, int, int] | None] = []

    def fake_build_workshop(
        kind: str,
        x: int,
        y: int,
        z: int,
        *,
        work_rect=None,
        extra_allowed_rects=None,
    ) -> Dict[str, Any]:
        seen.append(work_rect)
        return {"ok": True, "kind": kind, "x": x, "y": y, "z": z}

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_build_workshop", fake_build_workshop)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "CarpenterWorkshop", "x": 106, "y": 97, "z": 177}},
        backend="dfhack",
        state={
            "time": 0,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wealth": 9},
            "map_bounds": (200, 200, 200),
            "work": {"target_rect": [98, 97, 177, 102, 101, 177]},
        },
    )

    assert result["accepted"] is True
    assert seen == [(98, 97, 177, 102, 101, 177)]


def test_dfhack_dig_does_not_complete_by_default(monkeypatch) -> None:
    complete_calls: list[tuple[int, int, int, int, int, int]] = []

    def fake_designate_rect(kind: str, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        return {"ok": True, "kind": kind, "rect": [x1, y1, z1, x2, y2, z2]}

    def fake_complete_dig_rect(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        complete_calls.append((x1, y1, z1, x2, y2, z2))
        return {"ok": True}

    monkeypatch.delenv("FORT_GYM_DFHACK_COMPLETE_DIG", raising=False)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_designate_rect", fake_designate_rect)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_complete_dig_rect", fake_complete_dig_rect)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "DIG", "params": {"area": [50, 35, 0], "size": [5, 5, 1]}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert "completion" not in result["result"]
    assert complete_calls == []


def test_dfhack_dig_completion_requires_explicit_opt_in(monkeypatch) -> None:
    complete_calls: list[tuple[int, int, int, int, int, int]] = []

    def fake_designate_rect(kind: str, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        return {"ok": True, "kind": kind, "rect": [x1, y1, z1, x2, y2, z2]}

    def fake_complete_dig_rect(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        complete_calls.append((x1, y1, z1, x2, y2, z2))
        return {"ok": True, "changed": 25}

    monkeypatch.setenv("FORT_GYM_DFHACK_COMPLETE_DIG", "1")
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_designate_rect", fake_designate_rect)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_complete_dig_rect", fake_complete_dig_rect)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "DIG", "params": {"area": [50, 35, 0], "size": [5, 5, 1]}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert result["result"]["completion"] == {"ok": True, "changed": 25}
    assert complete_calls == [(50, 35, 0, 54, 39, 0)]


def test_dfhack_keystroke_allows_advance_only_empty_keys(monkeypatch) -> None:
    def fail_execute_keystroke_action(_keys):
        raise AssertionError("advance-only empty keys should not send keystrokes")

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.execute_keystroke_action",
        fail_execute_keystroke_action,
    )

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {
            "type": "KEYSTROKE",
            "params": {"keys": []},
            "intent": "let dwarves work without another UI key",
            "advance_ticks": 1500,
        },
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert result["result"] == {"ok": True, "keys_sent": 0, "advance_only": True}
