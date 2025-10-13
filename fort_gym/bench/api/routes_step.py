"""Interactive DFHack step endpoint and throttling helpers."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..env.actions import parse_action, validate_action
from ..env.dfhack_client import DFHackClient
from ..env.encoder import encode_observation
from ..env.executor import Executor
from ..env.state_reader import StateReader
from ..eval import metrics, milestones, scoring
from ..run.storage import RUN_REGISTRY, RunInfo
from .schemas import StepRequest, StepResponse


router = APIRouter()

DEFAULT_MIN_PERIOD_MS = 1000
MIN_ALLOWED_PERIOD_MS = 100
DEFAULT_MAX_TICKS = 500
MAX_TICKS_CAP = 1000


@dataclass
class StepContext:
    run_id: str
    backend: str
    model: str
    trace_path: Path
    summary_path: Path
    max_steps: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    inflight: bool = False
    completed: bool = False
    last_step_ts_ms: Optional[int] = None
    last_elapsed_ms: Optional[int] = None
    step_idx: int = 0
    reward_cum: float = 0.0
    last_score: float = 0.0
    previous_state: Optional[Dict[str, Any]] = None


_CONTEXT_LOCK = threading.Lock()
_STEP_CONTEXTS: Dict[str, StepContext] = {}


def _artifacts_root(run_id: str) -> Path:
    settings = get_settings()
    root = Path(settings.ARTIFACTS_DIR).resolve()
    path = root / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_context(run: RunInfo) -> StepContext:
    with _CONTEXT_LOCK:
        ctx = _STEP_CONTEXTS.get(run.run_id)
        if ctx is None:
            artifact_dir = _artifacts_root(run.run_id)
            ctx = StepContext(
                run_id=run.run_id,
                backend=run.backend,
                model=run.model,
                trace_path=artifact_dir / "trace.jsonl",
                summary_path=artifact_dir / "summary.json",
                max_steps=run.max_steps,
                step_idx=run.step,
            )
            _STEP_CONTEXTS[run.run_id] = ctx
        return ctx


def _write_summary(context: StepContext) -> Dict[str, Any]:
    summary_payload = {
        "run_id": context.run_id,
        "backend": context.backend,
        "model": context.model,
        "steps": context.step_idx,
        "reward_cum": context.reward_cum,
        "total_score": context.reward_cum,
        "last_step_at": datetime.utcnow().isoformat() + "Z",
    }
    context.summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    RUN_REGISTRY.set_summary(context.run_id, summary_payload)
    return summary_payload


def _emit_event(run_id: str, events: list[Dict[str, Any]], event_type: str, data: Dict[str, Any]) -> None:
    payload = {"type": event_type, "data": data}
    events.append(payload)
    RUN_REGISTRY.append_event(run_id, {"t": event_type, "data": data})


@router.post("/step", response_model=StepResponse)
async def step_endpoint(payload: StepRequest) -> StepResponse:
    settings = get_settings()
    if not settings.DFHACK_ENABLED:
        raise HTTPException(status_code=400, detail="DFHack backend is disabled.")

    run = RUN_REGISTRY.get(payload.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run.backend != "dfhack":
        raise HTTPException(status_code=400, detail="Interactive steps require DFHack backend.")

    context = _get_context(run)
    now_ms = int(time.time() * 1000)

    min_period_ms = payload.min_step_period_ms if payload.min_step_period_ms is not None else DEFAULT_MIN_PERIOD_MS
    min_period_ms = max(MIN_ALLOWED_PERIOD_MS, int(min_period_ms))

    with context.lock:
        if context.completed or (context.max_steps and context.step_idx >= context.max_steps):
            context.completed = True
            raise HTTPException(status_code=400, detail="Run has already completed.")
        if context.inflight:
            raise HTTPException(status_code=429, detail="Step already in progress.")
        if context.last_step_ts_ms is not None and now_ms - context.last_step_ts_ms < min_period_ms:
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")
        context.inflight = True
        previous_ts = context.last_step_ts_ms

    max_ticks = payload.max_ticks if payload.max_ticks is not None else DEFAULT_MAX_TICKS
    max_ticks = max(1, min(MAX_TICKS_CAP, int(max_ticks)))

    raw_action = payload.action or {}
    if not isinstance(raw_action, dict):
        raise HTTPException(status_code=400, detail="Action must be a JSON object.")

    dfhack_client = DFHackClient(host=settings.DFHACK_HOST, port=settings.DFHACK_PORT)
    executor = Executor(dfhack_client=dfhack_client)
    events: list[Dict[str, Any]] = []

    try:
        dfhack_client.connect()
        dfhack_client.pause()

        state_before = StateReader.from_dfhack(dfhack_client)
        obs_text, obs_json = encode_observation(state_before)
        _emit_event(run.run_id, events, "state", {"state": obs_json, "text": obs_text})

        _emit_event(run.run_id, events, "action", {"raw": raw_action})

        action = raw_action
        validation: Dict[str, Any]
        validation = {"valid": True, "reason": None}

        is_noop = raw_action.get("type", "").lower() == "noop"
        if not is_noop:
            try:
                action = parse_action(raw_action)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid action: {exc}") from exc

            valid, reason = validate_action(obs_json, action)
            validation = {"valid": valid, "reason": reason}
            if not valid:
                raise HTTPException(status_code=400, detail=reason or "Action validation failed.")
        _emit_event(run.run_id, events, "validation", validation)

        if is_noop:
            execute_result = {"accepted": True, "why": "noop"}
            state_after_apply = state_before
        else:
            execute_result = executor.apply(action, backend="dfhack", state=obs_json)
            error_message = None
            if not execute_result.get("accepted"):
                error_message = execute_result.get("why")
                result_payload = execute_result.get("result") or {}
                error_message = error_message or result_payload.get("error")
                if error_message:
                    _emit_event(run.run_id, events, "stderr", {"message": error_message})
                state_after_apply = state_before
            else:
                state_after_apply = execute_result.get("state") or state_before
        _emit_event(run.run_id, events, "execute", {"result": execute_result})

        advance_state = dfhack_client.advance(max_ticks)
        dfhack_client.pause()
        _emit_event(run.run_id, events, "advance", {"state": advance_state})

        metrics_snapshot = metrics.step_snapshot(advance_state)
        _emit_event(run.run_id, events, "metrics", {"metrics": metrics_snapshot})

        score_value = scoring.composite_score(metrics_snapshot)
        milestone_notes = milestones.detect(context.previous_state, advance_state)
        _emit_event(
            run.run_id,
            events,
            "score",
            {
                "value": score_value,
                "milestones": milestone_notes,
            },
        )

        end_ms = int(time.time() * 1000)
        elapsed_ms = end_ms - (previous_ts if previous_ts is not None else now_ms)
        elapsed_ms = max(1, elapsed_ms)

        with context.lock:
            step_index = context.step_idx
            context.step_idx += 1
            context.previous_state = advance_state
            reward_delta = score_value - context.last_score
            context.last_score = score_value
            context.reward_cum += reward_delta
            context.last_step_ts_ms = end_ms
            context.last_elapsed_ms = elapsed_ms
            context.inflight = False
            done = False
            if context.max_steps and context.step_idx >= context.max_steps:
                context.completed = True
                done = True

        pace_target_hz = round(1000.0 / min_period_ms, 3)
        now_hz = round(1000.0 / elapsed_ms, 3)
        step_event = {
            "run_id": run.run_id,
            "step_idx": step_index,
            "reward_delta": reward_delta,
            "reward_cum": context.reward_cum,
            "pace_target_hz": pace_target_hz,
            "now_hz": now_hz,
            "ts": end_ms,
            "last_obs": metrics_snapshot,
        }
        _emit_event(run.run_id, events, "step", step_event)

        record = {
            "run_id": run.run_id,
            "step": step_index,
            "observation": obs_json,
            "observation_text": obs_text,
            "action": action,
            "raw_action": raw_action,
            "validation": validation,
            "execute": execute_result,
            "state_after_apply": state_after_apply,
            "state_after_advance": advance_state,
            "metrics": metrics_snapshot,
            "score": score_value,
            "reward": {"delta": reward_delta, "cumulative": context.reward_cum},
            "events": events,
        }
        context.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with context.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

        summary_payload = _write_summary(context)

        now_dt = datetime.utcnow()
        if context.step_idx == 1 and not run.started_at:
            RUN_REGISTRY.set_status(run.run_id, status="running", step=step_index, started_at=now_dt)
        elif context.completed:
            RUN_REGISTRY.set_status(
                run.run_id,
                status="completed",
                step=step_index,
                ended_at=now_dt,
            )
        else:
            RUN_REGISTRY.set_status(run.run_id, status="running", step=step_index)

        response = StepResponse(
            observation=advance_state,
            reward=reward_delta,
            done=context.completed,
            info={
                "step_idx": step_index,
                "reward_cum": context.reward_cum,
                "metrics": metrics_snapshot,
                "score": score_value,
                "summary": summary_payload,
            },
        )
        if not execute_result.get("accepted"):
            error_message = execute_result.get("why")
            result_payload = execute_result.get("result") or {}
            error_message = error_message or result_payload.get("error")
            if error_message:
                response.info["error"] = error_message
        return response
    finally:
        with context.lock:
            context.inflight = False
        try:
            dfhack_client.close()
        except Exception:
            pass


def _reset_step_contexts_for_tests() -> None:
    """Utility hook for pytest to clear cached step contexts."""

    with _CONTEXT_LOCK:
        _STEP_CONTEXTS.clear()


__all__ = ["router", "_reset_step_contexts_for_tests"]
