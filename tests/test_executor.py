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


def test_dfhack_build_still_routes_to_build_workshop_hook(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_build_workshop(kind: str, x: int, y: int, z: int) -> Dict[str, Any]:
        calls.append((kind, x, y, z))
        return {
            "ok": True,
            "kind": kind,
            "before_workshops_of_kind": 0,
            "after_workshops_of_kind": 1,
        }

    def fake_place_furniture(*args, **kwargs):
        raise AssertionError("Still must not route to place_furniture")

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_build_workshop", fake_build_workshop)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_place_furniture", fake_place_furniture)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "Still", "x": 88, "y": 96, "z": 177}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [("Still", 88, 96, 177)]
    assert result["result"]["after_workshops_of_kind"] == 1


def test_dfhack_build_action_does_not_thread_state_work_rect(monkeypatch) -> None:
    seen: list[tuple] = []

    def fake_build_workshop(kind: str, x: int, y: int, z: int) -> Dict[str, Any]:
        seen.append((kind, x, y, z))
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
    assert seen == [("CarpenterWorkshop", 106, 97, 177)]


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


def test_dfhack_dig_chop_kind_routes_to_chop_and_skips_completion(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_designate_rect(kind: str, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        calls.append((kind, x1, y1, z1, x2, y2, z2))
        return {"ok": True, "kind": kind}

    def fake_complete_dig_rect(*args):
        raise AssertionError("chop must never trigger dig completion")

    monkeypatch.setenv("FORT_GYM_DFHACK_COMPLETE_DIG", "1")
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_designate_rect", fake_designate_rect)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_complete_dig_rect", fake_complete_dig_rect)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "DIG", "params": {"area": [50, 35, 0], "size": [3, 3, 1], "kind": "chop"}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [("chop", 50, 35, 0, 52, 37, 0)]


def test_dfhack_dig_gather_kind_routes_to_gather_and_skips_completion(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_designate_rect(kind: str, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        calls.append((kind, x1, y1, z1, x2, y2, z2))
        return {"ok": True, "kind": kind, "shrubs_designated": 3}

    def fake_complete_dig_rect(*args):
        raise AssertionError("gather must never trigger dig completion")

    monkeypatch.setenv("FORT_GYM_DFHACK_COMPLETE_DIG", "1")
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_designate_rect", fake_designate_rect)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_complete_dig_rect", fake_complete_dig_rect)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "DIG", "params": {"area": [50, 35, 0], "size": [3, 3, 1], "kind": "gather"}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [("gather", 50, 35, 0, 52, 37, 0)]
    assert result["result"]["shrubs_designated"] == 3


def test_dfhack_unsuspend_routes_to_backend_wrapper_with_plain_args(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_unsuspend_jobs(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        calls.append((x1, y1, z1, x2, y2, z2))
        return {"ok": True, "unsuspended": 1, "suspended_found": 1}

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_unsuspend_jobs", fake_unsuspend_jobs)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "UNSUSPEND", "params": {"area": [101, 98, 177], "size": [1, 1, 1]}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert result["result"] == {"ok": True, "unsuspended": 1, "suspended_found": 1}
    assert calls == [(101, 98, 177, 101, 98, 177)]


def test_dfhack_unsuspend_expands_rect_from_area_and_size(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_unsuspend_jobs(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int):
        calls.append((x1, y1, z1, x2, y2, z2))
        return {"ok": True, "unsuspended": 0, "suspended_found": 0}

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_unsuspend_jobs", fake_unsuspend_jobs)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "UNSUSPEND", "params": {"area": [98, 95, 177], "size": [5, 5, 1]}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [(98, 95, 177, 102, 99, 177)]


def test_dfhack_unsuspend_reports_rejection_when_hook_errors(monkeypatch) -> None:
    def fake_unsuspend_jobs(*args):
        return {"ok": False, "error": "rect_too_large"}

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_unsuspend_jobs", fake_unsuspend_jobs)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "UNSUSPEND", "params": {"area": [0, 0, 0], "size": [11, 11, 1]}},
        backend="dfhack",
    )

    assert result["accepted"] is False
    assert result["why"] == "rect_too_large"


def test_dfhack_order_brew_routes_to_backend_wrapper(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_queue_manager_order(job: str, qty: int):
        calls.append((job, qty))
        return {"ok": True, "item": job, "qty": qty, "mode": "workshop_job", "workshop_id": 3}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_queue_manager_order", fake_queue_manager_order
    )

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "ORDER", "params": {"job": "brew", "quantity": 2}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [("brew", 2)]


def test_parse_action_defaults_dig_kind_to_dig() -> None:
    from fort_gym.bench.env.actions import parse_action

    action = parse_action(
        {
            "type": "DIG",
            "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
            "intent": "plain dig",
        }
    )
    assert action["params"]["kind"] == "dig"

    chop = parse_action(
        {
            "type": "DIG",
            "params": {"area": [50, 35, 0], "size": [3, 3, 1], "kind": "chop"},
            "intent": "fell trees",
        }
    )
    assert chop["params"]["kind"] == "chop"

    gather = parse_action(
        {
            "type": "DIG",
            "params": {"area": [50, 35, 0], "size": [3, 3, 1], "kind": "gather"},
            "intent": "gather shrubs",
        }
    )
    assert gather["params"]["kind"] == "gather"


def test_dfhack_build_furniture_routes_to_place_furniture(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_place_furniture(kind, x, y, z):
        calls.append((kind, x, y, z))
        return {"ok": True, "kind": kind, "building_id": 7}

    def fake_build_workshop(*args, **kwargs):
        raise AssertionError("furniture must not route to the workshop hook")

    monkeypatch.setattr("fort_gym.bench.env.executor.safe_place_furniture", fake_place_furniture)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_build_workshop", fake_build_workshop)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "Bed", "x": 96, "y": 96, "z": 177}},
        backend="dfhack",
        state={"work": {"target_rect": [90, 90, 177, 99, 99, 177]}},
    )

    assert result["accepted"] is True
    assert calls == [("Bed", 96, 96, 177)]


def test_dfhack_build_rejects_unknown_kind() -> None:
    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "Throne", "x": 1, "y": 1, "z": 0}},
        backend="dfhack",
    )
    assert result["accepted"] is False
    assert "Unsupported BUILD kind" in result["why"]


def test_dfhack_build_wall_routes_to_build_construction_without_work_rect(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_build_construction(kind, x, y, z, x2, y2):
        calls.append((kind, x, y, z, x2, y2))
        return {"ok": True, "kind": kind, "placed_count": 4}

    def fake_place_furniture(*args, **kwargs):
        raise AssertionError("constructions must not route to the furniture hook")

    def fake_build_workshop(*args, **kwargs):
        raise AssertionError("constructions must not route to the workshop hook")

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_construction", fake_build_construction
    )
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_place_furniture", fake_place_furniture)
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_build_workshop", fake_build_workshop)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {
            "type": "BUILD",
            "params": {"kind": "Wall", "x": 10, "y": 20, "z": 0, "x2": 12, "y2": 20},
        },
        backend="dfhack",
        state={"work": {"target_rect": [90, 90, 177, 99, 99, 177]}},
    )

    assert result["accepted"] is True
    assert calls == [("Wall", 10, 20, 0, 12, 20)]


