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


def test_encoder_shows_material_phase_after_enough_ui_excavation_without_materials() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 0, "stone": 0},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "successful_targets": 2,
            },
        },
        screen_text="screen",
    )

    assert "Live UI run progress: total_work_delta=12" in text
    assert "building material is missing" in text
    assert "material target recommended keys" in text


def test_encoder_shows_build_phase_after_material_exists() -> None:
    text, _ = encode_observation(
        {
            "time": 100,
            "population": 7,
            "stocks": {"food": 45, "drink": 60, "wood": 0, "stone": 1},
            "ui_run_progress": {
                "total_work_delta": 12,
                "total_excavation_delta": 10,
                "successful_targets": 2,
            },
        },
        screen_text="screen",
    )

    assert "enough starter digging and building material exist" in text
    assert "try D_BUILDING" in text


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
