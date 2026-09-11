"""Declaration keeps the native experiment fixed and exposes the partial loss."""

from fort_gym.bench.run.keyboard_config import load_window
from fort_gym.bench.run.keyboard_partial_restart import PARTIAL_KIND
from tests.test_keyboard_runtime import PROJECT


def test_partial_restart_changes_only_restart_identity_and_clock_implementation():
    condition = PROJECT / "experiments/campaign_astra_keyboard_20260907.json"
    old_condition, old = load_window(
        condition, PROJECT / "experiments/campaign_astra_keyboard_window_20260908r.json"
    )
    new_condition, new = load_window(
        condition, PROJECT / "experiments/campaign_astra_keyboard_window_20260908s.json"
    )
    assert new_condition == old_condition
    for key in (
        "continuation_from_next_step",
        "steps_per_segment",
        "max_segments",
        "snapshot_profile",
        "private_measurement_profile",
        "reset_memory",
        "reset_usage",
        "strategy_intervention",
    ):
        assert new[key] == old[key]
    assert new["restart"]["failure_kind"] == PARTIAL_KIND
    assert new["restart"]["restored_next_step"] == 711
    assert new["restart"]["lost_trace_next_step"] == 733
    assert new["steps_per_segment"] == 64 and new["max_segments"] == 1
    assert "budget_extension" not in new
