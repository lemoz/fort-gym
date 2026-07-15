"""Bounded external DFHack tick control and governed interruption handling."""

from __future__ import annotations

import time
from typing import Dict

from .config import DFHACK_RUN, DFROOT
from .dfhack_exec import (
    DFHackError,
    read_pause_state,
    read_tick_pause_viewscreen,
    run_dfhack,
    set_paused,
)
from .env.actions import (
    ABSOLUTE_MAX_ADVANCE_TICKS,
    INTERACT_ALLOWED_VIEWSCREEN_TYPES,
)
from .env.keystroke_exec import execute_keystroke_action
from .tick_receipt import (
    GOVERNED_POSITIVE_TICK_BASELINE_VIEWSCREEN_TYPE,
    MAX_REQUEST_OVERSHOOT_TICKS,
    TICKS_PER_YEAR,
    calendar_elapsed_ticks,
)

MAX_ADVANCE_TICKS = 2000


def _safe_read_pause_state(timeout: float = 1.0) -> bool | None:
    try:
        return read_pause_state(timeout=timeout)
    except (DFHackError, OSError):
        return None


def _set_nopause(enabled: bool) -> str | None:
    try:
        run_dfhack(
            [str(DFHACK_RUN), "nopause", "1" if enabled else "0"],
            timeout=2.0,
            cwd=str(DFROOT),
        )
    except Exception as exc:
        return str(exc)
    return None


def ensure_paused_external(
    *, timeout: float = 2.5, attempts: int = 2
) -> Dict[str, object]:
    """Disable nopause and attest that DF is actually paused."""

    attempt_records: list[Dict[str, object]] = []
    paused: bool | None = None
    for attempt in range(1, max(1, int(attempts)) + 1):
        nopause_error = _set_nopause(False)
        pause_error: str | None = None
        try:
            set_paused(True, timeout=timeout)
        except (DFHackError, OSError) as exc:
            pause_error = str(exc)
        paused = _safe_read_pause_state(timeout=timeout)
        record: Dict[str, object] = {
            "attempt": attempt,
            "nopause_disabled": nopause_error is None,
            "paused": paused,
        }
        if nopause_error:
            record["nopause_error"] = nopause_error
        if pause_error:
            record["pause_error"] = pause_error
        attempt_records.append(record)
        if nopause_error is None and paused is True:
            return {
                "ok": True,
                "paused": True,
                "attempts": attempt,
                "attempt_records": attempt_records,
            }
        if attempt < max(1, int(attempts)):
            time.sleep(0.1)
    return {
        "ok": False,
        "paused": paused,
        "attempts": len(attempt_records),
        "attempt_records": attempt_records,
        "error": "pause_state_unverified",
    }


