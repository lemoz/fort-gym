"""Run loop orchestration utilities."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent.base import Agent
from ..config import get_settings
from ..env.actions import parse_action, validate_action
from ..env.dfhack_client import DFHackClient, DFHackError, DFHackUnavailableError
from ..env.encoder import encode_observation
from ..env.executor import Executor
from ..env.mock_env import MockEnvironment
from ..env.scenarios import evaluate_scenario_assertions, get_mock_scenario
from ..env.state_reader import StateReader
from ..dfhack_backend import prepare_keystroke_target, read_map_snapshot, read_work_metrics
from ..eval import metrics, milestones, scoring
from ..eval.summary import RunSummary, summarize
from .storage import RunRegistry
from .seed_reset import maybe_reset_dfhack_seed

ASSISTED_DFHACK_ACTIONS = {"DIG", "BUILD", "ORDER"}
ASSISTED_PROGRESS_FIELDS = (
    "target_dig_designations_delta",
    "target_floor_tiles_delta",
    "target_wall_tiles_delta",
    "active_dig_jobs_delta",
    "designation_progress",
    "completion_progress",
    "work_progress",
    "manager_orders_delta",
    "manager_order_quantity_delta",
    "carpenter_workshops_delta",
    "utility_action_progress",
    "utility_progress",
    "production_workshops_delta",
    "production_progress",
    "complexity_floor_tiles_delta",
    "complexity_wall_tiles_delta",
    "complexity_spaces_delta",
    "complexity_progress",
    "ui_target_dig_designations_delta",
    "ui_target_floor_tiles_delta",
    "ui_target_floor_removed_delta",
    "ui_target_wall_tiles_delta",
    "ui_designation_progress",
    "ui_completion_progress",
    "ui_excavation_progress",
    "ui_work_progress",
)
UI_WORK_RADIUS = 7
INVALID_DF_CURSOR = -30000
UI_TARGET_REFRESH_NO_PROGRESS_STEPS = 2
UI_TARGET_RECOMMENDED_KEY_RETRY_LIMIT = 2
UI_MATERIAL_TARGET_RECOMMENDED_KEY_RETRY_LIMIT = 2
UI_WORKSHOP_TARGET_RECOMMENDED_KEY_RETRY_LIMIT = 6
UI_EXISTING_WORKSHOP_TARGET_RECOMMENDED_KEY_RETRY_LIMIT = 3
UI_MATERIAL_BLOCKER_ESCAPE_KEYS = ("LEAVESCREEN", "LEAVESCREEN", "LEAVESCREEN")
UI_MATERIAL_TARGET_MIN_EXCAVATION_PROGRESS = 6
KEYSTROKE_MODEL_NAMES = {
    "openrouter-glm-5.2",
}


def _is_keystroke_model(model: str) -> bool:
    normalized = str(model or "").lower()
    return (
        "keystroke" in normalized
        or normalized.endswith("-research")
        or normalized in KEYSTROKE_MODEL_NAMES
    )


def _artifacts_root() -> Path:
    settings = get_settings()
    return Path(settings.ARTIFACTS_DIR).resolve()


def _normalize_rect(value: Any) -> tuple[int, int, int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 6:
        return None
    try:
        x1, y1, z1, x2, y2, z2 = [int(v) for v in value[:6]]
    except (TypeError, ValueError):
        return None
    return (
        min(x1, x2),
        min(y1, y2),
        min(z1, z2),
        max(x1, x2),
        max(y1, y2),
        max(z1, z2),
    )


def _same_target_rect(
    first: Dict[str, Any] | None,
    second: Dict[str, Any] | None,
) -> bool:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    first_rect = _normalize_rect(first.get("target_rect") or first.get("selection_rect"))
    second_rect = _normalize_rect(second.get("target_rect") or second.get("selection_rect"))
    return first_rect is not None and first_rect == second_rect


def _recommended_key_route(target: Dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(target, dict):
        return ()
    keys = target.get("recommended_keys")
    if not isinstance(keys, list):
        return ()
    return tuple(str(key) for key in keys)


def _same_target_route(
    first: Dict[str, Any] | None,
    second: Dict[str, Any] | None,
) -> bool:
    if _same_target_rect(first, second):
        return True
    first_keys = _recommended_key_route(first)
    second_keys = _recommended_key_route(second)
    return bool(first_keys and first_keys == second_keys)


def _map_snapshot_rect_from_state(state: Dict[str, Any], margin: int = 1) -> tuple[int, int, int, int, int, int] | None:
    work = state.get("work")
    if not isinstance(work, dict):
        return None

    rects = [
        rect
        for key in ("target_rect", "fortress_connector_rect", "fortress_workshop_room_rect")
        if (rect := _normalize_rect(work.get(key))) is not None and rect[2] == rect[5]
    ]
    if not rects:
        return None

    z_values = {rect[2] for rect in rects}
    if len(z_values) != 1:
        return None
    z = z_values.pop()
    return (
        min(rect[0] for rect in rects) - margin,
        min(rect[1] for rect in rects) - margin,
        z,
        max(rect[3] for rect in rects) + margin,
        max(rect[4] for rect in rects) + margin,
        z,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stock_total(state: Dict[str, Any]) -> int:
    stocks = state.get("stocks") if isinstance(state.get("stocks"), dict) else {}
    total = 0
    for key in ("food", "drink", "wood", "stone", "wealth"):
        value = _int_or_none(stocks.get(key))
        if value is not None:
            total += max(0, value)
    return total


def _work_read_failed(work: Any) -> bool:
    if not isinstance(work, dict):
        return False
    if work.get("ok") is not False:
        return False
    error = str(work.get("error") or "").lower()
    return any(marker in error for marker in ("timeout", "failed", "error"))


def _read_state_has_live_values(state: Dict[str, Any]) -> bool:
    return (_int_or_none(state.get("population")) or 0) > 0 or _stock_total(state) > 0


def _preserve_state_after_degraded_read(
    state: Dict[str, Any],
    fallback_state: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    """Keep a transient DFHack read failure from erasing real prior state."""

    if not isinstance(state, dict) or not isinstance(fallback_state, dict):
        return state, None
    if not _read_state_has_live_values(fallback_state):
        return state, None

    state_work = state.get("work")
    fallback_work = fallback_state.get("work")
    work_failed = _work_read_failed(state_work)
    top_level_zeroed = not _read_state_has_live_values(state)
    fallback_work_ok = isinstance(fallback_work, dict) and fallback_work.get("ok") is not False

    if not top_level_zeroed and not (work_failed and fallback_work_ok):
        return state, None

    preserved = dict(state)
    preserved_fields: List[str] = []
    if top_level_zeroed:
        for key in (
            "population",
            "stocks",
            "risks",
            "reminders",
            "recent_events",
            "hostiles",
            "dead",
            "map_bounds",
            "workshops",
        ):
            if key in fallback_state:
                preserved[key] = fallback_state[key]
                preserved_fields.append(key)

    if work_failed and fallback_work_ok:
        preserved["work"] = fallback_work
        preserved_fields.append("work")

    if not preserved_fields:
        return state, None

    metadata = {
        "reason": "dfhack_state_read_degraded",
        "preserved_fields": list(dict.fromkeys(preserved_fields)),
        "raw_population": state.get("population"),
        "fallback_population": fallback_state.get("population"),
        "raw_stock_total": _stock_total(state),
        "fallback_stock_total": _stock_total(fallback_state),
    }
    if isinstance(state_work, dict) and state_work.get("error"):
        metadata["work_error"] = state_work.get("error")
    preserved["state_read_preservation"] = metadata
    return preserved, metadata


def _preserve_work_after_degraded_read(
    work: Dict[str, Any],
    fallback_work: Any,
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    if not _work_read_failed(work):
        return work, None
    if not isinstance(fallback_work, dict) or fallback_work.get("ok") is False:
        return work, None

    preserved = dict(fallback_work)
    metadata = {
        "reason": "dfhack_work_read_degraded",
        "raw_error": work.get("error"),
        "preserved_fields": ["ui_work"],
    }
    preserved["state_read_preservation"] = metadata
    return preserved, metadata


def _available_building_materials(state: Dict[str, Any]) -> int:
    stocks = state.get("stocks")
    if not isinstance(stocks, dict):
        return 0
    wood = _int_or_none(stocks.get("wood")) or 0
    stone = _int_or_none(stocks.get("stone")) or 0
    return max(0, wood) + max(0, stone)


def _carpenter_workshops(state: Dict[str, Any]) -> int:
    work = state.get("work")
    if isinstance(work, dict):
        planned = _int_or_none(work.get("carpenter_workshops_planned"))
        if planned is not None:
            return max(0, planned)
        return max(0, _int_or_none(work.get("carpenter_workshops")) or 0)
    return max(0, _int_or_none(state.get("carpenter_workshops")) or 0)


def _unproven_carpenter_workshop_needs_selection(state: Dict[str, Any]) -> bool:
    work = state.get("work")
    if not isinstance(work, dict):
        return False

    planned = _int_or_none(work.get("carpenter_workshops_planned"))
    if planned is None:
        planned = _int_or_none(work.get("carpenter_workshops"))
    usable = _int_or_none(work.get("carpenter_workshops_usable")) or 0
    task_jobs = _int_or_none(work.get("carpenter_workshop_task_jobs")) or 0
    construction_jobs = _int_or_none(work.get("carpenter_workshop_construction_jobs")) or 0
    active_construct_jobs = _int_or_none(work.get("active_construct_building_jobs")) or 0

    return bool(
        (planned or 0) > 0
        and usable <= 0
        and task_jobs <= 0
        and construction_jobs <= 0
        and active_construct_jobs <= 0
    )


def _pending_carpenter_workshop_construction(state: Dict[str, Any]) -> bool:
    work = state.get("work")
    if not isinstance(work, dict):
        return False

    planned = _int_or_none(work.get("carpenter_workshops_planned"))
    if planned is None:
        planned = _int_or_none(work.get("carpenter_workshops"))
    usable = _int_or_none(work.get("carpenter_workshops_usable")) or 0
    task_jobs = _int_or_none(work.get("carpenter_workshop_task_jobs")) or 0
    construction_jobs = _int_or_none(work.get("carpenter_workshop_construction_jobs")) or 0
    active_construct_jobs = _int_or_none(work.get("active_construct_building_jobs")) or 0

    return bool(
        (planned or 0) > 0
        and usable <= 0
        and task_jobs <= 0
        and (construction_jobs > 0 or active_construct_jobs > 0)
    )


def _carry_forward_carpenter_workshop_proof(
    state: Dict[str, Any],
    usable_seen: int,
) -> int:
    work = state.get("work")
    if not isinstance(work, dict):
        return usable_seen

    planned = _int_or_none(work.get("carpenter_workshops_planned"))
    if planned is None:
        planned = _int_or_none(work.get("carpenter_workshops"))
    planned = max(0, planned or 0)
    current_usable = max(0, _int_or_none(work.get("carpenter_workshops_usable")) or 0)
    current_task_jobs = max(0, _int_or_none(work.get("carpenter_workshop_task_jobs")) or 0)

    proof_now = current_usable
    if current_task_jobs > 0:
        proof_now = max(proof_now, planned, 1)
    usable_seen = max(0, usable_seen, proof_now)
    if usable_seen <= current_usable:
        return usable_seen

    work["carpenter_workshops_usable"] = usable_seen
    if planned > 0:
        work["carpenter_workshops_unproven"] = max(0, planned - usable_seen)
    work["carpenter_workshops_usable_carried_forward"] = True
    return usable_seen


def _dict_delta(before: Dict[str, Any], after: Dict[str, Any], key: str) -> int:
    before_value = _int_or_none(before.get(key)) or 0
    after_value = _int_or_none(after.get(key)) or 0
    return after_value - before_value


def _snapshot_tile_key(tile: Dict[str, Any]) -> tuple[int, int, int] | None:
    x = _int_or_none(tile.get("x"))
    y = _int_or_none(tile.get("y"))
    z = _int_or_none(tile.get("z"))
    if x is None or y is None or z is None:
        return None
    return (x, y, z)


def _snapshot_tile_signature(tile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "category": tile.get("category"),
        "char": tile.get("char"),
        "dig": tile.get("dig"),
        "hidden": bool(tile.get("hidden", False)),
        "building": tile.get("building"),
        "building_kind": tile.get("building_kind"),
        "tiletype_name": tile.get("tiletype_name"),
    }


def _snapshot_tile_changes(
    before_snapshot: Dict[str, Any] | None,
    after_snapshot: Dict[str, Any] | None,
    *,
    limit: int = 20,
) -> Dict[str, Any]:
    """Return compact proof of map-tile changes between two DF snapshots."""

    if not (
        isinstance(before_snapshot, dict)
        and isinstance(after_snapshot, dict)
        and before_snapshot.get("ok")
        and after_snapshot.get("ok")
    ):
        return {
            "ok": False,
            "changed_tile_count": 0,
            "changed_tiles": [],
            "truncated": False,
            "reason": "snapshot_unavailable",
        }
    if before_snapshot.get("rect") != after_snapshot.get("rect"):
        return {
            "ok": False,
            "changed_tile_count": 0,
            "changed_tiles": [],
            "truncated": False,
            "reason": "snapshot_rect_changed",
            "before_rect": before_snapshot.get("rect"),
            "after_rect": after_snapshot.get("rect"),
        }

    before_tiles = {
        key: _snapshot_tile_signature(tile)
        for tile in before_snapshot.get("tiles", [])
        if isinstance(tile, dict) and (key := _snapshot_tile_key(tile)) is not None
    }
    after_tiles = {
        key: _snapshot_tile_signature(tile)
        for tile in after_snapshot.get("tiles", [])
        if isinstance(tile, dict) and (key := _snapshot_tile_key(tile)) is not None
    }
    changed_tiles: List[Dict[str, Any]] = []
    for x, y, z in sorted(set(before_tiles) | set(after_tiles)):
        before = before_tiles.get((x, y, z))
        after = after_tiles.get((x, y, z))
        if before == after:
            continue
        changed_tiles.append(
            {
                "x": x,
                "y": y,
                "z": z,
                "before": before,
                "after": after,
            }
        )

    changed_count = len(changed_tiles)
    count_fields = (
        "dig_designations",
        "floor_tiles",
        "wall_tiles",
        "hidden_tiles",
        "building_tiles",
    )
    counts = {
        f"{field}_delta": _dict_delta(before_snapshot, after_snapshot, field)
        for field in count_fields
    }
    return {
        "ok": True,
        "rect": after_snapshot.get("rect"),
        "changed_tile_count": changed_count,
        "changed_tiles": changed_tiles[:limit],
        "truncated": changed_count > limit,
        "snapshot_counts": counts,
    }


def _gameplay_proof(
    *,
    action: Dict[str, Any],
    metrics_snapshot: Dict[str, Any],
    before_map_snapshot: Dict[str, Any] | None,
    after_map_snapshot: Dict[str, Any] | None,
    state_before: Dict[str, Any],
    advance_state: Dict[str, Any],
    tick_info: Dict[str, Any],
    score_value: float,
) -> Dict[str, Any]:
    before_work = state_before.get("work") if isinstance(state_before.get("work"), dict) else {}
    after_work = advance_state.get("work") if isinstance(advance_state.get("work"), dict) else {}
    before_stocks = (
        state_before.get("stocks") if isinstance(state_before.get("stocks"), dict) else {}
    )
    after_stocks = (
        advance_state.get("stocks") if isinstance(advance_state.get("stocks"), dict) else {}
    )
    tile_changes = _snapshot_tile_changes(before_map_snapshot, after_map_snapshot)
    state_deltas = {
        "wood": _dict_delta(before_stocks, after_stocks, "wood"),
        "stone": _dict_delta(before_stocks, after_stocks, "stone"),
        "target_dig_designations": _dict_delta(
            before_work,
            after_work,
            "target_dig_designations",
        ),
        "target_floor_tiles": _dict_delta(before_work, after_work, "target_floor_tiles"),
        "target_wall_tiles": _dict_delta(before_work, after_work, "target_wall_tiles"),
        "active_dig_jobs": _dict_delta(before_work, after_work, "active_dig_jobs"),
        "carpenter_workshops": _dict_delta(before_work, after_work, "carpenter_workshops"),
        "carpenter_workshops_planned": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshops_planned",
        ),
        "carpenter_workshops_usable": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshops_usable",
        ),
        "carpenter_workshop_task_jobs": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshop_task_jobs",
        ),
        "carpenter_workshop_construction_jobs": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshop_construction_jobs",
        ),
        "manager_orders_count": _dict_delta(before_work, after_work, "manager_orders_count"),
        "manager_orders_amount_left": _dict_delta(
            before_work,
            after_work,
            "manager_orders_amount_left",
        ),
    }
    positive_state_deltas = {
        key: value for key, value in state_deltas.items() if value not in (0, None)
    }
    ui_step_work_progress = int(metrics_snapshot.get("ui_step_work_progress") or 0)
    ui_step_excavation_progress = int(
        metrics_snapshot.get("ui_step_excavation_progress") or 0
    )
    ui_step_material_progress = int(
        metrics_snapshot.get("ui_step_material_progress") or 0
    )
    step_gameplay_progress = bool(
        ui_step_work_progress
        or ui_step_excavation_progress
        or ui_step_material_progress
        or tile_changes.get("changed_tile_count")
        or positive_state_deltas
    )
    proof_ok = bool(
        step_gameplay_progress
    )
    return {
        "ok": proof_ok,
        "source": "dfhack-map-and-state",
        "action_type": action.get("type"),
        "keys": action.get("params", {}).get("keys", []),
        "score": score_value,
        "score_provenance": metrics_snapshot.get("score_provenance"),
        "gameplay_progress_eligible": step_gameplay_progress,
        "score_duration_blocked": bool(metrics_snapshot.get("score_duration_blocked", False)),
        "tick_advance": {
            "requested": action.get("advance_ticks"),
            "actual": int(tick_info.get("ticks_advanced") or 0),
        },
        "progress": {
            "work": int(metrics_snapshot.get("work_progress") or 0),
            "designation": int(metrics_snapshot.get("designation_progress") or 0),
            "completion": int(metrics_snapshot.get("completion_progress") or 0),
            "utility": int(metrics_snapshot.get("utility_progress") or 0),
            "production": int(metrics_snapshot.get("production_progress") or 0),
            "complexity": int(metrics_snapshot.get("complexity_progress") or 0),
            "ui_work": ui_step_work_progress,
            "ui_excavation": ui_step_excavation_progress,
            "ui_material": ui_step_material_progress,
            "cumulative_ui_work": int(metrics_snapshot.get("ui_work_progress") or 0),
            "cumulative_ui_excavation": int(
                metrics_snapshot.get("ui_excavation_progress") or 0
            ),
        },
        "state_deltas": positive_state_deltas,
        "tile_changes": tile_changes,
        "changed_tile_count": int(tile_changes.get("changed_tile_count") or 0),
        "changed_tiles": tile_changes.get("changed_tiles", []),
        "truncated_changed_tiles": bool(tile_changes.get("truncated", False)),
    }


def _format_delta(name: str, delta: int) -> str:
    sign = "+" if delta > 0 else ""
    return f"{name}:{sign}{delta}"


def _append_delta(
    changed: List[str],
    productive_reasons: List[str],
    *,
    name: str,
    delta: int,
    positive_reason: str | None = None,
) -> None:
    if delta == 0:
        return
    changed.append(_format_delta(name, delta))
    if delta > 0 and positive_reason:
        productive_reasons.append(positive_reason)


def _keystroke_key_fingerprint(keys: Any) -> str:
    if not isinstance(keys, list) or not keys:
        return "none"
    return " ".join(str(key) for key in keys[:12])


def _keystroke_action_family(action: Dict[str, Any]) -> str:
    keys = action.get("params", {}).get("keys", [])
    key_values = [str(key) for key in keys] if isinstance(keys, list) else []
    key_set = set(key_values)
    intent = str(action.get("intent") or "").lower()
    if "D_DESIGNATE" in key_set:
        return "designation"
    if "D_BUILDING" in key_set:
        return "building_placement_menu"
    if "D_JOBLIST" in key_set or "UNITJOB_MANAGER" in key_set:
        return "job_manager_menu"
    if "D_NOBLES" in key_set or "nobles" in intent or "manager" in intent:
        return "manager_nobles_menu"
    if (
        "D_BUILDJOB" in key_set
        or "BUILDJOB_ADD" in key_set
        or "workshop task" in intent
        or "carpenter workshop" in intent
    ):
        return "workshop_task_menu"
    if "STRING_A032" in key_set:
        return "wait"
    navigation_keys = {
        "LEAVESCREEN",
        "SELECT",
        "CURSOR_UP",
        "CURSOR_DOWN",
        "CURSOR_LEFT",
        "CURSOR_RIGHT",
        "SECONDSCROLL_UP",
        "SECONDSCROLL_DOWN",
        "STANDARDSCROLL_UP",
        "STANDARDSCROLL_DOWN",
        "STANDARDSCROLL_PAGEUP",
        "STANDARDSCROLL_PAGEDOWN",
    }
    if key_values and all(key in navigation_keys for key in key_values):
        return "menu_navigation"
    return key_values[0] if key_values else "none"


def _keystroke_action_history_entry(
    *,
    step: int,
    action: Dict[str, Any],
    requested_ticks: Any,
    tick_info: Dict[str, Any],
    execute_result: Dict[str, Any],
    state_before: Dict[str, Any],
    advance_state: Dict[str, Any],
    metrics_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a compact factual outcome row for the next model observation."""

    before_work = state_before.get("work") if isinstance(state_before.get("work"), dict) else {}
    after_work = advance_state.get("work") if isinstance(advance_state.get("work"), dict) else {}
    before_stocks = (
        state_before.get("stocks") if isinstance(state_before.get("stocks"), dict) else {}
    )
    after_stocks = (
        advance_state.get("stocks") if isinstance(advance_state.get("stocks"), dict) else {}
    )

    changed: List[str] = []
    productive_reasons: List[str] = []

    ui_step_work = int(metrics_snapshot.get("ui_step_work_progress") or 0)
    ui_step_excavation = int(metrics_snapshot.get("ui_step_excavation_progress") or 0)
    ui_step_material = int(metrics_snapshot.get("ui_step_material_progress") or 0)
    _append_delta(
        changed,
        productive_reasons,
        name="ui_work",
        delta=ui_step_work,
        positive_reason="map_tiles_changed",
    )
    if ui_step_excavation > 0:
        productive_reasons.append("excavation_progress")
    _append_delta(
        changed,
        productive_reasons,
        name="building_materials",
        delta=ui_step_material,
        positive_reason="material_acquired",
    )

    for key, reason in (
        ("wood", "wood_stock_changed"),
        ("stone", "stone_stock_changed"),
    ):
        _append_delta(
            changed,
            productive_reasons,
            name=key,
            delta=_dict_delta(before_stocks, after_stocks, key),
            positive_reason=reason,
        )

    for key, reason in (
        ("target_dig_designations", "dig_designated"),
        ("target_floor_tiles", "target_tiles_dug"),
        ("fortress_connector_floor_tiles", "connector_advanced"),
        ("fortress_workshop_room_floor_tiles", "workshop_room_advanced"),
        ("fortress_complexity_spaces_completed", "planned_space_completed"),
        ("manager_orders_count", "manager_order_created"),
        ("manager_orders_amount_left", "manager_order_quantity_added"),
        ("active_jobs", "jobs_started"),
        ("active_dig_jobs", "dig_jobs_started"),
    ):
        _append_delta(
            changed,
            productive_reasons,
            name=key,
            delta=_dict_delta(before_work, after_work, key),
            positive_reason=reason,
        )

    has_workshop_proof_fields = (
        "carpenter_workshops_planned" in before_work
        or "carpenter_workshops_planned" in after_work
        or "carpenter_workshops_usable" in before_work
        or "carpenter_workshops_usable" in after_work
    )
    if has_workshop_proof_fields:
        for key, reason in (
            ("carpenter_workshops_planned", "carpenter_workshop_placed_unproven"),
            ("carpenter_workshops_usable", "carpenter_workshop_usable_proven"),
            ("carpenter_workshop_task_jobs", "workshop_task_job_created"),
            ("carpenter_workshop_construction_jobs", "workshop_construction_job_created"),
            ("workshop_count", "workshop_created_or_queued"),
        ):
            _append_delta(
                changed,
                productive_reasons,
                name=key,
                delta=_dict_delta(before_work, after_work, key),
                positive_reason=reason,
            )
    else:
        for key, reason in (
            ("carpenter_workshops", "carpenter_workshop_created"),
            ("workshop_count", "workshop_created_or_queued"),
        ):
            _append_delta(
                changed,
                productive_reasons,
                name=key,
                delta=_dict_delta(before_work, after_work, key),
                positive_reason=reason,
            )

    # Keep first occurrence of each reason while preserving order.
    productive_reasons = list(dict.fromkeys(productive_reasons))
    actual_ticks = int(tick_info.get("ticks_advanced") or 0)
    accepted = bool(execute_result.get("accepted", execute_result.get("ok", False)))
    if not accepted:
        outcome = "rejected"
    elif productive_reasons:
        outcome = "gameplay_state_changed"
    elif actual_ticks > 0:
        outcome = "advanced_ticks_without_tracked_state_change"
    else:
        outcome = "keys_sent_without_tracked_state_change"

    return {
        "step": step,
        "keys": action.get("params", {}).get("keys", []),
        "key_fingerprint": _keystroke_key_fingerprint(
            action.get("params", {}).get("keys", [])
        ),
        "action_family": _keystroke_action_family(action),
        "intent": action.get("intent", ""),
        "expected_visible_result": action.get("expected_visible_result"),
        "expected_simulation_result": action.get("expected_simulation_result"),
        "screen_read": action.get("screen_read"),
        "last_action_review": action.get("last_action_review"),
        "advance_ticks": action.get("advance_ticks", requested_ticks),
        "requested_ticks": requested_ticks,
        "actual_ticks": actual_ticks,
        "accepted": accepted,
        "outcome": outcome,
        "productive_reasons": productive_reasons,
        "changed": changed,
        "manager_orders_before": _int_or_none(before_work.get("manager_orders_count")) or 0,
        "manager_orders_after": _int_or_none(after_work.get("manager_orders_count")) or 0,
        "order_qty_left_before": _int_or_none(before_work.get("manager_orders_amount_left")) or 0,
        "order_qty_left_after": _int_or_none(after_work.get("manager_orders_amount_left")) or 0,
        "carpenter_workshops_before": _int_or_none(before_work.get("carpenter_workshops")) or 0,
        "carpenter_workshops_after": _int_or_none(after_work.get("carpenter_workshops")) or 0,
        "active_jobs_before": _int_or_none(before_work.get("active_jobs")) or 0,
        "active_jobs_after": _int_or_none(after_work.get("active_jobs")) or 0,
    }


