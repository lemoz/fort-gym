from __future__ import annotations

from fort_gym.bench.run.runner import (
    _available_building_materials,
    _carry_forward_carpenter_workshop_proof,
    _carpenter_workshops,
    _desired_keystroke_target_mode,
    _gameplay_proof,
    _is_exit_only_recovery_action,
    _is_keystroke_model,
    _preserve_state_after_degraded_read,
    _preserve_work_after_degraded_read,
    _screen_shows_building_type_menu,
    _screen_shows_ready_workshop_placement,
    _screen_shows_workshop_material_selection,
    _same_target_rect,
    _same_target_route,
    _snapshot_tile_changes,
    _ui_target_setup_for_observation,
    _ui_target_step_succeeded,
    _ui_work_rect_from_state,
    _workshop_current_screen_select_target,
    _workshop_placement_confirm_target,
    _zero_assisted_dfhack_progress,
)


def test_openrouter_glm_alias_uses_keystroke_mode() -> None:
    assert _is_keystroke_model("openrouter-glm-5.2") is True
    assert _is_keystroke_model("openrouter-keystroke-perception-review") is True
    assert _is_keystroke_model("anthropic-research") is True
    assert _is_keystroke_model("fake") is False


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


def test_snapshot_tile_changes_compares_real_map_tiles() -> None:
    before = {
        "ok": True,
        "rect": [10, 20, 0, 11, 20, 0],
        "dig_designations": 0,
        "floor_tiles": 0,
        "wall_tiles": 2,
        "hidden_tiles": 0,
        "building_tiles": 0,
        "tiles": [
            {"x": 10, "y": 20, "z": 0, "category": "wall", "char": "#", "dig": "No"},
            {"x": 11, "y": 20, "z": 0, "category": "wall", "char": "#", "dig": "No"},
        ],
    }
    after = {
        "ok": True,
        "rect": [10, 20, 0, 11, 20, 0],
        "dig_designations": 1,
        "floor_tiles": 1,
        "wall_tiles": 1,
        "hidden_tiles": 0,
        "building_tiles": 0,
        "tiles": [
            {"x": 10, "y": 20, "z": 0, "category": "dig", "char": "x", "dig": "Default"},
            {"x": 11, "y": 20, "z": 0, "category": "floor", "char": ".", "dig": "No"},
        ],
    }

    proof = _snapshot_tile_changes(before, after)

    assert proof["ok"] is True
    assert proof["changed_tile_count"] == 2
    assert proof["snapshot_counts"] == {
        "dig_designations_delta": 1,
        "floor_tiles_delta": 1,
        "wall_tiles_delta": -1,
        "hidden_tiles_delta": 0,
        "building_tiles_delta": 0,
    }
    assert proof["changed_tiles"][0]["before"]["category"] == "wall"
    assert proof["changed_tiles"][0]["after"]["category"] == "dig"


def test_gameplay_proof_marks_keystroke_progress_as_evidence_backed() -> None:
    before_snapshot = {
        "ok": True,
        "rect": [10, 20, 0, 10, 20, 0],
        "dig_designations": 0,
        "floor_tiles": 0,
        "wall_tiles": 1,
        "hidden_tiles": 0,
        "building_tiles": 0,
        "tiles": [
            {"x": 10, "y": 20, "z": 0, "category": "wall", "char": "#", "dig": "No"},
        ],
    }
    after_snapshot = {
        "ok": True,
        "rect": [10, 20, 0, 10, 20, 0],
        "dig_designations": 1,
        "floor_tiles": 0,
        "wall_tiles": 1,
        "hidden_tiles": 0,
        "building_tiles": 0,
        "tiles": [
            {"x": 10, "y": 20, "z": 0, "category": "dig", "char": "x", "dig": "Default"},
        ],
    }

    proof = _gameplay_proof(
        action={
            "type": "KEYSTROKE",
            "params": {"keys": ["D_DESIGNATE", "DESIGNATE_DIG"]},
            "advance_ticks": 200,
        },
        metrics_snapshot={
            "gameplay_progress_eligible": True,
            "score_provenance": "keystroke_ui_work_rect",
            "work_progress": 1,
            "designation_progress": 1,
            "ui_work_progress": 1,
        },
        before_map_snapshot=before_snapshot,
        after_map_snapshot=after_snapshot,
        state_before={"stocks": {"wood": 0, "stone": 0}, "work": {"target_dig_designations": 0}},
        advance_state={"stocks": {"wood": 0, "stone": 0}, "work": {"target_dig_designations": 1}},
        tick_info={"ticks_advanced": 200},
        score_value=24.1,
    )

    assert proof["ok"] is True
    assert proof["gameplay_progress_eligible"] is True
    assert proof["score_provenance"] == "keystroke_ui_work_rect"
    assert proof["changed_tile_count"] == 1
    assert proof["state_deltas"] == {"target_dig_designations": 1}
    assert proof["progress"]["work"] == 1
    assert proof["progress"]["ui_work"] == 0
    assert proof["progress"]["cumulative_ui_work"] == 1


