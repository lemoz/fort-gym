from __future__ import annotations

from fort_gym.bench.run.runner import (
    _ui_target_setup_for_observation,
    _ui_work_rect_from_state,
    _zero_assisted_dfhack_progress,
)


def test_zero_assisted_dfhack_progress_preserves_audit_values() -> None:
    metrics = {
        "work_progress": 25,
        "completion_progress": 25,
        "utility_progress": 10,
        "production_progress": 5,
        "complexity_progress": 38,
        "ui_work_progress": 9,
        "ui_designation_progress": 9,
        "ui_completion_progress": 6,
        "ui_excavation_progress": 6,
        "ui_target_dig_designations_delta": 9,
        "ui_target_floor_removed_delta": 6,
        "target_floor_tiles_delta": 25,
        "target_wall_tiles_delta": 25,
        "run_elapsed_ticks": 500,
    }

    _zero_assisted_dfhack_progress(metrics)

    assert metrics["work_progress"] == 0
    assert metrics["completion_progress"] == 0
    assert metrics["utility_progress"] == 0
    assert metrics["production_progress"] == 0
    assert metrics["complexity_progress"] == 0
    assert metrics["ui_work_progress"] == 0
    assert metrics["ui_designation_progress"] == 0
    assert metrics["ui_completion_progress"] == 0
    assert metrics["ui_excavation_progress"] == 0
    assert metrics["ui_target_dig_designations_delta"] == 0
    assert metrics["ui_target_floor_removed_delta"] == 0
    assert metrics["target_floor_tiles_delta"] == 0
    assert metrics["target_wall_tiles_delta"] == 0
    assert metrics["run_elapsed_ticks"] == 500
    assert metrics["dfhack_assisted_progress"] is True
    assert metrics["gameplay_progress_eligible"] is False
    assert metrics["score_provenance"] == "gameplay_only_assisted_progress_zeroed"
    assert metrics["assisted_dfhack_progress"] == {
        "target_floor_tiles_delta": 25,
        "target_wall_tiles_delta": 25,
        "completion_progress": 25,
        "work_progress": 25,
        "utility_progress": 10,
        "production_progress": 5,
        "complexity_progress": 38,
        "ui_target_dig_designations_delta": 9,
        "ui_target_floor_removed_delta": 6,
        "ui_designation_progress": 9,
        "ui_completion_progress": 6,
        "ui_excavation_progress": 6,
        "ui_work_progress": 9,
    }


def test_ui_work_rect_prefers_live_cursor_plane() -> None:
    state = {
        "work": {
            "cursor_x": 107,
            "cursor_y": 108,
            "cursor_z": 177,
            "window_x": 94,
            "window_y": 95,
            "window_z": 177,
        }
    }

    assert _ui_work_rect_from_state(state) == (100, 101, 177, 114, 115, 177)


def test_ui_work_rect_falls_back_to_window_when_cursor_invalid() -> None:
    state = {
        "work": {
            "cursor_x": -30000,
            "cursor_y": -30000,
            "cursor_z": -30000,
            "window_x": 94,
            "window_y": 95,
            "window_z": 177,
        }
    }

    assert _ui_work_rect_from_state(state) == (94, 95, 177, 108, 109, 177)


def test_ui_target_setup_retries_recommended_keys_after_failed_attempt() -> None:
    target = {
        "ok": True,
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN"],
    }

    fresh = _ui_target_setup_for_observation(
        target,
        generation=1,
        attempts=0,
        no_progress_streak=0,
        target_progress_seen=False,
    )
    attempted = _ui_target_setup_for_observation(
        target,
        generation=1,
        attempts=1,
        no_progress_streak=1,
        target_progress_seen=False,
    )

    assert fresh["recommended_keys"] == ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN"]
    assert fresh["show_recommended_keys"] is True
    assert fresh["recommended_keys_retry"] is False
    assert attempted["recommended_keys"] == ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN"]
    assert attempted["show_recommended_keys"] is True
    assert attempted["recommended_keys_retry"] is True
    assert attempted["recommended_keys_suppressed"] is False


def test_ui_target_setup_hides_recommended_keys_after_progress_or_retry_cap() -> None:
    target = {
        "ok": True,
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN"],
    }

    progressed = _ui_target_setup_for_observation(
        target,
        generation=1,
        attempts=1,
        no_progress_streak=0,
        target_progress_seen=True,
    )
    exhausted = _ui_target_setup_for_observation(
        target,
        generation=1,
        attempts=2,
        no_progress_streak=2,
        target_progress_seen=False,
    )

    assert progressed["recommended_keys"] == []
    assert progressed["show_recommended_keys"] is False
    assert progressed["recommended_keys_suppressed"] is True
    assert exhausted["recommended_keys"] == []
    assert exhausted["show_recommended_keys"] is False
    assert exhausted["recommended_keys_suppressed"] is True
