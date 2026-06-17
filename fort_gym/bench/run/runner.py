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
from ..dfhack_backend import read_map_snapshot
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
    last_action_result: Optional[Dict[str, Any]] = None  # Track previous action result for feedback
    previous_screen = None  # Track previous screen for diff feedback (no type annotation for nonlocal)
    assisted_dfhack_action_seen = False

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
                if baseline_work is None:
                    work_snapshot = state_before.get("work")
                    baseline_work = dict(work_snapshot) if isinstance(work_snapshot, dict) else {}

                # Get screen text for keystroke mode
                screen_text = get_screen_text() if is_keystroke_mode else None
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

                # Track action for history (keystroke mode memory)
                if is_keystroke_mode:
                    action_history.append({
                        "step": step,
                        "keys": action.get("params", {}).get("keys", []),
                        "intent": action.get("intent", ""),
                        "advance_ticks": action.get("advance_ticks", ticks),
                    })
                    # Keep only last 5 actions
                    if len(action_history) > 5:
                        action_history.pop(0)

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
                utility_action = metrics.utility_action_progress(action, execute_result)
                metrics_snapshot.update(utility_action)
                metrics_snapshot["utility_progress"] = max(
                    int(metrics_snapshot.get("utility_progress") or 0),
                    int(utility_action.get("utility_action_progress") or 0),
                )
                if assisted_dfhack_action_seen:
                    _zero_assisted_dfhack_progress(metrics_snapshot)
                metrics_snapshot["run_elapsed_ticks"] = elapsed_ticks_total
                publish_event(step, "metrics", {"metrics": metrics_snapshot}, events)

                score_metrics = dict(metrics_snapshot)
                score_metrics["time"] = elapsed_ticks_total
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
                    snapshot_rect = _map_snapshot_rect_from_state(advance_state)
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
