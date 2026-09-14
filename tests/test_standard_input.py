from copy import deepcopy

import pytest

from fort_gym.bench.agent.standard_input import (
    CONTROL_PROFILE,
    OBSERVATION_PROFILE,
    parse_response,
    response_schema,
    screen_observation,
)


def action():
    return {
        "type": "KEYSTROKE",
        "params": {"keys": ["D_BUILDJOB", "BUILDJOB_ADD", "STRING_A098"]},
        "advance_ticks": 0,
        "intent": "Add a job through the workshop menu",
        "memory_update": "",
    }


def test_contract_exposes_native_keys_without_shortcuts():
    schema = response_schema(max_advance_ticks=2000)
    assert CONTROL_PROFILE == "native_keyboard/v1"
    assert schema["properties"]["type"]["enum"] == ["KEYSTROKE"]
    keys = schema["properties"]["params"]["properties"]["keys"]["items"]["enum"]
    assert {"BUILDJOB_ADD", "D_STOCKPILES", "D_SQUADS", "ZOOM_IN"} <= set(keys)
    assert schema["additionalProperties"] is False


def test_roundtrip_preserves_chosen_keys_and_optional_empty_notes():
    payload = action()
    result = parse_response(payload, max_advance_ticks=2000)
    assert result == payload
    result["params"]["keys"].append("SELECT")
    assert result != payload


@pytest.mark.parametrize("kind", ["BUILD", "ORDER", "DIG", "VIEW", "INTERACT", "WAIT"])
def test_no_implicit_shortcut_or_wait_fallback(kind):
    payload = action()
    payload["type"] = kind
    with pytest.raises(ValueError):
        parse_response(payload, max_advance_ticks=2000)


@pytest.mark.parametrize("ticks", [True, 1.0, -1, 2001, "1", None])
def test_tick_bounds_are_not_coerced(ticks):
    payload = action()
    payload["advance_ticks"] = ticks
    with pytest.raises(ValueError):
        parse_response(payload, max_advance_ticks=2000)


@pytest.mark.parametrize("keys", [["not_a_key"], [None], [["SELECT"]], "SELECT", ["SELECT"] * 101])
def test_invalid_keys_are_not_partially_executed(keys):
    payload = action()
    payload["params"]["keys"] = keys
    with pytest.raises(ValueError):
        parse_response(payload, max_advance_ticks=2000)


def test_empty_keys_are_explicit_advance_only_choice():
    payload = action()
    payload.update(params={"keys": []}, advance_ticks=2000)
    assert parse_response(payload, max_advance_ticks=2000) == payload


@pytest.mark.parametrize("mutation", ["extra_root", "extra_params", "missing_note", "invalid_note"])
def test_response_contract_is_exact(mutation):
    payload = action()
    if mutation == "extra_root":
        payload["shortcut"] = "ORDER"
    elif mutation == "extra_params":
        payload["params"]["job"] = "bed"
    elif mutation == "missing_note":
        del payload["memory_update"]
    else:
        payload["intent"] = None
    with pytest.raises(ValueError):
        parse_response(payload, max_advance_ticks=2000)


@pytest.mark.parametrize("dimensions", [(80, 25), (120, 40), (160, 50)])
def test_full_screen_grid_and_selection_colors_survive(dimensions):
    width, height = dimensions
    screen = {
        "width": width,
        "height": height,
        "tiles": [[32, 7, 0] for _ in range(width * height)],
    }
    screen["tiles"][-1] = [219, 15, 4]
    screen["internal_fort_metrics"] = {"secret": "not screen content"}
    original = deepcopy(screen)
    result = screen_observation(screen)
    assert result["observation_profile"] == OBSERVATION_PROFILE
    assert result["tile_order"] == "column_major"
    assert (result["width"], result["height"]) == dimensions
    assert result["tiles"][-1] == [219, 15, 4]
    assert "internal_fort_metrics" not in result
    result["tiles"][-1][0] = 0
    assert screen == original


@pytest.mark.parametrize(
    "screen",
    [
        None,
        {},
        {"width": True, "height": 1, "tiles": [[1, 1, 0]]},
        {"width": 2, "height": 1, "tiles": [[1, 1, 0]]},
        {"width": 1, "height": 1, "tiles": [[1, 1]]},
        {"width": 1, "height": 1, "tiles": [[1, None, 0]]},
    ],
)
def test_incomplete_screen_is_not_presented_as_valid(screen):
    with pytest.raises(ValueError):
        screen_observation(screen)
