"""Explicit rollback when native UI disappears after fully recorded input.

No final time is invented. The retained checkpoint supplies game state; the
failed attempt supplies all model usage and the latest existing loss history.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from ..agent.keyboard_exchange import read
from ..agent.standard_input import parse_response
from ..env.native_key_catalog import NATIVE_PROFILE
from ..eval.campaign import read_campaign_progress
from .campaign_checkpoint import CampaignCheckpointError, verify_checkpoint
from .campaign_save import save_inventory

UNAVAILABLE_KIND = "runtime_unavailable_after_input"
UNAVAILABLE_STAGE = "runtime_unavailable_before_save_identity"


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Restart evidence must be a regular file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_unavailable_discontinuity(row: dict) -> None:
    if (
        row.get("failure_kind") != UNAVAILABLE_KIND
        or row.get("save_failure_stage") != UNAVAILABLE_STAGE
        or row.get("lost_elapsed_ticks_complete") is not False
        or "lost_uncommitted_ticks" not in row
        or row["lost_uncommitted_ticks"] is not None
        or type(row.get("lost_uncommitted_decisions")) is not int
        or row["lost_uncommitted_decisions"] != 1
        or any(
            not isinstance(row.get(key), str) or re.fullmatch("[a-f0-9]{64}", row[key]) is None
            for key in (
                "source_failure_sha256",
                "source_runtime_sha256",
                "source_start_agent_sha256",
            )
        )
    ):
        raise ValueError("Unavailable-runtime restart must preserve its unknown terminal clock")


def restart_history(checkpoint: Path, segment: Path, record: dict) -> list[dict]:
    """Carry additional, already-recorded losses without recursively nesting them."""
    from .keyboard_restart import validate_discontinuities

    result = read(segment / "result.json")
    if digest(segment / "result.json") != record["source_result_sha256"]:
        raise ValueError("Restart history source differs from the prepared failure")
    saved = validate_discontinuities(read(checkpoint / "runner.json").get("discontinuities", []))
    history = validate_discontinuities(result.get("discontinuities", []))
    if history[: len(saved)] != saved:
        raise ValueError("Restart cannot erase or change checkpoint loss history")
    if len(history) > len(saved):
        started = read(segment / "restart.json")
        manifest = verify_checkpoint(checkpoint)
        if (
            started != history[-1]
            or started["checkpoint_sha256"] != manifest["sha256"]
            or started["restored_next_step"] != manifest["payload"]["next_step"]
            or started["retained_usage"] != read(segment / "agent-before.json")["usage"]
        ):
            raise ValueError("Additional losses lack their original restart and usage boundary")
    return deepcopy(history)


def _input_boundary(failure: dict, runtime: dict, saved: dict, max_advance_ticks: int) -> dict:
    from .campaign_loop import _clock

    boundary = failure.get("native_after_apply")
    if not isinstance(boundary, dict):
        raise ValueError("Unavailable runtime lacks a paused post-input boundary")
    _clock(boundary)
    action = parse_response(
        failure.get("action"), control_profile=NATIVE_PROFILE, max_advance_ticks=max_advance_ticks
    )
    events = failure.get("events")
    if not isinstance(events, list) or len(events) != 1:
        raise ValueError("Unavailable runtime lacks its accounted model event")
    decision = events[0].get("receipt", {})
    if events[0].get("type") != "codex_keyboard_decision" or decision.get("action") != action:
        raise ValueError("Unavailable runtime model event differs from its action")
    if (
        decision.get("action_grammar_valid") is not True
        or decision.get("native_action_dispatched") is not False
    ):
        raise ValueError("Unavailable runtime lacks a valid model-only decision receipt")
    execution = failure.get("execute", {})
    result = execution.get("result", {})
    keys = action["params"]["keys"]
    receipts = result.get("native_receipts")
    if (
        execution.get("accepted") is not True
        or result.get("schema_version") != "fortgym.campaign-keyboard-execution/v1"
        or result.get("ok") is not True
        or result.get("command_mutation") != "completed"
        or result.get("control_profile") != NATIVE_PROFILE
        or not keys
        or any(
            type(result.get(k)) is not int or result[k] != len(keys)
            for k in ("keys_sent", "keys_confirmed")
        )
        or not isinstance(receipts, list)
        or len(receipts) != len(keys) + 1
    ):
        raise ValueError("Unavailable runtime lacks complete native key receipts")
    for index, item in enumerate(receipts):
        if (
            item.get("schema_version") != "fortgym.campaign-keyboard-native/v1"
            or item.get("ok") is not True
            or item.get("mode") != ("key" if index else "probe")
            or type(item.get("keys_sent")) is not int
            or item["keys_sent"] != int(index > 0)
            or item.get("command_mutation") != ("completed" if index else "not_attempted")
            or (index and item.get("key") != keys[index - 1])
        ):
            raise ValueError("Unavailable runtime native input receipt is incomplete")
        for native in (item.get("before"), item.get("after")):
            if not isinstance(native, dict) or (
                native.get("dfroot") != runtime["loaded"]["dfroot"]
                or native.get("save_name") != saved["save_name"]
                or native.get("paused") is not True
                or any(
                    type(native.get(k)) is not int or native[k] != boundary[k]
                    for k in ("year", "year_tick")
                )
            ):
                raise ValueError("Unavailable runtime input crossed its paused calendar")
    if receipts[-1]["after"]["viewscreen_type"] != f"<type: {boundary['viewscreen_type']}>":
        raise ValueError("Unavailable runtime post-input screen differs from its native receipt")
    return boundary


def prepare_unavailable_restart(
    checkpoint: Path, source_root: Path, declaration: dict, latest: bytes
) -> dict:
    """Validate known loss, unknown remainder, unchanged save, and fully retained usage."""
    try:
        return _prepare_unavailable_restart(checkpoint, source_root, declaration, latest)
    except (
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        OSError,
        CampaignCheckpointError,
    ) as error:
        raise ValueError(
            "Unavailable-runtime restart evidence is incomplete or malformed"
        ) from error


def _prepare_unavailable_restart(
    checkpoint: Path, source_root: Path, declaration: dict, latest: bytes
) -> dict:
    from .campaign_loop import _clock, reconciled_usage
    from .keyboard_restart import SCHEMA, validate_discontinuities

    segment = source_root / f"segment-{declaration['source_segment']}"
    runtime = read(source_root / f"runtime-{declaration['source_segment']}/result.json")
    manifest = verify_checkpoint(checkpoint)
    payload, saved = manifest["payload"], manifest["payload"]["native_save"]
    original, before, returned = (
        read(path)
        for path in (
            checkpoint / "agent.json",
            segment / "agent-before.json",
            segment / "agent-after.json",
        )
    )
    result = read(segment / "result.json")
    if (
        result.get("schema_version") != "fortgym.keyboard-segment/v1"
        or result.get("campaign_id") != payload["campaign_id"]
        or result.get("source_revision") != declaration["source_revision"]
        or result.get("first_step") != payload["next_step"]
        or result.get("first_step") != declaration["restored_next_step"]
        or result.get("next_step") != declaration["lost_trace_next_step"]
        or result.get("status") != "checkpoint_failed"
        or result.get("checkpoint_verified") is not False
        or result.get("recovery_requires_reconciliation") is not True
        or result.get("stop_reason") != "unsettled_failure"
        or result.get("error_type") != "RuntimeError"
        or result.get("error") != "Keyboard clock preflight could not attest native UI"
        or result.get("checkpoint_error_type") != "JSONDecodeError"
        or result.get("final_observation_error_type") != "JSONDecodeError"
        or (segment / "checkpoint").exists()
        or (segment / "native-after.json").exists()
        or read(segment / "save-attempt.json")
        != {"schema_version": "fortgym.native-menu-save-attempt/v1"}
    ):
        raise ValueError("Restart source is not the declared unavailable native runtime")
    if (
        runtime.get("schema_version") != "fortgym.isolated-experiment-runtime/v1"
        or runtime.get("code_revision") != declaration["source_revision"]
        or runtime.get("experiment") != result
        or runtime.get("source_checkpoint_file_sha256") != digest(checkpoint / "checkpoint.json")
        or runtime.get("native_load_verified") is not True
        or runtime.get("cleanup_verified") is not True
        or runtime.get("listener_closed") is not True
        or runtime.get("remaining_live_processes") != []
        or runtime.get("loaded", {}).get("save_name") != saved["save_name"]
        or runtime.get("loaded", {}).get("map_loaded") is not True
        or runtime.get("loaded", {}).get("paused") is not True
        or any(
            type(runtime.get("loaded", {}).get(k)) is not int or runtime["loaded"][k] != saved[k]
            for k in ("year", "year_tick")
        )
    ):
        raise ValueError("Unavailable runtime lacks source-load and cleanup evidence")
    latest_path = segment / "loop/usage.jsonl"
    if (
        latest != latest_path.read_bytes()
        or not latest.startswith((checkpoint / "usage.jsonl").read_bytes())
        or reconciled_usage(original, latest) != returned.get("usage")
        or reconciled_usage(before, latest) != returned.get("usage")
        or returned.get("usage") != result.get("usage")
        or any(state.get("campaign_id") != payload["campaign_id"] for state in (before, returned))
        or any(
            before.get(k) != original.get(k)
            for k in ("memory", "configuration", "budget_extensions")
        )
        or any(returned.get(k) != original.get(k) for k in ("configuration", "budget_extensions"))
        or any(
            returned["usage"][k] - before["usage"][k]
            != result["next_step"] - result["first_step"] + 1
            for k in ("accounted_responses", "returned_responses", "dispatched_requests")
        )
    ):
        raise ValueError(
            "Unavailable-runtime restart must retain all earlier usage and saved memory"
        )
    trace = segment / "loop/trace.jsonl"
    with trace.open("rb") as current, (checkpoint / "trace.jsonl").open("rb") as parent:
        while block := parent.read(1024 * 1024):
            if current.read(len(block)) != block:
                raise ValueError("Unavailable runtime changed its checkpoint trace prefix")
        tail = []
        for line in current:
            if not line.endswith(b"\n"):
                raise ValueError("Unavailable runtime has an incomplete committed trace tail")
            tail.append(json.loads(line))
    if [row.get("step") for row in tail] != list(range(result["first_step"], result["next_step"])):
        raise ValueError("Unavailable runtime lacks its consecutive committed tail")
    progress = read_campaign_progress(trace)
    if progress["elapsed_ticks"] != result["committed_elapsed_ticks"]:
        raise ValueError("Unavailable runtime committed time does not reconcile")
    failure_bytes = (segment / "loop/failures.jsonl").read_bytes()
    if not failure_bytes.endswith(b"\n"):
        raise ValueError("Unavailable runtime failure receipt is incomplete")
    failures = [json.loads(line) for line in failure_bytes.splitlines()]
    if len(failures) != 1 or (
        failures[0].get("step") != result["next_step"]
        or failures[0].get("message") != result["error"]
        or any(key in failures[0] for key in ("tick_receipt", "native_after"))
    ):
        raise ValueError("Unavailable runtime lacks one unresolved input transaction")
    boundary = _input_boundary(
        failures[0], runtime, saved, original["configuration"]["max_advance_ticks"]
    )
    decision = failures[0]["events"][0]["receipt"]
    receipt = decision["transport_receipt"]
    completed = [
        row
        for row in (json.loads(line) for line in latest.splitlines())
        if row.get("type") == "decision_finished"
    ]
    count = result["next_step"] - result["first_step"] + 1
    if (
        len(completed) <= count
        or [row.get("step") for row in completed[-count:]]
        != list(range(result["first_step"], result["next_step"] + 1))
        or completed[-count - 1].get("usage") != before["usage"]
        or completed[-1].get("decision_returned") is not True
        or completed[-1].get("usage") != returned["usage"]
        or returned.get("memory") != decision["action"]["memory_update"]
        or receipt.get("accepted") is not True
        or receipt.get("dispatched") is not True
        or receipt.get("model_requested") != original["configuration"]["model"]
        or receipt.get("reasoning_effort_requested")
        != original["configuration"]["reasoning_effort"]
        or returned["usage"]["total_tokens"] - completed[-2]["usage"]["total_tokens"]
        != receipt.get("total_tokens")
    ):
        raise ValueError("Unavailable runtime discarded or changed its final response usage")
    end = (
        tail[-1]["state_after_advance"]
        if tail
        else {"year": saved["year"], "year_tick": saved["year_tick"], "pause_state": True}
    )
    if _clock(boundary) != _clock(end):
        raise ValueError("Last attested input differs from the committed paused clock")
    native = (
        source_root
        / f"runtime-{declaration['source_segment']}/runtime/data/save"
        / saved["save_name"]
    )
    if [row for row in save_inventory(native) if row["path"] != "events-dfhack.log"] != [
        row for row in saved["files"] if row["path"] != "events-dfhack.log"
    ]:
        raise ValueError("Newer native save exists; do not discard it as an unknown tail")
    record = {
        "schema_version": SCHEMA,
        "failure_kind": UNAVAILABLE_KIND,
        "save_failure_stage": UNAVAILABLE_STAGE,
        "checkpoint_sha256": manifest["sha256"],
        "source_result_sha256": digest(segment / "result.json"),
        "source_trace_sha256": digest(trace),
        "source_usage_sha256": digest(latest_path),
        "source_failure_sha256": digest(segment / "loop/failures.jsonl"),
        "source_runtime_sha256": digest(
            source_root / f"runtime-{declaration['source_segment']}/result.json"
        ),
        "source_save_attempt_sha256": digest(segment / "save-attempt.json"),
        "source_start_agent_sha256": digest(segment / "agent-before.json"),
        "restored_next_step": result["first_step"],
        "lost_trace_next_step": result["next_step"],
        "lost_elapsed_ticks": _clock(boundary) - (saved["year"] * 403200 + saved["year_tick"]),
        "lost_elapsed_ticks_complete": False,
        "lost_uncommitted_ticks": None,
        "lost_uncommitted_decisions": 1,
        "retained_usage": returned["usage"],
        "memory_policy": "restore_checkpoint_memory",
        "actions_replayed": False,
        "uninterrupted_campaign": False,
    }
    history = restart_history(checkpoint, segment, record)
    if any(
        row.get("discontinuities", []) != history or row.get("run_id") != payload["run_id"]
        for row in tail
    ):
        raise ValueError("Unavailable runtime trace dropped prior loss history or identity")
    if not history and before["usage"] != original["usage"]:
        raise ValueError("Additional usage has no preserved restart history")
    return validate_discontinuities([record])[0]
