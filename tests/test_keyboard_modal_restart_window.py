"""The modal restart preserves the original experiment and retains its usage."""

from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.keyboard_exchange import publish
from fort_gym.bench.run.keyboard_config import load_window
from fort_gym.bench.run.keyboard_modal_restart import MODAL_KIND
from tests.test_keyboard_modal_restart import modal as modal
from tests.test_keyboard_runtime import PROJECT, saved as saved
from tests.test_keyboard_prompt import condition


def test_modal_restart_changes_only_failure_and_runtime_implementation():
    config = PROJECT / "experiments/campaign_astra_keyboard_memory_contract_20260909.json"
    before, old = load_window(
        config, PROJECT / "experiments/campaign_astra_keyboard_window_20260909u.json"
    )
    after, new = load_window(
        config, PROJECT / "experiments/campaign_astra_keyboard_window_20260909v.json"
    )
    assert before == after
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
        assert old[key] == new[key]
    assert new["restart"]["failure_kind"] == MODAL_KIND
    assert new["restart"]["restored_next_step"] == 775
    assert new["restart"]["lost_trace_next_step"] == 792
    assert new["restart"]["source_revision"] == "52ed94a5c22f84cd25ed1d7f6015c9ee8f82084d"
    assert "prompt_change" not in new and "budget_extension" not in new


@pytest.mark.parametrize("matching_profile", [True, False])
def test_outer_preflight_uses_retained_profile_before_runtime(
    tmp_path, modal, monkeypatch, matching_profile
):
    from scripts import campaign_keyboard_native as native
    from tests.test_keyboard_runtime import CONDITION

    checkpoint, source, declaration = modal
    config_path, window_path = tmp_path / "condition.json", tmp_path / "window.json"
    publish(config_path, condition() if matching_profile else CONDITION)
    publish(
        window_path,
        {
            "schema_version": "fortgym.codex-keyboard-window/v1",
            "condition_id": "test",
            "original_condition": config_path.name,
            "continuation_from_next_step": 1,
            "steps_per_segment": 1,
            "max_segments": 1,
            "reset_memory": False,
            "reset_usage": False,
            "strategy_intervention": False,
            "restart": declaration,
        },
    )
    args = SimpleNamespace(
        condition=config_path,
        window=window_path,
        checkpoint=checkpoint,
        latest_usage=source / "segment-0/loop/usage.jsonl",
        restart_source=source,
        port=5530,
        output=tmp_path / "output",
        source=tmp_path / "assets",
        revision="b" * 40,
    )
    calls = []

    class RuntimeBoundary(Exception):
        pass

    def stop_before_runtime(**kwargs):
        calls.append(kwargs)
        raise RuntimeBoundary("No native game or model is started by this test")

    monkeypatch.setattr(native, "run_isolated", stop_before_runtime)
    if matching_profile:
        result = native.run_window(args)
        assert result["status"] == "failed" and result["error_type"] == "RuntimeBoundary"
        assert result["original_checkpoint_unchanged"] is True
        assert len(calls) == 1
    else:
        with pytest.raises(ValueError, match="Prompt profile differs"):
            native.run_window(args)
        assert calls == [] and not args.output.exists()
