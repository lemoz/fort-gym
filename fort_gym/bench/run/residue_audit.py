"""Fail-closed, read-only final residue inventory for M1b batches."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .process_supervisor import PortLease, PortLeaseError
from .runtime_controller import MANAGED_LABEL, RUN_ID_LABEL

_RUN_ID_MAX = 128
_MAX_CAPTURE_BYTES = 256 * 1024


class ResidueAuditError(RuntimeError):
    """The final inventory could not establish a bounded result."""


class CommandProbe(Protocol):
    def __call__(self, argv: Sequence[str]) -> tuple[int, str, str]: ...


@dataclass(frozen=True)
class ResidueExpectation:
    """Exact resources owned by one completed batch."""

    run_ids: Sequence[str]
    ports: Sequence[int]
    process_group_ids: Sequence[int] = field(default_factory=tuple)
    mount_paths: Sequence[Path] = field(default_factory=tuple)
    temporary_paths: Sequence[Path] = field(default_factory=tuple)
    retained_evidence_paths: Sequence[Path] = field(default_factory=tuple)
    foreign_process_ids: Sequence[int] = field(default_factory=tuple)
    foreign_container_ids: Sequence[str] = field(default_factory=tuple)
    port_lock_dir: Path = Path("/tmp/fort-gym-port-leases")

    def __post_init__(self) -> None:
        run_ids = tuple(str(value) for value in self.run_ids)
        if not run_ids or len(set(run_ids)) != len(run_ids):
            raise ValueError("run_ids must be a non-empty unique sequence")
        if any(
            not value
            or len(value) > _RUN_ID_MAX
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for character in value
            )
            for value in run_ids
        ):
            raise ValueError("run_ids contain an unsafe identifier")
        ports = tuple(int(value) for value in self.ports)
        if len(ports) != len(run_ids):
            raise ValueError("ports must contain exactly one value per run")
        if len(set(ports)) != len(ports) or any(
            value < 1 or value > 65_535 for value in ports
        ):
            raise ValueError("ports must be unique values in the TCP port range")
        process_groups = tuple(int(value) for value in self.process_group_ids)
        foreign_processes = tuple(int(value) for value in self.foreign_process_ids)
        if len(set(process_groups)) != len(process_groups) or len(
            set(foreign_processes)
        ) != len(foreign_processes):
            raise ValueError("process identities must be unique")
        if any(value <= 1 for value in (*process_groups, *foreign_processes)):
            raise ValueError("process identities must be greater than one")
        object.__setattr__(self, "run_ids", run_ids)
        object.__setattr__(self, "ports", ports)
        object.__setattr__(self, "process_group_ids", process_groups)
        object.__setattr__(self, "foreign_process_ids", foreign_processes)
        for name in (
            "mount_paths",
            "temporary_paths",
            "retained_evidence_paths",
        ):
            paths = tuple(Path(value) for value in getattr(self, name))
            if any(not path.is_absolute() for path in paths):
                raise ValueError(f"{name} must contain absolute paths")
            object.__setattr__(self, name, paths)
        foreign_containers = tuple(str(value) for value in self.foreign_container_ids)
        if len(set(foreign_containers)) != len(foreign_containers) or any(
            not value
            or len(value) > _RUN_ID_MAX
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for character in value
            )
            for value in foreign_containers
        ):
            raise ValueError("foreign container identities must be unique and safe")
        object.__setattr__(self, "foreign_container_ids", foreign_containers)
        lock_dir = Path(self.port_lock_dir)
        if not lock_dir.is_absolute():
            raise ValueError("port_lock_dir must be absolute")
        object.__setattr__(self, "port_lock_dir", lock_dir)


@dataclass(frozen=True)
class ResidueReport:
    ok: bool
    observed_at: str
    residues: Mapping[str, Any]
    foreign_canaries: Mapping[str, Any]
    retained_evidence: Sequence[str]

    def payload(self) -> dict[str, Any]:
        return {
            "schema": "fortgym.m1b-residue-audit/v1",
            "ok": self.ok,
            "observed_at": self.observed_at,
            "residues": dict(self.residues),
            "foreign_canaries": dict(self.foreign_canaries),
            "retained_evidence": list(self.retained_evidence),
        }


class BatchResidueAuditor:
    """Inventory exact managed residue without deleting any resource."""

    def __init__(
        self,
        *,
        command_probe: CommandProbe | None = None,
        process_group_exists: Callable[[int], bool] | None = None,
        process_exists: Callable[[int], bool] | None = None,
        mount_exists: Callable[[Path], bool] = os.path.ismount,
        path_exists: Callable[[Path], bool] = Path.exists,
        lease_available: Callable[[int, Path], bool] | None = None,
    ) -> None:
        self._command_probe = command_probe or _subprocess_probe
        self._process_group_exists = process_group_exists or _process_group_exists
        self._process_exists = process_exists or _process_exists
        self._mount_exists = mount_exists
        self._path_exists = path_exists
        self._lease_available = lease_available or _lease_available

    def audit(self, expected: ResidueExpectation) -> ResidueReport:
        container_residue: dict[str, list[str]] = {}
        probe_errors: list[dict[str, str]] = []
        for run_id in expected.run_ids:
            argv = (
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label={MANAGED_LABEL}=true",
                "--filter",
                f"label={RUN_ID_LABEL}={run_id}",
            )
            returncode, stdout, stderr = self._command_probe(argv)
            if returncode != 0:
                probe_errors.append(
                    {
                        "probe": "containers",
                        "run_id": run_id,
                        "error": _bounded_message(stderr or stdout),
                    }
                )
                continue
            ids = [line.strip() for line in stdout.splitlines() if line.strip()]
            if ids:
                container_residue[run_id] = ids[:32]

        listener_residue: dict[str, list[str]] = {}
        for port in expected.ports:
            returncode, stdout, stderr = self._command_probe(
                ("ss", "-Hlnpt", f"sport = :{port}")
            )
            if returncode != 0:
                probe_errors.append(
                    {
                        "probe": "listeners",
                        "port": str(port),
                        "error": _bounded_message(stderr or stdout),
                    }
                )
                continue
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            if lines:
                listener_residue[str(port)] = lines[:20]

        held_leases = [
            port
            for port in expected.ports
            if not self._lease_available(port, expected.port_lock_dir)
        ]
        live_groups = [
            process_group
            for process_group in expected.process_group_ids
            if self._process_group_exists(process_group)
        ]
        mounted = [
            str(path) for path in expected.mount_paths if self._mount_exists(path)
        ]
        temporary = [
            str(path) for path in expected.temporary_paths if self._path_exists(path)
        ]

        foreign_processes = {
            str(pid): self._process_exists(pid) for pid in expected.foreign_process_ids
        }
        foreign_containers: dict[str, bool] = {}
        for container_id in expected.foreign_container_ids:
            returncode, _stdout, _stderr = self._command_probe(
                ("docker", "inspect", "--type", "container", container_id)
            )
            foreign_containers[container_id] = returncode == 0

        residues = {
            "containers": container_residue,
            "process_groups": live_groups,
            "listeners": listener_residue,
            "leases": held_leases,
            "mounts": mounted,
            "temporary_paths": temporary,
            "probe_errors": probe_errors,
        }
        foreign = {
            "processes": foreign_processes,
            "containers": foreign_containers,
            "all_untouched": all(foreign_processes.values())
            and all(foreign_containers.values()),
        }
        retained = [
            str(path)
            for path in expected.retained_evidence_paths
            if self._path_exists(path)
        ]
        residue_empty = not any(
            (
                container_residue,
                live_groups,
                listener_residue,
                held_leases,
                mounted,
                temporary,
                probe_errors,
            )
        )
        return ResidueReport(
            ok=residue_empty and bool(foreign["all_untouched"]),
            observed_at=_utc_now(),
            residues=residues,
            foreign_canaries=foreign,
            retained_evidence=retained,
        )

    def audit_twice(
        self,
        expected: ResidueExpectation,
        *,
        journal_path: Path | None = None,
    ) -> tuple[ResidueReport, ResidueReport]:
        reports = (self.audit(expected), self.audit(expected))
        if journal_path is not None:
            for index, report in enumerate(reports, start=1):
                _append_report(journal_path, index=index, report=report)
        return reports


def _subprocess_probe(argv: Sequence[str]) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            tuple(argv),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=15.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lease_available(port: int, lock_dir: Path) -> bool:
    try:
        return PortLease.lock_available(port, lock_dir)
    except (OSError, PortLeaseError):
        return False


def _append_report(path: Path, *, index: int, report: ResidueReport) -> None:
    if not path.is_absolute():
        raise ResidueAuditError("journal_path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {**report.payload(), "pass_index": index}
    encoded = (
        json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    if len(encoded) > _MAX_CAPTURE_BYTES:
        raise ResidueAuditError("residue report exceeds evidence size bound")
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short residue journal append")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _bounded_message(value: str) -> str:
    return " ".join(value.split())[:400]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "BatchResidueAuditor",
    "ResidueAuditError",
    "ResidueExpectation",
    "ResidueReport",
]