def test_gameplay_proof_requires_current_step_progress() -> None:
    snapshot = {
        "ok": True,
        "rect": [10, 20, 0, 10, 20, 0],
        "dig_designations": 0,
        "floor_tiles": 1,
        "wall_tiles": 0,
        "hidden_tiles": 0,
        "building_tiles": 0,
        "tiles": [
            {"x": 10, "y": 20, "z": 0, "category": "floor", "char": ".", "dig": "No"},
        ],
    }

    proof = _gameplay_proof(
        action={
            "type": "KEYSTROKE",
            "params": {"keys": ["LEAVESCREEN"]},
            "advance_ticks": 0,
        },
        metrics_snapshot={
            "gameplay_progress_eligible": True,
            "score_provenance": "keystroke_ui_work_rect",
            "work_progress": 7,
            "ui_work_progress": 7,
            "ui_excavation_progress": 7,
            "ui_step_work_progress": 0,
            "ui_step_excavation_progress": 0,
            "ui_step_material_progress": 0,
        },
        before_map_snapshot=snapshot,
        after_map_snapshot=snapshot,
        state_before={"stocks": {"wood": 3, "stone": 0}, "work": {"carpenter_workshops": 1}},
        advance_state={"stocks": {"wood": 3, "stone": 0}, "work": {"carpenter_workshops": 1}},
        tick_info={"ticks_advanced": 0},
        score_value=74.3,
    )

    assert proof["ok"] is False
    assert proof["gameplay_progress_eligible"] is False
    assert proof["changed_tile_count"] == 0
    assert proof["state_deltas"] == {}
    assert proof["progress"]["ui_work"] == 0
    assert proof["progress"]["cumulative_ui_work"] == 7


def test_preserve_state_after_degraded_dfhack_read_keeps_last_good_state() -> None:
    degraded = {
        "time": 0,
        "population": 0,
        "stocks": {"food": 0, "drink": 0, "wood": 0, "stone": 0, "wealth": 0},
        "work": {"ok": False, "error": "timeout: work_metrics.lua"},
    }
    last_good = {
        "time": 250,
        "population": 7,
        "stocks": {"food": 45, "drink": 60, "wood": 8, "stone": 0, "wealth": 30},
        "work": {
            "ok": True,
            "carpenter_workshops": 1,
            "manager_orders_count": 0,
            "manager_orders_amount_left": 0,
        },
        "workshops": {"CarpenterWorkshop": 1},
    }

    preserved, metadata = _preserve_state_after_degraded_read(degraded, last_good)

    assert metadata is not None
    assert metadata["reason"] == "dfhack_state_read_degraded"
    assert "population" in metadata["preserved_fields"]
    assert "work" in metadata["preserved_fields"]
    assert preserved["population"] == 7
    assert preserved["stocks"]["wood"] == 8
    assert preserved["work"]["carpenter_workshops"] == 1
    assert preserved["state_read_preservation"] == metadata


def test_preserve_work_after_degraded_read_uses_previous_ui_work() -> None:
    degraded = {"ok": False, "error": "timeout: map/work metrics"}
    last_good = {
        "ok": True,
        "target_rect": [1, 2, 0, 3, 4, 0],
        "target_dig_designations": 2,
        "target_floor_tiles": 5,
    }

    preserved, metadata = _preserve_work_after_degraded_read(degraded, last_good)

    assert metadata is not None
    assert metadata["reason"] == "dfhack_work_read_degraded"
    assert preserved["ok"] is True
    assert preserved["target_floor_tiles"] == 5
    assert preserved["state_read_preservation"] == metadata


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


