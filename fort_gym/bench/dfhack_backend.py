"""High-level DFHack helpers backed by bounded CLI scripts."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Iterable, Sequence

from .config import DFROOT
from .dfhack_exec import (
    DFHackError,
    read_pause_state,
    run_dfhack,
    run_lua_file,
    set_paused,
    tick_read,
)
from .env.keystroke_exec import execute_keystroke_action

HOOK_ROOT = DFROOT / "hook"
REPO_HOOK_ROOT = Path(__file__).resolve().parents[2] / "hook"

ALLOWED_ITEMS = {"bed", "door", "table", "chair", "barrel", "bin", "brew"}
ALLOWED_WORKSHOPS = {"CarpenterWorkshop", "Still"}
ALLOWED_FURNITURE = {"Bed", "Door", "Table", "Chair"}
ALLOWED_CONSTRUCTIONS = {"Wall", "Floor"}
MAX_QTY = 5
MAX_RECT_W = 30
MAX_RECT_H = 30
MAX_SNAPSHOT_W = 64
MAX_SNAPSHOT_H = 64
MAX_FARM_PLOT_W = 5
MAX_FARM_PLOT_H = 5
FARM_SEASONS = ("spring", "summer", "autumn", "winter")
MAX_CROP_TOKEN_LEN = 64
VALID_KINDS: Iterable[str] = ("dig", "channel", "chop", "gather")
# Friendly labor name -> df.unit_labor enum name. Whitelist is mirrored in
# hook/set_labor.lua (which independently pcall-guards each enum on the live DF
# build). Flipping u.status.labors[df.unit_labor.X] is exactly the player's
# v-p-l toggle: it lets a matching queued job be taken by that citizen but
# completes no work itself.
LABOR_WHITELIST: Dict[str, str] = {
    "mine": "MINE",
    "woodcutting": "CUTWOOD",
    "carpentry": "CARPENTER",
    "masonry": "MASON",
    "farming": "PLANT",
    "herbalism": "HERBALIST",
    "brewing": "BREWER",
    "fishing": "FISH",
    "construction": "BUILD_CONSTRUCTION",
    "cooking": "COOK",
}
DEFAULT_WORK_RECT = (50, 35, 0, 54, 39, 0)


def _hook_path(name: str) -> str:
    repo_path = REPO_HOOK_ROOT / name
    if repo_path.exists():
        return str(repo_path)
    installed_path = HOOK_ROOT / name
    if installed_path.exists():
        return str(installed_path)
    return str(repo_path)


def _work_rect_from_env() -> tuple[int, int, int, int, int, int]:
    raw = os.getenv("FORT_GYM_WORK_RECT")
    if not raw:
        return DEFAULT_WORK_RECT
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) != 6:
        return DEFAULT_WORK_RECT
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return DEFAULT_WORK_RECT


def queue_manager_order(item: str, qty: int) -> Dict[str, object]:
    if item not in ALLOWED_ITEMS:
        return {"ok": False, "error": "invalid_item"}
    qty_clamped = max(1, min(int(qty), MAX_QTY))
    try:
        return run_lua_file(_hook_path("order_make.lua"), item, str(qty_clamped))
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def build_workshop(
    kind: str,
    x: int,
    y: int,
    z: int,
) -> Dict[str, object]:
    """Place a bounded safe workshop near the fort.

    Plan-agnostic: the hook rejects placements farther than 24 tiles
    (Chebyshev) from every existing player building and citizen with
    ``too_far_from_fort``.
    """

    if kind not in ALLOWED_WORKSHOPS:
        return {"ok": False, "error": "invalid_kind"}

    x_val = int(x)
    y_val = int(y)
    z_val = int(z)

    try:
        return run_lua_file(
            _hook_path("build_workshop.lua"),
            kind,
            str(x_val),
            str(y_val),
            str(z_val),
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def place_furniture(
    kind: str,
    x: int,
    y: int,
    z: int,
) -> Dict[str, object]:
    """Install a finished furniture item as a bounded 1x1 building.

    Uses an existing produced item and creates a normal install job that a
    dwarf completes over real time — the player's b-menu placement.
    Plan-agnostic: the hook rejects tiles farther than 24 tiles (Chebyshev)
    from every existing player building and citizen with ``too_far_from_fort``.
    """

    if kind not in ALLOWED_FURNITURE:
        return {"ok": False, "error": "invalid_kind"}

    x_val = int(x)
    y_val = int(y)
    z_val = int(z)

    try:
        return run_lua_file(
            _hook_path("place_furniture.lua"),
            kind,
            str(x_val),
            str(y_val),
            str(z_val),
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def build_construction(
    kind: str,
    x1: int,
    y1: int,
    z: int,
    x2: int | None = None,
    y2: int | None = None,
) -> Dict[str, object]:
    """Place bounded wall/floor constructions with a plan-agnostic locality bound.

    Unlike workshop/furniture placement, constructions are not checked against
    a plan rect — the hook itself rejects tiles far from the existing fort
    (buildings and citizens). This helper only enforces the shared 10-tile cap.
    """

    if kind not in ALLOWED_CONSTRUCTIONS:
        return {"ok": False, "error": "invalid_kind"}

    x1_val = int(x1)
    y1_val = int(y1)
    z_val = int(z)
    x2_val = int(x2) if x2 is not None else x1_val
    y2_val = int(y2) if y2 is not None else y1_val

    width = abs(x2_val - x1_val) + 1
    height = abs(y2_val - y1_val) + 1
    if width * height > 10:
        return {"ok": False, "error": "too_many_tiles"}

    try:
        return run_lua_file(
            _hook_path("build_construction.lua"),
            kind,
            str(x1_val),
            str(y1_val),
            str(z_val),
            str(x2_val),
            str(y2_val),
            timeout=10.0,
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def build_farm_plot(
    x1: int,
    y1: int,
    z: int,
    x2: int | None = None,
    y2: int | None = None,
) -> Dict[str, object]:
    """Place a bounded farm plot near the fort (no material item required).

    Rect corner semantics like build_construction's Wall/Floor: a single
    tile at (x1, y1, z) when x2/y2 are omitted, or a rectangle up to 5x5
    when given. Plan-agnostic: the hook rejects placements farther than 24
    tiles (Chebyshev) from every existing player building and citizen, same
    as build_workshop/build_construction/place_furniture.
    """

    x1_val = int(x1)
    y1_val = int(y1)
    z_val = int(z)
    x2_val = int(x2) if x2 is not None else x1_val
    y2_val = int(y2) if y2 is not None else y1_val

    width = abs(x2_val - x1_val) + 1
    height = abs(y2_val - y1_val) + 1
    if width > MAX_FARM_PLOT_W or height > MAX_FARM_PLOT_H:
        return {"ok": False, "error": "rect_too_large"}

    try:
        return run_lua_file(
            _hook_path("build_farm_plot.lua"),
            str(x1_val),
            str(y1_val),
            str(z_val),
            str(x2_val),
            str(y2_val),
            timeout=10.0,
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def set_farm_crop(
    building_id: int,
    crop: str,
    seasons: Sequence[str] | None = None,
) -> Dict[str, object]:
    """Set (or clear) the seasonal crop selection on an existing farm plot.

    Mirrors the player's q-menu crop picker: writes a plant raw index into
    ``df.building_farmplotst.plant_id[season]`` (``crop='clear'`` writes -1).
    The hook never plants a seed or advances any job — a dwarf with the
    farming labor plants a matching seed over real time. Bounded params:
    seasons are whitelisted to the four names; the crop token is length-bound
    and resolved to a raw index inside the hook (unknown tokens are rejected
    there as ``crop_not_found``).
    """

    try:
        building_id_val = int(building_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_building_id"}

    crop_token = str(crop or "").strip()
    if not crop_token or len(crop_token) > MAX_CROP_TOKEN_LEN:
        return {"ok": False, "error": "invalid_crop"}

    if seasons is None:
        season_list: list[str] = []
    else:
        season_list = [str(s).strip().lower() for s in seasons]
        for season in season_list:
            if season not in FARM_SEASONS:
                return {"ok": False, "error": "invalid_season"}
        if not season_list:
            return {"ok": False, "error": "invalid_season"}

    seasons_csv = ",".join(season_list)

    try:
        return run_lua_file(
            _hook_path("set_farm_crop.lua"),
            str(building_id_val),
            crop_token,
            seasons_csv,
            timeout=10.0,
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def designate_rect(
    kind: str, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int
) -> Dict[str, object]:
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
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def unsuspend_jobs(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> Dict[str, object]:
    """Clear the suspended flag on construction/build jobs inside a bounded rect.

    Mirrors a player's q-menu unsuspend action. Does not complete any work —
    a dwarf must still path to and perform the job over real time. Bounded to
    a single z-level, 10x10 tiles max (same cap as build_construction).
    """

    if int(z1) != int(z2):
        return {"ok": False, "error": "z_span_not_supported"}

    width = abs(int(x2) - int(x1)) + 1
    height = abs(int(y2) - int(y1)) + 1
    if width > 10 or height > 10:
        return {"ok": False, "error": "rect_too_large"}

    try:
        return run_lua_file(
            _hook_path("unsuspend_jobs.lua"),
            str(int(x1)),
            str(int(y1)),
            str(int(z1)),
            str(int(x2)),
            str(int(y2)),
            str(int(z2)),
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def set_labor(unit_id: int, labor: str, enable: bool) -> Dict[str, object]:
    """Flip one whitelisted labor on one citizen (player's v-p-l toggle).

    Mirrors ``u.status.labors[df.unit_labor.X] = enable`` — it lets a matching
    queued job be taken by that citizen but completes no work itself; a dwarf
    must still path to and perform the job over real time. ``labor`` must be a
    whitelisted friendly name; the hook independently guards the enum on the
    live DF build and reports ``unsupported_labor`` if it is absent. Never
    mutates tiles, buildings, or any other unit field.
    """

    if labor not in LABOR_WHITELIST:
        return {"ok": False, "error": "unsupported_labor", "labor": labor}
    try:
        unit_id_int = int(unit_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_unit_id"}

    try:
        return run_lua_file(
            _hook_path("set_labor.lua"),
            str(unit_id_int),
            str(labor),
            "1" if enable else "0",
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def complete_dig_rect(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> Dict[str, object]:
    """Complete bounded DFHack dig designations by converting wall tiles to floors."""

    width = abs(int(x2) - int(x1)) + 1
    height = abs(int(y2) - int(y1)) + 1
    if int(z1) != int(z2):
        return {"ok": False, "error": "z_span_not_supported"}
    if width > MAX_RECT_W or height > MAX_RECT_H:
        return {"ok": False, "error": "rect_too_large"}

    try:
        return run_lua_file(
            _hook_path("complete_dig_rect.lua"),
            str(int(x1)),
            str(int(y1)),
            str(int(z1)),
            str(int(x2)),
            str(int(y2)),
            str(int(z2)),
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def read_work_metrics(rect: tuple[int, int, int, int, int, int] | None = None) -> Dict[str, object]:
    """Read bounded live work metrics for a target rectangle."""

    x1, y1, z1, x2, y2, z2 = rect or _work_rect_from_env()
    width = abs(int(x2) - int(x1)) + 1
    height = abs(int(y2) - int(y1)) + 1
    if int(z1) != int(z2):
        return {"ok": False, "error": "z_span_not_supported"}
    if width > MAX_RECT_W or height > MAX_RECT_H:
        return {"ok": False, "error": "rect_too_large"}

    try:
        return run_lua_file(
            _hook_path("work_metrics.lua"),
            str(int(x1)),
            str(int(y1)),
            str(int(z1)),
            str(int(x2)),
            str(int(y2)),
            str(int(z2)),
        )
    except DFHackError as exc:
        return {"ok": False, "error": str(exc)}


def read_job_metrics(
    rect: tuple[int, int, int, int, int, int] | None = None,
) -> Dict[str, object]:
    """Read bounded, read-only crew/job/workshop observability metrics.

    ``rect`` optionally adds a tile-composition report for that area (same
    30x30 single-z bounds as the other helpers). Never mutates game state.
    """

    args: list[str] = []
    if rect is not None:
        x1, y1, z1, x2, y2, z2 = rect
        width = abs(int(x2) - int(x1)) + 1
        height = abs(int(y2) - int(y1)) + 1
        if int(z1) != int(z2):
            return {"ok": False, "error": "z_span_not_supported"}
        if width > MAX_RECT_W or height > MAX_RECT_H:
            return {"ok": False, "error": "rect_too_large"}
        args = [str(int(v)) for v in (x1, y1, z1, x2, y2, z2)]

    try:
        return run_lua_file(_hook_path("job_metrics.lua"), *args, timeout=5.0)
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def start_g7_evidence(run_id: str) -> Dict[str, object]:
    """Start a run-scoped, read-only survival evidence ledger in DFHack."""

    try:
        return run_lua_file(_hook_path("g7_evidence.lua"), "start", str(run_id), timeout=5.0)
    except (DFHackError, OSError) as exc:
        return {"ok": False, "active": False, "error": str(exc)}


def read_g7_evidence() -> Dict[str, object]:
    """Read cumulative G7 production, consumption, and death evidence."""

    try:
        return run_lua_file(_hook_path("g7_evidence.lua"), "read", timeout=5.0)
    except (DFHackError, OSError) as exc:
        return {"ok": False, "active": False, "error": str(exc)}


def stop_g7_evidence() -> Dict[str, object]:
    """Detach G7 evidence callbacks and return their final snapshot."""

    try:
        return run_lua_file(_hook_path("g7_evidence.lua"), "stop", timeout=5.0)
    except (DFHackError, OSError) as exc:
        return {"ok": False, "active": None, "error": str(exc)}


def read_map_snapshot(rect: tuple[int, int, int, int, int, int]) -> Dict[str, object]:
    """Capture a bounded live DFHack map tile snapshot for replay proof."""

    x1, y1, z1, x2, y2, z2 = rect
    width = abs(int(x2) - int(x1)) + 1
    height = abs(int(y2) - int(y1)) + 1
    if int(z1) != int(z2):
        return {"ok": False, "error": "z_span_not_supported"}
    if width > MAX_SNAPSHOT_W or height > MAX_SNAPSHOT_H:
        return {"ok": False, "error": "rect_too_large"}

    try:
        return run_lua_file(
            _hook_path("map_snapshot.lua"),
            str(int(x1)),
            str(int(y1)),
            str(int(z1)),
            str(int(x2)),
            str(int(y2)),
            str(int(z2)),
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def read_fort_metrics() -> Dict[str, object]:
    """Read plan-agnostic fortress structure metrics (read-only).

    Flood-fills enclosed spaces from player buildings, classifies them
    functionally, and counts player constructions. Anchored on what the
    player actually built — no plan rectangles; works on any seed.
    """

    try:
        return run_lua_file(_hook_path("fort_metrics.lua"), timeout=10.0)
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def read_view_state() -> Dict[str, object]:
    """Read the current DF viewport and cursor without changing game state."""

    try:
        return run_lua_file(_hook_path("view_state.lua"))
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def restore_view_state(view_state: Dict[str, object] | None) -> Dict[str, object]:
    """Best-effort restore for the live DF viewport/cursor."""

    if not view_state or not view_state.get("ok"):
        return {"ok": False, "error": "missing_view_state"}

    try:
        return run_lua_file(
            _hook_path("restore_view_state.lua"),
            str(int(view_state.get("window_x", 0) or 0)),
            str(int(view_state.get("window_y", 0) or 0)),
            str(int(view_state.get("window_z", 0) or 0)),
            str(int(view_state.get("cursor_x", -30000) or -30000)),
            str(int(view_state.get("cursor_y", -30000) or -30000)),
            str(int(view_state.get("cursor_z", -30000) or -30000)),
        )
    except (DFHackError, OSError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def _format_blocked_workshop_targets(
    blocked_workshop_targets: Sequence[Sequence[int]] | None,
) -> str:
    if not blocked_workshop_targets:
        return ""
    tokens: list[str] = []
    for target in blocked_workshop_targets:
        if len(target) < 3:
            continue
        try:
            x, y, z = int(target[0]), int(target[1]), int(target[2])
        except (TypeError, ValueError):
            continue
        tokens.append(f"{x},{y},{z}")
    return ";".join(tokens)


def prepare_keystroke_target(
    mode: str = "starter",
    *,
    blocked_workshop_targets: Sequence[Sequence[int]] | None = None,
) -> Dict[str, object]:
    """Center the live UI on a visible, mineable wall pocket for keystroke runs."""

    try:
        safe_mode = (
            mode if mode in {"starter", "material", "workshop", "existing_workshop"} else "starter"
        )
        return run_lua_file(
            _hook_path("prepare_keystroke_target.lua"),
            safe_mode,
            _format_blocked_workshop_targets(blocked_workshop_targets),
            timeout=10.0,
        )
    except (DFHackError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def _safe_read_pause_state() -> bool | None:
    try:
        return read_pause_state()
    except DFHackError:
        return None


def _set_nopause(enabled: bool) -> None:
    """Best-effort toggle for DFHack nopause mode."""

    try:
        from .config import DFHACK_RUN, DFROOT

        run_dfhack(
            [str(DFHACK_RUN), "nopause", "1" if enabled else "0"],
            timeout=2.0,
            cwd=str(DFROOT),
        )
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

    started_paused = _safe_read_pause_state()

    try:
        start_tick = tick_read()
    except DFHackError as exc:
        return {"ok": False, "error": f"tick_read_failed:{exc}"}

    ok = True
    error: str | None = None
    resume_error: str | None = None
    resume_fallback: str | None = None
    repause_error: str | None = None
    timed_out = False
    current_tick = start_tick
    # Allow ~200ms per tick (conservative for slow headless mode)
    safety_ms = max(10000, want * 200)
    t_start = time.monotonic()

    # Some headless DFHack builds report a stale pause state. Prefer observed tick
    # movement over pause flags, and only try to resume when the clock is stalled.
    _set_nopause(True)
    time.sleep(0.1)
    try:
        current_tick = tick_read()
    except DFHackError as exc:
        return {"ok": False, "error": f"tick_read_failed:{exc}"}
    if current_tick <= start_tick:
        try:
            set_paused(False, timeout=2.5)
        except DFHackError as exc:
            resume_error = str(exc)
        time.sleep(0.1)
        try:
            current_tick = tick_read()
        except DFHackError as exc:
            return {"ok": False, "error": f"tick_read_failed:{exc}"}
        if current_tick <= start_tick and _safe_read_pause_state() is True:
            try:
                fallback_result = execute_keystroke_action(["STRING_A032"])
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                resume_fallback = f"STRING_A032_failed:{exc}"
            else:
                resume_fallback = (
                    "STRING_A032" if fallback_result.get("ok") else str(fallback_result)
                )
            time.sleep(0.1)
            try:
                current_tick = tick_read()
            except DFHackError as exc:
                return {"ok": False, "error": f"tick_read_failed:{exc}"}

    try:
        while True:
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
            time.sleep(0.05)
    finally:
        if repause:
            _set_nopause(False)
            try:
                set_paused(True, timeout=2.5)
            except DFHackError as exc:
                repause_error = str(exc)

    elapsed_ms_int = int((time.monotonic() - t_start) * 1000.0)
    paused_after = _safe_read_pause_state()
    ticks_advanced = max(0, current_tick - start_tick)

    if timed_out:
        ok = False
        error = error or resume_error or "timeout_waiting_for_ticks"
    elif ticks_advanced < want:
        ok = False
        error = error or resume_error or "insufficient_tick_advance"

    result: Dict[str, object] = {
        "ok": ok and error is None,
        "requested": want,
        "ticks_advanced": ticks_advanced,
        "start_tick": start_tick,
        "end_tick": current_tick,
        "paused_before": started_paused,
        "paused_after": paused_after,
        "elapsed_ms": elapsed_ms_int,
        "repause_requested": repause,
        "repause_effective": paused_after is True if repause else None,
    }
    if resume_error:
        result["resume_error"] = resume_error
    if resume_fallback:
        result["resume_fallback"] = resume_fallback
    if repause_error:
        result["repause_error"] = repause_error
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
    "MAX_SNAPSHOT_W",
    "MAX_SNAPSHOT_H",
    "MAX_FARM_PLOT_W",
    "MAX_FARM_PLOT_H",
    "FARM_SEASONS",
    "queue_manager_order",
    "build_workshop",
    "place_furniture",
    "build_construction",
    "build_farm_plot",
    "set_farm_crop",
    "designate_rect",
    "unsuspend_jobs",
    "set_labor",
    "LABOR_WHITELIST",
    "complete_dig_rect",
    "read_work_metrics",
    "read_job_metrics",
    "start_g7_evidence",
    "read_g7_evidence",
    "stop_g7_evidence",
    "read_fort_metrics",
    "read_map_snapshot",
    "prepare_keystroke_target",
    "read_view_state",
    "restore_view_state",
    "advance_ticks_exact_external",
    "advance_ticks_exact",
    "execute_keystroke_action",
]
