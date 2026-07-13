"""Calendar and receipt validation for external DFHack tick control."""

from __future__ import annotations

from typing import Any, Dict

from .env.actions import INTERACT_ALLOWED_VIEWSCREEN_TYPES

TICKS_PER_YEAR = 403200
MAX_CALENDAR_ADVANCE_TICKS = 2000
# Repause and the final atomic read can observe a few ticks after the request.
MAX_REQUEST_OVERSHOOT_TICKS = 50
GOVERNED_POSITIVE_TICK_BASELINE_VIEWSCREEN_TYPE = "viewscreen_dwarfmodest"


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def calendar_elapsed_ticks(
    start_year: Any,
    start_tick: Any,
    end_year: Any,
    end_tick: Any,
    *,
    max_advance_ticks: int | None = None,
) -> tuple[int | None, str | None]:
    """Validate a bounded DF calendar span and return its elapsed ticks."""

    if not all(
        _nonnegative_int(value)
        for value in (start_year, start_tick, end_year, end_tick)
    ):
        return None, "calendar_sample_invalid"
    if start_tick >= TICKS_PER_YEAR or end_tick >= TICKS_PER_YEAR:
        return None, "calendar_tick_out_of_range"
    year_delta = end_year - start_year
    if year_delta < 0:
        return None, "calendar_year_decreased"
    if year_delta > 1:
        return None, "calendar_year_jump_invalid"
    elapsed = year_delta * TICKS_PER_YEAR + end_tick - start_tick
    if elapsed < 0:
        return None, "calendar_tick_reversed"
    if max_advance_ticks is not None and elapsed > max_advance_ticks:
        return None, "calendar_elapsed_exceeds_bound"
    return elapsed, None


def _state_calendar_pair(state: Dict[str, Any] | None) -> tuple[Any, Any]:
    state = state or {}
    return state.get("year"), state.get("year_tick", state.get("time"))


