from __future__ import annotations

from fort_gym.bench.run.runner import (
    _available_building_materials,
    _carpenter_workshops,
    _desired_keystroke_target_mode,
    _screen_shows_ready_workshop_placement,
    _screen_shows_workshop_material_selection,
    _ui_target_setup_for_observation,
    _ui_target_step_succeeded,
    _ui_work_rect_from_state,
    _workshop_current_screen_select_target,
    _workshop_placement_confirm_target,
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


def test_desired_keystroke_target_mode_switches_to_material_after_starter_digging() -> None:
    state = {"stocks": {"wood": 0, "stone": 0}}

    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_successful_targets=1,
        )
        == "material"
    )
    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=0,
            ui_successful_targets=2,
        )
        == "material"
    )


def test_desired_keystroke_target_mode_switches_to_workshop_when_material_exists() -> None:
    state = {"stocks": {"wood": 0, "stone": 1}, "work": {"carpenter_workshops": 0}}

    assert _available_building_materials(state) == 1
    assert _carpenter_workshops(state) == 0
    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_run_material_progress=1,
            ui_successful_targets=2,
        )
        == "workshop"
    )


def test_desired_keystroke_target_mode_does_not_trust_stock_only_material() -> None:
    state = {"stocks": {"wood": 3, "stone": 0}, "work": {"carpenter_workshops": 0}}

    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_run_material_progress=0,
            ui_successful_targets=2,
        )
        == "material"
    )


def test_desired_keystroke_target_mode_returns_to_starter_after_workshop_exists() -> None:
    state = {"stocks": {"wood": 3, "stone": 0}, "work": {"carpenter_workshops": 1}}

    assert _carpenter_workshops(state) == 1
    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_run_material_progress=1,
            ui_successful_targets=2,
        )
        == "starter"
    )


def test_desired_keystroke_target_mode_trusts_visible_material_blocker() -> None:
    state = {"stocks": {"wood": 3, "stone": 0}, "work": {"carpenter_workshops": 1}}

    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_successful_targets=2,
            build_material_blocked=True,
        )
        == "material"
    )


def test_ready_workshop_placement_screen_gets_select_target() -> None:
    assert _screen_shows_ready_workshop_placement(
        "Carpenter's Workshop\nPlacement\nEnter: Place\nESC: Cancel"
    )
    assert not _screen_shows_ready_workshop_placement(
        "Carpenter's Workshop\nPlacement\nNeeds building material\nESC: Cancel"
    )
    assert not _screen_shows_ready_workshop_placement(
        "Carpenter's Workshop\nPlacement\nBlocked\nESC: Cancel"
    )
    assert not _screen_shows_ready_workshop_placement(
        "Carpenter's Workshop\nPlacement\nBuilding present\nEnter: Place"
    )

    target = _workshop_placement_confirm_target(
        {
            "work": {
                "cursor_x": 94,
                "cursor_y": 100,
                "cursor_z": 177,
            },
        }
    )

    assert target["target_mode"] == "workshop"
    assert target["source"] == "visible_workshop_placement"
    assert target["recommended_keys"] == ["SELECT"]
    assert target["selection_rect"] == [94, 100, 177, 96, 102, 177]


def test_workshop_material_selection_screen_gets_select_target() -> None:
    assert _screen_shows_workshop_material_selection(
        "Carpenter's Workshop\nItem              Dist Num\n"
        "ginkgo wood logs  1    0/3\nEnter: Select"
    )
    assert not _screen_shows_workshop_material_selection(
        "Carpenter's Workshop\nNeeds building material\nEnter: Select"
    )

    target = _workshop_current_screen_select_target(
        {
            "work": {
                "cursor_x": 92,
                "cursor_y": 100,
                "cursor_z": 177,
            },
        },
        source="visible_workshop_material_selection",
    )

    assert target["target_mode"] == "workshop"
    assert target["source"] == "visible_workshop_material_selection"
    assert target["recommended_keys"] == ["SELECT"]
    assert target["selection_rect"] == [92, 100, 177, 94, 102, 177]


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


