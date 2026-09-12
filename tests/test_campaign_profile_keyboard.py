"""Describe native keyboard attempts without claiming task completion or rescue."""

from copy import deepcopy
import json

import pytest

from tests.test_campaign_profile import profile, row


@pytest.mark.parametrize("accepted,outcome", [(True, "accepted"), (False, "rejected"), (None, "unknown")])
def test_native_keyboard_is_a_known_action_type_with_independent_execution_outcome(accepted, outcome):
    record = row(kind="KEYSTROKE", accepted=accepted, end=0)
    record["action"].update(
        params={"keys": ["SELECT"]},
        intent="private-intent",
        memory_update="private-memory",
    )
    original = deepcopy(record)
    result = profile([record])
    assert result["actions"]["by_type"] == {
        "KEYSTROKE": {key: int(key == outcome) for key in ("accepted", "rejected", "unknown")}
    }
    assert result["actions"][outcome] == 1
    assert result["progress"]["elapsed_ticks"] == 0
    assert result["functioning_fortress"] == result["autonomous_gameplay"] == "not_assessed"
    assert result["flow_measurement"]["production"] is None
    assert record == original
    encoded = json.dumps(result)
    assert "private-" not in encoded and "SELECT" not in encoded


def test_unknown_control_kinds_remain_unknown_and_are_not_promoted_to_keyboard():
    result = profile([row(kind="unsupported-input")])
    assert result["actions"]["by_type"] == {
        "UNKNOWN": {"accepted": 1, "rejected": 0, "unknown": 0}
    }


def test_screen_only_native_observation_does_not_invent_initial_fortress_metrics():
    record = row(kind="KEYSTROKE")
    record["observation"] = {
        "observation_profile": "native_screen_text/v1",
        "screen_capture": {"private-screen": "Food: 999"},
    }
    result = profile([record])
    assert result["metrics"]["population"]["start"] is None
    assert result["metrics"]["food_stock"]["start"] is None
    assert result["metrics"]["population"]["end"] == 7
    assert result["actions"]["by_type"]["KEYSTROKE"]["accepted"] == 1
    assert "private-screen" not in json.dumps(result)
