"""Run loop orchestration utilities."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime
from os import fsync
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent.base import Agent
from ..config import get_settings
from ..dfhack_backend import (
    MAX_RECT_H,
    MAX_RECT_W,
    MAX_SNAPSHOT_H,
    MAX_SNAPSHOT_W,
    ensure_paused_external,
    prepare_keystroke_target,
    read_fort_metrics,
    read_g7_evidence,
    read_job_metrics,
    read_map_snapshot,
    read_work_metrics,
    start_g7_evidence,
    stop_g7_evidence,
)
from ..env.actions import (
    FINISH_TOPIC_MEETING_OPTION_TEXT,
    INTERACT_ALLOWED_VIEWSCREEN_TYPES,
    TOPIC_MEETING_OPTION_OPERATIONS,
    blocking_viewscreen_action_reason,
    normalized_action_fingerprint,
    parse_action,
    validate_action,
    visible_topic_meeting_option,
)
from ..env.dfhack_client import DFHackClient, DFHackError
from ..env.encoder import encode_observation
from ..env.executor import Executor
from ..env.mock_env import MockEnvironment
from ..env.scenarios import evaluate_scenario_assertions, get_mock_scenario
from ..env.state_reader import StateReader
from ..eval import metrics, milestones, scoring
from ..eval.summary import RunSummary, summarize
from .model_modes import (
    GOVERNED_DFHACK_MODELS as GOVERNED_DFHACK_MODELS,
    is_governed_dfhack_model,
)
from .seed_reset import maybe_reset_dfhack_seed
from .storage import RunRegistry

ASSISTED_DFHACK_ACTIONS = {
    "DIG",
    "BUILD",
    "ORDER",
    "UNSUSPEND",
    "FARM",
    "LABOR",
    "INTERACT",
}
GOVERNED_DFHACK_ACTIONS = {
    "DIG",
    "BUILD",
    "ORDER",
    "UNSUSPEND",
    "FARM",
    "LABOR",
    "WAIT",
    "INTERACT",
}
MAX_CONSECUTIVE_ZERO_TICKS = 3
MAX_INTERACT_OPERATIONS_PER_MODAL = 8
MAX_UNCHANGED_INTERACT_SCREENS = 3
MIN_GOVERNED_ACTION_HISTORY = 6
SCREEN_CAPTURE_FAILED = "(screen capture failed)"
def _screen_sha256(screen_text: str | None) -> str:
    return hashlib.sha256((screen_text or "").encode("utf-8")).hexdigest()


def _effective_action_history_limit(configured: Any, *, governed: bool) -> int:
    """Keep enough governed history for one review interval plus its checkpoint."""

    minimum = MIN_GOVERNED_ACTION_HISTORY if governed else 0
    return max(minimum, int(configured))


def _write_jsonl_record(fh: Any, record: Dict[str, Any]) -> None:
    payload = dict(record)
    payload.setdefault("score_version", scoring.SCORE_VERSION)
    if isinstance(payload.get("metrics"), dict):
        metrics_payload = dict(payload["metrics"])
        metrics_payload.setdefault("score_version", scoring.SCORE_VERSION)
        payload["metrics"] = metrics_payload
    if isinstance(payload.get("score"), dict):
        score_payload = dict(payload["score"])
        score_payload.setdefault("version", scoring.SCORE_VERSION)
        payload["score"] = score_payload
    if isinstance(payload.get("events"), list):
        versioned_events = []
        for event in payload["events"]:
            if not isinstance(event, dict) or event.get("type") != "score":
                versioned_events.append(event)
                continue
            event_payload = dict(event)
            data_payload = (
                dict(event_payload["data"])
                if isinstance(event_payload.get("data"), dict)
                else {}
            )
            data_payload.setdefault("version", scoring.SCORE_VERSION)
            event_payload["data"] = data_payload
            versioned_events.append(event_payload)
        payload["events"] = versioned_events
    fh.write(json.dumps(payload) + "\n")


def _write_durable_jsonl_record(fh: Any, record: Dict[str, Any]) -> None:
    """Make a terminal trace row durable before publishing terminal status."""

    _write_jsonl_record(fh, record)
    fh.flush()
    fsync(fh.fileno())


def _interact_context_reason(
    *,
    backend_name: str,
    is_governed_dfhack_mode: bool,
    state: Dict[str, Any],
    action: Dict[str, Any] | None = None,
    screen_text: str | None = None,
) -> str | None:
    """Reject semantic UI input unless DF attests a paused interactive view."""

    if backend_name != "dfhack" or not is_governed_dfhack_mode:
        return "INTERACT is available only in governed DFHack mode"
    if state.get("pause_state") is not True:
        return "INTERACT requires an attested paused game state"
    blocking_reason = blocking_viewscreen_action_reason(state, action or {})
    if blocking_reason is not None:
        return blocking_reason
    viewscreen_type = str(state.get("viewscreen_type") or "unknown")
    if viewscreen_type not in INTERACT_ALLOWED_VIEWSCREEN_TYPES:
        return f"INTERACT is not allowed on DF viewscreen {viewscreen_type!r}"
    operation = (action or {}).get("params", {}).get("operation")
    if (
        operation == "finish_topic_meeting"
        and FINISH_TOPIC_MEETING_OPTION_TEXT not in (screen_text or "")
    ):
        return (
            "INTERACT finish_topic_meeting requires the visible option "
            f"{FINISH_TOPIC_MEETING_OPTION_TEXT!r}"
        )
    if operation in TOPIC_MEETING_OPTION_OPERATIONS and not visible_topic_meeting_option(
        str(operation), screen_text or ""
    ):
        letter = str(operation).rsplit("_", 1)[-1]
        return f"INTERACT {operation} requires a visible '{letter} - ...' topic option"
    return None


def _interaction_terminal_reason(
    *,
    action_type: str,
    interaction_audit: Dict[str, Any] | None,
    state_after: Dict[str, Any],
    episode_count: int,
    unchanged_screen_streak: int,
) -> tuple[Dict[str, Any] | None, int, int]:
    """Bound a zero-tick modal-recovery episode independently of tick stalls."""

    if action_type != "INTERACT" or interaction_audit is None:
        return None, episode_count, unchanged_screen_streak

    next_count = episode_count + 1
    viewscreen_after = str(state_after.get("viewscreen_type") or "unknown")
    if viewscreen_after not in INTERACT_ALLOWED_VIEWSCREEN_TYPES:
        return None, 0, 0

    screen_changed = bool(interaction_audit.get("screen_changed"))
    next_unchanged = 0 if screen_changed else unchanged_screen_streak + 1
    base = {
        "interaction_episode_count": next_count,
        "interaction_episode_limit": MAX_INTERACT_OPERATIONS_PER_MODAL,
        "unchanged_screen_streak": next_unchanged,
        "unchanged_screen_limit": MAX_UNCHANGED_INTERACT_SCREENS,
        "interaction": dict(interaction_audit),
    }
    if next_unchanged >= MAX_UNCHANGED_INTERACT_SCREENS:
        return {"code": "interaction_unchanged_screen_loop", **base}, next_count, next_unchanged
    if next_count >= MAX_INTERACT_OPERATIONS_PER_MODAL:
        return {"code": "interaction_budget_exhausted", **base}, next_count, next_unchanged
    return None, next_count, next_unchanged


def _tick_terminal_reason(
    requested_ticks: Any,
    tick_info: Dict[str, Any],
    consecutive_zero_tick_streak: int,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], int]:
    """Classify an advance result without treating paused UI actions as failures."""

    requested_ticks_int = _int_or_none(requested_ticks) or 0
    if requested_ticks_int <= 0:
        return None, None, consecutive_zero_tick_streak

    actual_ticks = _int_or_none(tick_info.get("ticks_advanced")) or 0
    base = {
        "requested_ticks": requested_ticks_int,
        "ticks_advanced": actual_ticks,
        "tick_info": dict(tick_info),
    }
    if (
        tick_info.get("error") == "repause_unverified"
        or tick_info.get("repause_error") is not None
        or (
            tick_info.get("repause_requested") is True
            and tick_info.get("repause_effective") is not True
        )
    ):
        return {"code": "tick_repause_unverified", **base}, None, 0
    if actual_ticks > 0:
        if tick_info.get("timeout") is True:
            return None, {"code": "partial_tick_timeout", **base}, 0
        if tick_info.get("ok") is False:
            return None, {"code": "partial_tick_failed", **base}, 0
        return None, None, 0

    if tick_info.get("timeout") is True:
        return {"code": "tick_timeout_zero_progress", **base}, None, 0
    if tick_info.get("ok") is False:
        return {"code": "tick_failed_zero_progress", **base}, None, 0

    next_streak = consecutive_zero_tick_streak + 1
    if next_streak >= MAX_CONSECUTIVE_ZERO_TICKS:
        return (
            {
                "code": "consecutive_zero_ticks",
                "consecutive_zero_tick_streak": next_streak,
                "zero_tick_threshold": MAX_CONSECUTIVE_ZERO_TICKS,
                **base,
            },
            None,
            next_streak,
        )
    return None, None, next_streak


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
UI_WORKSHOP_BLOCKED_FALLBACK_TARGETS = 3
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


def _is_governed_dfhack_model(model: str) -> bool:
    """Compatibility wrapper for callers that imported the old private helper."""

    return is_governed_dfhack_model(model)


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


def _governed_dig_rect_from_action(
    action: Dict[str, Any],
) -> tuple[int, int, int, int, int, int] | None:
    """Return the exact bounded footprint from a model-authored dig action."""

    if str(action.get("type") or "").upper() != "DIG":
        return None
    params = action.get("params")
    if not isinstance(params, dict):
        return None
    if str(params.get("kind") or "dig").lower() not in {"dig", "channel"}:
        return None
    area = params.get("area")
    size = params.get("size")
    if not isinstance(area, (list, tuple)) or len(area) != 3:
        return None
    if not isinstance(size, (list, tuple)) or len(size) != 3:
        return None
    try:
        x, y, z = (int(value) for value in area)
        width, height, depth = (int(value) for value in size)
    except (TypeError, ValueError):
        return None
    if width < 1 or height < 1 or depth != 1:
        return None
    if width > MAX_RECT_W or height > MAX_RECT_H:
        return None
    return (x, y, z, x + width - 1, y + height - 1, z)


def _channel_focus_rect_from_action(
    action: Dict[str, Any],
) -> tuple[int, int, int, int, int, int] | None:
    """Return the exact rect from a model-authored channel action."""

    params = action.get("params")
    if not isinstance(params, dict) or str(params.get("kind") or "").lower() != "channel":
        return None
    return _governed_dig_rect_from_action(action)


def _owned_channel_focus_rect(
    action: Dict[str, Any], owned_delta: Dict[str, Any]
) -> tuple[int, int, int, int, int, int] | None:
    """Focus access telemetry on one newly model-owned channel tile only."""

    if _channel_focus_rect_from_action(action) is None:
        return None
    designated = []
    for coordinate in owned_delta.get("governed_designated_tiles", []):
        if not isinstance(coordinate, list) or len(coordinate) != 3:
            continue
        try:
            designated.append(tuple(int(value) for value in coordinate))
        except (TypeError, ValueError):
            continue
    if not designated:
        return None
    x, y, z = sorted(designated)[0]
    return x, y, z, x, y, z


def _owned_excavation_snapshot_rects(
    owned_tiles: Dict[tuple[int, int, int], str],
) -> list[tuple[int, int, int, int, int, int]]:
    """Cover owned coordinates with bounded, camera-independent snapshot rects."""

    buckets: Dict[tuple[int, int, int], list[tuple[int, int]]] = {}
    for x, y, z in owned_tiles:
        bucket = (z, x // MAX_SNAPSHOT_W, y // MAX_SNAPSHOT_H)
        buckets.setdefault(bucket, []).append((x, y))
    rects = []
    for (z, _, _), coordinates in sorted(buckets.items()):
        xs = [coordinate[0] for coordinate in coordinates]
        ys = [coordinate[1] for coordinate in coordinates]
        rects.append((min(xs), min(ys), z, max(xs), max(ys), z))
    return rects


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


def _map_snapshot_rect_from_state(
    state: Dict[str, Any], margin: int = 1
) -> tuple[int, int, int, int, int, int] | None:
    # Prefer the plan-agnostic fort minimap window (fort_metrics.lua): a
    # citizen/building/construction-anchored bbox, so the snapshot — and the
    # tile-change proof diffed from it — follows wherever the fort is actually
    # built. The legacy plan-rect bbox below remains only as a fallback: a
    # fixed window that plan-agnostic forts outgrow (run 2f58fd37 built its
    # second room outside it, leaving walls unproven and the replay frozen).
    fort = state.get("fort")
    if isinstance(fort, dict) and fort.get("ok"):
        origin = fort.get("map_origin")
        rows = fort.get("map_rows")
        if (
            isinstance(origin, (list, tuple))
            and len(origin) == 3
            and isinstance(rows, list)
            and rows
            and all(isinstance(row, str) for row in rows)
        ):
            try:
                origin_x, origin_y, origin_z = (int(v) for v in origin)
            except (TypeError, ValueError):
                origin_x = None
            if origin_x is not None:
                width = max(len(row) for row in rows)
                height = len(rows)
                if width > 0 and height > 0:
                    width = min(width + 2 * margin, MAX_SNAPSHOT_W)
                    height = min(height + 2 * margin, MAX_SNAPSHOT_H)
                    x1 = max(0, origin_x - margin)
                    y1 = max(0, origin_y - margin)
                    return (
                        x1,
                        y1,
                        origin_z,
                        x1 + width - 1,
                        y1 + height - 1,
                        origin_z,
                    )

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


def _job_metrics_survey_rect(
    state: Dict[str, Any], margin: int = 1
) -> tuple[int, int, int, int, int, int] | None:
    """Bound the fort/legacy snapshot rect to job_metrics' tighter tile survey.

    The snapshot rect follows the fort minimap window (up to ~34 tiles + margin,
    clamped to MAX_SNAPSHOT_W/H = 64). ``read_job_metrics`` rejects any rect over
    MAX_RECT_W/H (30) outright, which would drop the *entire* crew read — not just
    the optional tile survey. Shrink the survey rect to the job-metrics bound so
    crew observability always attaches; the snapshot/proof rect stays full-size.
    """

    rect = _map_snapshot_rect_from_state(state, margin=margin)
    if rect is None:
        return None
    x1, y1, z1, x2, y2, z2 = rect
    if (x2 - x1 + 1) <= MAX_RECT_W and (y2 - y1 + 1) <= MAX_RECT_H:
        return rect
    return (
        x1,
        y1,
        z1,
        x1 + min(x2 - x1 + 1, MAX_RECT_W) - 1,
        y1 + min(y2 - y1 + 1, MAX_RECT_H) - 1,
        z2,
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


def _available_carpenter_materials(state: Dict[str, Any]) -> int:
    stocks = state.get("stocks")
    if not isinstance(stocks, dict):
        return 0
    return max(0, _int_or_none(stocks.get("wood")) or 0)


def _carpenter_workshops(state: Dict[str, Any]) -> int:
    work = state.get("work")
    if isinstance(work, dict):
        planned = _int_or_none(work.get("carpenter_workshops_planned"))
        if planned is not None:
            return max(0, planned)
        return max(0, _int_or_none(work.get("carpenter_workshops")) or 0)
    return max(0, _int_or_none(state.get("carpenter_workshops")) or 0)


def _usable_carpenter_workshops(state: Dict[str, Any]) -> int:
    work = state.get("work")
    if isinstance(work, dict):
        return max(0, _int_or_none(work.get("carpenter_workshops_usable")) or 0)
    return 0


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


def _queued_carpenter_workshop_task_needs_resolution(state: Dict[str, Any]) -> bool:
    work = state.get("work")
    if not isinstance(work, dict):
        return False

    planned = _int_or_none(work.get("carpenter_workshops_planned"))
    if planned is None:
        planned = _int_or_none(work.get("carpenter_workshops"))
    usable = _int_or_none(work.get("carpenter_workshops_usable")) or 0
    task_jobs = _int_or_none(work.get("carpenter_workshop_task_jobs")) or 0

    return bool((planned or 0) > 0 and usable > 0 and task_jobs > 0)


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
    tile_changes = _snapshot_tile_changes(before_map_snapshot, after_map_snapshot)
    state_deltas = _keystroke_productive_state_deltas(state_before, advance_state)
    ui_step_work_progress = int(metrics_snapshot.get("ui_step_work_progress") or 0)
    ui_step_excavation_progress = int(metrics_snapshot.get("ui_step_excavation_progress") or 0)
    ui_step_material_progress = int(metrics_snapshot.get("ui_step_material_progress") or 0)
    step_gameplay_progress = bool(
        ui_step_work_progress
        or ui_step_excavation_progress
        or ui_step_material_progress
        or tile_changes.get("changed_tile_count")
        or state_deltas
    )
    proof_ok = bool(step_gameplay_progress)
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
            "cumulative_ui_excavation": int(metrics_snapshot.get("ui_excavation_progress") or 0),
        },
        "state_deltas": state_deltas,
        "tile_changes": tile_changes,
        "changed_tile_count": int(tile_changes.get("changed_tile_count") or 0),
        "changed_tiles": tile_changes.get("changed_tiles", []),
        "truncated_changed_tiles": bool(tile_changes.get("truncated", False)),
    }


def _governed_durable_helper_progress(action: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """Return helper effects durable enough to unlock governed scalar scoring."""

    if action.get("type") == "INTERACT":
        return False
    # A BUILD helper creates an ordinary pending ConstructBuilding job. That is
    # legal command evidence, but it is not completed fortress work and cannot
    # unlock accumulated survival time. FARM can change a crop only on a built
    # plot after exhaustive native eligibility checks and four-slot readback.
    return int(result.get("seasons_changed") or 0) > 0


_GOVERNED_TRACKED_BUILDING_KINDS = frozenset(
    {"CarpenterWorkshop", "Still", "FarmPlot"}
)


def _governed_rollback_unverified(result: Dict[str, Any]) -> bool:
    """Recognize every helper form that explicitly reports rollback failure."""

    if result.get("rollback_verified") is False:
        return True
    if str(result.get("error") or "").lower() == "rollback_failed":
        return True
    failed = result.get("failed")
    return any(
        isinstance(item, dict)
        and (
            item.get("rollback_verified") is False
            or str(item.get("error") or "").lower() == "rollback_failed"
        )
        for item in (failed if isinstance(failed, list) else [])
    )


def _governed_building_claims(
    action: Dict[str, Any], execute_result: Dict[str, Any]
) -> Dict[int, str]:
    """Return exact building IDs created by one accepted governed BUILD."""

    if action.get("type") != "BUILD" or execute_result.get("accepted") is not True:
        return {}
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    kind = str(params.get("kind") or "")
    if kind not in _GOVERNED_TRACKED_BUILDING_KINDS:
        return {}
    result = (
        execute_result.get("result")
        if isinstance(execute_result.get("result"), dict)
        else {}
    )
    if result.get("ok") is not True:
        return {}
    building_id = _int_or_none(result.get("building_id"))
    if building_id is None or building_id < 0:
        return {}
    return {building_id: kind}


def _native_building_stage_complete(entry: Dict[str, Any]) -> bool:
    """Require an attested, internally consistent native build-stage read."""

    if entry.get("stage_read_ok") is not True or entry.get("built") is not True:
        return False
    stage = _int_or_none(entry.get("stage"))
    max_stage = _int_or_none(entry.get("max_stage"))
    return bool(
        stage is not None
        and max_stage is not None
        and max_stage > 0
        and stage >= max_stage
    )


def _governed_completed_owned_buildings(
    owned_buildings: Dict[int, str], state: Dict[str, Any]
) -> set[int]:
    """Match owned building IDs to native completed-stage observations."""

    if not owned_buildings:
        return set()
    crew = state.get("crew") if isinstance(state.get("crew"), dict) else {}
    if crew.get("ok") is not True:
        return set()

    completed: set[int] = set()
    workshops = crew.get("workshops")
    for entry in workshops if isinstance(workshops, list) else []:
        if not isinstance(entry, dict) or not _native_building_stage_complete(entry):
            continue
        building_id = _int_or_none(entry.get("id"))
        if building_id is None:
            continue
        owned_kind = owned_buildings.get(building_id)
        observed_subtype = str(entry.get("subtype") or "")
        expected_subtype = {
            "CarpenterWorkshop": "Carpenters",
            "Still": "Still",
        }.get(owned_kind)
        if expected_subtype is not None and observed_subtype == expected_subtype:
            completed.add(building_id)

    farm_plots = crew.get("farm_plot_details")
    for entry in farm_plots if isinstance(farm_plots, list) else []:
        if not isinstance(entry, dict) or not _native_building_stage_complete(entry):
            continue
        building_id = _int_or_none(entry.get("id"))
        if building_id is None:
            continue
        if owned_buildings.get(building_id) == "FarmPlot":
            completed.add(building_id)
    return completed


def _governed_owned_building_progress(
    owned_buildings: Dict[int, str], completed_buildings: set[int]
) -> Dict[str, Any]:
    """Compute paid non-excavation progress from exact completed IDs only."""

    completed_ids = sorted(
        building_id
        for building_id in completed_buildings
        if building_id in owned_buildings
    )
    completed_carpenters = sum(
        owned_buildings[building_id] == "CarpenterWorkshop"
        for building_id in completed_ids
    )
    completed_stills = sum(
        owned_buildings[building_id] == "Still" for building_id in completed_ids
    )
    completed_farms = sum(
        owned_buildings[building_id] == "FarmPlot" for building_id in completed_ids
    )
    paid_workshop_progress = (
        completed_carpenters * metrics.PRODUCTION_WORKSHOP_PROGRESS
    )
    return {
        "governed_owned_buildings": len(owned_buildings),
        "governed_owned_completed_buildings": len(completed_ids),
        "governed_owned_completed_building_ids": completed_ids,
        "governed_owned_completed_carpenter_workshops": completed_carpenters,
        "governed_owned_completed_stills": completed_stills,
        "governed_owned_completed_farm_plots": completed_farms,
        "governed_owned_utility_progress": paid_workshop_progress,
        "governed_owned_production_progress": paid_workshop_progress,
        # Rooms and construction totals are global observations. They remain
        # audit-only until exact model-owned completion evidence exists.
        "governed_owned_complexity_progress": 0.0,
    }


def _governed_helper_progress(action: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """Return action-specific state change for audit and agent feedback."""

    workshops_added = max(
        int(result.get("after_carpenter_workshops") or 0)
        - int(result.get("before_carpenter_workshops") or 0),
        int(result.get("after_workshops_of_kind") or 0)
        - int(result.get("before_workshops_of_kind") or 0),
    )
    farm_plots_added = int(result.get("after_farm_plots") or 0) - int(
        result.get("before_farm_plots") or 0
    )
    return bool(
        _governed_durable_helper_progress(action, result)
        or workshops_added > 0
        or farm_plots_added > 0
        or int(result.get("placed_count") or 0) > 0
        or (result.get("ok") is True and result.get("building_id") is not None)
        or int(result.get("unsuspended") or 0) > 0
        or bool(result.get("labor_changed"))
    )


def _governed_helper_pending(action: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """Return true when a governed designation was accepted but may still be queued."""

    if action.get("type") != "DIG":
        return False
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    result_key = {
        "dig": "newly_designated",
        "channel": "newly_designated",
        "chop": "trees_designated",
        "gather": "shrubs_designated",
    }.get(str(params.get("kind") or "dig"))
    return bool(result_key and (_int_or_none(result.get(result_key)) or 0) > 0)


_ORDER_GOODS_KEYS = {
    "bed": "bed",
    "door": "door",
    "table": "table",
    "chair": "chair",
    "barrel": "barrel",
    "bin": "bin",
}


def _tracked_job_ids(state: Dict[str, Any]) -> tuple[set[int], bool]:
    crew = state.get("crew") if isinstance(state.get("crew"), dict) else {}
    jobs = crew.get("jobs") if isinstance(crew.get("jobs"), dict) else {}
    values = jobs.get("active_ids")
    if isinstance(values, list):
        complete = not bool(jobs.get("active_ids_truncated"))
    else:
        values = [
            entry.get("id")
            for entry in jobs.get("entries", [])
            if isinstance(entry, dict)
        ]
        total = _int_or_none(jobs.get("total"))
        complete = total is not None and total <= len(values)
    tracked: set[int] = set()
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            tracked.add(parsed)
    return tracked, complete


def _matching_order_job_ids(state: Dict[str, Any], job: str) -> tuple[set[int], bool]:
    crew = state.get("crew") if isinstance(state.get("crew"), dict) else {}
    jobs = crew.get("jobs") if isinstance(crew.get("jobs"), dict) else {}
    values = jobs.get("order_jobs")
    if isinstance(values, list):
        complete = not bool(jobs.get("order_jobs_truncated"))
    else:
        active_ids, active_complete = _tracked_job_ids(state)
        if active_complete and not active_ids:
            return set(), True
        return set(), False
    matching: set[int] = set()
    for value in values:
        if not isinstance(value, dict) or str(value.get("item") or "") != job:
            continue
        parsed = _int_or_none(value.get("id"))
        if parsed is not None:
            matching.add(parsed)
    return matching, complete


def _order_output_value(state: Dict[str, Any], job: str) -> tuple[str, int | None]:
    if job == "brew":
        survival = state.get("survival") if isinstance(state.get("survival"), dict) else {}
        value = _int_or_none(survival.get("drink_produced_in_run"))
        return "survival.drink_produced_in_run", value
    goods_key = _ORDER_GOODS_KEYS.get(job)
    if goods_key is None:
        return "untracked", None
    crew = state.get("crew") if isinstance(state.get("crew"), dict) else {}
    goods = crew.get("goods") if isinstance(crew.get("goods"), dict) else {}
    return f"crew.goods.{goods_key}", _int_or_none(goods.get(goods_key))


def _governed_order_effect(
    action: Dict[str, Any],
    result: Dict[str, Any],
    state_before: Dict[str, Any],
    advance_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Report ORDER acceptance separately from durable post-tick effect."""

    created = []
    created_values = result.get("created_job_ids")
    for value in created_values if isinstance(created_values, list) else []:
        parsed = _int_or_none(value)
        if parsed is not None:
            created.append(parsed)
    created = list(dict.fromkeys(created))
    active_ids, active_ids_complete = _tracked_job_ids(advance_state)
    remaining = [job_id for job_id in created if job_id in active_ids]
    job = str((action.get("params") or {}).get("job") or "").strip().lower()
    prior_matching_ids, prior_matching_complete = _matching_order_job_ids(state_before, job)
    before_work = state_before.get("work") if isinstance(state_before.get("work"), dict) else {}
    manager_orders_present = bool(
        int(before_work.get("manager_orders_count") or 0)
        or int(before_work.get("manager_orders_amount_left") or 0)
    )
    output_source, output_before = _order_output_value(state_before, job)
    _, output_after = _order_output_value(advance_state, job)
    output_delta = (
        output_after - output_before
        if output_before is not None and output_after is not None
        else None
    )
    output_observed = output_before is not None and output_after is not None
    completed = [job_id for job_id in created if job_id not in active_ids]
    lifecycle_complete = active_ids_complete or all(job_id in active_ids for job_id in created)
    created_job_completion_observed = bool(active_ids_complete and completed)
    attribution_complete = bool(
        created
        and created_job_completion_observed
        and prior_matching_complete
        and not prior_matching_ids
        and not manager_orders_present
    )
    if output_delta is not None and output_delta > 0 and attribution_complete:
        status = "progressed"
    elif output_delta is not None and output_delta > 0:
        status = "unattributed_output"
    elif remaining:
        status = "pending"
    elif created and (not lifecycle_complete or not output_observed):
        status = "unobserved"
    else:
        status = "no_progress"
    return {
        "status": status,
        "job": job,
        "created_job_ids": created,
        "remaining_job_ids": remaining,
        "completed_job_ids": completed if active_ids_complete else [],
        "created_job_completion_observed": created_job_completion_observed,
        "active_job_ids_complete": active_ids_complete,
        "prior_matching_job_ids": sorted(prior_matching_ids),
        "prior_matching_jobs_complete": prior_matching_complete,
        "manager_orders_present": manager_orders_present,
        "attribution_complete": attribution_complete,
        "output_observed": output_observed,
        "output_source": output_source,
        "output_before": output_before,
        "output_after": output_after,
        "output_delta": output_delta,
    }


