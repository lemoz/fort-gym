from __future__ import annotations

from fort_gym.bench.env.encoder import encode_observation


def test_encoder_hides_recommended_keys_after_target_attempt() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60},
            "ui_work": {
                "target_z": 177,
                "target_dig_designations": 0,
                "target_floor_tiles": 132,
                "target_wall_tiles": 10,
            },
            "ui_target_setup": {
                "ok": True,
                "target_generation": 1,
                "target_attempts": 1,
                "target_progress_seen": True,
                "selection_rect": [1, 2, 3, 4, 5, 6],
                "designatable_tiles": 6,
                "show_recommended_keys": False,
                "recommended_keys_suppressed": True,
                "recommended_keys": ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN"],
            },
            "ui_work_feedback": {
                "last_ui_work_progress_delta": 0,
                "last_ui_excavation_delta": 0,
                "no_progress_streak": 2,
            },
        },
        screen_text="screen",
    )

    assert "Fresh target recommended keys: hidden" in text
    assert "already produced real tile progress" in text
    assert "D_DESIGNATE, DESIGNATE_STAIR_DOWN" not in text
    assert "last_action_work_delta=0" in text
    assert "do not repeat the same key sequence" in text
    assert "selection_rect and window are observation metadata" in text
    assert "not a manual cursor route" in text
    assert "Fresh target route: unavailable" in text
    assert "do not invent CURSOR offsets" in text


def test_encoder_shows_recommended_keys_for_fresh_target() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60},
            "ui_target_setup": {
                "ok": True,
                "target_generation": 2,
                "target_attempts": 0,
                "target_progress_seen": False,
                "selection_rect": [1, 2, 3, 4, 5, 6],
                "designatable_tiles": 6,
                "show_recommended_keys": True,
                "recommended_keys": ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN"],
            },
            "ui_work_feedback": {
                "target_refreshed": True,
            },
        },
        screen_text="screen",
    )

    assert "target refreshed after repeated no-progress actions" in text
    assert "selection_rect and window are observation metadata" in text
    assert "Fresh target recommended keys: D_DESIGNATE, DESIGNATE_STAIR_DOWN" in text


def test_encoder_shows_retry_recommended_keys_after_failed_attempt() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60},
            "ui_target_setup": {
                "ok": True,
                "target_generation": 2,
                "target_attempts": 1,
                "target_progress_seen": False,
                "selection_rect": [1, 2, 3, 4, 5, 6],
                "designatable_tiles": 6,
                "show_recommended_keys": True,
                "recommended_keys_retry": True,
                "recommended_keys": ["D_DESIGNATE", "DESIGNATE_STAIR_DOWN"],
            },
            "ui_work_feedback": {
                "last_ui_work_progress_delta": 0,
                "last_ui_excavation_delta": 0,
                "no_progress_streak": 1,
            },
        },
        screen_text="screen",
    )

    assert "Retry fresh target recommended keys: D_DESIGNATE, DESIGNATE_STAIR_DOWN" in text
    assert "last_action_work_delta=0" in text


def test_encoder_material_target_tile_change_is_not_material_success() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_target_setup": {
                "ok": True,
                "target_mode": "material",
                "target_generation": 2,
                "target_attempts": 1,
                "target_progress_seen": False,
                "selection_rect": [1, 2, 3, 4, 5, 6],
                "designatable_tiles": 1,
                "show_recommended_keys": True,
                "recommended_keys_retry": True,
                "recommended_keys": ["D_DESIGNATE", "DESIGNATE_CHOP"],
            },
            "ui_work_feedback": {
                "last_ui_work_progress_delta": 2,
                "last_ui_excavation_delta": 0,
                "last_ui_material_delta": 0,
                "target_step_succeeded": False,
                "no_progress_streak": 1,
            },
        },
        screen_text="screen",
    )

    assert "last_action_work_delta=2" in text
    assert "did not acquire usable wood or stone yet" in text
    assert "last action dug real tiles" not in text
    assert "Retry fresh target recommended keys: D_DESIGNATE, DESIGNATE_CHOP" in text


def test_encoder_explains_inactive_df_cursor_sentinel() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60},
            "work": {
                "cursor_x": -30000,
                "cursor_y": 92,
                "cursor_z": 177,
                "window_x": 87,
                "window_y": 82,
                "window_z": 177,
            },
        },
        screen_text="screen",
    )

    assert "cursor_inactive=(-30000,92,177)" in text
    assert "no active DF cursor" in text
    assert "opening a designation, stockpile, or building-placement mode" in text


def test_encoder_shows_material_phase_after_enough_ui_excavation_without_materials() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 0, "stone": 0},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "total_material_delta": 1,
                "successful_targets": 2,
            },
        },
        screen_text="screen",
    )

    assert "Live UI run progress: total_work_delta=12" in text
    assert "building material is missing" in text
    assert "material target recommended keys" in text


def test_encoder_material_blocker_overrides_available_stock_build_phase() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "total_material_delta": 0,
                "successful_targets": 2,
            },
            "ui_build_feedback": {
                "material_blocked": True,
                "visible": True,
            },
        },
        screen_text="Needs building material",
    )

    assert "building material is missing, unusable, or not yet proven" in text
    assert "D_BUILDING is premature on this turn" in text
    assert "try D_BUILDING" not in text


