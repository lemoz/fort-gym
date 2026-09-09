"""Score-independent game-time telemetry for the campaign website.

This is observed run time, not a gameplay-success verdict or a checkpoint chain.
Only actual tick advances count; requested ticks and scalar scores never do.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

TICKS_PER_YEAR = 403_200


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def campaign_progress(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe elapsed time without mistaking a budget stop for game failure.

    Missing or malformed tick samples leave total duration unknown while retaining
    valid observed ticks. Calendar samples, when supplied, must agree with the
    actual delta. This function does not infer missing ticks from requested ticks.
    """

    observed_ticks = 0
    row_count = 0
    invalid_samples = 0
    previous_end: int | None = None
    previous_step: int | None = None
    seen_steps: set[int] = set()
    run_ids: set[str] = set()
    restart_losses: dict[str, int] = {}
    incomplete_restart_losses: set[str] = set()
    restart_metadata_invalid = False
    for record in records:
        row_count += 1
        discontinuities = record.get("discontinuities", [])
        if not isinstance(discontinuities, list):
            restart_metadata_invalid = True
        else:
            for restart in discontinuities:
                if not isinstance(restart, dict) or (
                    restart.get("schema_version") != "fortgym.native-save-loss-restart/v1"
                    or not isinstance(restart.get("source_result_sha256"), str)
                    or _count(restart.get("lost_elapsed_ticks")) is None
                    or restart.get("uninterrupted_campaign") is not False
                ):
                    restart_metadata_invalid = True
                    continue
                identity, loss = restart["source_result_sha256"], restart["lost_elapsed_ticks"]
                if identity in restart_losses and restart_losses[identity] != loss:
                    restart_metadata_invalid = True
                restart_losses[identity] = loss
                if "lost_elapsed_ticks_complete" in restart:
                    if restart["lost_elapsed_ticks_complete"] is not False:
                        restart_metadata_invalid = True
                    else:
                        incomplete_restart_losses.add(identity)
        step = _count(record.get("step"))
        duplicate = step is not None and step in seen_steps
        sequence_gap = step is None or (previous_step is not None and step != previous_step + 1)
        if step is not None:
            seen_steps.add(step)
            previous_step = step
        run_id = record.get("run_id")
        if isinstance(run_id, str) and run_id:
            run_ids.add(run_id)
        sample = record.get("tick_advance")
        if not isinstance(sample, Mapping) or duplicate or sequence_gap:
            invalid_samples += 1
            continue
        ticks = _count(sample.get("ticks_advanced"))
        if ticks is None:
            invalid_samples += 1
            continue
        calendar_keys = ("start_year", "start_tick", "end_year", "end_tick")
        if any(sample.get(key) is not None for key in calendar_keys):
            calendar = [_count(sample.get(key)) for key in calendar_keys]
            if any(value is None for value in calendar):
                invalid_samples += 1
                continue
            start_year, start_tick, end_year, end_tick = calendar
            assert start_year is not None and start_tick is not None
            assert end_year is not None and end_tick is not None
            start = start_year * TICKS_PER_YEAR + start_tick
            end = end_year * TICKS_PER_YEAR + end_tick
            if (
                start_tick >= TICKS_PER_YEAR
                or end_tick >= TICKS_PER_YEAR
                or end - start != ticks
                or (previous_end is not None and start != previous_end)
            ):
                invalid_samples += 1
                previous_end = None
                continue
            previous_end = end
        else:
            previous_end = None
        observed_ticks += ticks

    complete = row_count > 0 and invalid_samples == 0 and len(run_ids) <= 1
    return {
        "schema_version": "fortgym.campaign-progress/v1",
        "scope": "single_run",
        "ticks_per_year": TICKS_PER_YEAR,
        "observed_ticks": observed_ticks,
        "elapsed_ticks": observed_ticks if complete else None,
        "elapsed_years": observed_ticks / TICKS_PER_YEAR if complete else None,
        "year_two_reached": observed_ticks >= TICKS_PER_YEAR if complete else None,
        "time_evidence": "complete" if complete else "incomplete",
        "sample_count": row_count,
        "invalid_or_missing_samples": invalid_samples,
        "mixed_run_ids": len(run_ids) > 1,
        "functioning_fortress": "not_assessed",
        "autonomous_gameplay": "not_assessed",
        **({
            "uninterrupted_campaign": False if not restart_metadata_invalid else None,
            "native_save_loss_restarts": len(restart_losses) if not restart_metadata_invalid else None,
            "discarded_native_ticks": sum(restart_losses.values()) if not restart_metadata_invalid and not incomplete_restart_losses else None,
            **({
                "confirmed_discarded_native_ticks": sum(restart_losses.values()) if not restart_metadata_invalid else None,
                "discarded_native_ticks_complete": False,
            } if incomplete_restart_losses else {}),
        } if restart_losses or restart_metadata_invalid else {}),
    }


def read_campaign_progress(trace_path: Path) -> dict[str, Any]:
    """Read an existing trace without rewriting or rescoring historical evidence."""

    def records() -> Iterable[Mapping[str, Any]]:
        with trace_path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Malformed trace JSON at line {number}") from exc
                if not isinstance(record, dict):
                    raise TypeError(f"Trace line {number} must be an object")
                yield record

    return campaign_progress(records())