def test_dfhack_build_floor_defaults_x2_y2_to_xy(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_build_construction(kind, x, y, z, x2, y2):
        calls.append((kind, x, y, z, x2, y2))
        return {"ok": True, "kind": kind, "placed_count": 1}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_construction", fake_build_construction
    )

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "Floor", "x": 30, "y": 40, "z": 2}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [("Floor", 30, 40, 2, 30, 40)]


def test_dfhack_build_farm_plot_routes_to_backend_wrapper_with_rect_corner(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_build_farm_plot(x1, y1, z, x2, y2):
        calls.append((x1, y1, z, x2, y2))
        return {"ok": True, "kind": "FarmPlot", "before_farm_plots": 0, "after_farm_plots": 1}

    def fake_build_construction(*args, **kwargs):
        raise AssertionError("FarmPlot must not route to build_construction")

    def fake_place_furniture(*args, **kwargs):
        raise AssertionError("FarmPlot must not route to place_furniture")

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_farm_plot", fake_build_farm_plot
    )
    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_construction", fake_build_construction
    )
    monkeypatch.setattr("fort_gym.bench.env.executor.safe_place_furniture", fake_place_furniture)

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {
            "type": "BUILD",
            "params": {"kind": "FarmPlot", "x": 90, "y": 95, "z": 177, "x2": 92, "y2": 97},
        },
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [(90, 95, 177, 92, 97)]
    assert result["result"]["after_farm_plots"] == 1


def test_dfhack_build_farm_plot_defaults_x2_y2_to_xy(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_build_farm_plot(x1, y1, z, x2, y2):
        calls.append((x1, y1, z, x2, y2))
        return {"ok": True, "kind": "FarmPlot"}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_farm_plot", fake_build_farm_plot
    )

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {"type": "BUILD", "params": {"kind": "FarmPlot", "x": 30, "y": 40, "z": 2}},
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [(30, 40, 2, 30, 40)]


def test_dfhack_build_wall_normalizes_explicit_null_coords(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_build_construction(kind, x, y, z, x2, y2):
        calls.append((kind, x, y, z, x2, y2))
        return {"ok": True, "placed_count": 1}

    monkeypatch.setattr(
        "fort_gym.bench.env.executor.safe_build_construction", fake_build_construction
    )

    result = Executor(dfhack_client=_ConnectedDFHackClient()).apply(
        {
            "type": "BUILD",
            "params": {"kind": "Wall", "x": 94, "y": 91, "z": 177, "x2": None, "y2": None},
        },
        backend="dfhack",
    )

    assert result["accepted"] is True
    assert calls == [("Wall", 94, 91, 177, 94, 91)]
