from __future__ import annotations

from pathlib import Path

from fort_gym.bench.run.runner import (
    _action_history_entry,
    _available_building_materials,
    _carry_forward_carpenter_workshop_proof,
    _carpenter_workshops,
    _channel_focus_rect_from_action,
    _owned_channel_focus_rect,
    _desired_keystroke_target_mode,
    _gameplay_proof,
    _governed_dig_rect_from_action,
    _governed_building_claims,
    _governed_completed_owned_buildings,
    _governed_durable_helper_progress,
    _governed_gameplay_proof,
    _governed_owned_building_progress,
    _is_exit_only_recovery_action,
    _is_governed_dfhack_model,
    _is_keystroke_model,
    _keystroke_productive_state_deltas,
    _keystroke_step_score_progress,
    _material_exhausted_fallback_target_mode,
    _preserve_state_after_degraded_read,
    _preserve_work_after_degraded_read,
    _screen_shows_blocked_workshop_placement,
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
    _workshop_blocked_fallback_active,
    _workshop_placement_confirm_target,
    _zero_assisted_dfhack_progress,
)


def test_openrouter_glm_alias_uses_keystroke_mode() -> None:
    assert _is_keystroke_model("openrouter-glm-5.2") is True
    assert _is_keystroke_model("openrouter-keystroke-perception-review") is True
    assert _is_keystroke_model("anthropic-research") is True
    assert _is_keystroke_model("fake") is False


def test_governed_dfhack_model_is_not_keystroke_mode() -> None:
    assert _is_governed_dfhack_model("dfhack-governed-scripted") is True
    assert _is_keystroke_model("dfhack-governed-scripted") is False


def test_channel_focus_comes_only_from_model_authored_channel_rect() -> None:
    action = {
        "type": "DIG",
        "params": {"kind": "channel", "area": [91, 88, 177], "size": [2, 1, 1]},
    }

    assert _channel_focus_rect_from_action(action) == (91, 88, 177, 92, 88, 177)
    assert _channel_focus_rect_from_action(
        {**action, "params": {**action["params"], "kind": "dig"}}
    ) is None


def test_channel_focus_requires_a_newly_model_owned_tile() -> None:
    action = {
        "type": "DIG",
        "params": {
            "kind": "channel",
            "area": [91, 88, 177],
            "size": [2, 1, 1],
        },
    }

    assert _owned_channel_focus_rect(action, {"governed_designated_tiles": []}) is None
    assert _owned_channel_focus_rect(
        action,
        {"governed_designated_tiles": [[92, 88, 177], [91, 88, 177]]},
    ) == (91, 88, 177, 91, 88, 177)
    assert _channel_focus_rect_from_action(
        {**action, "params": {**action["params"], "size": [2, 1, 2]}}
    ) is None


def test_governed_dig_rect_tracks_only_excavation_footprints() -> None:
    action = {
        "type": "DIG",
        "params": {"kind": "dig", "area": [91, 88, 177], "size": [2, 3, 1]},
    }

    assert _governed_dig_rect_from_action(action) == (91, 88, 177, 92, 90, 177)
    assert _governed_dig_rect_from_action(
        {**action, "params": {**action["params"], "kind": "chop"}}
    ) is None
    assert _governed_dig_rect_from_action({"type": "WAIT", "params": {}}) is None


def test_governed_runner_uses_plan_agnostic_work_and_records_copy_screen_text() -> None:
    runner_text = (
        Path(__file__).resolve().parents[1]
        / "fort_gym"
        / "bench"
        / "run"
        / "runner.py"
    ).read_text(encoding="utf-8")

    assert "dfhack_client.set_work_metrics_global_only(True)" in runner_text
    assert "def prepare_governed_target" not in runner_text
    assert "governed_workshop_target" not in runner_text
    assert 'crew = read_job_metrics()' in runner_text
    assert "if is_keystroke_mode or is_governed_dfhack_mode" in runner_text
    assert "record_line[\"screen_text\"] = screen_text" in runner_text


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
    assert proof["state_deltas"] == {}
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


def test_material_exhaustion_falls_forward_to_workshop_with_stock() -> None:
    state = {"stocks": {"wood": 3, "stone": 0}, "work": {"carpenter_workshops": 0}}

    assert (
        _material_exhausted_fallback_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_successful_targets=1,
        )
        == "workshop"
    )


def test_material_exhaustion_returns_to_starter_without_usable_build_signal() -> None:
    assert (
        _material_exhausted_fallback_target_mode(
            {"stocks": {"wood": 3, "stone": 0}, "work": {"carpenter_workshops": 0}},
            ui_run_excavation_progress=6,
            ui_successful_targets=1,
            build_material_blocked=True,
        )
        == "starter"
    )

    assert (
        _material_exhausted_fallback_target_mode(
            {"stocks": {"wood": 0, "stone": 0}, "work": {"carpenter_workshops": 0}},
            ui_run_excavation_progress=6,
            ui_successful_targets=1,
        )
        == "starter"
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


def test_desired_keystroke_target_mode_keeps_usable_workshop_with_wood_productive() -> None:
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
        == "existing_workshop"
    )


def test_desired_keystroke_target_mode_usable_workshop_without_wood_gets_material() -> None:
    state = {
        "stocks": {"wood": 0, "stone": 0},
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
        == "material"
    )


