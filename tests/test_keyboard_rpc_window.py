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
