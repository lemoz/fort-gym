"""Bounded helpers for invoking DFHack CLI scripts."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from shutil import which
from typing import Dict, List

from .config import DFHACK_RUN, DFROOT, dfhack_cmd


class DFHackError(RuntimeError):
    """Raised when DFHack commands fail or time out."""


def _maybe_wrap_with_script(args: List[str]) -> List[str]:
    """Wrap a DFHack invocation in a pseudo-tty when available.

    Some DFHack builds crash when stdout isn't a tty (e.g. headless systemd).
    Wrapping with `script -q -c ... /dev/null` forces a pty and stabilizes output.
    """

    if not args:
        return args

    if sys.platform == "win32":
        return args

    # macOS ships a BSD `script` without `-c`; only wrap on Linux where util-linux is standard.
    if not sys.platform.startswith("linux"):
        return args

    if which("script") is None:
        return args

    argv0 = args[0]
    if not argv0.endswith("dfhack-run"):
        return args

    return ["script", "-q", "-c", shlex.join(args), "/dev/null"]


def run_dfhack(args: List[str], *, timeout: float = 2.5, cwd: str = str(DFROOT)) -> str:
    """Execute a DFHack command with tight bounds and return stdout."""

    try:
        args = _maybe_wrap_with_script(args)
        output = subprocess.check_output(
            args,
            cwd=cwd,
            timeout=timeout,
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - runtime guard
        raise DFHackError(f"timeout: {args}") from exc
    except subprocess.CalledProcessError as exc:  # pragma: no cover - runtime guard
        raise DFHackError(f"rc={exc.returncode} out={exc.output!r}") from exc
    return output.strip()


# ANSI escape sequence pattern
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_ESCAPE.sub("", text)


def run_lua_file(path: str, *args: str, timeout: float = 2.5) -> Dict[str, object]:
    """Invoke a DFHack Lua script and parse JSON output."""

    command = [str(DFHACK_RUN), "lua", "-f", path]
    command.extend(args)
    out = run_dfhack(command, timeout=timeout)
    if not out:
        return {}
    # Strip ANSI color codes before parsing JSON
    clean = _strip_ansi(out).strip()
    if not clean:
        return {}
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        for line in reversed([line.strip() for line in clean.splitlines() if line.strip()]):
            if line.startswith("{") or line.startswith("["):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise DFHackError(f"bad json from {path}: {clean!r}") from exc


def run_lua_expr(expr: str, *, timeout: float = 1.0) -> str:
    """Execute an inline Lua expression via dfhack-run and return stdout."""

    # Pass Lua code directly without -e flag (not supported in all DFHack versions)
    out = run_dfhack(
        dfhack_cmd("lua", expr),
        timeout=timeout,
        cwd=str(DFROOT),
    )
    # Strip ANSI color codes
    return _strip_ansi(out).strip()


def tick_read(timeout: float = 1.0) -> int:
    """Return the current df.global.cur_year_tick value."""

    out = run_lua_expr("print(df.global.cur_year_tick or 0)", timeout=timeout)
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        raise DFHackError("tick_read: empty output")
    try:
        return int(lines[-1])
    except ValueError as exc:
        raise DFHackError(f"tick_read: invalid output {lines[-1]!r}") from exc


def read_pause_state(timeout: float = 1.0) -> bool:
    """Return True if DF is currently paused."""

    out = run_lua_expr(
        "print(df.global.pause_state and 1 or 0)",
        timeout=timeout,
    )
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        raise DFHackError("read_pause_state: empty output")
    if lines[-1] not in {"0", "1"}:
        raise DFHackError(f"read_pause_state: invalid output {lines[-1]!r}")
    return lines[-1] == "1"


def read_tick_pause_viewscreen(timeout: float = 1.0) -> Dict[str, object]:
    """Atomically read the tick, pause flag, and concrete current viewscreen."""

    lua_script = """
local json = require('json')
local viewscreen_type = "unknown"
pcall(function()
    local view = dfhack.gui.getCurViewscreen()
    if view and view._type then
        local rendered = tostring(view._type)
        viewscreen_type = rendered:match("<type: ([^>]+)>") or rendered
    end
end)
print(json.encode({
    cur_year = df.global.cur_year or 0,
    cur_year_tick = df.global.cur_year_tick or 0,
    pause_state = df.global.pause_state and true or false,
    viewscreen_type = viewscreen_type,
}))
"""
    out = run_lua_expr(lua_script, timeout=timeout)
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        raise DFHackError("read_tick_pause_viewscreen: empty output")
    try:
        value = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise DFHackError(
            f"read_tick_pause_viewscreen: invalid output {lines[-1]!r}"
        ) from exc
    if not isinstance(value, dict):
        raise DFHackError("read_tick_pause_viewscreen: expected object output")
    cur_year = value.get("cur_year")
    cur_year_tick = value.get("cur_year_tick")
    if type(cur_year) is not int or cur_year < 0:
        raise DFHackError("read_tick_pause_viewscreen: invalid cur_year")
    if type(cur_year_tick) is not int or cur_year_tick < 0:
        raise DFHackError("read_tick_pause_viewscreen: invalid cur_year_tick")
    if not isinstance(value.get("pause_state"), bool):
        raise DFHackError("read_tick_pause_viewscreen: invalid pause_state")
    viewscreen_type = value.get("viewscreen_type")
    if not isinstance(viewscreen_type, str):
        raise DFHackError("read_tick_pause_viewscreen: invalid viewscreen_type")
    return {
        "cur_year": cur_year,
        "cur_year_tick": cur_year_tick,
        "pause_state": value["pause_state"],
        "viewscreen_type": viewscreen_type,
    }


def set_paused(paused: bool, timeout: float = 1.0) -> None:
    """Set df.global.pause_state to the requested value."""

    value = "true" if paused else "false"
    run_lua_expr(f"df.global.pause_state={value}", timeout=timeout)


def read_game_state(timeout: float = 2.5) -> Dict[str, object]:
    """Read game state via CLI and return as dict."""

    lua_script = """
