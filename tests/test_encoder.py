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
