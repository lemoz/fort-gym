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
from .storage import RUN_REGISTRY, RunRegistry
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
UI_MATERIAL_TARGET_RECOMMENDED_KEY_RETRY_LIMIT = 8
UI_MATERIAL_BLOCKER_ESCAPE_KEYS = ("LEAVESCREEN", "LEAVESCREEN")
UI_MATERIAL_TARGET_MIN_EXCAVATION_PROGRESS = 6


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


def _available_building_materials(state: Dict[str, Any]) -> int:
    stocks = state.get("stocks")
    if not isinstance(stocks, dict):
        return 0
    wood = _int_or_none(stocks.get("wood")) or 0
    stone = _int_or_none(stocks.get("stone")) or 0
    return max(0, wood) + max(0, stone)


def _dict_delta(before: Dict[str, Any], after: Dict[str, Any], key: str) -> int:
    before_value = _int_or_none(before.get(key)) or 0
    after_value = _int_or_none(after.get(key)) or 0
    return after_value - before_value


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
        ("carpenter_workshops", "carpenter_workshop_created"),
        ("workshop_count", "workshop_created_or_queued"),
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
        "intent": action.get("intent", ""),
        "advance_ticks": action.get("advance_ticks", requested_ticks),
        "requested_ticks": requested_ticks,
        "actual_ticks": actual_ticks,
        "accepted": accepted,
        "outcome": outcome,
        "productive_reasons": productive_reasons,
        "changed": changed,
    }


def _desired_keystroke_target_mode(
    state: Dict[str, Any],
    *,
    ui_run_excavation_progress: int,
    ui_successful_targets: int,
    build_material_blocked: bool = False,
) -> str:
    if build_material_blocked:
        return "material"
    if _available_building_materials(state) > 0:
        return "starter"
    if (
        ui_run_excavation_progress >= UI_MATERIAL_TARGET_MIN_EXCAVATION_PROGRESS
        or ui_successful_targets >= 2
    ):
        return "material"
    return "starter"


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
) -> Dict[str, Any]:
    setup = dict(target)
    target_mode = str(setup.get("target_mode") or "starter")
    retry_limit = (
        UI_MATERIAL_TARGET_RECOMMENDED_KEY_RETRY_LIMIT
        if target_mode == "material"
        else UI_TARGET_RECOMMENDED_KEY_RETRY_LIMIT
    )
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
            setup["recommended_keys"] = prefix + list(original_keys)
            setup["recommended_key_prefix"] = prefix
        setup["recommended_keys_suppressed"] = False
        setup["recommended_keys_retry"] = attempts > 0
        setup["recommended_keys_force_shown"] = force_show_recommended
    else:
        setup["recommended_keys"] = []
        setup["recommended_key_prefix"] = []
        setup["recommended_keys_suppressed"] = True
        setup["recommended_keys_retry"] = False
        setup["recommended_keys_force_shown"] = False
    return setup


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

    # Detect keystroke mode from model name
    # Models that need screen capture: *-keystroke, *-research
    is_keystroke_mode = model.endswith("-keystroke") or model.endswith("-research")
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
        except DFHackUnavailableError as exc:  # pragma: no cover - environment guard
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
                    return dfhack_client.get_screen_text()
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

    try:
        with trace_path.open("w", encoding="utf-8") as fh:
            for step in range(max_steps):
                events: List[Dict[str, Any]] = []
                tick_info_state = {}

                pause_env()
                if (
                    backend_name == "dfhack"
                    and is_keystroke_mode
                    and ui_no_progress_streak >= UI_TARGET_REFRESH_NO_PROGRESS_STEPS
                ):
                    refreshed_target = prepare_keystroke_target(ui_target_mode)
                    if refreshed_target.get("ok"):
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
                screen_text = get_screen_text() if is_keystroke_mode else None
                screen_has_material_blocker = bool(
                    is_keystroke_mode
                    and screen_text
                    and "Needs building material" in screen_text
                )
                if screen_has_material_blocker:
                    ui_build_material_blocked = True
                if backend_name == "dfhack" and is_keystroke_mode:
                    desired_target_mode = _desired_keystroke_target_mode(
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
                            ui_work_feedback = {
                                "target_refreshed": True,
                                "target_mode": ui_target_mode,
                                "reason": "switching to material acquisition target",
                            }
                        else:
                            ui_work_feedback = {
                                "target_refresh_failed": True,
                                "target_mode": desired_target_mode,
                                "error": refreshed_target.get("error", "unknown"),
                            }
                    if keystroke_ui_target is not None:
                        recovery_prefix = (
                            list(UI_MATERIAL_BLOCKER_ESCAPE_KEYS)
                            if ui_target_mode == "material" and screen_has_material_blocker
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

                raw_action = agent.decide(obs_text, obs_json)
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
                    ui_target_attempts += 1

                # Use agent-requested ticks, falling back to default if not specified
                requested_ticks = action.get("advance_ticks", ticks)
                try:
                    advance_state = call_with_retry("advance", lambda: advance_env(requested_ticks))
                except DFHackError:
                    if registry:
                        registry.set_status(
                            run_identifier,
                            status="failed",
                            ended_at=datetime.utcnow(),
                        )
                    break
                if backend_name == "dfhack" and is_keystroke_mode and ui_work_rect is not None:
                    ui_work_after = read_work_metrics(ui_work_rect)
                    advance_state["ui_work"] = ui_work_after
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
                        if ui_step_work_progress > 0 or ui_step_material_progress > 0:
                            if not ui_target_progress_seen:
                                ui_successful_targets += 1
                            ui_target_progress_seen = True
                            ui_run_work_progress += ui_step_work_progress
                            ui_run_excavation_progress += ui_step_excavation_progress
                            ui_run_material_progress += ui_step_material_progress
                            if ui_step_material_progress > 0:
                                ui_build_material_blocked = False
                            ui_no_progress_streak = 0
                            ui_work_feedback = {
                                "last_ui_work_progress_delta": ui_step_work_progress,
                                "last_ui_excavation_delta": ui_step_excavation_progress,
                                "last_ui_material_delta": ui_step_material_progress,
                                "no_progress_streak": ui_no_progress_streak,
                                "message": "last UI action changed real map tiles or material stocks",
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
                    metrics_snapshot["score_duration_blocked"] = False
                metrics_snapshot["run_elapsed_ticks"] = score_elapsed_ticks
                publish_event(step, "metrics", {"metrics": metrics_snapshot}, events)

                score_metrics = dict(metrics_snapshot)
                score_metrics["time"] = score_elapsed_ticks
                score_value = scoring.composite_score(score_metrics)
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
                if backend_name == "dfhack":
                    snapshot_rect = (
                        ui_work_rect
                        if is_keystroke_mode and ui_work_rect is not None
                        else _map_snapshot_rect_from_state(advance_state)
                    )
                    if snapshot_rect:
                        map_snapshot = read_map_snapshot(snapshot_rect)
                        publish_event(step, "map_snapshot", {"map_snapshot": map_snapshot}, events)

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
                fh.write(json.dumps(record_line) + "\n")

                if registry:
                    registry.set_status(run_identifier, step=step)

        if registry:
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
