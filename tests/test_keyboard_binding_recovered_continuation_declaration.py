"""Declaration only: this does not claim that the next window ran."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_recovered_origin_retains_different_trace_and_usage_counters():
    window = json.loads((ROOT / "experiments/keyboard_binding_continuation_20260911/window-256-416.json").read_text())
    prior = json.loads((ROOT / "experiments/evidence/keyboard_binding_astra_r1_recovery_224_256_20260911.json").read_text())
    assert window["continuation_checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert window["continuation_from_next_step"] == prior["next_step"] == 256
    assert window["accounted_responses_before_window"] == prior["total_responses"] == 288
    assert window["returned_tokens_before_window"] == prior["total_tokens"] == 7735275
    assert window["saved_elapsed_ticks_before_window"] == prior["saved_elapsed_ticks"] == 229845
    loss = prior["discontinuity"]
    assert window["inherited_lost_decisions"] == loss["lost_trace_next_step"] - loss["restored_next_step"] == 32
    assert window["inherited_lost_elapsed_ticks"] == loss["lost_elapsed_ticks"] == 422
    assert window["source_native_revision"] == prior["source_revision"]


def test_ordinary_continuation_does_not_restart_or_change_conditions():
    folder = ROOT / "experiments/keyboard_binding_continuation_20260911"
    prior = json.loads((folder / "window-96-256.json").read_text())
    window = json.loads((folder / "window-256-416.json").read_text())
    assert window["steps_per_segment"] == 32 and window["max_segments"] == 5
    assert window["window_end_decision"] == window["continuation_from_next_step"] + 160 == 416
    for key in ("condition_id", "original_condition", "snapshot_profile", "runtime_rpc_transport",
                "private_measurement_profile", "private_measurement_timeout_seconds",
                "resource_observation_profile"):
        assert window[key] == prior[key]
    assert all(window[key] is False for key in ("reset_memory", "reset_usage", "strategy_intervention"))
    assert not {"restart", "prompt_change", "budget_extension"} & window.keys()
    assert window["audit_revision"] == "bb8516aa6a27d6ba92bee39f9769adcfb7095d6c"