def test_desired_keystroke_target_mode_stays_on_existing_workshop_for_queued_task() -> None:
    state = {
        "stocks": {"wood": 30, "stone": 0},
        "work": {
            "carpenter_workshops_planned": 1,
            "carpenter_workshops_usable": 1,
            "carpenter_workshop_task_jobs": 1,
            "active_carpenter_jobs": 0,
        },
    }

    assert (
        _desired_keystroke_target_mode(
            state,
            ui_run_excavation_progress=6,
            ui_run_material_progress=27,
            ui_successful_targets=4,
        )
        == "existing_workshop"
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
        == "existing_workshop"
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


def test_blocked_workshop_placement_screen_is_distinct_from_ready_select() -> None:
    blocked = "Carpenter's Workshop\nPlacement\nBlocked\nESC: Cancel"
    occupied = "Carpenter's Workshop\nPlacement\nBuilding present\nEnter: Place"
    needs_material = "Carpenter's Workshop\nPlacement\nNeeds building material\nESC: Cancel"
    ready = "Carpenter's Workshop\nPlacement\nEnter: Place\nESC: Cancel"

    assert _screen_shows_blocked_workshop_placement(blocked)
    assert _screen_shows_blocked_workshop_placement(occupied)
    assert not _screen_shows_blocked_workshop_placement(needs_material)
    assert not _screen_shows_blocked_workshop_placement(ready)


def test_workshop_blocked_fallback_requires_new_floor_progress() -> None:
    assert _workshop_blocked_fallback_active(3, 10, 10)
    assert _workshop_blocked_fallback_active(4, 10, 9)
    assert not _workshop_blocked_fallback_active(2, 10, 10)
    assert not _workshop_blocked_fallback_active(3, None, 10)
    assert not _workshop_blocked_fallback_active(3, 10, 11)


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


def test_keystroke_step_score_progress_requires_current_progress() -> None:
    assert not _keystroke_step_score_progress(
        {
            "ui_work_progress": 7,
            "ui_excavation_progress": 7,
            "ui_step_work_progress": 0,
            "ui_step_excavation_progress": 0,
            "ui_step_material_progress": 0,
            "production_progress": 0,
            "utility_action_progress": 0,
        },
        state_before={"stocks": {"wood": 3}, "work": {"carpenter_workshops_planned": 0}},
        advance_state={"stocks": {"wood": 3}, "work": {"carpenter_workshops_planned": 0}},
    )
    assert not _keystroke_step_score_progress(
        {
            "ui_step_work_progress": 0,
            "ui_step_excavation_progress": 0,
            "ui_step_material_progress": 0,
            "production_progress": 5,
            "utility_progress": 5,
            "utility_action_progress": 0,
        },
        state_before={
            "stocks": {"wood": 30, "wealth": 96},
            "work": {
                "carpenter_workshop_task_jobs": 1,
                "carpenter_workshops_usable": 1,
            },
        },
        advance_state={
            "stocks": {"wood": 30, "wealth": 96},
            "work": {
                "carpenter_workshop_task_jobs": 1,
                "carpenter_workshops_usable": 1,
            },
        },
    )

    assert _keystroke_step_score_progress(
        {"ui_step_work_progress": 0, "ui_step_material_progress": 1},
        state_before={"stocks": {"wood": 3}, "work": {}},
        advance_state={"stocks": {"wood": 4}, "work": {}},
    )


def test_keystroke_step_score_progress_counts_real_workshop_state() -> None:
    assert _keystroke_step_score_progress(
        {
            "ui_step_work_progress": 0,
            "ui_step_excavation_progress": 0,
            "ui_step_material_progress": 0,
        },
        state_before={
            "stocks": {"wood": 3, "wealth": 9},
            "work": {"carpenter_workshop_task_jobs": 0},
        },
        advance_state={
            "stocks": {"wood": 3, "wealth": 9},
            "work": {"carpenter_workshop_task_jobs": 1},
        },
    )


def test_keystroke_state_progress_ignores_negative_construction_job_delta() -> None:
    state_before = {
        "stocks": {"wood": 29, "wealth": 9},
        "work": {
            "carpenter_workshop_construction_jobs": 1,
            "carpenter_workshops_usable": 0,
        },
    }
    advance_state = {
        "stocks": {"wood": 29, "wealth": 9},
        "work": {
            "carpenter_workshop_construction_jobs": 0,
            "carpenter_workshops_usable": 0,
        },
    }

    assert _keystroke_productive_state_deltas(state_before, advance_state) == {}
    assert not _keystroke_step_score_progress(
        {
            "ui_step_work_progress": 0,
            "ui_step_excavation_progress": 0,
            "ui_step_material_progress": 0,
        },
        state_before=state_before,
        advance_state=advance_state,
    )


def test_keystroke_state_progress_counts_completed_workshop_task_with_consumed_wood() -> None:
    state_before = {
        "stocks": {"wood": 8, "wealth": 9},
        "work": {
            "carpenter_workshop_task_jobs": 1,
            "carpenter_workshops_usable": 1,
        },
    }
    advance_state = {
        "stocks": {"wood": 7, "wealth": 9},
        "work": {
            "carpenter_workshop_task_jobs": 0,
            "carpenter_workshops_usable": 1,
        },
    }

    assert _keystroke_productive_state_deltas(state_before, advance_state) == {
        "carpenter_workshop_completed_tasks": 1,
        "wood_consumed_by_workshop": 1,
    }
    assert _keystroke_step_score_progress(
        {
            "ui_step_work_progress": 0,
            "ui_step_excavation_progress": 0,
            "ui_step_material_progress": 0,
        },
        state_before=state_before,
        advance_state=advance_state,
    )


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


def _governed_proof_kwargs(**overrides):
    kwargs = {
        "action": {"type": "DIG", "params": {"area": [50, 35, 0], "size": [5, 5, 1]}, "advance_ticks": 1000},
        "execute_result": {"accepted": True, "result": {}},
        "metrics_snapshot": {"score_provenance": "dfhack_governed_observed_state"},
        "before_map_snapshot": None,
        "after_map_snapshot": None,
        "state_before": {},
        "advance_state": {},
        "tick_info": {"ticks_advanced": 1000},
        "score_value": 10.0,
    }
    kwargs.update(overrides)
    return kwargs


def test_governed_action_history_preserves_partial_and_tile_postconditions() -> None:
    entry = _action_history_entry(
        step=24,
        action={
            "type": "BUILD",
            "params": {"kind": "Wall", "x": 88, "y": 101, "z": 161, "x2": 91},
            "intent": "build a north wall",
            "advance_ticks": 1000,
        },
        requested_ticks=1000,
        tick_info={"ticks_advanced": 1005},
        execute_result={
            "accepted": False,
            "why": "partial_placement",
            "result": {
                "partial": True,
                "placed_count": 2,
                "failed_count": 1,
                "placed": [
                    {"x": 88, "y": 101, "z": 161},
                    {"x": 89, "y": 101, "z": 161},
                ],
                "failed": [
                    {
                        "x": 91,
                        "y": 101,
                        "z": 161,
                        "error": "tile_not_open_floor",
                        "tile_shape": "BOULDER",
                        "tiletype": "GRASS_DARK_BOULDER",
                    }
                ],
            },
        },
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )

    assert entry["outcome"] == "partial_mutation"
    assert entry["placed_targets"] == ["(88,101,161)", "(89,101,161)"]
    assert entry["failed_targets"] == [
        "(91,101,161):tile_not_open_floor"
        "[tile_shape=BOULDER,tiletype=GRASS_DARK_BOULDER]"
    ]
    assert entry["result_details"] == {"placed_count": 2, "failed_count": 1}


def test_governed_action_history_preserves_complete_rejected_workshop_footprint() -> None:
    entry = _action_history_entry(
        step=83,
        action={
            "type": "BUILD",
            "params": {"kind": "Still", "x": 97, "y": 98, "z": 160},
            "intent": "build a still",
            "advance_ticks": 1500,
        },
        requested_ticks=1500,
        tick_info={"ticks_advanced": 1505},
        execute_result={
            "accepted": False,
            "why": "tile_not_open_floor",
            "result": {
                "ok": False,
                "error": "tile_not_open_floor",
                "failed_count": 3,
                "failed": [
                    {
                        "x": 97,
                        "y": 98,
                        "z": 160,
                        "error": "tile_not_open_floor",
                        "tile_shape": "WALL",
                        "tiletype": "SoilWall",
                    },
                    {
                        "x": 98,
                        "y": 98,
                        "z": 160,
                        "error": "tile_occupied_by_building",
                        "tile_shape": "FLOOR",
                        "tiletype": "SoilFloor1",
                    },
                    {
                        "x": 99,
                        "y": 98,
                        "z": 160,
                        "error": "tile_hidden_unexplored",
                    },
                ],
            },
        },
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )

    assert entry["outcome"] == "rejected"
    assert entry["failed_targets"] == [
        "(97,98,160):tile_not_open_floor[tile_shape=WALL,tiletype=SoilWall]",
        "(98,98,160):tile_occupied_by_building[tile_shape=FLOOR,tiletype=SoilFloor1]",
        "(99,98,160):tile_hidden_unexplored",
    ]
    assert entry["result_details"] == {"failed_count": 3}


def test_governed_action_history_uses_exact_owned_completion_proof() -> None:
    entry = _action_history_entry(
        step=3,
        action={
            "type": "DIG",
            "params": {
                "kind": "channel",
                "area": [95, 100, 161],
                "size": [1, 1, 1],
            },
            "advance_ticks": 1500,
        },
        requested_ticks=1500,
        tick_info={"ticks_advanced": 1506},
        execute_result={
            "accepted": True,
            "gameplay_progress_eligible": True,
            "governed_current_action_effect_observed": True,
            "result": {"ok": True, "newly_designated": 1},
        },
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )

    assert entry["outcome"] == "action_effect_observed"


def test_governed_action_history_does_not_credit_unrelated_owned_completion() -> None:
    entry = _action_history_entry(
        step=45,
        action={
            "type": "UNSUSPEND",
            "params": {"area": [96, 100, 160], "size": [1, 1, 1]},
            "advance_ticks": 1500,
        },
        requested_ticks=1500,
        tick_info={"ticks_advanced": 1506},
        execute_result={
            "accepted": True,
            "gameplay_progress_eligible": True,
            "governed_current_action_effect_observed": False,
            "result": {"ok": True, "suspended_found": 0, "unsuspended": 0},
        },
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )

    assert entry["outcome"] == "advanced_ticks_without_tracked_state_change"


def test_governed_designations_are_pending_feedback_without_completion_proof() -> None:
    cases = (
        ("dig", "newly_designated"),
        ("channel", "newly_designated"),
        ("chop", "trees_designated"),
        ("gather", "shrubs_designated"),
    )

    for kind, result_key in cases:
        action = {
            "type": "DIG",
            "params": {"kind": kind, "area": [92, 98, 161], "size": [1, 1, 1]},
            "advance_ticks": 1500,
        }
        execute_result = {
            "accepted": True,
            "gameplay_progress_eligible": False,
            "result": {"ok": True, result_key: 1},
        }
        entry = _action_history_entry(
            step=14,
            action=action,
            requested_ticks=1500,
            tick_info={"ticks_advanced": 1500},
            execute_result=execute_result,
            state_before={"stocks": {}, "work": {}},
            advance_state={"stocks": {}, "work": {}},
            metrics_snapshot={},
        )
        proof = _governed_gameplay_proof(
            **_governed_proof_kwargs(action=action, execute_result=execute_result)
        )

        assert entry["outcome"] == "action_pending"
        assert proof["gameplay_progress_eligible"] is False


def test_governed_action_history_calls_helper_mutations_action_effects() -> None:
    entry = _action_history_entry(
        step=1,
        action={
            "type": "BUILD",
            "params": {"kind": "Still", "x": 91, "y": 100, "z": 161},
            "intent": "place a still",
            "advance_ticks": 0,
        },
        requested_ticks=0,
        tick_info={"ticks_advanced": 0},
        execute_result={
            "accepted": True,
            "result": {
                "ok": True,
                "before_workshops_of_kind": 0,
                "after_workshops_of_kind": 1,
            },
        },
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )

    assert entry["outcome"] == "action_effect_observed"


def test_governed_action_history_calls_full_placement_gameplay_change() -> None:
    action = {
        "type": "BUILD",
        "params": {"kind": "Wall", "x": 88, "y": 101, "z": 161},
        "intent": "place one wall",
        "advance_ticks": 0,
    }
    execute_result = {
        "accepted": True,
        "result": {
            "ok": True,
            "partial": False,
            "placed_count": 1,
            "failed_count": 0,
            "placed": [{"x": 88, "y": 101, "z": 161}],
        },
    }
    entry = _action_history_entry(
        step=1,
        action=action,
        requested_ticks=0,
        tick_info={"ticks_advanced": 0},
        execute_result=execute_result,
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action=action,
            execute_result=execute_result,
            tick_info={"ticks_advanced": 0},
        )
    )

    assert entry["outcome"] == "action_effect_observed"
    assert entry["placed_targets"] == ["(88,101,161)"]
    assert proof["ok"] is True
    assert proof["helper_evidence"]["placed_count"] == 1


