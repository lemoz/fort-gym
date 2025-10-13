"""Bounded helpers for invoking DFHack CLI scripts."""

from __future__ import annotations

import json
import subprocess
from typing import Dict, List

from .config import DFROOT, DFHACK_RUN


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


def run_lua_file(path: str, *args: str, timeout: float = 2.5) -> Dict[str, object]:
    """Invoke a DFHack Lua script and parse JSON output."""

    command = [str(DFHACK_RUN), "lua", "-q", "-f", path]
    command.extend(args)
    out = run_dfhack(command, timeout=timeout)
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise DFHackError(f"bad json from {path}: {out!r}") from exc


__all__ = ["DFHackError", "run_dfhack", "run_lua_file"]