def test_encoder_ready_workshop_placement_overrides_stale_material_warning() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "total_material_delta": 3,
                "successful_targets": 2,
            },
            "ui_build_feedback": {
                "material_blocked": True,
                "visible": False,
            },
            "ui_target_setup": {
                "ok": True,
                "target_mode": "workshop",
                "target_generation": 5,
                "target_attempts": 0,
                "selection_rect": [94, 100, 177, 96, 102, 177],
                "designatable_tiles": 9,
                "show_recommended_keys": True,
                "recommended_keys": ["SELECT"],
            },
        },
        screen_text="Carpenter's Workshop\nPlacement\nEnter: Place\nESC: Cancel",
    )

    assert "current visible workshop placement screen says Enter: Place" in text
    assert "older material warnings as stale" in text
    assert "valid carpenter workshop placement screen" in text
    assert "press SELECT with advance_ticks=0" in text
    assert "Fresh target recommended keys: SELECT" in text
    assert "previous build screen said material was missing" not in text
    assert "building material is missing, unusable, or not yet proven" not in text


def test_encoder_workshop_material_selection_recommends_select() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "total_material_delta": 3,
                "successful_targets": 2,
            },
            "ui_build_feedback": {
                "material_blocked": True,
                "visible": False,
            },
            "ui_target_setup": {
                "ok": True,
                "target_mode": "workshop",
                "target_generation": 5,
                "target_attempts": 0,
                "selection_rect": [92, 100, 177, 94, 102, 177],
                "designatable_tiles": 9,
                "show_recommended_keys": True,
                "recommended_keys": ["SELECT"],
            },
        },
        screen_text=(
            "Carpenter's Workshop\n"
            "Item              Dist Num\n"
            "ginkgo wood logs  1    0/3\n"
            "Enter: Select"
        ),
    )

    assert "current visible workshop material selection screen" in text
    assert "press SELECT with advance_ticks=0 to choose the highlighted material" in text
    assert "carpenter workshop material-selection list" in text
    assert "Fresh target recommended keys: SELECT" in text
    assert "previous build screen said material was missing" not in text
    assert "building material is missing, unusable, or not yet proven" not in text


def test_encoder_existing_workshop_target_prioritizes_reselection() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
                "carpenter_workshops_planned": 1,
                "carpenter_workshops_usable": 0,
                "carpenter_workshop_task_jobs": 0,
                "carpenter_workshop_construction_jobs": 0,
                "active_construct_building_jobs": 0,
                "carpenter_workshop_x1": 97,
                "carpenter_workshop_y1": 93,
                "carpenter_workshop_z": 177,
                "carpenter_workshop_x2": 99,
                "carpenter_workshop_y2": 95,
            },
            "ui_target_setup": {
                "ok": True,
                "target_mode": "existing_workshop",
                "target_generation": 6,
                "target_attempts": 0,
                "selection_rect": [97, 93, 177, 99, 95, 177],
                "designatable_tiles": 0,
                "show_recommended_keys": True,
                "recommended_keys": ["D_BUILDJOB"],
            },
        },
        screen_text="D: Designations\nB: Building\nmain map",
    )

    assert "Existing workshop: rect=(97,93,177)-(99,95,177)" in text
    assert "Workshop proof route: before using manager/nobles" in text
    assert "Live UI existing workshop target" in text
    assert "Fresh target recommended keys: D_BUILDJOB" in text


def test_encoder_explains_carried_forward_workshop_proof() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
                "carpenter_workshops_planned": 1,
                "carpenter_workshops_usable": 1,
                "carpenter_workshops_usable_carried_forward": True,
                "carpenter_workshop_task_jobs": 0,
                "carpenter_workshop_construction_jobs": 0,
            },
        },
        screen_text="D: Designations\nB: Building\nmain map",
    )

    assert "already proven usable by earlier real task-menu evidence" in text
    assert "Do not reopen the same workshop just to prove usability again" in text


def test_encoder_anchors_queued_workshop_task_phase() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 30, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
                "carpenter_workshops_planned": 1,
                "carpenter_workshops_usable": 1,
                "carpenter_workshop_task_jobs": 1,
                "active_jobs": 0,
                "active_carpenter_jobs": 0,
                "carpenter_labors_enabled": 1,
                "carpenter_workshop_task_job_type_names": ["ConstructShield"],
            },
            "ui_target_setup": {
                "ok": True,
                "target_mode": "existing_workshop",
                "target_generation": 7,
                "target_attempts": 0,
                "selection_rect": [97, 93, 177, 99, 95, 177],
                "show_recommended_keys": True,
                "recommended_keys": ["D_BUILDJOB"],
            },
        },
        screen_text="D: Designations\nB: Building\nmain map",
    )

    assert "active_jobs=0, active_carpenter_jobs=0" in text
    assert "Workshop queued tasks: ConstructShield" in text
    assert "real carpenter workshop task is queued on a usable workshop" in text
    assert "Keep the existing_workshop target anchored" in text
    assert "prefer a larger empty-key time advance or inspect D_JOBLIST" in text


def test_encoder_shows_build_phase_after_material_exists() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 0, "stone": 1},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "total_material_delta": 1,
                "successful_targets": 2,
            },
        },
        screen_text="screen",
    )

    assert "enough starter digging and building material exist" in text
    assert "try D_BUILDING" in text


def test_encoder_shows_production_phase_after_order_exists() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 13, "stone": 0},
            "work": {
                "manager_orders_count": 1,
                "manager_orders_amount_left": 5,
                "carpenter_workshops": 1,
            },
        },
        screen_text="Ready: Construct Bed 5/5",
    )

    assert "Live UI production phase" in text
    assert "a real manager order is queued" in text
    assert "advance_ticks >= 1000" in text
    assert "inspect the workshop/task/cancellation path" in text