def test_governed_order_ids_without_output_are_not_progress() -> None:
    action = {
        "type": "ORDER",
        "params": {"job": "brew", "quantity": 3},
        "intent": "queue brew jobs",
        "advance_ticks": 1200,
    }
    execute_result = {
        "accepted": True,
        "result": {"ok": True, "created_job_ids": [223, 225, 227]},
    }
    state_before = {
        "stocks": {},
        "work": {"active_jobs": 1},
        "crew": {"jobs": {"active_ids": []}},
        "survival": {"drink_produced_in_run": 25},
    }
    advance_state = {
        "stocks": {},
        # An unrelated job starts during the tick window.
        "work": {"active_jobs": 2},
        "crew": {"jobs": {"active_ids": [999]}},
        "survival": {"drink_produced_in_run": 25},
    }

    entry = _action_history_entry(
        step=80,
        action=action,
        requested_ticks=1200,
        tick_info={"ticks_advanced": 1205},
        execute_result=execute_result,
        state_before=state_before,
        advance_state=advance_state,
        metrics_snapshot={},
    )
    proof = _governed_gameplay_proof(
        action=action,
        execute_result=execute_result,
        metrics_snapshot={},
        before_map_snapshot=None,
        after_map_snapshot=None,
        state_before=state_before,
        advance_state=advance_state,
        tick_info={"ticks_advanced": 1205},
        score_value=0.0,
    )

    assert entry["outcome"] == "concurrent_gameplay_state_changed"
    assert entry["action_effect"] == {
        "status": "no_progress",
        "job": "brew",
        "created_job_ids": [223, 225, 227],
        "remaining_job_ids": [],
        "completed_job_ids": [223, 225, 227],
        "created_job_completion_observed": True,
        "active_job_ids_complete": True,
        "prior_matching_job_ids": [],
        "prior_matching_jobs_complete": True,
        "manager_orders_present": False,
        "attribution_complete": True,
        "output_observed": True,
        "output_source": "survival.drink_produced_in_run",
        "output_before": 25,
        "output_after": 25,
        "output_delta": 0,
    }
    assert proof["ok"] is False
    assert proof["action_effect_observed"] is False
    assert proof["concurrent_world_state_changed"] is True


