"""The post-restart experiment continues the verified branch without another loss."""
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_config import load_window


def test_postrestart_window_preserves_condition_and_does_not_repeat_restart():
    root = Path(__file__).resolve().parents[1]
    condition, window = load_window(
        root / "experiments/campaign_astra_keyboard_20260907.json",
        root / "experiments/campaign_astra_keyboard_window_20260908q.json",
    )
    parent = read(root / "experiments/evidence/astra_native_keyboard_presave_restart_20260908.json")
    assert window["continuation_from_next_step"] == parent["progress"]["checkpoint_cursor"] == 647
    assert window["snapshot_profile"] == parent["snapshot_profile"] == "native_menu_preserving_save/v4"
    assert window["steps_per_segment"] == 64 and window["max_segments"] == 1
    assert "restart" not in window and "budget_extension" not in window
    assert window["reset_memory"] is window["reset_usage"] is window["strategy_intervention"] is False
    assert condition["model"] == "gpt-6-astra" and condition["reasoning_effort"] == "medium"
    assert condition["screen_size"] == [120, 40]
    assert condition["control_profile"] == "native_keyboard/v2"
    assert window["private_measurement_profile"] == "fortgym.campaign-food-measurement/v1"