local json = require('json')
local state = {}
state.time = df.global.cur_year_tick or 0
state.year = df.global.cur_year or 0
state.year_tick = df.global.cur_year_tick or 0

-- Pause state - critical for agent to know if game is running
state.pause_state = df.global.pause_state and true or false

-- Factual UI context for bounded paused-dialog interaction. Keep this as the
-- concrete DF viewscreen type; policy and safety checks live in the runner.
state.viewscreen_type = "unknown"
pcall(function()
    local view = dfhack.gui.getCurViewscreen()
    if view and view._type then
        local rendered = tostring(view._type)
        state.viewscreen_type = rendered:match("<type: ([^>]+)>") or rendered
    end
end)

-- Count only citizen dwarves
local dwarf_count = 0
for _, u in ipairs(df.global.world.units.active) do
    if dfhack.units.isCitizen(u) and not dfhack.units.isDead(u) then
        dwarf_count = dwarf_count + 1
    end
end
state.population = dwarf_count

-- Use pre-computed food/drink counts from ui.tasks.food (no iteration needed)
local food_stats = df.global.ui.tasks.food
local food_count = (food_stats.meat or 0) + (food_stats.fish or 0) + (food_stats.plant or 0) + (food_stats.other or 0)
local drink_count = food_stats.drink or 0
local wealth = df.global.ui.tasks.wealth.total or 0

local wood_count = 0
local stone_count = 0
local wood_usable = 0
local stone_usable = 0
local item_lists = df.global.world.items and df.global.world.items.other
local in_play = item_lists and item_lists.IN_PLAY or {}
local wood_type = df.item_type and df.item_type.WOOD
local boulder_type = df.item_type and df.item_type.BOULDER
local blocks_type = df.item_type and df.item_type.BLOCKS

-- "usable" mirrors the material filter the build hooks apply: an item that
-- is claimed by a job, locked inside a (pending) building/construction, or
-- forbidden/hidden cannot be consumed by a new BUILD. G6 attempt 2 (run
-- 55c39cdd): 10 pending walls claimed 10 of 11 logs at step 8 and the raw
-- count kept reading 11 for 90 futile steps.
local function item_usable(item)
    local ok, usable = pcall(function()
        return not (item.flags.in_job or item.flags.forbid or item.flags.hidden
            or item.flags.in_building or item.flags.construction
            or item.flags.garbage_collect or item.flags.artifact)
            and item.pos ~= nil and item.pos.x >= 0
    end)
    return ok and usable or false
end

for _, item in ipairs(in_play) do
    local ok_type, item_type = pcall(function() return item:getType() end)
    if ok_type then
        if wood_type and item_type == wood_type then
            wood_count = wood_count + 1
            if item_usable(item) then wood_usable = wood_usable + 1 end
        elseif (boulder_type and item_type == boulder_type)
            or (blocks_type and item_type == blocks_type) then
            stone_count = stone_count + 1
            if item_usable(item) then stone_usable = stone_usable + 1 end
        end
    end
end

state.stocks = {food=food_count, drink=drink_count, wood=wood_count, stone=stone_count,
    wood_usable=wood_usable, stone_usable=stone_usable, wealth=wealth}
state.hostiles = false
-- Count our civ's dead dwarves for real. This was hardcoded 0 until G6
-- attempt 1 (run 769f5034): a citizen drowned, population dropped 7->6,
-- and the dead metric never moved -- the casualty check read a constant.
local dead_count = 0
pcall(function()
    local civ_id = df.global.ui.civ_id
    for _, unit in ipairs(df.global.world.units.all) do
        local ok_dead, is_dead = pcall(function()
            return unit.civ_id == civ_id
                and dfhack.units.isDwarf(unit)
                and dfhack.units.isDead(unit)
        end)
        if ok_dead and is_dead then
            dead_count = dead_count + 1
        end
    end
end)
state.dead = dead_count
state.recent_events = {}
print(json.encode(state))
"""
    try:
        out = run_lua_expr(lua_script, timeout=timeout)
        if not out:
            return {}
        # Parse the entire output as JSON (may be multi-line formatted)
        return json.loads(out)
    except (DFHackError, json.JSONDecodeError):
        return {}


__all__ = [
    "DFHackError",
    "run_dfhack",
    "run_lua_file",
    "run_lua_expr",
    "tick_read",
    "read_pause_state",
    "read_tick_pause_viewscreen",
    "set_paused",
    "read_game_state",
]
