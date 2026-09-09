from pathlib import Path

import pytest

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.run.keyboard_config import load_window

PROJECT = Path(__file__).resolve().parents[1]
CONDITION = PROJECT / "experiments/campaign_astra_keyboard_memory_contract_20260909.json"
WINDOW = PROJECT / "experiments/campaign_astra_keyboard_window_20260909x.json"


def test_direct_rpc_window_preserves_gameplay_and_existing_budget():
    condition, window = load_window(CONDITION, WINDOW)
    assert window["runtime_rpc_transport"] == "native-rpc"
    assert window["resource_observation_profile"] == "fortgym.native-resource-observations/v1"
    assert window["container_init_required"] is True
    assert window["private_measurement_timeout_seconds"] == 15
    assert window["continuation_from_next_step"] == 807
    assert window["max_segments"] == 1 and window["steps_per_segment"] == 32
    assert "restart" not in window and "prompt_change" not in window
    assert "budget_extension" not in window
    assert condition["max_dispatches"] == 8  # Historical base remains unchanged.
    limits = read(PROJECT / "experiments/campaign_astra_keyboard_window_20260907d.json")["budget_extension"]
    assert limits == {"max_dispatches": 1024, "max_total_tokens": 40000000}
    assert 989 + 32 <= limits["max_dispatches"]


@pytest.mark.parametrize("field,value", [
    ("runtime_rpc_transport", None), ("runtime_rpc_transport", True),
    ("runtime_rpc_transport", {}), ("runtime_rpc_transport", "native-rpc-typo"),
    ("resource_observation_profile", True), ("resource_observation_profile", {}),
    ("resource_observation_profile", "typo"),
])
def test_invalid_runtime_protocol_is_rejected(tmp_path, field, value):
    data = read(WINDOW)
    data[field] = value
    path = tmp_path / "window.json"
    publish(path, data)
    with pytest.raises(ValueError, match="Unsupported declared"):
        load_window(CONDITION, path)


def test_two_segment_continuation_retains_gameplay_and_extends_only_dispatch_limit():
    condition, previous = load_window(CONDITION, WINDOW)
    same, following = load_window(
        CONDITION, PROJECT / "experiments/campaign_astra_keyboard_window_20260909y.json"
    )
    assert same == condition
    assert following["continuation_from_next_step"] == 839
    assert following["steps_per_segment"] == 32 and following["max_segments"] == 2
    for key in ("snapshot_profile", "private_measurement_profile", "private_measurement_timeout_seconds",
                "runtime_rpc_transport", "resource_observation_profile", "host_read_policy", "container_init_required",
                "reset_memory", "reset_usage", "strategy_intervention"):
        assert following[key] == previous[key]
    assert "restart" not in following and "prompt_change" not in following
    assert following["budget_extension"] == {"max_dispatches": 1152, "max_total_tokens": 40000000}
    assert 1021 + following["steps_per_segment"] * following["max_segments"] <= 1152
    assert condition["max_dispatches"] == 8


def test_new_allowance_is_append_only_without_resetting_usage():
    from copy import deepcopy
    from fort_gym.bench.agent.campaign_budget import effective_budget
    from fort_gym.bench.agent.campaign_keyboard import CodexKeyboardAgent

    condition, window = load_window(
        CONDITION, PROJECT / "experiments/campaign_astra_keyboard_window_20260909y.json"
    )
    agent = CodexKeyboardAgent(decision=lambda *args: None, **{
        key: condition[key] for key in ("max_dispatches", "max_total_tokens", "max_advance_ticks", "model", "reasoning_effort")
    })
    agent.set_campaign_context(campaign_id="extension-fixture")
    agent.extend_budget(checkpoint_sha256="a" * 64, max_dispatches=1024, max_total_tokens=40000000)
    prior = deepcopy(agent.budget_extensions)
    usage = deepcopy(agent.usage)
    agent.extend_budget(checkpoint_sha256="b" * 64, **window["budget_extension"])
    assert agent.budget_extensions[:-1] == prior
    assert agent.usage == usage
    assert effective_budget(agent.configuration, agent.budget_extensions, agent.usage) == window["budget_extension"]
