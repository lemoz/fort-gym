from __future__ import annotations

from fort_gym.bench.dfhack_backend import MAX_SNAPSHOT_H, MAX_SNAPSHOT_W
from fort_gym.bench.run.runner import _map_snapshot_rect_from_state

LEGACY_WORK = {
    "target_rect": [90, 90, 177, 96, 96, 177],
    "fortress_connector_rect": [96, 92, 177, 98, 94, 177],
    "fortress_workshop_room_rect": [98, 90, 177, 104, 96, 177],
}


def test_snapshot_rect_follows_fort_minimap_window() -> None:
    # The fort grew east of the legacy plan rects (run 2f58fd37): the window
    # must follow the fort minimap bbox, not the retired plan.
    state = {
        "work": dict(LEGACY_WORK),
        "fort": {
            "ok": True,
            "map_origin": [100, 95, 177],
            "map_rows": ["." * 20] * 12,
        },
    }

    rect = _map_snapshot_rect_from_state(state, margin=1)

    assert rect == (99, 94, 177, 99 + 21, 94 + 13, 177)


def test_snapshot_rect_falls_back_to_legacy_without_fort() -> None:
    state = {"work": dict(LEGACY_WORK)}

    rect = _map_snapshot_rect_from_state(state, margin=1)

    assert rect == (89, 89, 177, 105, 97, 177)


def test_snapshot_rect_falls_back_on_malformed_fort_data() -> None:
    for bad_fort in (
        {"ok": True, "map_origin": "junk", "map_rows": ["..."]},
        {"ok": True, "map_origin": [1, 2, 3], "map_rows": "junk"},
        {"ok": True, "map_origin": [1, 2], "map_rows": ["..."]},
        {"ok": False, "map_origin": [1, 2, 3], "map_rows": ["..."]},
        {"ok": True, "map_origin": [1, 2, 3], "map_rows": []},
    ):
        state = {"work": dict(LEGACY_WORK), "fort": bad_fort}
        assert _map_snapshot_rect_from_state(state, margin=1) == (
            89,
            89,
            177,
            105,
            97,
            177,
        ), bad_fort


def test_snapshot_rect_clamps_to_snapshot_bounds() -> None:
    state = {
        "fort": {
            "ok": True,
            "map_origin": [10, 10, 5],
            "map_rows": ["." * 100] * 100,
        }
    }

    rect = _map_snapshot_rect_from_state(state, margin=1)

    assert rect is not None
    x1, y1, z1, x2, y2, z2 = rect
    assert x2 - x1 + 1 <= MAX_SNAPSHOT_W
    assert y2 - y1 + 1 <= MAX_SNAPSHOT_H
    assert z1 == z2 == 5


def test_snapshot_rect_none_without_fort_or_work() -> None:
    assert _map_snapshot_rect_from_state({}) is None
    assert _map_snapshot_rect_from_state({"work": "junk"}) is None
