"""Compose native checkpoint continuity across an entire declared window.

Provider receipts, private measurement coverage, resource ownership and VM
teardown are separate outer-auditor responsibilities. This module is read-only.
"""

from pathlib import Path

from ..agent.keyboard_exchange import read
from .campaign_checkpoint import verify_checkpoint
from .keyboard_config import validate_condition
from .keyboard_segment_audit import _require, verify_saved_segment
from .keyboard_window_audit import settled_segment_spans
from .keyboard_window_courier import window_bounds


def verify_window_checkpoints(
    native: Path,
    parent: Path,
    *,
    condition: dict,
    window: dict,
    initial_metrics: dict,
) -> dict:
    """Verify every saved segment and identify which saves were actually reloaded."""
    _require(
        read(native / "condition.json") == validate_condition(condition)
        and read(native / "window.json") == window,
        "Native window conditions changed",
    )
    result = read(native / "result.json")
    spans = settled_segment_spans(result, window)
    limit, _ = window_bounds(condition, window)
    _require(
        all(
            type(window.get(key)) is int and window[key] >= 0
            for key in (
                "accounted_responses_before_window",
                "returned_tokens_before_window",
                "saved_elapsed_ticks_before_window",
            )
        )
        and window["accounted_responses_before_window"] == spans[0].first_step,
        "Invalid prior campaign counters",
    )
    original = verify_checkpoint(parent)
    _require(
        original["sha256"] == window["continuation_checkpoint_sha256"],
        "Native window started from a different checkpoint",
    )
    initial_parent = parent
    reports: list[dict] = []
    metrics = initial_metrics
    for span in spans:
        _require(
            read(native / f"segment-{span.index}" / "result.json")
            == result["segments"][span.index],
            "Window summary differs from a segment result",
        )
        report = verify_saved_segment(
            native,
            parent,
            span,
            campaign_id=window["expected_campaign_id"],
            revision=window["source_native_revision"],
            expected_initial_metrics=metrics,
        )
        if reports:
            _require(
                report["prior_checkpoint_sha256"] == reports[-1]["checkpoint_sha256"],
                "Native window skipped a saved segment",
            )
            reports[-1]["final_fresh_reload_verified"] = True
        reports.append(report)
        parent = native / f"segment-{span.index}" / "checkpoint"
        metrics = report["saved_metrics"]
    responses = sum(row["new_responses"] for row in reports)
    tokens = sum(row["new_tokens"] for row in reports)
    ticks = sum(row["new_saved_ticks"] for row in reports)
    final = reports[-1]
    _require(
        final["usage"]["accounted_responses"]
        == window["accounted_responses_before_window"] + responses
        and final["usage"]["total_tokens"]
        == window["returned_tokens_before_window"] + tokens
        and final["saved_elapsed_ticks"]
        == window["saved_elapsed_ticks_before_window"] + ticks,
        "Window totals do not reconcile with the unchanged prior campaign",
    )
    _require(
        verify_checkpoint(initial_parent) == original
        and read(native / "result.json") == result,
        "Native window changed during audit",
    )
    return {
        "schema_version": "fortgym.private-window-checkpoint-audit/v1",
        "campaign_id": result["campaign_id"],
        "status": result["status"],
        "first_step": spans[0].first_step,
        "next_step": spans[-1].next_step,
        "response_limit": limit,
        "new_responses": responses,
        "new_tokens": tokens,
        "new_saved_ticks": ticks,
        "saved_elapsed_ticks": final["saved_elapsed_ticks"],
        "usage": final["usage"],
        "prior_checkpoint_sha256": original["sha256"],
        "checkpoint_sha256": final["checkpoint_sha256"],
        "segments": reports,
        "initial_metrics": initial_metrics,
        "saved_metrics": final["saved_metrics"],
        "final_fresh_reload_verified": False,
        "scope": "Native checkpoint, agent, trace, usage, calendar and load continuity only; not provider receipts, resource limits, measurement coverage, VM teardown or gameplay success.",
    }