def _desired_keystroke_target_mode(
    state: Dict[str, Any],
    *,
    ui_run_excavation_progress: int,
    ui_run_material_progress: int = 0,
    ui_successful_targets: int,
    build_material_blocked: bool = False,
) -> str:
    if build_material_blocked:
        return "material"
    if _pending_carpenter_workshop_construction(state):
        return "existing_workshop"
    if _unproven_carpenter_workshop_needs_selection(state):
        return "existing_workshop"
    if _carpenter_workshops(state) > 0:
        return "starter"
    enough_starter_space = (
        ui_run_excavation_progress >= UI_MATERIAL_TARGET_MIN_EXCAVATION_PROGRESS
        or ui_successful_targets >= 2
    )
    if (
        _available_building_materials(state) > 0
        and ui_run_material_progress > 0
        and _carpenter_workshops(state) <= 0
        and enough_starter_space
    ):
        return "workshop"
    if _available_building_materials(state) > 0 and not enough_starter_space:
        return "starter"
    if enough_starter_space:
        return "material"
    return "starter"


def _material_exhausted_fallback_target_mode(
    state: Dict[str, Any],
    *,
    ui_run_excavation_progress: int,
    ui_successful_targets: int,
    build_material_blocked: bool = False,
) -> str:
    enough_starter_space = (
        ui_run_excavation_progress >= UI_MATERIAL_TARGET_MIN_EXCAVATION_PROGRESS
        or ui_successful_targets >= 2
    )
    if (
        not build_material_blocked
        and enough_starter_space
        and _available_building_materials(state) > 0
        and _carpenter_workshops(state) <= 0
    ):
        return "workshop"
    return "starter"