def _governed_gameplay_proof(
    *,
    action: Dict[str, Any],
    execute_result: Dict[str, Any],
    metrics_snapshot: Dict[str, Any],
    before_map_snapshot: Dict[str, Any] | None,
    after_map_snapshot: Dict[str, Any] | None,
    state_before: Dict[str, Any],
    advance_state: Dict[str, Any],
    tick_info: Dict[str, Any],
    score_value: float,
) -> Dict[str, Any]:
    """Per-step evidence that a governed action changed real DF state.

    Evidence only — this object never feeds scoring. Command acceptance and
    unrelated simulation changes are reported separately from a verified
    action-specific effect.
    """

    tile_changes = _snapshot_tile_changes(before_map_snapshot, after_map_snapshot)
    state_deltas = _keystroke_productive_state_deltas(state_before, advance_state)
    result = execute_result.get("result") if isinstance(execute_result.get("result"), dict) else {}
    helper_evidence: Dict[str, Any] = {
        key: result[key]
        for key in (
            "newly_designated",
            "trees_designated",
            "already_designated",
            "non_wall_tiles",
            "created_job_ids",
            "building_id",
            "placed_count",
            "before_carpenter_workshops",
            "after_carpenter_workshops",
            "before_workshops_of_kind",
            "after_workshops_of_kind",
            "manager_recorded",
            "unsuspended",
            "suspended_found",
            "before_farm_plots",
            "after_farm_plots",
            "shrubs_designated",
            "non_shrub_tiles",
            "labor_changed",
            "labor_before",
            "labor_after",
            # FARM crop-selection evidence: seasons_changed is the world-change
            # signal (a plant_id slot actually flipped); the rest are
            # informational and whitelisted as non-world-change in the rubric.
            "farm_building_id",
            "crop",
            "seasons_changed",
            "seasons_set",
            "seasons_skipped",
            "seeds_on_hand",
            # Paused interface attestation is audit evidence only. It is
            # intentionally excluded from the progress expression below.
            "operation",
            "interface_key",
            "keys_sent",
            "viewscreen_before",
            "viewscreen_after",
            "pause_before",
            "pause_after",
            "screen_before_sha256",
            "screen_after_sha256",
            "screen_changed",
        )
        if key in result
    }
    world_state_changed = bool(int(tile_changes.get("changed_tile_count") or 0) or state_deltas)
    order_effect = (
        _governed_order_effect(action, result, state_before, advance_state)
        if action.get("type") == "ORDER"
        else None
    )
    action_effect_observed = bool(
        _governed_helper_progress(action, result)
        or (isinstance(order_effect, dict) and order_effect.get("status") == "progressed")
    )
    step_gameplay_progress = action.get("type") != "INTERACT" and action_effect_observed
    return {
        "ok": step_gameplay_progress,
        "source": "dfhack-map-and-state",
        "provenance": "dfhack_governed",
        "action_type": action.get("type"),
        "accepted": bool(execute_result.get("accepted")),
        "score": score_value,
        "score_provenance": metrics_snapshot.get("score_provenance"),
        "gameplay_progress_eligible": step_gameplay_progress,
        "tick_advance": {
            "requested": action.get("advance_ticks"),
            "actual": int(tick_info.get("ticks_advanced") or 0),
        },
        "helper_evidence": helper_evidence,
        "action_effect": order_effect,
        "action_effect_observed": action_effect_observed,
        "concurrent_world_state_changed": world_state_changed and not action_effect_observed,
        "state_deltas": state_deltas,
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


def _action_history_entry(
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
    action_result = (
        execute_result.get("result") if isinstance(execute_result.get("result"), dict) else {}
    )
    order_effect = (
        _governed_order_effect(action, action_result, state_before, advance_state)
        if action.get("type") == "ORDER"
        else None
    )
    result_error = (
        execute_result.get("reason")
        or execute_result.get("why")
        or execute_result.get("error")
        or action_result.get("error")
    )
    failed_targets = []
    failed = action_result.get("failed")
    if isinstance(failed, list):
        for item in failed:
            if not isinstance(item, dict):
                continue
            coords = [item.get(key) for key in ("x", "y", "z") if item.get(key) is not None]
            target = "(" + ",".join(str(value) for value in coords) + ")" if coords else "?"
            tile_facts = [
                f"{key}={item[key]}"
                for key in ("tile_shape", "tiletype")
                if item.get(key) is not None
            ]
            fact_suffix = "[" + ",".join(tile_facts) + "]" if tile_facts else ""
            failed_targets.append(
                f"{target}:{item.get('error') or 'unknown'}{fact_suffix}"
            )
    placed_targets = []
    placed = action_result.get("placed")
    if isinstance(placed, list):
        for item in placed:
            if not isinstance(item, dict):
                continue
            coords = [item.get(key) for key in ("x", "y", "z") if item.get(key) is not None]
            if coords:
                placed_targets.append("(" + ",".join(str(value) for value in coords) + ")")
    result_details = {
        key: action_result[key]
        for key in (
            "newly_designated",
            "trees_designated",
            "shrubs_designated",
            "placed_count",
            "failed_count",
            "building_id",
            "material_item_id",
            "created_job_ids",
            "workshop_id",
            "farm_plot_id",
            "before_carpenter_workshops",
            "after_carpenter_workshops",
            "before_workshops_of_kind",
            "after_workshops_of_kind",
            "before_farm_plots",
            "after_farm_plots",
            "seasons_changed",
            "unsuspended",
            "labor_changed",
            "operation",
            "semantic_effect_observed",
            "screen_changed",
        )
        if key in action_result
    }
    partial_mutation = bool(
        action_result.get("partial")
        and (_int_or_none(action_result.get("placed_count")) or 0) > 0
    )
    governed_action = action.get("type") != "KEYSTROKE"
    helper_mutation = governed_action and _governed_helper_progress(action, action_result)
    helper_pending = governed_action and _governed_helper_pending(action, action_result)
    proven_governed_progress = bool(
        governed_action
        and execute_result.get("governed_current_action_effect_observed") is True
    )
    proven_wait_progress = bool(
        action.get("type") == "WAIT"
        and execute_result.get("governed_wait_effect_observed") is True
    )
    state_mutation = bool(_keystroke_productive_state_deltas(state_before, advance_state))
    validation_rejected = bool(execute_result.get("validation_rejected"))
    if partial_mutation:
        outcome = "partial_mutation"
    elif validation_rejected:
        outcome = "validation_rejected"
    elif not accepted:
        outcome = "rejected"
    elif governed_action and action.get("type") == "INTERACT":
        interaction_changed = bool(
            action_result.get("semantic_effect_observed") or action_result.get("screen_changed")
        )
        outcome = (
            "interface_state_changed"
            if interaction_changed
            else "interaction_accepted_without_tracked_state_change"
        )
    elif isinstance(order_effect, dict) and order_effect.get("status") == "progressed":
        outcome = "action_effect_observed"
    elif isinstance(order_effect, dict) and order_effect.get("status") == "pending":
        outcome = "action_pending"
    elif isinstance(order_effect, dict) and order_effect.get("status") == "unattributed_output":
        outcome = "action_output_unattributed"
    elif isinstance(order_effect, dict) and order_effect.get("status") == "unobserved":
        outcome = "action_effect_unobserved"
    elif proven_governed_progress:
        # Exact owned completion proof is computed before history recording;
        # preserve that truth even when the helper only reports designation.
        outcome = "action_effect_observed"
    elif proven_wait_progress:
        outcome = "gameplay_state_changed"
    elif helper_pending:
        outcome = "action_pending"
    elif helper_mutation:
        outcome = "action_effect_observed"
    elif not governed_action and (state_mutation or productive_reasons):
        outcome = "gameplay_state_changed"
    elif action.get("type") == "WAIT" and (state_mutation or productive_reasons):
        outcome = "gameplay_state_changed"
    elif state_mutation or productive_reasons:
        outcome = "concurrent_gameplay_state_changed"
    elif actual_ticks > 0:
        outcome = "advanced_ticks_without_tracked_state_change"
    elif governed_action:
        outcome = "action_accepted_without_tracked_state_change"
    else:
        outcome = "keys_sent_without_tracked_state_change"

    return {
        "step": step,
        "action_type": action.get("type"),
        "params": {
            key: value
            for key, value in (action.get("params") or {}).items()
            if key != "keys" and value is not None
        },
        "keys": action.get("params", {}).get("keys", []),
        "key_fingerprint": _keystroke_key_fingerprint(action.get("params", {}).get("keys", [])),
        "action_fingerprint": normalized_action_fingerprint(action),
        "action_family": _keystroke_action_family(action),
        "intent": action.get("intent", ""),
        "objective": action.get("objective"),
        "plan_step": action.get("plan_step"),
        "plan_review": action.get("plan_review"),
        "expected_visible_result": action.get("expected_visible_result"),
        "expected_simulation_result": action.get("expected_simulation_result"),
        "screen_read": action.get("screen_read"),
        "last_action_review": action.get("last_action_review"),
        "advance_ticks": action.get("advance_ticks", requested_ticks),
        "requested_ticks": requested_ticks,
        "actual_ticks": actual_ticks,
        "accepted": accepted,
        "validation_rejected": validation_rejected,
        "outcome": outcome,
        "error": result_error,
        "failed_targets": failed_targets,
        "placed_targets": placed_targets,
        "result_details": result_details,
        "action_effect": order_effect,
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


def _record_action_history(
    action_history: List[Dict[str, Any]],
    *,
    action_history_limit: int,
    step: int,
    action: Dict[str, Any],
    requested_ticks: Any,
    tick_info: Dict[str, Any],
    execute_result: Dict[str, Any],
    state_before: Dict[str, Any],
    advance_state: Dict[str, Any],
    metrics_snapshot: Dict[str, Any],
) -> None:
    """Append one run-local action outcome while retaining the configured window."""

    if action_history_limit <= 0:
        return
    action_history.append(
        _action_history_entry(
            step=step,
            action=action,
            requested_ticks=requested_ticks,
            tick_info=tick_info,
            execute_result=execute_result,
            state_before=state_before,
            advance_state=advance_state,
            metrics_snapshot=metrics_snapshot,
        )
    )
    if len(action_history) > action_history_limit:
        del action_history[:-action_history_limit]


def _desired_keystroke_target_mode(
    state: Dict[str, Any],
    *,
    ui_run_excavation_progress: int,
    ui_run_material_progress: int = 0,
    ui_successful_targets: int,
    build_material_blocked: bool = False,
) -> str:
    enough_starter_space = (
        ui_run_excavation_progress >= UI_MATERIAL_TARGET_MIN_EXCAVATION_PROGRESS
        or ui_successful_targets >= 2
    )
    if build_material_blocked:
        return "material"
    if _pending_carpenter_workshop_construction(state):
        return "existing_workshop"
    if _unproven_carpenter_workshop_needs_selection(state):
        return "existing_workshop"
    if _queued_carpenter_workshop_task_needs_resolution(state):
        return "existing_workshop"
    if _usable_carpenter_workshops(state) > 0:
        if _available_carpenter_materials(state) > 0:
            return "existing_workshop"
        if enough_starter_space:
            return "material"
        return "starter"
    if _carpenter_workshops(state) > 0:
        return "starter"
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


def _workshop_blocked_fallback_active(
    blocked_target_count: int,
    blocked_at_work_progress: int | None,
    current_work_progress: int,
) -> bool:
    return bool(
        blocked_target_count >= UI_WORKSHOP_BLOCKED_FALLBACK_TARGETS
        and blocked_at_work_progress is not None
        and current_work_progress <= blocked_at_work_progress
    )


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


def _screen_shows_blocked_workshop_placement(screen_text: str | None) -> bool:
    return bool(
        screen_text
        and "Carpenter's Workshop" in screen_text
        and "Placement" in screen_text
        and ("Blocked" in screen_text or "Building present" in screen_text)
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


def _workshop_target_key(target: Dict[str, Any] | None) -> tuple[int, int, int] | None:
    if not isinstance(target, dict):
        return None
    rect = _normalize_rect(target.get("target_rect") or target.get("selection_rect"))
    if rect is None:
        return None
    return (rect[0], rect[1], rect[2])


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
        or (not target_progress_seen and attempts < retry_limit)
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
            setup["recommended_keys_exit_only"] = bool(recommended_keys_exit_only and prefix)
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


def _keystroke_productive_state_deltas(
    state_before: Dict[str, Any],
    advance_state: Dict[str, Any],
) -> Dict[str, int]:
    """Return real state deltas that should count as current-turn progress."""

    deltas = _keystroke_real_state_deltas(state_before, advance_state)
    productive: Dict[str, int] = {}
    for key, value in deltas.items():
        if value <= 0:
            continue
        productive[key] = value
    before_work = state_before.get("work") if isinstance(state_before.get("work"), dict) else {}
    after_work = advance_state.get("work") if isinstance(advance_state.get("work"), dict) else {}
    before_stocks = (
        state_before.get("stocks") if isinstance(state_before.get("stocks"), dict) else {}
    )
    after_stocks = (
        advance_state.get("stocks") if isinstance(advance_state.get("stocks"), dict) else {}
    )
    task_delta = _dict_delta(
        before_work,
        after_work,
        "carpenter_workshop_task_jobs",
    )
    wood_delta = _dict_delta(before_stocks, after_stocks, "wood")
    if task_delta is not None and task_delta < 0 and wood_delta is not None and wood_delta < 0:
        productive["carpenter_workshop_completed_tasks"] = abs(task_delta)
        productive["wood_consumed_by_workshop"] = abs(wood_delta)
    return productive


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
        "utility_action_progress",
    ):
        if int(metrics_snapshot.get(field) or 0) > 0:
            return True
    if state_before is not None and advance_state is not None:
        return bool(_keystroke_productive_state_deltas(state_before, advance_state))
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


def _cleanup_dfhack_runtime(
    client: Optional[DFHackClient],
    *,
    evidence_attempted: bool,
    require_pause: bool = False,
) -> Dict[str, Any]:
    """Attempt one bounded runtime release and report whether it was verified."""

    errors: list[Dict[str, str]] = []
    pause_rpc_ok = False
    pause_direct_ok = client is None and not require_pause
    pause_attestation: Dict[str, Any] | None = None
    if client is not None:
        try:
            client.pause()
            pause_rpc_ok = True
        except Exception as exc:
            errors.append({"stage": "pause_rpc", "error": str(exc)})
    if client is not None or require_pause:
        try:
            pause_attestation = dict(
                ensure_paused_external(timeout=2.5, attempts=2)
            )
            pause_direct_ok = pause_attestation.get("ok") is True
            if not pause_direct_ok:
                errors.append(
                    {
                        "stage": "pause_attestation",
                        "error": str(
                            pause_attestation.get("error") or pause_attestation
                        ),
                    }
                )
        except Exception as exc:
            errors.append({"stage": "pause_attestation", "error": str(exc)})
        if pause_direct_ok:
            errors = [error for error in errors if error["stage"] != "pause_rpc"]

    evidence_result: Dict[str, Any] | None = None
    if evidence_attempted:
        try:
            evidence_result = dict(stop_g7_evidence())
        except Exception as exc:
            evidence_result = {"ok": False, "active": None, "error": str(exc)}
        if evidence_result.get("ok") is not True or evidence_result.get("active") is not False:
            errors.append(
                {
                    "stage": "g7_evidence_stop",
                    "error": str(evidence_result.get("error") or evidence_result),
                }
            )

    client_closed = client is None
    if client is not None:
        try:
            client.close()
            client_closed = True
        except Exception as exc:
            errors.append({"stage": "client_close", "error": str(exc)})

    return {
        "ok": not errors,
        "errors": errors,
        "pause_rpc_completed": pause_rpc_ok,
        "pause_verified": pause_direct_ok,
        "pause_attestation": pause_attestation,
        "evidence_stop": evidence_result,
        "client_closed": client_closed,
    }


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
    seed_save: Optional[str] = None,
    runtime_save: Optional[str] = None,
) -> str:
    """Execute a run and persist a JSONL trace while streaming events."""

    settings = get_settings()
    backend_name = env or backend
    if scenario and backend_name != "mock":
        raise ValueError("Scenarios are currently supported only by the mock backend")
    ticks = ticks_per_step if ticks_per_step is not None else settings.TICKS_PER_STEP
    run_identifier = run_id or uuid.uuid4().hex

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
        if not registry.claim_pending_run(
            run_identifier,
            started_at=datetime.utcnow(),
        ):
            current = registry.get(run_identifier)
            current_status = current.status if current is not None else "missing"
            raise RuntimeError(
                f"Run '{run_identifier}' cannot be claimed from status '{current_status}'"
            )
        if loop is not None:
            registry.bind_loop(run_identifier, loop)

    # A registered run must be claimed before its artifacts can be touched.
    artifacts_dir = _artifacts_root() / run_identifier
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    trace_path = artifacts_dir / "trace.jsonl"

    executor = Executor()
    dfhack_client: Optional[DFHackClient] = None
    g7_evidence_attempted = False
    g7_evidence_start: Dict[str, Any] | None = None
    cleanup_attempts = 0
    cleanup_outcome: Dict[str, Any] | None = None
    cleanup_recorded = False
    cleanup_failure_without_registry: Dict[str, Any] | None = None
    dfhack_runtime_may_be_active = False

    def cleanup_dfhack_runtime() -> Dict[str, Any]:
        nonlocal cleanup_attempts, cleanup_outcome, cleanup_recorded
        nonlocal dfhack_client, g7_evidence_attempted
        while cleanup_attempts < 2 and not (cleanup_outcome or {}).get("ok"):
            cleanup_attempts += 1
            cleanup_outcome = _cleanup_dfhack_runtime(
                dfhack_client,
                evidence_attempted=g7_evidence_attempted,
                require_pause=dfhack_runtime_may_be_active,
            )
        if cleanup_outcome is None:
            cleanup_outcome = {
                "ok": False,
                "errors": [{"stage": "cleanup", "error": "not_attempted"}],
            }
        cleanup_outcome["attempts"] = cleanup_attempts
        if cleanup_outcome.get("ok"):
            if registry and not cleanup_recorded:
                registry.record_cleanup_completed(
                    run_identifier,
                    completed_at=datetime.utcnow(),
                )
                cleanup_recorded = True
            dfhack_client = None
            g7_evidence_attempted = False
        return cleanup_outcome

    def cleanup_terminal_reason(
        outcome: Dict[str, Any],
        *,
        prior_reason: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        reason: Dict[str, Any] = {
            "code": "dfhack_cleanup_unverified",
            "cleanup": outcome,
        }
        if prior_reason is not None:
            reason["prior_terminal_reason"] = prior_reason
        return reason

    def fail_setup_after_cleanup() -> None:
        outcome = cleanup_dfhack_runtime()
        if registry:
            if outcome.get("ok"):
                registry.set_status(
                    run_identifier,
                    status="failed",
                    step=0,
                    ended_at=datetime.utcnow(),
                )
            else:
                registry.record_terminal_failure(
                    run_identifier,
                    terminal_reason=cleanup_terminal_reason(outcome),
                    step=0,
                    ended_at=datetime.utcnow(),
                )
            registry.clear_stop(run_identifier)

    tick_info_state: Dict[str, Any] = {}
    elapsed_ticks_total = 0

    # Detect models that need screen capture and native UI keystroke scaffolding.
    is_keystroke_mode = _is_keystroke_model(model)
    is_governed_dfhack_mode = _is_governed_dfhack_model(model)
    governed_channel_focus: tuple[int, int, int, int, int, int] | None = None
    keystroke_ui_target: Optional[Dict[str, Any]] = None
    ui_target_mode = "starter"
    ui_target_generation = 0
    ui_target_attempts = 0
    ui_blocked_workshop_targets: set[tuple[int, int, int]] = set()

    def get_screen_text() -> str:
        """Get screen text when CopyScreen is available."""
        return ""

    if (
        backend_name == "dfhack"
        and is_governed_dfhack_mode
        and os.getenv("FORT_GYM_DFHACK_COMPLETE_DIG", "0") == "1"
    ):
        fail_setup_after_cleanup()
        raise RuntimeError(
            "Governed DFHack runs forbid FORT_GYM_DFHACK_COMPLETE_DIG=1; "
            "unset the harness-assisted completion flag before gameplay"
        )

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
            fail_setup_after_cleanup()
            raise RuntimeError("DFHack backend disabled. Set DFHACK_ENABLED=1 to use it.")

        dfhack_runtime_may_be_active = True

        # If configured, reset the save from a pristine seed before connecting.
        if not preserve_save:
            try:
                maybe_reset_dfhack_seed(
                    settings,
                    seed_save=seed_save,
                    runtime_save=runtime_save,
                )
            except Exception:
                fail_setup_after_cleanup()
                raise

        try:
            dfhack_client = DFHackClient(host=settings.DFHACK_HOST, port=settings.DFHACK_PORT)
            dfhack_client.connect()
            pause_preflight = ensure_paused_external(timeout=2.5, attempts=2)
            if pause_preflight.get("ok") is not True:
                raise RuntimeError(
                    "DFHack startup pause preflight failed: "
                    f"{pause_preflight.get('error') or pause_preflight}"
                )
            if is_governed_dfhack_mode:
                dfhack_client.set_work_metrics_global_only(True)
            executor = Executor(
                dfhack_client=dfhack_client,
                allow_assisted_dig_completion=not is_governed_dfhack_mode,
            )
            if is_governed_dfhack_mode:
                g7_evidence_attempted = True
                g7_evidence_start = start_g7_evidence(run_identifier)
            if is_keystroke_mode:
                keystroke_ui_target = prepare_keystroke_target(
                    ui_target_mode,
                    blocked_workshop_targets=tuple(ui_blocked_workshop_targets),
                )
                if keystroke_ui_target.get("ok"):
                    ui_target_generation = 1
        except Exception:
            fail_setup_after_cleanup()
            raise

        def pause_env() -> None:
            dfhack_client.pause()

        def attach_crew_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
            """Attach read-only crew/job/workshop observability for governed runs."""

            if not is_governed_dfhack_mode:
                return state
            crew = read_job_metrics()
            if isinstance(crew, dict) and crew.get("ok"):
                state = dict(state)
                state["crew"] = crew
            return state

        def attach_fort_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
            """Attach read-only plan-agnostic fort structure observability for governed runs."""

            if not is_governed_dfhack_mode:
                return state
            fort = read_fort_metrics(governed_channel_focus)
            if isinstance(fort, dict) and fort.get("ok"):
                state = dict(state)
                state["fort"] = fort
            return state

        def attach_survival_evidence(state: Dict[str, Any]) -> Dict[str, Any]:
            """Attach run-scoped production, consumption, and death facts."""

            if not is_governed_dfhack_mode:
                return state
            evidence = read_g7_evidence()
            evidence_valid = bool(
                g7_evidence_start
                and g7_evidence_start.get("ok") is True
                and evidence.get("ok") is True
                and evidence.get("active") is True
                and evidence.get("run_id") == run_identifier
            )
            if not evidence_valid:
                evidence = {
                    **evidence,
                    "ok": False,
                    "active": False,
                    "flow_evidence_complete": False,
                    "death_evidence_complete": False,
                    "error": "g7_evidence_run_scope_invalid",
                    "expected_run_id": run_identifier,
                    "start_result": g7_evidence_start,
                }
            state = dict(state)
            state["survival"] = evidence
            return state

        def observe() -> Dict[str, Any]:
            # fort metrics attach before crew: the crew tile-survey rect
            # follows the fort minimap window when it is available.
            return attach_survival_evidence(
                attach_crew_metrics(
                    attach_fort_metrics(
                        StateReader.from_dfhack(dfhack_client)
                    )
                )
            )

        def apply_action(action_dict: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
            return executor.apply(
                action_dict,
                backend="dfhack",
                state=state,
                allow_interact=is_governed_dfhack_mode,
            )

        def advance_env(num_ticks: int) -> Dict[str, Any]:
            nonlocal tick_info_state
            if num_ticks <= 0:
                tick_info_state = {"ok": True, "ticks_advanced": 0, "skipped": True}
                return observe()
            state = attach_survival_evidence(
                attach_crew_metrics(
                    attach_fort_metrics(
                        dfhack_client.advance(num_ticks)
                    )
                )
            )
            tick_info_state = dict(dfhack_client.last_tick_info or {})
            return state

        if is_keystroke_mode or is_governed_dfhack_mode:

            def get_screen_text() -> str:
                """Get screen text for replay evidence."""
                try:
                    return dfhack_client.get_screen_text(include_visual_hints=True)
                except Exception:
                    return SCREEN_CAPTURE_FAILED

    else:
        fail_setup_after_cleanup()
        raise ValueError(f"Unsupported backend: {backend_name}")

    previous_state: Optional[Dict[str, Any]] = None
    baseline_work: Optional[Dict[str, Any]] = None
    baseline_fort: Optional[Dict[str, Any]] = None
    baseline_goods: Optional[Dict[str, Any]] = None
    baseline_wealth: int | None = None
    action_history: List[Dict[str, Any]] = []
    action_history_limit = _effective_action_history_limit(
        settings.ACTION_HISTORY_LIMIT,
        governed=is_governed_dfhack_mode,
    )
    last_action_result: Optional[Dict[str, Any]] = None  # Track previous action result for feedback
    previous_screen = (
        None  # Track previous screen for diff feedback (no type annotation for nonlocal)
    )
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
    ui_run_completed_workshop_tasks = 0
    ui_successful_targets = 0
    ui_work_feedback: Dict[str, Any] = {}
    ui_build_material_blocked = False
    ui_workshop_target_blocked = False
    ui_workshop_blocked_at_work_progress: int | None = None
    ui_material_target_exhausted = False
    carpenter_workshop_usable_seen = 0
    scoreable_elapsed_ticks = 0
    last_keystroke_score_value: float | None = None
    governed_owned_excavation: Dict[tuple[int, int, int], str] = {}
    governed_designated_tiles: set[tuple[int, int, int]] = set()
    governed_completed_tiles: set[tuple[int, int, int]] = set()
    governed_owned_buildings: Dict[int, str] = {}
    governed_completed_buildings: set[int] = set()
    governed_score_progress_seen = False

    def current_governed_score_metrics() -> Dict[str, Any]:
        if not is_governed_dfhack_mode:
            return {}
        building_progress = _governed_owned_building_progress(
            governed_owned_buildings,
            governed_completed_buildings,
        )
        return {
            "score_progress_provenance": scoring.GOVERNED_SCORE_PROGRESS_PROVENANCE,
            "governed_owned_work_progress": len(governed_completed_tiles),
            "governed_owned_designation_progress": len(governed_designated_tiles),
            "governed_owned_completion_progress": len(governed_completed_tiles),
            "utility_progress": building_progress[
                "governed_owned_utility_progress"
            ],
            "production_progress": building_progress[
                "governed_owned_production_progress"
            ],
            "complexity_progress": building_progress[
                "governed_owned_complexity_progress"
            ],
            **building_progress,
            "score_duration_blocked": not governed_score_progress_seen,
        }

    def publish_event(
        step: int, event_type: str, payload: Dict[str, Any], events: List[Dict[str, Any]]
    ) -> None:
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
    terminal_failure_reason: Dict[str, Any] | None = None
    terminal_failure_step = 0
    last_step = 0
    consecutive_zero_tick_streak = 0
    interaction_episode_count = 0
    interaction_unchanged_screen_streak = 0

    try:
        with trace_path.open("w", encoding="utf-8") as fh:
            def record_pre_execution_rejection(
                *,
                step: int,
                state: Dict[str, Any],
                reason: Any,
                events: List[Dict[str, Any]],
                record_line: Dict[str, Any],
            ) -> bool:
                """Record one no-execution row and bound blocked-screen retries."""

                nonlocal interaction_episode_count
                nonlocal interaction_unchanged_screen_streak
                nonlocal run_failed
                nonlocal terminal_failure_reason
                nonlocal terminal_failure_step

                blocking_context = (
                    blocking_viewscreen_action_reason(state, {})
                    if is_governed_dfhack_mode
                    else None
                )
                terminal_reason = None
                interaction_audit = None
                if blocking_context is not None:
                    interaction_audit = {
                        "screen_changed": False,
                        "validation_rejected": True,
                        "blocking_viewscreen": str(
                            state.get("viewscreen_type") or "unknown"
                        ),
                        "reason": str(reason),
                        "required_recovery": blocking_context,
                    }
                    (
                        terminal_reason,
                        interaction_episode_count,
                        interaction_unchanged_screen_streak,
                    ) = _interaction_terminal_reason(
                        action_type="INTERACT",
                        interaction_audit=interaction_audit,
                        state_after=state,
                        episode_count=interaction_episode_count,
                        unchanged_screen_streak=interaction_unchanged_screen_streak,
                    )
                    record_line["interaction"] = interaction_audit

                if terminal_reason is None:
                    _write_jsonl_record(fh, record_line)
                    if registry:
                        registry.set_status(run_identifier, step=step)
                    return False

                terminal_data = {
                    "run_id": run_identifier,
                    "step": step,
                    "terminal_reason": terminal_reason,
                }
                events.append({"type": "terminal", "data": terminal_data})
                record_line["terminal_reason"] = terminal_reason
                _write_durable_jsonl_record(fh, record_line)
                terminal_failure_reason = terminal_reason
                terminal_failure_step = step
                if registry:
                    registry.record_pending_terminal_failure(
                        run_identifier,
                        terminal_reason=terminal_reason,
                        step=step,
                    )
                    registry.append_event(
                        run_identifier,
                        {"t": "terminal", "data": terminal_data},
                    )
                run_failed = True
                return True

            for step in range(max_steps):
                last_step = step
                events: List[Dict[str, Any]] = []
                tick_info_state = {}
                map_snapshot_before = None
                map_snapshot = None
                gameplay_proof = None
                governed_action_rect = None
                governed_action_snapshot_before = None
                governed_action_snapshot_applied = None
                governed_action_snapshot_after = None
                governed_action_owned_delta = metrics.governed_action_footprint_progress_delta(
                    {"type": "WAIT", "params": {}}, None, None
                )
                governed_action_owned_keys: set[tuple[int, int, int]] = set()
                governed_completed_before_step = set(governed_completed_tiles)
                governed_completed_buildings_before_step = set(
                    governed_completed_buildings
                )
                execution_terminal_reason: Dict[str, Any] | None = None
                interaction_audit: Dict[str, Any] | None = None
                interaction_screen_after: str | None = None

                if registry and registry.stop_requested(run_identifier):
                    run_stopped = True
                    publish_event(step, "stopped", {"reason": "stop_requested"}, events)
                    _write_durable_jsonl_record(
                        fh,
                        {
                            "run_id": run_identifier,
                            "step": step,
                            "stopped": {"reason": "stop_requested"},
                            "events": events,
                        },
                    )
                    break

                pause_env()
                if registry and registry.stop_requested(run_identifier):
                    run_stopped = True
                    publish_event(
                        step,
                        "stopped",
                        {"reason": "stop_requested_after_pause"},
                        events,
                    )
                    _write_durable_jsonl_record(
                        fh,
                        {
                            "run_id": run_identifier,
                            "step": step,
                            "stopped": {"reason": "stop_requested_after_pause"},
                            "events": events,
                        },
                    )
                    break
                if (
                    backend_name == "dfhack"
                    and is_keystroke_mode
                    and ui_no_progress_streak >= UI_TARGET_REFRESH_NO_PROGRESS_STEPS
                ):
                    if _workshop_blocked_fallback_active(
                        len(ui_blocked_workshop_targets),
                        ui_workshop_blocked_at_work_progress,
                        ui_run_work_progress,
                    ):
                        starter_target = prepare_keystroke_target(
                            "starter",
                            blocked_workshop_targets=tuple(ui_blocked_workshop_targets),
                        )
                        if starter_target.get("ok"):
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
                            ui_workshop_target_blocked = False
                            ui_work_feedback = {
                                "target_refreshed": True,
                                "target_mode": ui_target_mode,
                                "reason": (
                                    "multiple workshop footprints were blocked; "
                                    "expanding starter floor before retrying placement"
                                ),
                                "blocked_workshop_target_count": len(ui_blocked_workshop_targets),
                                "refresh_after_no_progress_steps": UI_TARGET_REFRESH_NO_PROGRESS_STEPS,
                            }
                        else:
                            ui_work_feedback = {
                                "target_refresh_failed": True,
                                "error": starter_target.get("error", "unknown"),
                                "target_mode": "starter",
                                "previous_target_mode": ui_target_mode,
                                "blocked_workshop_target_count": len(ui_blocked_workshop_targets),
                                "no_progress_streak": ui_no_progress_streak,
                            }
                    else:
                        refreshed_target = prepare_keystroke_target(
                            ui_target_mode,
                            blocked_workshop_targets=tuple(ui_blocked_workshop_targets),
                        )
                        if refreshed_target.get("ok"):
                            if ui_target_mode == "material" and _same_target_route(
                                keystroke_ui_target,
                                refreshed_target,
                            ):
                                starter_target = prepare_keystroke_target(
                                    "starter",
                                    blocked_workshop_targets=tuple(ui_blocked_workshop_targets),
                                )
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
                                if ui_target_mode == "workshop":
                                    ui_workshop_target_blocked = False
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
                            _handle_dfhack_failure(
                                step, f"{label} failed again: {final_exc}", events
                            )
                            raise

                try:
                    state_before = call_with_retry("observe", observe)
                except DFHackError:
                    run_failed = True
                    break
                if is_keystroke_mode:
                    carpenter_workshop_usable_seen = _carry_forward_carpenter_workshop_proof(
                        state_before,
                        carpenter_workshop_usable_seen,
                    )
                screen_text = (
                    get_screen_text() if is_keystroke_mode or is_governed_dfhack_mode else None
                )
                if (
                    str(state_before.get("viewscreen_type") or "unknown")
                    not in INTERACT_ALLOWED_VIEWSCREEN_TYPES
                ):
                    interaction_episode_count = 0
                    interaction_unchanged_screen_streak = 0
                screen_has_material_blocker = bool(
                    is_keystroke_mode and screen_text and "Needs building material" in screen_text
                )
                screen_has_ready_workshop_placement = _screen_shows_ready_workshop_placement(
                    screen_text if is_keystroke_mode else None
                )
                screen_has_workshop_material_selection = _screen_shows_workshop_material_selection(
                    screen_text if is_keystroke_mode else None
                )
                screen_has_blocked_workshop_placement = _screen_shows_blocked_workshop_placement(
                    screen_text if is_keystroke_mode else None
                )
                screen_has_building_type_menu = _screen_shows_building_type_menu(
                    screen_text if is_keystroke_mode else None
                )
                if screen_has_material_blocker:
                    ui_build_material_blocked = True
                if screen_has_blocked_workshop_placement:
                    blocked_key = _workshop_target_key(keystroke_ui_target)
                    if blocked_key is not None:
                        ui_blocked_workshop_targets.add(blocked_key)
                    if (
                        len(ui_blocked_workshop_targets) >= UI_WORKSHOP_BLOCKED_FALLBACK_TARGETS
                        and ui_workshop_blocked_at_work_progress is None
                    ):
                        ui_workshop_blocked_at_work_progress = ui_run_work_progress
                    ui_workshop_target_blocked = True
                    ui_no_progress_streak = max(
                        ui_no_progress_streak,
                        UI_TARGET_REFRESH_NO_PROGRESS_STEPS,
                    )
                elif screen_has_ready_workshop_placement or screen_has_workshop_material_selection:
                    ui_build_material_blocked = False
                if backend_name == "dfhack" and is_keystroke_mode:
                    if (
                        screen_has_ready_workshop_placement
                        or screen_has_workshop_material_selection
                    ):
                        ui_target_mode = "workshop"
                        ui_workshop_target_blocked = False
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
                        if ui_material_target_exhausted and desired_target_mode == "material":
                            desired_target_mode = _material_exhausted_fallback_target_mode(
                                state_before,
                                ui_run_excavation_progress=ui_run_excavation_progress,
                                ui_successful_targets=ui_successful_targets,
                                build_material_blocked=ui_build_material_blocked,
                            )
                        if desired_target_mode == "workshop" and _workshop_blocked_fallback_active(
                            len(ui_blocked_workshop_targets),
                            ui_workshop_blocked_at_work_progress,
                            ui_run_work_progress,
                        ):
                            desired_target_mode = "starter"
                        if desired_target_mode != ui_target_mode:
                            refreshed_target = prepare_keystroke_target(
                                desired_target_mode,
                                blocked_workshop_targets=tuple(ui_blocked_workshop_targets),
                            )
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
                                if desired_target_mode == "workshop":
                                    ui_workshop_target_blocked = False
                                if ui_target_mode == "material":
                                    refresh_reason = "switching to material acquisition target"
                                elif ui_target_mode == "existing_workshop":
                                    refresh_reason = (
                                        "switching to existing workshop inspection target"
                                    )
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
                        material_needs_menu_escape = ui_target_mode == "material" and (
                            screen_has_material_blocker or screen_has_building_type_menu
                        )
                        workshop_blocked_menu_escape = ui_target_mode == "workshop" and (
                            screen_has_blocked_workshop_placement
                            or (ui_workshop_target_blocked and screen_has_building_type_menu)
                        )
                        recovery_prefix = (
                            list(UI_MATERIAL_BLOCKER_ESCAPE_KEYS)
                            if material_needs_menu_escape or workshop_blocked_menu_escape
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
                    if ui_workshop_target_blocked:
                        state_before["ui_workshop_feedback"] = {
                            "placement_blocked": True,
                            "blocked_target_count": len(ui_blocked_workshop_targets),
                            "blocked_targets": [
                                [x, y, z] for x, y, z in sorted(ui_blocked_workshop_targets)
                            ],
                            "menu_escape_keys": (
                                list(UI_MATERIAL_BLOCKER_ESCAPE_KEYS)
                                if screen_has_blocked_workshop_placement
                                or screen_has_building_type_menu
                                else []
                            ),
                            "message": (
                                "native DF rejected this carpenter workshop footprint as blocked; exit build menus, use a fresh workshop target that skips blocked footprints, or return to excavation"
                            ),
                        }
                    state_before["ui_run_progress"] = {
                        "total_work_delta": ui_run_work_progress,
                        "total_excavation_delta": ui_run_excavation_progress,
                        "total_material_delta": ui_run_material_progress,
                        "successful_targets": ui_successful_targets,
                    }
                governed_snapshot_rect = None
                if backend_name == "dfhack" and is_governed_dfhack_mode:
                    governed_snapshot_rect = _map_snapshot_rect_from_state(state_before)
                    if governed_snapshot_rect:
                        map_snapshot_before = read_map_snapshot(governed_snapshot_rect)

                if baseline_work is None:
                    work_snapshot = state_before.get("work")
                    baseline_work = dict(work_snapshot) if isinstance(work_snapshot, dict) else {}
                if baseline_fort is None:
                    fort_snapshot = state_before.get("fort")
                    baseline_fort = dict(fort_snapshot) if isinstance(fort_snapshot, dict) else {}
                crew_snapshot = state_before.get("crew")
                current_goods = (
                    dict(crew_snapshot.get("goods"))
                    if isinstance(crew_snapshot, dict)
                    and isinstance(crew_snapshot.get("goods"), dict)
                    else None
                )
                if baseline_goods is None and current_goods is not None:
                    baseline_goods = dict(current_goods)
                if baseline_wealth is None:
                    stocks_snapshot = state_before.get("stocks")
                    if isinstance(stocks_snapshot, dict):
                        baseline_wealth = _int_or_none(stocks_snapshot.get("wealth")) or 0

                obs_text, obs_json = encode_observation(
                    state_before,
                    screen_text=screen_text,
                    action_history=(
                        action_history
                        if is_keystroke_mode or is_governed_dfhack_mode
                        else None
                    ),
                    governed=is_governed_dfhack_mode,
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
                    _write_durable_jsonl_record(
                        fh,
                        {
                            "run_id": run_identifier,
                            "step": step,
                            "observation": obs_json,
                            "observation_text": obs_text,
                            "stopped": {"reason": "stop_requested_before_agent_decide"},
                            "events": events,
                        },
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
                    terminal_failure_reason = {
                        "code": "agent_decide_error",
                        **error_payload,
                    }
                    terminal_failure_step = step
                    publish_event(
                        step,
                        "terminal",
                        {"terminal_reason": terminal_failure_reason},
                        events,
                    )
                    _write_durable_jsonl_record(
                        fh,
                        {
                            "run_id": run_identifier,
                            "step": step,
                            "observation": obs_json,
                            "observation_text": obs_text,
                            "error": error_payload,
                            "terminal_reason": terminal_failure_reason,
                            "events": events,
                        },
                    )
                    if registry:
                        registry.record_pending_terminal_failure(
                            run_identifier,
                            terminal_reason=terminal_failure_reason,
                            step=step,
                        )
                    run_failed = True
                    break

                if registry and registry.stop_requested(run_identifier):
                    run_stopped = True
                    publish_event(
                        step,
                        "stopped",
                        {"reason": "stop_requested_after_agent_decide"},
                        events,
                    )
                    _write_durable_jsonl_record(
                        fh,
                        {
                            "run_id": run_identifier,
                            "step": step,
                            "observation": obs_json,
                            "observation_text": obs_text,
                            "raw_action": raw_action,
                            "stopped": {"reason": "stop_requested_after_agent_decide"},
                            "events": events,
                        },
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

                if isinstance(raw_action, list) or any(
                    k in raw_action for k in ("actions", "plan")
                ):
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
                    if record_pre_execution_rejection(
                        step=step,
                        state=obs_json,
                        reason=reason,
                        events=events,
                        record_line=record_line,
                    ):
                        break
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
                    if record_pre_execution_rejection(
                        step=step,
                        state=obs_json,
                        reason=str(exc),
                        events=events,
                        record_line=record_line,
                    ):
                        break
                    continue

                valid, reason = validate_action(obs_json, action)
                blocking_rejection_reason = (
                    blocking_viewscreen_action_reason(obs_json, action)
                    if is_governed_dfhack_mode
                    else None
                )
                if valid and blocking_rejection_reason is not None:
                    reason = blocking_rejection_reason
                    valid = False
                if valid and action.get("type") == "INTERACT":
                    reason = _interact_context_reason(
                        backend_name=backend_name,
                        is_governed_dfhack_mode=is_governed_dfhack_mode,
                        state=obs_json,
                        action=action,
                        screen_text=screen_text,
                    )
                    valid = reason is None
                validation = {"valid": valid, "reason": reason}
                publish_event(step, "validation", validation, events)
                if not valid:
                    requested_ticks = action.get("advance_ticks", 0)
                    validation_execute_result: Dict[str, Any] = {
                        "accepted": False,
                        "why": reason,
                        "result": {
                            "ok": False,
                            "error": "validation_rejected",
                            "reason": reason,
                        },
                        "gameplay_progress_eligible": False,
                        "validation_rejected": True,
                    }
                    validation_gameplay_proof = None
                    if is_governed_dfhack_mode:
                        validation_execute_result["provenance"] = "dfhack_governed"
                        validation_gameplay_proof = _governed_gameplay_proof(
                            action=action,
                            execute_result=validation_execute_result,
                            metrics_snapshot={},
                            before_map_snapshot=map_snapshot_before,
                            after_map_snapshot=map_snapshot_before,
                            state_before=state_before,
                            advance_state=state_before,
                            tick_info={"ticks_advanced": 0},
                            score_value=0.0,
                        )
                    last_action_result = {
                        "accepted": False,
                        "reason": reason,
                        "_action": action,
                        "_action_step": step,
                    }
                    validation_metrics = current_governed_score_metrics()
                    if is_keystroke_mode or is_governed_dfhack_mode:
                        _record_action_history(
                            action_history,
                            action_history_limit=action_history_limit,
                            step=step,
                            action=action,
                            requested_ticks=requested_ticks,
                            tick_info={"ticks_advanced": 0},
                            execute_result=validation_execute_result,
                            state_before=state_before,
                            advance_state=state_before,
                            metrics_snapshot={},
                        )
                    record_line = {
                        "run_id": run_identifier,
                        "step": step,
                        "observation": obs_json,
                        "observation_text": obs_text,
                        "action": action,
                        "validation": validation,
                        "execute": validation_execute_result,
                        "state_after_apply": state_before,
                        "state_after_advance": state_before,
                        "screen_text": screen_text,
                        "map_snapshot": map_snapshot_before,
                        "gameplay_proof": validation_gameplay_proof,
                        "tick_advance": {
                            "ok": True,
                            "requested_ticks": requested_ticks,
                            "ticks_advanced": 0,
                            "validation_rejected": True,
                        },
                        "metrics": validation_metrics,
                        "events": events,
                    }
                    if record_pre_execution_rejection(
                        step=step,
                        state=obs_json,
                        reason=reason,
                        events=events,
                        record_line=record_line,
                    ):
                        break
                    continue

                if backend_name == "dfhack" and is_governed_dfhack_mode:
                    governed_action_rect = _governed_dig_rect_from_action(action)
                    if governed_action_rect is not None:
                        governed_action_snapshot_before = read_map_snapshot(
                            governed_action_rect
                        )

                try:
                    apply_state = obs_json
                    if action.get("type") == "INTERACT":
                        apply_state = {**obs_json, "screen_text": screen_text}
                    execute_result = call_with_retry(
                        "apply", lambda: apply_action(action, apply_state)
                    )
                except DFHackError:
                    run_failed = True
                    break
                if action.get("type") == "INTERACT":
                    interaction_result = (
                        dict(execute_result.get("result"))
                        if isinstance(execute_result.get("result"), dict)
                        else {}
                    )
                    interaction_result.update(
                        {
                            "viewscreen_before": obs_json.get("viewscreen_type"),
                            "pause_before": obs_json.get("pause_state"),
                            "screen_before_sha256": _screen_sha256(screen_text),
                        }
                    )
                    execute_result = {**execute_result, "result": interaction_result}
                if (
                    backend_name == "dfhack"
                    and is_governed_dfhack_mode
                    and action.get("type") in GOVERNED_DFHACK_ACTIONS
                ):
                    execute_result = {
                        **execute_result,
                        "provenance": "dfhack_governed",
                        # Final eligibility is set only after post-tick proof.
                        "gameplay_progress_eligible": False,
                    }
                elif backend_name == "dfhack" and action.get("type") in ASSISTED_DFHACK_ACTIONS:
                    execute_result = {
                        **execute_result,
                        "provenance": "dfhack_assisted",
                        "gameplay_progress_eligible": False,
                    }
                    if execute_result.get("accepted", False):
                        assisted_dfhack_action_seen = True
                if (
                    backend_name == "dfhack"
                    and is_governed_dfhack_mode
                    and governed_action_rect is not None
                    and execute_result.get("accepted") is True
                ):
                    governed_action_snapshot_applied = read_map_snapshot(governed_action_rect)
                    governed_action_owned_delta = (
                        metrics.governed_action_footprint_progress_delta(
                            action,
                            governed_action_snapshot_before,
                            governed_action_snapshot_applied,
                        )
                    )
                    params = action.get("params") if isinstance(action.get("params"), dict) else {}
                    owned_kind = str(params.get("kind") or "dig").lower()
                    for coord in governed_action_owned_delta.get(
                        "governed_owned_tiles_added", []
                    ):
                        if not isinstance(coord, list) or len(coord) != 3:
                            continue
                        key = (int(coord[0]), int(coord[1]), int(coord[2]))
                        governed_action_owned_keys.add(key)
                        governed_owned_excavation[key] = owned_kind
                    for coord in governed_action_owned_delta.get(
                        "governed_designated_tiles", []
                    ):
                        if isinstance(coord, list) and len(coord) == 3:
                            governed_designated_tiles.add(
                                (int(coord[0]), int(coord[1]), int(coord[2]))
                            )
                    for coord in governed_action_owned_delta.get(
                        "governed_completed_tiles", []
                    ):
                        if isinstance(coord, list) and len(coord) == 3:
                            governed_completed_tiles.add(
                                (int(coord[0]), int(coord[1]), int(coord[2]))
                            )
                    channel_focus = _owned_channel_focus_rect(
                        action, governed_action_owned_delta
                    )
                    if channel_focus is not None:
                        governed_channel_focus = channel_focus

                result_payload = (
                    execute_result.get("result")
                    if isinstance(execute_result.get("result"), dict)
                    else {}
                )
                if (
                    backend_name == "dfhack"
                    and is_governed_dfhack_mode
                    and _governed_rollback_unverified(result_payload)
                ):
                    execution_terminal_reason = {
                        "code": "governed_rollback_unverified",
                        "action_type": action.get("type"),
                        "helper_error": result_payload.get("error"),
                        "helper_detail": result_payload.get("detail"),
                    }
                if action.get("type") != "INTERACT":
                    publish_event(step, "execute", {"result": execute_result}, events)
                state_after_apply = execute_result.get("state") or state_before

                if (
                    action.get("type") != "INTERACT"
                    and registry
                    and registry.stop_requested(run_identifier)
                ):
                    run_stopped = True
                    publish_event(
                        step,
                        "stopped",
                        {"reason": "stop_requested_after_execute"},
                        events,
                    )
                    _write_durable_jsonl_record(
                        fh,
                        {
                            "run_id": run_identifier,
                            "step": step,
                            "observation": obs_json,
                            "observation_text": obs_text,
                            "action": action,
                            "validation": validation,
                            "execute": execute_result,
                            "state_after_apply": state_after_apply,
                            "metrics": current_governed_score_metrics(),
                            "stopped": {"reason": "stop_requested_after_execute"},
                            "events": events,
                        },
                    )
                    break

                # Track action result for next step's feedback
                last_action_result = execute_result
                if (
                    is_keystroke_mode
                    and action.get("type") == "KEYSTROKE"
                    and execute_result.get("accepted", False)
                ):
                    target_setup = state_before.get("ui_target_setup")
                    target_setup_exit_only = isinstance(target_setup, dict) and bool(
                        target_setup.get("recommended_keys_exit_only")
                    )
                    if not (target_setup_exit_only and _is_exit_only_recovery_action(action)):
                        ui_target_attempts += 1

                # Use agent-requested ticks, falling back to default if not specified
                requested_ticks = action.get("advance_ticks", ticks)
                if execution_terminal_reason is not None:
                    advance_state = state_after_apply
                    tick_info_state = {
                        "ok": False,
                        "ticks_advanced": 0,
                        "skipped": True,
                        "error": "governed_rollback_unverified",
                    }
                else:
                    try:
                        advance_state = call_with_retry(
                            "advance", lambda: advance_env(requested_ticks)
                        )
                    except DFHackError:
                        run_failed = True
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
                if action.get("type") == "INTERACT":
                    interaction_screen_after = get_screen_text()
                    interaction_result = (
                        dict(execute_result.get("result"))
                        if isinstance(execute_result.get("result"), dict)
                        else {}
                    )
                    viewscreen_before = str(obs_json.get("viewscreen_type") or "unknown")
                    viewscreen_after = str(advance_state.get("viewscreen_type") or "unknown")
                    screen_before_sha256 = _screen_sha256(screen_text)
                    screen_after_sha256 = _screen_sha256(interaction_screen_after)
                    screen_changed = (
                        screen_before_sha256 != screen_after_sha256
                        or viewscreen_before != viewscreen_after
                    )
                    interaction_audit = {
                        "operation": interaction_result.get("operation"),
                        "interface_key": interaction_result.get("interface_key"),
                        "keys_sent": interaction_result.get("keys_sent"),
                        "viewscreen_before": viewscreen_before,
                        "viewscreen_after": viewscreen_after,
                        "pause_before": obs_json.get("pause_state"),
                        "pause_after": advance_state.get("pause_state"),
                        "screen_before_sha256": screen_before_sha256,
                        "screen_after_sha256": screen_after_sha256,
                        "screen_changed": screen_changed,
                    }
                    if (
                        interaction_result.get("operation") == "finish_topic_meeting"
                        or interaction_result.get("operation")
                        in TOPIC_MEETING_OPTION_OPERATIONS
                    ):
                        post_screen_captured = interaction_screen_after != SCREEN_CAPTURE_FAILED
                        if interaction_result.get("operation") == "finish_topic_meeting":
                            semantic_effect_observed = (
                                viewscreen_after != "viewscreen_topicmeetingst"
                                or (
                                    post_screen_captured
                                    and FINISH_TOPIC_MEETING_OPTION_TEXT
                                    not in interaction_screen_after
                                )
                            )
                        else:
                            semantic_effect_observed = post_screen_captured and screen_changed
                        interaction_audit["post_screen_captured"] = post_screen_captured
                        interaction_audit["semantic_effect_observed"] = semantic_effect_observed
                        if not semantic_effect_observed:
                            interaction_result.update(
                                {
                                    "ok": False,
                                    "error": "interaction_no_effect",
                                }
                            )
                            execute_result = {
                                **execute_result,
                                "accepted": False,
                                "why": "interaction_no_effect",
                            }
                    interaction_result.update(interaction_audit)
                    execute_result = {**execute_result, "result": interaction_result}
                    last_action_result = execute_result
                    publish_event(step, "execute", {"result": execute_result}, events)
                    publish_event(
                        step,
                        "interaction",
                        {"interaction": interaction_audit},
                        events,
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
                if registry and registry.stop_requested(run_identifier):
                    run_stopped = True
                    publish_event(
                        step,
                        "stopped",
                        {"reason": "stop_requested_after_advance"},
                        events,
                    )
                    _write_durable_jsonl_record(
                        fh,
                        {
                            "run_id": run_identifier,
                            "step": step,
                            "observation": obs_json,
                            "observation_text": obs_text,
                            "action": action,
                            "validation": validation,
                            "execute": execute_result,
                            "state_after_apply": state_after_apply,
                            "state_after_advance": advance_state,
                            "metrics": current_governed_score_metrics(),
                            "tick_advance": tick_info_state,
                            "stopped": {"reason": "stop_requested_after_advance"},
                            "events": events,
                        },
                    )
                    break
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

                if governed_action_rect is not None:
                    governed_action_snapshot_after = read_map_snapshot(
                        governed_action_rect
                    )

                metrics_snapshot = metrics.step_snapshot(advance_state)
                current_work = advance_state.get("work")
                advance_crew = advance_state.get("crew")
                current_goods_after = (
                    advance_crew.get("goods")
                    if isinstance(advance_crew, dict)
                    and isinstance(advance_crew.get("goods"), dict)
                    else current_goods
                )
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
                        current_goods=current_goods_after,
                        baseline_goods=baseline_goods,
                        population=advance_state.get("population"),
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
                        current_fort=advance_state.get("fort") or state_before.get("fort"),
                        baseline_fort=baseline_fort,
                    )
                )
                current_ui_work = advance_state.get("ui_work")
                ui_delta = {}
                ui_step_work_progress = 0
                ui_step_excavation_progress = 0
                ui_step_material_progress = 0
                keystroke_productive_deltas: Dict[str, int] = {}
                if is_keystroke_mode:
                    keystroke_productive_deltas = _keystroke_productive_state_deltas(
                        state_before,
                        advance_state,
                    )
                    completed_workshop_tasks = int(
                        keystroke_productive_deltas.get(
                            "carpenter_workshop_completed_tasks",
                            0,
                        )
                    )
                    if completed_workshop_tasks > 0:
                        ui_run_completed_workshop_tasks += completed_workshop_tasks
                    if ui_run_completed_workshop_tasks > 0:
                        production_unit = int(getattr(metrics, "PRODUCTION_WORKSHOP_PROGRESS", 5))
                        metrics_snapshot[
                            "production_completed_tasks"
                        ] = ui_run_completed_workshop_tasks
                        metrics_snapshot[
                            "production_completed_tasks_delta"
                        ] = completed_workshop_tasks
                        metrics_snapshot["production_progress"] = max(
                            int(metrics_snapshot.get("production_progress") or 0),
                            int(metrics_snapshot.get("production_progress") or 0)
                            + ui_run_completed_workshop_tasks * production_unit,
                        )
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
                        made_state_progress = bool(keystroke_productive_deltas)
                        made_tracked_progress = (
                            ui_step_work_progress > 0
                            or ui_step_material_progress > 0
                            or made_state_progress
                        )
                        target_step_succeeded = (
                            _ui_target_step_succeeded(
                                ui_target_mode,
                                ui_step_work_progress=ui_step_work_progress,
                                ui_step_material_progress=ui_step_material_progress,
                            )
                            or made_state_progress
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
                            if (
                                ui_target_mode == "starter"
                                and ui_step_work_progress > 0
                                and ui_workshop_blocked_at_work_progress is not None
                                and ui_run_work_progress > ui_workshop_blocked_at_work_progress
                            ):
                                ui_workshop_blocked_at_work_progress = None
                                ui_workshop_target_blocked = False
                            if target_step_succeeded:
                                ui_no_progress_streak = 0
                            elif ui_target_mode == "material":
                                ui_no_progress_streak += 1
                            ui_work_feedback = {
                                "last_ui_work_progress_delta": ui_step_work_progress,
                                "last_ui_excavation_delta": ui_step_excavation_progress,
                                "last_ui_material_delta": ui_step_material_progress,
                                "last_state_progress_delta": keystroke_productive_deltas,
                                "no_progress_streak": ui_no_progress_streak,
                                "target_step_succeeded": target_step_succeeded,
                                "message": (
                                    "last UI action changed tracked tiles but did not acquire usable material"
                                    if ui_target_mode == "material" and not target_step_succeeded
                                    else (
                                        "last action changed real workshop state or consumed production material"
                                        if made_state_progress
                                        else "last UI action changed real map tiles or material stocks"
                                    )
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
                    metrics_snapshot[
                        "ui_run_completed_workshop_tasks"
                    ] = ui_run_completed_workshop_tasks
                    metrics_snapshot["ui_successful_targets"] = ui_successful_targets
                utility_action = metrics.utility_action_progress(action, execute_result)
                metrics_snapshot.update(utility_action)
                # score-v3: utility_progress can now be a float (demand-capped
                # production pays a 0.2 surplus rate) — do not int()-truncate
                # it away here, that would silently discard the surplus pay.
                metrics_snapshot["utility_progress"] = max(
                    metrics_snapshot.get("utility_progress") or 0,
                    int(utility_action.get("utility_action_progress") or 0),
                )
                if backend_name == "dfhack" and is_governed_dfhack_mode:
                    metrics_snapshot["observed_global_work_progress"] = int(
                        metrics_snapshot.get("work_progress") or 0
                    )
                    metrics_snapshot["observed_global_completion_progress"] = int(
                        metrics_snapshot.get("completion_progress") or 0
                    )
                    metrics_snapshot["observed_global_utility_progress"] = float(
                        metrics_snapshot.get("utility_progress") or 0
                    )
                    metrics_snapshot["observed_global_production_progress"] = int(
                        metrics_snapshot.get("production_progress") or 0
                    )
                    metrics_snapshot["observed_global_complexity_progress"] = float(
                        metrics_snapshot.get("complexity_progress") or 0
                    )

                    governed_owned_buildings.update(
                        _governed_building_claims(action, execute_result)
                    )
                    governed_completed_buildings.update(
                        _governed_completed_owned_buildings(
                            governed_owned_buildings,
                            advance_state,
                        )
                    )
                    newly_completed_owned_buildings = sorted(
                        governed_completed_buildings
                        - governed_completed_buildings_before_step
                    )
                    owned_building_progress = _governed_owned_building_progress(
                        governed_owned_buildings,
                        governed_completed_buildings,
                    )
                    metrics_snapshot.update(owned_building_progress)
                    metrics_snapshot["governed_step_owned_completed_building_ids"] = (
                        newly_completed_owned_buildings
                    )
                    metrics_snapshot["utility_progress"] = owned_building_progress[
                        "governed_owned_utility_progress"
                    ]
                    metrics_snapshot["production_progress"] = owned_building_progress[
                        "governed_owned_production_progress"
                    ]
                    metrics_snapshot["complexity_progress"] = owned_building_progress[
                        "governed_owned_complexity_progress"
                    ]
                    if governed_snapshot_rect is not None:
                        map_snapshot = read_map_snapshot(governed_snapshot_rect)
                    pending_owned_excavation = {
                        coordinate: kind
                        for coordinate, kind in governed_owned_excavation.items()
                        if coordinate not in governed_completed_tiles
                    }
                    owned_observation_snapshots = [
                        read_map_snapshot(rect)
                        for rect in _owned_excavation_snapshot_rects(
                            pending_owned_excavation
                        )
                    ]
                    completed_observations = (
                        metrics.governed_owned_excavation_completion_tiles(
                            governed_owned_excavation,
                            *owned_observation_snapshots,
                            governed_action_snapshot_after,
                        )
                    )
                    for coord in completed_observations:
                        governed_completed_tiles.add(
                            (int(coord[0]), int(coord[1]), int(coord[2]))
                        )

                    newly_completed_owned = sorted(
                        governed_completed_tiles - governed_completed_before_step
                    )
                    step_completed = sorted(
                        governed_action_owned_keys
                        & set(newly_completed_owned)
                    )
                    owned_delta = {
                        **governed_action_owned_delta,
                        "governed_step_completion_progress": len(step_completed),
                        "governed_completed_tiles": [list(coord) for coord in step_completed],
                    }
                    metrics_snapshot.update(owned_delta)

                    metrics_snapshot["designation_progress"] = len(
                        governed_designated_tiles
                    )
                    metrics_snapshot["work_progress"] = len(governed_completed_tiles)
                    metrics_snapshot["completion_progress"] = len(
                        governed_completed_tiles
                    )
                    metrics_snapshot["governed_owned_excavation_tiles"] = len(
                        governed_owned_excavation
                    )
                    metrics_snapshot["governed_owned_designation_progress"] = len(
                        governed_designated_tiles
                    )
                    metrics_snapshot["governed_owned_work_progress"] = len(
                        governed_completed_tiles
                    )
                    metrics_snapshot["governed_owned_completion_progress"] = len(
                        governed_completed_tiles
                    )
                    metrics_snapshot["governed_step_owned_completion_progress"] = len(
                        newly_completed_owned
                    )
                    metrics_snapshot["governed_step_owned_completion_tiles"] = [
                        list(coord) for coord in newly_completed_owned
                    ]
                    metrics_snapshot["governed_owned_observation_rects"] = len(
                        owned_observation_snapshots
                    )
                    metrics_snapshot[
                        "score_progress_provenance"
                    ] = scoring.GOVERNED_SCORE_PROGRESS_PROVENANCE
                    interaction_only = action.get("type") == "INTERACT"
                    metrics_snapshot["score_provenance"] = (
                        "dfhack_governed_interaction_only"
                        if interaction_only
                        else "dfhack_governed_observed_state_action_owned_progress"
                    )
                    fort_after = advance_state.get("fort")
                    fort_metrics_observed = bool(
                        isinstance(fort_after, dict) and fort_after.get("ok") is True
                    )
                    metrics_snapshot["fort_metrics_observed"] = fort_metrics_observed
                    if fort_metrics_observed:
                        metrics_snapshot["fort_enclosed_spaces"] = int(
                            fort_after.get("enclosed_spaces") or 0
                        )
                        metrics_snapshot["fort_functional_rooms"] = int(
                            fort_after.get("functional_rooms") or 0
                        )
                        metrics_snapshot["fort_constructions"] = int(
                            fort_after.get("constructions") or 0
                        )
                    else:
                        # A failed current read cannot inherit structure from an
                        # earlier observation. Zero the scoring surface while the
                        # explicit flag preserves the distinction from observed zero.
                        metrics_snapshot["fort_enclosed_spaces"] = 0
                        metrics_snapshot["fort_functional_rooms"] = 0
                        metrics_snapshot["fort_constructions"] = 0
                    gameplay_proof = _governed_gameplay_proof(
                        action=action,
                        execute_result=execute_result,
                        metrics_snapshot=metrics_snapshot,
                        before_map_snapshot=map_snapshot_before,
                        after_map_snapshot=map_snapshot,
                        state_before=state_before,
                        advance_state=advance_state,
                        tick_info=tick_info_state,
                        score_value=0.0,
                    )
                    gameplay_proof["action_footprint"] = {
                        "rect": list(governed_action_rect)
                        if governed_action_rect is not None
                        else None,
                        "tile_changes": _snapshot_tile_changes(
                            governed_action_snapshot_before,
                            governed_action_snapshot_after,
                        ),
                        "applied_tile_changes": _snapshot_tile_changes(
                            governed_action_snapshot_before,
                            governed_action_snapshot_applied,
                        ),
                        "owned_delta": owned_delta,
                    }
                    owned_completion_evidence = [
                        {
                            "coordinate": list(coord),
                            "kind": governed_owned_excavation[coord],
                        }
                        for coord in newly_completed_owned
                    ]
                    gameplay_proof["owned_completion_observation"] = {
                        "source": "camera_independent_bounded_map_snapshot",
                        "completed_tiles": owned_completion_evidence,
                    }
                    owned_building_completion_evidence = [
                        {
                            "building_id": building_id,
                            "kind": governed_owned_buildings[building_id],
                        }
                        for building_id in newly_completed_owned_buildings
                    ]
                    gameplay_proof["owned_building_completion_observation"] = {
                        "source": "job_metrics_exact_building_id_and_native_stage",
                        "completed_buildings": owned_building_completion_evidence,
                    }
                    if owned_completion_evidence or owned_building_completion_evidence:
                        gameplay_proof.update(
                            {
                                "ok": True,
                                "gameplay_progress_eligible": True,
                                "action_effect_observed": True,
                                "owned_prior_action_effect_observed": (
                                    action.get("type") == "WAIT"
                                ),
                                "concurrent_world_state_changed": False,
                            }
                        )
                    progress_eligible = bool(gameplay_proof.get("ok"))
                    result_payload = (
                        execute_result.get("result")
                        if isinstance(execute_result.get("result"), dict)
                        else {}
                    )
                    if (
                        governed_completed_tiles
                        or governed_completed_buildings
                        or _governed_durable_helper_progress(action, result_payload)
                    ):
                        governed_score_progress_seen = True
                    execute_result = {
                        **execute_result,
                        "gameplay_progress_eligible": progress_eligible,
                        "governed_current_action_effect_observed": bool(
                            int(
                                owned_delta.get("governed_step_completion_progress")
                                or 0
                            )
                            > 0
                        ),
                        "governed_wait_effect_observed": bool(
                            action.get("type") == "WAIT"
                            and (
                                owned_completion_evidence
                                or owned_building_completion_evidence
                            )
                        ),
                    }
                    last_action_result = execute_result
                    metrics_snapshot["gameplay_progress_eligible"] = progress_eligible
                    metrics_snapshot["governed_dfhack_progress"] = progress_eligible
                if is_keystroke_mode or is_governed_dfhack_mode:
                    _record_action_history(
                        action_history,
                        action_history_limit=action_history_limit,
                        step=step,
                        action=action,
                        requested_ticks=requested_ticks,
                        tick_info=tick_info_state,
                        execute_result=execute_result,
                        state_before=state_before,
                        advance_state=advance_state,
                        metrics_snapshot=metrics_snapshot,
                    )
                if isinstance(last_action_result, dict):
                    last_action_result = {
                        **last_action_result,
                        "_action": action,
                        "_action_step": step,
                    }
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
                elif (
                    backend_name == "dfhack"
                    and is_governed_dfhack_mode
                    and not governed_score_progress_seen
                ):
                    metrics_snapshot["observed_run_elapsed_ticks"] = elapsed_ticks_total
                    metrics_snapshot["score_duration_blocked"] = True
                    metrics_snapshot[
                        "score_provenance"
                    ] = "dfhack_governed_no_gameplay_progress_yet"
                    score_elapsed_ticks = 0
                elif backend_name == "dfhack" and is_governed_dfhack_mode:
                    metrics_snapshot["score_duration_blocked"] = False
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
                        metrics_snapshot[
                            "score_provenance"
                        ] = "keystroke_no_current_gameplay_progress"
                    score_elapsed_ticks = scoreable_elapsed_ticks
                metrics_snapshot["score_version"] = scoring.SCORE_VERSION
                metrics_snapshot["run_elapsed_ticks"] = score_elapsed_ticks
                publish_event(step, "metrics", {"metrics": metrics_snapshot}, events)

                score_metrics = dict(metrics_snapshot)
                score_metrics["time"] = score_elapsed_ticks
                if baseline_wealth is not None:
                    current_wealth = _int_or_none(score_metrics.get("wealth"))
                    if current_wealth is not None:
                        score_metrics["created_wealth"] = max(
                            0,
                            current_wealth - baseline_wealth,
                        )
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
                        "version": scoring.SCORE_VERSION,
                        "milestones": milestone_notes,
                    },
                    events,
                )

                previous_state = advance_state

                if backend_name == "dfhack":
                    if is_keystroke_mode and ui_work_rect is not None:
                        snapshot_rect = ui_work_rect
                    elif is_governed_dfhack_mode:
                        snapshot_rect = governed_snapshot_rect
                    else:
                        snapshot_rect = _map_snapshot_rect_from_state(advance_state)
                    if snapshot_rect and map_snapshot is None:
                        map_snapshot = read_map_snapshot(snapshot_rect)
                    if map_snapshot is not None:
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
                    elif is_governed_dfhack_mode:
                        if gameplay_proof is None:
                            gameplay_proof = _governed_gameplay_proof(
                                action=action,
                                execute_result=execute_result,
                                metrics_snapshot=metrics_snapshot,
                                before_map_snapshot=map_snapshot_before,
                                after_map_snapshot=map_snapshot,
                                state_before=state_before,
                                advance_state=advance_state,
                                tick_info=tick_info_state,
                                score_value=score_value,
                            )
                        else:
                            gameplay_proof = {**gameplay_proof, "score": score_value}
                        publish_event(
                            step,
                            "gameplay_proof",
                            {"gameplay_proof": gameplay_proof},
                            events,
                        )

                terminal_reason = execution_terminal_reason
                degraded_tick = None
                if terminal_reason is None:
                    (
                        terminal_reason,
                        degraded_tick,
                        consecutive_zero_tick_streak,
                    ) = _tick_terminal_reason(
                        requested_ticks,
                        tick_info_state,
                        consecutive_zero_tick_streak,
                    )
                if int(tick_info_state.get("ticks_advanced") or 0) > 0:
                    interaction_episode_count = 0
                    interaction_unchanged_screen_streak = 0
                interaction_terminal_reason = None
                (
                    interaction_terminal_reason,
                    interaction_episode_count,
                    interaction_unchanged_screen_streak,
                ) = _interaction_terminal_reason(
                    action_type=str(action.get("type") or ""),
                    interaction_audit=interaction_audit,
                    state_after=advance_state,
                    episode_count=interaction_episode_count,
                    unchanged_screen_streak=interaction_unchanged_screen_streak,
                )
                if terminal_reason is None:
                    terminal_reason = interaction_terminal_reason
                if degraded_tick is not None:
                    publish_event(
                        step,
                        "tick_degraded",
                        {"tick_degraded": degraded_tick},
                        events,
                    )
                if terminal_reason is not None:
                    terminal_event = {
                        "type": "terminal",
                        "data": {
                            "run_id": run_identifier,
                            "step": step,
                            "terminal_reason": terminal_reason,
                        },
                    }
                    events.append(terminal_event)

                record_line = {
                    "run_id": run_identifier,
                    "step": step,
                    "score_version": scoring.SCORE_VERSION,
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
                        "version": scoring.SCORE_VERSION,
                        "milestones": milestone_notes,
                    },
                    "events": events,
                    "tick_advance": tick_info_state,
                }
                if map_snapshot is not None:
                    record_line["map_snapshot"] = map_snapshot
                if gameplay_proof is not None:
                    record_line["gameplay_proof"] = gameplay_proof
                if screen_text:
                    record_line["screen_text"] = screen_text
                if interaction_audit is not None:
                    record_line["interaction"] = interaction_audit
                if interaction_screen_after:
                    record_line["screen_text_after_interaction"] = interaction_screen_after
                if degraded_tick is not None:
                    record_line["tick_degraded"] = degraded_tick
                if terminal_reason is not None:
                    record_line["terminal_reason"] = terminal_reason
                _write_jsonl_record(fh, record_line)

                if terminal_reason is not None:
                    # Persist the terminal event now; status waits for DF cleanup below.
                    fh.flush()
                    fsync(fh.fileno())
                    terminal_failure_reason = terminal_reason
                    terminal_failure_step = step
                    if registry:
                        registry.record_pending_terminal_failure(
                            run_identifier,
                            terminal_reason=terminal_reason,
                            step=step,
                        )
                        registry.append_event(
                            run_identifier,
                            {"t": "terminal", "data": terminal_event["data"]},
                        )
                    run_failed = True
                    break

                if registry:
                    registry.set_status(run_identifier, step=step)

        cleanup_outcome = cleanup_dfhack_runtime()
        if not cleanup_outcome.get("ok"):
            if registry is None:
                cleanup_failure_without_registry = dict(cleanup_outcome)
            terminal_failure_reason = cleanup_terminal_reason(
                cleanup_outcome,
                prior_reason=terminal_failure_reason,
            )
            terminal_failure_step = last_step
            run_failed = True
            if registry:
                registry.record_pending_terminal_failure(
                    run_identifier,
                    terminal_reason=terminal_failure_reason,
                    step=terminal_failure_step,
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

            if terminal_failure_reason is not None:
                registry.record_terminal_failure(
                    run_identifier,
                    terminal_reason=terminal_failure_reason,
                    step=terminal_failure_step,
                    ended_at=datetime.utcnow(),
                )
                registry.clear_stop(run_identifier)
            elif run_failed:
                registry.set_status(
                    run_identifier,
                    status="failed",
                    step=last_step,
                    ended_at=datetime.utcnow(),
                )
                registry.clear_stop(run_identifier)
            elif run_stopped:
                registry.set_status(
                    run_identifier,
                    status="stopped",
                    step=last_step,
                    ended_at=datetime.utcnow(),
                )
                registry.clear_stop(run_identifier)
            else:
                registry.finalize_success_after_cleanup(
                    run_identifier,
                    step=last_step,
                    ended_at=datetime.utcnow(),
                )

        # Auto-analyze trace with LLM (optional - requires GOOGLE_API_KEY)
        try:
            from ..eval.analyzer import TraceAnalyzer, save_analysis

            if os.environ.get("GOOGLE_API_KEY") and (cleanup_outcome or {}).get("ok"):
                analyzer = TraceAnalyzer()
                analysis = analyzer.analyze(trace_path)
                save_analysis(analysis, trace_path.parent)
        except Exception as e:
            # Analysis is optional - don't fail the run if it errors
            import logging

            logging.getLogger(__name__).warning(f"Auto-analysis skipped: {e}")
    except Exception:
        failed_cleanup = cleanup_dfhack_runtime()
        if registry:
            if failed_cleanup.get("ok"):
                registry.set_status(
                    run_identifier,
                    status="failed",
                    step=last_step,
                    ended_at=datetime.utcnow(),
                )
            else:
                registry.record_terminal_failure(
                    run_identifier,
                    terminal_reason=cleanup_terminal_reason(
                        failed_cleanup,
                        prior_reason=terminal_failure_reason,
                    ),
                    step=last_step,
                    ended_at=datetime.utcnow(),
                )
            registry.clear_stop(run_identifier)
        raise
    finally:
        cleanup_dfhack_runtime()

    if cleanup_failure_without_registry is not None:
        raise RuntimeError(
            "DFHack cleanup remained unverified: "
            f"{cleanup_failure_without_registry.get('errors') or cleanup_failure_without_registry}"
        )

    return run_identifier


__all__ = ["run_once"]