def test_encoder_production_phase_prioritizes_manager_required_screen() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 13, "stone": 0},
            "work": {
                "manager_orders_count": 1,
                "manager_orders_amount_left": 5,
                "carpenter_workshops": 1,
            },
        },
        screen_text="A manager is required to coordinate work orders.\nReady: Construct Bed 5/5",
    )

    assert "Live UI production phase" in text
    assert "appoint a manager before relying on time advancement" in text
    assert "advance_ticks >= 1000" not in text


def test_encoder_production_phase_prioritizes_cancellation_inspection() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 4, "stone": 0},
            "work": {
                "manager_orders_count": 1,
                "manager_orders_amount_left": 2,
                "carpenter_workshops": 1,
            },
        },
        screen_text="Woodworker cancels Construct Bed: Nee[ds] something\nMain map",
    )

    assert "visible production cancellation/Needs message" in text
    assert "do not blindly wait" in text
    assert "Inspect the carpenter workshop/task list" in text
    assert "advance_ticks >= 1000" not in text


def test_encoder_classifies_manager_required_screen() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 13, "stone": 0},
            "work": {
                "manager_orders_count": 1,
                "manager_orders_amount_left": 5,
                "carpenter_workshops": 1,
            },
        },
        screen_text="A manager is required to coordinate work orders.\nReady: Construct Bed 5/5",
    )

    assert "Screen state: mode=manager_required" in text
    assert "Do not advance time for production yet" in text
    assert "do not combine LEAVESCREEN with a later menu/action key" in text
    assert state["screen_state"]["mode"] == "manager_required"
    assert state["screen_state"]["confidence"] == "high"


def test_encoder_classifies_main_map_before_nobles_menu_option() -> None:
    screen_text = (
        "#*PAUSED*######################  Dwarf Fortress\n"
        "a: View Announcements\n"
        "b: Building     r: Reports\n"
        "d: Designations o: Set Order\n"
        "n: Nobles and Administrators\n"
        "Space: Resume .: One-Step"
    )
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
        },
        screen_text=screen_text,
    )

    assert "Screen state: mode=main_map" in text
    assert state["screen_state"]["mode"] == "main_map"


def test_encoder_warns_nobles_screen_requires_visible_manager_row() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 8, "stone": 0},
        },
        screen_text=(
            "The Nobles and Administrators of Niralrakust\n"
            "Expedition Leader: Urist\n"
            "Manager: None\n"
        ),
    )

    assert "Screen state: mode=nobles_administrators" in text
    assert "Do not use STANDARDSCROLL keys here" in text
    assert "target row is visible and highlighted" in text
    assert state["screen_state"]["mode"] == "nobles_administrators"


def test_encoder_classifies_workshop_add_task_list_with_highlight() -> None:
    screen_text = (
        "Carpenter's Workshop\n"
        "Make wooden shield\n"
        "Construct Bed (b)\n"
        "+-*/: Scroll\n\n"
        "== SCREEN VISUAL HINTS ==\n"
        "Rows below have non-default CopyScreen background colors.\n"
        "- row 2 cols 0-16 fg=0 bg=7: Construct Bed (b)"
    )
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 13, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
            },
        },
        screen_text=screen_text,
    )

    assert "Screen state: mode=workshop_add_task_list" in text
    assert "highlighted=Construct Bed (b)" in text
    assert "SELECT chooses the highlighted task row" in text
    assert "STANDARDSCROLL keys, not CURSOR_DOWN/CURSOR_UP" in text
    assert state["screen_state"]["mode"] == "workshop_add_task_list"
    assert state["screen_state"]["highlighted"] == "Construct Bed (b)"


def test_encoder_does_not_treat_add_new_task_prompt_as_task_list() -> None:
    screen_text = (
        "Ctrl+n: Give name\n"
        "Carpenter's Workshop\n"
        "a: Add new task +-/*: Select\n"
        "c: Cancel task  d: Details\n"
        "x: Remove Building\n"
        "ESC: Done\n"
    )
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 29, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
                "carpenter_workshop_task_jobs": 0,
            },
        },
        screen_text=screen_text,
    )

    assert "Screen state: mode=carpenter_workshop_selected" in text
    assert "use BUILDJOB_ADD to open the native add-task list" in text
    assert state["screen_state"]["mode"] == "carpenter_workshop_selected"


def test_encoder_classifies_manager_new_order_search() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 13, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
            },
        },
        screen_text="Manager\nNew Order\nSearch: bed\nConstruct Bed\nEnter: Select",
    )

    assert "Screen state: mode=manager_new_order_search" in text
    assert "SELECT can queue it" in text
    assert "Construct Bed" in state["screen_state"]["evidence"]
    assert state["screen_state"]["mode"] == "manager_new_order_search"


def test_encoder_classifies_pending_carpenter_workshop_construction_screen() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
                "carpenter_workshops_planned": 1,
                "carpenter_workshops_usable": 0,
                "carpenter_workshops_unproven": 1,
                "active_jobs": 0,
            },
        },
        screen_text=(
            "Ctrl+n: Give name\n"
            "Carpenter's Workshop\n"
            "Waiting for construction...\n"
            "Needs Carpentry\n"
            "Construction inactive.\n"
            "x: Remove Building\n"
            "ESC: Done"
        ),
    )

    assert "Screen state: mode=carpenter_workshop_construction_pending" in text
    assert "BUILDJOB_ADD will not queue production" in text
    assert "no usable workshop or task job is proven yet" in text
    assert "BUILDJOB_ADD is not a valid production action" in text
    assert state["screen_state"]["mode"] == "carpenter_workshop_construction_pending"
    assert state["screen_state"]["confidence"] == "high"


