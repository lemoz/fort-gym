"""A finite continuation can cross the anniversary without resetting history."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from fort_gym.bench.agent.campaign_budget import effective_budget
from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent
from fort_gym.bench.agent.codex_allowance import evaluate_allowance
from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_config import load_window
from tests.test_codex_allowance import account, limits

ROOT = Path(__file__).resolve().parents[1]
CONDITION = ROOT / "experiments/campaign_astra_keyboard_included_headroom_20260910.json"
WINDOW = ROOT / "experiments/campaign_astra_keyboard_window_20260910ab.json"
CHECKPOINT = "0875aab1e7f43fbdacc182902c2ffe96652de014e4cb8c47dbb18b8b3f42baa4"


def test_year_two_window_preserves_condition_and_extends_only_dispatch_budget():
    condition, window = load_window(CONDITION, WINDOW)
    previous_condition, previous = load_window(
        CONDITION, ROOT / "experiments/campaign_astra_keyboard_window_20260910aa.json")
    assert condition == previous_condition
    for key in ("snapshot_profile", "private_measurement_profile", "private_measurement_timeout_seconds",
                "runtime_rpc_transport", "resource_observation_profile", "host_read_policy",
                "container_init_required", "reset_memory", "reset_usage", "strategy_intervention"):
        assert window[key] == previous[key]
    assert window["continuation_from_next_step"] == 929
    assert window["continuation_checkpoint_sha256"] == CHECKPOINT
    assert (window["steps_per_segment"], window["max_segments"]) == (32, 4)
    assert not {"restart", "prompt_change", "admission_policy_change"} & window.keys()
    assert window["budget_extension"] == {"max_dispatches": 1280, "max_total_tokens": 40000000}
    assert condition["max_dispatches"] == 8  # The historical base must not be rewritten.
    assert condition["maximum_included_usage_percent"] == 98
    assert "budget_extension" not in previous
    original = read(ROOT / "experiments/evidence/astra_native_keyboard_paused_window_20260910aa.json")
    assert original["status"] == "paused" and original["checkpoint_sha256"] == CHECKPOINT
    progress = original["progress"]
    remaining = 403200 - progress["saved_elapsed_ticks"]
    assert remaining == 110618
    assert (1152 - progress["cumulative_model_responses"]) * condition["max_advance_ticks"] < remaining
    decisions = window["steps_per_segment"] * window["max_segments"]
    assert decisions == 128 and decisions * condition["max_advance_ticks"] >= remaining
    assert progress["cumulative_model_responses"] + decisions == 1239 <= 1280
    assert original["usage"]["campaign_tokens"] < window["budget_extension"]["max_total_tokens"]


def test_append_only_extension_keeps_original_state_and_survives_restore():
    condition, window = load_window(CONDITION, WINDOW)

    def create():
        return CodexKeyboardAgent(decision=lambda *args: pytest.fail("No model call in this fixture"), **{
            key: condition[key] for key in (
                "max_dispatches", "max_total_tokens", "max_advance_ticks", "model", "reasoning_effort")})

    agent = create()
    agent.set_campaign_context(campaign_id="year-two-extension-fixture")
    agent.extend_budget(checkpoint_sha256="a" * 64, max_dispatches=1152, max_total_tokens=40000000)
    agent.memory = "fixture memory retained"
    before = agent.export_campaign_state()
    extension = agent.extend_budget(checkpoint_sha256=CHECKPOINT, **window["budget_extension"])
    after = agent.export_campaign_state()
    assert extension["previous"] == {"max_dispatches": 1152, "max_total_tokens": 40000000}
    assert after["budget_extensions"] == [*before["budget_extensions"], extension]
    assert {k: v for k, v in after.items() if k != "budget_extensions"} == {
        k: v for k, v in before.items() if k != "budget_extensions"}
    restored = create()
    restored.restore_campaign_state(after, campaign_id=after["campaign_id"])
    assert restored.export_campaign_state() == after
    assert effective_budget(restored.configuration, restored.budget_extensions, restored.usage) == window["budget_extension"]
    with pytest.raises(ValueError, match="lineage"):
        restored.extend_budget(checkpoint_sha256=CHECKPOINT, max_dispatches=1408, max_total_tokens=40000000)
    assert restored.export_campaign_state() == after


@pytest.mark.parametrize("used,allowed", [(97, True), (98, False), (100, False)])
def test_larger_gameplay_budget_does_not_bypass_account_admission(used, allowed):
    condition, _ = load_window(CONDITION, WINDOW)
    value = deepcopy(limits())
    value["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = used
    assert evaluate_allowance(account(), value, now=1000,
        maximum_used_percent=condition["maximum_included_usage_percent"])["allowed"] is allowed


@pytest.mark.parametrize("value", [None, False, 929, "", "a" * 63, "A" * 64, "g" * 64, {}])
def test_invalid_checkpoint_pin_fails_during_configuration_load(tmp_path, value):
    from fort_gym.bench.agent.keyboard_exchange import publish

    window = read(WINDOW)
    window["continuation_checkpoint_sha256"] = value
    path = tmp_path / "window.json"
    publish(path, window)
    with pytest.raises(ValueError, match="continuation checkpoint digest"):
        load_window(CONDITION, path)


def test_another_checkpoint_at_the_same_cursor_is_rejected_before_launch(tmp_path, monkeypatch):
    from scripts import campaign_keyboard_native as native

    monkeypatch.setattr(native, "verify_checkpoint", lambda path: {
        "sha256": "b" * 64, "payload": {"next_step": 929}})
    args = SimpleNamespace(condition=CONDITION, window=WINDOW, checkpoint=tmp_path / "other",
                           output=tmp_path / "not-created", port=5583)
    with pytest.raises(ValueError, match="declared continuation digest"):
        native.run_window(args)
    assert not args.output.exists()