def test_governed_order_reports_pending_and_completed_lifecycle() -> None:
    action = {
        "type": "ORDER",
        "params": {"job": "brew", "quantity": 3},
        "intent": "queue brew jobs",
        "advance_ticks": 1200,
    }
    execute_result = {
        "accepted": True,
        "result": {"ok": True, "created_job_ids": [301, 302, 303]},
    }
    state_before = {
        "stocks": {},
        "work": {},
        "crew": {"jobs": {"active_ids": []}},
        "survival": {"drink_produced_in_run": 25},
    }
    pending = _action_history_entry(
        step=1,
        action=action,
        requested_ticks=1200,
        tick_info={"ticks_advanced": 1200},
        execute_result=execute_result,
        state_before=state_before,
        advance_state={
            "stocks": {},
            "work": {},
            "crew": {"jobs": {"active_ids": [301, 302]}},
            "survival": {"drink_produced_in_run": 25},
        },
        metrics_snapshot={},
    )
    completed = _action_history_entry(
        step=2,
        action=action,
        requested_ticks=1200,
        tick_info={"ticks_advanced": 1200},
        execute_result=execute_result,
        state_before=state_before,
        advance_state={
            "stocks": {},
            "work": {},
            "crew": {"jobs": {"active_ids": []}},
            "survival": {"drink_produced_in_run": 50},
        },
        metrics_snapshot={},
    )

    assert pending["outcome"] == "action_pending"
    assert pending["action_effect"]["remaining_job_ids"] == [301, 302]
    assert completed["outcome"] == "action_effect_observed"
    assert completed["action_effect"]["output_delta"] == 25


