"""A replay must show rejected choices without pretending they reached the game."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.export_displayed_key_recording import recorded_action


@pytest.fixture
def rejected():
    action = {
        "type": "KEYSTROKE",
        "params": {"keys": ["SYM:0:>"]},
        "intent": "Inspect",
        "advance_ticks": 0,
        "memory_update": "private",
    }
    result = {"action": None}
    row = {
        "action": deepcopy(action),
        "record_origin": "model_input_rejection/v1",
        "execute": {
            "accepted": False,
            "validation_rejected": True,
            "result": {
                "native_action_dispatched": False,
                "command_mutation": "not_attempted",
                "keys_sent": 0,
                "keys_confirmed": 0,
            },
        },
        "tick_advance": {
            "ticks_advanced": 0,
            "clock_dispatched": False,
            "start_year": 30,
            "end_year": 30,
            "start_tick": 16801,
            "end_tick": 16801,
        },
        "state_after_advance": {"year": 30, "year_tick": 16801},
    }
    calls = []

    def receipt_action(request, response):
        calls.append((request, response))
        return action

    return SimpleNamespace(receipt_action=receipt_action), {}, result, row, calls


def test_retained_rejection_is_reconstructed_by_pinned_parser(rejected):
    watch, request, result, row, calls = rejected
    original = deepcopy(row)
    assert recorded_action(watch, request, result, row) == row["action"]
    assert calls == [(request, result)]
    assert row == original and row["execute"]["accepted"] is False


@pytest.mark.parametrize(
    "path,value",
    [
        (("action", "memory_update"), "altered"),
        (("record_origin",), "accepted"),
        (("execute", "accepted"), True),
        (("execute", "validation_rejected"), False),
        (("execute", "result", "native_action_dispatched"), True),
        (("execute", "result", "command_mutation"), "completed"),
        (("execute", "result", "keys_sent"), 1),
        (("execute", "result", "keys_confirmed"), False),
        (("tick_advance", "ticks_advanced"), False),
        (("tick_advance", "clock_dispatched"), True),
        (("tick_advance", "end_year"), 31),
        (("tick_advance", "end_tick"), 16802),
    ],
)
def test_changed_rejected_trace_cannot_be_published(rejected, path, value):
    watch, request, result, row, _ = rejected
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        recorded_action(watch, request, result, row)


def test_provider_rejection_validation_cannot_be_bypassed(rejected):
    _, request, result, row, _ = rejected

    def invalid(*_):
        raise ValueError("invalid typed receipt")

    with pytest.raises(ValueError, match="invalid typed receipt"):
        recorded_action(SimpleNamespace(receipt_action=invalid), request, result, row)


def test_valid_accepted_choice_keeps_its_native_acceptance(rejected):
    watch, request, result, row, _ = rejected
    result["action"] = deepcopy(row["action"])
    row["execute"]["accepted"] = True
    assert recorded_action(watch, request, result, row) == result["action"]
    row["execute"]["accepted"] = False
    with pytest.raises(ValueError, match="accepted native record"):
        recorded_action(watch, request, result, row)
