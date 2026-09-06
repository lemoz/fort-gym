"""Continue one endurance campaign serially across verified native checkpoints.

No strategy, retries of failed segments, invoice inference, or success verdicts.
The segment launcher owns runtime teardown. This controller never creates a VM.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run.campaign_config import ENDURANCE_SCHEMA, load_segment_config
from scripts.campaign_development import append_event
from scripts.campaign_load_smoke import verify_load_source
from scripts.campaign_process import termination_as_interrupt
from scripts.campaign_segment import launch_segment, write_result


def read_record(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Campaign controller requires a regular {path.name}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Campaign controller requires an object in {path.name}")
    return value


def persist(root: Path, record: dict) -> None:
    pending = root / "campaign-run.pending.json"
    # A stale pending file is evidence of an interrupted write, not safe to discard.
    write_result(pending, record)
    os.replace(pending, root / "campaign-run.json")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def inspect_segment(root: Path, record: dict, config: dict) -> tuple[dict, dict | None]:
    """Fixed paths and retained bytes establish the handoff, not child exit status."""
    segment = read_record(root / "campaign-segment.json")
    runtime = read_record(root / "result.json")
    if (
        segment.get("schema_version") != "fortgym.campaign-segment/v1"
        or runtime.get("schema_version") != "fortgym.isolated-experiment-runtime/v1"
        or any(segment.get(key) != record[key] for key in ("campaign_id", "model", "code_revision"))
        or segment.get("configuration") != config
        or segment.get("condition_id") != config["condition_id"]
        or segment.get("segment_id") != root.name
        or runtime.get("code_revision") != record["code_revision"]
        or runtime.get("cleanup_verified") is not True
        or runtime.get("native_load_verified") is not True
    ):
        raise ValueError("Segment identity, native loading or teardown is unverified")
    source_key = (
        "source_snapshot_receipt_sha256"
        if record["segments_completed"] == 0
        else "source_checkpoint_file_sha256"
    )
    expected_source = (
        record["starting_snapshot_sha256"]
        if record["segments_completed"] == 0
        else record["checkpoint_file_sha256"]
    )
    if runtime.get(source_key) != expected_source:
        raise ValueError("Segment loaded a different snapshot or checkpoint")
    checkpoint = None
    if segment.get("new_checkpoint_verified") is True:
        checkpoint_path = root / "checkpoint"
        checkpoint = verify_checkpoint(checkpoint_path)
        payload = checkpoint["payload"]
        agent = read_record(checkpoint_path / "agent.json")
        steps = segment.get("segment_committed_steps")
        if (
            checkpoint["schema_version"] != "fortgym.campaign-checkpoint/v2"
            or payload.get("campaign_id") != record["campaign_id"]
            or payload.get("code_revision") != record["code_revision"]
            or type(steps) is not int
            or steps <= 0
            or segment.get("first_step") != record["next_step"]
            or segment.get("next_step") != record["next_step"] + steps
            or payload.get("next_step") != segment["next_step"]
            or payload.get("parent_sha256") != record.get("checkpoint_payload_sha256")
            or segment.get("checkpoint") != str(checkpoint_path)
            or segment.get("checkpoint_payload_sha256") != checkpoint["sha256"]
            or segment.get("checkpoint_file_sha256")
            != hashlib.sha256((checkpoint_path / "checkpoint.json").read_bytes()).hexdigest()
            or agent.get("usage") != segment.get("usage")
            or (checkpoint_path / "usage.jsonl").read_bytes()
            != (root / "campaign/usage.jsonl").read_bytes()
        ):
            raise ValueError("Segment checkpoint does not establish a contiguous handoff")
    return segment, checkpoint


def budget_reached(usage: dict, config: dict) -> bool:
    return (
        usage["dispatched_requests"] >= config["max_dispatches"]
        or usage["total_tokens"] >= config["max_total_tokens"]
        or Decimal(usage["total_cost_usd"]) >= Decimal(str(config["max_cost_usd"]))
    )


def run_campaign(args, *, launch=launch_segment) -> dict:
    config = load_segment_config(args.config, args.model)
    if config["schema_version"] != ENDURANCE_SCHEMA:
        raise ValueError("Automatic continuation requires a separate endurance condition")
    if not args.campaign_id or len(args.campaign_id) > 128:
        raise ValueError("A bounded campaign identity is required")
    count = args.segments if args.segments is not None else config["max_segments"]
    if type(count) is not int or not 1 <= count <= config["max_segments"]:
        raise ValueError("Invocation segment count exceeds this campaign condition")
    last_port = args.port + config["max_segments"] - 1
    if not 1024 <= args.port <= last_port <= 65535 or args.port <= 5000 <= last_port:
        raise ValueError("Use an unprivileged non-production port range for all segments")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    root = args.output.absolute()
    if root.is_symlink():
        raise ValueError("Campaign output must not be a symlink")
    root = root.resolve()
    if not args.resume:
        if args.snapshot is None or args.snapshot_sha256 is None:
            raise ValueError("A new campaign requires a digest-bound native snapshot")
        verify_load_source(args.snapshot, args.snapshot_sha256, "native_snapshot")
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        (root / "segments").mkdir(mode=0o700)
        write_result(root / "condition.json", config)
        record = {
            "schema_version": "fortgym.campaign-run/v1",
            "campaign_id": args.campaign_id,
            "model": args.model,
            "condition_id": config["condition_id"],
            "code_revision": revision,
            "source_runtime": str(args.source.resolve()),
            "first_port": args.port,
            "starting_snapshot": str(args.snapshot.resolve()),
            "starting_snapshot_sha256": args.snapshot_sha256,
            "segments_started": 0,
            "segments_completed": 0,
            "next_step": 0,
            "checkpoint_payload_sha256": None,
            "checkpoint_file_sha256": None,
            "usage": None,
            "usage_status": "not_started",
            "status": "ready",
            "year_two_gameplay_verified": False,
        }
        persist(root, record)
    lock_fd = os.open(root / ".controller.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = read_record(root / "campaign-run.json")
        if (
            record.get("schema_version") != "fortgym.campaign-run/v1"
            or record.get("campaign_id") != args.campaign_id
            or record.get("model") != args.model
            or record.get("code_revision") != revision
            or record.get("source_runtime") != str(args.source.resolve())
            or record.get("first_port") != args.port
            or read_record(root / "condition.json") != config
        ):
            raise ValueError("Campaign continuation identity changed")
        if record.get("status") not in {"ready", "invocation_limited_pause"}:
            raise ValueError("Campaign requires reconciliation before continuation")
        if record["segments_started"] != record["segments_completed"]:
            raise ValueError("An interrupted segment must be reconciled before continuation")
        if record["segments_completed"]:
            previous = root / "segments" / f"segment-{record['segments_completed']:06d}"
            manifest = verify_checkpoint(previous / "checkpoint")
            if (
                manifest["sha256"] != record["checkpoint_payload_sha256"]
                or hashlib.sha256(
                    (previous / "checkpoint/checkpoint.json").read_bytes()
                ).hexdigest()
                != record["checkpoint_file_sha256"]
                or manifest["payload"]["next_step"] != record["next_step"]
                or read_record(previous / "checkpoint/agent.json")["usage"] != record["usage"]
                or read_record(previous / "result.json").get("cleanup_verified") is not True
                or (previous / "checkpoint/usage.jsonl").read_bytes()
                != (previous / "campaign/usage.jsonl").read_bytes()
            ):
                raise ValueError("Retained continuation boundary or usage has changed")
        for _ in range(count):
            if record["segments_started"] >= config["max_segments"]:
                record["status"] = "segment_limit_pause"
                break
            if record["usage"] is not None and budget_reached(record["usage"], config):
                record["status"] = "budget_limited_pause"
                break
            index = record["segments_started"] + 1
            output = root / "segments" / f"segment-{index:06d}"
            previous = root / "segments" / f"segment-{index - 1:06d}"
            options = SimpleNamespace(
                config=root / "condition.json",
                model=args.model,
                campaign_id=args.campaign_id,
                source=args.source,
                output=output,
                # Native teardown closes the listener, but old TCP connections
                # may remain in TIME_WAIT. Never misread that as a gameplay loss.
                port=args.port + index - 1,
                snapshot=Path(record["starting_snapshot"]) if index == 1 else None,
                snapshot_sha256=record["starting_snapshot_sha256"] if index == 1 else None,
                checkpoint=previous / "checkpoint" if index > 1 else None,
                latest_usage=previous / "campaign/usage.jsonl" if index > 1 else None,
                public_campaign_dir=args.public_campaign_dir,
            )
            record.update(
                status="running",
                segments_started=index,
                usage_status="last_verified_boundary_only"
                if record["usage"] is not None
                else "unknown",
            )
            persist(root, record)
            append_event(root / "controller.jsonl", {"type": "segment_started", "segment": index})
            try:
                launch(options, config)
                segment, checkpoint = inspect_segment(output, record, config)
                record["last_segment_status"] = segment.get("status")
                record["usage"] = segment.get("usage")
                record["usage_status"] = "terminal_segment_reported"
                if checkpoint is not None:
                    record.update(
                        next_step=segment["next_step"],
                        checkpoint_payload_sha256=checkpoint["sha256"],
                        checkpoint_file_sha256=segment["checkpoint_file_sha256"],
                        usage_status="verified_checkpoint_reported",
                    )
                if segment.get("status") == "budget_limited_pause":
                    record["status"] = "budget_limited_pause"
                elif (
                    segment.get("status") != "bounded_segment_complete"
                    or segment.get("recovery_requires_reconciliation") is not False
                    or checkpoint is None
                ):
                    record["status"] = "segment_requires_reconciliation"
                else:
                    record.update(status="ready", segments_completed=index)
            except (Exception, KeyboardInterrupt) as error:
                # The launcher's finally owns teardown. Never infer a safe retry
                # from an exception, missing usage, or an older good checkpoint.
                record.update(status="requires_reconciliation", error_type=type(error).__name__)
            append_event(
                root / "controller.jsonl",
                {
                    "type": "segment_finished",
                    "segment": index,
                    "status": record["status"],
                },
            )
            persist(root, record)
            if record["status"] != "ready":
                break
        if record["status"] == "ready":
            record["status"] = (
                "budget_limited_pause"
                if budget_reached(record["usage"], config)
                else "segment_limit_pause"
                if record["segments_completed"] >= config["max_segments"]
                else "invocation_limited_pause"
            )
        persist(root, record)
        return record
    finally:
        os.close(lock_fd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--segments", type=int, help="Bound this invocation; never reset campaign caps"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5501,
        help="First local RPC port; each successive segment uses the next port",
    )
    parser.add_argument("--public-campaign-dir", type=Path)
    args = parser.parse_args()
    if args.resume and (args.snapshot is not None or args.snapshot_sha256 is not None):
        parser.error("Resume uses the retained campaign boundary, not a new snapshot")
    with termination_as_interrupt():
        print(json.dumps(run_campaign(args), sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
