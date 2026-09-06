from copy import deepcopy

import pytest

from fort_gym.bench.env import dfhack_client as module
from fort_gym.bench.env.state_reader import StateReader


@pytest.fixture
def native_client(monkeypatch):
    client = module.DFHackClient()
    monkeypatch.setattr(client, "_ensure_connection", lambda: None)
    monkeypatch.setattr(module, "read_work_metrics", lambda *args, **kwargs: {"ok": True})
    return client


@pytest.mark.parametrize("field", ["empty", "population", "food", "drink", "wood", "stone"])
def test_campaign_cannot_turn_missing_native_counts_into_zero(native_client, monkeypatch, field):
    state = {"population": 7, "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0}}
    if field == "empty":
        state = {}
    elif field == "population":
        del state[field]
    else:
        del state["stocks"][field]
    monkeypatch.setattr(module, "cli_read_game_state", lambda: deepcopy(state))
    with pytest.raises(RuntimeError, match="observation is unavailable"):
        StateReader.from_dfhack(native_client, require_native=True)


@pytest.mark.parametrize("value", [None, True, False, "7", -1, 7.5])
def test_campaign_rejects_non_native_population_counts(native_client, monkeypatch, value):
    monkeypatch.setattr(
        module,
        "cli_read_game_state",
        lambda: {"population": value, "stocks": {"food": 1, "drink": 1, "wood": 1, "stone": 1}},
    )
    with pytest.raises(RuntimeError, match="observation is unavailable"):
        native_client.get_state(require_native=True)


def test_real_observed_zero_is_allowed_and_legacy_fallback_is_unchanged(native_client, monkeypatch):
    monkeypatch.setattr(module, "cli_read_game_state", lambda: {})
    assert native_client.get_state()["population"] == 0
    monkeypatch.setattr(
        module,
        "cli_read_game_state",
        lambda: {"population": 0, "stocks": {"food": 0, "drink": 0, "wood": 0, "stone": 0}},
    )
    state = StateReader.from_dfhack(native_client, require_native=True)
    assert state["population"] == 0 and state["stocks"]["food"] == 0