def test_governed_order_does_not_claim_output_while_all_created_jobs_remain_active() -> None:
    action = {
        "type": "ORDER",
        "params": {"job": "brew", "quantity": 3},
        "intent": "queue brew jobs",
        "advance_ticks": 1200,
    }
    execute_result = {
        "accepted": True,
        "result": {"ok": True, "created_job_ids": [311, 312, 313]},
    }
    state_before = {
        "stocks": {},
        "work": {},
        "crew": {"jobs": {"active_ids": [], "order_jobs": []}},
        "survival": {"drink_produced_in_run": 25},
    }
    advance_state = {
        "stocks": {},
        "work": {},
        "crew": {
            "jobs": {
                "active_ids": [311, 312, 313],
                "order_jobs": [
                    {"id": 311, "item": "brew"},
                    {"id": 312, "item": "brew"},
                    {"id": 313, "item": "brew"},
                ],
            }
        },
        "survival": {"drink_produced_in_run": 50},
    }

    entry = _action_history_entry(
        step=3,
        action=action,
        requested_ticks=1200,
        tick_info={"ticks_advanced": 1200},
        execute_result=execute_result,
        state_before=state_before,
        advance_state=advance_state,
        metrics_snapshot={},
    )
    proof = _governed_gameplay_proof(
        action=action,
        execute_result=execute_result,
        metrics_snapshot={},
        before_map_snapshot=None,
        after_map_snapshot=None,
        state_before=state_before,
        advance_state=advance_state,
        tick_info={"ticks_advanced": 1200},
        score_value=0.0,
    )

    assert entry["outcome"] == "action_output_unattributed"
    assert entry["action_effect"]["status"] == "unattributed_output"
    assert entry["action_effect"]["completed_job_ids"] == []
    assert entry["action_effect"]["created_job_completion_observed"] is False
    assert entry["action_effect"]["attribution_complete"] is False
    assert proof["ok"] is False


def test_governed_order_does_not_claim_output_from_older_matching_job() -> None:
    action = {
        "type": "ORDER",
        "params": {"job": "brew", "quantity": 1},
        "intent": "queue one brew job",
        "advance_ticks": 1200,
    }
    execute_result = {
        "accepted": True,
        "result": {"ok": True, "created_job_ids": [301]},
    }
    state_before = {
        "stocks": {},
        "work": {},
        "crew": {
            "jobs": {
                "active_ids": [200],
                "order_jobs": [{"id": 200, "item": "brew"}],
            }
        },
        "survival": {"drink_produced_in_run": 25},
    }
    advance_state = {
        "stocks": {},
        "work": {},
        "crew": {"jobs": {"active_ids": [], "order_jobs": []}},
        "survival": {"drink_produced_in_run": 50},
    }

    entry = _action_history_entry(
        step=3,
        action=action,
        requested_ticks=1200,
        tick_info={"ticks_advanced": 1200},
        execute_result=execute_result,
        state_before=state_before,
        advance_state=advance_state,
        metrics_snapshot={},
    )
    proof = _governed_gameplay_proof(
        action=action,
        execute_result=execute_result,
        metrics_snapshot={},
        before_map_snapshot=None,
        after_map_snapshot=None,
        state_before=state_before,
        advance_state=advance_state,
        tick_info={"ticks_advanced": 1200},
        score_value=0.0,
    )

    assert entry["outcome"] == "action_output_unattributed"
    assert entry["action_effect"]["status"] == "unattributed_output"
    assert entry["action_effect"]["prior_matching_job_ids"] == [200]
    assert entry["action_effect"]["attribution_complete"] is False
    assert proof["ok"] is False


def test_governed_order_fails_closed_to_unknown_when_job_ids_are_truncated() -> None:
    entry = _action_history_entry(
        step=4,
        action={
            "type": "ORDER",
            "params": {"job": "bed", "quantity": 1},
            "intent": "queue one bed",
            "advance_ticks": 1200,
        },
        requested_ticks=1200,
        tick_info={"ticks_advanced": 1200},
        execute_result={
            "accepted": True,
            "result": {"ok": True, "created_job_ids": [401]},
        },
        state_before={
            "stocks": {},
            "work": {},
            "crew": {"jobs": {"active_ids": [], "order_jobs": []}},
        },
        advance_state={
            "stocks": {},
            "work": {},
            "crew": {
                "goods": {"bed": 0},
                "jobs": {
                    "active_ids": [],
                    "active_ids_truncated": True,
                    "order_jobs": [],
                    "order_jobs_truncated": True,
                },
            },
        },
        metrics_snapshot={},
    )

    assert entry["outcome"] == "action_effect_unobserved"
    assert entry["action_effect"]["status"] == "unobserved"
    assert entry["action_effect"]["active_job_ids_complete"] is False


def test_governed_action_history_separates_interface_effects_from_gameplay() -> None:
    entry = _action_history_entry(
        step=1,
        action={
            "type": "INTERACT",
            "params": {"operation": "finish_topic_meeting"},
            "intent": "close the current topic meeting",
            "advance_ticks": 0,
        },
        requested_ticks=0,
        tick_info={"ticks_advanced": 0},
        execute_result={
            "accepted": True,
            "result": {"semantic_effect_observed": True, "screen_changed": True},
        },
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )

    assert entry["outcome"] == "interface_state_changed"


def test_governed_action_history_does_not_call_zero_tick_noop_keystrokes() -> None:
    entry = _action_history_entry(
        step=1,
        action={"type": "WAIT", "params": {}, "intent": "observe", "advance_ticks": 0},
        requested_ticks=0,
        tick_info={"ticks_advanced": 0},
        execute_result={"accepted": True, "result": {}},
        state_before={"stocks": {}, "work": {}},
        advance_state={"stocks": {}, "work": {}},
        metrics_snapshot={},
    )

    assert entry["outcome"] == "action_accepted_without_tracked_state_change"


