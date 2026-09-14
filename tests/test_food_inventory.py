"""Execute the candidate Lua, then validate its actual JSON-shaped output."""

import json
import shutil
import subprocess
from copy import deepcopy

import pytest

from fort_gym.bench.food_inventory import (
    COUNTERS,
    FOOD_INVENTORY_LUA,
    SCHEMA,
    SCOPE,
    SOURCE,
    validate_food_inventory,
)

LUA = shutil.which("lua")
PRELUDE = """
local next_id = 0
local function item(units, edible, kind, overrides)
    next_id = next_id + 1
    local flags = {removed=false, garbage_collect=false, forbid=false, rotten=false,
        in_job=false, trader=false, hidden=false}
    for k, v in pairs(overrides or {}) do flags[k] = v end
    return {id=next_id, stack_size=999, flags=flags,
        getType=function() return kind or 7 end,
        isEdibleRaw=function(_, argument)
            assert(argument == 0)
            if edible == nil then return true end
            return edible
        end,
        getStackSize=function() return units end}
end
"""
ENCODE = """
local fields = {}
for key, value in pairs(r) do
    local encoded = type(value) == 'string' and string.format('%q', value) or tostring(value)
    table.insert(fields, string.format('%q', key) .. ':' .. encoded)
end
print('{' .. table.concat(fields, ',') .. '}')
"""