def test_desired_keystroke_target_mode_inspects_unproven_workshop() -> None:
    state = {
        "stocks": {"wood": 3, "stone": 0},
        "work": {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 0,
            "carpenter_workshop_task_jobs": 0,
            "carpenter_workshop_construction_jobs": 0,
            "active_construct_building_jobs": 0,
        },
    }

    assert _carpenter_workshops(state) == 1
    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_run_material_progress=1,
            ui_successful_targets=2,
        )
        == "existing_workshop"
    )


def test_desired_keystroke_target_mode_stays_on_existing_workshop_during_construction() -> None:
    state = {
        "stocks": {"wood": 3, "stone": 0},
        "work": {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 0,
            "carpenter_workshop_task_jobs": 0,
            "carpenter_workshop_construction_jobs": 1,
            "active_construct_building_jobs": 0,
        },
    }

    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=8,
            ui_run_material_progress=3,
            ui_successful_targets=3,
        )
        == "existing_workshop"
    )


def test_desired_keystroke_target_mode_returns_to_starter_after_usable_workshop() -> None:
    state = {
        "stocks": {"wood": 3, "stone": 0},
        "work": {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 1,
        },
    }

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


def test_carry_forward_workshop_task_proof_after_task_disappears() -> None:
    seen = 0
    task_state = {
        "work": {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 0,
            "carpenter_workshop_task_jobs": 1,
            "carpenter_workshops_unproven": 1,
        }
    }

    seen = _carry_forward_carpenter_workshop_proof(task_state, seen)

    assert seen == 1
    assert task_state["work"]["carpenter_workshops_usable"] == 1
    assert task_state["work"]["carpenter_workshops_unproven"] == 0

    later_state = {
        "stocks": {"wood": 3, "stone": 0},
        "work": {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 0,
            "carpenter_workshop_task_jobs": 0,
            "carpenter_workshop_construction_jobs": 0,
            "active_construct_building_jobs": 0,
            "carpenter_workshops_unproven": 1,
        },
    }

    seen = _carry_forward_carpenter_workshop_proof(later_state, seen)

    assert seen == 1
    assert later_state["work"]["carpenter_workshops_usable"] == 1
    assert later_state["work"]["carpenter_workshops_unproven"] == 0
    assert later_state["work"]["carpenter_workshops_usable_carried_forward"] is True
    assert (
        _desired_keystroke_target_mode(
            later_state,
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


def test_same_target_rect_matches_normalized_target_or_selection_rect() -> None:
    target = {"target_rect": [10, 20, 0, 12, 22, 0]}
    same_reversed = {"selection_rect": [12, 22, 0, 10, 20, 0]}
    different = {"target_rect": [10, 21, 0, 12, 23, 0]}

    assert _same_target_rect(target, same_reversed) is True
    assert _same_target_rect(target, different) is False
    assert _same_target_rect(target, {"target_rect": ["bad"]}) is False


def test_same_target_route_matches_repeated_recommended_keys() -> None:
    first = {
        "target_rect": [92, 79, 177, 106, 93, 177],
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_CHOP", "CURSOR_LEFT"],
    }
    second_same_keys = {
        "target_rect": [81, 80, 177, 95, 94, 177],
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_CHOP", "CURSOR_LEFT"],
    }
    second_different_keys = {
        "target_rect": [81, 80, 177, 95, 94, 177],
        "recommended_keys": ["D_DESIGNATE", "DESIGNATE_CHOP", "CURSOR_RIGHT"],
    }

    assert _same_target_route(first, second_same_keys) is True
    assert _same_target_route(first, second_different_keys) is False


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


def test_building_type_menu_screen_is_detected() -> None:
    assert _screen_shows_building_type_menu(
        "Armor Stand              (a)\n"
        "Bed                      (b)\n"
        "Seat                     (c)\n"
        "+-*/: Select"
    )
    assert not _screen_shows_building_type_menu(
        "Carpenter's Workshop\nNeeds building material non-economic item"
    )


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


def test_exit_only_recovery_action_is_not_a_target_attempt() -> None:
    assert _is_exit_only_recovery_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN"]},
            "advance_ticks": 0,
        }
    )
    assert not _is_exit_only_recovery_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["LEAVESCREEN", "D_DESIGNATE"]},
            "advance_ticks": 0,
        }
    )
    assert not _is_exit_only_recovery_action(
        {
            "type": "KEYSTROKE",
            "params": {"keys": ["LEAVESCREEN"]},
            "advance_ticks": 100,
        }
    )


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
