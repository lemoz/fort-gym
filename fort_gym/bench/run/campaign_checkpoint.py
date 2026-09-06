"""Bind a completed native save, agent state, and committed trace in one checkpoint.

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
from .campaign_save import NativeSaveSnapshotter, save_inventory


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
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "fortgym.campaign-checkpoint/v1"
    ):
        raise CampaignCheckpointError("Unsupported checkpoint manifest")
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or _digest(_json_bytes(payload)) != manifest.get("sha256"):
        raise CampaignCheckpointError("Checkpoint manifest digest mismatch")
    for name, key in (("agent.json", "agent_sha256"), ("trace.jsonl", "trace_sha256")):
        if _digest(_read_regular(directory / name)) != payload.get(key):
            raise CampaignCheckpointError(f"Checkpoint digest mismatch: {name}")
    receipt = payload.get("native_save")
    if not isinstance(receipt, dict) or save_inventory(directory / "game") != receipt.get("files"):
        raise CampaignCheckpointError("Checkpoint game save digest mismatch")
    return manifest


def create_checkpoint(
    destination: Path,
    *,
    campaign_id: str,
    agent: Agent,
    snapshotter: NativeSaveSnapshotter,
    trace_path: Path,
    last_committed_step: int,
    code_revision: str,
    parent: Path | None = None,
) -> dict[str, Any]:
    """Capture at a paused, committed action boundary with decisions suspended.

    The runner must call after execution and trace fsync, not after model decision.
    The pending action inside agent state is therefore for review, not execution.
    Incomplete destinations are retained for diagnosis without a final manifest.
    """
    if type(last_committed_step) is not int or last_committed_step < 0:
        raise ValueError("last_committed_step must be a nonnegative integer")
    if not campaign_id or not code_revision:
        raise ValueError("Campaign identity and code revision are required")
    state = agent.export_campaign_state()
    if state.get("campaign_id") != campaign_id:
        raise CampaignCheckpointError("Agent belongs to another campaign")
    agent_bytes = _json_bytes(state)
    trace_bytes = _read_regular(trace_path)
    if not trace_bytes.endswith(b"\n"):
        raise CampaignCheckpointError("Trace does not end at a committed newline")
    rows = [json.loads(line) for line in trace_bytes.splitlines() if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise CampaignCheckpointError("Trace has no committed action records")
    run_id = rows[0].get("run_id")
    steps = [row.get("step") for row in rows]
    if (
        not isinstance(run_id, str)
        or not run_id
        or any(row.get("run_id") != run_id for row in rows)
        or any(type(step) is not int for step in steps)
        or steps != list(range(steps[0], last_committed_step + 1))
        or steps[0] not in (0, 1)
    ):
        raise CampaignCheckpointError("Trace cursor or run identity does not match the checkpoint")
    parent_manifest = verify_checkpoint(parent) if parent is not None else None
    if parent_manifest is not None and parent_manifest["payload"].get("campaign_id") != campaign_id:
        raise CampaignCheckpointError("Parent checkpoint belongs to another campaign")
    tick_advance = rows[-1].get("tick_advance")
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
    ):
        raise CampaignCheckpointError("Agent or trace changed during checkpoint capture")
    _write_new(destination / "agent.json", agent_bytes)
    _write_new(destination / "trace.jsonl", trace_bytes)
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
    manifest = {
        "schema_version": "fortgym.campaign-checkpoint/v1",
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