def test_encoder_classifies_building_workshop_type_menu_after_workshop_placed() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
                "carpenter_workshops_planned": 1,
                "carpenter_workshops_usable": 0,
                "carpenter_workshops_unproven": 1,
                "carpenter_workshop_construction_jobs": 1,
                "active_construct_building_jobs": 0,
            },
        },
        screen_text=(
            "Leather Works            (e)\n"
            "Quern                    (q)\n"
            "Bowyer's Workshop        (b)\n"
            "Carpenter's Workshop     (c)\n"
            "Mason's Workshop         (m)"
        ),
    )

    assert "Screen state: mode=building_workshop_type_menu" in text
    assert "construction job is already queued" in text
    assert "submit only LEAVESCREEN" in text
    assert state["screen_state"]["mode"] == "building_workshop_type_menu"
    assert state["screen_state"]["confidence"] == "high"


def test_encoder_classifies_selected_usable_carpenter_workshop_screen() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
                "carpenter_workshops_planned": 1,
                "carpenter_workshops_usable": 1,
                "active_jobs": 0,
            },
        },
        screen_text=(
            "Ctrl+n: Give name\n"
            "Carpenter's Workshop\n"
            "x: Remove Building\n"
            "ESC: Done"
        ),
    )

    assert "Screen state: mode=carpenter_workshop_selected" in text
    assert "use BUILDJOB_ADD to open the native add-task list" in text
    assert "do not leave and wait" in text
    assert state["screen_state"]["mode"] == "carpenter_workshop_selected"
    assert state["screen_state"]["confidence"] == "high"


def test_encoder_keeps_carpenter_placement_screen_distinct_from_selected_workshop() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 0,
                "active_jobs": 0,
            },
        },
        screen_text=(
            "Carpenter's Workshop\n"
            "Placement\n"
            "Needs building material\n"
            "x: Remove Building\n"
            "ESC: Done"
        ),
    )

    assert "Screen state: mode=workshop_placement" in text
    assert state["screen_state"]["mode"] == "workshop_placement"


def test_encoder_classifies_jobs_screen_manager_footer() -> None:
    screen_text = (
        "###############################  Dwarf Fortress  ###############################\n"
        "# Fish                        Kogan At?kustuth, Fisherdwrf                     #\n"
        "# Construct Building          Inactive                      Carpenter's Wrkshp #\n"
        "# No Job                      Uvash Inethshedim, Miner                         #\n"
        "# v: View Unit z: Go to Unit    b: Go to Bld   m: Manager     x: Remove Worker #\n"
        "# r: Set Job Repeat             j: View Job    s: Suspend Job c: Cancel Job    #\n"
        "# q: Search                     n: Do job now!                                 #\n"
        "################################################################################"
    )
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 13, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 1,
            },
        },
        screen_text=screen_text,
    )

    assert "Screen state: mode=job_list" in text
    assert "UNITJOB_MANAGER" in text
    assert "do not combine LEAVESCREEN with a later menu/action key" in text
    assert state["screen_state"]["mode"] == "job_list"
    assert state["screen_state"]["confidence"] == "high"


def test_encoder_does_not_trust_stock_only_material_for_build_phase() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "total_material_delta": 0,
                "successful_targets": 2,
            },
        },
        screen_text="screen",
    )

    assert "building material is missing, unusable, or not yet proven" in text
    assert "try D_BUILDING" not in text


def test_encoder_labels_material_target_setup() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 0, "stone": 0},
            "ui_target_setup": {
                "ok": True,
                "target_mode": "material",
                "target_generation": 3,
                "target_attempts": 0,
                "selection_rect": [10, 20, 177, 13, 21, 177],
                "designatable_tiles": 4,
                "show_recommended_keys": True,
                "recommended_keys": ["D_DESIGNATE", "DESIGNATE_DIG"],
            },
        },
        screen_text="screen",
    )

    assert "Live UI setup: mode=material" in text
    assert "Live UI material target" in text


def test_encoder_surfaces_target_z_mismatch() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 0, "stone": 0},
            "work": {
                "cursor_x": -30000,
                "cursor_y": 92,
                "cursor_z": 176,
                "window_x": 87,
                "window_y": 82,
                "window_z": 176,
            },
            "ui_work": {
                "target_z": 177,
                "target_dig_designations": 0,
                "target_floor_tiles": 12,
                "target_wall_tiles": 4,
            },
            "ui_target_setup": {
                "ok": True,
                "target_mode": "material",
                "target_generation": 3,
                "target_attempts": 1,
                "selection_rect": [10, 20, 177, 13, 21, 177],
                "designatable_tiles": 4,
                "show_recommended_keys": True,
                "recommended_keys": ["D_DESIGNATE", "DESIGNATE_DIG"],
            },
        },
        screen_text="screen",
    )

    assert "Live UI z-level mismatch: current view z=176, target z=177" in text
    assert "Do not send target designation or placement keys" in text
    assert "CURSOR_UP_Z" in text
    assert "wait for the next observation" in text
    assert "intentionally exploring this z-level" in text
    assert "ignore the stale target keys" in text


