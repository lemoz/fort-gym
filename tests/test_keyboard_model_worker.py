"""Native worker wiring with fake environment and exchange, never a game process."""

from types import SimpleNamespace

import pytest

from scripts import campaign_keyboard_native as native
from tests.test_keyboard_model_selection import condition
from tests.test_keyboard_runtime import CONDITION
from tests.test_keyboard_prompt import condition as prompt_condition
from tests.test_keyboard_binding_profile import condition as binding_condition
from tests.test_selected_workshop_profile import condition as workshop_condition


@pytest.mark.parametrize("selected", [
    CONDITION, condition("gpt-6-astra"), condition("gpt-5.6-sol"), condition("gpt-5.6-terra"),
    prompt_condition(), binding_condition(), workshop_condition(),
])
@pytest.mark.parametrize("fresh", [False, True], ids=["continuation", "fresh"])
def test_worker_binds_declared_selection_into_agent_and_exchange(tmp_path, monkeypatch, selected, fresh):
    closed, exchanges = [], []
    window = {"steps_per_segment": 1, "source_snapshot_receipt_sha256": "a" * 64}
    monkeypatch.setattr(native, "load_window", lambda *args: (selected, window))
    monkeypatch.setattr("fort_gym.bench.run.keyboard_trial_config.load_trial",
                        lambda *args: (selected, window))
    monkeypatch.setattr(native, "NativeCampaignEnvironment", lambda **kwargs: SimpleNamespace(
        close=lambda: closed.append(True),
    ))
    monkeypatch.setattr(native, "NativeSaveSnapshotter", lambda **kwargs: None)

    def exchange(*args, **kwargs):
        exchanges.append((args, kwargs))
        return {"offline": True}

    def segment(**kwargs):
        agent = kwargs["agent"]
        assert agent.configuration["model"] == selected["model"]
        assert agent.configuration["reasoning_effort"] == selected["reasoning_effort"]
        return agent.decision({"screen": "fixture"}, "memory", None)

    monkeypatch.setattr(native, "exchange_decision", exchange)
    monkeypatch.setattr(native, "run_keyboard_segment", segment)
    monkeypatch.setattr("fort_gym.bench.run.keyboard_trial.run_keyboard_trial", segment)
    monkeypatch.setattr(native, "read", lambda path: {})
    args = SimpleNamespace(
        condition=tmp_path / "condition", window=tmp_path / "window", runtime=tmp_path,
        exchange=tmp_path, output=tmp_path, checkpoint=tmp_path, latest_usage=tmp_path,
        cursor=1, revision="offline", extend_budget=False,
        trial=tmp_path / "trial" if fresh else None,
        campaign_id="offline", loaded_boundary=tmp_path / "loaded",
    )
    assert native.worker(args) == {"offline": True}
    assert closed == [True] and len(exchanges) == 1
    _, options = exchanges[0]
    assert options["max_advance_ticks"] == selected["max_advance_ticks"]
    assert options["timeout_seconds"] == selected["exchange_timeout_seconds"]
    if selected["schema_version"] != "fortgym.codex-keyboard-condition/v1":
        assert options["model"] == selected["model"]
        assert options["reasoning_effort"] == selected["reasoning_effort"]
        if "prompt_profile" in selected:
            assert options["prompt_profile"] == selected["prompt_profile"]
    else:
        assert "model" not in options and "reasoning_effort" not in options
