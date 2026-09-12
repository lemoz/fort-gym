"""Read-only native checkpoint continuity checks for one declared segment.

The outer auditor still owns provider receipts, resource limits, whole-window
ordering and VM teardown. A verified saved checkpoint is not a fresh reload of
that final checkpoint, and neither one is evidence of sustainable gameplay.
"""

import hashlib
import json
from pathlib import Path
import re

from ..agent.keyboard_exchange import read
from ..eval.campaign import TICKS_PER_YEAR, read_campaign_progress
from ..eval.campaign_profile import metrics_from_state
from .campaign_checkpoint import verify_checkpoint
from .campaign_loop import reconciled_usage
from .keyboard_window_audit import SegmentSpan


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _clock(value: dict, pause_key: str) -> int:
    year, tick = value.get("year"), value.get("year_tick")
    if (
        type(year) is not int
        or year < 0
        or type(tick) is not int
        or not 0 <= tick < TICKS_PER_YEAR
        or value.get(pause_key) is not True
    ):
        raise ValueError("Invalid or unpaused native calendar")
    return year * TICKS_PER_YEAR + tick


def verify_save_boundary(save: dict, after: dict) -> None:
    """Check the semantic save receipt, not promise an identical reloaded menu."""
    _require(
        save.get("snapshot_profile") == "native_menu_preserving_save/v4",
        "Unexpected native save profile",
    )
    for key in ("screen_sha256", "screen_after_sha256"):
        _require(
            isinstance(save.get(key), str)
            and re.fullmatch(r"[a-f0-9]{64}", save[key]) is not None,
            "Malformed native save screen digest",
        )
    _require(
        save.get("screen_unchanged")
        is (save["screen_sha256"] == save["screen_after_sha256"])
        and save.get("ui_identity_unchanged") is True
        and save.get("world_observations_unchanged") is True,
        "Native save altered its world or UI identity",
    )
    _require(
        _clock(save, "paused") == _clock(after, "pause_state"),
        "Saved and observed calendar differ",
    )