def test_encoder_labels_material_recovery_as_exit_only() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 0, "stone": 0},
            "ui_target_setup": {
                "ok": True,
                "target_mode": "material",
                "target_generation": 3,
                "target_attempts": 2,
                "selection_rect": [10, 20, 177, 13, 21, 177],
                "designatable_tiles": 4,
                "show_recommended_keys": True,
                "recommended_keys": ["LEAVESCREEN", "LEAVESCREEN"],
                "recommended_key_prefix": ["LEAVESCREEN", "LEAVESCREEN"],
                "recommended_keys_exit_only": True,
            },
        },
        screen_text="Needs building material",
    )

    assert "copy only the listed escape keys this turn" in text
    assert "Do not chain a new designation or build command" in text
    assert "Fresh target recommended keys: LEAVESCREEN, LEAVESCREEN" in text
    assert "D_DESIGNATE" not in text


def test_encoder_labels_workshop_target_setup() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_target_setup": {
                "ok": True,
                "target_mode": "workshop",
                "target_generation": 4,
                "target_attempts": 0,
                "selection_rect": [10, 20, 177, 12, 22, 177],
                "designatable_tiles": 9,
                "show_recommended_keys": True,
                "recommended_keys": [
                    "LEAVESCREEN",
                    "LEAVESCREEN",
                    "D_BUILDING",
                    "HOTKEY_BUILDING_WORKSHOP",
                    "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
                    "SELECT",
                    "SELECT",
                ],
            },
        },
        screen_text="screen",
    )

    assert "Live UI setup: mode=workshop" in text
    assert "Live UI workshop target" in text
    assert "candidate 3x3 floor target" in text
    assert "Only press SELECT" in text
    assert "D_BUILDING, HOTKEY_BUILDING_WORKSHOP" in text


def test_encoder_lets_visible_blocked_workshop_screen_override_target_metadata() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_target_setup": {
                "ok": True,
                "target_mode": "workshop",
                "target_generation": 4,
                "target_attempts": 1,
                "selection_rect": [10, 20, 177, 12, 22, 177],
                "designatable_tiles": 9,
                "show_recommended_keys": True,
                "recommended_keys": [
                    "D_BUILDING",
                    "HOTKEY_BUILDING_WORKSHOP",
                    "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
                ],
            },
        },
        screen_text="Carpenter's Workshop\nPlacement\nBlocked",
    )

    assert "this is only a candidate 3x3 floor target" in text
    assert "visible DF placement screen currently says placement is blocked" in text
    assert "do not press SELECT" in text
    assert "trust the visible screen" in text

    building_present_text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_target_setup": {
                "ok": True,
                "target_mode": "workshop",
                "target_generation": 4,
                "target_attempts": 1,
                "selection_rect": [10, 20, 177, 12, 22, 177],
                "designatable_tiles": 9,
                "show_recommended_keys": True,
                "recommended_keys": ["SELECT"],
            },
        },
        screen_text="Carpenter's Workshop\nPlacement\nBuilding present\nEnter: Place",
    )

    assert "visible DF placement screen currently says placement is blocked" in building_present_text
    assert "valid carpenter workshop placement screen" not in building_present_text


def test_encoder_shows_material_recovery_prefix() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_target_setup": {
                "ok": True,
                "target_mode": "material",
                "target_generation": 3,
                "target_attempts": 1,
                "selection_rect": [10, 20, 177, 13, 21, 177],
                "designatable_tiles": 1,
                "show_recommended_keys": True,
                "recommended_keys_retry": True,
                "recommended_key_prefix": ["LEAVESCREEN", "LEAVESCREEN"],
                "recommended_keys": [
                    "LEAVESCREEN",
                    "LEAVESCREEN",
                    "D_DESIGNATE",
                    "DESIGNATE_CHOP",
                ],
            },
        },
        screen_text="Needs building material",
    )

    assert "Live UI material recovery" in text
    assert "LEAVESCREEN, LEAVESCREEN" in text
    assert (
        "Retry fresh target recommended keys: LEAVESCREEN, LEAVESCREEN, "
        "D_DESIGNATE, DESIGNATE_CHOP"
    ) in text


def test_encoder_surfaces_build_material_blocker() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "ui_build_feedback": {
                "material_blocked": True,
            },
        },
        screen_text="screen",
    )

    assert "visible build screen says material is missing" in text
    assert "acquire logs or stone" in text


def test_encoder_surfaces_blocked_workshop_footprint_feedback() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 8, "stone": 0},
            "ui_workshop_feedback": {
                "placement_blocked": True,
                "blocked_targets": [[97, 93, 177]],
                "menu_escape_keys": ["LEAVESCREEN"],
            },
        },
        screen_text="Carpenter's Workshop\nPlacement\nBlocked",
    )

    assert "native DF rejected the current carpenter workshop footprint as blocked" in text
    assert "do not retry that exact footprint" in text
    assert "submit only LEAVESCREEN keys with advance_ticks=0" in text


def test_encoder_renders_recent_action_outcomes() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
        },
        screen_text="screen",
        action_history=[
            {
                "step": 12,
                "intent": "place workshop",
                "keys": ["STRING_A099", "SELECT"],
                "requested_ticks": 200,
                "actual_ticks": 206,
                "accepted": True,
                "outcome": "gameplay_state_changed",
                "productive_reasons": ["carpenter_workshop_created"],
                "changed": ["carpenter_workshops:+1", "wood:-1"],
            },
            {
                "step": 13,
                "intent": "retry same menu item",
                "keys": ["STRING_A099"],
                "requested_ticks": 0,
                "actual_ticks": 0,
                "accepted": True,
                "outcome": "keys_sent_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
            },
        ],
    )

    assert "== RECENT ACTION OUTCOMES ==" in text
    assert "Step 12: place workshop" in text
    assert "actual=206t" in text
    assert "outcome=gameplay_state_changed" in text
    assert "changed=carpenter_workshops:+1, wood:-1" in text
    assert "outcome=keys_sent_without_tracked_state_change" in text
    assert "changed=none" in text


