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
    assert "try D_BUILDING" not in text


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
    assert "do not move the placement cursor" in text
    assert "D_BUILDING, HOTKEY_BUILDING_WORKSHOP" in text


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