def _screen_shows_ready_workshop_placement(screen_text: str | None) -> bool:
    return bool(
        screen_text
        and "Carpenter's Workshop" in screen_text
        and "Placement" in screen_text
        and "Enter: Place" in screen_text
        and "Blocked" not in screen_text
        and "Building present" not in screen_text
        and "Needs building material" not in screen_text
    )


def _screen_shows_workshop_material_selection(screen_text: str | None) -> bool:
    return bool(
        screen_text
        and "Carpenter's Workshop" in screen_text
        and "Item" in screen_text
        and "Dist" in screen_text
        and "Num" in screen_text
        and "Enter: Select" in screen_text
        and "Needs building material" not in screen_text
    )


def _screen_shows_building_type_menu(screen_text: str | None) -> bool:
    return bool(
        screen_text
        and "+-*/: Select" in screen_text
        and "Armor Stand" in screen_text
        and "Bed" in screen_text
        and "Seat" in screen_text
    )


def _workshop_current_screen_select_target(
    state: Dict[str, Any],
    *,
    source: str,
) -> Dict[str, Any]:
    work = state.get("work") if isinstance(state.get("work"), dict) else {}
    cursor_x = int(work.get("cursor_x") or 0)
    cursor_y = int(work.get("cursor_y") or 0)
    cursor_z = int(work.get("cursor_z") or 0)
    if cursor_x <= -10000:
        cursor_x = int(work.get("window_x") or 0)
    selection_rect = [
        cursor_x,
        cursor_y,
        cursor_z,
        cursor_x + 2,
        cursor_y + 2,
        cursor_z,
    ]
    return {
        "ok": True,
        "target_mode": "workshop",
        "source": source,
        "selection_rect": selection_rect,
        "target_rect": selection_rect,
        "designatable_tiles": 9,
        "recommended_keys": ["SELECT"],
    }


