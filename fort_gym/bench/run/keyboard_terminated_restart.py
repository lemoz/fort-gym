"""Rollback an externally terminated worker from original partial evidence.

There is no fabricated final agent, segment result or save-attempt file. The
original journal supplies usage; only the last verified save supplies gameplay.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from ..agent.keyboard_exchange import read
from ..agent.keyboard_prompt import BASE_PROMPT, effective_prompt
from ..agent.campaign_keyboard import validate_usage
from ..eval.campaign import read_campaign_progress
from .campaign_checkpoint import CampaignCheckpointError, verify_checkpoint
from .campaign_save import save_inventory
from .keyboard_restart_prompt import inspect_restart_initial
from .keyboard_unavailable_restart import digest, _input_boundary, validated_restart_history

TERMINATED_KIND = "controller_termination_after_input"


def history_digest(history: list[dict]) -> str:
    return hashlib.sha256(json.dumps(history, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_terminated_discontinuity(row: dict) -> None:
    if (
        row.get("failure_kind") != TERMINATED_KIND
        or row.get("termination_stage") != "worker_interrupted_before_final_receipt"
        or row.get("lost_elapsed_ticks_complete") is not False
        or row.get("lost_uncommitted_ticks", "missing") is not None
        or type(row.get("lost_uncommitted_decisions")) is not int
        or row["lost_uncommitted_decisions"] != 1
        or any(key in row for key in ("save_failure_stage", "source_save_attempt_sha256"))
        or any(
            not isinstance(row.get(key), str) or re.fullmatch("[a-f0-9]{64}", row[key]) is None
            for key in (
                "source_failure_sha256",
                "source_runtime_sha256",
                "source_prompt_state_sha256",
                "source_prior_history_sha256",
            )
        )
        or not isinstance(row.get("retained_prompt_changes"), list)
        or not isinstance(row.get("retained_usage"), dict)
    ):
        raise ValueError(
            "Terminated-worker restart must preserve missing final evidence and unknown time"
        )
    validate_usage(row["retained_usage"])
    effective_prompt(row["retained_prompt_changes"], row["retained_usage"])


def _tail(checkpoint: Path, segment: Path) -> list[dict]:
    path = segment / "loop/trace.jsonl"
    digest(path)
    with path.open("rb") as stream, (checkpoint / "trace.jsonl").open("rb") as parent:
        while block := parent.read(1024 * 1024):
            if stream.read(len(block)) != block:
                raise ValueError("Termination changed the saved trace prefix")
        rows = []
        for line in stream:
            if not line.endswith(b"\n"):
                raise ValueError("Termination has an incomplete committed trace row")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Termination trace row is not an object")
            rows.append(row)
        return rows


def terminated_history(checkpoint: Path, segment: Path) -> list[dict]:
    """Use history actually retained in every committed row, not a synthetic result."""
    tail = _tail(checkpoint, segment)
    saved = read(checkpoint / "runner.json").get("discontinuities", [])
    retained = segment / "history-before.json"
    if tail:
        history = tail[0].get("discontinuities", [])
        if any(row.get("discontinuities", []) != history for row in tail):
            raise ValueError("Termination trace changed its prior loss history")
    elif retained.exists():
        history = read(retained).get("discontinuities")
    elif (segment / "restart.json").exists():
        raise ValueError("Interrupted restart has no complete retained prior loss history")
    else:
        history = saved
    if retained.exists() and read(retained) != {"discontinuities": history}:
        raise ValueError("Termination trace and original prior loss history differ")
    return validated_restart_history(checkpoint, segment, history)


def _runtime(checkpoint: Path, source: Path, index: int, revision: str, payload: dict) -> dict:
    runtime = read(source / f"runtime-{index}/result.json")
    saved = payload["native_save"]
    loaded = runtime.get("loaded", {})
    if (
        runtime.get("schema_version") != "fortgym.isolated-experiment-runtime/v1"
        or runtime.get("code_revision") != revision
        or runtime.get("source_checkpoint_file_sha256") != digest(checkpoint / "checkpoint.json")
        or runtime.get("native_load_verified") is not True
        or runtime.get("cleanup_verified") is not True
        or runtime.get("listener_closed") is not True
        or runtime.get("remaining_live_processes") != []
        or "experiment" in runtime
        or loaded.get("save_name") != saved["save_name"]
        or loaded.get("map_loaded") is not True
        or loaded.get("paused") is not True
        or any(
            type(loaded.get(k)) is not int or loaded[k] != saved[k] for k in ("year", "year_tick")
        )
    ):
        raise ValueError("Termination lacks matching native-load and cleanup evidence")
    path = source / f"runtime-{index}/runtime/data/save" / saved["save_name"]
    if [r for r in save_inventory(path) if r["path"] != "events-dfhack.log"] != [
        r for r in saved["files"] if r["path"] != "events-dfhack.log"
    ]:
        raise ValueError("Newer native save exists; termination cannot discard it")
    return runtime


def _usage(initial: dict, latest: bytes, tail: list[dict], failure: dict, first: int) -> dict:
    from .campaign_loop import reconciled_usage

    usage = reconciled_usage(initial, latest)
    count = len(tail) + 1
    completed = [
        row
        for row in (json.loads(line) for line in latest.splitlines())
        if row.get("type") == "decision_finished"
    ]
    if (
        len(completed) <= count
        or completed[-count - 1].get("usage") != initial["usage"]
        or [r.get("step") for r in completed[-count:]] != list(range(first, first + count))
        or any(
            usage[k] - initial["usage"][k] != count
            for k in ("accounted_responses", "returned_responses", "dispatched_requests")
        )
    ):
        raise ValueError("Termination usage does not cover exactly its returned decisions")
    prior = initial["usage"]
    profile = effective_prompt(initial.get("prompt_changes", []), prior)
    for index, (row, finished) in enumerate(zip([*tail, failure], completed[-count:])):
        events = row.get("events", [])
        decisions = (
            [
                event.get("receipt")
                for event in events
                if event.get("type") == "codex_keyboard_decision"
            ]
            if index == len(tail)
            else [
                event.get("data", {}).get("receipt")
                for event in events
                if event.get("type") == "tool_call"
                and event.get("data", {}).get("type") == "codex_keyboard_decision"
            ]
        )
        if len(decisions) != 1 or not isinstance(decisions[0], dict):
            raise ValueError("Termination requires one model receipt per retained decision")
        decision = decisions[0]
        receipt = decision.get("transport_receipt", {})
        current = finished["usage"]
        if (
            decision.get("action") != row.get("action")
            or decision.get("action_grammar_valid") is not True
            or decision.get("prompt_profile", BASE_PROMPT) != profile
            or receipt.get("accepted") is not True
            or receipt.get("dispatched") is not True
            or receipt.get("model_requested") != initial["configuration"]["model"]
            or receipt.get("reasoning_effort_requested")
            != initial["configuration"]["reasoning_effort"]
            or type(receipt.get("total_tokens")) is not int
            or receipt["total_tokens"] < 0
            or current["total_tokens"] - prior["total_tokens"] != receipt["total_tokens"]
            or finished.get("decision_returned") is not True
            or any(
                current[k] - prior[k] != 1
                for k in ("accounted_responses", "returned_responses", "dispatched_requests")
            )
        ):
            raise ValueError(
                "Termination changed a model receipt, prompt profile or its accounted usage"
            )
        prior = current
    if prior != usage:
        raise ValueError("Termination has an unaccounted final response")
    return usage


def prepare_terminated_restart(
    checkpoint: Path, source: Path, declaration: dict, latest: bytes
) -> dict:
    try:
        return _prepare(checkpoint, source, declaration, latest)
    except (
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        OSError,
        CampaignCheckpointError,
    ) as error:
        raise ValueError("Terminated-worker restart evidence is incomplete or malformed") from error


def _prepare(checkpoint: Path, source: Path, declaration: dict, latest: bytes) -> dict:
    from .campaign_loop import _clock, reconciled_usage
    from .keyboard_restart import SCHEMA, validate_discontinuities

    manifest = verify_checkpoint(checkpoint)
    payload, index = manifest["payload"], declaration["source_segment"]
    segment = source / f"segment-{index}"
    window = read(source / "result.json")
    if (
        window.get("schema_version") != "fortgym.keyboard-window-result/v1"
        or window.get("source_revision") != declaration["source_revision"]
        or window.get("campaign_id") != payload["campaign_id"]
        or window.get("status") != "failed"
        or window.get("original_checkpoint_unchanged") is not True
        or payload["next_step"] != declaration["restored_next_step"]
        or any(
            (segment / name).exists()
            for name in (
                "checkpoint",
                "result.json",
                "agent-after.json",
                "native-after.json",
                "save-attempt.json",
            )
        )
        or latest != (segment / "loop/usage.jsonl").read_bytes()
        or not latest.startswith((checkpoint / "usage.jsonl").read_bytes())
    ):
        raise ValueError("Termination is not the declared incomplete worker result")
    runtime = _runtime(checkpoint, source, index, declaration["source_revision"], payload)
    history = terminated_history(checkpoint, segment)
    change = (
        read(segment / "prompt-change.json") if (segment / "prompt-change.json").exists() else None
    )
    initial = inspect_restart_initial(
        checkpoint, segment, {"prompt_change": change}, history=history
    )
    tail = _tail(checkpoint, segment)
    if [r.get("step") for r in tail] != list(
        range(payload["next_step"], declaration["lost_trace_next_step"])
    ) or any(
        r.get("run_id") != payload["campaign_id"]
        or r.get("execute", {}).get("accepted") is not True
        for r in tail
    ):
        raise ValueError("Termination trace does not match the declared consecutive input tail")
    failure_path = segment / "loop/failures.jsonl"
    raw = failure_path.read_bytes()
    failures = [json.loads(line) for line in raw.splitlines()]
    if not raw.endswith(b"\n") or len(failures) != 1:
        raise ValueError("Termination requires one complete retained failure receipt")
    failure = failures[0]
    if (
        type(failure.get("step")) is not int
        or failure["step"] != declaration["lost_trace_next_step"]
        or failure.get("error_type") != "KeyboardInterrupt"
        or failure.get("message") != "Campaign termination requested"
        or any(k in failure for k in ("tick_receipt", "native_after"))
    ):
        raise ValueError("Termination lacks its original interrupted post-input transaction")
    boundary = _input_boundary(
        failure, runtime, payload["native_save"], initial["configuration"]["max_advance_ticks"]
    )
    saved = payload["native_save"]
    end = (
        tail[-1]["state_after_advance"]
        if tail
        else {
            "year": saved["year"],
            "year_tick": saved["year_tick"],
            "pause_state": True,
        }
    )
    if _clock(boundary) != _clock(end):
        raise ValueError("Termination post-input clock differs from its last committed boundary")
    progress = read_campaign_progress(segment / "loop/trace.jsonl")
    known = _clock(boundary) - (saved["year"] * 403200 + saved["year_tick"])
    if known != sum(r["tick_advance"]["ticks_advanced"] for r in tail) or known < 0:
        raise ValueError("Termination known elapsed time does not reconcile")
    saved_progress = read_campaign_progress(checkpoint / "trace.jsonl")
    if progress["elapsed_ticks"] != saved_progress["elapsed_ticks"] + known:
        raise ValueError("Termination lost previously saved elapsed time")
    usage = _usage(initial, latest, tail, failure, payload["next_step"])
    if reconciled_usage(read(checkpoint / "agent.json"), latest) != usage:
        raise ValueError("Termination discarded checkpoint usage")
    record = {
        "schema_version": SCHEMA,
        "failure_kind": TERMINATED_KIND,
        "termination_stage": "worker_interrupted_before_final_receipt",
        "checkpoint_sha256": manifest["sha256"],
        "source_result_sha256": digest(source / "result.json"),
        "source_trace_sha256": digest(segment / "loop/trace.jsonl"),
        "source_usage_sha256": digest(segment / "loop/usage.jsonl"),
        "source_failure_sha256": digest(failure_path),
        "source_runtime_sha256": digest(source / f"runtime-{index}/result.json"),
        "source_prompt_state_sha256": digest(segment / "agent-before.json"),
        "source_prior_history_sha256": history_digest(history),
        "restored_next_step": payload["next_step"],
        "lost_trace_next_step": declaration["lost_trace_next_step"],
        "lost_elapsed_ticks": known,
        "lost_elapsed_ticks_complete": False,
        "lost_uncommitted_ticks": None,
        "lost_uncommitted_decisions": 1,
        "retained_usage": usage,
        "retained_prompt_changes": deepcopy(initial.get("prompt_changes", [])),
        "memory_policy": "restore_checkpoint_memory",
        "uninterrupted_campaign": False,
        "actions_replayed": False,
    }
    return validate_discontinuities([record])[0]