@pytest.mark.skipif(LUA is None, reason="Lua interpreter is unavailable")
@pytest.mark.parametrize(
    "scenario",
    [
        """
local r = read_food_inventory({item(5), item(11), item(0), item(8, false), item(20, true, 6)}, 6)
assert(r.complete and r.units == 16 and r.food_records == 3)
assert(r.scanned_records == 5 and r.drink_records == 1 and r.nonfood_records == 1)
""",
        """
local r = read_food_inventory({}, 6)
assert(r.complete and r.units == 0 and r.scanned_records == 0)
""",
        """
local a = item(99, true, 7, {removed=true})
local b = item(99, true, 7, {garbage_collect=true})
a.getType = function() error('removed item must not be classified') end
b.getStackSize = function() error('garbage item must not be counted') end
local r = read_food_inventory({a, b, item(5)}, 6)
assert(r.complete and r.units == 5 and r.excluded_records == 2)
""",
        """
local r = read_food_inventory({item(5, true, 7, {forbid=true, rotten=true, in_job=true}),
    item(3, true, 7, {trader=true, hidden=true})}, 6)
assert(r.complete and r.units == 8)
assert(r.forbidden_units == 5 and r.rotten_units == 5 and r.in_job_units == 5)
assert(r.trader_units == 3 and r.hidden_units == 3)
""",
        """
local a = item(5)
local r = read_food_inventory({a, a}, 6)
assert(not r.complete and r.units == nil and r.scanned_units == 5)
assert(r.duplicate_records == 1)
""",
        """
local a = item(5, false)
a.getStackSize = function() error('nonfood stack must not be counted') end
local r = read_food_inventory({a}, 6)
assert(r.complete and r.units == 0 and r.nonfood_records == 1)
""",
        """
local a = item(20, true, 6)
a.isEdibleRaw = function() error('drink must be excluded before predicate') end
local r = read_food_inventory({a}, 6)
assert(r.complete and r.units == 0 and r.drink_records == 1)
""",
        """
local a = item(5)
a.isEdibleRaw = function() error('predicate unavailable') end
local r = read_food_inventory({item(3), a}, 6)
assert(not r.complete and r.units == nil and r.scanned_units == 3 and r.item_read_failures == 1)
""",
        """
local r = read_food_inventory({item(5, 1)}, 6)
assert(not r.complete and r.units == nil and r.item_read_failures == 1)
""",
        """
local a = item(5)
a.flags = nil
local r = read_food_inventory({a}, 6)
assert(not r.complete and r.item_read_failures == 1)
""",
        """
local a = item(5)
a.flags.forbid = nil
local r = read_food_inventory({a}, 6)
assert(not r.complete and r.item_read_failures == 1)
""",
        """
local a = item(5)
a.flags.removed = 0
local r = read_food_inventory({a}, 6)
assert(not r.complete and r.item_read_failures == 1)
""",
        """
local a = item(5)
a.id = nil
local r = read_food_inventory({a}, 6)
assert(not r.complete and r.item_read_failures == 1)
""",
        """
local a = item(5)
a.getType = function() return nil end
local r = read_food_inventory({a}, 6)
assert(not r.complete and r.item_read_failures == 1)
""",
        """
local r = read_food_inventory(nil, 6)
assert(not r.complete and r.units == nil and r.list_read_failures == 1)
""",
        """
local r = read_food_inventory({}, nil)
assert(not r.complete and r.units == nil and r.list_read_failures == 1)
""",
        """
local broken = setmetatable({}, {__index=function() error('list unreadable') end})
local r = read_food_inventory(broken, 6)
assert(not r.complete and r.units == nil and r.list_read_failures == 1)
""",
        """
local a = item(5, true, 7, {in_job=true})
local r = read_food_inventory({a}, 6)
assert(r.complete and r.units == 5 and r.in_job_units == 5)
assert(a.stack_size == 999 and a.flags.in_job == true and a.id == 1)
assert(a.flags.removed == false and a.flags.garbage_collect == false)
""",
        *[
            f"""
local r = read_food_inventory({{item({bad})}}, 6)
assert(not r.complete and r.units == nil and r.item_read_failures == 1)
"""
            for bad in ("-1", "1.5", "'5'", "true", "math.huge", "0/0", "nil")
        ],
        """
local r = read_food_inventory({item(9007199254740991), item(1)}, 6)
assert(not r.complete and r.units == nil and r.item_read_failures == 1)
""",
    ],
)
def test_food_scanner_executes_without_promoting_incomplete_reads(scenario):
    result = subprocess.run(
        [LUA, "-"],
        input=PRELUDE + FOOD_INVENTORY_LUA + scenario + ENCODE,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    raw = json.loads(result.stdout)
    normalized = validate_food_inventory(raw)
    assert normalized["complete"] is raw["complete"]
    assert normalized["units"] == raw.get("units")


def complete_scan():
    return {
        "schema_version": SCHEMA,
        "source": SOURCE,
        "scope": SCOPE,
        "predicate_argument": 0,
        "complete": True,
        "units": 0,
        **dict.fromkeys(COUNTERS, 0),
    }


def test_scan_projection_preserves_zero_and_drops_extra_native_content():
    raw = complete_scan()
    raw["private_items"] = [{"id": 12, "position": [1, 2, 3]}]
    original = deepcopy(raw)
    result = validate_food_inventory(raw)
    assert result["units"] == 0 and result["complete"] is True
    assert "private_items" not in result and raw == original


def test_incomplete_scan_has_unknown_total_not_successful_zero():
    raw = complete_scan()
    raw.update(complete=False, list_read_failures=1)
    del raw["units"]
    result = validate_food_inventory(raw)
    assert result["complete"] is False and result["units"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "other"),
        ("source", "UI food"),
        ("scope", "reachable food"),
        ("predicate_argument", False),
        ("predicate_argument", 1),
        ("complete", 1),
        ("units", True),
        ("units", 1),
        ("food_records", 1),
        ("scanned_records", 1),
        ("scanned_units", 1),
        ("forbidden_units", 1),
        ("duplicate_records", 1),
        ("list_read_failures", 1),
    ],
)
def test_food_measurement_rejects_inconsistent_claims(field, value):
    raw = complete_scan()
    raw[field] = value
    with pytest.raises(ValueError):
        validate_food_inventory(raw)


@pytest.mark.parametrize("value", [True, False, -1, 0.5, "0", None, 9007199254740992])
@pytest.mark.parametrize("field", COUNTERS)
def test_every_food_counter_requires_a_safe_nonnegative_integer(field, value):
    raw = complete_scan()
    raw[field] = value
    with pytest.raises(ValueError):
        validate_food_inventory(raw)


def test_partial_scan_cannot_expose_a_complete_total():
    raw = complete_scan()
    raw.update(complete=False, list_read_failures=1)
    with pytest.raises(ValueError):
        validate_food_inventory(raw)
