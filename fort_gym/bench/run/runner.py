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
from ..env.state_reader import StateReader
from ..eval import metrics, milestones, scoring
from ..eval.summary import RunSummary, summarize
from .storage import RUN_REGISTRY, RunRegistry


def _artifacts_root() -> Path:
    settings = get_settings()
    return Path(settings.ARTIFACTS_DIR).resolve()


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
) -> str:
    """Execute a run and persist a JSONL trace while streaming events."""

    settings = get_settings()
    backend_name = env or backend
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

    # Detect keystroke mode from model name
    is_keystroke_mode = model.endswith("-keystroke")

    def get_screen_text() -> str:
        """Get screen text for keystroke mode, empty string otherwise."""
        return ""

    if backend_name == "mock":
        mock_env = MockEnvironment()
        mock_env.reset(seed=123)
        executor = Executor(mock_env=mock_env)

        def pause_env() -> None:
            return None

        def observe() -> Dict[str, Any]:
            return mock_env.observe()

        def apply_action(action_dict: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
            return executor.apply(action_dict, backend="mock", state=state)

        def advance_env() -> Dict[str, Any]:
            nonlocal tick_info_state
            result = mock_env.advance(ticks)
            tick_info_state = {"ok": True, "ticks_advanced": ticks}
            return result

    elif backend_name == "dfhack":
        if not settings.DFHACK_ENABLED:
            raise RuntimeError("DFHack backend disabled. Set DFHACK_ENABLED=1 to use it.")

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

        def advance_env() -> Dict[str, Any]:
            nonlocal tick_info_state
            state = dfhack_client.advance(ticks)
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

                # Get screen text for keystroke mode
                screen_text = get_screen_text() if is_keystroke_mode else None
                obs_text, obs_json = encode_observation(state_before, screen_text=screen_text)
                publish_event(step, "state", {"state": obs_json, "text": obs_text}, events)

                raw_action = agent.decide(obs_text, obs_json)
                publish_event(step, "action", {"raw": raw_action}, events)

                if not isinstance(raw_action, dict):
                    raise TypeError("Agent must return a dictionary action")

                if isinstance(raw_action, list) or any(k in raw_action for k in ("actions", "plan")):
                    reason = "Multiple actions are not supported"
                    validation = {"valid": False, "reason": reason}
                    publish_event(step, "validation", validation, events)
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
                publish_event(step, "execute", {"result": execute_result}, events)
                state_after_apply = execute_result.get("state") or state_before

                try:
                    advance_state = call_with_retry("advance", advance_env)
                except DFHackError:
                    if registry:
                        registry.set_status(
                            run_identifier,
                            status="failed",
                            ended_at=datetime.utcnow(),
                        )
                    break
                pause_env()
                publish_event(
                    step,
                    "advance",
                    {"state": advance_state, "tick_advance": tick_info_state},
                    events,
                )

                metrics_snapshot = metrics.step_snapshot(advance_state)
                publish_event(step, "metrics", {"metrics": metrics_snapshot}, events)

                score_value = scoring.composite_score(metrics_snapshot)
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
            dfhack_client.close()

    return run_identifier


__all__ = ["run_once"]