def test_action_history_preserves_review_contract_for_all_outcomes() -> None:
    action = {
        "type": "BUILD",
        "params": {"kind": "Wall", "x": 88, "y": 101, "z": 161},
        "objective": "Close the workshop room wall.",
        "plan_step": "Build the north wall.",
        "plan_review": "The target tile remains open floor.",
        "last_action_review": {
            "worked": False,
            "should_retry_same_path": False,
        },
    }
    outcomes = (
        ({"accepted": True, "result": {}}, "action_accepted_without_tracked_state_change"),
        ({"accepted": False, "reason": "blocked", "result": {}}, "rejected"),
        (
            {
                "accepted": False,
                "reason": "invalid target",
                "validation_rejected": True,
            },
            "validation_rejected",
        ),
    )

    for execute_result, expected_outcome in outcomes:
        entry = _action_history_entry(
            step=4,
            action=action,
            requested_ticks=0,
            tick_info={"ticks_advanced": 0},
            execute_result=execute_result,
            state_before={"stocks": {}, "work": {}},
            advance_state={"stocks": {}, "work": {}},
            metrics_snapshot={},
        )

        assert entry["objective"] == action["objective"]
        assert entry["plan_step"] == action["plan_step"]
        assert entry["plan_review"] == action["plan_review"]
        assert entry["last_action_review"] == action["last_action_review"]
        assert entry["outcome"] == expected_outcome


def test_action_history_fingerprint_uses_only_normalized_type_and_params() -> None:
    contract = {"type": "build", "params": {"z": 161, "kind": "Wall", "x": 88}}
    same_contract_different_metadata = {
        "type": " BUILD ",
        "params": {"kind": "Wall", "x": 88, "z": 161},
        "objective": "A different goal.",
        "plan_step": "A different plan step.",
        "plan_review": "A different review.",
        "last_action_review": {"worked": False},
        "intent": "Different metadata must not matter.",
    }

    def fingerprint(action):
        return _action_history_entry(
            step=1,
            action=action,
            requested_ticks=0,
            tick_info={"ticks_advanced": 0},
            execute_result={"accepted": True, "result": {}},
            state_before={"stocks": {}, "work": {}},
            advance_state={"stocks": {}, "work": {}},
            metrics_snapshot={},
        )["action_fingerprint"]

    base = fingerprint(contract)
    assert base == fingerprint(same_contract_different_metadata)
    assert base != fingerprint({**contract, "type": "DIG"})
    assert base != fingerprint({**contract, "params": {"z": 161, "kind": "Wall", "x": 89}})


def test_review_metadata_does_not_enter_helper_evidence_or_score_progress() -> None:
    review_metadata = {
        "objective": "Close the workshop room wall.",
        "plan_step": "Build the north wall.",
        "plan_review": "The target tile remains open floor.",
        "last_action_review": {"worked": False, "should_retry_same_path": False},
    }
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "DIG",
                "params": {"area": [50, 35, 0], "size": [5, 5, 1]},
                **review_metadata,
            },
            execute_result={
                "accepted": True,
                "result": {"newly_designated": 1, **review_metadata},
            },
        )
    )

    assert proof["helper_evidence"] == {"newly_designated": 1}
    assert not _keystroke_step_score_progress(review_metadata)


def test_governed_gameplay_proof_rejects_noop_redesignation() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            execute_result={
                "accepted": True,
                "result": {"newly_designated": 0, "already_designated": 25, "non_wall_tiles": 0},
            }
        )
    )
    assert proof["ok"] is False
    assert proof["provenance"] == "dfhack_governed"
    assert proof["gameplay_progress_eligible"] is False
    assert proof["helper_evidence"]["already_designated"] == 25
    assert proof["score_provenance"] == "dfhack_governed_observed_state"


def test_governed_gameplay_proof_rejects_noop_gather_redesignation() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "DIG",
                "params": {"area": [50, 35, 0], "size": [5, 5, 1], "kind": "gather"},
                "advance_ticks": 1000,
            },
            execute_result={
                "accepted": True,
                "result": {"shrubs_designated": 0, "already_designated": 9, "non_shrub_tiles": 16},
            },
        )
    )
    assert proof["ok"] is False
    assert proof["gameplay_progress_eligible"] is False
    assert proof["helper_evidence"]["already_designated"] == 9


def test_governed_gameplay_proof_records_new_gather_designations_without_progress() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "DIG",
                "params": {"area": [50, 35, 0], "size": [5, 5, 1], "kind": "gather"},
                "advance_ticks": 1000,
            },
            execute_result={
                "accepted": True,
                "result": {"shrubs_designated": 4, "already_designated": 0, "non_shrub_tiles": 21},
            },
        )
    )
    assert proof["ok"] is False
    assert proof["gameplay_progress_eligible"] is False
    assert proof["helper_evidence"]["shrubs_designated"] == 4


def test_governed_gameplay_proof_accepts_farm_crop_flip() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "FARM",
                "params": {"building_id": 34, "crop": "RADISH", "seasons": ["summer"]},
                "advance_ticks": 1000,
            },
            execute_result={
                "accepted": True,
                "result": {
                    "farm_building_id": 34,
                    "crop": "RADISH",
                    "seasons_set": ["summer"],
                    "seasons_skipped": [],
                    "seasons_changed": 1,
                    "seeds_on_hand": 1,
                },
            },
        )
    )
    assert proof["ok"] is True
    assert proof["helper_evidence"]["seasons_changed"] == 1
    assert proof["helper_evidence"]["crop"] == "RADISH"
    # building_id (new-building signal) must NOT leak in for a crop set
    assert "building_id" not in proof["helper_evidence"]