def _workshop_placement_confirm_target(state: Dict[str, Any]) -> Dict[str, Any]:
    return _workshop_current_screen_select_target(
        state,
        source="visible_workshop_placement",
    )


def _ui_work_rect_from_state(
    state: Dict[str, Any],
    radius: int = UI_WORK_RADIUS,
) -> tuple[int, int, int, int, int, int] | None:
    """Choose a fixed live UI work rectangle around the starting cursor."""

    work = state.get("work")
    if not isinstance(work, dict):
        return None

    cursor_x = _int_or_none(work.get("cursor_x"))
    cursor_y = _int_or_none(work.get("cursor_y"))
    cursor_z = _int_or_none(work.get("cursor_z"))
    if (
        cursor_x is not None
        and cursor_y is not None
        and cursor_z is not None
        and cursor_x > INVALID_DF_CURSOR
        and cursor_y > INVALID_DF_CURSOR
        and cursor_z > INVALID_DF_CURSOR
    ):
        center_x, center_y, z = cursor_x, cursor_y, cursor_z
    else:
        window_x = _int_or_none(work.get("window_x"))
        window_y = _int_or_none(work.get("window_y"))
        window_z = _int_or_none(work.get("window_z"))
        if window_x is None or window_y is None or window_z is None:
            return None
        center_x = window_x + radius
        center_y = window_y + radius
        z = window_z

    return (
        max(0, center_x - radius),
        max(0, center_y - radius),
        z,
        max(0, center_x + radius),
        max(0, center_y + radius),
        z,
    )


def _ui_target_setup_for_observation(
    target: Dict[str, Any],
    *,
    generation: int,
    attempts: int,
    no_progress_streak: int,
    target_progress_seen: bool,
    recommended_key_prefix: List[str] | None = None,
    force_show_recommended: bool = False,
    recommended_keys_exit_only: bool = False,
) -> Dict[str, Any]:
    setup = dict(target)
    target_mode = str(setup.get("target_mode") or "starter")
    if target_mode == "material":
        retry_limit = UI_MATERIAL_TARGET_RECOMMENDED_KEY_RETRY_LIMIT
    elif target_mode == "workshop":
        retry_limit = UI_WORKSHOP_TARGET_RECOMMENDED_KEY_RETRY_LIMIT
    elif target_mode == "existing_workshop":
        retry_limit = UI_EXISTING_WORKSHOP_TARGET_RECOMMENDED_KEY_RETRY_LIMIT
    else:
        retry_limit = UI_TARGET_RECOMMENDED_KEY_RETRY_LIMIT
    show_recommended = (
        force_show_recommended
        or attempts == 0
        or (
            not target_progress_seen
            and attempts < retry_limit
        )
    )
    setup["target_generation"] = generation
    setup["target_attempts"] = attempts
    setup["no_progress_streak"] = no_progress_streak
    setup["target_progress_seen"] = target_progress_seen
    setup["recommended_key_retry_limit"] = retry_limit
    setup["show_recommended_keys"] = show_recommended
    if show_recommended:
        original_keys = setup.get("recommended_keys")
        if isinstance(original_keys, list):
            prefix = list(recommended_key_prefix or [])
            if recommended_keys_exit_only and prefix:
                setup["recommended_keys"] = prefix
            else:
                setup["recommended_keys"] = prefix + list(original_keys)
            setup["recommended_key_prefix"] = prefix
            setup["recommended_keys_exit_only"] = bool(
                recommended_keys_exit_only and prefix
            )
        setup["recommended_keys_suppressed"] = False
        setup["recommended_keys_retry"] = attempts > 0
        setup["recommended_keys_force_shown"] = force_show_recommended
    else:
        setup["recommended_keys"] = []
        setup["recommended_key_prefix"] = []
        setup["recommended_keys_exit_only"] = False
        setup["recommended_keys_suppressed"] = True
        setup["recommended_keys_retry"] = False
        setup["recommended_keys_force_shown"] = False
    return setup


def _is_exit_only_recovery_action(action: Dict[str, Any]) -> bool:
    keys = action.get("params", {}).get("keys", [])
    return bool(
        action.get("type") == "KEYSTROKE"
        and isinstance(keys, list)
        and keys
        and all(str(key) == "LEAVESCREEN" for key in keys)
        and int(action.get("advance_ticks") or 0) == 0
    )


def _ui_target_step_succeeded(
    target_mode: str,
    *,
    ui_step_work_progress: int,
    ui_step_material_progress: int,
) -> bool:
    """Return whether the current UI target actually achieved its phase goal."""
    if target_mode == "material":
        return ui_step_material_progress > 0
    return ui_step_work_progress > 0 or ui_step_material_progress > 0


def _keystroke_real_state_deltas(
    state_before: Dict[str, Any],
    advance_state: Dict[str, Any],
) -> Dict[str, int]:
    """Return state deltas that represent real game progress, not target movement."""

    before_work = state_before.get("work") if isinstance(state_before.get("work"), dict) else {}
    after_work = advance_state.get("work") if isinstance(advance_state.get("work"), dict) else {}
    before_stocks = (
        state_before.get("stocks") if isinstance(state_before.get("stocks"), dict) else {}
    )
    after_stocks = (
        advance_state.get("stocks") if isinstance(advance_state.get("stocks"), dict) else {}
    )
    deltas = {
        "wood": _dict_delta(before_stocks, after_stocks, "wood"),
        "stone": _dict_delta(before_stocks, after_stocks, "stone"),
        "wealth": _dict_delta(before_stocks, after_stocks, "wealth"),
        "active_dig_jobs": _dict_delta(before_work, after_work, "active_dig_jobs"),
        "active_construct_building_jobs": _dict_delta(
            before_work,
            after_work,
            "active_construct_building_jobs",
        ),
        "active_carpenter_jobs": _dict_delta(before_work, after_work, "active_carpenter_jobs"),
        "active_jobs": _dict_delta(before_work, after_work, "active_jobs"),
        "carpenter_workshops": _dict_delta(before_work, after_work, "carpenter_workshops"),
        "carpenter_workshops_planned": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshops_planned",
        ),
        "carpenter_workshops_usable": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshops_usable",
        ),
        "carpenter_workshop_task_jobs": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshop_task_jobs",
        ),
        "carpenter_workshop_construction_jobs": _dict_delta(
            before_work,
            after_work,
            "carpenter_workshop_construction_jobs",
        ),
        "manager_orders_count": _dict_delta(before_work, after_work, "manager_orders_count"),
        "manager_orders_amount_left": _dict_delta(
            before_work,
            after_work,
            "manager_orders_amount_left",
        ),
    }
    return {key: value for key, value in deltas.items() if value not in (0, None)}


def _keystroke_step_score_progress(
    metrics_snapshot: Dict[str, Any],
    *,
    state_before: Dict[str, Any] | None = None,
    advance_state: Dict[str, Any] | None = None,
) -> bool:
    """Return whether the current keystroke turn should be allowed to score time."""

    for field in (
        "ui_step_work_progress",
        "ui_step_excavation_progress",
        "ui_step_material_progress",
        "production_progress",
        "utility_action_progress",
    ):
        if int(metrics_snapshot.get(field) or 0) > 0:
            return True
    if state_before is not None and advance_state is not None:
        return bool(_keystroke_real_state_deltas(state_before, advance_state))
    return False


def _zero_assisted_dfhack_progress(metrics_snapshot: Dict[str, Any]) -> None:
    assisted_values: Dict[str, Any] = {}
    for field in ASSISTED_PROGRESS_FIELDS:
        value = metrics_snapshot.get(field)
        if value not in (None, 0, 0.0):
            assisted_values[field] = value
        metrics_snapshot[field] = 0

    metrics_snapshot["dfhack_assisted_progress"] = True
    metrics_snapshot["gameplay_progress_eligible"] = False
    metrics_snapshot["score_provenance"] = "gameplay_only_assisted_progress_zeroed"
    if assisted_values:
        metrics_snapshot["assisted_dfhack_progress"] = assisted_values


