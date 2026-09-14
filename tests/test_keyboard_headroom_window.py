"""The new operating cutoff is explicit; historical conditions stay unchanged."""

from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.agent.codex_allowance import evaluate_allowance
from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_config import load_window
from tests.test_codex_allowance import account, limits

ROOT = Path(__file__).resolve().parents[1]
CONDITION = ROOT / "experiments/campaign_astra_keyboard_included_headroom_20260910.json"
WINDOW = ROOT / "experiments/campaign_astra_keyboard_window_20260910aa.json"


def test_headroom_change_preserves_gameplay_and_historical_condition():
    selected, window = load_window(CONDITION, WINDOW)
    prior = read(ROOT / "experiments/campaign_astra_keyboard_memory_contract_20260909.json")
    assert prior["maximum_included_usage_percent"] == 90
    expected = deepcopy(prior)
    expected.update(
        condition_id="astra-medium-native-keyboard-included-headroom-120x40",
        maximum_included_usage_percent=98,
    )
    assert selected == expected
    assert window["continuation_from_next_step"] == 903
    assert window["steps_per_segment"] == 32 and window["max_segments"] == 1
    assert all(window[key] is False for key in ("reset_memory", "reset_usage", "strategy_intervention"))
    assert not set(window) & {"budget_extension", "restart", "prompt_change"}
    assert 1085 + window["steps_per_segment"] * window["max_segments"] <= 1152
    change = window["admission_policy_change"]
    assert change["previous_maximum_included_usage_percent"] == 90
    assert change["maximum_included_usage_percent"] == 98
    sealed = read(ROOT / "experiments/campaign_astra_keyboard_window_20260910z.json")
    assert sealed["original_condition"] == "campaign_astra_keyboard_memory_contract_20260909.json"
    assert sealed["max_segments"] == 2


@pytest.mark.parametrize("used,allowed", [(89, True), (90, True), (96, True), (97, True), (98, False), (100, False)])
def test_new_cutoff_is_still_enforced_before_inference(used, allowed):
    selected, _ = load_window(CONDITION, WINDOW)
    value = limits()
    value["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = used
    actual = evaluate_allowance(
        account(), value, now=1000,
        maximum_used_percent=selected["maximum_included_usage_percent"],
    )
    assert actual["allowed"] is allowed
    assert actual["atomic_account_reservation"] is False
    assert actual["reported_charge_usd"] is None


@pytest.mark.parametrize("failure", ["provider", "stale", "missing", "secondary", "auth"])
def test_operating_change_cannot_override_provider_or_unknown_account_state(failure):
    identity, value = account(), limits()
    bucket = value["rateLimitsByLimitId"]["codex"]
    if failure == "provider":
        bucket["rateLimitReachedType"] = "weekly"
    elif failure == "stale":
        bucket["primary"]["resetsAt"] = 999
    elif failure == "missing":
        bucket["primary"] = None
    elif failure == "secondary":
        bucket["secondary"] = {**bucket["primary"], "usedPercent": 98}
    else:
        identity["account"]["type"] = "apiKey"
    assert evaluate_allowance(identity, value, now=1000, maximum_used_percent=98)["allowed"] is False
