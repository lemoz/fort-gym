"""Read-only validation and fingerprinting of a retained keyboard failure."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from ..agent.keyboard_exchange import digest, read, validate_request
from ..agent.standard_input import parse_response
from ..env.native_key_catalog import NATIVE_PROFILE
from ..env.screen_observation import TEXT_PROFILE, encode_screen
from ..eval.campaign import read_campaign_progress
from .campaign_checkpoint import verify_checkpoint
from .campaign_loop import _clock, reconciled_usage
from .campaign_save import save_inventory
from .keyboard_clock import BLOCKING_FOCUS, NATIVE_VIEW

SCHEMA = "fortgym.keyboard-failure-recovery/v1"
SOURCE_FILES = (
    "result.json",
    "agent-before.json",
    "agent-after.json",
    "native-after.json",
    "loop/trace.jsonl",
    "loop/usage.jsonl",
    "loop/failures.jsonl",
)


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Recovery evidence must be a regular file")
    return path.read_bytes()


def _hash(path: Path) -> str:
    return hashlib.sha256(_bytes(path)).hexdigest()


def _rows(path: Path) -> list[dict]:
    raw = _bytes(path)
    if not raw.endswith(b"\n"):
        raise ValueError("Recovery evidence has an incomplete journal")
    result = [json.loads(line) for line in raw.splitlines()]
    if not result or any(not isinstance(row, dict) for row in result):
        raise ValueError("Recovery journal lacks complete records")
    return result


def inspect_recovery_source(*, parent: Path, segment: Path, exchange: Path) -> dict:
    """Validate and fingerprint a narrow recoverable case, without any writes."""
    if segment.is_symlink() or not segment.is_dir() or exchange.is_symlink():
        raise ValueError("Recovery source must be a retained regular directory")
    failures = _rows(segment / "loop/failures.jsonl")
    if len(failures) == 1 and failures[0].get("error_type") == "CodexTransportError":
        from .keyboard_rejection_recovery import inspect_input_rejection_source

        return inspect_input_rejection_source(parent=parent, segment=segment, exchange=exchange)
    checkpoint = verify_checkpoint(parent)
    initial, previous, final = (
        read(parent / "agent.json"),
        read(segment / "agent-before.json"),
        read(segment / "agent-after.json"),
    )
    result = read(segment / "result.json")
    rows, failures = (
        _rows(segment / "loop/trace.jsonl"),
        _rows(segment / "loop/failures.jsonl"),
    )
    cursor = len(rows)
    if (
        initial != previous
        or final.get("schema_version") != "fortgym.codex-keyboard-agent/v1"
        or final["configuration"] != initial["configuration"]
        or final.get("budget_extensions") != initial.get("budget_extensions")
        or final["campaign_id"] != checkpoint["payload"]["campaign_id"]
        or result.get("schema_version") != "fortgym.keyboard-segment/v1"
        or result.get("status") != "failed"
        or result.get("stop_reason") != "unsettled_failure"
        or result.get("checkpoint_verified") is not False
        or result.get("recovery_requires_reconciliation") is not True
        or result.get("unreconciled_native_snapshot_retained") is not True
        or result.get("first_step") != checkpoint["payload"]["next_step"]
        or type(result.get("first_step")) is not int
        or type(result.get("next_step")) is not int
        or result["next_step"] != cursor
        or len(failures) != 1
        or any(
            type(row.get("step")) is not int or row["step"] != i
            for i, row in enumerate(rows)
        )
        or any(row.get("run_id") != final["campaign_id"] for row in rows)
        or any(row.get("action", {}).get("type") != "KEYSTROKE" for row in rows)
    ):
        raise ValueError(
            "Recovery source does not identify one unchanged keyboard campaign"
        )
    for name in ("trace.jsonl", "usage.jsonl"):
        if not _bytes(segment / "loop" / name).startswith(_bytes(parent / name)):
            raise ValueError("Recovery source does not preserve the checkpoint prefix")
    progress = read_campaign_progress(segment / "loop/trace.jsonl")
    if progress["elapsed_ticks"] is None or progress["elapsed_ticks"] != result.get(
        "committed_elapsed_ticks"
    ):
        raise ValueError("Recovery source has inconsistent committed game time")
    usage = final["usage"]
    if (
        reconciled_usage(final, _bytes(segment / "loop/usage.jsonl")) != usage
        or result.get("usage") != usage
        or usage["dispatched_requests"] != usage["returned_responses"]
        or usage["returned_responses"] != cursor + 1
    ):
        raise ValueError("Recovery source usage is not fully accounted")
    failure = failures[0]
    action = parse_response(
        failure["action"],
        max_advance_ticks=final["configuration"]["max_advance_ticks"],
        control_profile=NATIVE_PROFILE,
    )
    request, response = (
        read(exchange / "request.json"),
        read(exchange / "response.json"),
    )
    validate_request(request)
    decision = response.get("result")
    if (
        response.get("request_sha256") != digest(request)
        or not isinstance(decision, dict)
        or failure.get("events")
        != [{"type": "codex_keyboard_decision", "receipt": decision}]
        or decision.get("action") != action
        or decision.get("screen_sha256")
        != digest(encode_screen(request["screen"], TEXT_PROFILE))
        or request["control_profile"] != final["configuration"]["control_profile"]
        or request["observation_profile"]
        != final["configuration"]["observation_profile"]
        or request["max_advance_ticks"] != final["configuration"]["max_advance_ticks"]
        or request["memory"] != rows[-1]["action"]["memory_update"]
        or final["memory"] != action["memory_update"]
        or decision.get("action_grammar_valid") is not True
    ):
        raise ValueError(
            "Recovery decision is not bound to the original model input and memory"
        )
    journal = _rows(segment / "loop/usage.jsonl")
    finished = [row for row in journal if row["type"] == "decision_finished"]
    if (
        [row["step"] for row in finished] != list(range(cursor + 1))
        or finished[-1].get("decision_returned") is not True
        or finished[-1]["usage"] != usage
        or usage["total_tokens"] - finished[-2]["usage"]["total_tokens"]
        != decision["transport_receipt"].get("total_tokens")
        or decision["transport_receipt"].get("accepted") is not True
        or decision["transport_receipt"].get("dispatched") is not True
    ):
        raise ValueError("Failed decision usage differs from its retained response")
    tick = failure["tick_receipt"]
    native = read(segment / "native-after.json")
    clock = _clock(native)
    before, after = failure.get("native_before"), failure.get("native_after")
    if (
        failure.get("step") != cursor
        or failure.get("error_type") != "ValueError"
        or failure.get("message")
        != "Native tick operation did not finish or interrupt cleanly"
        or failure.get("requested_ticks") != action["advance_ticks"]
        or tick.get("final_viewscreen_type") != "viewscreen_dwarfmodest"
        or native.get("viewscreen_type") != "viewscreen_dwarfmodest"
        or before != after
        or not isinstance(before, dict)
        or _clock(before) != clock
        or _clock(rows[-1]["state_after_advance"]) != clock
        or tick.get("ok") is not False
        or tick.get("timeout") is not True
        or tick.get("error") != "timeout_waiting_for_ticks"
        or type(tick.get("ticks_advanced")) is not int
        or tick["ticks_advanced"] != 0
        or type(tick.get("requested")) is not int
        or not 0 < tick["requested"] == action["advance_ticks"]
        or (tick.get("start_year"), tick.get("start_tick"))
        != (native["year"], native["year_tick"])
        or (tick.get("end_year"), tick.get("end_tick"))
        != (native["year"], native["year_tick"])
        or any(
            tick.get(k) is not True
            for k in (
                "paused_before",
                "paused_after",
                "repause_requested",
                "repause_effective",
                "final_pause_state",
            )
        )
        or any(
            tick.get(k) is not False
            for k in ("interrupt_safety_error", "calendar_safety_error")
        )
        or any(
            tick.get(k) is not None
            for k in ("resume_error", "repause_error", "nopause_enable_error")
        )
    ):
        raise ValueError("Only an attested zero-tick timeout is recoverable")
    repause = tick.get("repause", {})
    attempts = repause.get("attempt_records", [])
    if (
        repause.get("ok") is not True
        or repause.get("paused") is not True
        or not attempts
        or type(repause.get("attempts")) is not int
        or repause["attempts"] != len(attempts)
        or any(
            row.get("attempt") != i + 1
            or row.get("nopause_disabled") is not True
            or row.get("paused") is not True
            for i, row in enumerate(attempts)
        )
    ):
        raise ValueError("Failed clock lacks verified repause evidence")
    execution = failure["execute"]
    keys, sent = action["params"]["keys"], execution.get("result", {})
    receipts = sent.get("native_receipts", [])
    if (
        execution.get("accepted") is not True
        or sent.get("ok") is not True
        or sent.get("command_mutation") != "completed"
        or type(sent.get("keys_confirmed")) is not int
        or sent["keys_confirmed"] != len(keys)
        or type(sent.get("keys_sent")) is not int
        or sent["keys_sent"] != len(keys)
        or len(receipts) != len(keys) + 1
    ):
        raise ValueError(
            "Recovery requires complete keyboard delivery, never partial input"
        )
    first = receipts[0]["before"]
    if any(
        not isinstance(first.get(key), str) or not first[key]
        for key in ("dfroot", "save_name")
    ):
        raise ValueError("Recovery keyboard receipt lacks native runtime identity")
    for i, receipt in enumerate(receipts):
        if (
            receipt.get("schema_version") != "fortgym.campaign-keyboard-native/v1"
            or receipt.get("ok") is not True
            or receipt.get("mode") != ("key" if i else "probe")
            or receipt.get("command_mutation")
            != ("completed" if i else "not_attempted")
            or type(receipt.get("keys_sent")) is not int
            or receipt["keys_sent"] != int(i > 0)
            or (i > 0 and receipt.get("key") != keys[i - 1])
        ):
            raise ValueError("Recovery native key sequence is not fully attested")
        for sample in (receipt["before"], receipt["after"]):
            if (
                sample.get("paused") is not True
                or sample.get("dfroot") != first.get("dfroot")
                or sample.get("save_name") != first.get("save_name")
                or type(sample.get("year")) is not int
                or type(sample.get("year_tick")) is not int
                or (sample["year"], sample["year_tick"])
                != (native["year"], native["year_tick"])
            ):
                raise ValueError(
                    "Native keyboard boundary differs from the retained save"
                )
    if (
        receipts[-1]["after"].get("focus") != BLOCKING_FOCUS
        or receipts[-1]["after"].get("viewscreen_type") != NATIVE_VIEW
    ):
        raise ValueError("Recovery is limited to the observed build-menu clock failure")
    return {
        "schema_version": SCHEMA,
        "campaign_id": final["campaign_id"],
        "parent_checkpoint_sha256": checkpoint["sha256"],
        "source_files_sha256": {name: _hash(segment / name) for name in SOURCE_FILES},
        "request_sha256": _hash(exchange / "request.json"),
        "response_sha256": _hash(exchange / "response.json"),
        "forensic_save_inventory": save_inventory(segment / "unreconciled-native-save"),
        "failed_step": cursor,
        "next_step": cursor + 1,
        "year": native["year"],
        "year_tick": native["year_tick"],
        "usage": deepcopy(usage),
        "original_clock_outcome": "timeout_waiting_for_ticks",
        "model_calls_to_recover": 0,
        "gameplay_keys_to_recover": 0,
        "replay_allowed": False,
    }