def verify_saved_segment(
    native: Path,
    parent: Path,
    span: SegmentSpan,
    *,
    campaign_id: str,
    revision: str,
    expected_initial_metrics: dict,
) -> dict:
    """Verify native bytes, load, saved cursor, own usage and full trace prefix."""
    _require(
        type(span.index) is int
        and 0 <= span.index < 16
        and type(span.first_step) is int
        and span.first_step > 0
        and type(span.next_step) is int
        and span.first_step <= span.next_step <= span.first_step + 64,
        "Invalid declared segment span",
    )
    segment_path = native / f"segment-{span.index}"
    checkpoint = segment_path / "checkpoint"
    runtime_path = native / f"runtime-{span.index}" / "result.json"
    parent_manifest = verify_checkpoint(parent)
    manifest = verify_checkpoint(checkpoint)
    source, payload = parent_manifest["payload"], manifest["payload"]
    _require(
        source["campaign_id"] == payload["campaign_id"] == campaign_id
        and source["next_step"] == span.first_step
        and type(source["next_step"]) is int
        and type(payload["next_step"]) is int
        and type(payload["last_committed_step"]) is int
        and payload["next_step"] == span.next_step
        and payload["last_committed_step"] == span.next_step - 1
        and payload["parent_sha256"] == parent_manifest["sha256"]
        and payload["code_revision"] == revision,
        "Native segment does not extend its own exact checkpoint",
    )
    segment, runtime = read(segment_path / "result.json"), read(runtime_path)
    _require(
        segment == runtime["experiment"]
        and segment.get("status") == "bounded_segment_complete"
        and segment.get("checkpoint_verified") is True
        and segment.get("recovery_requires_reconciliation") is False
        and segment.get("discontinuities", []) == []
        and not any(k.endswith("error") or k.endswith("error_type") for k in segment)
        and segment["campaign_id"] == campaign_id
        and type(segment["first_step"]) is int
        and type(segment["next_step"]) is int
        and segment["first_step"] == span.first_step
        and segment["next_step"] == span.next_step
        and segment["source_revision"] == runtime["code_revision"] == revision
        and runtime["source_checkpoint_file_sha256"] == _sha(parent / "checkpoint.json")
        and all(
            runtime.get(key) is True
            for key in ("native_load_verified", "cleanup_verified", "listener_closed")
        )
        and runtime.get("remaining_live_processes") == [],
        "Native runtime did not load the bound parent and clean up",
    )
    before, after = (
        read(segment_path / "native-before.json"),
        read(segment_path / "native-after.json"),
    )
    _require(
        _clock(before, "pause_state")
        == _clock(source["native_save"], "paused")
        == _clock(runtime["loaded"], "paused")
        and metrics_from_state(before) == expected_initial_metrics,
        "Native source load differs from the previous saved world",
    )
    verify_save_boundary(payload["native_save"], after)
    new_ticks = _clock(after, "pause_state") - _clock(before, "pause_state")
    _require(new_ticks >= 0, "Native calendar regressed")
    initial, agent = read(parent / "agent.json"), read(checkpoint / "agent.json")
    _require(
        initial == read(segment_path / "agent-before.json")
        and agent == read(segment_path / "agent-after.json"),
        "Native segment changed its bound agent state",
    )
    for key in ("configuration", "budget_extensions", "prompt_changes", "campaign_id"):
        _require(
            agent.get(key) == initial.get(key),
            "Campaign conditions changed inside segment",
        )
    _require(initial["campaign_id"] == campaign_id, "Agent belongs to another campaign")
    _require(
        reconciled_usage(initial, (parent / "usage.jsonl").read_bytes())
        == initial["usage"],
        "Source checkpoint usage is unsettled",
    )
    _require(
        reconciled_usage(agent, (checkpoint / "usage.jsonl").read_bytes())
        == agent["usage"]
        == segment["usage"],
        "Final checkpoint usage is unsettled",
    )
    for key in ("accounted_responses", "returned_responses", "dispatched_requests"):
        _require(
            type(agent["usage"][key]) is type(initial["usage"][key]) is int
            and agent["usage"][key] == initial["usage"][key] + span.responses,
            "Segment response counters do not match its saved cursor",
        )
    new_tokens = agent["usage"]["total_tokens"] - initial["usage"]["total_tokens"]
    _require(
        type(new_tokens) is int
        and new_tokens >= 0
        and agent["usage"]["total_cost_usd"] is None,
        "Segment token or unreported-cost accounting changed",
    )
    for name in ("trace.jsonl", "usage.jsonl"):
        with (
            (parent / name).open("rb") as left,
            (checkpoint / name).open("rb") as right,
        ):
            while chunk := left.read(1024 * 1024):
                _require(
                    right.read(len(chunk)) == chunk,
                    "Prior campaign history was changed",
                )
        _require(
            _sha(checkpoint / name) == _sha(segment_path / "loop" / name),
            "Checkpoint does not contain the settled worker history",
        )
    seen, advanced = 0, 0
    with (checkpoint / "trace.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            _require(
                line.endswith("\n")
                and isinstance(row, dict)
                and type(row.get("step")) is int
                and row["step"] == seen
                and seen < span.next_step
                and row.get("run_id") == campaign_id,
                "Segment trace has missing, repeated or borrowed decisions",
            )
            if seen >= span.first_step:
                ticks = row["tick_advance"]["ticks_advanced"]
                _require(type(ticks) is int and ticks >= 0, "Invalid action tick count")
                advanced += ticks
            seen += 1
    _require(
        seen == span.next_step and advanced == new_ticks,
        "Native calendar and per-action tick receipts disagree",
    )
    progress = read_campaign_progress(checkpoint / "trace.jsonl")
    _require(
        progress["elapsed_ticks"] == segment["committed_elapsed_ticks"]
        and progress.get("native_save_loss_restarts", 0) == 0
        and not (segment_path / "loop/failures.jsonl").exists(),
        "Native segment has unreconciled history or save loss",
    )
    _require(
        verify_checkpoint(parent) == parent_manifest
        and verify_checkpoint(checkpoint) == manifest,
        "Checkpoint changed during read-only audit",
    )
    return {
        "segment_index": span.index,
        "first_step": span.first_step,
        "next_step": span.next_step,
        "new_responses": span.responses,
        "new_tokens": new_tokens,
        "new_saved_ticks": new_ticks,
        "saved_elapsed_ticks": progress["elapsed_ticks"],
        "usage": agent["usage"],
        "prior_checkpoint_sha256": parent_manifest["sha256"],
        "checkpoint_sha256": manifest["sha256"],
        "initial_metrics": expected_initial_metrics,
        "saved_metrics": metrics_from_state(after),
        "source_checkpoint_fresh_load_verified": True,
        "native_cleanup_verified": True,
        "final_fresh_reload_verified": False,
    }
