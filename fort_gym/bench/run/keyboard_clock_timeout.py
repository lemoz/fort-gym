"""Keep an attested zero-tick timeout as model feedback, not unknown execution."""

from __future__ import annotations

from .keyboard_clock import NATIVE_VIEW

SCHEMA = "fortgym.keyboard-clock-unavailable/v1"


def validate_zero_tick_timeout(receipt: dict, *, requested_ticks: int, state: dict) -> str | None:
    """Validate the original clock failure; never turn it into a successful advance."""
    year, tick = state.get("year"), state.get("year_tick")
    if (
        type(year) is not int
        or year < 0
        or type(tick) is not int
        or not 0 <= tick < 403200
        or state.get("pause_state") is not True
        or state.get("viewscreen_type") != "viewscreen_dwarfmodest"
        or type(requested_ticks) is not int
        or requested_ticks <= 0
        or type(receipt.get("requested")) is not int
        or receipt["requested"] != requested_ticks
        or type(receipt.get("ticks_advanced")) is not int
        or receipt["ticks_advanced"] != 0
        or receipt.get("ok") is not False
        or receipt.get("timeout") is not True
        or receipt.get("error") != "timeout_waiting_for_ticks"
        or receipt.get("final_viewscreen_type") != "viewscreen_dwarfmodest"
        or any(
            receipt.get(key) is not True
            for key in (
                "paused_before",
                "paused_after",
                "repause_requested",
                "repause_effective",
                "final_pause_state",
            )
        )
        or any(
            receipt.get(key) is not False
            for key in (
                "interrupt_safety_error",
                "calendar_safety_error",
            )
        )
        or any(
            receipt.get(key) is not None
            for key in (
                "resume_error",
                "repause_error",
                "nopause_enable_error",
                "tick_deadline_error",
                "intermediate_probe_error",
                "interruption_detection",
                "interrupted",
            )
        )
        or any(
            type(receipt.get(key)) is not int
            for key in (
                "start_year",
                "start_tick",
                "end_year",
                "end_tick",
            )
        )
        or (receipt["start_year"], receipt["start_tick"], receipt["end_year"], receipt["end_tick"])
        != (year, tick, year, tick)
    ):
        return "zero_tick_timeout_not_attested"
    repause = receipt.get("repause")
    if not isinstance(repause, dict):
        return "zero_tick_timeout_repause_missing"
    attempts = repause.get("attempt_records")
    if (
        repause.get("ok") is not True
        or repause.get("paused") is not True
        or not isinstance(attempts, list)
        or not attempts
        or type(repause.get("attempts")) is not int
        or repause["attempts"] != len(attempts)
        or any(
            not isinstance(row, dict)
            or type(row.get("attempt")) is not int
            or row["attempt"] != i + 1
            or row.get("nopause_disabled") is not True
            or row.get("paused") is not True
            for i, row in enumerate(attempts)
        )
    ):
        return "zero_tick_timeout_repause_unverified"
    return None


def validate_clock_unavailable(
    receipt: dict,
    *,
    requested_ticks: int,
    before: dict,
    after: dict,
) -> str | None:
    """Require fresh matching UI probes around the original failed clock operation."""
    if (
        receipt.get("schema_version") != SCHEMA
        or receipt.get("clock_unavailable") is not True
        or receipt.get("clock_dispatched") is not True
        or "deferred" in receipt
        or validate_zero_tick_timeout(receipt, requested_ticks=requested_ticks, state=after)
    ):
        return "clock_unavailable_contract_invalid"
    native, final = receipt.get("native_before"), receipt.get("native_after")
    if not isinstance(native, dict) or not isinstance(final, dict) or native != final:
        return "clock_unavailable_native_boundary_changed"
    if (
        native.get("paused") is not True
        or native.get("viewscreen_type") != NATIVE_VIEW
        or any(
            not isinstance(native.get(key), str) or not native[key]
            for key in ("dfroot", "save_name", "focus")
        )
        or type(native.get("year")) is not int
        or type(native.get("year_tick")) is not int
    ):
        return "clock_unavailable_native_identity_missing"
    for state in (before, after):
        if (
            type(state.get("year")) is not int
            or type(state.get("year_tick")) is not int
            or state.get("pause_state") is not True
            or state.get("viewscreen_type") != "viewscreen_dwarfmodest"
            or (state["year"], state["year_tick"]) != (native["year"], native["year_tick"])
        ):
            return "clock_unavailable_observation_mismatch"
    return None