def test_encoder_summarizes_stuck_queued_order_waits() -> None:
    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "work": {
                "manager_orders_count": 1,
                "manager_orders_amount_left": 1,
                "carpenter_workshops": 1,
            },
        },
        screen_text="main map",
        action_history=[
            {
                "step": 27,
                "intent": "wait for bed order",
                "keys": ["STRING_A032"],
                "requested_ticks": 500,
                "actual_ticks": 500,
                "accepted": True,
                "outcome": "advanced_ticks_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
                "manager_orders_before": 1,
                "manager_orders_after": 1,
                "order_qty_left_before": 1,
                "order_qty_left_after": 1,
                "carpenter_workshops_before": 1,
                "carpenter_workshops_after": 1,
            },
            {
                "step": 28,
                "intent": "wait again for bed order",
                "keys": ["STRING_A032"],
                "requested_ticks": 1000,
                "actual_ticks": 1001,
                "accepted": True,
                "outcome": "advanced_ticks_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
                "manager_orders_before": 1,
                "manager_orders_after": 1,
                "order_qty_left_before": 1,
                "order_qty_left_after": 1,
                "carpenter_workshops_before": 1,
                "carpenter_workshops_after": 1,
            },
        ],
    )

    summary = state["recent_progress_summary"]
    assert summary["queued_order_stuck"] is True
    assert summary["manager_order_qty_unchanged_after_ticks"] == 1501
    assert summary["do_not_repeat_wait"] is True
    assert "queued_order_stuck=true" in text
    assert "manager_order_qty_unchanged_after_ticks=1501" in text
    assert "do_not_repeat_wait=true" in text
    assert "do not press STRING_A032 or wait again" in text


def test_encoder_flags_repeated_manager_menu_loop() -> None:
    action_history = []
    for step in range(6):
        if step % 2 == 0:
            keys = ["LEAVESCREEN", "LEAVESCREEN", "D_NOBLES"]
            intent = "Open Nobles screen to assign manager"
        else:
            keys = ["CURSOR_DOWN", "CURSOR_DOWN", "CURSOR_DOWN", "CURSOR_DOWN", "SELECT"]
            intent = "Navigate to Manager row and select a candidate"
        action_history.append(
            {
                "step": step,
                "intent": intent,
                "keys": keys,
                "requested_ticks": 0,
                "actual_ticks": 0,
                "accepted": True,
                "outcome": "keys_sent_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
                "last_action_review": {
                    "worked": False,
                    "should_retry_same_path": False,
                    "mismatch_reason": "Still on unit info screen, not the Nobles list",
                },
            }
        )

    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "work": {
                "manager_orders_count": 1,
                "manager_orders_amount_left": 1,
                "carpenter_workshops": 1,
            },
        },
        screen_text="unit info screen",
        action_history=action_history,
    )

    summary = state["recent_progress_summary"]
    assert summary["menu_no_progress_streak"] == 6
    assert summary["repeated_menu_family"] == "manager_nobles_menu"
    assert summary["repeated_menu_family_count"] == 6
    assert summary["last_action_family"] == "manager_nobles_menu"
    assert summary["escape_recovery_attempted"] is False
    assert summary["agent_marked_bad_menu_path"] is True
    assert summary["do_not_repeat_menu_path"] is True
    assert "do_not_repeat_menu_path=true" in text
    assert "you are repeating a no-progress manager_nobles_menu path" in text
    assert "your next action must be only LEAVESCREEN keys" in text
    assert "do not use fixed CURSOR_DOWN counts" in text


def test_encoder_does_not_classify_workshop_intent_designation_as_menu_loop() -> None:
    _, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "work": {},
        },
        screen_text="main map",
        action_history=[
            {
                "step": 1,
                "intent": "Chop trees to get logs for carpenter workshop construction",
                "keys": ["D_DESIGNATE", "DESIGNATE_CHOP", "SELECT", "SELECT"],
                "requested_ticks": 500,
                "actual_ticks": 500,
                "accepted": True,
                "outcome": "advanced_ticks_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
            }
        ],
    )

    summary = state["recent_progress_summary"]
    assert summary["menu_no_progress_streak"] == 0
    assert summary["do_not_repeat_menu_path"] is False


def test_encoder_warns_not_to_reopen_blocked_menu_after_escape() -> None:
    action_history = []
    for step in range(5):
        action_history.append(
            {
                "step": step,
                "intent": "Reopen carpenter workshop placement after a blocked attempt",
                "keys": [
                    "LEAVESCREEN",
                    "D_BUILDING",
                    "HOTKEY_BUILDING_WORKSHOP",
                    "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
                ],
                "requested_ticks": 0,
                "actual_ticks": 0,
                "accepted": True,
                "outcome": "keys_sent_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
            }
        )
    action_history.append(
        {
            "step": 5,
            "intent": "Escape the blocked workshop placement path",
            "keys": ["LEAVESCREEN", "LEAVESCREEN"],
            "requested_ticks": 0,
            "actual_ticks": 0,
            "accepted": True,
            "outcome": "keys_sent_without_tracked_state_change",
            "productive_reasons": [],
            "changed": [],
        }
    )

    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 0,
            },
        },
        screen_text="main map",
        action_history=action_history,
    )

    summary = state["recent_progress_summary"]
    assert summary["do_not_repeat_menu_path"] is True
    assert summary["escape_recovery_attempted"] is True
    assert "a clean LEAVESCREEN recovery has already happened" in text
    assert "do not reopen the blocked menu family" in text
    assert "do not press D_BUILDING" in text


