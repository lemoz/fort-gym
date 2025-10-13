"""High-level DFHack helpers backed by bounded CLI scripts."""

from __future__ import annotations

from typing import Dict, Iterable

from .dfhack_exec import DFHackError, run_lua_file

HOOK_ROOT = "/opt/dwarf-fortress/hook"

ALLOWED_ITEMS = {"bed", "door", "table", "chair", "barrel", "bin"}
MAX_QTY = 5
MAX_RECT_W = 30
MAX_RECT_H = 30
VALID_KINDS: Iterable[str] = ("dig", "channel", "chop")


def _hook_path(name: str) -> str:
    return f"{HOOK_ROOT}/{name}"


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


__all__ = [
    "ALLOWED_ITEMS",
    "MAX_QTY",
    "MAX_RECT_W",
    "MAX_RECT_H",
    "queue_manager_order",
    "designate_rect",
]