def validate_clean_interruption_receipt(
    tick_info: Dict[str, Any],
    *,
    requested_ticks: int,
    state_after_apply: Dict[str, Any] | None,
    state_after_advance: Dict[str, Any] | None,
) -> str | None:
    """Return the first failed invariant for a clean governed interruption."""

    before = tick_info.get("viewscreen_before")
    at_interrupt = tick_info.get(
        "viewscreen_at_interrupt", tick_info.get("viewscreen_after")
    )
    after = tick_info.get("viewscreen_after")
    baseline = str((state_after_apply or {}).get("viewscreen_type") or "unknown")
    observed_after = str(
        (state_after_advance or {}).get("viewscreen_type") or "unknown"
    )
    start_year = tick_info.get("start_year")
    start_tick = tick_info.get("start_tick")
    end_year = tick_info.get("end_year")
    end_tick = tick_info.get("end_tick")
    ticks_advanced = tick_info.get("ticks_advanced")
    state_before_year, state_before_tick = _state_calendar_pair(state_after_apply)
    state_after_year, state_after_tick = _state_calendar_pair(state_after_advance)
    repause = tick_info.get("repause")

    if tick_info.get("interrupted") is not True:
        return "interrupt_flag_missing"
    if tick_info.get("ok") is not False:
        return "interrupt_ok_must_be_false"
    if tick_info.get("error") != "blocking_viewscreen_transition":
        return "interrupt_error_invalid"
    timeout = tick_info.get("timeout")
    if timeout is not None and type(timeout) is not bool:
        return "interrupt_timeout_invalid"
    if timeout is True:
        return "interrupt_timeout_present"
    if tick_info.get("interrupt_safety_error") is not False:
        return "interrupt_safety_error_present"
    if tick_info.get("calendar_safety_error") is not False:
        return "interrupt_calendar_safety_error_present"
    if any(
        tick_info.get(field) is not None
        for field in ("nopause_enable_error", "resume_error", "resume_fallback")
    ):
        return "interrupt_resume_error_present"
    if (
        type(tick_info.get("requested")) is not int
        or tick_info.get("requested") != requested_ticks
    ):
        return "interrupt_requested_ticks_mismatch"
    elapsed, calendar_error = calendar_elapsed_ticks(
        start_year,
        start_tick,
        end_year,
        end_tick,
    )
    if calendar_error is not None:
        return f"interrupt_{calendar_error}"
    if elapsed is not None and elapsed > requested_ticks + MAX_REQUEST_OVERSHOOT_TICKS:
        return "interrupt_tick_overshoot_exceeds_allowance"
    if type(ticks_advanced) is not int or ticks_advanced != elapsed:
        return "interrupt_tick_evidence_mismatch"
    if not all(
        type(value) is int and value >= 0
        for value in (
            state_before_year,
            state_before_tick,
            state_after_year,
            state_after_tick,
        )
    ):
        return "interrupt_calendar_state_invalid"
    if (state_before_year, state_before_tick) != (start_year, start_tick):
        return "interrupt_start_calendar_state_mismatch"
    if (state_after_year, state_after_tick) != (end_year, end_tick):
        return "interrupt_end_calendar_state_mismatch"
    state_before_time = (state_after_apply or {}).get("time")
    state_after_time = (state_after_advance or {}).get("time")
    if type(state_before_time) is not int or state_before_time < 0:
        return "interrupt_start_tick_state_invalid"
    if type(state_after_time) is not int or state_after_time < 0:
        return "interrupt_end_tick_state_invalid"
    if state_before_time != start_tick:
        return "interrupt_start_tick_state_mismatch"
    if state_after_time != end_tick:
        return "interrupt_end_tick_state_mismatch"
    if tick_info.get("paused_before") is not True:
        return "interrupt_paused_before_unattested"
    if tick_info.get("paused_after") is not True:
        return "interrupt_paused_after_unattested"
    if (
        not isinstance(before, str)
        or not isinstance(at_interrupt, str)
        or not isinstance(after, str)
    ):
        return "interrupt_viewscreen_missing"
    if before != GOVERNED_POSITIVE_TICK_BASELINE_VIEWSCREEN_TYPE:
        return "interrupt_baseline_not_normal_gameplay"
    if at_interrupt not in INTERACT_ALLOWED_VIEWSCREEN_TYPES:
        return "interrupt_initial_viewscreen_not_allowlisted"
    if after not in INTERACT_ALLOWED_VIEWSCREEN_TYPES:
        return "interrupt_viewscreen_not_allowlisted"
    if before != baseline:
        return "interrupt_baseline_mismatch"
    if (state_after_apply or {}).get("pause_state") is not True:
        return "interrupt_baseline_not_paused"
    if type(tick_info.get("pause_state_at_interrupt")) is not bool:
        return "interrupt_pause_state_invalid"
    if (
        tick_info.get("repause_requested") is not True
        or tick_info.get("repause_effective") is not True
    ):
        return "interrupt_repause_unattested"
    if tick_info.get("repause_error") is not None:
        return "interrupt_repause_error_present"
    if not isinstance(repause, dict):
        return "interrupt_repause_missing"
    if repause.get("ok") is not True or repause.get("paused") is not True:
        return "interrupt_repause_nested_unattested"
    if repause.get("error") is not None:
        return "interrupt_repause_nested_error_present"
    attempts = repause.get("attempts")
    records = repause.get("attempt_records")
    if type(attempts) is not int or attempts <= 0:
        return "interrupt_repause_attempts_invalid"
    if not isinstance(records, list) or not records or len(records) != attempts:
        return "interrupt_repause_records_invalid"
    for expected_attempt, record in enumerate(records, start=1):
        if (
            not isinstance(record, dict)
            or type(record.get("attempt")) is not int
            or record.get("attempt") != expected_attempt
        ):
            return "interrupt_repause_records_invalid"
    final_record = records[-1]
    if (
        final_record.get("nopause_disabled") is not True
        or final_record.get("paused") is not True
        or final_record.get("nopause_error") is not None
        or final_record.get("pause_error") is not None
    ):
        return "interrupt_repause_final_record_invalid"
    if tick_info.get("final_pause_state") is not True:
        return "interrupt_final_pause_unattested"
    if tick_info.get("final_viewscreen_type") != after:
        return "interrupt_final_viewscreen_mismatch"
    if (
        observed_after != after
        or (state_after_advance or {}).get("pause_state") is not True
    ):
        return "interrupt_post_observation_mismatch"
    return None


__all__ = [
    "GOVERNED_POSITIVE_TICK_BASELINE_VIEWSCREEN_TYPE",
    "MAX_CALENDAR_ADVANCE_TICKS",
    "MAX_REQUEST_OVERSHOOT_TICKS",
    "TICKS_PER_YEAR",
    "calendar_elapsed_ticks",
    "validate_clean_interruption_receipt",
]
