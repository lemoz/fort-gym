from __future__ import annotations

import re
from pathlib import Path

from fort_gym.bench.dfhack_backend import (
    MAX_RECT_H,
    MAX_RECT_W,
    MAX_SNAPSHOT_H,
    MAX_SNAPSHOT_W,
)
from fort_gym.bench.run.runner import (
    _job_metrics_survey_rect,
    _map_snapshot_rect_from_state,
    _snapshot_tile_changes,
)

RUNNER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "fort_gym"
    / "bench"
    / "run"
    / "runner.py"
).read_text(encoding="utf-8")

LEGACY_WORK = {
    "target_rect": [90, 90, 177, 96, 96, 177],
    "fortress_connector_rect": [96, 92, 177, 98, 94, 177],
    "fortress_workshop_room_rect": [98, 90, 177, 104, 96, 177],
}

# A fort minimap at its lua-bounded 34x34 extent — with margin the snapshot rect
# is 36 wide, which read_job_metrics (MAX_RECT_W/H = 30) rejects outright.
FULL_FORT = {
    "ok": True,
    "map_origin": [100, 95, 177],
    "map_rows": ["." * 34] * 34,
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


def test_job_metrics_survey_rect_bounds_full_fort_window_to_job_limit() -> None:
    # The full-fort snapshot rect is 36 wide (34 + 2*margin); read_job_metrics
    # rejects anything over MAX_RECT_W/H and would drop the ENTIRE crew read.
    # The survey rect must shrink to the job-metrics bound so crew still attaches.
    state = {"work": dict(LEGACY_WORK), "fort": dict(FULL_FORT)}

    snapshot_rect = _map_snapshot_rect_from_state(state, margin=1)
    survey_rect = _job_metrics_survey_rect(state, margin=1)

    assert snapshot_rect is not None and survey_rect is not None
    # The full snapshot rect exceeds the job-metrics limit...
    assert (snapshot_rect[3] - snapshot_rect[0] + 1) > MAX_RECT_W
    # ...but the survey rect is clamped down so read_job_metrics accepts it.
    x1, y1, z1, x2, y2, z2 = survey_rect
    assert (x2 - x1 + 1) <= MAX_RECT_W
    assert (y2 - y1 + 1) <= MAX_RECT_H
    # Same origin/z as the snapshot window — it is a sub-window, not a new anchor.
    assert (x1, y1, z1, z2) == (snapshot_rect[0], snapshot_rect[1], snapshot_rect[2], snapshot_rect[5])


def test_job_metrics_survey_rect_passes_small_rect_through_unchanged() -> None:
    # A legacy-sized window already fits the job-metrics bound; pass it verbatim.
    state = {"work": dict(LEGACY_WORK)}
    assert _job_metrics_survey_rect(state, margin=1) == _map_snapshot_rect_from_state(
        state, margin=1
    )


def test_job_metrics_survey_rect_none_without_rect() -> None:
    assert _job_metrics_survey_rect({}) is None


def test_governed_step_computes_snapshot_rect_once_and_reuses_it() -> None:
    # SAME-STEP BEFORE/AFTER RECT IDENTITY (proof-integrity critical):
    # the governed proof path must compute the snapshot rect exactly once per
    # step and reuse the identical value for both the before-capture and the
    # after-capture. Recomputing between them could misalign the tile diff.
    #
    # Structurally: governed_snapshot_rect is assigned once from state_before,
    # the before-capture reads it, and the after-rect selection reuses the same
    # variable (never a fresh _map_snapshot_rect_from_state call for the after).
    assigns = re.findall(
        r"governed_snapshot_rect\s*=\s*_map_snapshot_rect_from_state\(", RUNNER_SOURCE
    )
    assert len(assigns) == 1, "governed snapshot rect must be computed exactly once per step"
    assert "governed_snapshot_rect = _map_snapshot_rect_from_state(state_before)" in RUNNER_SOURCE
    assert "map_snapshot_before = read_map_snapshot(governed_snapshot_rect)" in RUNNER_SOURCE
    # After-capture reuses the hoisted rect rather than recomputing.
    assert "snapshot_rect = governed_snapshot_rect" in RUNNER_SOURCE


def test_snapshot_tile_changes_rejects_mismatched_rects() -> None:
    # Proof-integrity safety net: if the before/after rects ever drift, the diff
    # must refuse to compare (absolute coordinates would no longer describe the
    # same window) instead of emitting a misaligned, false tile-change proof.
    before = {"ok": True, "rect": [10, 20, 0, 11, 20, 0], "tiles": []}
    after = {"ok": True, "rect": [12, 20, 0, 13, 20, 0], "tiles": []}

    result = _snapshot_tile_changes(before, after)

    assert result["ok"] is False
    assert result["reason"] == "snapshot_rect_changed"
    assert result["changed_tile_count"] == 0


def test_snapshot_tile_changes_aligns_on_absolute_coordinates() -> None:
    # Tiles are keyed by their absolute (x, y, z), so identical rects align a
    # changed tile by coordinate regardless of the window's origin.
    rect = [50, 50, 2, 51, 50, 2]
    before = {
        "ok": True,
        "rect": rect,
        "tiles": [
            {"x": 50, "y": 50, "z": 2, "category": "wall", "char": "#", "dig": "No"},
            {"x": 51, "y": 50, "z": 2, "category": "wall", "char": "#", "dig": "No"},
        ],
    }
    after = {
        "ok": True,
        "rect": list(rect),
        "tiles": [
            {"x": 50, "y": 50, "z": 2, "category": "wall", "char": "#", "dig": "No"},
            {"x": 51, "y": 50, "z": 2, "category": "floor", "char": ".", "dig": "No"},
        ],
    }

    result = _snapshot_tile_changes(before, after)

    assert result["ok"] is True
    assert result["changed_tile_count"] == 1
    changed = result["changed_tiles"][0]
    assert (changed["x"], changed["y"], changed["z"]) == (51, 50, 2)
    assert changed["before"]["category"] == "wall"
    assert changed["after"]["category"] == "floor"