def test_encoder_keeps_blocked_menu_sticky_after_no_progress_detour() -> None:
    action_history = []
    for step in range(5):
        action_history.append(
            {
                "step": step,
                "intent": "Try carpenter workshop placement again",
                "keys": [
                    "LEAVESCREEN",
                    "D_BUILDING",
                    "HOTKEY_BUILDING_WORKSHOP",
                    "HOTKEY_BUILDING_WORKSHOP_CARPENTER",
                ],
                "requested_ticks": 0,
                "actual_ticks": 0,
                "accepted": True,
                "outcome": "keys_sent_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
            }
        )
    action_history.extend(
        [
            {
                "step": 5,
                "intent": "Escape the blocked placement screen",
                "keys": ["LEAVESCREEN", "LEAVESCREEN"],
                "requested_ticks": 0,
                "actual_ticks": 0,
                "accepted": True,
                "outcome": "keys_sent_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
            },
            {
                "step": 6,
                "intent": "Open designation mode but do not complete a useful designation",
                "keys": ["D_DESIGNATE", "DESIGNATE_DIG"],
                "requested_ticks": 0,
                "actual_ticks": 0,
                "accepted": True,
                "outcome": "keys_sent_without_tracked_state_change",
                "productive_reasons": [],
                "changed": [],
            },
        ]
    )

    text, state = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 23},
            "work": {
                "manager_orders_count": 0,
                "manager_orders_amount_left": 0,
                "carpenter_workshops": 0,
            },
        },
        screen_text="main map",
        action_history=action_history,
    )

    summary = state["recent_progress_summary"]
    assert summary["do_not_repeat_menu_path"] is True
    assert summary["sticky_blocked_menu_path"] is True
    assert summary["escape_recovery_attempted"] is True
    assert summary["repeated_menu_family"] == "building_placement_menu"
    assert "sticky_blocked_menu_path=true" in text
    assert "remains forbidden until a later action produces real" in text


def test_encoder_surfaces_plan_rects_and_legal_build_site() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "work": {
                "target_rect": [90, 90, 177, 96, 96, 177],
                "fortress_connector_rect": [96, 92, 177, 98, 94, 177],
                "fortress_workshop_room_rect": [98, 90, 177, 104, 96, 177],
                "carpenter_build_site": [99, 93, 177],
            },
        },
        screen_text="main map",
    )

    assert (
        "Plan rects (x1,y1,z1,x2,y2,z2): starter=[90,90,177,96,96,177], "
        "connector=[96,92,177,98,94,177], workshop_room=[98,90,177,104,96,177]" in text
    )
    assert "Legal BUILD site observed: carpenter_build_site=(99,93,177)" in text
    assert "a BUILD there fits the allowed rects." in text


def test_encoder_reports_no_legal_build_site_without_carpenter_build_site() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "work": {
                "target_rect": [90, 90, 177, 96, 96, 177],
            },
        },
        screen_text="main map",
    )

    assert "No legal BUILD site observed yet." in text
    assert (
        "BUILD must fit a full 3x3 footprint on open floor inside the starter "
        "or workshop_room rects; complete more floor first." in text
    )


def test_encoder_echoes_bounded_helper_result_counts() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
        },
        screen_text="main map",
        last_action_result={
            "accepted": True,
            "result": {"newly_designated": 0, "already_designated": 25},
        },
    )

    assert "Last Action detail:" in text
    assert "newly_designated=0" in text
    assert "already_designated=25" in text


def test_encoder_ignores_malformed_plan_rects_without_crashing() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "work": {
                "target_rect": "junk",
            },
        },
        screen_text="main map",
    )

    assert "Plan rects" not in text
    assert "No legal BUILD site observed yet." in text


def test_encoder_surfaces_full_crew_block() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "crew": {
                "ok": True,
                "citizens": {
                    "total": 7,
                    "idle": 6,
                    "mining_labor": 1,
                    "carpentry_labor": 2,
                    "woodcutting_labor": 1,
                    "masonry_labor": 0,
                    "herbalism_labor": 0,
                },
                "jobs": {
                    "total": 1,
                    "dig": 0,
                    "construct_building": 0,
                    "workshop_task": 0,
                    "suspended": 0,
                    "entries": [
                        {
                            "type": "Fish",
                            "pos": [165, 132, 177],
                            "suspended": False,
                            "has_worker": True,
                        }
                    ],
                },
                "workshops": [
                    {
                        "id": 1,
                        "subtype": "Carpenters",
                        "pos": [98, 96, 177],
                        "built": True,
                        "stage": 3,
                        "max_stage": 3,
                        "queued_jobs": 0,
                    }
                ],
                "rect_tiles": {
                    "rect": [100, 90, 177, 106, 96, 177],
                    "wall": 3,
                    "floor": 20,
                    "shrub_or_other": 9,
                    "designated": 0,
                },
            },
        },
        screen_text="main map",
    )

    assert (
        "Crew: 7 citizens, 6 idle; labors: mining=1, carpentry=2, woodcutting=1, "
        "masonry=0, herbalism=0" in text
    )
    assert (
        "Jobs: total=1 (dig=0, construct_building=0, workshop_tasks=0, suspended=0); "
        "sample: Fish@(165,132,177)" in text
    )
    assert (
        "Workshop id=1 Carpenters at (98,96,177): construction COMPLETE "
        "(stage 3/3), queued_jobs=0" in text
    )
    assert "ORDER can queue jobs to any built carpenter workshop." in text
    assert (
        "Plan-area tiles: wall=3 (diggable), floor=20, shrub/other=9 "
        "(not diggable — DIG designations on non-wall tiles are silently dropped "
        "by DF), designated=0" in text
    )


