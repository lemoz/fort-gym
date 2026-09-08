"""Append-only reconciliation of a historically fatal, fully received rejection."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from ..agent.keyboard_exchange import digest, request_selection, validate_request
from ..agent.keyboard_rejection import rejected_receipt
from ..env.native_key_catalog import NATIVE_PROFILE
from ..env.screen_observation import TEXT_PROFILE, encode_screen

RECORD = "keyboard_rejection_reconciled/v1"


def make_record(*, journal: bytes, request: dict, response: dict, failure: dict,
                native_boundary: dict) -> dict:
    """An additional evidence record; original journal bytes are never edited."""
    return {
        "type": RECORD,
        "step": failure["step"],
        "original_journal_sha256": hashlib.sha256(journal).hexdigest(),
        "request": request,
        "response": response,
        "original_failure": failure,
        "native_boundary": native_boundary,
        "native_action_dispatched": False,
        "original_failure_reclassified_as_success": False,
    }


def effective_records(checkpoint: dict, journal: bytes) -> list[dict]:
    """Interpret attested reconciliation without normalizing uncertain failures."""
    from .campaign_loop import _clock

    lines = journal.splitlines(keepends=True)
    records = [json.loads(line) for line in lines]
    effective: list[dict] = []
    prefix = hashlib.sha256()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError("Usage journal record must be an object")
        if record.get("type") != RECORD:
            effective.append(record)
            prefix.update(lines[index])
            continue
        previous = effective[-1] if effective else {}
        failure, request, response = (
            record.get("original_failure"), record.get("request"), record.get("response")
        )
        if (
            set(record) != {
                "type", "step", "original_journal_sha256", "request", "response",
                "original_failure", "native_boundary", "native_action_dispatched",
                "original_failure_reclassified_as_success",
            }
            or previous.get("type") != "decision_finished"
            or previous.get("decision_returned") is not False
            or "outcome" in previous
            or type(record.get("step")) is not int
            or record["step"] != previous.get("step")
            or record.get("original_journal_sha256") != prefix.hexdigest()
            or record.get("native_action_dispatched") is not False
            or record.get("original_failure_reclassified_as_success") is not False
            or not isinstance(failure, dict)
            or set(failure) != {"step", "error_type", "message", "events"}
            or type(failure.get("step")) is not int
            or failure["step"] != record["step"]
            or failure.get("error_type") != "CodexTransportError"
            or failure.get("message") != "Keyboard decision or subscription identity failed"
            or not isinstance(request, dict)
            or not isinstance(response, dict)
            or set(response) != {"request_sha256", "result"}
            or not isinstance(response.get("result"), dict)
            or response.get("request_sha256") != digest(request)
            or failure.get("events") != [
                {"type": "codex_keyboard_decision", "receipt": response["result"]}
            ]
            or not isinstance(record.get("native_boundary"), dict)
        ):
            raise ValueError("Historical rejection is not bound to its original evidence")
        validate_request(request)
        config = checkpoint["configuration"]
        receipt = response["result"]["transport_receipt"]
        if (
            config.get("control_profile") != NATIVE_PROFILE
            or config.get("observation_profile") != TEXT_PROFILE
            or request["max_advance_ticks"] != config.get("max_advance_ticks")
            or config.get("model") != receipt.get("model_requested")
            or config.get("reasoning_effort") != receipt.get("reasoning_effort_requested")
            or config.get("transport") != receipt.get("transport")
        ):
            raise ValueError("Rejection reconciliation changed campaign condition")
        if request_selection(request) != (config["model"], config["reasoning_effort"]):
            raise ValueError("Rejection request changed campaign model")
        rejected_receipt(
            response["result"],
            screen_sha256=digest(encode_screen(request["screen"], TEXT_PROFILE)),
            max_advance_ticks=request["max_advance_ticks"],
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
        )
        _clock(record["native_boundary"])
        prior = next(
            (item["usage"] for item in reversed(effective[:-1])
             if item.get("type") == "decision_finished"), None
        )
        if prior is None:
            from ..agent.campaign_keyboard import initial_usage
            prior = initial_usage()
        if (
            previous["usage"]["total_tokens"] - prior["total_tokens"]
            != response["result"]["transport_receipt"]["total_tokens"]
        ):
            raise ValueError("Reconciled response does not match retained usage")
        effective[-1] = {
            **deepcopy(previous), "decision_returned": True,
            "outcome": "model_input_rejected/v1", "native_action_dispatched": False,
            "native_boundary": record["native_boundary"],
        }
        prefix.update(lines[index])
    return effective