def advance_ticks_exact_external(
    ticks: int,
    repause: bool = True,
    *,
    interrupt_on_viewscreen_transition: bool = False,
    viewscreen_before: str | None = None,
    max_advance_ticks: int = MAX_ADVANCE_TICKS,
) -> Dict[str, object]:
    """Advance a bounded number of ticks using atomic DF calendar samples."""

    try:
        want = int(ticks)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_ticks"}
    if want <= 0:
        return {"ok": False, "error": "invalid_ticks"}
    try:
        effective_max = int(max_advance_ticks)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_max_advance_ticks"}
    if effective_max <= 0 or effective_max > ABSOLUTE_MAX_ADVANCE_TICKS:
        return {"ok": False, "error": "invalid_max_advance_ticks"}
    want = min(want, effective_max)
    if interrupt_on_viewscreen_transition and repause is not True:
        return {
            "ok": False,
            "error": "governed_repause_required",
            "requested": want,
            "ticks_advanced": 0,
            "repause_requested": repause,
            "repause_effective": None,
        }

    started_paused: bool | None = None
    start_sample: Dict[str, object] | None = None
    current_sample: Dict[str, object] | None = None
    final_sample: Dict[str, object] | None = None
    ok = True
    error: str | None = None
    calendar_safety_error: str | None = None
    interrupt_safety_error: str | None = None
    resume_error: str | None = None
    resume_fallback: str | None = None
    nopause_enable_error: str | None = None
    repause_outcome: Dict[str, object] | None = None
    timed_out = False
    interrupted = False
    viewscreen_after: str | None = None
    viewscreen_at_interrupt: str | None = None
    pause_state_at_interrupt: bool | None = None
    intermediate_probe_error: str | None = None
    intermediate_probe_phase: str | None = None
    intermediate_probe_failure_kind: str | None = None
    interruption_detection: str | None = None
    baseline_viewscreen = str(viewscreen_before or "unknown")
    safety_ms = max(10000, want * 200)
    t_start = time.monotonic()

    def exceeds_request_overshoot(elapsed_ticks: int | None) -> bool:
        return (
            elapsed_ticks is not None
            and elapsed_ticks > want + MAX_REQUEST_OVERSHOOT_TICKS
        )

    def sample(*, governed: bool, phase: str, initial: bool = False) -> bool:
        nonlocal current_sample, started_paused, error, calendar_safety_error
        nonlocal \
            interrupt_safety_error, \
            interrupted, \
            viewscreen_after, \
            viewscreen_at_interrupt, \
            pause_state_at_interrupt
        nonlocal intermediate_probe_phase, intermediate_probe_failure_kind
        try:
            probe = read_tick_pause_viewscreen(timeout=2.5)
        except (DFHackError, OSError) as exc:
            if governed:
                error = "calendar_sample_read_failed"
                calendar_safety_error = error
                interrupt_safety_error = error
                intermediate_probe_phase = phase
                intermediate_probe_failure_kind = (
                    "dfhack_error" if isinstance(exc, DFHackError) else "os_error"
                )
            else:
                error = f"tick_read_failed:{exc}"
            return False
        current_sample = probe
        pause_state = probe["pause_state"]
        viewscreen = probe["viewscreen_type"]
        if started_paused is None:
            started_paused = pause_state if isinstance(pause_state, bool) else None
        calendar_start = start_sample or probe
        observed_elapsed, calendar_error = calendar_elapsed_ticks(
            calendar_start["cur_year"],
            calendar_start["cur_year_tick"],
            probe["cur_year"],
            probe["cur_year_tick"],
        )
        if calendar_error is not None:
            error = calendar_error
            calendar_safety_error = calendar_error
            if governed:
                interrupt_safety_error = calendar_error
            return False
        if not governed:
            if start_sample is not None and exceeds_request_overshoot(observed_elapsed):
                error = "tick_overshoot_exceeds_allowance"
                calendar_safety_error = error
                return False
            return True
        viewscreen_after = str(viewscreen)
        if (
            initial
            and baseline_viewscreen != GOVERNED_POSITIVE_TICK_BASELINE_VIEWSCREEN_TYPE
        ):
            error = "interrupt_baseline_invalid"
            interrupt_safety_error = error
            return False
        if viewscreen_after == "unknown":
            error = "interrupt_viewscreen_unknown"
            interrupt_safety_error = error
            return False
        if initial:
            if viewscreen_after != baseline_viewscreen:
                error = "interrupt_baseline_mismatch"
                interrupt_safety_error = error
                return False
            if pause_state is not True:
                error = "interrupt_baseline_unpaused"
                interrupt_safety_error = error
                return False
            return True
        if viewscreen_after == baseline_viewscreen:
            if start_sample is not None and exceeds_request_overshoot(observed_elapsed):
                error = "tick_overshoot_exceeds_allowance"
                calendar_safety_error = error
                interrupt_safety_error = error
                return False
            return True
        if viewscreen_after in INTERACT_ALLOWED_VIEWSCREEN_TYPES:
            interrupted = True
            viewscreen_at_interrupt = viewscreen_after
            pause_state_at_interrupt = pause_state
            error = "blocking_viewscreen_transition"
            return False
        error = "interrupt_viewscreen_unexpected"
        interrupt_safety_error = error
        return False

    def elapsed() -> int | None:
        if start_sample is None or current_sample is None:
            return None
        value, calendar_error = calendar_elapsed_ticks(
            start_sample["cur_year"],
            start_sample["cur_year_tick"],
            current_sample["cur_year"],
            current_sample["cur_year_tick"],
        )
        if calendar_error is not None:
            return None
        return value

    try:
        initial_ok = sample(
            governed=interrupt_on_viewscreen_transition,
            phase="initial",
            initial=interrupt_on_viewscreen_transition,
        )
        start_sample = current_sample
        if not initial_ok:
            ok = False

        if error is None and start_sample is not None:
            nopause_enable_error = _set_nopause(True)
            time.sleep(0.1)
            if not sample(
                governed=interrupt_on_viewscreen_transition,
                phase="post_nopause",
            ):
                ok = False

        if error is None and elapsed() == 0:
            try:
                set_paused(False, timeout=2.5)
            except (DFHackError, OSError) as exc:
                resume_error = str(exc)
            time.sleep(0.1)
            if not sample(
                governed=interrupt_on_viewscreen_transition,
                phase="post_resume",
            ):
                ok = False

        if (
            not interrupt_on_viewscreen_transition
            and error is None
            and elapsed() == 0
            and _safe_read_pause_state(timeout=2.5) is True
        ):
            try:
                fallback_result = execute_keystroke_action(["STRING_A032"])
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                resume_fallback = f"STRING_A032_failed:{exc}"
            else:
                resume_fallback = (
                    "STRING_A032" if fallback_result.get("ok") else str(fallback_result)
                )
            time.sleep(0.1)
            if not sample(governed=False, phase="fallback_resume"):
                ok = False

        if error is None and start_sample is not None and current_sample is not None:
            while True:
                if not sample(
                    governed=interrupt_on_viewscreen_transition,
                    phase="poll",
                ):
                    ok = False
                    break
                observed_elapsed = elapsed()
                if observed_elapsed is not None and observed_elapsed >= want:
                    break
                if (time.monotonic() - t_start) * 1000.0 > safety_ms:
                    timed_out = True
                    ok = False
                    error = "timeout_waiting_for_ticks"
                    break
                time.sleep(0.05)
    finally:
        if repause or error is not None:
            repause_outcome = ensure_paused_external(timeout=2.5, attempts=2)
        else:
            nopause_disable_error = _set_nopause(False)
            if nopause_disable_error:
                ok = False
                error = "nopause_disable_failed"
                repause_outcome = ensure_paused_external(timeout=2.5, attempts=2)

    paused_after = (
        repause_outcome.get("paused")
        if repause_outcome is not None
        else _safe_read_pause_state(timeout=2.5)
    )
    if repause_outcome is not None and repause_outcome.get("ok") is True:
        try:
            final_sample = read_tick_pause_viewscreen(timeout=2.5)
            current_sample = final_sample
            paused_after = final_sample["pause_state"]
            final_elapsed: int | None = None
            final_calendar_error: str | None = None
            if start_sample is not None:
                final_elapsed, final_calendar_error = calendar_elapsed_ticks(
                    start_sample["cur_year"],
                    start_sample["cur_year_tick"],
                    final_sample["cur_year"],
                    final_sample["cur_year_tick"],
                )
            if interrupt_on_viewscreen_transition:
                final_viewscreen = str(final_sample["viewscreen_type"])
                recoverable_final_transition = (
                    error == "calendar_sample_read_failed"
                    and start_sample is not None
                    and final_sample["pause_state"] is True
                    and final_viewscreen != baseline_viewscreen
                    and final_viewscreen in INTERACT_ALLOWED_VIEWSCREEN_TYPES
                    and final_calendar_error is None
                    and final_elapsed is not None
                    and not exceeds_request_overshoot(final_elapsed)
                    and nopause_enable_error is None
                    and resume_error is None
                )
                final_viewscreen_valid = (
                    final_viewscreen in INTERACT_ALLOWED_VIEWSCREEN_TYPES
                    if interrupted or recoverable_final_transition
                    else final_viewscreen == baseline_viewscreen
                )
                if (
                    final_sample["pause_state"] is not True
                    or not final_viewscreen_valid
                ):
                    interrupt_safety_error = "final_interrupt_attestation_inconsistent"
                elif recoverable_final_transition:
                    # A DFHack calendar probe can fail while a modal transition
                    # is occurring. If the governed start, final calendar,
                    # repause, and final allowlisted modal are independently
                    # attested, preserve the failed probe as audit evidence and
                    # hand the final modal back to the runner.
                    intermediate_probe_error = error
                    interruption_detection = "final_attestation"
                    interrupted = True
                    viewscreen_after = final_viewscreen
                    error = "blocking_viewscreen_transition"
                    calendar_safety_error = None
                    interrupt_safety_error = None
                elif interrupted:
                    # DF can progress through a chain of blocking meeting views
                    # while the controller is re-pausing it. Preserve the first
                    # detected modal for audit, but hand the runner the final,
                    # paused, allowlisted modal it will actually observe.
                    viewscreen_after = final_viewscreen
            if start_sample is not None:
                if final_calendar_error is not None:
                    calendar_safety_error = final_calendar_error
                    if interrupt_on_viewscreen_transition:
                        interrupt_safety_error = final_calendar_error
                elif error is None and exceeds_request_overshoot(final_elapsed):
                    calendar_safety_error = "tick_overshoot_exceeds_allowance"
                    if interrupt_on_viewscreen_transition:
                        interrupt_safety_error = calendar_safety_error
        except (DFHackError, OSError) as exc:
            ok = False
            if interrupt_on_viewscreen_transition:
                calendar_safety_error = "calendar_final_read_failed"
                interrupt_safety_error = "final_interrupt_attestation_read_failed"
            elif error is None:
                error = f"final_tick_read_failed:{exc}"
    elif repause_outcome is not None:
        ok = False

    ticks_advanced = 0
    if start_sample is not None and current_sample is not None:
        ticks_advanced, calendar_error = calendar_elapsed_ticks(
            start_sample["cur_year"],
            start_sample["cur_year_tick"],
            current_sample["cur_year"],
            current_sample["cur_year_tick"],
        )
        if calendar_error is not None:
            ticks_advanced = 0
            calendar_safety_error = calendar_error
            if interrupt_on_viewscreen_transition:
                interrupt_safety_error = calendar_error

    if error is None and exceeds_request_overshoot(ticks_advanced):
        calendar_safety_error = "tick_overshoot_exceeds_allowance"
        if interrupt_on_viewscreen_transition:
            interrupt_safety_error = calendar_safety_error

    repause_unverified = repause_outcome is not None and (
        repause_outcome.get("ok") is not True or (repause and paused_after is not True)
    )
    if repause_unverified:
        ok = False
        if interrupt_on_viewscreen_transition:
            error = "repause_unverified"
        else:
            error = error or "repause_unverified"
    elif calendar_safety_error is not None:
        ok = False
        error = calendar_safety_error
    elif interrupt_safety_error is not None:
        ok = False
        error = interrupt_safety_error
    elif timed_out:
        ok = False
        error = error or resume_error or "timeout_waiting_for_ticks"
    elif ticks_advanced is not None and ticks_advanced < want:
        ok = False
        error = error or resume_error or "insufficient_tick_advance"

    result: Dict[str, object] = {
        "ok": ok and error is None,
        "requested": want,
        "ticks_advanced": ticks_advanced or 0,
        "start_year": start_sample.get("cur_year") if start_sample else None,
        "start_tick": start_sample.get("cur_year_tick") if start_sample else None,
        "end_year": current_sample.get("cur_year") if current_sample else None,
        "end_tick": current_sample.get("cur_year_tick") if current_sample else None,
        "paused_before": started_paused,
        "paused_after": paused_after,
        "elapsed_ms": int((time.monotonic() - t_start) * 1000.0),
        "repause_requested": repause,
        "repause_effective": paused_after is True if repause else None,
    }
    if nopause_enable_error:
        result["nopause_enable_error"] = nopause_enable_error
    if resume_error:
        result["resume_error"] = resume_error
    if resume_fallback:
        result["resume_fallback"] = resume_fallback
    if repause_outcome is not None:
        result["repause"] = repause_outcome
        if repause_unverified:
            result["repause_error"] = str(
                repause_outcome.get("error") or "pause_state_unverified"
            )
    if error:
        result["error"] = error
    if intermediate_probe_error:
        result["intermediate_probe_error"] = intermediate_probe_error
        result["intermediate_probe_phase"] = intermediate_probe_phase
        result["intermediate_probe_failure_kind"] = intermediate_probe_failure_kind
    if interruption_detection:
        result["interruption_detection"] = interruption_detection
    if timed_out:
        result["timeout"] = True
    if interrupted:
        result.update(
            {
                "interrupted": True,
                "viewscreen_before": baseline_viewscreen,
                "viewscreen_after": viewscreen_after,
            }
        )
        if viewscreen_at_interrupt is not None:
            result["viewscreen_at_interrupt"] = viewscreen_at_interrupt
        if pause_state_at_interrupt is not None:
            result["pause_state_at_interrupt"] = pause_state_at_interrupt
    if interrupt_on_viewscreen_transition:
        result["interrupt_safety_error"] = interrupt_safety_error is not None
        result["calendar_safety_error"] = calendar_safety_error is not None
        if final_sample is not None:
            result["final_pause_state"] = final_sample["pause_state"]
            result["final_viewscreen_type"] = final_sample["viewscreen_type"]
    elif calendar_safety_error is not None:
        result["calendar_safety_error"] = True
    return result


advance_ticks_exact = advance_ticks_exact_external


__all__ = [
    "GOVERNED_POSITIVE_TICK_BASELINE_VIEWSCREEN_TYPE",
    "MAX_ADVANCE_TICKS",
    "MAX_REQUEST_OVERSHOOT_TICKS",
    "TICKS_PER_YEAR",
    "advance_ticks_exact",
    "advance_ticks_exact_external",
    "ensure_paused_external",
]
