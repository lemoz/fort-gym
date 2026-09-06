"""Opt-in public campaign summaries, kept outside private gameplay artifacts.

The worker reports committed boundaries; the parent reports terminal state only
after runtime teardown. Readers see atomic snapshots and explicit freshness, not
a claim that a recently reporting process is still alive. No raw model/game text
is accepted by this projection.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..eval.campaign import TICKS_PER_YEAR
from ..eval.campaign_profile import METRICS, mapping, metrics_from_state
from ..eval.campaign_public import SCHEMA, now_utc, parse_update_time, public_snapshot

MARKER = ".fortgym-public-campaign-feed.json"
MARKER_VALUE = {"schema_version": "fortgym.public-campaign-feed/v1"}
MAX_BYTES = 512_000
MAX_RECORDS = 128
STALE_SECONDS = 300


def _read(path: Path, maximum: int = MAX_BYTES) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("Public campaign inputs must be bounded regular files")
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Public campaign input exceeds its bound")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Public campaign input must be an object")
    return value


def validate_root(root: Path) -> None:
    if root.is_symlink() or not root.is_dir() or _read(root / MARKER, 1024) != MARKER_VALUE:
        raise ValueError("Campaign feed is not an explicitly initialized public directory")


def initialize_feed(root: Path) -> None:
    if root.is_symlink():
        raise ValueError("Campaign public directory cannot be a symlink")
    root.mkdir(mode=0o755, exist_ok=True)
    marker = root / MARKER
    if not marker.exists():
        if any(root.iterdir()):
            raise ValueError("Use an empty dedicated public campaign directory")
        with marker.open("x") as stream:
            json.dump(MARKER_VALUE, stream)
    validate_root(root)


class CampaignFeed:
    def __init__(
        self,
        root: Path,
        *,
        campaign_id: str,
        segment_id: str,
        model: str,
        config: dict,
        revision: str,
    ):
        validate_root(root)
        self.root = root
        self.identity = {
            "schema_version": SCHEMA,
            "campaign_id": campaign_id,
            "segment_id": segment_id,
            "model": model,
            "condition_id": config["condition_id"],
            "code_revision": revision,
            "configuration_sha256": hashlib.sha256(
                json.dumps(config, sort_keys=True, allow_nan=False).encode()
            ).hexdigest(),
        }
        key = hashlib.sha256(campaign_id.encode()).hexdigest()
        self.path = root / f"campaign-{key}.json"

    @contextmanager
    def _lock(self):
        validate_root(self.root)
        descriptor = os.open(
            self.path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "a+") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def _write(self, value: dict, *, archive: bool = False) -> None:
        with self._lock():
            self._write_locked(value, archive=archive)

    def _write_locked(
        self, value: dict, *, archive: bool = False, new_segment: bool = False
    ) -> None:
        validate_root(self.root)
        if self.path.exists():
            current = public_snapshot(_read(self.path))
            if any(
                current[key] != self.identity[key]
                for key in ("campaign_id", "model", "condition_id", "configuration_sha256")
            ) or (
                not new_segment
                and any(
                    current[key] != self.identity[key] for key in ("segment_id", "code_revision")
                )
            ):
                raise ValueError("A different campaign segment owns the current public report")
        data = json.dumps(
            public_snapshot({**value, **self.identity, "updated_at": now_utc()}), allow_nan=False
        ).encode()
        if len(data) > MAX_BYTES or self.path.is_symlink():
            raise ValueError("Invalid public campaign destination or size")
        # This temporary contains only the already-projected public record.
        with tempfile.NamedTemporaryFile(
            dir=self.root, prefix=".campaign-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.chmod(0o644)
            if archive:
                directory = self.root / "recorded"
                if directory.is_symlink():
                    raise ValueError("Recorded campaign directory cannot be a symlink")
                directory.mkdir(mode=0o755, exist_ok=True)
                key = hashlib.sha256(
                    json.dumps([self.identity["campaign_id"], self.identity["segment_id"]]).encode()
                ).hexdigest()
                with (directory / f"{key}.json").open("xb") as record:
                    record.write(data)
                    record.flush()
                    os.fsync(record.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def start(self, *, resume: bool = False) -> None:
        with self._lock():
            if self.path.exists() or self.path.is_symlink():
                previous = public_snapshot(_read(self.path))
                if (
                    not resume
                    or previous["segment_id"] == self.identity["segment_id"]
                    or any(
                        previous[key] != self.identity[key]
                        for key in ("campaign_id", "model", "condition_id", "configuration_sha256")
                    )
                ):
                    raise ValueError(
                        "Existing public campaign requires a matching new continuation"
                    )
            self._write_locked(
                {"lifecycle": "starting", "segment_status": "started"}, new_segment=resume
            )

    def progress(self, result: dict, loop, state: dict | None) -> None:
        self._write(
            {
                "lifecycle": "running" if result["status"] == "started" else "awaiting_teardown",
                "segment_status": result["status"],
                "committed_steps": loop.next_step if loop is not None else None,
                "elapsed_ticks": loop.committed_elapsed_ticks if loop is not None else None,
                "current_metrics": metrics_from_state(state),
                "usage": result.get("usage"),
                "checkpoint_verified": result.get("new_checkpoint_verified"),
                "failure_kind": failure_kind(result),
            }
        )

    def finish(self, output: Path, report: dict | None) -> None:
        previous = public_snapshot(_read(self.path)) if self.path.exists() else {}
        runtime = _read(output / "result.json") if (output / "result.json").exists() else {}
        if runtime and (
            runtime.get("schema_version") != "fortgym.isolated-experiment-runtime/v1"
            or runtime.get("code_revision") != self.identity["code_revision"]
        ):
            raise ValueError("Terminal runtime does not match the published campaign")
        update = {
            **previous,
            "lifecycle": "finished"
            if runtime.get("cleanup_verified") is True
            else "awaiting_teardown",
            "segment_status": "failed",
            "current_metrics": {},
            "metric_summaries": {},
            "timeline": [],
            "actions": {},
            "usage": {},
            "failure_kind": "runtime" if runtime.get("error_type") else "unclassified",
            "cleanup_verified": runtime.get("cleanup_verified"),
        }
        if report is not None:
            if any(
                report.get(key) != self.identity[key]
                for key in (
                    "campaign_id",
                    "segment_id",
                    "model",
                    "condition_id",
                    "code_revision",
                    "configuration_sha256",
                )
            ):
                raise ValueError("Terminal profile does not match the published campaign")
            update.update(
                segment_status=report["segment_status"],
                committed_steps=mapping(report.get("actions")).get("committed_rows"),
                elapsed_ticks=mapping(report.get("progress")).get("elapsed_ticks"),
                current_metrics={
                    key: mapping(mapping(report.get("metrics")).get(key)).get("end")
                    for key in METRICS
                },
                metric_summaries=report.get("metrics"),
                timeline=report.get("timeline"),
                actions=report.get("actions"),
                usage=report.get("usage"),
                checkpoint_verified=report.get("new_checkpoint_verified"),
                source_sha256=report.get("source_sha256"),
            )
            segment = _read(output / "campaign-segment.json")
            update["failure_kind"] = failure_kind(segment)
        self._write(update, archive=True)


def read_feed(root: Path | None, *, now: datetime | None = None) -> dict:
    response: dict[str, Any] = {
        "schema_version": "fortgym.public-campaign-feed/v1",
        "configured": root is not None,
        "campaigns": [],
        "ticks_per_year": TICKS_PER_YEAR,
        "comparison_rankings_available": False,
    }
    if root is None:
        return response
    validate_root(root)
    files = sorted(root.glob("campaign-*.json"))
    if len(files) > MAX_RECORDS:
        raise ValueError("Public campaign feed exceeds its record bound")
    current = now or datetime.now(timezone.utc)
    records = []
    for path in files:
        record = public_snapshot(_read(path))
        expected = hashlib.sha256(record["campaign_id"].encode()).hexdigest()
        if path.name != f"campaign-{expected}.json":
            raise ValueError("Public campaign filename and identity disagree")
        age = (current - parse_update_time(record["updated_at"])).total_seconds()
        record["update_age_seconds"] = max(0, int(age))
        record["freshness"] = (
            "clock_mismatch"
            if age < -5
            else "stale"
            if age > STALE_SECONDS and record["lifecycle"] != "finished"
            else "recorded"
            if record["lifecycle"] == "finished"
            else "recent_report"
        )
        records.append(record)
    response["campaigns"] = sorted(records, key=lambda item: item["updated_at"], reverse=True)
    return response


def failure_kind(result: dict) -> str:
    if result.get("status") == "checkpoint_failed":
        return "checkpoint"
    if result.get("status") != "failed":
        return "none"
    code = result.get("terminal_code")
    if code == "campaign_invalid_action":
        return "model_action"
    if code == "campaign_local_inference_error" or (
        isinstance(code, str) and code.startswith("provider_")
    ):
        return "provider"
    return "unclassified"