def run_once(
    agent: Agent,
    *,
    backend: str = "mock",
    env: Optional[str] = None,
    model: str = "unknown",
    max_steps: int = 5,
    ticks_per_step: int = 100,
    run_id: Optional[str] = None,
    registry: Optional[RunRegistry] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    scenario: Optional[str] = None,
    preserve_save: bool = False,
) -> str:
    """Execute a run and persist a JSONL trace while streaming events."""

    settings = get_settings()
    backend_name = env or backend
    if scenario and backend_name != "mock":
        raise ValueError("Scenarios are currently supported only by the mock backend")
    ticks = ticks_per_step if ticks_per_step is not None else settings.TICKS_PER_STEP
    run_identifier = run_id or uuid.uuid4().hex
    artifacts_dir = _artifacts_root() / run_identifier
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    trace_path = artifacts_dir / "trace.jsonl"

    if registry:
        record = registry.get(run_identifier)
        if record is None:
            record = registry.create(
                backend=backend_name,
                model=model,
                max_steps=max_steps,
                ticks_per_step=ticks,
                loop=loop,
                run_id=run_identifier,
                preserve_save=preserve_save,
            )
        elif loop is not None:
            registry.bind_loop(run_identifier, loop)
        registry.set_status(
            run_identifier,
            status="running",
            step=0,
            started_at=datetime.utcnow(),
        )

    executor = Executor()
    dfhack_client: Optional[DFHackClient] = None

    tick_info_state: Dict[str, Any] = {}
    elapsed_ticks_total = 0

    # Detect models that need screen capture and native UI keystroke scaffolding.
    is_keystroke_mode = _is_keystroke_model(model)
    keystroke_ui_target: Optional[Dict[str, Any]] = None
    ui_target_mode = "starter"
    ui_target_generation = 0
    ui_target_attempts = 0

    def get_screen_text() -> str:
        """Get screen text for keystroke mode, empty string otherwise."""
        return ""

    if backend_name == "mock":
        mock_env = MockEnvironment(scenario_name=scenario)
        mock_env.reset(seed=123)
        executor = Executor(mock_env=mock_env)

        def pause_env() -> None:
            return None

        def observe() -> Dict[str, Any]:
            return mock_env.observe()

        def apply_action(action_dict: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
            return executor.apply(action_dict, backend="mock", state=state)

        def advance_env(num_ticks: int) -> Dict[str, Any]:
            nonlocal tick_info_state
            if num_ticks <= 0:
                tick_info_state = {"ok": True, "ticks_advanced": 0, "skipped": True}
                return mock_env.observe()
            result = mock_env.advance(num_ticks)
            tick_info_state = {"ok": True, "ticks_advanced": num_ticks}
            return result

    elif backend_name == "dfhack":
        if not settings.DFHACK_ENABLED:
            raise RuntimeError("DFHack backend disabled. Set DFHACK_ENABLED=1 to use it.")

        # If configured, reset the save from a pristine seed before connecting.
        if not preserve_save:
            maybe_reset_dfhack_seed(settings)

        dfhack_client = DFHackClient(host=settings.DFHACK_HOST, port=settings.DFHACK_PORT)
        try:
            dfhack_client.connect()
        except DFHackUnavailableError:  # pragma: no cover - environment guard
            if registry:
                registry.set_status(
                    run_identifier,
                    status="failed",
                    ended_at=datetime.utcnow(),
                )
            raise
        executor = Executor(dfhack_client=dfhack_client)
        if is_keystroke_mode:
            keystroke_ui_target = prepare_keystroke_target(ui_target_mode)
            if keystroke_ui_target.get("ok"):
                ui_target_generation = 1

        def pause_env() -> None:
            dfhack_client.pause()

        def observe() -> Dict[str, Any]:
            return StateReader.from_dfhack(dfhack_client)

        def apply_action(action_dict: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
            return executor.apply(action_dict, backend="dfhack", state=state)

        def advance_env(num_ticks: int) -> Dict[str, Any]:
            nonlocal tick_info_state
            if num_ticks <= 0:
                tick_info_state = {"ok": True, "ticks_advanced": 0, "skipped": True}
                return StateReader.from_dfhack(dfhack_client)
            state = dfhack_client.advance(num_ticks)
            tick_info_state = dict(dfhack_client.last_tick_info or {})
            return state

        if is_keystroke_mode:
            def get_screen_text() -> str:
                """Get screen text for keystroke mode."""
                try:
                    return dfhack_client.get_screen_text(include_visual_hints=True)
                except Exception:
                    return "(screen capture failed)"

    else:
        raise ValueError(f"Unsupported backend: {backend_name}")

    previous_state: Optional[Dict[str, Any]] = None
    baseline_work: Optional[Dict[str, Any]] = None
    action_history: List[Dict[str, Any]] = []  # Track recent actions for keystroke mode memory
    action_history_limit = max(0, int(settings.KEYSTROKE_ACTION_HISTORY_LIMIT))
    last_action_result: Optional[Dict[str, Any]] = None  # Track previous action result for feedback
    previous_screen = None  # Track previous screen for diff feedback (no type annotation for nonlocal)
    assisted_dfhack_action_seen = False
    ui_work_rect: tuple[int, int, int, int, int, int] | None = None
    baseline_ui_work: Optional[Dict[str, Any]] = None
    keystroke_gameplay_progress_seen = False
    ui_no_progress_streak = 0
    ui_last_work_progress = 0
    ui_last_excavation_progress = 0
    ui_target_progress_seen = False
    ui_run_work_progress = 0
    ui_run_excavation_progress = 0
    ui_run_material_progress = 0
    ui_successful_targets = 0
    ui_work_feedback: Dict[str, Any] = {}
    ui_build_material_blocked = False
    ui_material_target_exhausted = False
    carpenter_workshop_usable_seen = 0
    scoreable_elapsed_ticks = 0
    last_keystroke_score_value: float | None = None

    def publish_event(step: int, event_type: str, payload: Dict[str, Any], events: List[Dict[str, Any]]) -> None:
        data = {"run_id": run_identifier, "step": step, **payload}
        events.append({"type": event_type, "data": data})
        if registry:
            registry.append_event(run_identifier, {"t": event_type, "data": data})

    def _dump_model(model: RunSummary) -> Dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()  # type: ignore[attr-defined]

    def _handle_dfhack_failure(step_index: int, message: str, events: List[Dict[str, Any]]) -> None:
        publish_event(step_index, "stderr", {"message": message}, events)

    run_failed = False
    run_stopped = False

    try:
        with trace_path.open("w", encoding="utf-8") as fh:
            for step in range(max_steps):
                events: List[Dict[str, Any]] = []
                tick_info_state = {}
                map_snapshot_before = None

                if registry and registry.stop_requested(run_identifier):
                    run_stopped = True
                    publish_event(step, "stopped", {"reason": "stop_requested"}, events)
                    fh.write(
                        json.dumps(
                            {
                                "run_id": run_identifier,
                                "step": step,
                                "stopped": {"reason": "stop_requested"},
                                "events": events,
                            }
                        )
                        + "\n"
                    )
                    registry.set_status(
                        run_identifier,
                        status="stopped",
                        step=step,
                        ended_at=datetime.utcnow(),
                    )
                    break

                pause_env()
                if (
                    backend_name == "dfhack"
                    and is_keystroke_mode
                    and ui_no_progress_streak >= UI_TARGET_REFRESH_NO_PROGRESS_STEPS
                ):
                    refreshed_target = prepare_keystroke_target(ui_target_mode)
                    if refreshed_target.get("ok"):
                        if ui_target_mode == "material" and _same_target_route(
                            keystroke_ui_target,
                            refreshed_target,
                        ):
                            starter_target = prepare_keystroke_target("starter")
                            if starter_target.get("ok"):
                                ui_material_target_exhausted = True
                                ui_target_mode = "starter"
                                keystroke_ui_target = starter_target
                                ui_target_generation += 1
                                ui_target_attempts = 0
                                ui_work_rect = None
                                baseline_ui_work = None
                                ui_last_work_progress = 0
                                ui_last_excavation_progress = 0
                                ui_target_progress_seen = False
                                ui_no_progress_streak = 0
                                ui_work_feedback = {
                                    "target_refreshed": True,
                                    "target_mode": ui_target_mode,
                                    "reason": (
                                        "material target repeated with no usable "
                                        "material; switching back to starter excavation"
                                    ),
                                    "material_target_exhausted": True,
                                    "refresh_after_no_progress_steps": UI_TARGET_REFRESH_NO_PROGRESS_STEPS,
                                }
                            else:
                                ui_work_feedback = {
                                    "target_refresh_failed": True,
                                    "error": starter_target.get("error", "unknown"),
                                    "target_mode": "starter",
                                    "previous_target_mode": ui_target_mode,
                                    "material_target_exhausted": True,
                                    "no_progress_streak": ui_no_progress_streak,
                                }
                        else:
                            keystroke_ui_target = refreshed_target
                            ui_target_generation += 1
                            ui_target_attempts = 0
                            ui_work_rect = None
                            baseline_ui_work = None
                            ui_last_work_progress = 0
                            ui_last_excavation_progress = 0
                            ui_target_progress_seen = False
                            ui_no_progress_streak = 0
                            ui_work_feedback = {
                                "target_refreshed": True,
                                "target_mode": ui_target_mode,
                                "reason": "previous target produced no new UI work",
                                "refresh_after_no_progress_steps": UI_TARGET_REFRESH_NO_PROGRESS_STEPS,
                            }
                    else:
                        ui_work_feedback = {
                            "target_refresh_failed": True,
                            "error": refreshed_target.get("error", "unknown"),
                            "target_mode": ui_target_mode,
                            "no_progress_streak": ui_no_progress_streak,
                        }

                def call_with_retry(label: str, func):
                    if backend_name != "dfhack":
                        return func()
                    try:
                        return func()
                    except DFHackError as exc:
                        _handle_dfhack_failure(step, f"{label} failed: {exc}", events)
                        try:
                            return func()
                        except DFHackError as final_exc:
                            _handle_dfhack_failure(step, f"{label} failed again: {final_exc}", events)
                            raise

                try:
                    state_before = call_with_retry("observe", observe)
                except DFHackError:
                    if registry:
                        registry.set_status(
                            run_identifier,
                            status="failed",
                            ended_at=datetime.utcnow(),
                        )
                    break
                if is_keystroke_mode:
                    carpenter_workshop_usable_seen = _carry_forward_carpenter_workshop_proof(
                        state_before,
                        carpenter_workshop_usable_seen,
                    )
                screen_text = get_screen_text() if is_keystroke_mode else None
                screen_has_material_blocker = bool(
                    is_keystroke_mode
                    and screen_text
                    and "Needs building material" in screen_text
                )
                screen_has_ready_workshop_placement = _screen_shows_ready_workshop_placement(
                    screen_text if is_keystroke_mode else None
                )
                screen_has_workshop_material_selection = (
                    _screen_shows_workshop_material_selection(
                        screen_text if is_keystroke_mode else None
                    )
                )
                screen_has_building_type_menu = _screen_shows_building_type_menu(
                    screen_text if is_keystroke_mode else None
                )
                if screen_has_material_blocker:
                    ui_build_material_blocked = True
                elif screen_has_ready_workshop_placement or screen_has_workshop_material_selection:
                    ui_build_material_blocked = False
                if backend_name == "dfhack" and is_keystroke_mode:
                    if screen_has_ready_workshop_placement or screen_has_workshop_material_selection:
                        ui_target_mode = "workshop"
                        source = (
                            "visible_workshop_material_selection"
                            if screen_has_workshop_material_selection
                            else "visible_workshop_placement"
                        )
                        keystroke_ui_target = _workshop_current_screen_select_target(
                            state_before,
                            source=source,
                        )
                        ui_target_attempts = 0
                        ui_work_rect = None
                        baseline_ui_work = None
                        ui_target_progress_seen = False
                        ui_no_progress_streak = 0
                    else:
                        desired_target_mode = _desired_keystroke_target_mode(
                            state_before,
                            ui_run_excavation_progress=ui_run_excavation_progress,
                            ui_run_material_progress=ui_run_material_progress,
                            ui_successful_targets=ui_successful_targets,
                            build_material_blocked=ui_build_material_blocked,
                        )
                        if (
                            ui_material_target_exhausted
                            and desired_target_mode == "material"
                        ):
                            desired_target_mode = _material_exhausted_fallback_target_mode(
                                state_before,
                                ui_run_excavation_progress=ui_run_excavation_progress,
                                ui_successful_targets=ui_successful_targets,
                                build_material_blocked=ui_build_material_blocked,
                            )
                        if desired_target_mode != ui_target_mode:
                            refreshed_target = prepare_keystroke_target(desired_target_mode)
                            if refreshed_target.get("ok"):
                                ui_target_mode = desired_target_mode
                                keystroke_ui_target = refreshed_target
                                ui_target_generation += 1
                                ui_target_attempts = 0
                                ui_work_rect = None
                                baseline_ui_work = None
                                ui_last_work_progress = 0
                                ui_last_excavation_progress = 0
                                ui_target_progress_seen = False
                                ui_no_progress_streak = 0
                                if ui_target_mode == "material":
                                    refresh_reason = "switching to material acquisition target"
                                elif ui_target_mode == "existing_workshop":
                                    refresh_reason = "switching to existing workshop inspection target"
                                elif ui_target_mode == "workshop":
                                    refresh_reason = "switching to workshop placement target"
                                else:
                                    refresh_reason = "switching to starter excavation target"
                                ui_work_feedback = {
                                    "target_refreshed": True,
                                    "target_mode": ui_target_mode,
                                    "reason": refresh_reason,
                                }
                            else:
                                ui_work_feedback = {
                                    "target_refresh_failed": True,
                                    "target_mode": desired_target_mode,
                                    "error": refreshed_target.get("error", "unknown"),
                                }
                    if keystroke_ui_target is not None:
                        material_needs_menu_escape = (
                            ui_target_mode == "material"
                            and (screen_has_material_blocker or screen_has_building_type_menu)
                        )
                        recovery_prefix = (
                            list(UI_MATERIAL_BLOCKER_ESCAPE_KEYS)
                            if material_needs_menu_escape
                            else []
                        )
                        state_before["ui_target_setup"] = _ui_target_setup_for_observation(
                            keystroke_ui_target,
                            generation=ui_target_generation,
                            attempts=ui_target_attempts,
                            no_progress_streak=ui_no_progress_streak,
                            target_progress_seen=ui_target_progress_seen,
                            recommended_key_prefix=recovery_prefix,
                            force_show_recommended=bool(recovery_prefix),
                            recommended_keys_exit_only=bool(recovery_prefix),
                        )
                    if ui_work_rect is None:
                        prepared_rect = None
                        if keystroke_ui_target and keystroke_ui_target.get("ok"):
                            prepared_rect = _normalize_rect(keystroke_ui_target.get("target_rect"))
                        ui_work_rect = (
                            prepared_rect
                            if prepared_rect is not None and prepared_rect[2] == prepared_rect[5]
                            else _ui_work_rect_from_state(state_before)
                        )
                    if ui_work_rect is not None:
                        ui_work_before = read_work_metrics(ui_work_rect)
                        state_before["ui_work"] = ui_work_before
                        map_snapshot_before = read_map_snapshot(ui_work_rect)
                        if baseline_ui_work is None and ui_work_before.get("ok"):
                            baseline_ui_work = dict(ui_work_before)
                    if ui_work_feedback:
                        state_before["ui_work_feedback"] = dict(ui_work_feedback)
                    if ui_build_material_blocked:
                        state_before["ui_build_feedback"] = {
                            "material_blocked": True,
                            "visible": screen_has_material_blocker,
                            "menu_escape_keys": (
                                list(UI_MATERIAL_BLOCKER_ESCAPE_KEYS)
                                if screen_has_material_blocker
                                else []
                            ),
                            "message": (
                                "visible build screen requires material; exit build menus and acquire/chop/mine material before retrying construction"
                                if screen_has_material_blocker
                                else "previous build screen required material; acquire/chop/mine material before retrying construction"
                            ),
                        }
                    state_before["ui_run_progress"] = {
                        "total_work_delta": ui_run_work_progress,
                        "total_excavation_delta": ui_run_excavation_progress,
                        "total_material_delta": ui_run_material_progress,
                        "successful_targets": ui_successful_targets,
                    }
                if baseline_work is None:
                    work_snapshot = state_before.get("work")
                    baseline_work = dict(work_snapshot) if isinstance(work_snapshot, dict) else {}

                obs_text, obs_json = encode_observation(
                    state_before,
                    screen_text=screen_text,
                    action_history=action_history if is_keystroke_mode else None,
                    last_action_result=last_action_result,
                    previous_screen=previous_screen if is_keystroke_mode else None,
                )
                # Update previous_screen for next step's diff
                if is_keystroke_mode:
                    previous_screen = screen_text
                publish_event(step, "state", {"state": obs_json, "text": obs_text}, events)

                if registry and registry.stop_requested(run_identifier):
                    run_stopped = True
                    publish_event(
                        step,
                        "stopped",
                        {"reason": "stop_requested_before_agent_decide"},
                        events,
                    )
                    fh.write(
                        json.dumps(
                            {
                                "run_id": run_identifier,
                                "step": step,
                                "observation": obs_json,
                                "observation_text": obs_text,
                                "stopped": {
                                    "reason": "stop_requested_before_agent_decide"
                                },
                                "events": events,
                            }
                        )
                        + "\n"
                    )
                    registry.set_status(
                        run_identifier,
                        status="stopped",
                        step=step,
                        ended_at=datetime.utcnow(),
                    )
                    break

                try:
                    raw_action = agent.decide(obs_text, obs_json)
                except Exception as exc:
                    tool_events = []
                    pop_tool_events = getattr(agent, "pop_tool_events", None)
                    if callable(pop_tool_events):
                        try:
                            tool_events = pop_tool_events()
                        except Exception as pop_exc:  # pragma: no cover - defensive logging
                            tool_events = [
                                {
                                    "tool": "agent.pop_tool_events",
                                    "input": {},
                                    "output": {
                                        "error": type(pop_exc).__name__,
                                        "message": str(pop_exc),
                                    },
                                }
                            ]
                    for tool_event in tool_events:
                        publish_event(
                            step,
                            "tool_call",
                            {
                                "tool": tool_event.get("tool"),
                                "input": tool_event.get("input"),
                                "output": tool_event.get("output"),
                            },
                            events,
                        )
                    error_payload = {
                        "stage": "agent_decide",
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    publish_event(step, "error", error_payload, events)
                    fh.write(
                        json.dumps(
                            {
                                "run_id": run_identifier,
                                "step": step,
                                "observation": obs_json,
                                "observation_text": obs_text,
                                "error": error_payload,
                                "events": events,
                            }
                        )
                        + "\n"
                    )
                    run_failed = True
                    if registry:
                        registry.set_status(
                            run_identifier,
                            status="failed",
                            step=step,
                            ended_at=datetime.utcnow(),
                        )
                    break

                if registry and registry.stop_requested(run_identifier):
                    run_stopped = True
                    publish_event(
                        step,
                        "stopped",
                        {"reason": "stop_requested_after_agent_decide"},
                        events,
                    )
                    fh.write(
                        json.dumps(
                            {
                                "run_id": run_identifier,
                                "step": step,
                                "observation": obs_json,
                                "observation_text": obs_text,
                                "raw_action": raw_action,
                                "stopped": {
                                    "reason": "stop_requested_after_agent_decide"
                                },
                                "events": events,
                            }
                        )
                        + "\n"
                    )
                    registry.set_status(
                        run_identifier,
                        status="stopped",
                        step=step,
                        ended_at=datetime.utcnow(),
                    )
                    break

                tool_events = agent.pop_tool_events()
                for tool_event in tool_events:
                    publish_event(
                        step,
                        "tool_call",
                        {
                            "tool": tool_event.get("tool"),
                            "input": tool_event.get("input"),
                            "output": tool_event.get("output"),
                        },
                        events,
                    )
                publish_event(step, "action", {"raw": raw_action}, events)

                if not isinstance(raw_action, dict):
                    raise TypeError("Agent must return a dictionary action")

                if isinstance(raw_action, list) or any(k in raw_action for k in ("actions", "plan")):
                    reason = "Multiple actions are not supported"
                    validation = {"valid": False, "reason": reason}
                    publish_event(step, "validation", validation, events)
                    last_action_result = {"accepted": False, "reason": reason}
                    record_line = {
                        "run_id": run_identifier,
                        "step": step,
                        "observation": obs_json,
                        "observation_text": obs_text,
                        "raw_action": raw_action,
                        "validation": validation,
                        "events": events,
                    }
                    fh.write(json.dumps(record_line) + "\n")
                    if registry:
                        registry.set_status(run_identifier, step=step)
                    continue

                try:
                    action = parse_action(raw_action)
                except (TypeError, ValueError) as exc:
                    validation = {"valid": False, "reason": str(exc)}
                    publish_event(step, "validation", validation, events)
                    last_action_result = {"accepted": False, "reason": str(exc)}
                    record_line = {
                        "run_id": run_identifier,
                        "step": step,
                        "observation": obs_json,
                        "observation_text": obs_text,
                        "raw_action": raw_action,
                        "validation": validation,
                        "events": events,
                    }
                    fh.write(json.dumps(record_line) + "\n")
                    if registry:
                        registry.set_status(run_identifier, step=step)
                    continue

                valid, reason = validate_action(obs_json, action)
                validation = {"valid": valid, "reason": reason}
                publish_event(step, "validation", validation, events)
                if not valid:
                    last_action_result = {"accepted": False, "reason": reason}
                    record_line = {
                        "run_id": run_identifier,
                        "step": step,
                        "observation": obs_json,
                        "observation_text": obs_text,
                        "action": action,
                        "validation": validation,
                        "events": events,
                    }
                    fh.write(json.dumps(record_line) + "\n")
                    if registry:
                        registry.set_status(run_identifier, step=step)
                    continue

                try:
                    execute_result = call_with_retry("apply", lambda: apply_action(action, obs_json))
                except DFHackError:
                    run_failed = True
                    if registry:
                        registry.set_status(
                            run_identifier,
                            status="failed",
                            ended_at=datetime.utcnow(),
                        )
                    break
                if backend_name == "dfhack" and action.get("type") in ASSISTED_DFHACK_ACTIONS:
                    execute_result = {
                        **execute_result,
                        "provenance": "dfhack_assisted",
                        "gameplay_progress_eligible": False,
                    }
                    if execute_result.get("accepted", False):
                        assisted_dfhack_action_seen = True
                publish_event(step, "execute", {"result": execute_result}, events)
                state_after_apply = execute_result.get("state") or state_before

                # Track action result for next step's feedback
                last_action_result = execute_result
                if (
                    is_keystroke_mode
                    and action.get("type") == "KEYSTROKE"
                    and execute_result.get("accepted", False)
                ):
                    target_setup = state_before.get("ui_target_setup")
                    target_setup_exit_only = (
                        isinstance(target_setup, dict)
                        and bool(target_setup.get("recommended_keys_exit_only"))
                    )
                    if not (
                        target_setup_exit_only and _is_exit_only_recovery_action(action)
                    ):
                        ui_target_attempts += 1

                # Use agent-requested ticks, falling back to default if not specified
                requested_ticks = action.get("advance_ticks", ticks)
                try:
                    advance_state = call_with_retry("advance", lambda: advance_env(requested_ticks))
                except DFHackError:
                    run_failed = True
                    if registry:
                        registry.set_status(
                            run_identifier,
                            status="failed",
                            ended_at=datetime.utcnow(),
                        )
                    break
                state_preservation = None
                if backend_name == "dfhack" and is_keystroke_mode:
                    advance_state, state_preservation = _preserve_state_after_degraded_read(
                        advance_state,
                        state_after_apply,
                    )
                    carpenter_workshop_usable_seen = _carry_forward_carpenter_workshop_proof(
                        advance_state,
                        carpenter_workshop_usable_seen,
                    )
                if backend_name == "dfhack" and is_keystroke_mode and ui_work_rect is not None:
                    ui_work_after = read_work_metrics(ui_work_rect)
                    ui_work_preservation = None
                    fallback_ui_work = (
                        state_after_apply.get("ui_work")
                        if isinstance(state_after_apply, dict)
                        else None
                    )
                    ui_work_after, ui_work_preservation = _preserve_work_after_degraded_read(
                        ui_work_after,
                        fallback_ui_work,
                    )
                    advance_state["ui_work"] = ui_work_after
                    if ui_work_preservation is not None:
                        advance_state["ui_work_read_preservation"] = ui_work_preservation
                    if keystroke_ui_target is not None:
                        advance_state["ui_target_setup"] = _ui_target_setup_for_observation(
                            keystroke_ui_target,
                            generation=ui_target_generation,
                            attempts=ui_target_attempts,
                            no_progress_streak=ui_no_progress_streak,
                            target_progress_seen=ui_target_progress_seen,
                        )
                # Game stays paused - agent controls time
                try:
                    elapsed_ticks_total += max(0, int(tick_info_state.get("ticks_advanced") or 0))
                except (TypeError, ValueError):
                    pass
                publish_event(
                    step,
                    "advance",
                    {"state": advance_state, "tick_advance": tick_info_state},
                    events,
                )
                if state_preservation is not None:
                    publish_event(
                        step,
                        "state_read_preservation",
                        {"state_read_preservation": state_preservation},
                        events,
                    )
                if (
                    backend_name == "dfhack"
                    and is_keystroke_mode
                    and isinstance(advance_state.get("ui_work_read_preservation"), dict)
                ):
                    publish_event(
                        step,
                        "ui_work_read_preservation",
                        {
                            "ui_work_read_preservation": advance_state.get(
                                "ui_work_read_preservation"
                            )
                        },
                        events,
                    )

                metrics_snapshot = metrics.step_snapshot(advance_state)
                current_work = advance_state.get("work")
                metrics_snapshot.update(
                    metrics.work_progress_delta(
                        current_work if isinstance(current_work, dict) else {},
                        baseline_work,
                    )
                )
                metrics_snapshot.update(
                    metrics.utility_progress_delta(
                        current_work if isinstance(current_work, dict) else {},
                        baseline_work,
                    )
                )
                metrics_snapshot.update(
                    metrics.production_progress_delta(
                        current_work if isinstance(current_work, dict) else {},
                        baseline_work,
                    )
                )
                metrics_snapshot.update(
                    metrics.complexity_progress_delta(
                        current_work if isinstance(current_work, dict) else {},
                        baseline_work,
                    )
                )
                current_ui_work = advance_state.get("ui_work")
                ui_delta = {}
                ui_step_work_progress = 0
                ui_step_excavation_progress = 0
                ui_step_material_progress = 0
                if is_keystroke_mode:
                    ui_step_material_progress = max(
                        0,
                        _available_building_materials(advance_state)
                        - _available_building_materials(state_before),
                    )
                    metrics_snapshot["ui_step_material_progress"] = ui_step_material_progress
                if is_keystroke_mode and isinstance(current_ui_work, dict) and baseline_ui_work:
                    ui_delta = metrics.ui_work_progress_delta(current_ui_work, baseline_ui_work)
                    metrics_snapshot.update(ui_delta)
                    ui_total_work_progress = int(ui_delta.get("ui_work_progress") or 0)
                    ui_total_excavation_progress = int(ui_delta.get("ui_excavation_progress") or 0)
                    ui_step_work_progress = max(0, ui_total_work_progress - ui_last_work_progress)
                    ui_step_excavation_progress = max(
                        0,
                        ui_total_excavation_progress - ui_last_excavation_progress,
                    )
                    ui_last_work_progress = max(ui_last_work_progress, ui_total_work_progress)
                    ui_last_excavation_progress = max(
                        ui_last_excavation_progress,
                        ui_total_excavation_progress,
                    )
                    metrics_snapshot["ui_step_work_progress"] = ui_step_work_progress
                    metrics_snapshot["ui_step_excavation_progress"] = ui_step_excavation_progress
                    if int(ui_delta.get("ui_work_progress") or 0) > 0:
                        metrics_snapshot["score_provenance"] = "keystroke_ui_work_rect"
                        metrics_snapshot["gameplay_progress_eligible"] = True
                        metrics_snapshot["ui_work_rect"] = current_ui_work.get("target_rect")
                        metrics_snapshot["designation_progress"] = max(
                            int(metrics_snapshot.get("designation_progress") or 0),
                            int(ui_delta.get("ui_designation_progress") or 0),
                        )
                        metrics_snapshot["completion_progress"] = max(
                            int(metrics_snapshot.get("completion_progress") or 0),
                            int(ui_delta.get("ui_completion_progress") or 0),
                        )
                        metrics_snapshot["work_progress"] = max(
                            int(metrics_snapshot.get("work_progress") or 0),
                            int(ui_delta.get("ui_work_progress") or 0),
                        )
                        keystroke_gameplay_progress_seen = True
                if is_keystroke_mode:
                    advanced_ticks = int(tick_info_state.get("ticks_advanced") or 0)
                    action_accepted = bool(execute_result.get("accepted", False))
                    if action.get("type") == "KEYSTROKE" and action_accepted:
                        requested_ticks_int = _int_or_none(requested_ticks) or 0
                        made_tracked_progress = (
                            ui_step_work_progress > 0 or ui_step_material_progress > 0
                        )
                        target_step_succeeded = _ui_target_step_succeeded(
                            ui_target_mode,
                            ui_step_work_progress=ui_step_work_progress,
                            ui_step_material_progress=ui_step_material_progress,
                        )
                        if made_tracked_progress:
                            if target_step_succeeded and not ui_target_progress_seen:
                                ui_successful_targets += 1
                            if target_step_succeeded:
                                ui_target_progress_seen = True
                            ui_run_work_progress += ui_step_work_progress
                            ui_run_excavation_progress += ui_step_excavation_progress
                            ui_run_material_progress += ui_step_material_progress
                            if ui_step_material_progress > 0:
                                ui_build_material_blocked = False
                                ui_material_target_exhausted = False
                            if target_step_succeeded:
                                ui_no_progress_streak = 0
                            elif ui_target_mode == "material":
                                ui_no_progress_streak += 1
                            ui_work_feedback = {
                                "last_ui_work_progress_delta": ui_step_work_progress,
                                "last_ui_excavation_delta": ui_step_excavation_progress,
                                "last_ui_material_delta": ui_step_material_progress,
                                "no_progress_streak": ui_no_progress_streak,
                                "target_step_succeeded": target_step_succeeded,
                                "message": (
                                    "last UI action changed tracked tiles but did not acquire usable material"
                                    if ui_target_mode == "material" and not target_step_succeeded
                                    else "last UI action changed real map tiles or material stocks"
                                ),
                            }
                        elif advanced_ticks > 0 or requested_ticks_int > 0:
                            ui_no_progress_streak += 1
                            ui_work_feedback = {
                                "last_ui_work_progress_delta": 0,
                                "last_ui_excavation_delta": 0,
                                "last_ui_material_delta": 0,
                                "no_progress_streak": ui_no_progress_streak,
                                "message": "last UI action requested time but changed no tracked tiles or material stocks",
                            }
                        else:
                            ui_work_feedback = {
                                "last_ui_work_progress_delta": 0,
                                "last_ui_excavation_delta": 0,
                                "last_ui_material_delta": 0,
                                "no_progress_streak": ui_no_progress_streak,
                                "message": "last UI action did not advance time",
                            }
                    metrics_snapshot["ui_no_progress_streak"] = ui_no_progress_streak
                    metrics_snapshot["ui_target_generation"] = ui_target_generation
                    metrics_snapshot["ui_target_attempts"] = ui_target_attempts
                    metrics_snapshot["ui_target_progress_seen"] = ui_target_progress_seen
                    metrics_snapshot["ui_run_work_progress"] = ui_run_work_progress
                    metrics_snapshot["ui_run_excavation_progress"] = ui_run_excavation_progress
                    metrics_snapshot["ui_run_material_progress"] = ui_run_material_progress
                    metrics_snapshot["ui_successful_targets"] = ui_successful_targets
                utility_action = metrics.utility_action_progress(action, execute_result)
                metrics_snapshot.update(utility_action)
                metrics_snapshot["utility_progress"] = max(
                    int(metrics_snapshot.get("utility_progress") or 0),
                    int(utility_action.get("utility_action_progress") or 0),
                )
                if is_keystroke_mode and action_history_limit > 0:
                    action_history.append(
                        _keystroke_action_history_entry(
                            step=step,
                            action=action,
                            requested_ticks=requested_ticks,
                            tick_info=tick_info_state,
                            execute_result=execute_result,
                            state_before=state_before,
                            advance_state=advance_state,
                            metrics_snapshot=metrics_snapshot,
                        )
                    )
                    if len(action_history) > action_history_limit:
                        del action_history[:-action_history_limit]
                keystroke_step_score_progress = False
                if is_keystroke_mode:
                    keystroke_step_score_progress = _keystroke_step_score_progress(
                        metrics_snapshot,
                        state_before=state_before,
                        advance_state=advance_state,
                    )
                    metrics_snapshot[
                        "keystroke_step_score_progress"
                    ] = keystroke_step_score_progress

                score_elapsed_ticks = elapsed_ticks_total
                if assisted_dfhack_action_seen:
                    _zero_assisted_dfhack_progress(metrics_snapshot)
                    metrics_snapshot["observed_run_elapsed_ticks"] = elapsed_ticks_total
                    metrics_snapshot["score_duration_blocked"] = True
                    score_elapsed_ticks = 0
                elif is_keystroke_mode and not keystroke_gameplay_progress_seen:
                    metrics_snapshot["observed_run_elapsed_ticks"] = elapsed_ticks_total
                    metrics_snapshot["score_duration_blocked"] = True
                    metrics_snapshot["score_provenance"] = "keystroke_no_gameplay_progress_yet"
                    score_elapsed_ticks = 0
                elif is_keystroke_mode:
                    if keystroke_step_score_progress:
                        scoreable_elapsed_ticks = elapsed_ticks_total
                        metrics_snapshot["score_duration_blocked"] = False
                    else:
                        metrics_snapshot["observed_run_elapsed_ticks"] = elapsed_ticks_total
                        metrics_snapshot["score_duration_blocked"] = True
                        metrics_snapshot["score_provenance"] = (
                            "keystroke_no_current_gameplay_progress"
                        )
                    score_elapsed_ticks = scoreable_elapsed_ticks
                metrics_snapshot["run_elapsed_ticks"] = score_elapsed_ticks
                publish_event(step, "metrics", {"metrics": metrics_snapshot}, events)

                score_metrics = dict(metrics_snapshot)
                score_metrics["time"] = score_elapsed_ticks
                score_value = scoring.composite_score(score_metrics)
                if (
                    is_keystroke_mode
                    and not assisted_dfhack_action_seen
                    and not keystroke_step_score_progress
                    and last_keystroke_score_value is not None
                ):
                    score_value = min(score_value, last_keystroke_score_value)
                if is_keystroke_mode and not assisted_dfhack_action_seen:
                    if (
                        keystroke_step_score_progress
                        or last_keystroke_score_value is None
                        or score_value < last_keystroke_score_value
                    ):
                        last_keystroke_score_value = score_value
                milestone_notes = (
                    milestones.detect(previous_state or state_before, advance_state)
                    if previous_state is not None
                    else []
                )
                publish_event(
                    step,
                    "score",
                    {
                        "value": score_value,
                        "milestones": milestone_notes,
                    },
                    events,
                )

                previous_state = advance_state

                map_snapshot = None
                gameplay_proof = None
                if backend_name == "dfhack":
                    snapshot_rect = (
                        ui_work_rect
                        if is_keystroke_mode and ui_work_rect is not None
                        else _map_snapshot_rect_from_state(advance_state)
                    )
                    if snapshot_rect:
                        map_snapshot = read_map_snapshot(snapshot_rect)
                        publish_event(step, "map_snapshot", {"map_snapshot": map_snapshot}, events)
                    if is_keystroke_mode:
                        gameplay_proof = _gameplay_proof(
                            action=action,
                            metrics_snapshot=metrics_snapshot,
                            before_map_snapshot=map_snapshot_before,
                            after_map_snapshot=map_snapshot,
                            state_before=state_before,
                            advance_state=advance_state,
                            tick_info=tick_info_state,
                            score_value=score_value,
                        )
                        publish_event(
                            step,
                            "gameplay_proof",
                            {"gameplay_proof": gameplay_proof},
                            events,
                        )

                record_line = {
                    "run_id": run_identifier,
                    "step": step,
                    "observation": obs_json,
                    "observation_text": obs_text,
                    "action": action,
                    "validation": validation,
                    "execute": execute_result,
                    "state_after_apply": state_after_apply,
                    "state_after_advance": advance_state,
                    "metrics": metrics_snapshot,
                    "score": {
                        "value": score_value,
                        "milestones": milestone_notes,
                    },
                    "events": events,
                    "tick_advance": tick_info_state,
                }
                if map_snapshot is not None:
                    record_line["map_snapshot"] = map_snapshot
                if gameplay_proof is not None:
                    record_line["gameplay_proof"] = gameplay_proof
                fh.write(json.dumps(record_line) + "\n")

                if registry:
                    registry.set_status(run_identifier, step=step)

        if registry and run_stopped:
            registry.set_status(
                run_identifier,
                status="stopped",
                ended_at=datetime.utcnow(),
            )
        elif registry and not run_failed:
            registry.set_status(
                run_identifier,
                status="completed",
                ended_at=datetime.utcnow(),
            )
        summary = summarize(trace_path)
        summary.model = model
        summary.backend = backend_name
        if scenario:
            summary.scenario = scenario
            scenario_pack = get_mock_scenario(scenario)
            summary_payload = _dump_model(summary)
            summary.scenario_assertions = evaluate_scenario_assertions(
                scenario_pack,
                summary=summary_payload,
            )
        summary_path = trace_path.with_name("summary.json")
        summary_path.write_text(json.dumps(_dump_model(summary), indent=2), encoding="utf-8")
        if registry:
            registry.set_summary(run_identifier, _dump_model(summary))
            registry.append_event(
                run_identifier,
                {
                    "t": "score",
                    "data": {
                        "run_id": run_identifier,
                        "step": summary.steps,
                        "total_score": summary.total_score,
                    },
                },
            )

        # Auto-analyze trace with LLM (optional - requires GOOGLE_API_KEY)
        try:
            from ..eval.analyzer import TraceAnalyzer, save_analysis
            import os
            if os.environ.get("GOOGLE_API_KEY"):
                analyzer = TraceAnalyzer()
                analysis = analyzer.analyze(trace_path)
                save_analysis(analysis, trace_path.parent)
        except Exception as e:
            # Analysis is optional - don't fail the run if it errors
            import logging
            logging.getLogger(__name__).warning(f"Auto-analysis skipped: {e}")
    except Exception:
        if registry:
            registry.set_status(
                run_identifier,
                status="failed",
                ended_at=datetime.utcnow(),
            )
        raise
    finally:
        if dfhack_client:
            # Pause game before closing to prevent it from running between runs
            try:
                dfhack_client.pause()
            except Exception:
                pass  # Best effort via RPC
            # Also try direct dfhack-run as fallback
            try:
                import subprocess
                from ..config import dfhack_cmd
                subprocess.run(
                    dfhack_cmd("lua", "df.global.pause_state = true"),
                    timeout=5,
                    capture_output=True,
                )
            except Exception:
                pass  # Best effort
            dfhack_client.close()

    return run_identifier


__all__ = ["run_once"]