def test_governed_gameplay_proof_rejects_noop_farm_reset() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "FARM",
                "params": {"building_id": 34, "crop": "RADISH", "seasons": ["summer"]},
                "advance_ticks": 1000,
            },
            execute_result={
                "accepted": True,
                "result": {
                    "farm_building_id": 34,
                    "crop": "RADISH",
                    "seasons_set": ["summer"],
                    "seasons_skipped": [],
                    "seasons_changed": 0,
                    "seeds_on_hand": 1,
                },
            },
        )
    )
    assert proof["ok"] is False
    assert proof["gameplay_progress_eligible"] is False


def test_governed_gameplay_proof_rejects_designations_and_job_ids_alone() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            execute_result={"accepted": True, "result": {"newly_designated": 25}}
        )
    )
    assert proof["ok"] is False

    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "DIG",
                "params": {"kind": "chop", "area": [90, 100, 161], "size": [3, 3, 1]},
                "advance_ticks": 1000,
            },
            execute_result={"accepted": True, "result": {"trees_designated": 4}},
        )
    )
    assert proof["ok"] is False
    assert proof["helper_evidence"]["trees_designated"] == 4

    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "ORDER", "params": {"job": "bed", "quantity": 2}, "advance_ticks": 1000},
            execute_result={"accepted": True, "result": {"created_job_ids": [5, 7]}},
        )
    )
    assert proof["ok"] is False
    assert proof["helper_evidence"]["created_job_ids"] == [5, 7]
    assert proof["action_effect"]["status"] == "unobserved"

    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "BUILD", "params": {"kind": "CarpenterWorkshop"}, "advance_ticks": 1000},
            execute_result={
                "accepted": True,
                "result": {"before_carpenter_workshops": 0, "after_carpenter_workshops": 1},
            },
        )
    )
    assert proof["ok"] is True


def test_governed_gameplay_proof_accepts_new_farm_plot() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "BUILD", "params": {"kind": "FarmPlot", "x": 90, "y": 95, "z": 177}, "advance_ticks": 1000},
            execute_result={
                "accepted": True,
                "result": {"before_farm_plots": 0, "after_farm_plots": 1, "building_id": 42},
            },
        )
    )
    assert proof["ok"] is True
    assert proof["helper_evidence"]["after_farm_plots"] == 1


def test_governed_gameplay_proof_rejects_failed_farm_plot_placement() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "BUILD", "params": {"kind": "FarmPlot", "x": 90, "y": 95, "z": 177}, "advance_ticks": 1000},
            execute_result={
                "accepted": False,
                "result": {"error": "tile_not_placeable"},
            },
        )
    )
    assert proof["ok"] is False


def test_governed_gameplay_proof_accepts_new_still_workshop() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "BUILD", "params": {"kind": "Still", "x": 88, "y": 96, "z": 177}, "advance_ticks": 1000},
            execute_result={
                "accepted": True,
                "result": {"before_workshops_of_kind": 0, "after_workshops_of_kind": 1},
            },
        )
    )
    assert proof["ok"] is True
    assert proof["helper_evidence"]["after_workshops_of_kind"] == 1


def test_governed_duration_gate_rejects_queued_placements_but_accepts_built_farm_crop() -> None:
    assert not _governed_durable_helper_progress(
        {"type": "BUILD"},
        {
            "ok": True,
            "building_id": 42,
            "placed_count": 1,
            "before_workshops_of_kind": 0,
            "after_workshops_of_kind": 1,
        },
    )
    assert _governed_durable_helper_progress(
        {"type": "FARM"},
        {"ok": True, "farm_building_id": 42, "seasons_changed": 1},
    )


def test_governed_building_progress_requires_exact_owned_id_and_completed_stage() -> None:
    action = {
        "type": "BUILD",
        "params": {"kind": "CarpenterWorkshop", "x": 10, "y": 20, "z": 5},
    }
    execute_result = {
        "accepted": True,
        "result": {"ok": True, "building_id": 42},
    }

    claims = _governed_building_claims(action, execute_result)
    assert claims == {42: "CarpenterWorkshop"}
    assert _governed_completed_owned_buildings(
        claims,
        {
            "crew": {
                "ok": True,
                "workshops": [
                    {
                        "id": 41,
                        "subtype": "Carpenters",
                        "stage_read_ok": True,
                        "stage": 3,
                        "max_stage": 3,
                        "built": True,
                    },
                    {
                        "id": 42,
                        "subtype": "Carpenters",
                        "stage_read_ok": True,
                        "stage": 2,
                        "max_stage": 3,
                        "built": False,
                    },
                ],
            }
        },
    ) == set()

    completed = _governed_completed_owned_buildings(
        claims,
        {
            "crew": {
                "ok": True,
                "workshops": [
                    {
                        "id": 41,
                        "subtype": "Carpenters",
                        "stage_read_ok": True,
                        "stage": 3,
                        "max_stage": 3,
                        "built": True,
                    },
                    {
                        "id": 42,
                        "subtype": "Carpenters",
                        "stage_read_ok": True,
                        "stage": 3,
                        "max_stage": 3,
                        "built": True,
                    },
                ],
            }
        },
    )
    assert completed == {42}
    assert _governed_completed_owned_buildings(
        claims,
        {
            "crew": {
                "ok": True,
                "workshops": [
                    {
                        "id": 42,
                        "subtype": "Still",
                        "stage_read_ok": True,
                        "stage": 3,
                        "max_stage": 3,
                        "built": True,
                    }
                ],
            }
        },
    ) == set()
    assert _governed_completed_owned_buildings(
        claims,
        {
            "crew": {
                "ok": True,
                "workshops": [
                    {
                        "id": 42,
                        "subtype": "Carpenters",
                        "stage_read_ok": False,
                        "stage": 0,
                        "max_stage": 0,
                        "built": True,
                    }
                ],
            }
        },
    ) == set()
    assert _governed_owned_building_progress(claims, completed) == {
        "governed_owned_buildings": 1,
        "governed_owned_completed_buildings": 1,
        "governed_owned_completed_building_ids": [42],
        "governed_owned_completed_carpenter_workshops": 1,
        "governed_owned_completed_stills": 0,
        "governed_owned_completed_farm_plots": 0,
        "governed_owned_utility_progress": 5,
        "governed_owned_production_progress": 5,
        "governed_owned_complexity_progress": 0.0,
    }


