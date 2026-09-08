"""Opt-in, private campaign food measurement, separate from agent observations."""

from __future__ import annotations

import json
from pathlib import Path

from ..dfhack_exec import DFHackError, run_lua_expr
from ..food_inventory import FOOD_INVENTORY_LUA, validate_food_inventory

PROFILE = "fortgym.campaign-food-measurement/v1"


def validate_profile(value: object) -> str | None:
    if value is None:
        return None
    if value != PROFILE:
        raise ValueError("Unsupported private food measurement profile")
    return PROFILE


def _boundary(value: object, *, year: int, year_tick: int, root: str | None = None) -> dict:
    if not isinstance(value, dict) or (
        not isinstance(value.get("dfroot"), str) or not value["dfroot"].startswith("/")
        or (root is not None and value["dfroot"] != root)
        or not isinstance(value.get("save_name"), str) or not value["save_name"]
        or value.get("paused") is not True
        or type(value.get("year")) is not int or value["year"] != year
        or type(value.get("year_tick")) is not int or value["year_tick"] != year_tick
    ):
        raise ValueError("Food measurement crossed its loaded paused native boundary")
    return {key: value[key] for key in ("dfroot", "save_name", "paused", "year", "year_tick")}


def validate_measurement(value: object, *, year: int, year_tick: int, root: str | None = None) -> dict:
    if type(year) is not int or year < 0 or type(year_tick) is not int or not 0 <= year_tick < 403200:
        raise ValueError("Invalid private food measurement calendar")
    if not isinstance(value, dict) or (
        value.get("schema_version") != PROFILE or value.get("available") is not True
    ):
        raise ValueError("Private food measurement is unavailable")
    before = _boundary(value.get("before"), year=year, year_tick=year_tick, root=root)
    after = _boundary(value.get("after"), year=year, year_tick=year_tick, root=root)
    if before != after:
        raise ValueError("Food measurement native boundary changed")
    return {
        "schema_version": PROFILE, "available": True, "before": before, "after": after,
        "inventory": validate_food_inventory(value.get("inventory")),
    }


def read_food_measurement(*, expected_dfroot: Path, year: int, year_tick: int) -> dict:
    """Retain unreadable scans as unknown metadata, not a gameplay stop condition."""
    root = str(expected_dfroot.resolve())
    if type(year) is not int or year < 0 or type(year_tick) is not int or not 0 <= year_tick < 403200:
        raise ValueError("Invalid private food measurement calendar")
    script = FOOD_INVENTORY_LUA + """
local json = require('json')
local function boundary()
    return {dfroot=dfhack.getDFPath(), save_name=df.global.world.cur_savegame.save_dir,
        paused=df.global.pause_state, year=df.global.cur_year, year_tick=df.global.cur_year_tick}
end
local before = boundary()
assert(before.dfroot == expected_root and before.paused and dfhack.isMapLoaded())
assert(before.year == expected_year and before.year_tick == expected_tick)
local inventory = read_food_inventory(df.global.world.items.other.IN_PLAY, df.item_type.DRINK)
print(json.encode({schema_version='fortgym.campaign-food-measurement/v1',
    available=true, before=before, after=boundary(), inventory=inventory}))
"""
    prefix = (
        "local expected_root=" + json.dumps(root) + "\n"
        + f"local expected_year={year}; local expected_tick={year_tick}\n"
    )
    try:
        value = json.loads(run_lua_expr(prefix + script, timeout=5.0))
        return validate_measurement(value, year=year, year_tick=year_tick, root=root)
    except (DFHackError, OSError, ValueError, TypeError) as error:
        return {
            "schema_version": PROFILE, "available": False, "inventory": None,
            "error_type": type(error).__name__, "error": str(error),
        }
