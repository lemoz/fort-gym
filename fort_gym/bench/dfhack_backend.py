"""High-level DFHack helpers backed by bounded CLI scripts."""

from __future__ import annotations

import time
from typing import Dict, Iterable

from .config import DFROOT
from .dfhack_exec import (
    DFHackError,
    read_pause_state,
    run_lua_file,
    set_paused,
    tick_read,
)
from .env.keystroke_exec import execute_keystroke_action

HOOK_ROOT = DFROOT / "hook"

ALLOWED_ITEMS = {"bed", "door", "table", "chair", "barrel", "bin"}
MAX_QTY = 5
MAX_RECT_W = 30
MAX_RECT_H = 30
VALID_KINDS: Iterable[str] = ("dig", "channel", "chop")


def _hook_path(name: str) -> str:
    return str(HOOK_ROOT / name)


def queue_manager_order(item: str, qty: int) -> Dict[str, object]:
    if item not in ALLOWED_ITEMS:
        return {"ok": False, "error": "invalid_item"}
    qty_clamped = max(1, min(int(qty), MAX_QTY))
    try:
        return run_lua_file(_hook_path("order_make.lua"), item, str(qty_clamped))
    except DFHackError as exc:
        return {"ok": False, "error": str(exc)}


def designate_rect(kind: str, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> Dict[str, object]:
    kind_lower = kind.lower()
    if kind_lower not in VALID_KINDS:
        return {"ok": False, "error": "invalid_kind"}

    width = abs(int(x2) - int(x1)) + 1
    height = abs(int(y2) - int(y1)) + 1
    if width > MAX_RECT_W or height > MAX_RECT_H:
        return {"ok": False, "error": "rect_too_large"}

    try:
        return run_lua_file(
            _hook_path("designate_rect.lua"),
            kind_lower,
            str(int(x1)),
            str(int(y1)),
            str(int(z1)),
            str(int(x2)),
            str(int(y2)),
            str(int(z2)),
        )
    except DFHackError as exc:
        return {"ok": False, "error": str(exc)}


def _safe_read_pause_state() -> bool | None:
    try:
        return read_pause_state()
    except DFHackError:
        return None


def _enable_nopause() -> None:
    """Enable nopause mode to prevent auto-pausing during advancement."""
    try:
        from .dfhack_exec import run_dfhack
        from .config import DFHACK_RUN, DFROOT
        run_dfhack([str(DFHACK_RUN), "nopause", "1"], timeout=2.0, cwd=str(DFROOT))
    except Exception:
        pass  # Non-critical, continue anyway


def advance_ticks_exact_external(ticks: int, repause: bool = True) -> Dict[str, object]:
    """Advance DF by polling cur_year_tick via repeated dfhack-run ticks."""

    try:
        want = int(ticks)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_ticks"}

    if want <= 0:
        return {"ok": False, "error": "invalid_ticks"}

    want = min(want, 1000)

    try:
        started_paused = read_pause_state()
    except DFHackError as exc:
        return {"ok": False, "error": f"read_pause_failed:{exc}"}

    try:
        start_tick = tick_read()
    except DFHackError as exc:
        return {"ok": False, "error": f"tick_read_failed:{exc}"}

    ok = True
    error: str | None = None
    timed_out = False
    current_tick = start_tick
    # Allow ~200ms per tick (conservative for slow headless mode)
    safety_ms = max(10000, want * 200)
    t_start = time.monotonic()

    # Enable nopause to prevent auto-pausing during advancement
    _enable_nopause()

    if started_paused:
        try:
            set_paused(False)
        except DFHackError as exc:
            return {"ok": False, "error": f"resume_failed:{exc}"}

    try:
        while True:
            time.sleep(0.05)
            try:
                current_tick = tick_read()
            except DFHackError as exc:
                ok = False
                error = f"tick_read_failed:{exc}"
                break
            if current_tick - start_tick >= want:
                break
            elapsed_ms = (time.monotonic() - t_start) * 1000.0
            if elapsed_ms > safety_ms:
                timed_out = True
                break
    finally:
        if repause:
            try:
                set_paused(True)
            except DFHackError as exc:
                ok = False
                error = error or f"repause_failed:{exc}"

    elapsed_ms_int = int((time.monotonic() - t_start) * 1000.0)
    paused_after = _safe_read_pause_state()

    result: Dict[str, object] = {
        "ok": ok and error is None,
        "requested": want,
        "ticks_advanced": max(0, current_tick - start_tick),
        "start_tick": start_tick,
        "end_tick": current_tick,
        "paused_before": started_paused,
        "paused_after": paused_after,
        "elapsed_ms": elapsed_ms_int,
    }
    if error:
        result["error"] = error
    if timed_out:
        result["timeout"] = True
    return result


# Backwards compatibility for previous import path
advance_ticks_exact = advance_ticks_exact_external


__all__ = [
    "ALLOWED_ITEMS",
    "MAX_QTY",
    "MAX_RECT_W",
    "MAX_RECT_H",
    "queue_manager_order",
    "designate_rect",
    "advance_ticks_exact_external",
    "advance_ticks_exact",
    "execute_keystroke_action",
]
