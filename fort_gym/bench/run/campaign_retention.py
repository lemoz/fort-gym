"""Opt-in periodic snapshots inside one live copied game, without deleting evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from ..agent.governed_llm import GovernedBudgetCapError
from .campaign_checkpoint import verify_checkpoint

PROFILE = "periodic_checkpoints/v1"


def validate_retention(config: dict) -> dict | None:
    policy = config.get("checkpoint_policy")
    if policy is None:
        return None
    if (
        config.get("schema_version") != "fortgym.local-campaign-condition/v1"
        or not isinstance(policy, dict)
        or set(policy) != {"profile", "interval_steps", "minimum_free_bytes"}
        or policy.get("profile") != PROFILE
        or type(policy.get("interval_steps")) is not int
        or not 1 <= policy["interval_steps"] <= 32
        or type(policy.get("minimum_free_bytes")) is not int
        or not 536870912 <= policy["minimum_free_bytes"] <= 8589934592
    ):
        raise ValueError("Invalid local periodic checkpoint policy")
    return policy


def require_disk_space(directory: Path, policy: dict | None) -> None:
    if policy is not None and shutil.disk_usage(directory).free < policy["minimum_free_bytes"]:
        raise GovernedBudgetCapError("Campaign reached its declared free-space floor")


def capture_periodic(loop, snapshotter, output: Path, revision: str) -> dict:
    # Sibling snapshots retain the segment's original parent. The final checkpoint
    # keeps the existing controller handoff contract; no native process is restarted.
    directory = output / "checkpoints"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Periodic checkpoints require a regular directory")
    relative = f"checkpoints/step-{loop.next_step:06d}"
    path = output / relative
    manifest = loop.checkpoint(
        path, snapshotter=snapshotter, code_revision=revision, advance_parent=False
    )
    record = {
        "next_step": loop.next_step,
        "relative_path": relative,
        "payload_sha256": manifest["sha256"],
        "file_sha256": hashlib.sha256((path / "checkpoint.json").read_bytes()).hexdigest(),
    }
    # Retain the index before the next decision, including if no terminal segment
    # record can be written after a later process interruption.
    descriptor = os.open(
        output / "periodic-checkpoints.jsonl",
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return record


def verify_periodic(root: Path, segment: dict, config: dict, parent: str | None) -> None:
    """Verify fixed paths and coverage before accepting a terminal segment handoff."""
    policy = validate_retention(config)
    entries = segment.get("periodic_checkpoints", [])
    if policy is None:
        if entries:
            raise ValueError("Undeclared periodic checkpoints")
        return
    if not isinstance(entries, list) or len(entries) > config["max_steps"]:
        raise ValueError("Invalid periodic checkpoint inventory")
    index_path = root / "periodic-checkpoints.jsonl"
    if index_path.exists() or index_path.is_symlink():
        if index_path.is_symlink() or not index_path.is_file() or index_path.stat().st_size > 65536:
            raise ValueError("Periodic checkpoint index must be a bounded regular file")
        raw_index = index_path.read_bytes()
        if (
            not raw_index.endswith(b"\n")
            or [json.loads(line) for line in raw_index.splitlines()] != entries
        ):
            raise ValueError("Periodic checkpoint index differs from the terminal inventory")
    elif entries:
        raise ValueError("Periodic checkpoint index is missing")
    first, end = segment.get("first_step"), segment.get("next_step")
    if type(first) is not int or type(end) is not int or end < first:
        raise ValueError("Periodic checkpoint cursor is invalid")
    previous_trace = b""
    previous_usage = b""
    final_agent = json.loads((root / "agent-final.json").read_bytes())
    for index, entry in enumerate(entries, start=1):
        step = first + policy["interval_steps"] * index
        relative = f"checkpoints/step-{step:06d}"
        if (
            not isinstance(entry, dict)
            or set(entry) != {"next_step", "relative_path", "payload_sha256", "file_sha256"}
            or type(entry["next_step"]) is not int
            or entry["next_step"] != step
            or entry["relative_path"] != relative
            or step > end
        ):
            raise ValueError("Periodic checkpoint sequence differs from its policy")
        path = root / relative
        if (root / "checkpoints").is_symlink():
            raise ValueError("Periodic checkpoint directory is a symlink")
        manifest = verify_checkpoint(path)
        payload = manifest["payload"]
        state = json.loads((path / "agent.json").read_bytes())
        trace = (path / "trace.jsonl").read_bytes()
        usage = (path / "usage.jsonl").read_bytes()
        rows = [json.loads(line) for line in trace.splitlines()]
        journal = [json.loads(line) for line in usage.splitlines()]
        if (
            manifest["schema_version"] != "fortgym.campaign-checkpoint/v2"
            or manifest["sha256"] != entry["payload_sha256"]
            or hashlib.sha256((path / "checkpoint.json").read_bytes()).hexdigest()
            != entry["file_sha256"]
            or payload.get("next_step") != step
            or payload.get("campaign_id") != segment["campaign_id"]
            or payload.get("code_revision") != segment["code_revision"]
            or payload.get("parent_sha256") != parent
            or state.get("campaign_id") != segment["campaign_id"]
            or state.get("configuration") != final_agent.get("configuration")
            or not rows
            or rows[-1].get("step") != step - 1
            or (payload["native_save"]["year"], payload["native_save"]["year_tick"])
            != (rows[-1]["tick_advance"]["end_year"], rows[-1]["tick_advance"]["end_tick"])
            or not journal
            or journal[-1].get("type") != "decision_finished"
            or journal[-1].get("decision_returned") is not True
            or journal[-1].get("usage") != state.get("usage")
            or not trace.startswith(previous_trace)
            or not usage.startswith(previous_usage)
            or not (root / "campaign/trace.jsonl").read_bytes().startswith(trace)
            or not (root / "campaign/usage.jsonl").read_bytes().startswith(usage)
        ):
            raise ValueError("Periodic checkpoint identity or retained prefix differs")
        previous_trace, previous_usage = trace, usage
    if segment.get("new_checkpoint_verified") is True:
        # A complete final snapshot replaces a periodic snapshot at that same cursor.
        expected = list(range(first + policy["interval_steps"], end, policy["interval_steps"]))
        actual = [entry["next_step"] for entry in entries]
        if actual not in (expected, expected + [end] if end > first else expected):
            raise ValueError("Periodic checkpoint coverage has a gap")
