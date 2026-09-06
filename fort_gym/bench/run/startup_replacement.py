"""Append-only policy and evidence for bounded pre-harness replacements.

This module does not launch runtimes.  It owns the small durable ledger that
prevents a startup failure from becoming an unbounded retry loop.  Deliberate
test-injector reruns are accounted separately from natural replacements, as
required by the frozen M1b acceptance contract.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SCHEMA = "fortgym.m1b-startup-replacement/v1"
_MAX_RECORD_BYTES = 32_768
_MAX_RECORDS = 256
_RESERVED_RECORD_KEYS = frozenset({"schema", "packet_id", "sequence", "at", "event"})

ALLOWED_NATURAL_STARTUP_CODES = frozenset(
    {
        "container_create_failure",
        "rpc_readiness_timeout",
        "map_readiness_timeout",
    }
)
MAXIMUM_PER_LOGICAL_RUN = 1
MAXIMUM_NATURAL_STARTUP_REPLACEMENTS_PACKET = 2
MAXIMUM_NATURAL_STARTUP_REPLACEMENTS_CO8 = 1
TEST_INJECTOR_INVALID_RERUNS = 1


class StartupReplacementError(RuntimeError):
    """Base error for replacement policy or durable evidence failures."""


class StartupReplacementDenied(StartupReplacementError):
    """The observed attempt is not eligible for the requested retry kind."""


class StartupReplacementEvidenceError(StartupReplacementError):
    """The append-only replacement ledger is malformed or contradictory."""


@dataclass(frozen=True)
class ReplacementAuthorization:
    """One durably recorded permission to create a fresh attempt."""

    kind: str
    logical_run_id: str
    source_run_id: str
    terminal_code: str
    sequence: int


class StartupReplacementLedger:
    """Bounded append-only ledger for one acceptance packet."""

    def __init__(self, path: Path | str, *, packet_id: str, cohort_size: int) -> None:
        self.path = Path(path)
        if not self.path.is_absolute() or "\0" in str(self.path):
            raise ValueError("replacement ledger path must be absolute and NUL-free")
        if not _ID_RE.fullmatch(packet_id):
            raise ValueError("packet_id must be a bounded safe identifier")
        if (
            isinstance(cohort_size, bool)
            or not isinstance(cohort_size, int)
            or not 1 <= cohort_size <= 64
        ):
            raise ValueError("cohort_size must be an integer from 1 through 64")
        self.packet_id = packet_id
        self.cohort_size = cohort_size
        self._lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")

    def records(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        if len(lines) > _MAX_RECORDS:
            raise StartupReplacementEvidenceError("replacement ledger is oversized")
        records: list[dict[str, Any]] = []
        for sequence, line in enumerate(lines, start=1):
            if not line or len(line.encode("utf-8")) > _MAX_RECORD_BYTES:
                raise StartupReplacementEvidenceError(
                    "replacement ledger contains an invalid record size"
                )
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StartupReplacementEvidenceError(
                    "replacement ledger contains invalid JSON"
                ) from exc
            if (
                not isinstance(record, dict)
                or record.get("schema") != _SCHEMA
                or record.get("packet_id") != self.packet_id
                or record.get("sequence") != sequence
                or not isinstance(record.get("event"), str)
            ):
                raise StartupReplacementEvidenceError(
                    "replacement ledger identity or sequence differs"
                )
            records.append(record)
        return records

    def append(self, _event: str, **fields: Any) -> dict[str, Any]:
        if not _ID_RE.fullmatch(_event):
            raise ValueError("replacement event must be a bounded safe identifier")
        collisions = _RESERVED_RECORD_KEYS.intersection(fields)
        if collisions:
            raise ValueError(
                "replacement fields collide with reserved identity keys: "
                + ", ".join(sorted(collisions))
            )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            records = self.records()
            return self._append_locked(records, event=_event, fields=fields)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def authorize(
        self,
        *,
        kind: str,
        logical_run_id: str,
        source_run_id: str,
        terminal_code: str,
        injected: bool,
        harness_started: bool,
        cleanup_verified: bool,
    ) -> ReplacementAuthorization:
        if not _ID_RE.fullmatch(logical_run_id) or not _ID_RE.fullmatch(source_run_id):
            raise StartupReplacementDenied("replacement run identity is invalid")
        if not isinstance(injected, bool) or not isinstance(harness_started, bool):
            raise StartupReplacementDenied("replacement evidence booleans are invalid")
        if not isinstance(cleanup_verified, bool):
            raise StartupReplacementDenied("cleanup evidence boolean is invalid")
        if not cleanup_verified:
            raise StartupReplacementDenied("replacement requires verified cleanup")
        if harness_started:
            raise StartupReplacementDenied(
                "replacement is forbidden after the harness has started"
            )

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            records = self.records()
            authorizations = [
                row for row in records if row.get("event") == "replacement_authorized"
            ]
            logical = [
                row
                for row in authorizations
                if row.get("logical_run_id") == logical_run_id
            ]
            if kind == "natural_startup":
                if injected:
                    raise StartupReplacementDenied(
                        "injected faults cannot consume natural replacement budget"
                    )
                if terminal_code not in ALLOWED_NATURAL_STARTUP_CODES:
                    raise StartupReplacementDenied(
                        "terminal code is not eligible for startup replacement"
                    )
                natural_packet = [
                    row
                    for row in authorizations
                    if row.get("kind") == "natural_startup"
                ]
                natural_logical = [
                    row for row in logical if row.get("kind") == "natural_startup"
                ]
                packet_cap = (
                    MAXIMUM_NATURAL_STARTUP_REPLACEMENTS_CO8
                    if self.cohort_size >= 8
                    else MAXIMUM_NATURAL_STARTUP_REPLACEMENTS_PACKET
                )
                if len(natural_logical) >= MAXIMUM_PER_LOGICAL_RUN:
                    raise StartupReplacementDenied(
                        "logical run exhausted its natural replacement cap"
                    )
                if len(natural_packet) >= packet_cap:
                    raise StartupReplacementDenied(
                        "acceptance packet exhausted its natural replacement cap"
                    )
            elif kind == "test_injector_invalid_rerun":
                if not injected or terminal_code != "rpc_readiness_timeout":
                    raise StartupReplacementDenied(
                        "test-injector rerun requires an injected RPC readiness timeout"
                    )
                injected_logical = [
                    row
                    for row in logical
                    if row.get("kind") == "test_injector_invalid_rerun"
                ]
                if len(injected_logical) >= TEST_INJECTOR_INVALID_RERUNS:
                    raise StartupReplacementDenied(
                        "logical run exhausted its test-injector rerun cap"
                    )
            else:
                raise StartupReplacementDenied("replacement kind is unsupported")

            record = self._append_locked(
                records,
                event="replacement_authorized",
                fields={
                    "kind": kind,
                    "logical_run_id": logical_run_id,
                    "source_run_id": source_run_id,
                    "terminal_code": terminal_code,
                    "injected": injected,
                },
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        return ReplacementAuthorization(
            kind=kind,
            logical_run_id=logical_run_id,
            source_run_id=source_run_id,
            terminal_code=terminal_code,
            sequence=int(record["sequence"]),
        )

    def _append_locked(
        self,
        records: list[dict[str, Any]],
        *,
        event: str,
        fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one record while the caller holds the ledger flock."""

        if len(records) >= _MAX_RECORDS:
            raise StartupReplacementEvidenceError(
                "replacement ledger reached its record cap"
            )
        safe_fields = _json_safe(fields)
        assert isinstance(safe_fields, dict)
        record = {
            **safe_fields,
            "schema": _SCHEMA,
            "packet_id": self.packet_id,
            "sequence": len(records) + 1,
            "at": datetime.now(UTC).isoformat(),
            "event": event,
        }
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise StartupReplacementEvidenceError(
                "replacement ledger record exceeds its byte cap"
            )
        journal_fd = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            if os.write(journal_fd, encoded) != len(encoded):
                raise OSError("short replacement ledger append")
            os.fsync(journal_fd)
        finally:
            os.close(journal_fd)
        directory_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return record


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"replacement evidence is not JSON-safe: {type(value).__name__}")


__all__ = [
    "ALLOWED_NATURAL_STARTUP_CODES",
    "MAXIMUM_NATURAL_STARTUP_REPLACEMENTS_CO8",
    "MAXIMUM_NATURAL_STARTUP_REPLACEMENTS_PACKET",
    "MAXIMUM_PER_LOGICAL_RUN",
    "TEST_INJECTOR_INVALID_RERUNS",
    "ReplacementAuthorization",
    "StartupReplacementDenied",
    "StartupReplacementError",
    "StartupReplacementEvidenceError",
    "StartupReplacementLedger",
]
