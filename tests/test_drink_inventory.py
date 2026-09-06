"""Exercise the actual Lua scanner with engine doubles, plus Python plumbing."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from fort_gym.bench import dfhack_exec
from fort_gym.bench.drink_inventory import DRINK_INVENTORY_LUA
from fort_gym.bench.env.encoder import encode_observation
from fort_gym.bench.env.state_reader import StateReader

LUA = shutil.which("lua")
PRELUDE = """
local function item(units, flags, kind)
    return {stack_size=units, flags=flags or {},
        getType=function() return kind or 6 end}
end
"""


@pytest.mark.skipif(LUA is None, reason="Lua interpreter is unavailable")
@pytest.mark.parametrize(
    "scenario",
    [
        """
local r = read_drink_inventory({item(5), item(11), item(30), item(999, {}, 2)}, 6)
assert(r.complete and r.units == 46 and r.item_records == 3)
assert(r.scanned_units == 46 and r.excluded_records == 0)
""",
        """
local r = read_drink_inventory({}, 6)
assert(r.complete and r.units == 0 and r.item_records == 0)
""",
        """
local r = read_drink_inventory({item(0)}, 6)
assert(r.complete and r.units == 0 and r.item_records == 1)
""",
        """
local r = read_drink_inventory({item(5, {removed=true}),
    item(20, {garbage_collect=true}), item(7, {in_inventory=true})}, 6)
assert(r.complete and r.units == 7 and r.excluded_records == 2)
assert(r.item_records == 3)
""",
        """
local r = read_drink_inventory({item(5, {forbid=true, in_job=true}),
    item(3, {rotten=true}), item(7, {in_inventory=true})}, 6)
assert(r.complete and r.units == 15 and r.forbidden_units == 5)
assert(r.rotten_units == 3 and r.in_job_units == 5)
""",
        """
local broken = {getType=function() error('injected type failure') end}
local r = read_drink_inventory({item(4), broken}, 6)
assert(not r.complete and r.units == nil and r.scanned_units == 4)
assert(r.type_read_failures == 1)
""",
        """
local r = read_drink_inventory({{getType=function() return nil end}}, 6)
assert(not r.complete and r.units == nil and r.type_read_failures == 1)
""",
        """
local broken = item(4)
broken.flags = setmetatable({}, {__index=function() error('flag failure') end})
local r = read_drink_inventory({broken}, 6)
assert(not r.complete and r.units == nil and r.item_read_failures == 1)
""",
        """
local broken = item(4)
broken.flags = nil
local r = read_drink_inventory({broken}, 6)
assert(not r.complete and r.units == nil and r.item_read_failures == 1)
""",
        """
local broken = setmetatable({}, {__index=function() error('list failure') end})
local r = read_drink_inventory(broken, 6)
assert(not r.complete and r.units == nil and r.list_read_failures == 1)
""",
        """
local r = read_drink_inventory(nil, 6)
assert(not r.complete and r.units == nil and r.list_read_failures == 1)
""",
        """
local r = read_drink_inventory({}, nil)
assert(not r.complete and r.units == nil and r.list_read_failures == 1)
""",
        """
for _, bad in ipairs({-1, 1.5, '4', true, math.huge, 0/0}) do
    local r = read_drink_inventory({item(bad)}, 6)
    assert(not r.complete and r.units == nil and r.item_read_failures == 1)
end
local r = read_drink_inventory({item(nil)}, 6)
assert(not r.complete and r.units == nil and r.item_read_failures == 1)
""",
        """
local entry = item(9, {forbid=true})
local r = read_drink_inventory({entry}, 6)
assert(r.complete and r.units == 9)
assert(entry.stack_size == 9 and entry.flags.forbid == true)
assert(entry.flags.removed == nil and entry.flags.in_job == nil)
""",
    ],
)
def test_native_lua_scanner(scenario):
    result = subprocess.run(
        [LUA, "-"],
        input=PRELUDE + DRINK_INVENTORY_LUA + scenario,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("complete,units", [(True, 46), (True, 0), (False, None)])
def test_raw_normalized_and_encoded_observations_preserve_source_and_unknown(
    monkeypatch, complete, units
):
    raw = {
        "population": 7,
        "stocks": {"food": 45, "wood": 4, "stone": 0},
        "stock_observations": {
            "schema_version": "fortgym.stock-observations/v1",
            "food": {"source": "ui.tasks.food counters", "freshness": "unverified"},
            "drink": {"complete": complete, "ui_estimate": 60},
        },
    }
    if units is not None:
        raw["stocks"]["drink"] = units
        raw["stock_observations"]["drink"]["units"] = units

    def run_lua(script, **kwargs):
        assert DRINK_INVENTORY_LUA in script
        assert "drink=drink_inventory.units" in script
        assert "drink_inventory.ui_estimate = drink_ui_estimate" in script
        return json.dumps(raw)

    monkeypatch.setattr(dfhack_exec, "run_lua_expr", run_lua)
    observed = dfhack_exec.read_game_state()
    assert observed["stocks"]["drink"] == units
    normalized = StateReader.from_dfhack(SimpleNamespace(get_state=lambda: observed))
    assert normalized["stocks"]["drink"] == units
    _, encoded = encode_observation(normalized)
    assert encoded["stocks"]["drink"] == units
    assert encoded["stock_observations"] == raw["stock_observations"]


def test_legacy_mock_payloads_without_scan_metadata_are_not_reinterpreted(monkeypatch):
    raw = {"stocks": {"drink": 12}}
    monkeypatch.setattr(dfhack_exec, "run_lua_expr", lambda *args, **kwargs: json.dumps(raw))
    assert dfhack_exec.read_game_state() == raw
