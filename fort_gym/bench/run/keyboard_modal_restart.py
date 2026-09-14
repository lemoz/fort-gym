"""Recognize the retained zero-tick modal baseline failure and pending native save."""

import re

from ..agent.keyboard_prompt import effective_prompt
from ..agent.campaign_keyboard import validate_usage
from .keyboard_clock import MODAL_SCHEMA, deferral_schema

MODAL_KIND = "modal_clock_baseline_pending_save"
PROMPT_FIELDS = frozenset(("retained_prompt_changes", "source_prompt_state_sha256"))


def validate_modal_discontinuity(row: dict) -> None:
    if (
        row.get("failure_kind") != MODAL_KIND
        or row.get("save_failure_stage") != "identity_after_save_request_pending"
        or type(row.get("lost_uncommitted_decisions")) is not int
        or row["lost_uncommitted_decisions"] != 1
        or type(row.get("lost_uncommitted_ticks")) is not int
        or row["lost_uncommitted_ticks"] != 0
        or not isinstance(row.get("retained_usage"), dict)
        or not isinstance(row.get("retained_prompt_changes"), list)
        or "lost_elapsed_ticks_complete" in row
        or "source_start_agent_sha256" in row
        or any(
            not isinstance(row.get(key), str) or re.fullmatch("[a-f0-9]{64}", row[key]) is None
            for key in (
                "source_failure_sha256",
                "source_runtime_sha256",
                "source_prompt_state_sha256",
            )
        )
    ):
        raise ValueError("Modal restart lacks its accounted zero-tick failure")
    validate_usage(row["retained_usage"])
    effective_prompt(row["retained_prompt_changes"], row["retained_usage"])


def validate_modal_clock_failure(failure: dict, post_input: dict, after: dict) -> None:
    """Require the actual attempted-clock failure; never relabel it as a deferral."""
    native = failure["execute"]["result"]["native_receipts"][-1]["after"]
    tick = failure["tick_receipt"]
    year, clock = post_input["year"], post_input["year_tick"]
    expected = {
        "ok": False,
        "error": "interrupt_baseline_invalid",
        "requested": failure["action"]["advance_ticks"],
        "ticks_advanced": 0,
        "start_year": year,
        "end_year": year,
        "start_tick": clock,
        "end_tick": clock,
        "paused_before": True,
        "paused_after": True,
        "repause_requested": True,
        "repause_effective": True,
        "interrupt_safety_error": True,
        "calendar_safety_error": False,
        "final_pause_state": True,
        "final_viewscreen_type": post_input["viewscreen_type"],
    }
    if (
        deferral_schema(native) != MODAL_SCHEMA
        or post_input != after
        or failure["native_after_apply"] != post_input
        or set(tick) != set(expected) | {"elapsed_ms", "repause"}
        or any(
            type(tick.get(key)) is not type(value) or tick[key] != value
            for key, value in expected.items()
        )
        or type(tick.get("elapsed_ms")) is not int
        or tick["elapsed_ms"] < 0
    ):
        raise ValueError("Modal restart does not attest an unchanged zero-tick clock failure")
    repause = tick["repause"]
    attempts = repause.get("attempt_records", [])
    if (
        repause.get("ok") is not True
        or repause.get("paused") is not True
        or type(repause.get("attempts")) is not int
        or repause["attempts"] != len(attempts)
        or not attempts
        or any(
            type(row.get("attempt")) is not int
            or row["attempt"] != index + 1
            or row.get("nopause_disabled") is not True
            or row.get("paused") is not True
            for index, row in enumerate(attempts)
        )
    ):
        raise ValueError("Modal restart lacks verified final pause")