def test_material_target_setup_hides_keys_after_bounded_retry_cap() -> None:
    target = {
        "ok": True,
        "target_mode": "material",
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_CHOP"],
    }

    attempted = _ui_target_setup_for_observation(
        target,
        generation=3,
        attempts=1,
        no_progress_streak=1,
        target_progress_seen=False,
    )
    exhausted = _ui_target_setup_for_observation(
        target,
        generation=3,
        attempts=2,
        no_progress_streak=2,
        target_progress_seen=False,
    )

    assert attempted["recommended_keys"] == ["D_DESIGNATE", "DESIGNATE_CHOP"]
    assert attempted["show_recommended_keys"] is True
    assert attempted["recommended_keys_retry"] is True
    assert attempted["recommended_keys_suppressed"] is False
    assert exhausted["recommended_keys"] == []
    assert exhausted["show_recommended_keys"] is False
    assert exhausted["recommended_keys_suppressed"] is True
    assert exhausted["recommended_key_retry_limit"] == 2


def test_material_target_setup_can_prefix_build_menu_recovery_keys() -> None:
    target = {
        "ok": True,
        "target_mode": "material",
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_CHOP"],
    }

    setup = _ui_target_setup_for_observation(
        target,
        generation=3,
        attempts=9,
        no_progress_streak=2,
        target_progress_seen=False,
        recommended_key_prefix=["LEAVESCREEN", "LEAVESCREEN"],
        force_show_recommended=True,
    )

    assert setup["recommended_keys"] == [
        "LEAVESCREEN",
        "LEAVESCREEN",
        "D_DESIGNATE",
        "DESIGNATE_CHOP",
    ]
    assert setup["recommended_key_prefix"] == ["LEAVESCREEN", "LEAVESCREEN"]
    assert setup["show_recommended_keys"] is True
    assert setup["recommended_keys_force_shown"] is True
    assert setup["recommended_keys_exit_only"] is False


def test_material_target_setup_can_show_exit_only_recovery_keys() -> None:
    target = {
        "ok": True,
        "target_mode": "material",
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_CHOP"],
    }

    setup = _ui_target_setup_for_observation(
        target,
        generation=3,
        attempts=9,
        no_progress_streak=2,
        target_progress_seen=False,
        recommended_key_prefix=["LEAVESCREEN", "LEAVESCREEN"],
        force_show_recommended=True,
        recommended_keys_exit_only=True,
    )

    assert setup["recommended_keys"] == ["LEAVESCREEN", "LEAVESCREEN"]
    assert setup["recommended_key_prefix"] == ["LEAVESCREEN", "LEAVESCREEN"]
    assert setup["show_recommended_keys"] is True
    assert setup["recommended_keys_force_shown"] is True
    assert setup["recommended_keys_exit_only"] is True


def test_material_target_requires_material_delta_for_success() -> None:
    assert _ui_target_step_succeeded(
        "material",
        ui_step_work_progress=3,
        ui_step_material_progress=0,
    ) is False
    assert _ui_target_step_succeeded(
        "material",
        ui_step_work_progress=0,
        ui_step_material_progress=1,
    ) is True
    assert _ui_target_step_succeeded(
        "starter",
        ui_step_work_progress=3,
        ui_step_material_progress=0,
    ) is True


def test_workshop_target_setup_keeps_exact_placement_keys_visible() -> None:
    target = {
        "ok": True,
        "target_mode": "workshop",
        "recommended_keys": [
            "LEAVESCREEN",
            "LEAVESCREEN",
            "D_BUILDING",
            "HOTKEY_BUILDING_WORKSHOP",
            "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
            "SELECT",
            "SELECT",
        ],
    }

    setup = _ui_target_setup_for_observation(
        target,
        generation=4,
        attempts=3,
        no_progress_streak=1,
        target_progress_seen=False,
    )

    assert setup["recommended_keys"] == target["recommended_keys"]
    assert setup["show_recommended_keys"] is True
    assert setup["recommended_keys_retry"] is True
    assert setup["recommended_key_retry_limit"] > 3
