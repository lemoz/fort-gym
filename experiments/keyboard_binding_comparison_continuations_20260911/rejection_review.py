"""Bind a retained rejected choice to its native no-dispatch record."""

from __future__ import annotations

import json
from typing import Any

from continuation_state import require


def equal_json(left: Any, right: Any) -> bool:
    """Keep booleans distinct from integer counters in evidence comparisons."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def verify_rejected_record(record: dict, rejected: Any) -> int:
    """A typed rejected response is counted, but contributes no native key press."""
    action, after = rejected.action, record["state_after_advance"]
    require(
        record["record_origin"] == "model_input_rejection/v1"
        and equal_json(record["action"], action),
        "Rejected trace action differs from original typed receipt",
    )
    require(
        type(after["year"]) is type(after["year_tick"]) is int and after["pause_state"] is True,
        "Rejected input lacks a paused native boundary",
    )
    expected = {
        "accepted": False,
        "validation_rejected": True,
        "why": str(rejected),
        "result": {
            "ok": False,
            "command_mutation": "not_attempted",
            "keys_sent": 0,
            "keys_confirmed": 0,
            "native_action_dispatched": False,
            "invalid_keys": rejected.invalid_keys,
        },
        "tick_feedback": {
            "requested_ticks": action["advance_ticks"],
            "ticks_advanced": 0,
            "deferred": False,
            "clock_dispatched": False,
            "reason": "unsupported_native_keys",
        },
    }
    require(equal_json(record["execute"], expected), "Rejected input lacks zero-dispatch proof")
    expected_clock = {
        "schema_version": "fortgym.no-native-dispatch/v1",
        "ok": False,
        "error": "unsupported_native_keys",
        "requested": action["advance_ticks"],
        "ticks_advanced": 0,
        "clock_dispatched": False,
        "start_year": after["year"],
        "start_tick": after["year_tick"],
        "end_year": after["year"],
        "end_tick": after["year_tick"],
        "paused_before": True,
        "paused_after": True,
    }
    require(equal_json(record["tick_advance"], expected_clock), "Rejected input changed the clock")
    return 0


def review_rejection(record: dict, request: dict, result: dict, condition: dict) -> int:
    """Reconstruct only through the frozen parser, without game/provider calls."""
    from fort_gym.bench.agent.keyboard_exchange import digest
    from fort_gym.bench.agent.keyboard_rejection import rejected_receipt
    from fort_gym.bench.env.screen_observation import TEXT_PROFILE, encode_screen

    require(
        all(
            equal_json(request[key], condition[key])
            for key in (
                "model",
                "reasoning_effort",
                "control_profile",
                "bindings_sha256",
                "max_advance_ticks",
            )
        ),
        "Rejected input request changed its declared condition",
    )
    rejected = rejected_receipt(
        result,
        screen_sha256=digest(encode_screen(request["screen"], TEXT_PROFILE)),
        max_advance_ticks=condition["max_advance_ticks"],
        model=condition["model"],
        reasoning_effort=condition["reasoning_effort"],
        control_profile=condition["control_profile"],
    )
    return verify_rejected_record(record, rejected)
