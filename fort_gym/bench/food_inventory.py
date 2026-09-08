"""Candidate read-only food inventory; not yet part of campaign observations.

The version-pinned native predicate is recorded literally, not interpreted as
ownership, reachability, nutrition, production, or a sustainable food supply.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "fortgym.native-food-inventory/v1"
SOURCE = "world.items.other.IN_PLAY isEdibleRaw(0) getStackSize excluding DRINK"
SCOPE = "native predicate at argument 0, not accessibility, ownership or production/consumption"
COUNTERS = (
    "scanned_units",
    "scanned_records",
    "food_records",
    "excluded_records",
    "drink_records",
    "nonfood_records",
    "item_read_failures",
    "list_read_failures",
    "duplicate_records",
    "forbidden_units",
    "rotten_units",
    "in_job_units",
    "trader_units",
    "hidden_units",
)

FOOD_INVENTORY_LUA = """
local function read_food_inventory(in_play, drink_type)
    local result = {
        schema_version = 'fortgym.native-food-inventory/v1',
        source = 'world.items.other.IN_PLAY isEdibleRaw(0) getStackSize excluding DRINK',
        scope = 'native predicate at argument 0, not accessibility, ownership or production/consumption',
        predicate_argument = 0,
        complete = false,
        scanned_units = 0, scanned_records = 0, food_records = 0,
        excluded_records = 0, drink_records = 0, nonfood_records = 0,
        item_read_failures = 0, list_read_failures = 0, duplicate_records = 0,
        forbidden_units = 0, rotten_units = 0, in_job_units = 0,
        trader_units = 0, hidden_units = 0,
    }
    local function integer(value)
        return type(value) == 'number' and value >= 0
            and value <= 9007199254740991 and value == math.floor(value)
    end
    if in_play == nil or not integer(drink_type) then
        result.list_read_failures = 1
        return result
    end
    local seen = {}
    local scan_ok = pcall(function()
        for _, item in ipairs(in_play) do
            result.scanned_records = result.scanned_records + 1
            local ok, entry = pcall(function()
                local id = item.id
                assert(integer(id), 'invalid item identity')
                if seen[id] then return {kind = 'duplicate'} end
                seen[id] = true
                local flags = assert(item.flags, 'missing item flags')
                assert(type(flags.removed) == 'boolean'
                    and type(flags.garbage_collect) == 'boolean', 'unreadable exclusion flags')
                if flags.removed or flags.garbage_collect then return {kind = 'excluded'} end
                local kind = item:getType()
                assert(integer(kind), 'invalid item type')
                if kind == drink_type then return {kind = 'drink'} end
                local edible = item:isEdibleRaw(0)
                assert(type(edible) == 'boolean', 'invalid native food predicate')
                if not edible then return {kind = 'nonfood'} end
                local units = item:getStackSize()
                assert(integer(units), 'invalid native stack size')
                local record = {kind = 'food', units = units}
                for key, flag in pairs({forbidden = 'forbid', rotten = 'rotten',
                    in_job = 'in_job', trader = 'trader', hidden = 'hidden'}) do
                    assert(type(flags[flag]) == 'boolean', 'unreadable item flag')
                    record[key] = flags[flag]
                end
                assert(integer(result.scanned_units + units), 'inventory sum overflow')
                return record
            end)
            if not ok then
                result.item_read_failures = result.item_read_failures + 1
            elseif entry.kind == 'food' then
                result.food_records = result.food_records + 1
                result.scanned_units = result.scanned_units + entry.units
                for _, flag in ipairs({'forbidden', 'rotten', 'in_job', 'trader', 'hidden'}) do
                    if entry[flag] then
                        result[flag .. '_units'] = result[flag .. '_units'] + entry.units
                    end
                end
            else
                local field = entry.kind .. '_records'
                result[field] = result[field] + 1
            end
        end
    end)
    if not scan_ok then result.list_read_failures = result.list_read_failures + 1 end
    result.complete = result.item_read_failures == 0
        and result.list_read_failures == 0 and result.duplicate_records == 0
    if result.complete then result.units = result.scanned_units end
    return result
end
"""


def validate_food_inventory(value: Any) -> dict[str, Any]:
    """Normalize an attested scan; incomplete native reads remain explicit unknowns."""
    if not isinstance(value, dict) or (
        value.get("schema_version") != SCHEMA
        or value.get("source") != SOURCE
        or value.get("scope") != SCOPE
        or type(value.get("predicate_argument")) is not int
        or value["predicate_argument"] != 0
        or type(value.get("complete")) is not bool
    ):
        raise ValueError("Unrecognized native food inventory provenance")
    counts: dict[str, int] = {}
    for key in COUNTERS:
        n = value.get(key)
        if type(n) is not int or not 0 <= n <= 9007199254740991:
            raise ValueError("Invalid native food inventory counters")
        counts[key] = n
    if counts["scanned_records"] != sum(
        counts[key]
        for key in (
            "food_records",
            "excluded_records",
            "drink_records",
            "nonfood_records",
            "item_read_failures",
            "duplicate_records",
        )
    ):
        raise ValueError("Native food inventory records do not reconcile")
    if any(
        counts[key] > counts["scanned_units"]
        for key in (
            "forbidden_units",
            "rotten_units",
            "in_job_units",
            "trader_units",
            "hidden_units",
        )
    ) or (counts["food_records"] == 0 and counts["scanned_units"] != 0):
        raise ValueError("Native food inventory unit counters do not reconcile")
    complete = all(
        counts[key] == 0
        for key in (
            "item_read_failures",
            "list_read_failures",
            "duplicate_records",
        )
    )
    if value["complete"] is not complete:
        raise ValueError("Native food inventory completeness disagrees with failures")
    units = value.get("units")
    if (complete and (type(units) is not int or units != counts["scanned_units"])) or (
        not complete and units is not None
    ):
        raise ValueError("Incomplete native food inventory cannot publish a total")
    return {
        "schema_version": SCHEMA,
        "source": SOURCE,
        "scope": SCOPE,
        "predicate_argument": 0,
        "complete": complete,
        "units": units,
        **counts,
    }
