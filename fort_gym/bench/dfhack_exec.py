"""Bounded helpers for invoking DFHack CLI scripts."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Dict, List

from .config import DFROOT, DFHACK_RUN, dfhack_cmd


class DFHackError(RuntimeError):
    """Raised when DFHack commands fail or time out."""


def run_dfhack(args: List[str], *, timeout: float = 2.5, cwd: str = str(DFROOT)) -> str:
    """Execute a DFHack command with tight bounds and return stdout."""

    try:
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
_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_ESCAPE.sub('', text)


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
state.population = #df.global.world.units.active
state.stocks = {food=0, drink=0, wood=0, stone=0}
state.hostiles = false
state.dead = 0
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
    "set_paused",
    "read_game_state",
]
