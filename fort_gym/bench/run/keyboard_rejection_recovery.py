"""Attest a historical unsupported-key tail; no native input or model calls."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from ..agent.keyboard_exchange import read
from ..agent.keyboard_rejection import KeyboardInputRejected
from ..env.screen_observation import TEXT_PROFILE
from ..eval.campaign import read_campaign_progress
from .campaign_checkpoint import verify_checkpoint
from .campaign_loop import _clock, reconciled_usage
from .campaign_save import save_inventory
from .keyboard_rejection import rejection_record
from .keyboard_rejection_journal import make_record

SCHEMA = "fortgym.keyboard-input-rejection-recovery/v1"


def journal_record(*, segment: Path, exchange: Path) -> dict:
    from .keyboard_recovery_source import _bytes, _rows

    native = read(segment / "native-after.json")
    return make_record(
        journal=_bytes(segment / "loop/usage.jsonl"),
        request=read(exchange / "request.json"),
        response=read(exchange / "response.json"),
        failure=_rows(segment / "loop/failures.jsonl")[0],
        native_boundary={key: native[key] for key in ("year", "year_tick", "pause_state")},
    )


def inspect_input_rejection_source(*, parent: Path, segment: Path, exchange: Path) -> dict:
    from .keyboard_recovery_source import SOURCE_FILES, _bytes, _hash, _rows

    if any(path.is_symlink() or not path.is_dir() for path in (parent, segment, exchange)):
        raise ValueError("Recovery source must be a retained regular directory")
    checkpoint = verify_checkpoint(parent)
    initial, previous, final = (
        read(parent / "agent.json"), read(segment / "agent-before.json"),
        read(segment / "agent-after.json"),
    )
    result = read(segment / "result.json")
    rows = _rows(segment / "loop/trace.jsonl")
    failures = _rows(segment / "loop/failures.jsonl")
    cursor = len(rows)
    first = checkpoint["payload"]["next_step"]
    if (
        initial != previous
        or final.get("schema_version") != "fortgym.codex-keyboard-agent/v1"
        or final.get("configuration") != initial["configuration"]
        or final.get("budget_extensions") != initial.get("budget_extensions")
        or final.get("campaign_id") != checkpoint["payload"]["campaign_id"]
        or result.get("campaign_id", final["campaign_id"]) != final["campaign_id"]
        or result.get("schema_version") != "fortgym.keyboard-segment/v1"
        or result.get("status") != "failed"
        or result.get("stop_reason") != "unsettled_failure"
        or result.get("checkpoint_verified") is not False
        or result.get("recovery_requires_reconciliation") is not True
        or result.get("unreconciled_native_snapshot_retained") is not True
        or type(result.get("first_step")) is not int or result["first_step"] != first
        or type(result.get("next_step")) is not int or result["next_step"] != cursor
        or cursor < first
        or len(failures) != 1
        or any(type(row.get("step")) is not int or row["step"] != i
               or row.get("run_id") != final["campaign_id"]
               or row.get("action", {}).get("type") != "KEYSTROKE"
               for i, row in enumerate(rows))
    ):
        raise ValueError("Recovery source does not identify one unchanged keyboard campaign")
    for name in ("trace.jsonl", "usage.jsonl"):
        if not _bytes(segment / "loop" / name).startswith(_bytes(parent / name)):
            raise ValueError("Recovery source does not preserve the checkpoint prefix")
    memory = initial["memory"]
    for row in rows[first:]:
        if row.get("record_origin") != "model_input_rejection/v1":
            memory = row["action"]["memory_update"]
    request = read(exchange / "request.json")
    if final.get("memory") != memory or request.get("memory") != memory:
        raise ValueError("Rejected response changed memory or omitted committed actions")
    native = read(segment / "native-after.json")
    if (
        _clock(native) != _clock(rows[-1]["state_after_advance"])
        or native.get("viewscreen_type") != "viewscreen_dwarfmodest"
        or native.get("viewscreen_type") != rows[-1]["state_after_advance"].get("viewscreen_type")
    ):
        raise ValueError("Rejected response changed the native calendar or boundary")
    progress = read_campaign_progress(segment / "loop/trace.jsonl")
    if progress["elapsed_ticks"] is None or progress["elapsed_ticks"] != result.get(
        "committed_elapsed_ticks"
    ):
        raise ValueError("Rejected response source has inconsistent committed time")
    journal = _bytes(segment / "loop/usage.jsonl")
    original = _rows(segment / "loop/usage.jsonl")
    finished = [row for row in original if row.get("type") == "decision_finished"]
    if (
        [row.get("step") for row in finished] != list(range(cursor + 1))
        or original[-1] != finished[-1]
        or failures[0].get("step") != cursor
        or finished[-1].get("decision_returned") is not False
        or finished[-1].get("usage") != final["usage"]
        or result.get("usage") != final["usage"]
        or final["usage"]["returned_responses"] != cursor + 1
        or final["usage"]["dispatched_requests"] != cursor + 1
    ):
        raise ValueError("Rejected response does not have one retained final usage entry")
    extra = journal_record(segment=segment, exchange=exchange)
    extended = journal + (json.dumps(extra, allow_nan=False) + "\n").encode()
    if reconciled_usage(final, extended) != final["usage"]:
        raise ValueError("Rejection recovery would change retained usage")
    return {
        "schema_version": SCHEMA,
        "campaign_id": final["campaign_id"],
        "parent_checkpoint_sha256": checkpoint["sha256"],
        "source_files_sha256": {name: _hash(segment / name) for name in SOURCE_FILES},
        "request_sha256": _hash(exchange / "request.json"),
        "response_sha256": _hash(exchange / "response.json"),
        "forensic_save_inventory": save_inventory(segment / "unreconciled-native-save"),
        "failed_step": cursor, "next_step": cursor + 1,
        "year": native["year"], "year_tick": native["year_tick"],
        "usage": deepcopy(final["usage"]),
        "original_input_outcome": "unsupported_native_keys",
        "model_calls_to_recover": 0, "gameplay_keys_to_recover": 0, "replay_allowed": False,
    }


def recovered_row(*, plan: dict, segment: Path, exchange: Path, observed: dict,
                  screen: str) -> dict:
    from .keyboard_recovery_source import _rows

    request = read(exchange / "request.json")
    failure = _rows(segment / "loop/failures.jsonl")[0]
    state = read(segment / "native-after.json")
    rejection = KeyboardInputRejected(
        read(exchange / "response.json")["result"]["transport_receipt"]["response"],
        max_advance_ticks=request["max_advance_ticks"],
    )
    row = rejection_record(
        campaign_id=plan["campaign_id"], step=plan["failed_step"], rejection=rejection,
        before=state, after=state,
        observation={"observation_profile": TEXT_PROFILE, "screen_capture": request["screen"],
                     "last_action_feedback": request["feedback"]},
        text=screen, screen=screen, events=failure["events"],
    )
    row["record_origin"] = "verified_input_rejection_reconciliation/v1"
    row["execute"]["tick_feedback"].update(failure_reconciled=True, runtime_reloaded=True)
    row["reconciliation"] = {
        "plan": plan, "original_failure": failure,
        "loaded_native_boundary": {
            "year": observed["year"], "year_tick": observed["year_tick"], "pause_state": True,
        },
        "original_failure_reclassified_as_success": False,
    }
    return row