def test_encoder_flags_stalled_workshop_construction() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "crew": {
                "ok": True,
                "jobs": {
                    "total": 0,
                    "dig": 0,
                    "construct_building": 0,
                    "workshop_task": 0,
                    "suspended": 0,
                },
                "workshops": [
                    {
                        "id": 2,
                        "subtype": "Carpenters",
                        "pos": [98, 96, 177],
                        "built": False,
                        "stage": 1,
                        "max_stage": 3,
                        "queued_jobs": 0,
                    }
                ],
            },
        },
        screen_text="main map",
    )

    assert (
        "Workshop id=2 Carpenters at (98,96,177): UNDER CONSTRUCTION "
        "(stage 1/3), queued_jobs=0" in text
    )
    assert "no construct job exists; construction is stalled" in text


def test_encoder_ignores_malformed_or_disabled_crew_without_crashing() -> None:
    text_disabled, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "crew": {"ok": False},
        },
        screen_text="main map",
    )
    assert "Crew:" not in text_disabled

    text_junk, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "crew": "junk",
        },
        screen_text="main map",
    )
    assert "Crew:" not in text_junk

    text_missing_subkeys, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
            "crew": {"ok": True},
        },
        screen_text="main map",
    )
    assert "Crew:" not in text_missing_subkeys
    assert "Jobs:" not in text_missing_subkeys
    assert "Workshop id=" not in text_missing_subkeys
    assert "Plan-area tiles:" not in text_missing_subkeys


def test_encoder_surfaces_finished_goods_counts() -> None:
    state = {
        "time": 100,
        "population": 7,
        "stocks": {"food": 40, "drink": 50},
        "crew": {
            "ok": True,
            "goods": {"bed": 3, "door": 0, "table": 1, "chair": 0, "barrel": 12, "bin": 0, "wood": 250},
        },
    }

    obs_text, _ = encode_observation(state)

    assert "Finished goods in play: " in obs_text
    assert "beds=3" in obs_text
    assert "tables=1" in obs_text
    assert "wood_logs=250" in obs_text


def test_encoder_ignores_malformed_goods() -> None:
    state = {
        "time": 100,
        "population": 7,
        "stocks": {},
        "crew": {"ok": True, "goods": {"bed": "junk"}},
    }

    obs_text, _ = encode_observation(state)

    assert "Finished goods in play" not in obs_text


def test_encoder_surfaces_placed_furniture_buildings() -> None:
    state = {
        "time": 100,
        "population": 7,
        "stocks": {},
        "crew": {
            "ok": True,
            "placed_furniture": {"bed": 2, "door": 0, "table": 1, "chair": 0},
        },
    }

    obs_text, _ = encode_observation(state)

    assert "Placed furniture buildings: beds=2, doors=0, tables=1, chairs=0" in obs_text


def test_encoder_surfaces_full_fort_block() -> None:
    state = {
        "time": 100,
        "population": 7,
        "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
        "fort": {
            "ok": True,
            "enclosed_spaces": 1,
            "functional_rooms": 1,
            "constructions": 26,
            "player_buildings": 8,
            "spaces": [
                {
                    "z": 177,
                    "tiles": 6,
                    "kind": "production",
                    "contents": {"bed": 0, "table": 0, "chair": 0, "door": 0, "workshop": 1},
                }
            ],
        },
    }

    text, _ = encode_observation(state, screen_text="main map")

    assert (
        "Fort structure (plan-agnostic): enclosed_spaces=1, functional_rooms=1, "
        "constructions=26" in text
    )
    assert "Rooms: production(6 tiles, z177)" in text
    assert "No enclosed rooms yet" not in text


def test_encoder_flags_zero_enclosed_spaces() -> None:
    state = {
        "time": 100,
        "population": 7,
        "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
        "fort": {
            "ok": True,
            "enclosed_spaces": 0,
            "functional_rooms": 0,
            "constructions": 4,
            "player_buildings": 1,
            "spaces": [],
        },
    }

    text, _ = encode_observation(state, screen_text="main map")

    assert "Fort structure (plan-agnostic): enclosed_spaces=0" in text
    assert (
        "No enclosed rooms yet — spaces count as rooms only when fully bounded "
        "by walls, buildings, or doors. BUILD kind=Wall can enclose them." in text
    )
    assert "Rooms:" not in text


def test_encoder_ignores_malformed_fort_without_crashing() -> None:
    state = {
        "time": 100,
        "population": 7,
        "stocks": {"food": 45, "drink": 60, "wood": 6, "stone": 0},
        "fort": "junk",
    }

    text, _ = encode_observation(state, screen_text="main map")

    assert "Fort structure" not in text


def test_encoder_surfaces_executor_why_as_rejection_reason() -> None:
    state = {"time": 100, "population": 7, "stocks": {}}

    obs_text, _ = encode_observation(
        state,
        last_action_result={"accepted": False, "why": "outside_work_rect"},
    )

    assert "Last Action: REJECTED - outside_work_rect" in obs_text

    obs_text, _ = encode_observation(
        state,
        last_action_result={"accepted": False, "result": {"ok": False, "error": "no_building_material"}},
    )

    assert "Last Action: REJECTED - no_building_material" in obs_text