def test_governed_building_claim_rejects_unaccepted_or_unmonitored_builds() -> None:
    action = {"type": "BUILD", "params": {"kind": "CarpenterWorkshop"}}
    assert _governed_building_claims(
        action,
        {"accepted": False, "result": {"ok": True, "building_id": 42}},
    ) == {}
    assert _governed_building_claims(
        {"type": "BUILD", "params": {"kind": "Bed"}},
        {"accepted": True, "result": {"ok": True, "building_id": 42}},
    ) == {}


def test_governed_gameplay_proof_rejects_noop_still_workshop_evidence() -> None:
    # a result with matching before/after counts (e.g. a failed placement
    # that still echoes the pre-existing count) must not read as progress
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "BUILD", "params": {"kind": "Still", "x": 88, "y": 96, "z": 177}, "advance_ticks": 1000},
            execute_result={
                "accepted": False,
                "result": {"before_workshops_of_kind": 1, "after_workshops_of_kind": 1},
            },
        )
    )
    assert proof["ok"] is False


def test_governed_gameplay_proof_accepts_observed_brew_output() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "ORDER", "params": {"job": "brew", "quantity": 3}, "advance_ticks": 1000},
            execute_result={
                "accepted": True,
                "result": {"created_job_ids": [11, 12, 13], "workshop_id": 3},
            },
            state_before={
                "crew": {"jobs": {"active_ids": []}},
                "survival": {"drink_produced_in_run": 25},
            },
            advance_state={
                "crew": {"jobs": {"active_ids": []}},
                "survival": {"drink_produced_in_run": 50},
            },
        )
    )
    assert proof["ok"] is True
    assert proof["helper_evidence"]["created_job_ids"] == [11, 12, 13]
    assert proof["action_effect"]["output_delta"] == 25


def test_governed_gameplay_proof_accepts_real_labor_flip() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "LABOR",
                "params": {"unit_id": 243, "labor": "brewing", "enable": True},
                "advance_ticks": 6000,
            },
            execute_result={
                "accepted": True,
                "result": {
                    "ok": True,
                    "unit_id": 243,
                    "labor": "brewing",
                    "labor_changed": True,
                    "labor_before": False,
                    "labor_after": True,
                },
            },
        )
    )
    assert proof["ok"] is True
    assert proof["helper_evidence"]["labor_changed"] is True


def test_governed_gameplay_proof_rejects_noop_labor_flip() -> None:
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={
                "type": "LABOR",
                "params": {"unit_id": 243, "labor": "brewing", "enable": True},
                "advance_ticks": 6000,
            },
            execute_result={
                "accepted": True,
                "result": {
                    "ok": True,
                    "unit_id": 243,
                    "labor": "brewing",
                    "labor_changed": False,
                    "labor_before": True,
                    "labor_after": True,
                },
            },
        )
    )
    assert proof["ok"] is False
    assert proof["gameplay_progress_eligible"] is False
    assert proof["helper_evidence"]["labor_changed"] is False


def test_governed_gameplay_proof_keeps_unowned_tile_changes_during_wait_uncredited() -> None:
    rect = [49, 34, 0, 55, 40, 0]
    before = {
        "ok": True,
        "rect": rect,
        "tiles": [{"x": 50, "y": 35, "z": 0, "category": "wall", "dig": 1, "hidden": False}],
    }
    after = {
        "ok": True,
        "rect": rect,
        "tiles": [{"x": 50, "y": 35, "z": 0, "category": "floor", "dig": 0, "hidden": False}],
    }
    proof = _governed_gameplay_proof(
        **_governed_proof_kwargs(
            action={"type": "WAIT", "params": {}, "advance_ticks": 1000},
            before_map_snapshot=before,
            after_map_snapshot=after,
        )
    )
    assert proof["ok"] is False
    assert proof["action_effect_observed"] is False
    assert proof["concurrent_world_state_changed"] is True
    assert proof["changed_tile_count"] == 1


def test_governed_runner_attaches_crew_observability() -> None:
    runner_text = (
        Path(__file__).resolve().parents[1]
        / "fort_gym"
        / "bench"
        / "run"
        / "runner.py"
    ).read_text(encoding="utf-8")

    assert "def attach_crew_metrics" in runner_text
    # Governed crew facts are global and plan agnostic. In particular, the
    # legacy target/plan rectangle is not used as a tile survey.
    assert "crew = read_job_metrics()" in runner_text
    assert "read_job_metrics(_job_metrics_survey_rect(state))" not in runner_text
    assert 'state["crew"] = crew' in runner_text


def test_governed_runner_attaches_fort_observability() -> None:
    runner_text = (
        Path(__file__).resolve().parents[1]
        / "fort_gym"
        / "bench"
        / "run"
        / "runner.py"
    ).read_text(encoding="utf-8")

    assert "def attach_fort_metrics" in runner_text
    assert 'state["fort"] = fort' in runner_text
    assert "fort_enclosed_spaces" in runner_text
