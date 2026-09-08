"""Bind a completed native save, agent state, and settled trace in one checkpoint.

A checkpoint directory is resumable only when its final manifest and every bound
file verify. Restore materializes a new save directory; it never overwrites a live
fortress. The runtime launcher remains responsible for loading and verifying it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..agent.base import Agent
from .campaign_save import NativeSnapshotter, save_inventory


class CampaignCheckpointError(RuntimeError):
    """Checkpoint lineage, source state, or retained bytes failed verification."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CampaignCheckpointError(f"Checkpoint file is not regular: {path.name}")
    return path.read_bytes()


def verify_checkpoint(directory: Path) -> dict[str, Any]:
    """Verify fixed file locations, not arbitrary paths named by a manifest."""
    if directory.is_symlink() or not directory.is_dir():
        raise CampaignCheckpointError("Checkpoint must be a regular directory")
    manifest = json.loads(_read_regular(directory / "checkpoint.json"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") not in (
        "fortgym.campaign-checkpoint/v1",
        "fortgym.campaign-checkpoint/v2",
        "fortgym.campaign-checkpoint/v3",
    ):
        raise CampaignCheckpointError("Unsupported checkpoint manifest")
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or _digest(_json_bytes(payload)) != manifest.get("sha256"):
        raise CampaignCheckpointError("Checkpoint manifest digest mismatch")
    for name, key in (("agent.json", "agent_sha256"), ("trace.jsonl", "trace_sha256")):
        if _digest(_read_regular(directory / name)) != payload.get(key):
            raise CampaignCheckpointError(f"Checkpoint digest mismatch: {name}")
    if manifest["schema_version"] in {
        "fortgym.campaign-checkpoint/v2",
        "fortgym.campaign-checkpoint/v3",
    }:
        for name, key in (("runner.json", "runner_sha256"), ("usage.jsonl", "usage_sha256")):
            if _digest(_read_regular(directory / name)) != payload.get(key):
                raise CampaignCheckpointError(f"Checkpoint digest mismatch: {name}")
    receipt = payload.get("native_save")
    if not isinstance(receipt, dict) or save_inventory(directory / "game") != receipt.get("files"):
        raise CampaignCheckpointError("Checkpoint game save digest mismatch")
    if manifest["schema_version"] == "fortgym.campaign-checkpoint/v3":
        _verify_no_action_boundary(directory, payload)
    return manifest


def _verify_no_action_boundary(directory: Path, payload: dict) -> None:
    # Runtime import avoids a module-initialization cycle with the loop, which
    # owns the shared usage-journal validator used by resume as well.
    from .campaign_loop import _clock, reconciled_usage

    pause_bytes = _read_regular(directory / "decision-pauses.jsonl")
    if _digest(pause_bytes) != payload.get("decision_pauses_sha256"):
        raise CampaignCheckpointError("Checkpoint no-action receipt digest mismatch")
    boundary = payload.get("no_action_boundary")
    if not isinstance(boundary, dict):
        raise CampaignCheckpointError("Checkpoint lacks a no-action boundary")
    _clock(boundary)
    last, cursor = payload.get("last_committed_step"), payload.get("next_step")
    if type(last) is not int or last < -1 or type(cursor) is not int or cursor != last + 1:
        raise CampaignCheckpointError("No-action checkpoint cursor is invalid")
    trace = _read_regular(directory / "trace.jsonl")
    if cursor == 0:
        if trace:
            raise CampaignCheckpointError("Initial no-action checkpoint must have an empty trace")
    else:
        rows = [json.loads(line) for line in trace.splitlines()]
        if not trace.endswith(b"\n") or not rows or any(not isinstance(row, dict) for row in rows):
            raise CampaignCheckpointError("No-action checkpoint trace is incomplete")
        steps = [row.get("step") for row in rows]
        if (
            any(type(step) is not int for step in steps)
            or steps[0] not in (0, 1)
            or steps != list(range(steps[0], cursor))
            or any(row.get("run_id") != payload.get("run_id") for row in rows)
        ):
            raise CampaignCheckpointError("No-action checkpoint trace cursor differs")
        final = rows[-1].get("tick_advance")
        if not isinstance(final, dict) or (final.get("end_year"), final.get("end_tick")) != (
            boundary["year"],
            boundary["year_tick"],
        ):
            raise CampaignCheckpointError("No-action checkpoint differs from its committed trace")
    native = payload["native_save"]
    if native.get("paused") is not True or (native.get("year"), native.get("year_tick")) != (
        boundary["year"],
        boundary["year_tick"],
    ):
        raise CampaignCheckpointError("No-action checkpoint differs from its native boundary")
    if not pause_bytes.endswith(b"\n"):
        raise CampaignCheckpointError("No-action receipt is incomplete")
    pause = json.loads(pause_bytes.splitlines()[-1])
    usage_bytes = _read_regular(directory / "usage.jsonl")
    agent = json.loads(_read_regular(directory / "agent.json"))
    if not isinstance(agent, dict) or agent.get("campaign_id") != payload.get("campaign_id"):
        raise CampaignCheckpointError("No-action checkpoint agent identity differs")
    if reconciled_usage(agent, usage_bytes) != agent.get("usage"):
        raise CampaignCheckpointError("No-action checkpoint usage is not fully reconciled")
    decision = json.loads(usage_bytes.splitlines()[-1])
    if (
        not isinstance(pause, dict)
        or pause.get("type") != "accounted_no_action/v1"
        or pause.get("decision_started") is not True
        or pause.get("reason") != "output_token_limit"
        or pause.get("native_action_dispatched") is not False
        or pause.get("native_boundary") != boundary
        or pause.get("step") != payload.get("next_step")
        or decision.get("outcome") != "accounted_no_action/v1"
        or decision.get("native_boundary") != boundary
        or decision.get("step") != payload.get("next_step")
        or decision.get("usage") != agent.get("usage")
    ):
        raise CampaignCheckpointError("No-action checkpoint receipt or usage boundary differs")


def create_checkpoint(
    destination: Path,
    *,
    campaign_id: str,
    agent: Agent,
    snapshotter: NativeSnapshotter,
    trace_path: Path,
    last_committed_step: int,
    code_revision: str,
    parent: Path | None = None,
    runner_state: dict[str, Any] | None = None,
    usage_path: Path | None = None,
    no_action_boundary: dict[str, Any] | None = None,
    pauses_path: Path | None = None,
) -> dict[str, Any]:
    """Capture a paused action boundary or fully accounted no-action boundary.

    Decisions must be suspended. Normal checkpoints follow execution and trace
    fsync. A v3 no-action checkpoint instead binds settled usage and a receipt
    proving no command was dispatched, including before the first game action.
    Pending agent actions are for review, never execution during restoration.
    Incomplete destinations are retained for diagnosis without a final manifest.
    """
    if type(last_committed_step) is not int or last_committed_step < (
        -1 if no_action_boundary is not None else 0
    ):
        raise ValueError("last_committed_step must be a nonnegative integer")
    if not campaign_id or not code_revision:
        raise ValueError("Campaign identity and code revision are required")
    if (runner_state is None) != (usage_path is None):
        raise ValueError("Runner state and usage journal must be checkpointed together")
    if (no_action_boundary is None) != (pauses_path is None) or (
        no_action_boundary is not None and runner_state is None
    ):
        raise ValueError("No-action boundary requires loop state, usage and pause receipts")
    runner_bytes = _json_bytes(runner_state) if runner_state is not None else None
    boundary_bytes = _json_bytes(no_action_boundary)
    usage_bytes = _read_regular(usage_path) if usage_path is not None else None
    pause_bytes = _read_regular(pauses_path) if pauses_path is not None else None
    state = agent.export_campaign_state()
    if state.get("campaign_id") != campaign_id:
        raise CampaignCheckpointError("Agent belongs to another campaign")
    agent_bytes = _json_bytes(state)
    trace_bytes = _read_regular(trace_path)
    empty_boundary = no_action_boundary is not None and last_committed_step == -1
    if not trace_bytes.endswith(b"\n") and not (empty_boundary and not trace_bytes):
        raise CampaignCheckpointError("Trace does not end at a committed newline")
    rows = [json.loads(line) for line in trace_bytes.splitlines() if line.strip()]
    if (not rows and not empty_boundary) or any(not isinstance(row, dict) for row in rows):
        raise CampaignCheckpointError("Trace has no committed action records")
    run_id = rows[0].get("run_id") if rows else campaign_id
    steps = [row.get("step") for row in rows]
    if (
        not isinstance(run_id, str)
        or not run_id
        or any(row.get("run_id") != run_id for row in rows)
        or any(type(step) is not int for step in steps)
        or (
            bool(steps)
            and (steps != list(range(steps[0], last_committed_step + 1)) or steps[0] not in (0, 1))
        )
        or (empty_boundary and bool(rows))
    ):
        raise CampaignCheckpointError("Trace cursor or run identity does not match the checkpoint")
    parent_manifest = verify_checkpoint(parent) if parent is not None else None
    if parent_manifest is not None and parent_manifest["payload"].get("campaign_id") != campaign_id:
        raise CampaignCheckpointError("Parent checkpoint belongs to another campaign")
    if rows:
        tick_advance = rows[-1].get("tick_advance")
    else:
        assert no_action_boundary is not None  # Empty trace requires the v3 boundary above.
        tick_advance = {
            "end_year": no_action_boundary.get("year"),
            "end_tick": no_action_boundary.get("year_tick"),
        }
    if not isinstance(tick_advance, dict) or any(
        type(tick_advance.get(key)) is not int for key in ("end_year", "end_tick")
    ):
        raise CampaignCheckpointError("Final trace row must record the native calendar boundary")
    if (
        parent is not None
        and parent_manifest is not None
        and parent_manifest["payload"]["run_id"] == run_id
        and not trace_bytes.startswith(_read_regular(parent / "trace.jsonl"))
    ):
        raise CampaignCheckpointError("Same-run checkpoint must extend its parent trace")

    # Keep the immutable bytes and final calendar receipt, not a second expanded
    # copy of every observation while the snapshotter validates its own source.
    del rows
    destination.mkdir(parents=False, mode=0o700, exist_ok=False)
    native = snapshotter.capture(destination / "game")
    if (native["year"], native["year_tick"]) != (
        tick_advance["end_year"],
        tick_advance["end_tick"],
    ):
        raise CampaignCheckpointError("Native save calendar does not match the committed action")
    if parent_manifest is not None:
        previous = parent_manifest["payload"]["native_save"]
        if (native["year"], native["year_tick"]) < (previous["year"], previous["year_tick"]):
            raise CampaignCheckpointError("Checkpoint game time precedes its parent")
    if (
        _read_regular(trace_path) != trace_bytes
        or _json_bytes(agent.export_campaign_state()) != agent_bytes
        or (usage_path is not None and _read_regular(usage_path) != usage_bytes)
        or (runner_state is not None and _json_bytes(runner_state) != runner_bytes)
        or (pauses_path is not None and _read_regular(pauses_path) != pause_bytes)
        or _json_bytes(no_action_boundary) != boundary_bytes
    ):
        raise CampaignCheckpointError("Agent or trace changed during checkpoint capture")
    _write_new(destination / "agent.json", agent_bytes)
    _write_new(destination / "trace.jsonl", trace_bytes)
    if runner_bytes is not None and usage_bytes is not None:
        _write_new(destination / "runner.json", runner_bytes)
        _write_new(destination / "usage.jsonl", usage_bytes)
    if pause_bytes is not None:
        _write_new(destination / "decision-pauses.jsonl", pause_bytes)
    for record in native["files"]:
        with (destination / "game" / record["path"]).open("rb") as handle:
            os.fsync(handle.fileno())
    payload = {
        "campaign_id": campaign_id,
        "run_id": run_id,
        "last_committed_step": last_committed_step,
        "next_step": last_committed_step + 1,
        "code_revision": code_revision,
        "parent_sha256": parent_manifest["sha256"] if parent_manifest else None,
        "agent_sha256": _digest(agent_bytes),
        "trace_sha256": _digest(trace_bytes),
        "native_save": native,
    }
    if runner_bytes is not None and usage_bytes is not None:
        payload.update(runner_sha256=_digest(runner_bytes), usage_sha256=_digest(usage_bytes))
    if pause_bytes is not None:
        payload.update(
            no_action_boundary=no_action_boundary, decision_pauses_sha256=_digest(pause_bytes)
        )
        # Invalid no-action receipts must leave only an incomplete diagnostic
        # directory, never a published final checkpoint manifest.
        _verify_no_action_boundary(destination, payload)
    manifest = {
        "schema_version": (
            "fortgym.campaign-checkpoint/v3"
            if no_action_boundary is not None
            else "fortgym.campaign-checkpoint/v2"
            if runner_bytes is not None
            else "fortgym.campaign-checkpoint/v1"
        ),
        "payload": payload,
        "sha256": _digest(_json_bytes(payload)),
    }
    temporary_manifest = destination / "checkpoint.pending.json"
    _write_new(temporary_manifest, _json_bytes(manifest))
    # Publish atomically without replacing even an unexpected concurrent manifest.
    os.link(temporary_manifest, destination / "checkpoint.json")
    temporary_manifest.unlink()
    descriptor = os.open(destination, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return verify_checkpoint(destination)


def materialize_checkpoint(directory: Path, *, save_destination: Path) -> dict[str, Any]:
    """Prepare a verified new save and agent state, without loading/starting DF."""
    manifest = verify_checkpoint(directory)
    if save_destination.exists() or save_destination.is_symlink():
        raise CampaignCheckpointError("Restore destination already exists; refusing to overwrite")
    if (
        directory.resolve() == save_destination.resolve()
        or directory.resolve() in save_destination.resolve().parents
    ):
        raise CampaignCheckpointError("Restore destination must be outside the checkpoint")
    shutil.copytree(directory / "game", save_destination, symlinks=True)
    if save_inventory(save_destination) != manifest["payload"]["native_save"]["files"]:
        raise CampaignCheckpointError("Restored save digest mismatch")
    if verify_checkpoint(directory) != manifest:
        raise CampaignCheckpointError("Checkpoint changed during restore")
    return {
        "checkpoint": manifest,
        "agent_state": json.loads(_read_regular(directory / "agent.json")),
        "next_step": manifest["payload"]["next_step"],
        "runtime_loaded": False,
    }
