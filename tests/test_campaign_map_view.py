"""Campaign VIEW grammar, native-adapter plumbing and receipt validation."""

from copy import deepcopy

import pytest

from fort_gym.bench.env.actions import parse_action
from fort_gym.bench.env.campaign_view import (
    MAP_SCHEMA,
    parse_campaign_action,
    validate_map_read,
    view_selection,
)
from fort_gym.bench.run import campaign_environment as native

SELECTION = {"origin": [40, 27, 18], "size": [3, 2]}
STATE = {"year": 30, "year_tick": 212801, "pause_state": True}


def receipt(selection=SELECTION, state=STATE):
    result = {
        "schema_version": MAP_SCHEMA,
        "ok": True,
        "active": selection is not None,
        "scope": "visible_terrain_only",
        "map_dimensions": [64, 48, 20],
        "year": state["year"],
        "year_tick": state["year_tick"],
        "paused": True,
    }
    if selection is not None:
        width, height = selection["size"]
        result.update(
            map_origin=list(selection["origin"]),
            map_size=list(selection["size"]),
            map_rows=["." * width] * height,
            visible_tiles=width * height,
            hidden_tiles=0,
            unreadable_tiles=0,
            scan_complete=True,
        )
    return result


def action(params=SELECTION, ticks=0):
    return {"type": "VIEW", "params": deepcopy(params), "advance_ticks": ticks}


def test_view_is_opt_in_without_expanding_historical_action_parser():
    with pytest.raises(ValueError):
        parse_action(action())
    with pytest.raises(ValueError, match="declared interface"):
        parse_campaign_action(action(), max_advance_ticks=2500, allow_view=False)
    selected = parse_campaign_action(action(), max_advance_ticks=2500, allow_view=True)
    assert selected == action()
    selected["params"]["origin"][0] = 1
    assert SELECTION["origin"][0] == 40
    old = {"type": "WAIT", "params": {}, "advance_ticks": 2500}
    assert parse_campaign_action(old, max_advance_ticks=2500, allow_view=True) == parse_action(
        old, max_advance_ticks=2500
    )


@pytest.mark.parametrize("ticks", [None, True, False, -1, 1, 2000, 0.0, "0"])
def test_view_cannot_request_simulation_time(ticks):
    with pytest.raises(ValueError, match="requires advance_ticks"):
        parse_campaign_action(action(ticks=ticks), max_advance_ticks=2500, allow_view=True)


@pytest.mark.parametrize(
    "params",
    [
        None,
        {},
        {"origin": [1, 2, 3]},
        {"origin": [1, 2, 3], "size": [1, 1], "extra": 1},
        {"origin": [1, 2], "size": [1, 1]},
        {"origin": [1, 2, -1], "size": [1, 1]},
        {"origin": [True, 2, 3], "size": [1, 1]},
        {"origin": [1.0, 2, 3], "size": [1, 1]},
        {"origin": ["1", 2, 3], "size": [1, 1]},
        {"origin": [1, 2, 3], "size": [0, 1]},
        {"origin": [1, 2, 3], "size": [35, 1]},
        {"origin": [1, 2, 3], "size": [1, True]},
        {"origin": [1, 2, 3], "size": [1, 1, 1]},
    ],
)
def test_bad_view_parameters_are_not_coerced_or_replaced(params):
    with pytest.raises(ValueError, match="VIEW"):
        view_selection(params)


def test_map_read_binds_the_exact_view_and_preserves_unknown_tiles():
    original = receipt()
    original.update(
        map_rows=[". .", "   "],
        visible_tiles=2,
        hidden_tiles=3,
        unreadable_tiles=1,
        scan_complete=False,
    )
    result = validate_map_read(original, SELECTION, STATE)
    assert result == original
    result["map_rows"][0] = "..."
    assert original["map_rows"][0] == ". ."
    assert validate_map_read(receipt(None), None, STATE)["active"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "unknown"},
        {"ok": "true"},
        {"scope": "all_hidden_terrain"},
        {"paused": False},
        {"year": 31},
        {"year_tick": 212802},
        {"map_dimensions": [64, 48, False]},
        {"map_origin": [41, 27, 18]},
        {"map_size": [2, 3]},
        {"map_rows": ["..."]},
        {"map_rows": ["...", "...."]},
        {"map_rows": ["@@@", "..."]},
        {"visible_tiles": True},
        {"visible_tiles": 5},
        {"unreadable_tiles": 1},
        {"scan_complete": False},
        {"active": False},
    ],
)
def test_mismatched_map_receipt_is_not_presented_as_the_requested_view(change):
    with pytest.raises(ValueError):
        validate_map_read({**receipt(), **change}, SELECTION, STATE)


def test_native_outside_map_feedback_is_not_a_fabricated_empty_view():
    failure = {"schema_version": MAP_SCHEMA, "ok": False, "error": "view_rectangle_outside_map"}
    assert validate_map_read(failure, SELECTION, STATE) == failure
    assert "map_rows" not in failure


@pytest.mark.parametrize("selection", [None, SELECTION])
def test_native_adapter_uses_only_the_read_only_hook(monkeypatch, selection):
    environment = native.NativeCampaignEnvironment.__new__(native.NativeCampaignEnvironment)
    calls = []
    environment._verify_runtime = lambda: calls.append("identity")

    def run(path, *args, **kwargs):
        assert path.endswith("campaign_map_view_v1.lua")
        assert args == (() if selection is None else ("40", "27", "18", "3", "2"))
        assert kwargs == {"timeout": 5.0}
        calls.append("map-read")
        return receipt(selection)

    monkeypatch.setattr(native, "run_lua_file", run)
    assert environment.inspect_map(selection) == receipt(selection)
    assert calls == ["identity", "map-read"]


def test_native_reader_error_remains_unknown_without_changing_selection(monkeypatch):
    environment = native.NativeCampaignEnvironment.__new__(native.NativeCampaignEnvironment)
    environment._verify_runtime = lambda: None
    monkeypatch.setattr(
        native, "run_lua_file", lambda *a, **k: (_ for _ in ()).throw(native.DFHackError("test"))
    )
    before = deepcopy(SELECTION)
    assert environment.inspect_map(SELECTION) == {
        "schema_version": MAP_SCHEMA,
        "ok": False,
        "error": "test",
    }
    assert SELECTION == before
