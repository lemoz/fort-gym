"""Fail-closed host-side fault injection for the frozen M1b gates.

The driver is deliberately separate from the normal runtime controller.  A
fault can be attempted only with an opaque, single-use capability minted for
one exact gate and one exact target/peer pair.  Ambient environment variables,
serialized configuration, and ordinary production-mode arguments cannot
enable it.

Every external command is an argument vector executed with ``shell=False``.
The only Docker-daemon restart seam is an injected *host-controller* callback;
this module never tries to restart Docker from a container.  The driver records
observations but never assigns a terminal class.  After cleanup, the runtime
controller may load a completed record and pass its strictly validated
``classifier_evidence`` to :mod:`fault_classification`.  Missing or incomplete
driver evidence means explicit no-classification.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from .fault_classification import MAX_WORKSPACE_FAULT_BYTES

FAULT_DRIVER_OBSERVATION_SCHEMA = "fortgym.m1b-fault-driver-observation/v1"
STEP2_BARRIER_SCHEMA = "fortgym.m1b-step2-barrier/v1"
COHORT_START_SCHEMA = "fortgym.m1b-cohort-start/v1"
RUN_OWNERSHIP_SCHEMA = "fortgym.m1b-run-ownership/v1"
FAULT_STATE_SCHEMA = "fortgym.m1b-fault-state/v1"
CANARY_OBSERVATION_SCHEMA = "fortgym.m1b-canary-observation/v1"
DAEMON_RESTART_CALLBACK_SCHEMA = "fortgym.m1b-daemon-restart-callback/v1"
WORKSPACE_OWNER_SCHEMA = "fortgym.m1b-workspace-owner/v1"
TMPFS_LIFECYCLE_SCHEMA = "fortgym.m1b-private-tmpfs/v1"
WORKSPACE_FAULT_PROFILE_SCHEMA = "fortgym.m1b-workspace-fault-profile/v1"
PRELAUNCH_ENOSPC_TARGET_SCHEMA = "fortgym.m1b-prelaunch-enospc-target/v1"
PRELAUNCH_ENOSPC_RECEIPT_SCHEMA = "fortgym.m1b-prelaunch-enospc-workspace/v1"
PRE_READINESS_OOM_ARM_SCHEMA = "fortgym.m1b-pre-readiness-oom-monitor-arm/v1"
PRE_READINESS_OOM_FINALIZE_SCHEMA = "fortgym.m1b-pre-readiness-oom-monitor-finalize/v1"
PRE_READINESS_OOM_STATE_SCHEMA = "fortgym.m1b-pre-readiness-oom-state/v1"

_DOCKER = "/usr/bin/docker"
_KILL = "/bin/kill"
_OOM_MEMORY_BYTES = 256 * 1024 * 1024
_NORMAL_MEMORY_BYTES = 4 * 1024 * 1024 * 1024
_OOM_FAULT_PROFILE = "oom_256m"
_ENOSPC_WORKSPACE_PROFILE = "enospc_16m"
_NORMAL_WORKSPACE_PROFILE = "normal_workspace"
_DEFAULT_RUNTIME_READINESS_SECONDS = 330.0
_ENOSPC_FILL_PROGRAM = """\
import errno,json,os,sys
path=sys.argv[1]
limit=int(sys.argv[2])
written=0
observed=0
fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
try:
    chunk=b'\\0'*1048576
    while written<limit:
        try:
            count=os.write(fd,chunk[:min(len(chunk),limit-written)])
            if count<=0:
                raise OSError('short write')
            written+=count
        except OSError as exc:
            observed=int(exc.errno or 0)
            break
    try:
        os.fsync(fd)
    except OSError as exc:
        observed=observed or int(exc.errno or 0)
finally:
    os.close(fd)
print(json.dumps({'errno':observed,'fault_bytes':written,'maximum_fault_bytes':limit},sort_keys=True,separators=(',',':')))
raise SystemExit(0 if observed==errno.ENOSPC else 3)
"""
_MAX_CAPTURE_BYTES = 64 * 1024
_MAX_RECORD_BYTES = 128 * 1024
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_NONCE_RE = re.compile(r"^[a-f0-9]{32,64}$")
_CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_PROCESS_SUPERVISOR_TERMINAL_CLASSES = frozenset(
    {
        "completed",
        "child_exit",
        "port_policy_failure",
        "prepare_failure",
        "external_signal",
        "cap_trip",
        "provider_pin_violation",
        "timeout",
        "cleanup_failure",
        "runtime_df_killed",
        "harness_killed",
        "runtime_oom",
        "workspace_enospc",
        "runtime_container_restarted",
        "docker_daemon_restarted",
        "runtime_fault_classification_failure",
    }
)
_AUTH_SENTINEL = object()


class FaultDriverError(RuntimeError):
    """Base class for bounded M1b fault-driver failures."""


class FaultAuthorizationError(FaultDriverError):
    """Fault injection was not explicitly authorized for this exact attempt."""


class FaultEvidenceError(FaultDriverError):
    """Durable barrier, ownership, or fault evidence is invalid."""


class FaultActionError(FaultDriverError):
    """The exact fault action could not be attempted safely."""


class FaultEvidenceTimeout(FaultDriverError):
    """A required explicit observation never became available."""


class OwnedRunEvidencePending(FaultEvidenceError):
    """Settled control evidence for a live post-readiness run is not present yet."""


class FaultGate(str, Enum):
    """The six destructive M1b fault gates controlled by this driver."""

    DF_KILL = "DF-KILL"
    HARNESS_KILL = "HARNESS-KILL"
    OOM = "OOM"
    ENOSPC = "ENOSPC"
    CONTAINER_RESTART = "CONTAINER-RESTART"
    DAEMON_RESTART = "DAEMON-RESTART"


_CLASSIFIER_EVIDENCE_SCHEMA = "fortgym.m1b-fault-driver-classifier-evidence/v1"


@dataclass(frozen=True)
class OwnedRun:
    """Exact durable identity the host controller expects for one live run."""

    run_id: str
    contract_sha256: str
    nonce: str
    cohort_sha256: str
    container_id: str
    runtime_host_pid: int
    runtime_container_pid: int
    runtime_cgroup_path: str
    harness_pid: int
    harness_process_group_id: int
    supervisor_pid: int
    db_path: Path
    workspace: Path
    control_root: Path

    def __post_init__(self) -> None:
        if not _RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        for name in ("contract_sha256", "cohort_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if not isinstance(self.nonce, str) or not _NONCE_RE.fullmatch(self.nonce):
            raise ValueError("nonce must be 128-256 bits encoded as lowercase hex")
        if not isinstance(self.container_id, str) or not _CONTAINER_ID_RE.fullmatch(
            self.container_id
        ):
            raise ValueError("container_id must be a lowercase Docker identifier")
        for name in (
            "runtime_host_pid",
            "runtime_container_pid",
            "harness_pid",
            "harness_process_group_id",
            "supervisor_pid",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 1:
                raise ValueError(f"{name} must be an integer greater than one")
        cgroup_path = _bounded_string(
            self.runtime_cgroup_path, "runtime_cgroup_path", maximum=512
        )
        if not cgroup_path.startswith("/") or ".." in Path(cgroup_path).parts:
            raise ValueError("runtime_cgroup_path must be an absolute safe cgroup path")
        object.__setattr__(self, "runtime_cgroup_path", cgroup_path)
        db_path = _absolute_path("db_path", self.db_path).resolve(strict=False)
        workspace = _absolute_path("workspace", self.workspace).resolve(strict=False)
        control_root = _absolute_path("control_root", self.control_root).resolve(
            strict=False
        )
        if workspace == Path(workspace.anchor) or control_root == Path(
            control_root.anchor
        ):
            raise ValueError("workspace and control_root cannot be filesystem roots")
        object.__setattr__(self, "db_path", db_path)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "control_root", control_root)

    def public_identity(self) -> dict[str, Any]:
        """Return a secret-free identity suitable for durable evidence."""

        return {
            "run_id": self.run_id,
            "contract_sha256": self.contract_sha256,
            "nonce_sha256": _nonce_sha256(self.nonce),
            "cohort_sha256": self.cohort_sha256,
            "container_id": self.container_id,
            "runtime_host_pid": self.runtime_host_pid,
            "runtime_container_pid": self.runtime_container_pid,
            "runtime_cgroup_path": self.runtime_cgroup_path,
            "harness_pid": self.harness_pid,
            "harness_process_group_id": self.harness_process_group_id,
            "supervisor_pid": self.supervisor_pid,
            "db_path": str(self.db_path),
            "workspace": str(self.workspace),
        }


@dataclass(frozen=True)
class PreReadinessOomTarget:
    """Canonical target identity available before a harness can be launched.

    A 256 MiB target may OOM inside ``RuntimeController.prepare()``.  It
    therefore cannot honestly carry a ProcessSupervisor child PID.  The
    monitor binds this launch identity to the controller's exact
    ``container-created`` receipt during :meth:`PreReadinessOomMonitor.arm`.
    """

    run_id: str
    contract_sha256: str
    nonce: str
    cohort_sha256: str
    container_name: str
    db_path: Path
    workspace: Path
    control_root: Path

    def __post_init__(self) -> None:
        if not _RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        if not _SHA256_RE.fullmatch(self.contract_sha256):
            raise ValueError("contract_sha256 must be a lowercase SHA-256")
        if not _NONCE_RE.fullmatch(self.nonce):
            raise ValueError("nonce must be 128-256 bits encoded as lowercase hex")
        if not _SHA256_RE.fullmatch(self.cohort_sha256):
            raise ValueError("cohort_sha256 must be a lowercase SHA-256")
        expected_name = f"fortgym-m1b-{self.run_id}-{self.contract_sha256[:12]}"
        if self.container_name != expected_name:
            raise ValueError("pre-readiness OOM container name is noncanonical")
        db_path = _absolute_path("db_path", self.db_path).resolve(strict=False)
        workspace = _absolute_path("workspace", self.workspace).resolve(strict=False)
        control_root = _absolute_path("control_root", self.control_root).resolve(
            strict=False
        )
        if (
            workspace == Path(workspace.anchor)
            or control_root == Path(control_root.anchor)
            or _paths_overlap(workspace, control_root)
        ):
            raise ValueError("OOM workspace and control root must be safe and disjoint")
        object.__setattr__(self, "db_path", db_path)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "control_root", control_root)

    def public_identity(
        self,
        *,
        container_id: str,
        container_init_host_pid: int,
        container_cgroup_path: str,
    ) -> dict[str, Any]:
        return {
            "identity_kind": "pre_readiness_oom",
            "run_id": self.run_id,
            "contract_sha256": self.contract_sha256,
            "nonce_sha256": _nonce_sha256(self.nonce),
            "cohort_sha256": self.cohort_sha256,
            "container_name": self.container_name,
            "container_id": container_id,
            "container_init_host_pid": container_init_host_pid,
            "container_cgroup_path": container_cgroup_path,
            "db_path": str(self.db_path),
            "workspace": str(self.workspace),
        }


@dataclass(frozen=True)
class PrelaunchEnospcTarget:
    """Canonical ENOSPC workspace identity before any artifact file is opened."""

    run_id: str
    contract_sha256: str
    nonce: str
    cohort_sha256: str
    peer_run_id: str
    db_path: Path
    workspace: Path
    control_root: Path

    def __post_init__(self) -> None:
        if not _RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        if (
            not _RUN_ID_RE.fullmatch(self.peer_run_id)
            or self.peer_run_id == self.run_id
        ):
            raise ValueError("peer_run_id must identify one distinct bounded run")
        if not _SHA256_RE.fullmatch(self.contract_sha256):
            raise ValueError("contract_sha256 must be a lowercase SHA-256")
        if not _NONCE_RE.fullmatch(self.nonce):
            raise ValueError("nonce must be 128-256 bits encoded as lowercase hex")
        if not _SHA256_RE.fullmatch(self.cohort_sha256):
            raise ValueError("cohort_sha256 must be a lowercase SHA-256")
        db_path = _absolute_path("db_path", self.db_path).resolve(strict=False)
        workspace = _absolute_path("workspace", self.workspace).resolve(strict=False)
        control_root = _absolute_path("control_root", self.control_root).resolve(
            strict=False
        )
        if (
            workspace == Path(workspace.anchor)
            or control_root == Path(control_root.anchor)
            or _paths_overlap(workspace, control_root)
        ):
            raise ValueError(
                "ENOSPC workspace and control root must be safe and disjoint"
            )
        object.__setattr__(self, "db_path", db_path)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "control_root", control_root)

    def public_identity(self) -> dict[str, Any]:
        return {
            "schema": PRELAUNCH_ENOSPC_TARGET_SCHEMA,
            "run_id": self.run_id,
            "contract_sha256": self.contract_sha256,
            "nonce_sha256": _nonce_sha256(self.nonce),
            "cohort_sha256": self.cohort_sha256,
            "peer_run_id": self.peer_run_id,
            "db_path": str(self.db_path),
            "workspace": str(self.workspace),
        }


@dataclass(frozen=True)
class EnospcWorkspaceCleanupTarget(PrelaunchEnospcTarget):
    """Durably reconstructed ENOSPC mount identity after child-group reaping."""

    cleanup_mode: str
    harness_process_group_id: int | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.cleanup_mode not in {"pre_child_abort", "post_child_cleanup"}:
            raise ValueError("cleanup_mode is invalid")
        if self.cleanup_mode == "pre_child_abort":
            if self.harness_process_group_id is not None:
                raise ValueError("pre-child cleanup cannot carry a process group")
        elif (
            isinstance(self.harness_process_group_id, bool)
            or not isinstance(self.harness_process_group_id, int)
            or self.harness_process_group_id <= 1
        ):
            raise ValueError("post-child process group must be greater than one")


@dataclass(frozen=True)
class ProtectedCanary:
    """A foreign resource whose identity must remain unchanged."""

    name: str
    container_id: str
    process_ids: Sequence[int]
    workspace: Path

    def __post_init__(self) -> None:
        name = _bounded_string(self.name, "canary name", maximum=128)
        if not _RUN_ID_RE.fullmatch(name):
            raise ValueError("canary name must be filesystem-safe")
        if not _CONTAINER_ID_RE.fullmatch(self.container_id):
            raise ValueError("canary container_id is invalid")
        pids = tuple(self.process_ids)
        if (
            not pids
            or len(set(pids)) != len(pids)
            or any(
                isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1
                for pid in pids
            )
        ):
            raise ValueError(
                "canary process_ids must be unique integers greater than one"
            )
        workspace = _absolute_path("canary workspace", self.workspace).resolve(
            strict=False
        )
        if workspace == Path(workspace.anchor):
            raise ValueError("canary workspace cannot be a filesystem root")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "process_ids", pids)
        object.__setattr__(self, "workspace", workspace)

    @property
    def identity_sha256(self) -> str:
        payload = {
            "name": self.name,
            "container_id": self.container_id,
            "process_ids": list(self.process_ids),
            "workspace": str(self.workspace),
        }
        return _payload_sha256(payload)


class FaultTestAuthorization:
    """Opaque, non-serializable, single-use test capability."""

    __slots__ = (
        "_capability",
        "_cleanup_used",
        "_consumed",
        "_reconcile_used",
        "_setup_used",
        "gate",
        "peer_run_id",
        "target_run_id",
    )

    def __init__(
        self,
        *,
        gate: FaultGate,
        target_run_id: str,
        peer_run_id: str,
        _sentinel: object,
    ) -> None:
        if _sentinel is not _AUTH_SENTINEL:
            raise FaultAuthorizationError(
                "fault authorization can only be minted by the private test gate"
            )
        self.gate = gate
        self.target_run_id = target_run_id
        self.peer_run_id = peer_run_id
        self._capability = secrets.token_bytes(32)
        self._setup_used = False
        self._cleanup_used = False
        self._reconcile_used = False
        self._consumed = False

    def __repr__(self) -> str:
        return (
            "FaultTestAuthorization(gate="
            f"{self.gate.value!r}, target_run_id={self.target_run_id!r}, "
            f"peer_run_id={self.peer_run_id!r}, capability=<redacted>)"
        )

    def __reduce__(self) -> object:
        raise TypeError("fault test authorizations are intentionally non-serializable")

    def _consume(self, *, target_run_id: str, peer_run_id: str) -> FaultGate:
        if self._consumed:
            raise FaultAuthorizationError("fault authorization is single-use")
        if not isinstance(self._capability, bytes) or len(self._capability) != 32:
            raise FaultAuthorizationError("fault authorization is invalid")
        if self.target_run_id != target_run_id or self.peer_run_id != peer_run_id:
            raise FaultAuthorizationError(
                "fault authorization does not match the exact target and peer"
            )
        if self.gate is FaultGate.ENOSPC and not self._setup_used:
            raise FaultAuthorizationError(
                "ENOSPC injection requires the authorized private tmpfs setup"
            )
        self._consumed = True
        return self.gate

    def _authorize_tmpfs_setup(self, run: OwnedRun | PrelaunchEnospcTarget) -> None:
        self._validate_tmpfs_binding(run)
        if self._setup_used:
            raise FaultAuthorizationError("private tmpfs setup is single-use")
        if self._consumed:
            raise FaultAuthorizationError("private tmpfs setup must precede injection")
        self._setup_used = True

    def _authorize_tmpfs_cleanup(self, run: OwnedRun) -> None:
        self._validate_tmpfs_binding(run)
        if not self._setup_used or not self._consumed:
            raise FaultAuthorizationError(
                "private tmpfs cleanup requires setup and attempted injection"
            )
        if self._cleanup_used:
            raise FaultAuthorizationError("private tmpfs cleanup is single-use")
        self._cleanup_used = True

    def _authorize_tmpfs_reconcile(self, run: OwnedRun) -> None:
        """Authorize one recovery-only audit of an interrupted ENOSPC mount.

        Reconciliation deliberately requires a fresh private capability.  It
        cannot be used to bypass the ordinary setup/injection/cleanup sequence.
        """

        self._validate_tmpfs_binding(run)
        if self._setup_used or self._consumed or self._cleanup_used:
            raise FaultAuthorizationError(
                "private tmpfs reconciliation requires a fresh recovery token"
            )
        if self._reconcile_used:
            raise FaultAuthorizationError("private tmpfs reconciliation is single-use")
        self._reconcile_used = True

    def _validate_tmpfs_binding(self, run: OwnedRun | PrelaunchEnospcTarget) -> None:
        if (
            self.gate is not FaultGate.ENOSPC
            or self.target_run_id != run.run_id
            or not isinstance(self._capability, bytes)
            or len(self._capability) != 32
        ):
            raise FaultAuthorizationError(
                "private tmpfs authorization is not bound to this ENOSPC target"
            )


def authorize_private_m1b_fault(
    *,
    test_mode: bool,
    gate: FaultGate,
    target_run_id: str,
    peer_run_id: str,
) -> FaultTestAuthorization:
    """Mint one explicit private test capability; ordinary mode always rejects.

    ``test_mode`` must be the literal boolean ``True``.  Strings such as ``"1"``
    and mappings sourced from configuration are intentionally not coerced.
    """

    if test_mode is not True:
        raise FaultAuthorizationError(
            "M1b fault capabilities require explicit private test_mode=True"
        )
    if not isinstance(gate, FaultGate):
        raise FaultAuthorizationError("gate must be an exact FaultGate selection")
    if not _RUN_ID_RE.fullmatch(str(target_run_id)) or not _RUN_ID_RE.fullmatch(
        str(peer_run_id)
    ):
        raise FaultAuthorizationError("authorized run identifiers are invalid")
    if target_run_id == peer_run_id:
        raise FaultAuthorizationError("target and peer must be distinct runs")
    return FaultTestAuthorization(
        gate=gate,
        target_run_id=target_run_id,
        peer_run_id=peer_run_id,
        _sentinel=_AUTH_SENTINEL,
    )


@dataclass(frozen=True)
class FaultCommandResult:
    """Bounded result from one exact shell-free action."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class FaultCommandRunner(Protocol):
    def run(
        self, argv: Sequence[str], *, timeout_seconds: float
    ) -> FaultCommandResult: ...


class SubprocessFaultCommandRunner:
    """Default command boundary.  Fault authorization is enforced by the driver."""

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> FaultCommandResult:
        normalized = _command_vector(argv)
        try:
            completed = subprocess.run(
                normalized,
                check=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FaultActionError(
                f"fault command failed before completion: {type(exc).__name__}"
            ) from exc
        return FaultCommandResult(
            argv=normalized,
            returncode=completed.returncode,
            stdout=_bounded_capture(completed.stdout),
            stderr=_bounded_capture(completed.stderr),
        )


class OwnedRunEvidenceLoader:
    """Build an :class:`OwnedRun` only from settled read-only control evidence.

    The caller supplies the trusted service roots.  Launch evidence is not
    allowed to redirect the loader to another registry or artifact tree.  A
    full load is intentionally limited to the five post-readiness gates: it
    requires one active manager owner, one exact ProcessSupervisor child
    receipt, live child environment/PGID proof, the controller's durable
    container-created receipt, exact Docker labels/configuration, and one
    unique Dwarf_Fortress host/container PID+cgroup identity.

    ``load_pre_readiness_oom_target`` validates the same canonical launch and
    registry reservation without inventing a harness PID; the OOM monitor
    binds it to container evidence later.
    """

    def __init__(
        self,
        *,
        control_root: Path | str,
        db_path: Path | str,
        artifacts_root: Path | str,
        command_runner: FaultCommandRunner | None = None,
        read_bytes: Callable[[Path], bytes] | None = None,
        read_text: Callable[[Path], str] | None = None,
        path_exists: Callable[[Path], bool] = Path.exists,
        getpgid: Callable[[int], int] = os.getpgid,
        process_ids: Callable[[], Sequence[int]] | None = None,
        sqlite_connect: Callable[..., sqlite3.Connection] = sqlite3.connect,
        mount_probe: Callable[[Path], Mapping[str, Any] | None] | None = None,
        run_process_ids: Callable[[], Sequence[int]] | None = None,
    ) -> None:
        self.control_root = _absolute_path("control_root", control_root).resolve(
            strict=False
        )
        self.db_path = _absolute_path("db_path", db_path).resolve(strict=False)
        self.artifacts_root = _absolute_path("artifacts_root", artifacts_root).resolve(
            strict=False
        )
        if (
            self.control_root == Path(self.control_root.anchor)
            or self.artifacts_root == Path(self.artifacts_root.anchor)
            or _paths_overlap(self.control_root, self.artifacts_root)
        ):
            raise ValueError(
                "trusted control and artifact roots must be safe and disjoint"
            )
        self._runner = command_runner or SubprocessFaultCommandRunner()
        self._read_bytes = read_bytes or Path.read_bytes
        self._read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self._path_exists = path_exists
        self._getpgid = getpgid
        self._process_ids = process_ids or _linux_process_ids
        self._run_process_ids = run_process_ids
        self._sqlite_connect = sqlite_connect
        self._mount_probe = mount_probe or (
            lambda path: _find_exact_mount_with_runner(self._runner, path)
        )

    def load(self, run_id: str) -> OwnedRun:
        """Load one fully started post-readiness run or fail closed."""

        return self._load_full(
            run_id,
            runtime_fault_role=None,
            workspace_fault_role=None,
            counterpart_run_id=None,
        )

    def load_oom_peer(self, run_id: str, *, target_run_id: str) -> OwnedRun:
        """Load the exact normal-cap peer from a two-run OOM fault cohort."""

        return self._load_full(
            run_id,
            runtime_fault_role="peer",
            workspace_fault_role=None,
            counterpart_run_id=target_run_id,
        )

    def load_enospc_target(self, run_id: str, *, peer_run_id: str) -> OwnedRun:
        """Load a running ENOSPC target with its prelaunch tmpfs attested."""

        return self._load_full(
            run_id,
            runtime_fault_role=None,
            workspace_fault_role="target",
            counterpart_run_id=peer_run_id,
        )

    def load_enospc_peer(self, run_id: str, *, target_run_id: str) -> OwnedRun:
        """Load the ordinary-workspace peer in the exact ENOSPC cohort."""

        return self._load_full(
            run_id,
            runtime_fault_role=None,
            workspace_fault_role="peer",
            counterpart_run_id=target_run_id,
        )

    def _load_full(
        self,
        run_id: str,
        *,
        runtime_fault_role: str | None,
        workspace_fault_role: str | None,
        counterpart_run_id: str | None,
    ) -> OwnedRun:
        contract, registry = self._load_launch_and_registry(
            run_id,
            runtime_fault_role=runtime_fault_role,
            workspace_fault_role=workspace_fault_role,
            counterpart_run_id=counterpart_run_id,
        )
        run_dir = self.control_root / run_id
        attempt_dir = run_dir / "attempts" / "attempt-0001"
        owner = self._read_json(run_dir / "owner.json", "manager owner")
        _exact_keys(
            "manager owner",
            owner,
            {
                "schema",
                "run_id",
                "state",
                "manager_pid",
                "manager_start_ticks",
                "identity_bound",
                "contract_sha256",
                "nonce_sha256",
                "environment_identity_sha256",
                "observed_registry_status",
                "attempt_dir",
                "updated_at",
            },
        )
        supervisor_pid = _positive_evidence_int(
            owner.get("manager_pid"), "manager owner PID"
        )
        manager_start_ticks = _positive_evidence_int(
            owner.get("manager_start_ticks"), "manager owner start time"
        )
        manager_stat_path = Path(f"/proc/{supervisor_pid}/stat")
        try:
            observed_manager_start_ticks = _proc_stat_start_ticks(
                self._read_text(manager_stat_path)
            )
        except (OSError, KeyError) as exc:
            raise FaultEvidenceError(
                "active manager process start-time evidence is unavailable"
            ) from exc
        if (
            owner.get("schema") != "fortgym.supervised-manager-owner/v1"
            or owner.get("run_id") != run_id
            or owner.get("state") != "active"
            or observed_manager_start_ticks != manager_start_ticks
            or Path(str(owner.get("attempt_dir"))).resolve(strict=False)
            != attempt_dir.resolve(strict=False)
            or not isinstance(owner.get("observed_registry_status"), str)
            or not isinstance(owner.get("updated_at"), str)
            or not self._path_exists(Path(f"/proc/{supervisor_pid}"))
        ):
            raise FaultEvidenceError("active manager ownership evidence differs")

        # SupervisedRunManager first publishes an active, unbound owner while
        # its controller/contract factories run, then atomically binds it before
        # ProcessSupervisor starts. Polling that exact prelaunch window is not
        # an identity contradiction. Never return an OwnedRun from it, and never
        # excuse a missing binding after durable supervision/runtime evidence.
        if (
            owner.get("identity_bound") is False
            and owner.get("observed_registry_status") in {"pending", "running"}
            and all(
                owner.get(key) is None
                for key in ("contract_sha256", "nonce_sha256", "environment_identity_sha256")
            )
            and not any(
                self._path_exists(path)
                for path in (
                    attempt_dir / "attempt-journal.jsonl",
                    attempt_dir / "runtime" / "container-created.json",
                    run_dir / "manager-terminal.json",
                )
            )
        ):
            raise OwnedRunEvidencePending("manager launch identity is not yet bound")
        if (
            owner.get("identity_bound") is not True
            or owner.get("contract_sha256") != contract["contract_sha256"]
            or owner.get("nonce_sha256") != _nonce_sha256(str(contract["rpc"]["nonce"]))
            or owner.get("environment_identity_sha256") != _payload_sha256(contract)
        ):
            raise FaultEvidenceError("active manager ownership evidence differs")

        attempt_rows = self._read_jsonl(
            attempt_dir / "attempt-journal.jsonl", "process-supervisor journal"
        )
        attempt_started = [
            row for row in attempt_rows if row.get("event") == "attempt_started"
        ]
        child_started = [
            row for row in attempt_rows if row.get("event") == "child_started"
        ]
        if len(attempt_started) != 1 or len(child_started) != 1:
            raise OwnedRunEvidencePending(
                "one exact process-supervisor child receipt is not settled"
            )
        attempt_record = attempt_started[0]
        child_record = child_started[0]
        _exact_keys(
            "attempt_started receipt",
            attempt_record,
            {
                "schema",
                "at",
                "monotonic_ns",
                "supervisor_pid",
                "event",
                "run_id",
                "scripted",
                "provider_enabled",
                "argv0",
                "port",
                "environment_identity",
                "cotenancy",
                "supervisor_runtime",
            },
        )
        _exact_keys(
            "child_started receipt",
            child_record,
            {
                "schema",
                "at",
                "monotonic_ns",
                "supervisor_pid",
                "event",
                "run_id",
                "child_pid",
            },
        )
        if attempt_rows.index(attempt_record) >= attempt_rows.index(child_record):
            raise FaultEvidenceError("child receipt precedes its attempt receipt")
        if (
            attempt_record.get("environment_identity") != contract
            or _proc_stat_start_ticks(self._read_text(manager_stat_path))
            != manager_start_ticks
        ):
            raise FaultEvidenceError(
                "active manager ownership changed during evidence loading"
            )
        terminal_events = {
            "termination_requested",
            "cleanup_started",
            "terminal_pending_cleanup",
            "evidence_snapshot_completed",
            "harness_process_group_reaped",
            "runtime_container_removed",
            "cleanup_recorded",
            "cleanup_verified",
            "cleanup_completed",
            "immutable_terminal_classification",
            "terminal_pending",
            "terminal_written",
        }
        if any(row.get("event") in terminal_events for row in attempt_rows):
            raise FaultEvidenceError(
                "run already entered terminal or cleanup sequencing"
            )
        for label, row in (
            ("attempt_started", attempt_record),
            ("child_started", child_record),
        ):
            if (
                row.get("schema") != "fortgym.process-supervisor-attempt/v1"
                or row.get("run_id") != run_id
                or row.get("supervisor_pid") != supervisor_pid
                or not isinstance(row.get("at"), str)
                or isinstance(row.get("monotonic_ns"), bool)
                or not isinstance(row.get("monotonic_ns"), int)
                or row.get("monotonic_ns") < 0
            ):
                raise FaultEvidenceError(f"{label} process-supervisor binding differs")
        if attempt_record.get("environment_identity") != contract:
            raise FaultEvidenceError(
                "process-supervisor environment identity differs from launch contract"
            )
        if attempt_record.get("cotenancy") != contract["cotenancy"]:
            raise FaultEvidenceError(
                "process-supervisor cotenancy differs from launch contract"
            )
        if (
            attempt_record.get("scripted") is not True
            or attempt_record.get("provider_enabled") is not False
            or attempt_record.get("port") != contract["rpc"]["port"]
            or not isinstance(attempt_record.get("argv0"), str)
            or not Path(str(attempt_record.get("argv0"))).is_absolute()
            or not isinstance(attempt_record.get("supervisor_runtime"), Mapping)
        ):
            raise FaultEvidenceError(
                "process-supervisor launch mode differs from frozen bounds"
            )
        child_pid = _positive_evidence_int(
            child_record.get("child_pid"), "process-supervisor child PID"
        )
        if not self._path_exists(Path(f"/proc/{child_pid}")):
            raise OwnedRunEvidencePending("process-supervisor child is not live")
        try:
            child_pgid = self._getpgid(child_pid)
        except OSError as exc:
            raise OwnedRunEvidencePending(
                "process-supervisor child process group is not live"
            ) from exc
        if child_pgid != child_pid:
            raise FaultEvidenceError(
                "process-supervisor child does not own its exact process group"
            )
        child_environment = _nul_environment_index(
            self._read_bounded(Path(f"/proc/{child_pid}/environ"), 256 * 1024),
            "process-supervisor child environment",
        )
        if (
            child_environment.get("FORT_GYM_RUN_ID") != run_id
            or child_environment.get("FORT_GYM_RUN_CONTRACT_SHA256")
            != contract["contract_sha256"]
            or child_environment.get("FORT_GYM_RUN_NONCE") != contract["rpc"]["nonce"]
            or child_environment.get("FORT_GYM_CONTROL_DIR") != str(attempt_dir)
        ):
            raise FaultEvidenceError("live harness environment identity differs")
        child_argv = _nul_string_sequence(
            self._read_bounded(Path(f"/proc/{child_pid}/cmdline"), 64 * 1024),
            "process-supervisor child command",
        )
        if not any(
            child_argv[index : index + 2] == ("--external-run-id", run_id)
            for index in range(max(0, len(child_argv) - 1))
        ):
            raise FaultEvidenceError("live harness command lacks the exact run ID")

        receipt = self._read_json(
            attempt_dir / "runtime" / "container-created.json",
            "runtime container-created receipt",
        )
        container_id, container_name = _validate_container_created_receipt(
            receipt,
            run_id=run_id,
            contract_sha256=str(contract["contract_sha256"]),
            nonce=str(contract["rpc"]["nonce"]),
            cohort_sha256=str(contract["cotenancy"]["cohort_sha256"]),
            expected_fault_profile=None,
            expected_memory_bytes=_NORMAL_MEMORY_BYTES,
        )
        inspection = self._docker_inspection(container_id)
        container_init_host_pid = _validate_live_container_binding(
            inspection,
            run_id=run_id,
            contract=contract,
            container_name=container_name,
            container_id=container_id,
            expected_fault_profile=None,
            expected_memory_bytes=_NORMAL_MEMORY_BYTES,
        )
        runtime_host_pid, runtime_container_pid, runtime_cgroup_path = (
            _discover_unique_dwarf_process(
                container_id=container_id,
                container_init_host_pid=container_init_host_pid,
                process_ids=self._process_ids(),
                read_text=self._read_text,
                path_exists=self._path_exists,
            )
        )
        workspace = self.artifacts_root / run_id
        if not self._path_exists(workspace):
            raise OwnedRunEvidencePending("run workspace is not present")
        if registry["artifacts_dir"] != str(workspace):
            raise FaultEvidenceError("registry artifacts directory differs")
        if workspace_fault_role == "target":
            if counterpart_run_id is None:
                raise FaultEvidenceError("ENOSPC target peer identity is unavailable")
            self._validate_live_enospc_workspace(
                run_id=run_id,
                contract=contract,
                workspace=workspace,
                peer_run_id=counterpart_run_id,
            )
        return OwnedRun(
            run_id=run_id,
            contract_sha256=str(contract["contract_sha256"]),
            nonce=str(contract["rpc"]["nonce"]),
            cohort_sha256=str(contract["cotenancy"]["cohort_sha256"]),
            container_id=container_id,
            runtime_host_pid=runtime_host_pid,
            runtime_container_pid=runtime_container_pid,
            runtime_cgroup_path=runtime_cgroup_path,
            harness_pid=child_pid,
            harness_process_group_id=child_pgid,
            supervisor_pid=supervisor_pid,
            db_path=self.db_path,
            workspace=workspace,
            control_root=self.control_root,
        )

    def try_load(self, run_id: str) -> OwnedRun | None:
        """Return ``None`` only while valid evidence is not yet settled."""

        try:
            return self.load(run_id)
        except OwnedRunEvidencePending:
            return None

    def try_load_oom_peer(self, run_id: str, *, target_run_id: str) -> OwnedRun | None:
        """Return ``None`` only while the exact normal-cap OOM peer is pending."""

        try:
            return self.load_oom_peer(run_id, target_run_id=target_run_id)
        except OwnedRunEvidencePending:
            return None

    def try_load_enospc_target(
        self, run_id: str, *, peer_run_id: str
    ) -> OwnedRun | None:
        try:
            return self.load_enospc_target(run_id, peer_run_id=peer_run_id)
        except OwnedRunEvidencePending:
            return None

    def try_load_enospc_peer(
        self, run_id: str, *, target_run_id: str
    ) -> OwnedRun | None:
        try:
            return self.load_enospc_peer(run_id, target_run_id=target_run_id)
        except OwnedRunEvidencePending:
            return None

    def load_pre_readiness_oom_target(self, run_id: str) -> PreReadinessOomTarget:
        """Load the canonical reserved target without requiring a fake child PID."""

        contract, registry = self._load_launch_and_registry(
            run_id,
            runtime_fault_role="target",
            workspace_fault_role=None,
            counterpart_run_id=None,
        )
        if registry["status"] not in {"pending", "running"}:
            raise FaultEvidenceError("pre-readiness OOM target is already terminal")
        return PreReadinessOomTarget(
            run_id=run_id,
            contract_sha256=str(contract["contract_sha256"]),
            nonce=str(contract["rpc"]["nonce"]),
            cohort_sha256=str(contract["cotenancy"]["cohort_sha256"]),
            container_name=(
                f"fortgym-m1b-{run_id}-{str(contract['contract_sha256'])[:12]}"
            ),
            db_path=self.db_path,
            workspace=self.artifacts_root / run_id,
            control_root=self.control_root,
        )

    def load_prelaunch_enospc_target(
        self, run_id: str, *, mountpoint_created: bool = False
    ) -> PrelaunchEnospcTarget:
        """Load a reserved target before manager/artifact creation or fail closed."""

        contract, registry = self._load_launch_and_registry(
            run_id,
            runtime_fault_role=None,
            workspace_fault_role="target",
            counterpart_run_id=None,
        )
        cotenancy = _mapping("ENOSPC prelaunch cotenancy", contract.get("cotenancy"))
        peer_ids = cotenancy.get("peer_run_ids")
        if not isinstance(peer_ids, list) or len(peer_ids) != 1:
            raise FaultEvidenceError("ENOSPC prelaunch target lacks one exact peer")
        peer_run_id = str(peer_ids[0])
        run_dir = self.control_root / run_id
        workspace = self.artifacts_root / run_id
        workspace_exists = self._path_exists(workspace)
        if mountpoint_created:
            if not workspace_exists:
                raise FaultEvidenceError("ENOSPC pre-mount directory is absent")
            metadata = workspace.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or workspace.resolve(strict=True) != workspace
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != (run_dir / "launch.json").lstat().st_uid
                or any(workspace.iterdir())
            ):
                raise FaultEvidenceError("ENOSPC pre-mount directory is unsafe or nonempty")
        if (
            registry["status"] != "pending"
            or registry["step"] != 0
            or self._path_exists(run_dir / "owner.json")
            or self._path_exists(run_dir / "attempts")
            or (workspace_exists and not mountpoint_created)
            or self._mount_probe(workspace) is not None
        ):
            raise FaultEvidenceError(
                "ENOSPC workspace prelaunch window is already closed"
            )
        return PrelaunchEnospcTarget(
            run_id=run_id,
            contract_sha256=str(contract["contract_sha256"]),
            nonce=str(contract["rpc"]["nonce"]),
            cohort_sha256=str(contract["cotenancy"]["cohort_sha256"]),
            peer_run_id=peer_run_id,
            db_path=self.db_path,
            workspace=workspace,
            control_root=self.control_root,
        )

    def load_enospc_cleanup_target(
        self, run_id: str, *, peer_run_id: str
    ) -> EnospcWorkspaceCleanupTarget:
        """Reconstruct exact mount ownership after the child group is absent.

        This loader intentionally does not require a live manager owner.  It is
        therefore usable by dead-owner recovery, but it refuses any process in
        the recorded child process group. An exact already-absent unmount may
        be reconstructed through the durable cleanup/classification records;
        one final fsynced terminal-pending row is accepted only while the
        terminal record is absent. Existing terminal evidence remains outside
        this cleanup authority.
        """

        contract, _registry = self._load_launch_and_registry(
            run_id,
            runtime_fault_role=None,
            workspace_fault_role="target",
            counterpart_run_id=peer_run_id,
        )
        workspace = self.artifacts_root / run_id
        attempt_dir = self.control_root / run_id / "attempts" / "attempt-0001"
        journal_path = attempt_dir / "attempt-journal.jsonl"
        rows = (
            self._read_jsonl(
                journal_path,
                "ENOSPC cleanup process-supervisor journal",
            )
            if self._path_exists(journal_path)
            else []
        )
        terminal_path = attempt_dir / "terminal.json"
        if self._path_exists(terminal_path):
            raise FaultEvidenceError(
                "ENOSPC cleanup authority ends once terminal evidence exists"
            )
        children = [row for row in rows if row.get("event") == "child_started"]
        if len(children) > 1:
            raise FaultEvidenceError("ENOSPC cleanup has multiple child-start receipts")
        pending_rows = [row for row in rows if row.get("event") == "terminal_pending"]
        if len(pending_rows) > 1:
            raise FaultEvidenceError("ENOSPC cleanup has multiple terminal-pending rows")
        if any(row.get("event") == "terminal_written" for row in rows):
            raise FaultEvidenceError(
                "ENOSPC workspace cleanup is after terminal sequencing"
            )
        child_pgid: int | None = None
        cleanup_mode = "pre_child_abort"
        if children:
            child = children[0]
            _exact_keys(
                "ENOSPC cleanup child receipt",
                child,
                {
                    "schema",
                    "at",
                    "monotonic_ns",
                    "supervisor_pid",
                    "event",
                    "run_id",
                    "child_pid",
                },
            )
            child_pgid = _positive_evidence_int(
                child.get("child_pid"), "ENOSPC cleanup child process group"
            )
            if (
                child.get("schema") != "fortgym.process-supervisor-attempt/v1"
                or child.get("run_id") != run_id
            ):
                raise FaultEvidenceError("ENOSPC cleanup child receipt differs")
            cleanup_mode = "post_child_cleanup"
            members: list[int] = []
            for pid in self._process_ids():
                try:
                    if self._getpgid(pid) == child_pgid:
                        members.append(pid)
                except (OSError, KeyError):
                    continue
            if members:
                raise OwnedRunEvidencePending(
                    "ENOSPC child process group is not yet absent"
                )
        if self._live_processes_with_run_id(run_id):
            raise OwnedRunEvidencePending(
                "ENOSPC run-owned processes remain before workspace cleanup"
            )
        target = EnospcWorkspaceCleanupTarget(
            run_id=run_id,
            contract_sha256=str(contract["contract_sha256"]),
            nonce=str(contract["rpc"]["nonce"]),
            cohort_sha256=str(contract["cotenancy"]["cohort_sha256"]),
            peer_run_id=peer_run_id,
            db_path=self.db_path,
            workspace=workspace,
            control_root=self.control_root,
            cleanup_mode=cleanup_mode,
            harness_process_group_id=child_pgid,
        )
        if self._path_exists(workspace):
            if pending_rows:
                raise FaultEvidenceError(
                    "ENOSPC terminal-pending evidence contradicts a live workspace"
                )
            self._validate_live_enospc_workspace(
                run_id=run_id,
                contract=contract,
                workspace=workspace,
                peer_run_id=peer_run_id,
            )
            return target

        if self._mount_probe(workspace) is not None:
            raise FaultEvidenceError(
                "ENOSPC workspace path is absent but a mount remains"
            )
        completed = [
            row for row in rows if row.get("event") == "post_cleanup_completed"
        ]
        started = [row for row in rows if row.get("event") == "post_cleanup_started"]
        if len(completed) != 1 or len(started) != 1:
            raise OwnedRunEvidencePending(
                "absent ENOSPC workspace lacks one exact post-cleanup attestation"
            )
        completion = completed[0]
        start = started[0]
        start_index = rows.index(start)
        completion_index = rows.index(completion)
        if completion_index != start_index + 1:
            raise FaultEvidenceError(
                "ENOSPC post-cleanup journal ordering is contradictory"
            )
        _exact_keys(
            "ENOSPC post-cleanup start",
            start,
            {
                "schema",
                "at",
                "monotonic_ns",
                "supervisor_pid",
                "event",
                "run_id",
            },
        )
        _exact_keys(
            "ENOSPC post-cleanup completion",
            completion,
            {
                "schema",
                "at",
                "monotonic_ns",
                "supervisor_pid",
                "event",
                "run_id",
                "ok",
                "details",
            },
        )
        details = _mapping(
            "ENOSPC post-cleanup completion details", completion.get("details")
        )
        _exact_keys(
            "ENOSPC post-cleanup completion details",
            details,
            {
                "schema",
                "operation",
                "run_id",
                "argv",
                "shell",
                "cleanup_mode",
                "child_process_group_id",
                "child_process_group_absent",
                "residue_absent",
            },
        )
        if (
            start.get("schema") != "fortgym.process-supervisor-attempt/v1"
            or start.get("run_id") != run_id
            or completion.get("schema")
            != "fortgym.process-supervisor-attempt/v1"
            or completion.get("run_id") != run_id
            or completion.get("supervisor_pid") != start.get("supervisor_pid")
            or completion.get("ok") is not True
            or details.get("schema") != TMPFS_LIFECYCLE_SCHEMA
            or details.get("operation") != "unmounted"
            or details.get("run_id") != run_id
            or details.get("argv")
            != ["/bin/umount", "--", str(target.workspace)]
            or details.get("shell") is not False
            or details.get("cleanup_mode") != target.cleanup_mode
            or details.get("child_process_group_id")
            != target.harness_process_group_id
            or details.get("child_process_group_absent") is not True
            or details.get("residue_absent") is not True
        ):
            raise FaultEvidenceError(
                "ENOSPC post-cleanup completion does not prove exact unmount"
            )
        chain_identity, snapshot_sha256 = _validate_enospc_terminal_chain_prefix(
            rows=rows,
            start=start,
            attempt_dir=attempt_dir,
            contract=contract,
            target=target,
            read_bytes=self._read_bytes,
        )
        trailing = rows[completion_index + 1 :]
        trailing_events = [row.get("event") for row in trailing]
        expected_trailing = [
            "runtime_container_removed",
            "cleanup_recorded",
            "runtime_fault_classification_recorded",
            "cleanup_verified",
            "cleanup_completed",
            "immutable_terminal_classification",
            "terminal_pending",
        ]
        if trailing_events != expected_trailing[: len(trailing_events)]:
            raise FaultEvidenceError(
                "ENOSPC post-cleanup trailing journal sequence is contradictory"
            )
        preceding_monotonic = completion.get("monotonic_ns")
        if isinstance(preceding_monotonic, bool) or not isinstance(
            preceding_monotonic, int
        ):
            raise FaultEvidenceError("ENOSPC post-cleanup monotonic evidence differs")
        for row in trailing:
            observed_monotonic = row.get("monotonic_ns")
            if (
                row.get("schema") != "fortgym.process-supervisor-attempt/v1"
                or row.get("run_id") != run_id
                or row.get("supervisor_pid") != start.get("supervisor_pid")
                or isinstance(observed_monotonic, bool)
                or not isinstance(observed_monotonic, int)
                or observed_monotonic <= preceding_monotonic
            ):
                raise FaultEvidenceError(
                    "ENOSPC post-cleanup trailing journal identity differs"
                )
            preceding_monotonic = observed_monotonic
        if pending_rows and (
            rows[-1] is not pending_rows[0]
            or trailing_events != expected_trailing
        ):
            raise FaultEvidenceError(
                "ENOSPC terminal-pending journal ordering is contradictory"
            )
        if trailing:
            removal_row = trailing[0]
            _exact_keys(
                "ENOSPC runtime-removal record",
                removal_row,
                {
                    "schema",
                    "at",
                    "monotonic_ns",
                    "supervisor_pid",
                    "event",
                    "run_id",
                    "identity",
                    "ok",
                    "skipped",
                    "container_absent",
                    "listener_absent",
                },
            )
            if (
                removal_row.get("schema")
                != "fortgym.process-supervisor-attempt/v1"
                or removal_row.get("run_id") != run_id
                or removal_row.get("supervisor_pid") != start.get("supervisor_pid")
                or removal_row.get("identity") != chain_identity
                or removal_row.get("ok") is not True
                or removal_row.get("skipped") is not False
                or removal_row.get("container_absent") is not True
                or removal_row.get("listener_absent") is not True
            ):
                raise FaultEvidenceError(
                    "ENOSPC runtime-removal record is contradictory"
                )
        cleanup: Mapping[str, Any] | None = None
        cleanup_sha256: str | None = None
        if len(trailing) >= 2:
            cleanup_row = trailing[1]
            _exact_keys(
                "ENOSPC durable cleanup record",
                cleanup_row,
                {
                    "schema",
                    "at",
                    "monotonic_ns",
                    "supervisor_pid",
                    "event",
                    "run_id",
                    "cleanup",
                },
            )
            cleanup = _mapping(
                "ENOSPC durable cleanup record", cleanup_row.get("cleanup")
            )
            cleanup_sha256 = _payload_sha256(cleanup)
            _exact_keys("ENOSPC durable cleanup record", cleanup, {"ok", "stages"})
            stages = cleanup.get("stages")
            if not isinstance(stages, list) or not stages:
                raise FaultEvidenceError("ENOSPC durable cleanup stages are invalid")
            stage_mappings = [
                _mapping("ENOSPC durable cleanup stage", stage) for stage in stages
            ]
            stage_names = [stage.get("stage") for stage in stage_mappings]
            post_stages = [
                stage
                for stage in stage_mappings
                if stage.get("stage") == "post_callback"
            ]
            if (
                cleanup_row.get("schema")
                != "fortgym.process-supervisor-attempt/v1"
                or cleanup_row.get("run_id") != run_id
                or cleanup_row.get("supervisor_pid") != start.get("supervisor_pid")
                or cleanup.get("ok") is not True
                or any(stage.get("ok") is not True for stage in stage_mappings)
                or len(set(stage_names)) != len(stage_names)
                or len(post_stages) != 1
                or set(post_stages[0]) != {"stage", "ok", "details"}
                or post_stages[0].get("details") != details
            ):
                raise FaultEvidenceError(
                    "ENOSPC durable cleanup record contradicts the exact unmount"
                )
        fault_record: Mapping[str, Any] | None = None
        if len(trailing) >= 3:
            classification_row = trailing[2]
            _exact_keys(
                "ENOSPC durable fault-classification record",
                classification_row,
                {
                    "schema",
                    "at",
                    "monotonic_ns",
                    "supervisor_pid",
                    "event",
                    "run_id",
                    "fault_classification",
                    "terminal_draft_path",
                    "terminal_draft_sha256",
                },
            )
            fault_record = _mapping(
                "ENOSPC durable fault-classification record",
                classification_row.get("fault_classification"),
            )
            if (
                classification_row.get("schema")
                != "fortgym.process-supervisor-attempt/v1"
                or classification_row.get("run_id") != run_id
                or classification_row.get("supervisor_pid")
                != start.get("supervisor_pid")
                or classification_row.get("terminal_draft_path")
                != str(attempt_dir / "terminal-draft.json")
                or classification_row.get("terminal_draft_sha256")
                != hashlib.sha256(
                    self._read_bounded(
                        attempt_dir / "terminal-draft.json", 4 * 1024 * 1024
                    )
                ).hexdigest()
                or fault_record.get("schema")
                != "fortgym.runtime-fault-classification/v1"
                or not isinstance(fault_record.get("attempted"), bool)
                or not isinstance(fault_record.get("ok"), bool)
                or not isinstance(fault_record.get("classified"), bool)
            ):
                raise FaultEvidenceError(
                    "ENOSPC durable fault-classification record is contradictory"
                )
        if len(trailing) >= 4:
            if cleanup_sha256 is None:
                raise FaultEvidenceError("ENOSPC cleanup digest is unavailable")
            for offset, event in ((3, "cleanup_verified"), (4, "cleanup_completed")):
                if len(trailing) <= offset:
                    break
                cleanup_boundary = trailing[offset]
                _exact_keys(
                    f"ENOSPC {event} record",
                    cleanup_boundary,
                    {
                        "schema",
                        "at",
                        "monotonic_ns",
                        "supervisor_pid",
                        "event",
                        "run_id",
                        "identity",
                        "ok",
                        "cleanup_sha256",
                    },
                )
                if (
                    cleanup_boundary.get("schema")
                    != "fortgym.process-supervisor-attempt/v1"
                    or cleanup_boundary.get("run_id") != run_id
                    or cleanup_boundary.get("supervisor_pid")
                    != start.get("supervisor_pid")
                    or cleanup_boundary.get("event") != event
                    or cleanup_boundary.get("identity") != chain_identity
                    or cleanup_boundary.get("ok") is not True
                    or cleanup_boundary.get("cleanup_sha256") != cleanup_sha256
                ):
                    raise FaultEvidenceError(
                        f"ENOSPC {event} record is contradictory"
                    )
        immutable_terminal: str | None = None
        if len(trailing) >= 6:
            if cleanup_sha256 is None:
                raise FaultEvidenceError("ENOSPC cleanup digest is unavailable")
            immutable = trailing[5]
            _exact_keys(
                "ENOSPC immutable terminal record",
                immutable,
                {
                    "schema",
                    "at",
                    "monotonic_ns",
                    "supervisor_pid",
                    "event",
                    "run_id",
                    "identity",
                    "terminal_class",
                    "reason_sha256",
                    "cleanup_sha256",
                    "evidence_snapshot_sha256",
                },
            )
            immutable_terminal = immutable.get("terminal_class")
            if (
                immutable.get("schema") != "fortgym.process-supervisor-attempt/v1"
                or immutable.get("run_id") != run_id
                or immutable.get("supervisor_pid") != start.get("supervisor_pid")
                or immutable.get("identity") != chain_identity
                or immutable_terminal not in _PROCESS_SUPERVISOR_TERMINAL_CLASSES
                or immutable_terminal == "cleanup_failure"
                or not _SHA256_RE.fullmatch(str(immutable.get("reason_sha256") or ""))
                or immutable.get("cleanup_sha256") != cleanup_sha256
                or immutable.get("evidence_snapshot_sha256") != snapshot_sha256
            ):
                raise FaultEvidenceError(
                    "ENOSPC immutable terminal record is contradictory"
                )
        if len(trailing) == 7:
            terminal_pending = trailing[6]
            _exact_keys(
                "ENOSPC terminal-pending record",
                terminal_pending,
                {
                    "schema",
                    "at",
                    "monotonic_ns",
                    "supervisor_pid",
                    "event",
                    "run_id",
                    "terminal_class",
                    "cleanup_ok",
                },
            )
            terminal_class = terminal_pending.get("terminal_class")
            classified_terminal = (
                fault_record.get("terminal_class")
                if fault_record is not None
                and fault_record.get("classified") is True
                else None
            )
            classification_failed = bool(
                fault_record is not None
                and fault_record.get("attempted") is True
                and fault_record.get("ok") is False
            )
            if (
                terminal_pending.get("schema")
                != "fortgym.process-supervisor-attempt/v1"
                or terminal_pending.get("run_id") != run_id
                or terminal_pending.get("supervisor_pid")
                != start.get("supervisor_pid")
                or terminal_pending.get("cleanup_ok") is not True
                or terminal_class not in _PROCESS_SUPERVISOR_TERMINAL_CLASSES
                or terminal_class == "cleanup_failure"
                or terminal_class != immutable_terminal
                or (
                    classified_terminal is not None
                    and terminal_class != classified_terminal
                )
                or (
                    classification_failed
                    and terminal_class != "runtime_fault_classification_failure"
                )
            ):
                raise FaultEvidenceError(
                    "ENOSPC terminal-pending record is contradictory"
                )
        receipt = _read_bounded_json_path(
            self.control_root / run_id / "prelaunch-enospc-workspace.json",
            "prelaunch ENOSPC workspace receipt",
        )
        _validate_prelaunch_enospc_receipt(receipt, target)
        return target

    def _live_processes_with_run_id(self, run_id: str) -> tuple[int, ...]:
        expected = run_id.encode("utf-8")
        matches: list[int] = []
        for pid in (self._run_process_ids or self._process_ids)():
            path = Path(f"/proc/{pid}/environ")
            try:
                raw = self._read_bytes(path)
            except (FileNotFoundError, ProcessLookupError, KeyError):
                continue
            except OSError as exc:
                raise FaultEvidenceError(
                    "cannot prove ENOSPC run-process absence"
                ) from exc
            if not isinstance(raw, bytes) or len(raw) > 256 * 1024:
                raise FaultEvidenceError("live process environment is oversized")
            fields = raw.split(b"\0")
            if b"FORT_GYM_RUN_ID=" + expected in fields:
                matches.append(pid)
        return tuple(matches)

    def _load_launch_and_registry(
        self,
        run_id: str,
        *,
        runtime_fault_role: str | None,
        workspace_fault_role: str | None,
        counterpart_run_id: str | None,
    ) -> tuple[Mapping[str, Any], dict[str, Any]]:
        if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
            raise ValueError("run_id must be filesystem-safe")
        launch = self._read_json(
            self.control_root / run_id / "launch.json", "service launch"
        )
        allowed_launch_keys = {
            "schema",
            "run_id",
            "created_at",
            "contract",
            "request",
        }
        observed_launch_keys = set(launch)
        if runtime_fault_role is not None and workspace_fault_role is not None:
            raise FaultEvidenceError("fault profile families cannot be combined")
        expected_launch_keys = set(allowed_launch_keys)
        if runtime_fault_role is not None:
            expected_launch_keys.add("runtime_fault_profile")
        if workspace_fault_role is not None:
            expected_launch_keys.add("workspace_fault_profile")
        if observed_launch_keys != expected_launch_keys:
            raise FaultEvidenceError("service launch fields differ")
        if (
            launch.get("schema") != "fortgym.m1b-service-launch/v1"
            or launch.get("run_id") != run_id
            or not isinstance(launch.get("created_at"), str)
        ):
            raise FaultEvidenceError("service launch identity differs")
        contract = _mapping("launch contract", launch.get("contract"))
        _validate_canonical_launch_contract(
            contract,
            run_id=run_id,
            expected_control_root=self.control_root,
            expected_db_path=self.db_path,
            expected_artifacts_root=self.artifacts_root,
        )
        _validate_runtime_fault_profile_launch(
            launch,
            contract=contract,
            expected_role=runtime_fault_role,
            expected_counterpart_run_id=counterpart_run_id,
            control_root=self.control_root,
            db_path=self.db_path,
            artifacts_root=self.artifacts_root,
            read_bytes=self._read_bytes,
            path_exists=self._path_exists,
        )
        _validate_workspace_fault_profile_launch(
            launch,
            contract=contract,
            expected_role=workspace_fault_role,
            expected_counterpart_run_id=counterpart_run_id,
            control_root=self.control_root,
            db_path=self.db_path,
            artifacts_root=self.artifacts_root,
            read_bytes=self._read_bytes,
            path_exists=self._path_exists,
        )
        request = _mapping("launch request", launch.get("request"))
        _exact_keys(
            "launch request",
            request,
            {
                "max_steps",
                "ticks_per_step",
                "evaluation_protocol",
                "preserve_save",
                "memory_window",
                "safe",
            },
        )
        max_steps = request.get("max_steps")
        ticks_per_step = request.get("ticks_per_step")
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps <= 0
            or isinstance(ticks_per_step, bool)
            or not isinstance(ticks_per_step, int)
            or ticks_per_step <= 0
            or max_steps > 20
            or ticks_per_step > 200
            or request.get("memory_window") != 0
            or request.get("safe") is not True
            or not isinstance(request.get("preserve_save"), bool)
            or (
                request.get("evaluation_protocol") is not None
                and not isinstance(request.get("evaluation_protocol"), str)
            )
        ):
            raise FaultEvidenceError("launch request exceeds frozen M1b bounds")
        registry = self._registry_row(run_id)
        expected_registry = {
            "run_id": run_id,
            "backend": contract["backend"],
            "model": contract["model"],
            "max_steps": max_steps,
            "ticks_per_step": ticks_per_step,
            "seed_save": contract["seed"]["seed_save"],
            "runtime_save": contract["seed"]["runtime_save"],
            "preserve_save": 1 if request["preserve_save"] else 0,
            "evaluation_protocol": request["evaluation_protocol"],
            "supervision_mode": "m1b-process",
            "artifacts_dir": str(self.artifacts_root / run_id),
            "trace_path": str(self.artifacts_root / run_id / "trace.jsonl"),
        }
        if any(registry.get(key) != value for key, value in expected_registry.items()):
            raise FaultEvidenceError("registry row differs from canonical launch")
        if registry["status"] not in {"pending", "running", "paused"}:
            raise FaultEvidenceError("registry run is not active")
        step = registry["step"]
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or step < 0
            or step > max_steps
        ):
            raise FaultEvidenceError("registry step is outside the launch bounds")
        return contract, registry

    def _validate_live_enospc_workspace(
        self,
        *,
        run_id: str,
        contract: Mapping[str, Any],
        workspace: Path,
        peer_run_id: str,
    ) -> None:
        receipt = self._read_json(
            self.control_root / run_id / "prelaunch-enospc-workspace.json",
            "prelaunch ENOSPC workspace receipt",
        )
        target = PrelaunchEnospcTarget(
            run_id=run_id,
            contract_sha256=str(contract["contract_sha256"]),
            nonce=str(contract["rpc"]["nonce"]),
            cohort_sha256=str(contract["cotenancy"]["cohort_sha256"]),
            peer_run_id=peer_run_id,
            db_path=self.db_path,
            workspace=workspace,
            control_root=self.control_root,
        )
        _validate_prelaunch_enospc_receipt(receipt, target)
        marker_path = workspace / ".fortgym-m1b-workspace-owner.json"
        marker = self._read_json(marker_path, "ENOSPC workspace owner marker")
        _validate_workspace_marker(marker, target, peer_run_id=peer_run_id)
        if receipt.get("marker_sha256") != _payload_sha256(marker):
            raise FaultEvidenceError("ENOSPC workspace marker digest differs")
        _validate_private_tmpfs_mount(
            self._mount_probe(workspace),
            target,
            source=f"fortgym-m1b-enospc-{run_id}",
        )

    def _registry_row(self, run_id: str) -> dict[str, Any]:
        if not self._path_exists(self.db_path):
            raise OwnedRunEvidencePending("run registry database is absent")
        uri = f"{self.db_path.as_uri()}?mode=ro"
        try:
            connection = self._sqlite_connect(uri, uri=True, timeout=0)
        except sqlite3.Error as exc:
            raise FaultEvidenceError("run registry database is unreadable") from exc
        try:
            row = connection.execute(
                "SELECT run_id, backend, model, max_steps, ticks_per_step, "
                "status, step, seed_save, runtime_save, preserve_save, "
                "evaluation_protocol, supervision_mode, artifacts_dir, trace_path "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise FaultEvidenceError("run registry query failed") from exc
        finally:
            connection.close()
        if row is None:
            raise OwnedRunEvidencePending("run registry row is absent")
        values = tuple(row)
        names = (
            "run_id",
            "backend",
            "model",
            "max_steps",
            "ticks_per_step",
            "status",
            "step",
            "seed_save",
            "runtime_save",
            "preserve_save",
            "evaluation_protocol",
            "supervision_mode",
            "artifacts_dir",
            "trace_path",
        )
        if len(values) != len(names):
            raise FaultEvidenceError("run registry row shape differs")
        return dict(zip(names, values, strict=True))

    def _docker_inspection(self, container_id: str) -> Mapping[str, Any]:
        argv = (_DOCKER, "inspect", "--type", "container", container_id)
        result = self._runner.run(argv, timeout_seconds=10.0)
        if (
            not isinstance(result, FaultCommandResult)
            or result.argv != argv
            or result.returncode != 0
        ):
            raise OwnedRunEvidencePending("exact Docker container is not inspectable")
        stdout = _bounded_capture(result.stdout)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise FaultEvidenceError("Docker inspect returned invalid JSON") from exc
        if not isinstance(payload, list) or len(payload) != 1:
            raise FaultEvidenceError("Docker inspect must return one exact container")
        return _mapping("Docker inspection", payload[0])

    def _read_json(self, path: Path, label: str) -> Mapping[str, Any]:
        if not self._path_exists(path):
            raise OwnedRunEvidencePending(f"{label} is absent")
        raw = self._read_bounded(path, 256 * 1024)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultEvidenceError(f"{label} is invalid JSON") from exc
        return _mapping(label, value)

    def _read_jsonl(self, path: Path, label: str) -> list[Mapping[str, Any]]:
        if not self._path_exists(path):
            raise OwnedRunEvidencePending(f"{label} is absent")
        raw = self._read_bounded(path, 2 * 1024 * 1024)
        if not raw.endswith(b"\n"):
            raise FaultEvidenceError(f"{label} is partial")
        rows: list[Mapping[str, Any]] = []
        for line in raw.splitlines():
            if len(line) > 64 * 1024:
                raise FaultEvidenceError(f"{label} row is oversized")
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FaultEvidenceError(f"{label} is invalid JSONL") from exc
            rows.append(_mapping(f"{label} row", value))
        return rows

    def _read_bounded(self, path: Path, maximum: int) -> bytes:
        try:
            raw = self._read_bytes(path)
        except FileNotFoundError as exc:
            raise OwnedRunEvidencePending(
                f"required evidence is absent: {path}"
            ) from exc
        if not isinstance(raw, bytes) or len(raw) > maximum:
            raise FaultEvidenceError(f"required evidence is oversized: {path}")
        return raw


class BarrierProbe(Protocol):
    def __call__(self, run: OwnedRun) -> Mapping[str, Any] | None: ...


class OwnershipProbe(Protocol):
    def __call__(self, run: OwnedRun) -> Mapping[str, Any]: ...


class FaultStateProbe(Protocol):
    def __call__(
        self, gate: FaultGate, run: OwnedRun, phase: str
    ) -> Mapping[str, Any] | None: ...


class CanaryProbe(Protocol):
    def __call__(self, canary: ProtectedCanary) -> Mapping[str, Any]: ...


class DaemonRestartCallback(Protocol):
    def __call__(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class FaultInjectionResult:
    """Completed observation; deliberately contains no terminal class."""

    gate: FaultGate
    journal_path: Path
    observation: Mapping[str, Any]

    @property
    def classifier_evidence(self) -> Mapping[str, Any]:
        payload = _mapping("completed payload", self.observation.get("payload"))
        return _mapping("classifier_evidence", payload.get("classifier_evidence"))


class M1BFaultDriver:
    """Coordinate one explicitly authorized M1b host-side fault attempt."""

    def __init__(
        self,
        *,
        barrier_probe: BarrierProbe,
        cohort_start_probe: BarrierProbe | None = None,
        ownership_probe: OwnershipProbe,
        state_probe: FaultStateProbe,
        canary_probe: CanaryProbe,
        state_diagnostic_probe: Callable[[], Mapping[str, Any]] | None = None,
        command_runner: FaultCommandRunner | None = None,
        daemon_restart_callback: DaemonRestartCallback | None = None,
        barrier_poll_attempts: int = 120,
        state_poll_attempts: int = 120,
        peer_state_poll_attempts: int | None = None,
        poll_interval_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        peer_attempts = state_poll_attempts if peer_state_poll_attempts is None else peer_state_poll_attempts
        for name, value in (
            ("barrier_poll_attempts", barrier_poll_attempts),
            ("state_poll_attempts", state_poll_attempts),
            ("peer_state_poll_attempts", peer_attempts),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        poll_interval = _finite_nonnegative_seconds(
            poll_interval_seconds, "poll_interval_seconds"
        )
        self._barrier_probe = barrier_probe
        self._cohort_start_probe = cohort_start_probe
        self._ownership_probe = ownership_probe
        self._state_probe = state_probe
        self._state_diagnostic_probe = state_diagnostic_probe
        self._canary_probe = canary_probe
        self._command_runner = command_runner or SubprocessFaultCommandRunner()
        self._daemon_restart_callback = daemon_restart_callback
        self._barrier_poll_attempts = barrier_poll_attempts
        self._state_poll_attempts = state_poll_attempts
        self._peer_state_poll_attempts = peer_attempts
        self._poll_interval_seconds = poll_interval
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic

    def inject(
        self,
        *,
        authorization: FaultTestAuthorization,
        target: OwnedRun,
        peer: OwnedRun,
        protected_canaries: Sequence[ProtectedCanary] = (),
    ) -> FaultInjectionResult:
        """Attempt one gate after exact durable barrier and ownership proof.

        The token is consumed before evidence polling, so a failed or partial
        attempt cannot accidentally be replayed.  A new explicit authorization
        is required for any retry.
        """

        if not isinstance(authorization, FaultTestAuthorization):
            raise FaultAuthorizationError(
                "ordinary mode rejects every fault knob; an opaque test capability is required"
            )
        if authorization.gate is FaultGate.OOM:
            raise FaultAuthorizationError(
                "OOM is create-time only and requires PreReadinessOomMonitor; "
                "a post-readiness OwnedRun cannot authorize it"
            )
        if not isinstance(target, OwnedRun) or not isinstance(peer, OwnedRun):
            raise TypeError("target and peer must be OwnedRun instances")
        gate = authorization._consume(
            target_run_id=target.run_id,
            peer_run_id=peer.run_id,
        )
        canaries = tuple(protected_canaries)
        if any(not isinstance(canary, ProtectedCanary) for canary in canaries):
            raise TypeError("protected_canaries must contain ProtectedCanary values")
        self._validate_run_pair(target, peer, canaries)

        journal_path = fault_observation_journal_path(
            target.control_root, target.run_id
        )
        self._validate_control_path(journal_path, target, peer, canaries)
        writer = _ObservationJournal(
            journal_path,
            gate=gate,
            target=target,
            now=self._now,
        )
        writer.append(
            "authorized",
            {
                "target": target.public_identity(),
                "peer": peer.public_identity(),
                "protected_canary_sha256": [
                    canary.identity_sha256 for canary in canaries
                ],
            },
        )

        try:
            if gate is FaultGate.OOM:
                target_barrier, peer_barrier = self._wait_for_oom_cohort_start(
                    target, peer
                )
                barrier_phase = "cohort_start_confirmed"
            else:
                target_barrier, peer_barrier = self._wait_for_barrier(target, peer)
                barrier_phase = "barrier_confirmed"
            writer.append(
                barrier_phase,
                {
                    "target": _public_barrier(target_barrier),
                    "peer": _public_barrier(peer_barrier),
                },
            )

            target_ownership = self._verified_ownership(
                target, gate=gate, role="target"
            )
            peer_ownership = self._verified_ownership(peer, gate=gate, role="peer")
            canaries_before = self._observe_canaries(canaries)
            writer.append(
                "ownership_confirmed",
                {
                    "target": _public_ownership(target_ownership),
                    "peer": _public_ownership(peer_ownership),
                    "canaries": canaries_before,
                },
            )

            before = self._wait_for_state(gate, target, "before")
            writer.append("before_observed", {"state": _public_state(before)})

            # Re-probe both exact identities immediately before the side effect.
            # Nothing caller-controlled runs between this check and action setup.
            self._verified_ownership(target, gate=gate, role="target")
            self._verified_ownership(peer, gate=gate, role="peer")
            action = self._action_for(gate, target)
            self._assert_action_avoids_canaries(action, canaries)
            writer.append("action_armed", action.public_payload())

            action_started = _finite_nonnegative_seconds(
                self._monotonic(), "fault action monotonic sample"
            )
            action_result = self._perform_action(gate, action)
            writer.append("action_attempted", action_result)

            after = self._wait_for_state(gate, target, "after")
            target_detection_seconds = (
                _finite_nonnegative_seconds(
                    self._monotonic(), "fault target monotonic sample"
                )
                - action_started
            )
            if target_detection_seconds < 0:
                raise FaultEvidenceError("monotonic fault timing moved backwards")
            if gate is FaultGate.DF_KILL and target_detection_seconds > 10.0:
                raise FaultEvidenceError(
                    "DF-KILL detection exceeded the frozen 10 second bound"
                )
            peer_after = self._wait_for_state(gate, peer, "peer_after")
            all_required_observations_seconds = (
                _finite_nonnegative_seconds(
                    self._monotonic(), "fault completion monotonic sample"
                )
                - action_started
            )
            if all_required_observations_seconds < target_detection_seconds:
                raise FaultEvidenceError(
                    "monotonic reconciliation timing moved backwards"
                )
            if (
                gate is FaultGate.DAEMON_RESTART
                and all_required_observations_seconds > 120.0
            ):
                raise FaultEvidenceError(
                    "DAEMON-RESTART reconciliation exceeded the frozen 120 second bound"
                )
            classifier_evidence = _validate_fault_facts(
                gate,
                target,
                before=_mapping("before facts", before.get("facts")),
                after=_mapping("after facts", after.get("facts")),
                peer_after=_mapping("peer-after facts", peer_after.get("facts")),
                action=action_result,
            )
            canaries_after = self._observe_canaries(canaries)
            if canaries_after != canaries_before:
                raise FaultEvidenceError("protected canary identity changed")

            completed_payload = {
                "target": target.public_identity(),
                "peer": peer.public_identity(),
                "barrier": {
                    "target": _public_barrier(target_barrier),
                    "peer": _public_barrier(peer_barrier),
                },
                "ownership": {
                    "target": _public_ownership(target_ownership),
                    "peer": _public_ownership(peer_ownership),
                },
                "before": _public_state(before),
                "action": action_result,
                "after": _public_state(after),
                "peer_after": _public_state(peer_after),
                "canaries": {
                    "before": canaries_before,
                    "after": canaries_after,
                    "all_untouched": True,
                },
                "timing": {
                    "target_detection_seconds": target_detection_seconds,
                    "all_required_observations_seconds": (
                        all_required_observations_seconds
                    ),
                },
                "classifier_evidence_schema": _CLASSIFIER_EVIDENCE_SCHEMA,
                "classifier_evidence": classifier_evidence,
                "pending_external_checks": _pending_external_checks(gate),
            }
            completed = writer.append("completed", completed_payload)
            return FaultInjectionResult(
                gate=gate,
                journal_path=journal_path,
                observation=MappingProxyType(completed),
            )
        except Exception as exc:
            try:
                writer.append(
                    "failed",
                    {
                        "error_type": type(exc).__name__,
                        "error": _bounded_string(
                            str(exc) or type(exc).__name__,
                            "failure message",
                            maximum=500,
                        ),
                    },
                )
            except Exception as journal_exc:
                raise FaultEvidenceError(
                    "fault attempt failed and its failure record could not be persisted"
                ) from journal_exc
            raise

    def _validate_run_pair(
        self,
        target: OwnedRun,
        peer: OwnedRun,
        canaries: Sequence[ProtectedCanary],
    ) -> None:
        if target.run_id == peer.run_id:
            raise FaultEvidenceError("target and peer run identities must differ")
        if target.cohort_sha256 != peer.cohort_sha256:
            raise FaultEvidenceError("target and peer cohort identities differ")
        if target.container_id == peer.container_id:
            raise FaultEvidenceError("target and peer container identities collide")
        worker_pids = (
            target.runtime_host_pid,
            target.harness_pid,
            peer.runtime_host_pid,
            peer.harness_pid,
        )
        if len(set(worker_pids)) != len(worker_pids):
            raise FaultEvidenceError("target and peer process identities collide")
        if set(worker_pids) & {target.supervisor_pid, peer.supervisor_pid}:
            raise FaultEvidenceError(
                "runtime or harness PID collides with a supervisor"
            )
        if _paths_overlap(target.workspace, peer.workspace):
            raise FaultEvidenceError("target and peer workspaces overlap")
        if len({canary.name for canary in canaries}) != len(canaries):
            raise FaultEvidenceError("protected canary names must be unique")
        protected_containers = {canary.container_id for canary in canaries}
        if target.container_id in protected_containers or peer.container_id in (
            protected_containers
        ):
            raise FaultEvidenceError("run container collides with a protected canary")
        protected_pids = {pid for canary in canaries for pid in canary.process_ids}
        if protected_pids & {
            target.runtime_host_pid,
            target.harness_pid,
            target.supervisor_pid,
            peer.runtime_host_pid,
            peer.harness_pid,
            peer.supervisor_pid,
        }:
            raise FaultEvidenceError("run PID collides with a protected canary")
        for canary in canaries:
            if _paths_overlap(target.workspace, canary.workspace) or _paths_overlap(
                peer.workspace, canary.workspace
            ):
                raise FaultEvidenceError("run workspace overlaps a protected canary")

    @staticmethod
    def _validate_control_path(
        journal_path: Path,
        target: OwnedRun,
        peer: OwnedRun,
        canaries: Sequence[ProtectedCanary],
    ) -> None:
        for workspace in (
            target.workspace,
            peer.workspace,
            *(canary.workspace for canary in canaries),
        ):
            if journal_path == workspace or _is_relative_to(journal_path, workspace):
                raise FaultEvidenceError(
                    "fault control evidence must remain outside every run workspace"
                )

    def _wait_for_barrier(
        self, target: OwnedRun, peer: OwnedRun
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        for attempt in range(self._barrier_poll_attempts):
            target_record = self._barrier_probe(target)
            peer_record = self._barrier_probe(peer)
            if target_record is not None and peer_record is not None:
                validated_target = _validate_barrier_record(target_record, target)
                validated_peer = _validate_barrier_record(peer_record, peer)
                if validated_target.get("cohort_sha256") != validated_peer.get(
                    "cohort_sha256"
                ):
                    raise FaultEvidenceError("barrier cohort receipts differ")
                return validated_target, validated_peer
            if attempt + 1 < self._barrier_poll_attempts:
                self._sleep(self._poll_interval_seconds)
        raise FaultEvidenceTimeout(
            "exact durable target+peer step-2 barrier evidence was not observed"
        )

    def _wait_for_oom_cohort_start(
        self, target: OwnedRun, peer: OwnedRun
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        probe = self._cohort_start_probe
        if probe is None:
            raise FaultEvidenceError(
                "OOM requires durable create-time target+peer cohort-start evidence"
            )
        for attempt in range(self._barrier_poll_attempts):
            target_record = probe(target)
            peer_record = probe(peer)
            if target_record is not None and peer_record is not None:
                validated_target = _validate_cohort_start_record(
                    target_record, target, role="target"
                )
                validated_peer = _validate_cohort_start_record(
                    peer_record, peer, role="peer"
                )
                if validated_target.get("cohort_sha256") != validated_peer.get(
                    "cohort_sha256"
                ):
                    raise FaultEvidenceError("OOM cohort-start receipts differ")
                return validated_target, validated_peer
            if attempt + 1 < self._barrier_poll_attempts:
                self._sleep(self._poll_interval_seconds)
        raise FaultEvidenceTimeout(
            "durable create-time target+peer OOM cohort-start evidence was not observed"
        )

    def _verified_ownership(
        self, run: OwnedRun, *, gate: FaultGate, role: str
    ) -> Mapping[str, Any]:
        record = _validate_ownership_record(self._ownership_probe(run), run)
        container = _mapping("owned container", record.get("container"))
        host_config = _mapping(
            "owned container host_config", container.get("host_config")
        )
        expected_memory = (
            _OOM_MEMORY_BYTES
            if gate is FaultGate.OOM and role == "target"
            else _NORMAL_MEMORY_BYTES
        )
        expected_profile = (
            _OOM_FAULT_PROFILE if gate is FaultGate.OOM and role == "target" else None
        )
        if (
            host_config.get("memory_bytes") != expected_memory
            or host_config.get("memory_swap_bytes") != expected_memory
            or host_config.get("fault_profile") != expected_profile
        ):
            raise FaultEvidenceError(
                "runtime memory/profile does not match the prelaunch fault contract"
            )
        workspace = _mapping("workspace ownership", record.get("workspace_owner"))
        if (
            gate is FaultGate.ENOSPC
            and role == "target"
            and (
                workspace.get("filesystem") != "tmpfs"
                or workspace.get("size_bytes") != MAX_WORKSPACE_FAULT_BYTES
            )
        ):
            raise FaultEvidenceError(
                "ENOSPC requires an exact private 16 MiB tmpfs run workspace"
            )
        return record

    def _wait_for_state(
        self, gate: FaultGate, run: OwnedRun, phase: str
    ) -> Mapping[str, Any]:
        attempts = self._peer_state_poll_attempts if phase == "peer_after" else self._state_poll_attempts
        for attempt in range(attempts):
            record = self._state_probe(gate, run, phase)
            if record is not None:
                return _validate_state_record(record, gate, run, phase)
            if attempt + 1 < attempts:
                self._sleep(self._poll_interval_seconds)
        detail = ""
        if phase == "peer_after" and self._state_diagnostic_probe is not None:
            detail = "; peer health diagnostics=" + json.dumps(
                self._state_diagnostic_probe(), sort_keys=True, separators=(",", ":")
            )
        raise FaultEvidenceTimeout(
            f"required explicit {gate.value} {phase} observation was not observed{detail}"
        )

    def _observe_canaries(
        self, canaries: Sequence[ProtectedCanary]
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for canary in canaries:
            record = _mapping("canary observation", self._canary_probe(canary))
            _exact_keys(
                "canary observation",
                record,
                {"schema", "name", "identity_sha256", "present"},
            )
            if (
                record.get("schema") != CANARY_OBSERVATION_SCHEMA
                or record.get("name") != canary.name
                or record.get("identity_sha256") != canary.identity_sha256
                or record.get("present") is not True
            ):
                raise FaultEvidenceError("protected canary observation differs")
            observations.append(dict(record))
        return observations

    @staticmethod
    def _action_for(gate: FaultGate, target: OwnedRun) -> _FaultAction:
        if gate is FaultGate.DF_KILL:
            argv = (
                _KILL,
                "-KILL",
                "--",
                str(target.runtime_host_pid),
            )
            return _FaultAction("command", argv, 10.0)
        if gate is FaultGate.HARNESS_KILL:
            return _FaultAction(
                "command", (_KILL, "-KILL", "--", str(target.harness_pid)), 10.0
            )
        if gate is FaultGate.OOM:
            return _FaultAction(
                "prelaunched_fault_profile",
                (),
                0.0,
            )
        if gate is FaultGate.ENOSPC:
            fault_path = (target.workspace / ".fortgym-m1b-enospc.fill").resolve(
                strict=False
            )
            if not _is_relative_to(fault_path, target.workspace):
                raise FaultActionError(
                    "ENOSPC fault path escaped the private workspace"
                )
            return _FaultAction(
                "command",
                (
                    str(Path(sys.executable).resolve()),
                    "-I",
                    "-c",
                    _ENOSPC_FILL_PROGRAM,
                    str(fault_path),
                    str(MAX_WORKSPACE_FAULT_BYTES),
                ),
                30.0,
            )
        if gate is FaultGate.CONTAINER_RESTART:
            return _FaultAction(
                "command",
                (_DOCKER, "restart", "--time", "0", target.container_id),
                60.0,
            )
        if gate is FaultGate.DAEMON_RESTART:
            return _FaultAction("external_host_callback", (), 120.0)
        raise AssertionError(f"unhandled fault gate {gate!r}")

    @staticmethod
    def _assert_action_avoids_canaries(
        action: _FaultAction, canaries: Sequence[ProtectedCanary]
    ) -> None:
        tokens = set(action.argv)
        for canary in canaries:
            if canary.container_id in tokens or any(
                str(pid) in tokens for pid in canary.process_ids
            ):
                raise FaultActionError("fault command targets a protected canary")
            for token in action.argv:
                candidate = token.removeprefix("of=")
                if candidate == token or not candidate.startswith("/"):
                    continue
                path = Path(candidate).resolve(strict=False)
                if path == canary.workspace or _is_relative_to(path, canary.workspace):
                    raise FaultActionError(
                        "fault command writes inside a protected canary workspace"
                    )

    def _perform_action(self, gate: FaultGate, action: _FaultAction) -> dict[str, Any]:
        if action.kind == "external_host_callback":
            callback = self._daemon_restart_callback
            if callback is None:
                raise FaultActionError(
                    "DAEMON-RESTART requires an external host-controller callback"
                )
            raw = _mapping("daemon restart callback result", callback())
            _validate_daemon_callback_fields(raw)
            if (
                raw.get("schema") != DAEMON_RESTART_CALLBACK_SCHEMA
                or raw.get("host_controller") is not True
                or raw.get("inside_container") is not False
                or raw.get("invoked") is not True
            ):
                raise FaultActionError(
                    "Docker daemon restart was not proven to run from the host controller"
                )
            return {"kind": action.kind, "callback": dict(raw)}
        if action.kind == "prelaunched_fault_profile":
            return {
                "kind": action.kind,
                "profile": _OOM_FAULT_PROFILE,
                "memory_bytes": _OOM_MEMORY_BYTES,
                "late_runtime_mutation": False,
                "argv": [],
                "shell": False,
            }

        result = self._command_runner.run(
            action.argv, timeout_seconds=action.timeout_seconds
        )
        if not isinstance(result, FaultCommandResult):
            raise FaultActionError("fault command runner returned an invalid result")
        if tuple(result.argv) != action.argv:
            raise FaultActionError(
                "fault command runner returned evidence for different argv"
            )
        if isinstance(result.returncode, bool) or not isinstance(
            result.returncode, int
        ):
            raise FaultActionError("fault command returncode is invalid")
        stdout = _bounded_capture(result.stdout)
        stderr = _bounded_capture(result.stderr)
        if gate is not FaultGate.ENOSPC and result.returncode != 0:
            raise FaultActionError(
                f"exact {gate.value} action failed with return code {result.returncode}"
            )
        if gate is FaultGate.ENOSPC and result.returncode != 0:
            raise FaultActionError(
                f"bounded ENOSPC fill failed unexpectedly with return code {result.returncode}"
            )
        payload = {
            "kind": action.kind,
            "argv": list(action.argv),
            "shell": False,
            "timeout_seconds": action.timeout_seconds,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        if gate is FaultGate.ENOSPC:
            try:
                enospc = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise FaultActionError(
                    "bounded ENOSPC fill returned invalid structured evidence"
                ) from exc
            evidence = _mapping("bounded ENOSPC fill evidence", enospc)
            _exact_keys(
                "bounded ENOSPC fill evidence",
                evidence,
                {"errno", "fault_bytes", "maximum_fault_bytes"},
            )
            fault_bytes = _nonnegative_int(
                evidence.get("fault_bytes"), "bounded ENOSPC fault bytes"
            )
            if (
                evidence.get("errno") != 28
                or evidence.get("maximum_fault_bytes") != MAX_WORKSPACE_FAULT_BYTES
                or fault_bytes > MAX_WORKSPACE_FAULT_BYTES
            ):
                raise FaultActionError(
                    "bounded fill did not prove errno 28 within the 16 MiB cap"
                )
            payload["enospc"] = dict(evidence)
        return payload


@dataclass(frozen=True)
class _ArmedOomIdentity:
    container_id: str
    container_init_host_pid: int
    container_cgroup_path: str


class PreReadinessOomMonitor:
    """Arm and finish the create-time 256 MiB OOM gate before child launch.

    The runtime controller starts the created target into its entrypoint hold,
    exact-validates the durable hold-ready receipt, and only then calls
    :meth:`arm` with its fsynced ``container-created.json`` mapping.  It calls
    :meth:`finalize` only after fsyncing the exact stopped-container OOM
    receipt.  The monitor owns no Docker mutation.  It records target-local
    cgroup and global counters, waits for a separately normal-cap peer to
    become fully owned and healthy before authorizing release, and emits the
    same strict classifier subset consumed after supervisor cleanup.
    """

    def __init__(
        self,
        *,
        authorization: FaultTestAuthorization,
        target: PreReadinessOomTarget,
        peer_run_id: str,
        peer_loader: Callable[[], OwnedRun | None],
        peer_cohort_start_probe: BarrierProbe,
        peer_ownership_probe: OwnershipProbe,
        peer_state_probe: FaultStateProbe,
        canary_probe: CanaryProbe,
        protected_canaries: Sequence[ProtectedCanary] = (),
        command_runner: FaultCommandRunner | None = None,
        read_bytes: Callable[[Path], bytes] | None = None,
        read_text: Callable[[Path], str] | None = None,
        path_exists: Callable[[Path], bool] = Path.exists,
        peer_poll_attempts: int = (int(_DEFAULT_RUNTIME_READINESS_SECONDS / 0.25) + 1),
        poll_interval_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(authorization, FaultTestAuthorization):
            raise FaultAuthorizationError(
                "pre-readiness OOM requires the opaque test capability"
            )
        if authorization.gate is not FaultGate.OOM:
            raise FaultAuthorizationError(
                "pre-readiness monitor accepts only the exact OOM gate"
            )
        if not isinstance(target, PreReadinessOomTarget):
            raise TypeError("target must be PreReadinessOomTarget")
        if (
            authorization.target_run_id != target.run_id
            or authorization.peer_run_id != peer_run_id
            or target.run_id == peer_run_id
            or not _RUN_ID_RE.fullmatch(peer_run_id)
        ):
            raise FaultAuthorizationError(
                "pre-readiness OOM capability does not bind this target and peer"
            )
        for name, value in (("peer_poll_attempts", peer_poll_attempts),):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        poll_interval = _finite_nonnegative_seconds(
            poll_interval_seconds, "poll_interval_seconds"
        )
        canaries = tuple(protected_canaries)
        if any(not isinstance(canary, ProtectedCanary) for canary in canaries):
            raise TypeError("protected_canaries must contain ProtectedCanary values")
        if len({canary.name for canary in canaries}) != len(canaries):
            raise FaultEvidenceError("protected canary names must be unique")
        for canary in canaries:
            if _paths_overlap(target.workspace, canary.workspace):
                raise FaultEvidenceError(
                    "OOM target workspace overlaps a protected canary"
                )
        self._authorization = authorization
        self.target = target
        self.peer_run_id = peer_run_id
        self._peer_loader = peer_loader
        self._peer_cohort_start_probe = peer_cohort_start_probe
        self._peer_ownership_probe = peer_ownership_probe
        self._peer_state_probe = peer_state_probe
        self._canary_probe = canary_probe
        self._canaries = canaries
        self._runner = command_runner or SubprocessFaultCommandRunner()
        self._read_bytes = read_bytes or Path.read_bytes
        self._read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self._path_exists = path_exists
        self._peer_poll_attempts = peer_poll_attempts
        self._poll_interval_seconds = poll_interval
        self._peer_wait_bound_seconds = max(
            0.0, (peer_poll_attempts - 1) * self._poll_interval_seconds
        )
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._writer = _ObservationJournal(
            fault_observation_journal_path(target.control_root, target.run_id),
            gate=FaultGate.OOM,
            target=target,  # type: ignore[arg-type] - same journal identity surface
            now=self._now,
        )
        self._armed: _ArmedOomIdentity | None = None
        self._target_barrier: Mapping[str, Any] | None = None
        self._target_ownership: Mapping[str, Any] | None = None
        self._peer: OwnedRun | None = None
        self._peer_barrier: Mapping[str, Any] | None = None
        self._peer_ownership: Mapping[str, Any] | None = None
        self._peer_before_release: Mapping[str, Any] | None = None
        self._before: Mapping[str, Any] | None = None
        self._canaries_before: list[dict[str, Any]] | None = None
        self._action_started: float | None = None
        self._finalized = False
        self._live_oom_events: dict[str, int] | None = None
        self._counter_sampler_stop = threading.Event()
        self._counter_sampler: threading.Thread | None = None
        self._sampled_oom: tuple[dict[str, int], int] | None = None

    def start_counter_capture(self) -> None:
        """Sample the armed kernel path independently of slow Docker/RPC calls."""
        if self._armed is None or self._before is None or self._finalized:
            raise FaultAuthorizationError("OOM counter sampling requires an armed monitor")
        if self._counter_sampler is not None:
            raise FaultAuthorizationError("OOM counter sampler already started")
        cgroup_path = self._armed.container_cgroup_path
        baseline = self._before["facts"]["cgroup_memory_events"]["oom_kill"]
        # A synchronous read proves availability before the release is written.
        self._memory_events(cgroup_path)

        def sample() -> None:
            deadline = time.monotonic() + _DEFAULT_RUNTIME_READINESS_SECONDS
            while not self._counter_sampler_stop.is_set() and time.monotonic() < deadline:
                try:
                    events = self._memory_events(cgroup_path)
                    if _counter_delta(baseline, events["oom_kill"], "sampled target OOM") > 0:
                        self._sampled_oom = (dict(events), self._host_oom_counter())
                        return
                except (OSError, FaultEvidenceError):
                    # Absence or invalid counters never become synthetic proof.
                    # Finalize still requires a genuine captured sample or read.
                    return
                self._counter_sampler_stop.wait(0.01)

        self._counter_sampler = threading.Thread(
            target=sample, name=f"oom-counters-{self.target.run_id}", daemon=True,
        )
        self._counter_sampler.start()

    def stop_counter_capture(self) -> None:
        self._counter_sampler_stop.set()
        if self._counter_sampler is not None:
            self._counter_sampler.join(timeout=1.0)
            if self._counter_sampler.is_alive():
                raise FaultEvidenceError("OOM counter sampler did not stop")

    def _retain_sampled_oom(self) -> None:
        if self._sampled_oom is None or self._live_oom_events is not None:
            return
        assert self._armed is not None
        events, host_counter = self._sampled_oom
        self._writer.append("oom_counters_captured", {
            "container_id": self._armed.container_id,
            "container_cgroup_path": self._armed.container_cgroup_path,
            "cgroup_memory_events": events,
            "host_oom_counter": host_counter,
        })
        self._live_oom_events = dict(events)

    def arm(self, container_created: Mapping[str, Any]) -> Mapping[str, Any]:
        """Bind the live target and durably capture its pre-OOM baseline."""

        if self._armed is not None or self._finalized:
            raise FaultAuthorizationError("pre-readiness OOM monitor is single-use")
        self._authorization._consume(
            target_run_id=self.target.run_id,
            peer_run_id=self.peer_run_id,
        )
        journal_path = self._writer.path
        if journal_path == self.target.workspace or _is_relative_to(
            journal_path, self.target.workspace
        ):
            raise FaultEvidenceError(
                "OOM control evidence must remain outside the run workspace"
            )
        try:
            durable_created = self._require_durable_runtime_receipt(
                "container-created.json",
                container_created,
                "runtime container-created receipt",
            )
            container_id, _ = _validate_container_created_receipt(
                durable_created,
                run_id=self.target.run_id,
                contract_sha256=self.target.contract_sha256,
                nonce=self.target.nonce,
                cohort_sha256=self.target.cohort_sha256,
                expected_fault_profile=_OOM_FAULT_PROFILE,
                expected_memory_bytes=_OOM_MEMORY_BYTES,
            )
            hold_ready = self._read_durable_runtime_receipt(
                "pre-readiness-oom-hold-ready.json",
                "pre-readiness OOM hold-ready receipt",
            )
            _validate_pre_readiness_oom_hold_ready(
                hold_ready,
                target=self.target,
            )
            self._writer.append(
                "authorized",
                {
                    "target": {
                        "identity_kind": "pre_readiness_oom",
                        "run_id": self.target.run_id,
                        "contract_sha256": self.target.contract_sha256,
                        "nonce_sha256": _nonce_sha256(self.target.nonce),
                        "cohort_sha256": self.target.cohort_sha256,
                        "container_name": self.target.container_name,
                    },
                    "peer_run_id": self.peer_run_id,
                    "protected_canary_sha256": [
                        canary.identity_sha256 for canary in self._canaries
                    ],
                },
            )
            inspection = self._docker_inspection(container_id)
            container_init_host_pid = _validate_live_oom_container_binding(
                inspection,
                target=self.target,
                container_id=container_id,
            )
            container_cgroup_path = _container_init_cgroup_identity(
                container_id=container_id,
                container_init_host_pid=container_init_host_pid,
                read_text=self._read_text,
                path_exists=self._path_exists,
            )
            armed = _ArmedOomIdentity(
                container_id=container_id,
                container_init_host_pid=container_init_host_pid,
                container_cgroup_path=container_cgroup_path,
            )
            target_barrier = _cohort_start_from_container_created(
                durable_created, self.target, role="target"
            )
            target_ownership = {
                "schema": "fortgym.m1b-pre-readiness-oom-ownership/v1",
                **self.target.public_identity(
                    container_id=container_id,
                    container_init_host_pid=container_init_host_pid,
                    container_cgroup_path=container_cgroup_path,
                ),
                "fault_profile": _OOM_FAULT_PROFILE,
                "memory_bytes": _OOM_MEMORY_BYTES,
                "memory_swap_bytes": _OOM_MEMORY_BYTES,
                "hold_ready_sha256": _payload_sha256(hold_ready),
            }
            before_facts = {
                "runtime_identity": container_id,
                "runtime_exit_code": None,
                "cgroup_memory_events": self._memory_events(container_cgroup_path),
                "host_oom_counter": self._host_oom_counter(),
                "unattributed_host_oom_delta": None,
            }
            before = _pre_readiness_oom_state(
                self.target,
                armed,
                phase="before",
                facts=before_facts,
            )
            canaries_before = self._observe_canaries()
            (
                peer,
                peer_barrier,
                peer_ownership,
                peer_before_release,
            ) = self._wait_for_peer_ready(armed)
            self._writer.append(
                "cohort_start_confirmed",
                {
                    "target": _public_barrier(target_barrier),
                    "peer": _public_barrier(peer_barrier),
                },
            )
            self._writer.append(
                "ownership_confirmed",
                {
                    "target": dict(target_ownership),
                    "peer": _public_ownership(peer_ownership),
                    "canaries": canaries_before,
                },
            )
            self._writer.append(
                "peer_ready_before_release",
                {"state": _public_state(peer_before_release)},
            )
            self._writer.append("before_observed", {"state": dict(before)})
            action = {
                "kind": "prelaunched_fault_profile",
                "profile": _OOM_FAULT_PROFILE,
                "memory_bytes": _OOM_MEMORY_BYTES,
                "late_runtime_mutation": False,
                "argv": [],
                "shell": False,
            }
            self._action_started = _finite_nonnegative_seconds(
                self._monotonic(), "OOM action monotonic sample"
            )
            self._writer.append("action_attempted", action)
            self._armed = armed
            self._target_barrier = target_barrier
            self._target_ownership = target_ownership
            self._peer = peer
            self._peer_barrier = peer_barrier
            self._peer_ownership = peer_ownership
            self._peer_before_release = peer_before_release
            self._before = before
            self._canaries_before = canaries_before
            return {
                "schema": PRE_READINESS_OOM_ARM_SCHEMA,
                "ok": True,
                "run_id": self.target.run_id,
                "contract_sha256": self.target.contract_sha256,
                "nonce_sha256": _nonce_sha256(self.target.nonce),
                "cohort_sha256": self.target.cohort_sha256,
                "container_id": container_id,
                "container_init_host_pid": container_init_host_pid,
                "container_cgroup_path": container_cgroup_path,
                "peer_run_id": peer.run_id,
                "peer_container_id": peer.container_id,
                "peer_readiness_sha256": _payload_sha256(
                    _public_state(peer_before_release)
                ),
                "journal_path": str(self._writer.path),
            }
        except Exception as exc:
            self._append_failure(exc)
            raise

    def capture_live_oom(self, inspection: Mapping[str, Any]) -> bool:
        """Capture kernel counters while the exact container init still holds them."""
        if self._armed is None or self._before is None or self._finalized:
            raise FaultAuthorizationError("live OOM capture requires an armed monitor")
        state = _mapping("live OOM container state", inspection.get("State"))
        if not isinstance(state.get("OOMKilled"), bool):
            raise FaultEvidenceError("live OOM container state is invalid")
        pid = _validate_container_inspection_identity(
            inspection, run_id=self.target.run_id,
            contract_sha256=self.target.contract_sha256, nonce=self.target.nonce,
            cohort_sha256=self.target.cohort_sha256,
            container_name=self.target.container_name, container_id=self._armed.container_id,
            expected_fault_profile=_OOM_FAULT_PROFILE, expected_memory_bytes=_OOM_MEMORY_BYTES,
            expected_running=True, expected_oom_killed=state["OOMKilled"], expected_exit_code=None,
        )
        if pid != self._armed.container_init_host_pid:
            raise FaultEvidenceError("live OOM container init changed")
        self._retain_sampled_oom()
        if self._live_oom_events is not None:
            return True
        events = self._memory_events(self._armed.container_cgroup_path)
        before = self._before["facts"]["cgroup_memory_events"]
        if _counter_delta(before["oom_kill"], events["oom_kill"], "live target OOM") < 1:
            return False
        self._writer.append("oom_counters_captured", {
            "container_id": self._armed.container_id,
            "container_cgroup_path": self._armed.container_cgroup_path,
            "cgroup_memory_events": events,
            "host_oom_counter": self._host_oom_counter(),
        })
        self._live_oom_events = dict(events)
        return True

    def finalize(self, pre_readiness_oom: Mapping[str, Any]) -> Mapping[str, Any]:
        """Finish target+peer evidence after the controller observes exact OOM."""

        self.stop_counter_capture()
        self._retain_sampled_oom()
        armed = self._armed
        if (
            armed is None
            or self._target_barrier is None
            or self._target_ownership is None
            or self._peer is None
            or self._peer_barrier is None
            or self._peer_ownership is None
            or self._peer_before_release is None
            or self._before is None
            or self._canaries_before is None
            or self._action_started is None
            or self._finalized
        ):
            raise FaultAuthorizationError(
                "pre-readiness OOM finalize requires one successful arm"
            )
        self._finalized = True
        try:
            durable_oom = self._require_durable_runtime_receipt(
                "pre-readiness-oom.json",
                pre_readiness_oom,
                "pre-readiness OOM receipt",
            )
            _validate_pre_readiness_oom_receipt(
                durable_oom,
                target=self.target,
                container_id=armed.container_id,
            )
            stopped = self._docker_inspection(armed.container_id)
            _validate_stopped_oom_container_binding(
                stopped,
                target=self.target,
                container_id=armed.container_id,
            )
            after_facts = {
                "runtime_identity": armed.container_id,
                "runtime_exit_code": 137,
                "cgroup_memory_events": (
                    dict(self._live_oom_events) if self._live_oom_events is not None
                    else self._memory_events(armed.container_cgroup_path)
                ),
                "host_oom_counter": self._host_oom_counter(),
                "unattributed_host_oom_delta": None,
            }
            before_facts = _mapping("OOM before facts", self._before.get("facts"))
            before_events = _memory_events(
                before_facts.get("cgroup_memory_events"),
                "pre-readiness OOM before",
            )
            after_events = _memory_events(
                after_facts.get("cgroup_memory_events"),
                "pre-readiness OOM after",
            )
            global_delta = _counter_delta(
                before_facts.get("host_oom_counter"),
                after_facts.get("host_oom_counter"),
                "global /proc/vmstat oom_kill",
            )
            target_local_delta = _counter_delta(
                before_events["oom_kill"],
                after_events["oom_kill"],
                "target memory.events.local oom_kill",
            )
            after_facts["unattributed_host_oom_delta"] = (
                global_delta - target_local_delta
            )
            after = _pre_readiness_oom_state(
                self.target,
                armed,
                phase="after",
                facts=after_facts,
            )
            target_detection_seconds = (
                _finite_nonnegative_seconds(
                    self._monotonic(), "OOM target monotonic sample"
                )
                - self._action_started
            )
            if target_detection_seconds < 0:
                raise FaultEvidenceError("monotonic OOM timing moved backwards")

            (
                peer,
                peer_barrier,
                peer_ownership,
                peer_ready_revalidated,
            ) = self._wait_for_peer_ready(armed)
            if (
                self._peer is None
                or self._peer_barrier is None
                or self._peer_ownership is None
            ):
                raise FaultEvidenceError("OOM peer identity was not captured before release")
            if (
                peer.public_identity() != self._peer.public_identity()
                or _public_barrier(peer_barrier) != _public_barrier(self._peer_barrier)
                or _public_ownership(peer_ownership)
                != _public_ownership(self._peer_ownership)
            ):
                raise FaultEvidenceError(
                    "normal-cap peer identity changed after OOM release"
                )
            _validate_oom_peer_readiness_continuity(
                self._peer_before_release,
                peer_ready_revalidated,
                target_run_id=self.target.run_id,
                cohort_sha256=self.target.cohort_sha256,
            )
            peer_after: Mapping[str, Any] | None = None
            for attempt in range(self._peer_poll_attempts):
                raw_peer_after = self._peer_state_probe(
                    FaultGate.OOM, peer, "peer_after"
                )
                if raw_peer_after is not None:
                    peer_after = _validate_state_record(
                        raw_peer_after,
                        FaultGate.OOM,
                        peer,
                        "peer_after",
                    )
                    break
                if attempt + 1 < self._peer_poll_attempts:
                    self._sleep(self._poll_interval_seconds)
            if peer_after is None:
                raise FaultEvidenceTimeout(
                    "normal-cap peer health continuation was not observed"
                )
            all_required_observations_seconds = (
                _finite_nonnegative_seconds(
                    self._monotonic(), "OOM completion monotonic sample"
                )
                - self._action_started
            )
            if all_required_observations_seconds < target_detection_seconds:
                raise FaultEvidenceError("monotonic OOM timing moved backwards")

            classifier_evidence = _validate_pre_readiness_oom_facts(
                target_run_id=self.target.run_id,
                cohort_sha256=self.target.cohort_sha256,
                container_id=armed.container_id,
                before=before_facts,
                after=after_facts,
                peer_before_release=_mapping(
                    "OOM peer-before-release facts",
                    self._peer_before_release.get("facts"),
                ),
                peer_after=_mapping("OOM peer-after facts", peer_after.get("facts")),
            )
            canaries_after = self._observe_canaries()
            if canaries_after != self._canaries_before:
                raise FaultEvidenceError("protected canary identity changed")
            action = {
                "kind": "prelaunched_fault_profile",
                "profile": _OOM_FAULT_PROFILE,
                "memory_bytes": _OOM_MEMORY_BYTES,
                "late_runtime_mutation": False,
                "argv": [],
                "shell": False,
            }
            completed_payload = {
                "target": self.target.public_identity(
                    container_id=armed.container_id,
                    container_init_host_pid=armed.container_init_host_pid,
                    container_cgroup_path=armed.container_cgroup_path,
                ),
                "peer": peer.public_identity(),
                "barrier": {
                    "target": _public_barrier(self._target_barrier),
                    "peer": _public_barrier(peer_barrier),
                },
                "ownership": {
                    "target": dict(self._target_ownership),
                    "peer": _public_ownership(peer_ownership),
                },
                "before": dict(self._before),
                "peer_before_release": _public_state(self._peer_before_release),
                "action": action,
                "after": dict(after),
                "peer_after": _public_state(peer_after),
                "canaries": {
                    "before": self._canaries_before,
                    "after": canaries_after,
                    "all_untouched": True,
                },
                "timing": {
                    "target_detection_seconds": target_detection_seconds,
                    "all_required_observations_seconds": (
                        all_required_observations_seconds
                    ),
                },
                "classifier_evidence_schema": _CLASSIFIER_EVIDENCE_SCHEMA,
                "classifier_evidence": classifier_evidence,
                "pending_external_checks": [
                    "target_cleanup_verified",
                    "cleanup_double_audit",
                ],
            }
            completed = self._writer.append("completed", completed_payload)
            return {
                "schema": PRE_READINESS_OOM_FINALIZE_SCHEMA,
                "ok": True,
                "run_id": self.target.run_id,
                "contract_sha256": self.target.contract_sha256,
                "nonce_sha256": _nonce_sha256(self.target.nonce),
                "cohort_sha256": self.target.cohort_sha256,
                "container_id": armed.container_id,
                "journal_path": str(self._writer.path),
                "completed_record_sha256": _payload_sha256(completed),
                "classifier_evidence_sha256": _payload_sha256(classifier_evidence),
            }
        except Exception as exc:
            self._append_failure(exc)
            raise

    def _wait_for_peer_ready(
        self, armed: _ArmedOomIdentity
    ) -> tuple[
        OwnedRun,
        Mapping[str, Any],
        Mapping[str, Any],
        Mapping[str, Any],
    ]:
        for attempt in range(self._peer_poll_attempts):
            candidate = self._peer_loader()
            if candidate is not None:
                self._validate_peer_identity(candidate, armed)
                raw_barrier = self._peer_cohort_start_probe(candidate)
                if raw_barrier is not None:
                    barrier = _validate_cohort_start_record(
                        raw_barrier, candidate, role="peer"
                    )
                    ownership = _validate_ownership_record(
                        self._peer_ownership_probe(candidate), candidate
                    )
                    container = _mapping(
                        "OOM peer owned container", ownership.get("container")
                    )
                    host_config = _mapping(
                        "OOM peer host config", container.get("host_config")
                    )
                    if (
                        host_config.get("memory_bytes") != _NORMAL_MEMORY_BYTES
                        or host_config.get("memory_swap_bytes") != _NORMAL_MEMORY_BYTES
                        or host_config.get("fault_profile") is not None
                    ):
                        raise FaultEvidenceError(
                            "OOM peer does not retain the exact normal memory cap"
                        )
                    raw_readiness = self._peer_state_probe(
                        FaultGate.OOM, candidate, "peer_before_release"
                    )
                    if raw_readiness is not None:
                        readiness = _validate_state_record(
                            raw_readiness,
                            FaultGate.OOM,
                            candidate,
                            "peer_before_release",
                        )
                        _validate_oom_peer_before_release(
                            _mapping(
                                "OOM peer-before-release facts",
                                readiness.get("facts"),
                            ),
                            target_run_id=self.target.run_id,
                            cohort_sha256=self.target.cohort_sha256,
                        )
                        return candidate, barrier, ownership, readiness
            if attempt + 1 < self._peer_poll_attempts:
                self._sleep(self._poll_interval_seconds)
        raise FaultEvidenceTimeout(
            "normal-cap peer ownership and durable health readiness were not "
            "observed before OOM "
            f"release within the {self._peer_wait_bound_seconds:g}s bound"
        )

    def _validate_peer_identity(self, peer: OwnedRun, armed: _ArmedOomIdentity) -> None:
        if (
            not isinstance(peer, OwnedRun)
            or peer.run_id != self.peer_run_id
            or peer.run_id == self.target.run_id
            or peer.cohort_sha256 != self.target.cohort_sha256
            or peer.control_root != self.target.control_root
            or peer.db_path != self.target.db_path
            or _paths_overlap(peer.workspace, self.target.workspace)
            or armed.container_id == peer.container_id
            or armed.container_init_host_pid
            in {
                peer.runtime_host_pid,
                peer.harness_pid,
                peer.supervisor_pid,
            }
        ):
            raise FaultEvidenceError("pre-readiness OOM peer identity differs")

    def _docker_inspection(self, container_id: str) -> Mapping[str, Any]:
        argv = (_DOCKER, "inspect", "--type", "container", container_id)
        result = self._runner.run(argv, timeout_seconds=10.0)
        if (
            not isinstance(result, FaultCommandResult)
            or result.argv != argv
            or result.returncode != 0
        ):
            raise FaultEvidenceError("exact OOM container is not inspectable")
        try:
            payload = json.loads(_bounded_capture(result.stdout))
        except json.JSONDecodeError as exc:
            raise FaultEvidenceError(
                "OOM Docker inspect returned invalid JSON"
            ) from exc
        if not isinstance(payload, list) or len(payload) != 1:
            raise FaultEvidenceError("OOM Docker inspect must return one container")
        return _mapping("OOM Docker inspection", payload[0])

    def _require_durable_runtime_receipt(
        self, name: str, supplied: Mapping[str, Any], label: str
    ) -> Mapping[str, Any]:
        supplied_mapping = _mapping(label, supplied)
        durable_mapping = self._read_durable_runtime_receipt(name, label)
        if dict(durable_mapping) != dict(supplied_mapping):
            raise FaultEvidenceError(f"supplied {label} differs from durable receipt")
        return durable_mapping

    def _read_durable_runtime_receipt(self, name: str, label: str) -> Mapping[str, Any]:
        path = (
            self.target.control_root
            / self.target.run_id
            / "attempts"
            / "attempt-0001"
            / "runtime"
            / name
        )
        if not self._path_exists(path):
            raise FaultEvidenceError(f"durable {label} is absent")
        try:
            raw = self._read_bytes(path)
        except FileNotFoundError as exc:
            raise FaultEvidenceError(f"durable {label} is absent") from exc
        if not isinstance(raw, bytes) or len(raw) > 64 * 1024:
            raise FaultEvidenceError(f"durable {label} is oversized")
        try:
            durable = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultEvidenceError(f"durable {label} is invalid JSON") from exc
        durable_mapping = _mapping(f"durable {label}", durable)
        return durable_mapping

    def _memory_events(self, cgroup_path: str) -> dict[str, int]:
        path = Path("/sys/fs/cgroup") / cgroup_path.lstrip("/") / "memory.events.local"
        values = _key_value_int_file(
            self._read_text(path), "target cgroup memory.events.local"
        )
        if "oom" not in values or "oom_kill" not in values:
            raise FaultEvidenceError(
                "target cgroup memory.events.local lacks OOM counters"
            )
        return {"oom": values["oom"], "oom_kill": values["oom_kill"]}

    def _host_oom_counter(self) -> int:
        values = _key_value_int_file(
            self._read_text(Path("/proc/vmstat")), "host /proc/vmstat"
        )
        if "oom_kill" not in values:
            raise FaultEvidenceError("host /proc/vmstat lacks oom_kill")
        return values["oom_kill"]

    def _observe_canaries(self) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for canary in self._canaries:
            record = _mapping("canary observation", self._canary_probe(canary))
            _exact_keys(
                "canary observation",
                record,
                {"schema", "name", "identity_sha256", "present"},
            )
            if (
                record.get("schema") != CANARY_OBSERVATION_SCHEMA
                or record.get("name") != canary.name
                or record.get("identity_sha256") != canary.identity_sha256
                or record.get("present") is not True
            ):
                raise FaultEvidenceError("protected canary observation differs")
            observations.append(dict(record))
        return observations

    def _append_failure(self, exc: Exception) -> None:
        try:
            self._writer.append(
                "failed",
                {
                    "error_type": type(exc).__name__,
                    "error": _bounded_string(
                        str(exc) or type(exc).__name__,
                        "failure message",
                        maximum=500,
                    ),
                },
            )
        except Exception as journal_exc:
            raise FaultEvidenceError(
                "OOM monitor failed and its failure record could not be persisted"
            ) from journal_exc


class LinuxHostFaultProbe:
    """Concrete shell-free Linux observer for live M1b fault gates.

    Docker reads cross a bounded command-runner seam.  SQLite, ``/proc``, and
    cgroup reads cross individually injectable filesystem seams, which keeps
    tests provider/network/Docker-free while leaving the default instance
    directly runnable on an isolated Linux host.
    """

    def __init__(
        self,
        *,
        target_run_id: str,
        command_runner: FaultCommandRunner | None = None,
        read_bytes: Callable[[Path], bytes] | None = None,
        read_text: Callable[[Path], str] | None = None,
        path_exists: Callable[[Path], bool] = Path.exists,
        stat_size: Callable[[Path], int] | None = None,
        statvfs: Callable[[Path], os.statvfs_result] = os.statvfs,
        getpgid: Callable[[int], int] = os.getpgid,
        process_ids: Callable[[], Sequence[int]] | None = None,
        sqlite_connect: Callable[..., sqlite3.Connection] = sqlite3.connect,
    ) -> None:
        if not _RUN_ID_RE.fullmatch(target_run_id):
            raise ValueError("target_run_id must be filesystem-safe")
        self.target_run_id = target_run_id
        self._runner = command_runner or SubprocessFaultCommandRunner()
        self._read_bytes = read_bytes or Path.read_bytes
        self._read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self._path_exists = path_exists
        self._stat_size = stat_size or (lambda path: path.stat().st_size)
        self._statvfs = statvfs
        self._getpgid = getpgid
        self._process_ids = process_ids or _linux_process_ids
        self._sqlite_connect = sqlite_connect
        self._barrier_rpc_generations: dict[str, str] = {}
        self._oom_peer_readiness_generations: dict[str, str] = {}
        self._before_memory_events: dict[str, dict[str, int]] = {}
        self._before_restart_counts: dict[str, int] = {}
        self._before_container_generations: dict[str, str] = {}
        self._before_daemon_generations: dict[str, str] = {}
        self._peer_health_sample_count = 0
        self._peer_health_first: dict[str, Any] | None = None
        self._peer_health_last: dict[str, Any] | None = None

    def peer_health_diagnostics(self) -> Mapping[str, Any]:
        """Bounded diagnostic samples, never evidence granting acceptance."""
        return {
            "sample_count": self._peer_health_sample_count,
            "first": dict(self._peer_health_first) if self._peer_health_first else None,
            "last": dict(self._peer_health_last) if self._peer_health_last else None,
        }

    def barrier_probe(self, run: OwnedRun) -> Mapping[str, Any] | None:
        """Read the committed run row and require its exact step-2 state."""

        if not self._path_exists(run.db_path):
            return None
        uri = f"{run.db_path.as_uri()}?mode=ro"
        try:
            connection = self._sqlite_connect(uri, uri=True, timeout=0)
        except sqlite3.OperationalError as exc:
            raise FaultEvidenceError(
                "durable step barrier database is unreadable"
            ) from exc
        try:
            row = connection.execute(
                "SELECT run_id, status, step, supervision_mode, trace_path "
                "FROM runs WHERE run_id = ?",
                (run.run_id,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise FaultEvidenceError("durable step barrier query failed") from exc
        finally:
            connection.close()
        if row is None:
            return None
        values = tuple(row)
        if len(values) != 5:
            raise FaultEvidenceError("durable step barrier row shape differs")
        row_run_id, status, step, supervision_mode, trace_path = values
        if row_run_id != run.run_id or supervision_mode != "m1b-process":
            raise FaultEvidenceError("durable step barrier ownership differs")
        if status != "running":
            raise FaultEvidenceError("durable step barrier run is not active")
        if isinstance(step, bool) or not isinstance(step, int):
            raise FaultEvidenceError("durable step barrier step is invalid")
        if step < 2:
            return None
        if step != 2:
            raise FaultEvidenceError(
                "durable run advanced past the exact step-2 barrier"
            )
        if not isinstance(trace_path, str) or not trace_path:
            raise FaultEvidenceError("durable step barrier trace path is invalid")
        generation = self._rpc_generation(run)
        self._barrier_rpc_generations[run.run_id] = generation
        receipt = {
            "db_path": str(run.db_path),
            "run_id": row_run_id,
            "status": status,
            "step": step,
            "supervision_mode": supervision_mode,
            "trace_path": trace_path,
            "rpc_connection_generation": generation,
        }
        return {
            "schema": STEP2_BARRIER_SCHEMA,
            "run_id": run.run_id,
            "contract_sha256": run.contract_sha256,
            "nonce": run.nonce,
            "cohort_sha256": run.cohort_sha256,
            "container_id": run.container_id,
            "runtime_host_pid": run.runtime_host_pid,
            "runtime_container_pid": run.runtime_container_pid,
            "harness_pid": run.harness_pid,
            "workspace": str(run.workspace),
            "step": 2,
            "state": "reached",
            "durable": True,
            "journal_record_sha256": _payload_sha256(receipt),
        }

    def cohort_start_probe(self, run: OwnedRun) -> Mapping[str, Any] | None:
        """Load the controller's durable post-create/pre-readiness receipt."""

        path = (
            run.control_root
            / run.run_id
            / "attempts"
            / "attempt-0001"
            / "runtime"
            / "container-created.json"
        )
        if not self._path_exists(path):
            return None
        raw = self._read_bytes(path)
        if len(raw) > 64 * 1024:
            raise FaultEvidenceError("runtime container-created receipt is oversized")
        try:
            receipt = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FaultEvidenceError(
                "runtime container-created receipt is invalid JSON"
            ) from exc
        record = _mapping("runtime container-created receipt", receipt)
        required = {
            "schema",
            "ok",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "container_name",
            "container_id",
            "image_reference",
            "memory_bytes",
            "memory_swap_bytes",
            "fault_profile",
        }
        if set(record) != required:
            raise FaultEvidenceError("runtime container-created receipt fields differ")
        if (
            record.get("schema") != "fortgym.m1b-container-created/v1"
            or record.get("ok") is not True
            or record.get("run_id") != run.run_id
            or record.get("contract_sha256") != run.contract_sha256
            or record.get("nonce_sha256") != _nonce_sha256(run.nonce)
            or record.get("cohort_sha256") != run.cohort_sha256
            or record.get("container_id") != run.container_id
            or not isinstance(record.get("container_name"), str)
            or not isinstance(record.get("image_reference"), str)
        ):
            raise FaultEvidenceError("runtime container-created identity differs")
        target = run.run_id == self.target_run_id
        return {
            "schema": COHORT_START_SCHEMA,
            "run_id": run.run_id,
            "contract_sha256": run.contract_sha256,
            "nonce": run.nonce,
            "cohort_sha256": run.cohort_sha256,
            "container_id": run.container_id,
            "role": "target" if target else "peer",
            "memory_bytes": record["memory_bytes"],
            "memory_swap_bytes": record["memory_swap_bytes"],
            "fault_profile": record["fault_profile"],
            "provider_free": True,
            "state": "container_created",
            "durable": True,
            "journal_record_sha256": hashlib.sha256(raw).hexdigest(),
        }

    def ownership_probe(self, run: OwnedRun) -> Mapping[str, Any]:
        inspection = self._docker_inspection(run.container_id)
        config = _mapping("Docker container Config", inspection.get("Config"))
        host_config = _mapping(
            "Docker container HostConfig", inspection.get("HostConfig")
        )
        labels = _mapping("Docker container labels", config.get("Labels"))
        environment = _environment_index(config.get("Env"))
        if str(inspection.get("Id") or "").lower() != run.container_id:
            raise FaultEvidenceError("Docker inspection container ID differs")
        runtime = self._runtime_process_identity(run)
        harness_environment = self._process_environment(run.harness_pid)
        if (
            harness_environment.get("FORT_GYM_RUN_ID") != run.run_id
            or harness_environment.get("FORT_GYM_RUN_CONTRACT_SHA256")
            != run.contract_sha256
            or harness_environment.get("FORT_GYM_RUN_NONCE") != run.nonce
        ):
            raise FaultEvidenceError("harness /proc environment ownership differs")
        try:
            observed_pgid = self._getpgid(run.harness_pid)
        except OSError as exc:
            raise FaultEvidenceError("harness process is absent") from exc
        if observed_pgid != run.harness_process_group_id:
            raise FaultEvidenceError("harness process-group ownership differs")
        if not self._process_exists(run.supervisor_pid):
            raise FaultEvidenceError("supervisor process is absent")
        rpc_generation = self._rpc_generation(run)
        observed_generation = self._barrier_rpc_generations.setdefault(
            run.run_id, rpc_generation
        )
        if observed_generation != rpc_generation:
            raise FaultEvidenceError(
                "runtime RPC generation changed between barrier and ownership"
            )
        fault_profile = labels.get("fortgym.m1b.fault_profile")
        if fault_profile == "":
            fault_profile = None
        return {
            "schema": RUN_OWNERSHIP_SCHEMA,
            "run_id": run.run_id,
            "contract_sha256": run.contract_sha256,
            "nonce": run.nonce,
            "cohort_sha256": run.cohort_sha256,
            "container": {
                "id": run.container_id,
                "labels": {
                    "managed": labels.get("fortgym.m1b.managed"),
                    "run_id": labels.get("fortgym.m1b.run_id"),
                    "contract_sha256": labels.get("fortgym.m1b.contract_sha256"),
                },
                "environment": {
                    "run_id": environment.get("FORTGYM_RUN_ID"),
                    "contract_sha256": environment.get("FORTGYM_CONTRACT_SHA256"),
                    "nonce": environment.get("FORTGYM_RUN_NONCE"),
                },
                "host_config": {
                    "memory_bytes": host_config.get("Memory"),
                    "memory_swap_bytes": host_config.get("MemorySwap"),
                    "fault_profile": fault_profile,
                },
            },
            "runtime_process": runtime,
            "harness_process": {
                "pid": run.harness_pid,
                "run_id": run.run_id,
                "process_group_id": observed_pgid,
            },
            "supervisor_process": {
                "pid": run.supervisor_pid,
                "operational": True,
            },
            "workspace_owner": self._workspace_owner(run),
        }

    def state_probe(
        self, gate: FaultGate, run: OwnedRun, phase: str
    ) -> Mapping[str, Any] | None:
        if phase == "peer_before_release":
            if gate is not FaultGate.OOM:
                raise FaultEvidenceError(
                    "peer-before-release is reserved for the held OOM gate"
                )
            facts = self._oom_peer_before_release_facts(run)
        elif phase == "peer_after":
            facts = self._peer_after_facts(gate, run)
        elif phase in {"before", "after"}:
            facts = self._target_facts(gate, run, phase)
        else:
            raise FaultEvidenceError("unsupported concrete fault-state phase")
        if facts is None:
            return None
        return {
            "schema": FAULT_STATE_SCHEMA,
            "gate": gate.value,
            "phase": phase,
            "run_id": run.run_id,
            "contract_sha256": run.contract_sha256,
            "nonce": run.nonce,
            "container_id": run.container_id,
            "runtime_host_pid": run.runtime_host_pid,
            "runtime_container_pid": run.runtime_container_pid,
            "harness_pid": run.harness_pid,
            "workspace": str(run.workspace),
            "facts": facts,
        }

    def canary_probe(self, canary: ProtectedCanary) -> Mapping[str, Any]:
        result = self._run_command(
            (_DOCKER, "inspect", "--type", "container", canary.container_id),
            timeout_seconds=10.0,
            allow_failure=True,
        )
        present = (
            result.returncode == 0
            and all(self._process_exists(pid) for pid in canary.process_ids)
            and self._path_exists(canary.workspace)
        )
        return {
            "schema": CANARY_OBSERVATION_SCHEMA,
            "name": canary.name,
            "identity_sha256": canary.identity_sha256,
            "present": present,
        }

    def _target_facts(
        self, gate: FaultGate, run: OwnedRun, phase: str
    ) -> dict[str, Any] | None:
        inspection = self._docker_inspection(run.container_id, allow_absent=True)
        state = (
            _mapping("Docker container State", inspection.get("State"))
            if inspection is not None
            else {}
        )
        runtime_present = self._process_exists(run.runtime_host_pid)
        harness_present = self._process_exists(run.harness_pid)
        if gate is FaultGate.DF_KILL:
            if phase == "before":
                if not runtime_present or state.get("Running") is not True:
                    return None
                return {
                    "runtime_identity": run.container_id,
                    "runtime_state": "running",
                    "oom_killed": bool(state.get("OOMKilled", False)),
                }
            if runtime_present:
                return None
            self._require_action_command(
                run,
                gate,
                (_KILL, "-KILL", "--", str(run.runtime_host_pid)),
            )
            if state.get("ExitCode") != 137 or bool(state.get("OOMKilled", False)):
                return None
            return {
                "runtime_identity": run.container_id,
                "runtime_state": "exited",
                "runtime_exit_code": state.get("ExitCode"),
                "signal": 9,
                "oom_killed": bool(state.get("OOMKilled", False)),
            }
        if gate is FaultGate.HARNESS_KILL:
            members = list(self._process_group_members(run.harness_process_group_id))
            if phase == "before":
                if not harness_present:
                    return None
                return {
                    "child_pid": run.harness_pid,
                    "child_state": "running",
                    "process_group_members": members,
                }
            if harness_present:
                return None
            self._require_action_command(
                run,
                gate,
                (_KILL, "-KILL", "--", str(run.harness_pid)),
            )
            return {
                "child_pid": run.harness_pid,
                "child_state": "signaled",
                "signal": 9,
                "process_group_members": members,
            }
        if gate is FaultGate.OOM:
            events = self._cgroup_memory_events(run)
            if phase == "before":
                self._before_memory_events[run.run_id] = events
            else:
                baseline = self._before_memory_events.get(run.run_id)
                if (
                    baseline is None
                    or runtime_present
                    or state.get("ExitCode") != 137
                    or events["oom_kill"] <= baseline["oom_kill"]
                ):
                    return None
            return {
                "runtime_identity": run.container_id,
                "runtime_exit_code": None
                if phase == "before"
                else state.get("ExitCode"),
                "cgroup_memory_events": events,
                "host_oom_counter": self._host_oom_counter(),
            }
        if gate is FaultGate.ENOSPC:
            fault_path = (run.workspace / ".fortgym-m1b-enospc.fill").resolve(
                strict=False
            )
            fault_bytes = (
                self._stat_size(fault_path) if self._path_exists(fault_path) else 0
            )
            if phase == "after":
                action = self._action_evidence(run, gate)
                enospc = _mapping("durable ENOSPC action", action.get("enospc"))
                if (
                    enospc.get("errno") != 28
                    or enospc.get("fault_bytes") != fault_bytes
                ):
                    return None
            return {
                "operation": "fill-private-workspace",
                "workspace": {
                    "run_id": run.run_id,
                    "scope_root": str(run.workspace),
                    "fault_path": str(fault_path),
                    "fault_bytes": fault_bytes,
                    "maximum_fault_bytes": MAX_WORKSPACE_FAULT_BYTES,
                    "filesystem": "tmpfs",
                    "private": True,
                    "size_bytes": MAX_WORKSPACE_FAULT_BYTES,
                },
            }
        if gate is FaultGate.CONTAINER_RESTART:
            if inspection is None:
                return None
            generation = self._rpc_generation(run)
            barrier_generation = self._required_barrier_generation(run)
            terminal_observed = not harness_present
            restart_count = state.get("RestartCount", inspection.get("RestartCount"))
            if isinstance(restart_count, bool) or not isinstance(restart_count, int):
                raise FaultEvidenceError("Docker restart count is invalid")
            init_pid = state.get("Pid")
            if isinstance(init_pid, bool) or not isinstance(init_pid, int) or init_pid <= 1:
                return None
            process_generation = self._container_process_generation(init_pid)
            if phase == "before":
                self._before_restart_counts[run.run_id] = restart_count
                self._before_container_generations[run.run_id] = process_generation
            if phase == "after":
                self._require_action_command(
                    run,
                    gate,
                    (_DOCKER, "restart", "--time", "0", run.container_id),
                )
                baseline_count = self._before_restart_counts.get(run.run_id)
                if (
                    not terminal_observed
                    or baseline_count is None
                    or self._before_container_generations.get(run.run_id)
                    in (None, process_generation)
                ):
                    return None
            return {
                "container_identity": run.container_id,
                "restart_count": restart_count,
                "runtime_generation": process_generation,
                "running": bool(state.get("Running", False)),
                "rpc_connection_generation": generation,
                "reconnected": generation != barrier_generation,
                "terminal_observed": terminal_observed,
            }
        if gate is FaultGate.DAEMON_RESTART:
            generation = self._daemon_generation()
            rpc_generation = self._rpc_generation(run)
            barrier_generation = self._required_barrier_generation(run)
            terminal_observed = not harness_present
            if phase == "before":
                self._before_daemon_generations[run.run_id] = generation
            if phase == "after":
                action = self._action_evidence(run, gate)
                callback = _mapping(
                    "daemon restart action callback", action.get("callback")
                )
                baseline_generation = self._before_daemon_generations.get(run.run_id)
                if (
                    callback.get("invoked") is not True
                    or not terminal_observed
                    or baseline_generation is None
                    or generation == baseline_generation
                ):
                    return None
            return {
                "daemon_generation": generation,
                "runtime_identity": run.container_id,
                "inside_container": self._inside_container(),
                "supervisor_operational": self._process_exists(run.supervisor_pid),
                "rpc_connection_generation": rpc_generation,
                "reconnected": rpc_generation != barrier_generation,
                "terminal_observed": terminal_observed,
                "silent_continuation": harness_present and phase == "after",
            }
        raise AssertionError(f"unhandled fault gate {gate!r}")

    def _peer_after_facts(
        self, gate: FaultGate, run: OwnedRun
    ) -> dict[str, Any] | None:
        status, step = self._run_status(run)
        harness_present = self._process_exists(run.harness_pid)
        sample = {
            "run_id": run.run_id,
            "status": status,
            "step": step,
            "harness_pid": run.harness_pid,
            "harness_present": harness_present,
            "monotonic_seconds": time.monotonic(),
        }
        self._peer_health_sample_count += 1
        if self._peer_health_first is None:
            self._peer_health_first = sample
        self._peer_health_last = sample
        generation = self._rpc_generation(run)
        if gate is FaultGate.OOM:
            try:
                barrier_generation = self._oom_peer_readiness_generations[run.run_id]
            except KeyError as exc:
                raise FaultEvidenceError(
                    "OOM peer lacks a pre-release connection generation"
                ) from exc
        else:
            barrier_generation = self._required_barrier_generation(run)
        if gate is FaultGate.DAEMON_RESTART:
            if harness_present:
                return None
            return {
                "step": step,
                "healthy": False,
                "reconnected": generation != barrier_generation,
                "continued_after_fault": False,
                "target_run_id": self.target_run_id,
            }
        minimum = 5 if gate in {FaultGate.DF_KILL, FaultGate.HARNESS_KILL} else 3
        if step < minimum or status != "running" or not harness_present:
            return None
        facts = {
            "step": step,
            "healthy": True,
            "reconnected": generation != barrier_generation,
            "continued_after_fault": True,
            "target_run_id": self.target_run_id,
        }
        if gate is FaultGate.OOM:
            facts.update(
                {
                    "runtime_ready": self._process_exists(run.runtime_host_pid),
                    "cohort_sha256": run.cohort_sha256,
                    "connection_generation": generation,
                }
            )
        return facts

    def _oom_peer_before_release_facts(self, run: OwnedRun) -> dict[str, Any] | None:
        status, step = self._run_status(run)
        if (
            status != "running"
            or step < 2
            or not self._process_exists(run.runtime_host_pid)
            or not self._process_exists(run.harness_pid)
            or not self._process_exists(run.supervisor_pid)
        ):
            return None
        inspection = self._docker_inspection(run.container_id, allow_absent=True)
        if inspection is None:
            return None
        state = _mapping("OOM peer Docker State", inspection.get("State"))
        if state.get("Running") is not True or bool(state.get("OOMKilled", False)):
            return None
        generation = self._rpc_generation(run)
        baseline = self._oom_peer_readiness_generations.setdefault(
            run.run_id, generation
        )
        receipt = {
            "run_id": run.run_id,
            "contract_sha256": run.contract_sha256,
            "nonce_sha256": _nonce_sha256(run.nonce),
            "cohort_sha256": run.cohort_sha256,
            "target_run_id": self.target_run_id,
            "status": status,
            "step": step,
            "connection_generation": generation,
        }
        return {
            "target_run_id": self.target_run_id,
            "cohort_sha256": run.cohort_sha256,
            "status": status,
            "step": step,
            "runtime_ready": True,
            "healthy": True,
            "reconnected": generation != baseline,
            "continued_before_fault": True,
            "connection_generation": generation,
            "durable": True,
            "readiness_receipt_sha256": _payload_sha256(receipt),
        }

    def _docker_inspection(
        self, container_id: str, *, allow_absent: bool = False
    ) -> Mapping[str, Any] | None:
        result = self._run_command(
            (_DOCKER, "inspect", "--type", "container", container_id),
            timeout_seconds=10.0,
            allow_failure=allow_absent,
        )
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FaultEvidenceError("Docker inspect returned invalid JSON") from exc
        if not isinstance(payload, list) or len(payload) != 1:
            raise FaultEvidenceError("Docker inspect must return exactly one container")
        return _mapping("Docker inspection", payload[0])

    def _runtime_process_identity(self, run: OwnedRun) -> dict[str, Any]:
        comm = self._read_text(Path(f"/proc/{run.runtime_host_pid}/comm")).strip()
        if comm != "Dwarf_Fortress":
            raise FaultEvidenceError("runtime host PID executable differs")
        status = self._read_text(Path(f"/proc/{run.runtime_host_pid}/status"))
        namespace_pids = _proc_status_nspid(status)
        if not namespace_pids or namespace_pids[-1] != run.runtime_container_pid:
            raise FaultEvidenceError(
                "runtime host/container PID namespace identity differs"
            )
        cgroup = self._read_text(Path(f"/proc/{run.runtime_host_pid}/cgroup"))
        observed_paths = _proc_cgroup_paths(cgroup)
        if run.runtime_cgroup_path not in observed_paths or not any(
            run.container_id in path for path in observed_paths
        ):
            raise FaultEvidenceError("runtime /proc cgroup does not bind the container")
        return {
            "host_pid": run.runtime_host_pid,
            "container_pid": namespace_pids[-1],
            "run_id": run.run_id,
            "container_id": run.container_id,
            "executable_basename": comm,
            "cgroup_path": run.runtime_cgroup_path,
        }

    def _workspace_owner(self, run: OwnedRun) -> dict[str, Any]:
        marker = run.workspace / ".fortgym-m1b-workspace-owner.json"
        if self._path_exists(marker):
            try:
                payload = json.loads(self._read_text(marker))
            except json.JSONDecodeError as exc:
                raise FaultEvidenceError(
                    "workspace owner marker is invalid JSON"
                ) from exc
            record = _mapping("workspace owner marker", payload)
            launch_path = run.control_root / run.run_id / "launch.json"
            try:
                launch = _mapping("workspace launch", json.loads(self._read_text(launch_path)))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FaultEvidenceError("workspace launch identity is unreadable") from exc
            contract = _mapping("workspace launch contract", launch.get("contract"))
            _validate_canonical_launch_contract(
                contract, run_id=run.run_id, expected_control_root=run.control_root,
                expected_db_path=run.db_path, expected_artifacts_root=run.workspace.parent,
            )
            peers = contract["cotenancy"]["peer_run_ids"]
            if (
                contract["contract_sha256"] != run.contract_sha256
                or contract["rpc"]["nonce"] != run.nonce
                or contract["cotenancy"]["cohort_sha256"] != run.cohort_sha256
                or len(peers) != 1
            ):
                raise FaultEvidenceError("workspace launch ownership or peer differs")
            _validate_workspace_marker(record, run, peer_run_id=peers[0])
            return {
                "path": str(run.workspace),
                "run_id": run.run_id,
                "private": True,
                "filesystem": record["filesystem"],
                "size_bytes": record["size_bytes"],
            }
        if run.run_id not in run.workspace.parts or not self._path_exists(
            run.workspace
        ):
            raise FaultEvidenceError("run workspace lacks exact private path ownership")
        stats = self._statvfs(run.workspace)
        size_bytes = int(stats.f_frsize) * int(stats.f_blocks)
        if size_bytes <= 0:
            raise FaultEvidenceError("run workspace filesystem size is invalid")
        return {
            "path": str(run.workspace),
            "run_id": run.run_id,
            "private": True,
            "filesystem": "host-directory",
            "size_bytes": size_bytes,
        }

    def _process_environment(self, pid: int) -> dict[str, str]:
        raw = self._read_bytes(Path(f"/proc/{pid}/environ"))
        result: dict[str, str] = {}
        for item in raw.split(b"\0"):
            if not item:
                continue
            try:
                name, value = item.decode("utf-8").split("=", 1)
            except (UnicodeDecodeError, ValueError) as exc:
                raise FaultEvidenceError("process environment is malformed") from exc
            result[name] = value
        return result

    def _process_exists(self, pid: int) -> bool:
        return self._path_exists(Path(f"/proc/{pid}"))

    def _process_group_members(self, process_group_id: int) -> tuple[int, ...]:
        members: list[int] = []
        for pid in self._process_ids():
            try:
                if self._getpgid(pid) == process_group_id:
                    members.append(pid)
            except OSError:
                continue
        return tuple(sorted(set(members)))

    def _rpc_generation(self, run: OwnedRun) -> str:
        lifecycle = (
            run.control_root
            / run.run_id
            / "attempts"
            / "attempt-0001"
            / "runtime"
            / "lifecycle.jsonl"
        )
        if not self._path_exists(lifecycle):
            raise FaultEvidenceError("runtime lifecycle evidence is absent")
        raw = self._read_bytes(lifecycle)
        if len(raw) > 2 * 1024 * 1024 or not raw.endswith(b"\n"):
            raise FaultEvidenceError(
                "runtime lifecycle evidence is partial or oversized"
            )
        prepare_records: list[Mapping[str, Any]] = []
        for line in raw.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FaultEvidenceError(
                    "runtime lifecycle evidence is invalid JSONL"
                ) from exc
            if (
                isinstance(record, Mapping)
                and record.get("schema") == "fortgym.m1b-runtime-prepare/v1"
                and record.get("ok") is True
            ):
                prepare_records.append(record)
        if len(prepare_records) != 1:
            raise FaultEvidenceError(
                "runtime RPC generation requires exactly one successful prepare"
            )
        return _payload_sha256(prepare_records[0])

    def _required_barrier_generation(self, run: OwnedRun) -> str:
        try:
            return self._barrier_rpc_generations[run.run_id]
        except KeyError as exc:
            raise FaultEvidenceError(
                "run lacks an observed step-2 RPC generation"
            ) from exc

    def _cgroup_memory_events(self, run: OwnedRun) -> dict[str, int]:
        path = (
            Path("/sys/fs/cgroup")
            / run.runtime_cgroup_path.lstrip("/")
            / "memory.events"
        )
        values = _key_value_int_file(self._read_text(path), "cgroup memory.events")
        if "oom" not in values or "oom_kill" not in values:
            raise FaultEvidenceError("cgroup memory.events lacks OOM counters")
        return {"oom": values["oom"], "oom_kill": values["oom_kill"]}

    def _host_oom_counter(self) -> int:
        values = _key_value_int_file(
            self._read_text(Path("/proc/vmstat")), "host /proc/vmstat"
        )
        if "oom_kill" not in values:
            raise FaultEvidenceError("host /proc/vmstat lacks oom_kill")
        return values["oom_kill"]

    def _container_process_generation(self, pid: int) -> str:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
            raise FaultEvidenceError("container init PID is invalid")
        return _payload_sha256({
            "pid": pid,
            "start_ticks": _proc_stat_start_ticks(
                self._read_text(Path(f"/proc/{pid}/stat"))
            ),
        })

    def _daemon_generation(self) -> str:
        raw_pid = self._read_text(Path("/var/run/docker.pid")).strip()
        if not raw_pid.isdigit() or int(raw_pid) <= 1:
            raise FaultEvidenceError("Docker daemon PID file is invalid")
        stat = self._read_text(Path(f"/proc/{int(raw_pid)}/stat"))
        fields = stat.split()
        if len(fields) < 22:
            raise FaultEvidenceError("Docker daemon /proc stat is invalid")
        return _payload_sha256({"pid": int(raw_pid), "start_ticks": fields[21]})

    def _inside_container(self) -> bool:
        if self._path_exists(Path("/.dockerenv")) or self._path_exists(
            Path("/run/.containerenv")
        ):
            return True
        cgroup = self._read_text(Path("/proc/1/cgroup"))
        lowered = cgroup.lower()
        return any(
            marker in lowered for marker in ("/docker/", "kubepods", "containerd")
        )

    def _run_status(self, run: OwnedRun) -> tuple[str, int]:
        uri = f"{run.db_path.as_uri()}?mode=ro"
        connection = self._sqlite_connect(uri, uri=True, timeout=0)
        try:
            row = connection.execute(
                "SELECT status, step FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None or len(tuple(row)) != 2:
            raise FaultEvidenceError("peer durable run status is absent")
        status, step = tuple(row)
        if (
            not isinstance(status, str)
            or isinstance(step, bool)
            or not isinstance(step, int)
        ):
            raise FaultEvidenceError("peer durable run status is invalid")
        return status, step

    def _action_evidence(self, run: OwnedRun, gate: FaultGate) -> Mapping[str, Any]:
        path = fault_observation_journal_path(run.control_root, run.run_id)
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except FileNotFoundError as exc:
            raise FaultEvidenceError("fault action journal is absent") from exc
        try:
            records = _read_journal_descriptor(
                descriptor,
                expected_run_id=run.run_id,
                expected_contract_sha256=run.contract_sha256,
                expected_nonce_sha256=_nonce_sha256(run.nonce),
                expected_gate=gate,
            )
        finally:
            os.close(descriptor)
        attempted = [
            _mapping("action attempted payload", record.get("payload"))
            for record in records
            if record.get("phase") == "action_attempted"
        ]
        if len(attempted) != 1:
            raise FaultEvidenceError("fault action evidence is not uniquely durable")
        return attempted[0]

    def _require_action_command(
        self, run: OwnedRun, gate: FaultGate, expected_argv: tuple[str, ...]
    ) -> None:
        action = self._action_evidence(run, gate)
        if (
            action.get("kind") != "command"
            or action.get("argv") != list(expected_argv)
            or action.get("shell") is not False
            or action.get("returncode") != 0
        ):
            raise FaultEvidenceError("durable exact fault command evidence differs")

    def _run_command(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        allow_failure: bool = False,
    ) -> FaultCommandResult:
        normalized = _command_vector(argv)
        result = self._runner.run(normalized, timeout_seconds=timeout_seconds)
        if not isinstance(result, FaultCommandResult) or result.argv != normalized:
            raise FaultEvidenceError("host probe command evidence differs")
        _bounded_capture(result.stdout)
        _bounded_capture(result.stderr)
        if result.returncode != 0 and not allow_failure:
            raise FaultEvidenceError(
                f"host probe command failed with return code {result.returncode}"
            )
        return result


class PrelaunchEnospcWorkspace:
    """Provision the ENOSPC tmpfs before ProcessSupervisor opens artifacts.

    The target must come from
    :meth:`OwnedRunEvidenceLoader.load_prelaunch_enospc_target`.  In
    particular, an already-running :class:`OwnedRun` is rejected: mounting at
    that point would hide live artifacts and invalidate the gate.  Cleanup
    never reuses the consumed setup capability: it requires a strict
    :class:`EnospcWorkspaceCleanupTarget` reconstructed from the symmetric
    launch, registry, receipt, marker, mount, and process-absence evidence.
    """

    def __init__(
        self,
        *,
        command_runner: FaultCommandRunner | None = None,
        mount_probe: Callable[[Path], Mapping[str, Any] | None] | None = None,
        path_exists: Callable[[Path], bool] = Path.exists,
        process_group_members: Callable[[int], Sequence[int]] | None = None,
    ) -> None:
        self._runner = command_runner or SubprocessFaultCommandRunner()
        self._mount_probe = mount_probe or self._find_mount
        self._path_exists = path_exists
        self._process_group_members = (
            process_group_members or _linux_process_group_members
        )

    def prepare_workspace(
        self,
        *,
        authorization: FaultTestAuthorization,
        target: PrelaunchEnospcTarget,
    ) -> Mapping[str, Any]:
        if not isinstance(authorization, FaultTestAuthorization):
            raise FaultAuthorizationError(
                "private tmpfs requires the opaque test token"
            )
        if not isinstance(target, PrelaunchEnospcTarget):
            raise FaultAuthorizationError(
                "private tmpfs must be provisioned from canonical prelaunch evidence"
            )
        authorization._authorize_tmpfs_setup(target)
        run_dir = target.control_root / target.run_id
        if (
            not self._path_exists(run_dir)
            or self._path_exists(run_dir / "owner.json")
            or self._path_exists(run_dir / "attempts")
            or self._path_exists(target.workspace)
        ):
            raise FaultActionError(
                "ENOSPC workspace requires its reserved control parent and must be "
                "provisioned before manager or artifacts"
            )
        if self._mount_probe(target.workspace) is not None:
            raise FaultActionError("refusing to replace an existing workspace mount")
        target.workspace.mkdir(mode=0o700, parents=False, exist_ok=False)
        source = f"fortgym-m1b-enospc-{target.run_id}"
        argv = (
            "/bin/mount",
            "-t",
            "tmpfs",
            "-o",
            f"size={MAX_WORKSPACE_FAULT_BYTES},nosuid,nodev,noexec,mode=0700",
            source,
            str(target.workspace),
        )
        result = self._run_exact(argv, timeout_seconds=30.0, allow_failure=True)
        if result.returncode != 0:
            try:
                target.workspace.rmdir()
            except OSError as exc:
                raise FaultEvidenceError(
                    "failed tmpfs mount left a non-empty mountpoint"
                ) from exc
            raise FaultActionError("private 16 MiB tmpfs mount failed")
        observed = self._mount_probe(target.workspace)
        self._validate_mount(observed, target, source)
        marker = {
            "schema": WORKSPACE_OWNER_SCHEMA,
            "run_id": target.run_id,
            "contract_sha256": target.contract_sha256,
            "nonce_sha256": _nonce_sha256(target.nonce),
            "cohort_sha256": target.cohort_sha256,
            "peer_run_id": target.peer_run_id,
            "profile": _ENOSPC_WORKSPACE_PROFILE,
            "path": str(target.workspace),
            "filesystem": "tmpfs",
            "size_bytes": MAX_WORKSPACE_FAULT_BYTES,
            "source": source,
        }
        marker_path = target.workspace / ".fortgym-m1b-workspace-owner.json"
        receipt = {
            "schema": PRELAUNCH_ENOSPC_RECEIPT_SCHEMA,
            "ok": True,
            "run_id": target.run_id,
            "contract_sha256": target.contract_sha256,
            "nonce_sha256": _nonce_sha256(target.nonce),
            "cohort_sha256": target.cohort_sha256,
            "peer_run_id": target.peer_run_id,
            "workspace": str(target.workspace),
            "filesystem": "tmpfs",
            "size_bytes": MAX_WORKSPACE_FAULT_BYTES,
            "source": source,
            "marker_sha256": _payload_sha256(marker),
            "mount_argv": list(argv),
            "shell": False,
            "prepared_before_manager": True,
        }
        try:
            _atomic_json_write(marker_path, marker)
            _write_once_json_durable(
                run_dir / "prelaunch-enospc-workspace.json", receipt
            )
        except Exception:
            self._rollback_failed_prepare(target, source)
            raise
        return receipt

    def cleanup_workspace(
        self, *, target: EnospcWorkspaceCleanupTarget
    ) -> Mapping[str, Any]:
        if not isinstance(target, EnospcWorkspaceCleanupTarget):
            raise FaultAuthorizationError(
                "private tmpfs cleanup requires reconstructed durable ownership"
            )
        if target.harness_process_group_id is not None and tuple(
            self._process_group_members(target.harness_process_group_id)
        ):
            raise FaultEvidenceError(
                "private tmpfs cannot unmount before child process-group absence"
            )
        receipt = _read_bounded_json_path(
            target.control_root / target.run_id / "prelaunch-enospc-workspace.json",
            "prelaunch ENOSPC workspace receipt",
        )
        _validate_prelaunch_enospc_receipt(receipt, target)
        source = f"fortgym-m1b-enospc-{target.run_id}"
        observed = self._mount_probe(target.workspace)
        self._validate_mount(observed, target, source)
        marker_path = target.workspace / ".fortgym-m1b-workspace-owner.json"
        self._load_and_validate_marker(
            marker_path, target, peer_run_id=target.peer_run_id
        )
        argv = ("/bin/umount", "--", str(target.workspace))
        result = self._run_exact(argv, timeout_seconds=30.0)
        if result.returncode != 0:
            raise FaultActionError("private tmpfs unmount failed")
        if self._mount_probe(target.workspace) is not None:
            raise FaultEvidenceError("private tmpfs remains mounted after cleanup")
        try:
            target.workspace.rmdir()
        except OSError as exc:
            raise FaultEvidenceError(
                "private tmpfs mountpoint is not empty after unmount"
            ) from exc
        return {
            "schema": TMPFS_LIFECYCLE_SCHEMA,
            "operation": "unmounted",
            "run_id": target.run_id,
            "argv": list(argv),
            "shell": False,
            "cleanup_mode": target.cleanup_mode,
            "child_process_group_id": target.harness_process_group_id,
            "child_process_group_absent": True,
            "residue_absent": self.audit_absent(target),
        }

    def reconcile_workspace(
        self,
        *,
        target: EnospcWorkspaceCleanupTarget,
    ) -> Mapping[str, Any]:
        """Fail-closed recovery for one exact interrupted private tmpfs.

        The method removes only an exact 16 MiB tmpfs carrying the exact
        launch/receipt/marker ownership chain.  A missing mount with any
        residual path is refused because ownership can no longer be proved
        safely.
        """

        if not isinstance(target, EnospcWorkspaceCleanupTarget):
            raise FaultAuthorizationError(
                "private tmpfs reconciliation requires reconstructed durable ownership"
            )
        if target.harness_process_group_id is not None and tuple(
            self._process_group_members(target.harness_process_group_id)
        ):
            raise FaultEvidenceError(
                "private tmpfs cannot reconcile before child process-group absence"
            )
        receipt = _read_bounded_json_path(
            target.control_root / target.run_id / "prelaunch-enospc-workspace.json",
            "prelaunch ENOSPC workspace receipt",
        )
        _validate_prelaunch_enospc_receipt(receipt, target)
        observed = self._mount_probe(target.workspace)
        if observed is None:
            if self._path_exists(target.workspace):
                raise FaultEvidenceError(
                    "unmounted workspace residue cannot be reconciled without mount identity"
                )
            return {
                "schema": TMPFS_LIFECYCLE_SCHEMA,
                "operation": "already_absent",
                "run_id": target.run_id,
                "argv": None,
                "shell": False,
                "residue_absent": True,
            }

        source = f"fortgym-m1b-enospc-{target.run_id}"
        self._validate_mount(observed, target, source)
        self._load_and_validate_marker(
            target.workspace / ".fortgym-m1b-workspace-owner.json",
            target,
            peer_run_id=target.peer_run_id,
        )
        argv = ("/bin/umount", "--", str(target.workspace))
        result = self._run_exact(argv, timeout_seconds=30.0)
        if result.returncode != 0:
            raise FaultActionError("private tmpfs recovery unmount failed")
        if self._mount_probe(target.workspace) is not None:
            raise FaultEvidenceError(
                "private tmpfs remains mounted after reconciliation"
            )
        try:
            target.workspace.rmdir()
        except OSError as exc:
            raise FaultEvidenceError(
                "private tmpfs mountpoint is not empty after reconciliation"
            ) from exc
        if not self.audit_absent(target):
            raise FaultEvidenceError("private tmpfs reconciliation left residue")
        return {
            "schema": TMPFS_LIFECYCLE_SCHEMA,
            "operation": "reconciled",
            "run_id": target.run_id,
            "argv": list(argv),
            "shell": False,
            "residue_absent": True,
        }

    def audit_absent(
        self,
        run: OwnedRun | PrelaunchEnospcTarget | EnospcWorkspaceCleanupTarget,
    ) -> bool:
        return self._mount_probe(run.workspace) is None and not self._path_exists(
            run.workspace
        )

    def _load_and_validate_marker(
        self,
        marker_path: Path,
        run: OwnedRun | PrelaunchEnospcTarget,
        *,
        peer_run_id: str,
    ) -> None:
        if not self._path_exists(marker_path):
            raise FaultEvidenceError("private tmpfs ownership marker is absent")
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultEvidenceError(
                "private tmpfs ownership marker is invalid"
            ) from exc
        _validate_workspace_marker(
            _mapping("tmpfs owner marker", marker),
            run,
            peer_run_id=peer_run_id,
        )

    def _rollback_failed_prepare(
        self, target: PrelaunchEnospcTarget, source: str
    ) -> None:
        observed = self._mount_probe(target.workspace)
        self._validate_mount(observed, target, source)
        marker_path = target.workspace / ".fortgym-m1b-workspace-owner.json"
        if self._path_exists(marker_path):
            self._load_and_validate_marker(
                marker_path, target, peer_run_id=target.peer_run_id
            )
        argv = ("/bin/umount", "--", str(target.workspace))
        result = self._run_exact(argv, timeout_seconds=30.0)
        if result.returncode != 0 or self._mount_probe(target.workspace) is not None:
            raise FaultEvidenceError(
                "failed ENOSPC prelaunch evidence write left a mounted workspace"
            )
        target.workspace.rmdir()

    def _find_mount(self, path: Path) -> Mapping[str, Any] | None:
        return _find_exact_mount_with_runner(self._runner, path)

    @staticmethod
    def _validate_mount(
        observed: Mapping[str, Any] | None,
        run: OwnedRun | PrelaunchEnospcTarget,
        source: str,
    ) -> None:
        _validate_private_tmpfs_mount(observed, run, source=source)

    def _run_exact(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        allow_failure: bool = False,
    ) -> FaultCommandResult:
        normalized = _command_vector(argv)
        result = self._runner.run(normalized, timeout_seconds=timeout_seconds)
        if not isinstance(result, FaultCommandResult) or result.argv != normalized:
            raise FaultActionError("tmpfs command evidence differs")
        if result.returncode != 0 and not allow_failure:
            raise FaultActionError(
                f"tmpfs command failed with return code {result.returncode}"
            )
        return result


# Backward-compatible name for the already-private helper.  New integrations
# should use the phase-explicit class and method names above.
PrivateTmpfsWorkspace = PrelaunchEnospcWorkspace


@dataclass(frozen=True)
class _FaultAction:
    kind: str
    argv: tuple[str, ...]
    timeout_seconds: float

    def public_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "argv": list(self.argv),
            "shell": False,
            "timeout_seconds": self.timeout_seconds,
        }


class _ObservationJournal:
    def __init__(
        self,
        path: Path,
        *,
        gate: FaultGate,
        target: OwnedRun,
        now: Callable[[], datetime],
    ) -> None:
        self.path = path
        self.gate = gate
        self.target = target
        self.now = now

    def append(self, phase: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        phase = _bounded_string(phase, "fault evidence phase", maximum=64)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            existing = _read_journal_descriptor(
                descriptor,
                expected_run_id=self.target.run_id,
                expected_contract_sha256=self.target.contract_sha256,
                expected_nonce_sha256=_nonce_sha256(self.target.nonce),
                expected_gate=self.gate,
            )
            if any(record.get("phase") == "completed" for record in existing):
                raise FaultEvidenceError("fault observation is already complete")
            if any(record.get("phase") == "failed" for record in existing):
                raise FaultEvidenceError("failed fault observation cannot be resumed")
            timestamp = self.now()
            if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
                raise FaultEvidenceError("fault evidence clock must be timezone-aware")
            record = {
                "schema": FAULT_DRIVER_OBSERVATION_SCHEMA,
                "event_index": len(existing) + 1,
                "recorded_at": timestamp.astimezone(UTC).isoformat(),
                "phase": phase,
                "gate": self.gate.value,
                "run_id": self.target.run_id,
                "contract_sha256": self.target.contract_sha256,
                "nonce_sha256": _nonce_sha256(self.target.nonce),
                "payload": dict(payload),
            }
            encoded = (
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            if len(encoded) > _MAX_RECORD_BYTES:
                raise FaultEvidenceError(
                    "fault evidence record exceeds the bounded size"
                )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short append to fault observation journal")
                view = view[written:]
            os.fsync(descriptor)
            return record
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def fault_observation_journal_path(control_root: Path | str, run_id: str) -> Path:
    """Return the one canonical per-run driver observation path."""

    root = _absolute_path("control_root", control_root).resolve(strict=False)
    if root == Path(root.anchor):
        raise ValueError("control_root cannot be a filesystem root")
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be filesystem-safe")
    return root / run_id / "fault-driver-observations.jsonl"


def load_completed_fault_observation(
    *,
    control_root: Path | str,
    run_id: str,
    contract_sha256: str,
    nonce: str,
    expected_gate: FaultGate | None = None,
) -> Mapping[str, Any] | None:
    """Load one strict completed driver record or return ``None``.

    Absence, an empty journal, or a journal containing only pre-completion or
    failed records returns ``None``.  Any malformed, mismatched, duplicated, or
    contradictory completed evidence raises :class:`FaultEvidenceError`; it is
    never interpreted as a terminal.
    """

    if not _SHA256_RE.fullmatch(contract_sha256):
        raise ValueError("contract_sha256 must be a lowercase SHA-256")
    if not _NONCE_RE.fullmatch(nonce):
        raise ValueError("nonce must be 128-256 bits encoded as lowercase hex")
    if expected_gate is not None and not isinstance(expected_gate, FaultGate):
        raise TypeError("expected_gate must be FaultGate or None")
    path = fault_observation_journal_path(control_root, run_id)
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        records = _read_journal_descriptor(
            descriptor,
            expected_run_id=run_id,
            expected_contract_sha256=contract_sha256,
            expected_nonce_sha256=_nonce_sha256(nonce),
            expected_gate=expected_gate,
        )
    finally:
        os.close(descriptor)
    completed = [record for record in records if record.get("phase") == "completed"]
    if not completed:
        return None
    if len(completed) != 1 or completed[-1] is not records[-1]:
        raise FaultEvidenceError("completed fault observation must be unique and final")
    record = completed[0]
    _validate_completed_payload(
        _mapping("completed payload", record.get("payload")),
        FaultGate(record["gate"]),
        expected_run_id=run_id,
        expected_contract_sha256=contract_sha256,
        expected_nonce_sha256=_nonce_sha256(nonce),
    )
    return MappingProxyType(record)


def _read_journal_descriptor(
    descriptor: int,
    *,
    expected_run_id: str,
    expected_contract_sha256: str,
    expected_nonce_sha256: str,
    expected_gate: FaultGate | None,
) -> list[dict[str, Any]]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    data = bytearray()
    while True:
        chunk = os.read(descriptor, 64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 8 * _MAX_RECORD_BYTES:
            raise FaultEvidenceError("fault observation journal exceeds its bound")
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise FaultEvidenceError("fault observation journal has a partial record")
    records: list[dict[str, Any]] = []
    observed_gate: FaultGate | None = None
    for index, raw_line in enumerate(data.splitlines(), start=1):
        if len(raw_line) > _MAX_RECORD_BYTES:
            raise FaultEvidenceError("fault observation record exceeds its bound")
        try:
            decoded = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultEvidenceError(
                "fault observation journal is invalid JSONL"
            ) from exc
        record = _mapping("fault observation record", decoded)
        _exact_keys(
            "fault observation record",
            record,
            {
                "schema",
                "event_index",
                "recorded_at",
                "phase",
                "gate",
                "run_id",
                "contract_sha256",
                "nonce_sha256",
                "payload",
            },
        )
        try:
            gate = FaultGate(record.get("gate"))
        except (TypeError, ValueError) as exc:
            raise FaultEvidenceError("fault observation gate is invalid") from exc
        if observed_gate is None:
            observed_gate = gate
        if (
            record.get("schema") != FAULT_DRIVER_OBSERVATION_SCHEMA
            or record.get("event_index") != index
            or record.get("run_id") != expected_run_id
            or record.get("contract_sha256") != expected_contract_sha256
            or record.get("nonce_sha256") != expected_nonce_sha256
            or gate is not observed_gate
            or (expected_gate is not None and gate is not expected_gate)
            or not isinstance(record.get("recorded_at"), str)
            or not isinstance(record.get("phase"), str)
        ):
            raise FaultEvidenceError("fault observation binding or sequence differs")
        _mapping("fault observation payload", record.get("payload"))
        records.append(dict(record))
    return records


def _validate_completed_payload(
    payload: Mapping[str, Any],
    gate: FaultGate,
    *,
    expected_run_id: str,
    expected_contract_sha256: str,
    expected_nonce_sha256: str,
) -> None:
    expected_payload_keys = {
        "target",
        "peer",
        "barrier",
        "ownership",
        "before",
        "action",
        "after",
        "peer_after",
        "canaries",
        "timing",
        "classifier_evidence_schema",
        "classifier_evidence",
        "pending_external_checks",
    }
    if gate is FaultGate.OOM:
        expected_payload_keys.add("peer_before_release")
    _exact_keys(
        "completed payload",
        payload,
        expected_payload_keys,
    )
    if payload.get("classifier_evidence_schema") != _CLASSIFIER_EVIDENCE_SCHEMA:
        raise FaultEvidenceError("completed classifier evidence schema differs")
    for key in (
        "target",
        "peer",
        "barrier",
        "ownership",
        "before",
        "action",
        "after",
        "peer_after",
        "canaries",
        "timing",
        "classifier_evidence",
    ):
        _mapping(f"completed {key}", payload.get(key))
    if gate is FaultGate.OOM:
        _mapping("completed peer_before_release", payload.get("peer_before_release"))
    action = _mapping("completed action", payload.get("action"))
    if action.get("kind") == "command" and action.get("shell") is not False:
        raise FaultEvidenceError(
            "completed command evidence does not prove shell=False"
        )
    target = _mapping("completed target", payload.get("target"))
    peer = _mapping("completed peer", payload.get("peer"))
    if (
        target.get("run_id") != expected_run_id
        or target.get("contract_sha256") != expected_contract_sha256
        or target.get("nonce_sha256") != expected_nonce_sha256
        or peer.get("run_id") == expected_run_id
    ):
        raise FaultEvidenceError("completed target/peer binding differs")
    _validate_completed_action(gate, action, target)
    barrier = _mapping("completed barrier", payload.get("barrier"))
    target_barrier = _mapping("completed target barrier", barrier.get("target"))
    peer_barrier = _mapping("completed peer barrier", barrier.get("peer"))
    expected_barrier_schema = (
        COHORT_START_SCHEMA if gate is FaultGate.OOM else STEP2_BARRIER_SCHEMA
    )
    if (
        target_barrier.get("schema") != expected_barrier_schema
        or peer_barrier.get("schema") != expected_barrier_schema
        or target_barrier.get("run_id") != expected_run_id
        or target_barrier.get("contract_sha256") != expected_contract_sha256
        or target_barrier.get("nonce_sha256") != expected_nonce_sha256
        or target_barrier.get("durable") is not True
        or peer_barrier.get("durable") is not True
    ):
        raise FaultEvidenceError("completed durable synchronization evidence differs")
    canaries = _mapping("completed canaries", payload.get("canaries"))
    if canaries.get("all_untouched") is not True:
        raise FaultEvidenceError("completed evidence does not preserve canaries")
    timing = _mapping("completed timing", payload.get("timing"))
    _exact_keys(
        "completed timing",
        timing,
        {"target_detection_seconds", "all_required_observations_seconds"},
    )
    target_duration = timing.get("target_detection_seconds")
    all_duration = timing.get("all_required_observations_seconds")
    if (
        any(
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration < 0
            for duration in (target_duration, all_duration)
        )
        or all_duration < target_duration
    ):
        raise FaultEvidenceError("completed fault timing is invalid")
    if gate is FaultGate.DF_KILL and target_duration > 10:
        raise FaultEvidenceError("completed DF-KILL timing exceeds 10 seconds")
    if gate is FaultGate.DAEMON_RESTART and all_duration > 120:
        raise FaultEvidenceError("completed daemon reconciliation exceeds 120 seconds")
    pending = payload.get("pending_external_checks")
    if (
        not isinstance(pending, list)
        or not pending
        or any(not isinstance(item, str) or not item for item in pending)
        or "cleanup_double_audit" not in pending
    ):
        raise FaultEvidenceError("completed evidence omits external cleanup checks")
    if gate is FaultGate.OOM:
        _validate_completed_pre_readiness_oom(
            payload,
            expected_run_id=expected_run_id,
            expected_contract_sha256=expected_contract_sha256,
            expected_nonce_sha256=expected_nonce_sha256,
        )


def _validate_completed_action(
    gate: FaultGate, action: Mapping[str, Any], target: Mapping[str, Any]
) -> None:
    if gate is FaultGate.DF_KILL:
        expected = [_KILL, "-KILL", "--", str(target.get("runtime_host_pid"))]
        if action.get("kind") != "command" or action.get("argv") != expected:
            raise FaultEvidenceError("completed DF-KILL action differs")
        if str(target.get("runtime_container_pid")) in expected:
            raise FaultEvidenceError("completed DF-KILL confused PID namespaces")
    elif gate is FaultGate.HARNESS_KILL:
        expected = [_KILL, "-KILL", "--", str(target.get("harness_pid"))]
        if action.get("kind") != "command" or action.get("argv") != expected:
            raise FaultEvidenceError("completed HARNESS-KILL action differs")
    elif gate is FaultGate.OOM:
        _exact_keys(
            "completed OOM action",
            action,
            {
                "kind",
                "profile",
                "memory_bytes",
                "late_runtime_mutation",
                "argv",
                "shell",
            },
        )
        if (
            action.get("kind") != "prelaunched_fault_profile"
            or action.get("profile") != _OOM_FAULT_PROFILE
            or action.get("memory_bytes") != _OOM_MEMORY_BYTES
            or action.get("late_runtime_mutation") is not False
            or action.get("argv") != []
            or action.get("shell") is not False
        ):
            raise FaultEvidenceError("completed OOM action is not create-time-only")
    elif gate is FaultGate.ENOSPC:
        argv = action.get("argv")
        enospc = _mapping("completed ENOSPC action", action.get("enospc"))
        if (
            action.get("kind") != "command"
            or not isinstance(argv, list)
            or len(argv) != 6
            or argv[1:3] != ["-I", "-c"]
            or argv[-2]
            != str(Path(str(target.get("workspace"))) / ".fortgym-m1b-enospc.fill")
            or argv[-1] != str(MAX_WORKSPACE_FAULT_BYTES)
            or enospc.get("errno") != 28
            or enospc.get("maximum_fault_bytes") != MAX_WORKSPACE_FAULT_BYTES
        ):
            raise FaultEvidenceError(
                "completed ENOSPC action differs or exceeds its bound"
            )
    elif gate is FaultGate.CONTAINER_RESTART:
        expected = [
            _DOCKER,
            "restart",
            "--time",
            "0",
            str(target.get("container_id")),
        ]
        if action.get("kind") != "command" or action.get("argv") != expected:
            raise FaultEvidenceError("completed container-restart action differs")
    elif gate is FaultGate.DAEMON_RESTART:
        callback = _mapping("completed daemon callback", action.get("callback"))
        _validate_daemon_callback_fields(callback)
        if (
            action.get("kind") != "external_host_callback"
            or callback.get("schema") != DAEMON_RESTART_CALLBACK_SCHEMA
            or callback.get("host_controller") is not True
            or callback.get("inside_container") is not False
            or callback.get("invoked") is not True
        ):
            raise FaultEvidenceError(
                "completed daemon action lacks host callback proof"
            )


def _validate_barrier_record(
    value: Mapping[str, Any], run: OwnedRun
) -> Mapping[str, Any]:
    record = _mapping("step-2 barrier record", value)
    _exact_keys(
        "step-2 barrier record",
        record,
        {
            "schema",
            "run_id",
            "contract_sha256",
            "nonce",
            "cohort_sha256",
            "container_id",
            "runtime_host_pid",
            "runtime_container_pid",
            "harness_pid",
            "workspace",
            "step",
            "state",
            "durable",
            "journal_record_sha256",
        },
    )
    expected = {
        "schema": STEP2_BARRIER_SCHEMA,
        "run_id": run.run_id,
        "contract_sha256": run.contract_sha256,
        "nonce": run.nonce,
        "cohort_sha256": run.cohort_sha256,
        "container_id": run.container_id,
        "runtime_host_pid": run.runtime_host_pid,
        "runtime_container_pid": run.runtime_container_pid,
        "harness_pid": run.harness_pid,
        "workspace": str(run.workspace),
        "step": 2,
        "state": "reached",
        "durable": True,
    }
    if any(
        record.get(key) != expected_value for key, expected_value in expected.items()
    ):
        raise FaultEvidenceError("step-2 barrier record identity or durability differs")
    if not _SHA256_RE.fullmatch(str(record.get("journal_record_sha256") or "")):
        raise FaultEvidenceError("step-2 barrier durable receipt SHA-256 is invalid")
    return record


def _validate_cohort_start_record(
    value: Mapping[str, Any], run: OwnedRun, *, role: str
) -> Mapping[str, Any]:
    record = _mapping("OOM cohort-start record", value)
    _exact_keys(
        "OOM cohort-start record",
        record,
        {
            "schema",
            "run_id",
            "contract_sha256",
            "nonce",
            "cohort_sha256",
            "container_id",
            "role",
            "memory_bytes",
            "memory_swap_bytes",
            "fault_profile",
            "provider_free",
            "state",
            "durable",
            "journal_record_sha256",
        },
    )
    if role not in {"target", "peer"}:
        raise AssertionError("invalid OOM cohort-start role")
    target = role == "target"
    expected = {
        "schema": COHORT_START_SCHEMA,
        "run_id": run.run_id,
        "contract_sha256": run.contract_sha256,
        "nonce": run.nonce,
        "cohort_sha256": run.cohort_sha256,
        "container_id": run.container_id,
        "role": role,
        "memory_bytes": _OOM_MEMORY_BYTES if target else _NORMAL_MEMORY_BYTES,
        "memory_swap_bytes": _OOM_MEMORY_BYTES if target else _NORMAL_MEMORY_BYTES,
        "fault_profile": _OOM_FAULT_PROFILE if target else None,
        "provider_free": True,
        "state": "container_created",
        "durable": True,
    }
    if any(
        record.get(key) != expected_value for key, expected_value in expected.items()
    ):
        raise FaultEvidenceError(
            "OOM cohort-start identity or create-time profile differs"
        )
    if not _SHA256_RE.fullmatch(str(record.get("journal_record_sha256") or "")):
        raise FaultEvidenceError("OOM cohort-start durable receipt SHA-256 is invalid")
    return record


def _validate_ownership_record(
    value: Mapping[str, Any], run: OwnedRun
) -> Mapping[str, Any]:
    record = _mapping("run ownership record", value)
    _exact_keys(
        "run ownership record",
        record,
        {
            "schema",
            "run_id",
            "contract_sha256",
            "nonce",
            "cohort_sha256",
            "container",
            "runtime_process",
            "harness_process",
            "supervisor_process",
            "workspace_owner",
        },
    )
    if (
        record.get("schema") != RUN_OWNERSHIP_SCHEMA
        or record.get("run_id") != run.run_id
        or record.get("contract_sha256") != run.contract_sha256
        or record.get("nonce") != run.nonce
        or record.get("cohort_sha256") != run.cohort_sha256
    ):
        raise FaultEvidenceError("run ownership record identity differs")
    container = _mapping("owned container", record.get("container"))
    _exact_keys(
        "owned container", container, {"id", "labels", "environment", "host_config"}
    )
    labels = _mapping("owned container labels", container.get("labels"))
    environment = _mapping("owned container environment", container.get("environment"))
    _exact_keys(
        "owned container labels", labels, {"managed", "run_id", "contract_sha256"}
    )
    _exact_keys(
        "owned container environment",
        environment,
        {"run_id", "contract_sha256", "nonce"},
    )
    if (
        container.get("id") != run.container_id
        or labels
        != {
            "managed": "true",
            "run_id": run.run_id,
            "contract_sha256": run.contract_sha256,
        }
        or environment
        != {
            "run_id": run.run_id,
            "contract_sha256": run.contract_sha256,
            "nonce": run.nonce,
        }
    ):
        raise FaultEvidenceError("container ownership identity differs")
    host_config = _mapping("owned container host_config", container.get("host_config"))
    _exact_keys(
        "owned container host_config",
        host_config,
        {"memory_bytes", "memory_swap_bytes", "fault_profile"},
    )
    for name in ("memory_bytes", "memory_swap_bytes"):
        value = host_config.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FaultEvidenceError(f"owned container {name} is invalid")
    profile = host_config.get("fault_profile")
    if profile is not None and profile != _OOM_FAULT_PROFILE:
        raise FaultEvidenceError("owned container fault profile is invalid")
    runtime = _mapping("owned runtime process", record.get("runtime_process"))
    harness = _mapping("owned harness process", record.get("harness_process"))
    supervisor = _mapping("owned supervisor process", record.get("supervisor_process"))
    _exact_keys(
        "owned runtime process",
        runtime,
        {
            "host_pid",
            "container_pid",
            "run_id",
            "container_id",
            "executable_basename",
            "cgroup_path",
        },
    )
    _exact_keys("owned harness process", harness, {"pid", "run_id", "process_group_id"})
    _exact_keys("owned supervisor process", supervisor, {"pid", "operational"})
    if runtime != {
        "host_pid": run.runtime_host_pid,
        "container_pid": run.runtime_container_pid,
        "run_id": run.run_id,
        "container_id": run.container_id,
        "executable_basename": "Dwarf_Fortress",
        "cgroup_path": run.runtime_cgroup_path,
    } or harness != {
        "pid": run.harness_pid,
        "run_id": run.run_id,
        "process_group_id": run.harness_process_group_id,
    }:
        raise FaultEvidenceError("process ownership identity differs")
    if supervisor != {"pid": run.supervisor_pid, "operational": True}:
        raise FaultEvidenceError("supervisor process ownership identity differs")
    workspace = _mapping("workspace owner", record.get("workspace_owner"))
    _exact_keys(
        "workspace owner",
        workspace,
        {"path", "run_id", "private", "filesystem", "size_bytes"},
    )
    size = workspace.get("size_bytes")
    if (
        workspace.get("path") != str(run.workspace)
        or workspace.get("run_id") != run.run_id
        or workspace.get("private") is not True
        or not isinstance(workspace.get("filesystem"), str)
        or not workspace.get("filesystem")
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
    ):
        raise FaultEvidenceError("workspace ownership identity differs")
    return record


def _validate_state_record(
    value: Mapping[str, Any], gate: FaultGate, run: OwnedRun, phase: str
) -> Mapping[str, Any]:
    record = _mapping("fault state record", value)
    _exact_keys(
        "fault state record",
        record,
        {
            "schema",
            "gate",
            "phase",
            "run_id",
            "contract_sha256",
            "nonce",
            "container_id",
            "runtime_host_pid",
            "runtime_container_pid",
            "harness_pid",
            "workspace",
            "facts",
        },
    )
    expected = {
        "schema": FAULT_STATE_SCHEMA,
        "gate": gate.value,
        "phase": phase,
        "run_id": run.run_id,
        "contract_sha256": run.contract_sha256,
        "nonce": run.nonce,
        "container_id": run.container_id,
        "runtime_host_pid": run.runtime_host_pid,
        "runtime_container_pid": run.runtime_container_pid,
        "harness_pid": run.harness_pid,
        "workspace": str(run.workspace),
    }
    if any(
        record.get(key) != expected_value for key, expected_value in expected.items()
    ):
        raise FaultEvidenceError("fault state identity or phase differs")
    _mapping("fault state facts", record.get("facts"))
    return record


def _validate_oom_peer_before_release(
    facts: Mapping[str, Any],
    *,
    target_run_id: str,
    cohort_sha256: str,
) -> dict[str, Any]:
    """Require one durable, healthy normal-peer baseline before target release."""

    _exact_keys(
        "OOM peer-before-release facts",
        facts,
        {
            "target_run_id",
            "cohort_sha256",
            "status",
            "step",
            "runtime_ready",
            "healthy",
            "reconnected",
            "continued_before_fault",
            "connection_generation",
            "durable",
            "readiness_receipt_sha256",
        },
    )
    step = _nonnegative_int(facts.get("step"), "OOM peer readiness step")
    generation = facts.get("connection_generation")
    if (
        facts.get("target_run_id") != target_run_id
        or facts.get("cohort_sha256") != cohort_sha256
        or facts.get("status") != "running"
        or step < 2
        or facts.get("runtime_ready") is not True
        or facts.get("healthy") is not True
        or facts.get("reconnected") is not False
        or facts.get("continued_before_fault") is not True
        or not _SHA256_RE.fullmatch(str(generation or ""))
        or facts.get("durable") is not True
        or not _SHA256_RE.fullmatch(str(facts.get("readiness_receipt_sha256") or ""))
    ):
        raise FaultEvidenceError(
            "normal-cap peer lacks a durable healthy pre-release baseline"
        )
    return dict(facts)


def _validate_oom_peer_readiness_continuity(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    target_run_id: str,
    cohort_sha256: str,
) -> None:
    before_facts = _validate_oom_peer_before_release(
        _mapping("OOM initial peer-before-release facts", before.get("facts")),
        target_run_id=target_run_id,
        cohort_sha256=cohort_sha256,
    )
    after_facts = _validate_oom_peer_before_release(
        _mapping("OOM revalidated peer-before-release facts", after.get("facts")),
        target_run_id=target_run_id,
        cohort_sha256=cohort_sha256,
    )
    immutable_state_keys = {
        "schema",
        "gate",
        "phase",
        "run_id",
        "contract_sha256",
        "nonce",
        "container_id",
        "runtime_host_pid",
        "runtime_container_pid",
        "harness_pid",
        "workspace",
    }
    if any(before.get(key) != after.get(key) for key in immutable_state_keys):
        raise FaultEvidenceError("normal-cap peer readiness identity changed")
    if (
        after_facts["step"] < before_facts["step"]
        or after_facts["connection_generation"] != before_facts["connection_generation"]
    ):
        raise FaultEvidenceError(
            "normal-cap peer readiness regressed or silently reconnected"
        )


def _validate_fault_facts(
    gate: FaultGate,
    target: OwnedRun,
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    peer_after: Mapping[str, Any],
    action: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_peer_after(gate, target, peer_after)
    identity = {"expected": target.container_id, "observed": target.container_id}
    if gate is FaultGate.DF_KILL:
        _exact_keys(
            "DF-KILL before",
            before,
            {"runtime_identity", "runtime_state", "oom_killed"},
        )
        _exact_keys(
            "DF-KILL after",
            after,
            {
                "runtime_identity",
                "runtime_state",
                "runtime_exit_code",
                "signal",
                "oom_killed",
            },
        )
        if (
            before.get("runtime_identity") != target.container_id
            or before.get("runtime_state") != "running"
            or before.get("oom_killed") is not False
            or after.get("runtime_identity") != target.container_id
            or after.get("runtime_state") != "exited"
            or after.get("runtime_exit_code") != 137
            or after.get("signal") != 9
            or after.get("oom_killed") is not False
        ):
            raise FaultEvidenceError(
                "DF-KILL facts do not prove the exact non-OOM kill"
            )
        return {"runtime_identity": identity, "signal": 9, "oom_killed": False}
    if gate is FaultGate.HARNESS_KILL:
        _exact_keys(
            "HARNESS-KILL before",
            before,
            {"child_pid", "child_state", "process_group_members"},
        )
        _exact_keys(
            "HARNESS-KILL after",
            after,
            {"child_pid", "child_state", "signal", "process_group_members"},
        )
        before_members = _positive_int_sequence(
            before.get("process_group_members"), "before process group"
        )
        after_members = _positive_int_sequence(
            after.get("process_group_members"), "after process group"
        )
        if (
            before.get("child_pid") != target.harness_pid
            or before.get("child_state") != "running"
            or target.harness_pid not in before_members
            or after.get("child_pid") != target.harness_pid
            or after.get("child_state") != "signaled"
            or after.get("signal") != 9
            or target.harness_pid in after_members
        ):
            raise FaultEvidenceError(
                "HARNESS-KILL facts do not prove the exact child signal"
            )
        return {"child_pid": target.harness_pid, "signal": 9}
    if gate is FaultGate.OOM:
        _exact_keys(
            "OOM before",
            before,
            {
                "runtime_identity",
                "runtime_exit_code",
                "cgroup_memory_events",
                "host_oom_counter",
            },
        )
        _exact_keys("OOM after", after, set(before))
        before_events = _memory_events(before.get("cgroup_memory_events"), "OOM before")
        after_events = _memory_events(after.get("cgroup_memory_events"), "OOM after")
        if (
            before.get("runtime_identity") != target.container_id
            or before.get("runtime_exit_code") is not None
            or after.get("runtime_identity") != target.container_id
            or after.get("runtime_exit_code") != 137
            or after_events["oom_kill"] <= before_events["oom_kill"]
            or after_events["oom"] < before_events["oom"]
            or _nonnegative_int(before.get("host_oom_counter"), "host OOM before")
            != _nonnegative_int(after.get("host_oom_counter"), "host OOM after")
        ):
            raise FaultEvidenceError("OOM facts lack cgroup-only OOM proof")
        return {
            "runtime_identity": identity,
            "runtime_exit_code": 137,
            "cgroup_memory_events": {"before": before_events, "after": after_events},
        }
    if gate is FaultGate.ENOSPC:
        _exact_keys("ENOSPC before", before, {"operation", "workspace"})
        _exact_keys("ENOSPC after", after, set(before))
        before_workspace = _workspace_fault(before.get("workspace"), target, "before")
        after_workspace = _workspace_fault(after.get("workspace"), target, "after")
        operation = _bounded_string(
            after.get("operation"), "ENOSPC operation", maximum=128
        )
        enospc_action = _mapping("ENOSPC action evidence", action.get("enospc"))
        action_fault_bytes = _nonnegative_int(
            enospc_action.get("fault_bytes"), "ENOSPC action fault bytes"
        )
        if (
            before.get("operation") != operation
            or before_workspace["fault_bytes"] != 0
            or after_workspace["fault_bytes"] <= 0
            or enospc_action.get("errno") != 28
            or enospc_action.get("maximum_fault_bytes") != MAX_WORKSPACE_FAULT_BYTES
            or action_fault_bytes != after_workspace["fault_bytes"]
        ):
            raise FaultEvidenceError("ENOSPC facts lack exact bounded errno-28 proof")
        classifier_workspace = {
            key: after_workspace[key]
            for key in (
                "run_id",
                "scope_root",
                "fault_path",
                "fault_bytes",
                "maximum_fault_bytes",
            )
        }
        return {"errno": 28, "operation": operation, "workspace": classifier_workspace}
    if gate is FaultGate.CONTAINER_RESTART:
        restart_keys = {
            "container_identity", "restart_count", "running",
            "rpc_connection_generation", "reconnected", "terminal_observed",
        }
        has_generation = "runtime_generation" in before or "runtime_generation" in after
        if has_generation:
            restart_keys.add("runtime_generation")
        _exact_keys(
            "CONTAINER-RESTART before",
            before,
            restart_keys,
        )
        _exact_keys("CONTAINER-RESTART after", after, set(before))
        before_count = _nonnegative_int(
            before.get("restart_count"), "restart count before"
        )
        after_count = _nonnegative_int(
            after.get("restart_count"), "restart count after"
        )
        generation_changed = False
        if has_generation:
            if any(
                not isinstance(facts.get("runtime_generation"), str)
                or not _SHA256_RE.fullmatch(facts["runtime_generation"])
                for facts in (before, after)
            ):
                raise FaultEvidenceError("container process generation is invalid")
            generation_changed = before["runtime_generation"] != after["runtime_generation"]
        before_generation = _bounded_string(
            before.get("rpc_connection_generation"),
            "RPC connection generation before restart",
            maximum=256,
        )
        after_generation = _bounded_string(
            after.get("rpc_connection_generation"),
            "RPC connection generation after restart",
            maximum=256,
        )
        if (
            before.get("container_identity") != target.container_id
            or after.get("container_identity") != target.container_id
            or before.get("running") is not True
            or not isinstance(after.get("running"), bool)
            or (not generation_changed if has_generation else after_count <= before_count)
            or before_generation != after_generation
            or before.get("reconnected") is not False
            or after.get("reconnected") is not False
            or before.get("terminal_observed") is not False
            or after.get("terminal_observed") is not True
        ):
            raise FaultEvidenceError(
                "container restart facts lack restart delta or anti-reconnect terminal proof"
            )
        evidence = {
            "container_identity": {
                "expected": target.container_id,
                "before": target.container_id,
                "after": target.container_id,
            },
            "restart_count": {"before": before_count, "after": after_count},
        }
        if has_generation:
            evidence["runtime_generation"] = {
                "before": before["runtime_generation"],
                "after": after["runtime_generation"],
            }
        return evidence
    if gate is FaultGate.DAEMON_RESTART:
        expected_keys = {
            "daemon_generation",
            "runtime_identity",
            "inside_container",
            "supervisor_operational",
            "rpc_connection_generation",
            "reconnected",
            "terminal_observed",
            "silent_continuation",
        }
        _exact_keys("DAEMON-RESTART before", before, expected_keys)
        _exact_keys("DAEMON-RESTART after", after, expected_keys)
        before_generation = _bounded_string(
            before.get("daemon_generation"), "daemon generation before", maximum=256
        )
        after_generation = _bounded_string(
            after.get("daemon_generation"), "daemon generation after", maximum=256
        )
        before_connection = _bounded_string(
            before.get("rpc_connection_generation"),
            "RPC connection generation before daemon restart",
            maximum=256,
        )
        after_connection = _bounded_string(
            after.get("rpc_connection_generation"),
            "RPC connection generation after daemon restart",
            maximum=256,
        )
        if (
            before_generation == after_generation
            or before.get("runtime_identity") != target.container_id
            or after.get("runtime_identity") != target.container_id
            or before.get("inside_container") is not False
            or after.get("inside_container") is not False
            or before.get("supervisor_operational") is not True
            or after.get("supervisor_operational") is not True
            or before_connection != after_connection
            or before.get("reconnected") is not False
            or after.get("reconnected") is not False
            or before.get("terminal_observed") is not False
            or after.get("terminal_observed") is not True
            or before.get("silent_continuation") is not False
            or after.get("silent_continuation") is not False
        ):
            raise FaultEvidenceError(
                "daemon restart facts lack external generation proof"
            )
        return {
            "daemon_generation": {
                "before": before_generation,
                "after": after_generation,
            },
            "runtime_identity": identity,
        }
    raise AssertionError(f"unhandled fault gate {gate!r}")


def _validate_peer_after(
    gate: FaultGate, target: OwnedRun, facts: Mapping[str, Any]
) -> None:
    if gate is FaultGate.OOM:
        _exact_keys(
            "OOM peer-after facts",
            facts,
            {
                "step",
                "healthy",
                "runtime_ready",
                "reconnected",
                "continued_after_fault",
                "target_run_id",
                "cohort_sha256",
                "connection_generation",
            },
        )
        step = _nonnegative_int(facts.get("step"), "OOM peer-after step")
        if (
            facts.get("target_run_id") != target.run_id
            or facts.get("cohort_sha256") != target.cohort_sha256
            or step < 3
            or facts.get("healthy") is not True
            or facts.get("runtime_ready") is not True
            or facts.get("reconnected") is not False
            or facts.get("continued_after_fault") is not True
            or not _SHA256_RE.fullmatch(str(facts.get("connection_generation") or ""))
        ):
            raise FaultEvidenceError(
                "OOM peer did not prove healthy continuation without reconnect"
            )
        return
    _exact_keys(
        "peer-after facts",
        facts,
        {"step", "healthy", "reconnected", "continued_after_fault", "target_run_id"},
    )
    step = _nonnegative_int(facts.get("step"), "peer-after step")
    if (
        facts.get("target_run_id") != target.run_id
        or facts.get("reconnected") is not False
    ):
        raise FaultEvidenceError("peer-after facts are not bound to the target fault")
    if gate in {FaultGate.DF_KILL, FaultGate.HARNESS_KILL}:
        if (
            step < 5
            or facts.get("healthy") is not True
            or facts.get("continued_after_fault") is not True
        ):
            raise FaultEvidenceError(
                "peer did not prove healthy continuation through step 5"
            )
    elif gate is FaultGate.DAEMON_RESTART:
        if (
            step < 2
            or facts.get("healthy") is not False
            or facts.get("continued_after_fault") is not False
        ):
            raise FaultEvidenceError("daemon restart peer silently continued")
    elif (
        step < 3
        or facts.get("healthy") is not True
        or facts.get("continued_after_fault") is not True
    ):
        raise FaultEvidenceError("peer did not prove healthy post-fault continuation")


def _pending_external_checks(gate: FaultGate) -> list[str]:
    """Name proof that necessarily happens after injection observation."""

    gate_specific = {
        FaultGate.DF_KILL: ["cleanup_seconds_lte_30"],
        FaultGate.HARNESS_KILL: [
            "process_group_reaped",
            "runtime_listener_and_lease_removed",
        ],
        FaultGate.OOM: [
            "pre_readiness_oom_terminal_precedence_integration",
            "target_cleanup_verified",
        ],
        FaultGate.ENOSPC: ["private_tmpfs_unmounted_and_absent"],
        FaultGate.CONTAINER_RESTART: ["target_cleanup_verified"],
        FaultGate.DAEMON_RESTART: ["all_affected_runs_terminalized"],
    }
    return [*gate_specific[gate], "cleanup_double_audit"]


def _workspace_fault(value: Any, run: OwnedRun, phase: str) -> dict[str, Any]:
    workspace = _mapping(f"ENOSPC {phase} workspace", value)
    expected_keys = {
        "run_id",
        "scope_root",
        "fault_path",
        "fault_bytes",
        "maximum_fault_bytes",
        "filesystem",
        "private",
        "size_bytes",
    }
    _exact_keys(f"ENOSPC {phase} workspace", workspace, expected_keys)
    scope_root = Path(str(workspace.get("scope_root"))).resolve(strict=False)
    fault_path = Path(str(workspace.get("fault_path"))).resolve(strict=False)
    maximum = _nonnegative_int(
        workspace.get("maximum_fault_bytes"), "ENOSPC maximum fault bytes"
    )
    fault_bytes = _nonnegative_int(workspace.get("fault_bytes"), "ENOSPC fault bytes")
    if (
        workspace.get("run_id") != run.run_id
        or scope_root != run.workspace
        or not _is_relative_to(fault_path, run.workspace)
        or workspace.get("filesystem") != "tmpfs"
        or workspace.get("private") is not True
        or workspace.get("size_bytes") != MAX_WORKSPACE_FAULT_BYTES
        or maximum != MAX_WORKSPACE_FAULT_BYTES
        or fault_bytes > maximum
    ):
        raise FaultEvidenceError(
            "ENOSPC workspace facts exceed or escape the private 16 MiB bound"
        )
    return dict(workspace)


def _memory_events(value: Any, name: str) -> dict[str, int]:
    events = _mapping(name, value)
    _exact_keys(name, events, {"oom", "oom_kill"})
    return {
        "oom": _nonnegative_int(events.get("oom"), f"{name} oom"),
        "oom_kill": _nonnegative_int(events.get("oom_kill"), f"{name} oom_kill"),
    }


def _public_barrier(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.pop("nonce", None)
    payload["nonce_sha256"] = _nonce_sha256(str(record["nonce"]))
    return payload


def _public_ownership(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(record))
    nonce = payload.pop("nonce")
    payload["nonce_sha256"] = _nonce_sha256(nonce)
    environment = payload["container"]["environment"]
    environment_nonce = environment.pop("nonce")
    environment["nonce_sha256"] = _nonce_sha256(environment_nonce)
    return payload


def _public_state(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(record))
    nonce = payload.pop("nonce")
    payload["nonce_sha256"] = _nonce_sha256(nonce)
    return payload


def _command_vector(argv: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(item) for item in argv)
    if not normalized or any(not item or "\0" in item for item in normalized):
        raise FaultActionError("fault command vector contains an empty or NUL argument")
    return normalized


def _bounded_capture(value: str) -> str:
    if not isinstance(value, str):
        raise FaultActionError("fault command output must be text")
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) > _MAX_CAPTURE_BYTES:
        raise FaultActionError("fault command output exceeds the evidence bound")
    return value


def _absolute_path(name: str, value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute() or "\0" in str(path):
        raise ValueError(f"{name} must be an absolute NUL-free path")
    return path


def _paths_overlap(first: Path, second: Path) -> bool:
    return (
        first == second
        or _is_relative_to(first, second)
        or _is_relative_to(second, first)
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _nonce_sha256(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("ascii")).hexdigest()


def _validate_enospc_terminal_chain_prefix(
    *,
    rows: Sequence[Mapping[str, Any]],
    start: Mapping[str, Any],
    attempt_dir: Path,
    contract: Mapping[str, Any],
    target: EnospcWorkspaceCleanupTarget,
    read_bytes: Callable[[Path], bytes],
) -> tuple[dict[str, Any], str]:
    """Validate the durable chain prefix that must precede ENOSPC unmount."""

    prefix_events = (
        "terminal_pending_cleanup",
        "evidence_snapshot_completed",
        "harness_process_group_reaped",
    )
    matches = {
        event: [row for row in rows if row.get("event") == event]
        for event in prefix_events
    }
    if any(len(matches[event]) != 1 for event in prefix_events):
        raise FaultEvidenceError("ENOSPC terminal-chain prefix is incomplete")
    prefix = [matches[event][0] for event in prefix_events]
    child_rows = [row for row in rows if row.get("event") == "child_started"]
    if len(child_rows) != 1:
        raise FaultEvidenceError("ENOSPC terminal-chain child identity differs")
    indices = [rows.index(child_rows[0]), *(rows.index(row) for row in prefix)]
    if indices != sorted(indices) or len(set(indices)) != len(indices):
        raise FaultEvidenceError("ENOSPC terminal-chain prefix order differs")
    if rows.index(prefix[-1]) >= rows.index(start):
        raise FaultEvidenceError("ENOSPC harness reap does not precede post-cleanup")

    rpc = _mapping("ENOSPC terminal-chain RPC identity", contract.get("rpc"))
    child_pid = _positive_evidence_int(
        child_rows[0].get("child_pid"), "ENOSPC terminal-chain child PID"
    )
    expected_identity = {
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce_sha256": _nonce_sha256(target.nonce),
        "environment_identity_sha256": _payload_sha256(contract),
        "child_pid": child_pid,
        "port": rpc.get("port"),
    }
    if child_pid != target.harness_process_group_id:
        raise FaultEvidenceError("ENOSPC terminal-chain child PID differs")
    supervisor_pid = start.get("supervisor_pid")
    for event, row in zip(prefix_events, prefix, strict=True):
        if (
            row.get("schema") != "fortgym.process-supervisor-attempt/v1"
            or row.get("event") != event
            or row.get("run_id") != target.run_id
            or row.get("supervisor_pid") != supervisor_pid
            or row.get("identity") != expected_identity
            or isinstance(row.get("monotonic_ns"), bool)
            or not isinstance(row.get("monotonic_ns"), int)
        ):
            raise FaultEvidenceError(
                f"ENOSPC {event} record has contradictory identity"
            )
    pending, snapshot_row, reaped = prefix
    _exact_keys(
        "ENOSPC terminal-pending-cleanup record",
        pending,
        {
            "schema",
            "at",
            "monotonic_ns",
            "supervisor_pid",
            "event",
            "run_id",
            "identity",
            "primary_terminal_class",
            "primary_reason_sha256",
        },
    )
    if (
        pending.get("primary_terminal_class")
        not in _PROCESS_SUPERVISOR_TERMINAL_CLASSES
        or not _SHA256_RE.fullmatch(
            str(pending.get("primary_reason_sha256") or "")
        )
    ):
        raise FaultEvidenceError("ENOSPC terminal-pending-cleanup record differs")
    _exact_keys(
        "ENOSPC evidence-snapshot record",
        snapshot_row,
        {
            "schema",
            "at",
            "monotonic_ns",
            "supervisor_pid",
            "event",
            "run_id",
            "identity",
            "ok",
            "snapshot_path",
            "snapshot_sha256",
            "fault_snapshot_attached",
            "error",
        },
    )
    snapshot_path = attempt_dir / "evidence-snapshot.json"
    try:
        snapshot_raw = read_bytes(snapshot_path)
    except (OSError, KeyError) as exc:
        raise FaultEvidenceError("ENOSPC generic evidence snapshot is missing") from exc
    if not isinstance(snapshot_raw, bytes) or len(snapshot_raw) > 4 * 1024 * 1024:
        raise FaultEvidenceError("ENOSPC generic evidence snapshot is oversized")
    try:
        snapshot = json.loads(snapshot_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultEvidenceError("ENOSPC generic evidence snapshot is malformed") from exc
    snapshot_sha256 = hashlib.sha256(snapshot_raw).hexdigest()
    if (
        snapshot_row.get("ok") is not True
        or snapshot_row.get("snapshot_path") != str(snapshot_path)
        or snapshot_row.get("snapshot_sha256") != snapshot_sha256
        or snapshot_row.get("error") is not None
        or not isinstance(snapshot, Mapping)
        or snapshot.get("schema")
        != "fortgym.process-supervisor-evidence-snapshot/v1"
        or snapshot.get("identity") != expected_identity
    ):
        raise FaultEvidenceError("ENOSPC generic evidence snapshot binding differs")
    _exact_keys(
        "ENOSPC harness-reap record",
        reaped,
        {
            "schema",
            "at",
            "monotonic_ns",
            "supervisor_pid",
            "event",
            "run_id",
            "identity",
            "ok",
            "skipped",
            "child_pid",
            "group_exists",
        },
    )
    if (
        reaped.get("ok") is not True
        or reaped.get("skipped") is not False
        or reaped.get("child_pid") != child_pid
        or reaped.get("group_exists") is not False
    ):
        raise FaultEvidenceError("ENOSPC harness-reap record differs")
    return expected_identity, snapshot_sha256


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _proc_stat_start_ticks(value: str) -> int:
    try:
        close = value.rindex(")")
        fields = value[close + 2 :].split()
        start_ticks = int(fields[19])
    except (ValueError, IndexError) as exc:
        raise FaultEvidenceError("process stat start-time evidence is malformed") from exc
    if start_ticks <= 0:
        raise FaultEvidenceError("process stat start time is invalid")
    return start_ticks


def _positive_evidence_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 1:
        raise FaultEvidenceError(f"{name} must be an integer greater than one")
    return value


def _nul_environment_index(value: bytes, name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in value.split(b"\0"):
        if not item:
            continue
        try:
            key, item_value = item.decode("utf-8").split("=", 1)
        except (UnicodeDecodeError, ValueError) as exc:
            raise FaultEvidenceError(f"{name} is malformed") from exc
        if not key or key in result:
            raise FaultEvidenceError(f"{name} has duplicate or empty keys")
        result[key] = item_value
    return result


def _nul_string_sequence(value: bytes, name: str) -> tuple[str, ...]:
    try:
        items = tuple(item.decode("utf-8") for item in value.split(b"\0") if item)
    except UnicodeDecodeError as exc:
        raise FaultEvidenceError(f"{name} is malformed") from exc
    if not items or any("\0" in item for item in items):
        raise FaultEvidenceError(f"{name} is empty or malformed")
    return items


def _validate_canonical_launch_contract(
    contract: Mapping[str, Any],
    *,
    run_id: str,
    expected_control_root: Path,
    expected_db_path: Path,
    expected_artifacts_root: Path,
) -> None:
    _exact_keys(
        "launch contract",
        contract,
        {
            "schema",
            "run_id",
            "backend",
            "model",
            "runtime",
            "seed",
            "code_sha256",
            "rpc",
            "paths",
            "scripted",
            "provider",
            "cotenancy",
            "contract_sha256",
        },
    )
    if (
        contract.get("schema") != "fortgym.m1b-runtime-contract/v1"
        or contract.get("run_id") != run_id
        or contract.get("backend") != "dfhack"
        or contract.get("model") != "dfhack-governed-scripted"
        or contract.get("scripted") is not True
        or not _SHA256_RE.fullmatch(str(contract.get("code_sha256") or ""))
        or not _SHA256_RE.fullmatch(str(contract.get("contract_sha256") or ""))
    ):
        raise FaultEvidenceError("launch contract top-level identity differs")
    runtime = _mapping("launch runtime identity", contract.get("runtime"))
    _exact_keys(
        "launch runtime identity",
        runtime,
        {
            "classification",
            "source_reproducible",
            "image_manifest_sha256",
            "image_config_sha256",
            "image_archive_sha256",
        },
    )
    if (
        runtime.get("classification") != "private_stock_archive_seeded"
        or runtime.get("source_reproducible") is not False
        or any(
            not _SHA256_RE.fullmatch(str(runtime.get(name) or ""))
            for name in (
                "image_manifest_sha256",
                "image_config_sha256",
                "image_archive_sha256",
            )
        )
    ):
        raise FaultEvidenceError("launch runtime identity differs")
    seed = _mapping("launch seed identity", contract.get("seed"))
    _exact_keys(
        "launch seed identity",
        seed,
        {"tree_sha256", "world_sha256", "seed_save", "runtime_save"},
    )
    if (
        not _SHA256_RE.fullmatch(str(seed.get("tree_sha256") or ""))
        or not _SHA256_RE.fullmatch(str(seed.get("world_sha256") or ""))
        or not _RUN_ID_RE.fullmatch(str(seed.get("seed_save") or ""))
        or not _RUN_ID_RE.fullmatch(str(seed.get("runtime_save") or ""))
    ):
        raise FaultEvidenceError("launch seed identity differs")
    rpc = _mapping("launch RPC identity", contract.get("rpc"))
    _exact_keys("launch RPC identity", rpc, {"host", "port", "nonce"})
    port = rpc.get("port")
    if (
        rpc.get("host") != "127.0.0.1"
        or isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65_535
        or not _NONCE_RE.fullmatch(str(rpc.get("nonce") or ""))
    ):
        raise FaultEvidenceError("launch RPC identity differs")
    paths = _mapping("launch path identity", contract.get("paths"))
    _exact_keys(
        "launch path identity",
        paths,
        {"db", "artifacts_root", "control_root", "dfroot"},
    )
    expected_paths = {
        "db": expected_db_path,
        "artifacts_root": expected_artifacts_root,
        "control_root": expected_control_root,
    }
    for name, expected in expected_paths.items():
        raw = paths.get(name)
        if (
            not isinstance(raw, str)
            or raw != str(expected)
            or Path(raw).resolve(strict=False) != expected
        ):
            raise FaultEvidenceError(f"launch {name} path differs from trusted root")
    dfroot = paths.get("dfroot")
    if (
        not isinstance(dfroot, str)
        or not Path(dfroot).is_absolute()
        or Path(dfroot).resolve(strict=False) == Path(Path(dfroot).anchor)
        or "\0" in dfroot
    ):
        raise FaultEvidenceError("launch dfroot path is unsafe")
    provider = _mapping("launch provider identity", contract.get("provider"))
    expected_provider = {
        "enabled": False,
        "route": None,
        "model": None,
        "provider_name": None,
        "base_url": None,
        "max_total_tokens": None,
        "max_cost_usd": None,
        "credential_present": False,
        "strict_supervised": False,
    }
    if dict(provider) != expected_provider:
        raise FaultEvidenceError("fault driver requires provider-free launch identity")
    cotenancy = _mapping("launch cotenancy identity", contract.get("cotenancy"))
    _exact_keys(
        "launch cotenancy identity",
        cotenancy,
        {
            "schema",
            "cohort_sha256",
            "cohort_size",
            "slot",
            "peer_run_ids",
        },
    )
    peers = cotenancy.get("peer_run_ids")
    if (
        not isinstance(peers, list)
        or any(
            not isinstance(peer, str) or not _RUN_ID_RE.fullmatch(peer)
            for peer in peers
        )
        or run_id in peers
        or len(set(peers)) != len(peers)
    ):
        raise FaultEvidenceError("launch cotenancy peer identities differ")
    cohort_ids = tuple(sorted((run_id, *peers)))
    expected_cotenancy = {
        "schema": "fortgym.m1b-cotenancy/v1",
        "cohort_sha256": _payload_sha256(
            {"schema": "fortgym.m1b-cotenancy/v1", "run_ids": list(cohort_ids)}
        ),
        "cohort_size": len(cohort_ids),
        "slot": cohort_ids.index(run_id),
        "peer_run_ids": [item for item in cohort_ids if item != run_id],
    }
    if dict(cotenancy) != expected_cotenancy:
        raise FaultEvidenceError("launch cotenancy identity is noncanonical")
    identity_payload = dict(contract)
    contract_sha256 = identity_payload.pop("contract_sha256")
    if _payload_sha256(identity_payload) != contract_sha256:
        raise FaultEvidenceError("launch contract digest is invalid")


def _runtime_fault_profile_identity(role: str) -> dict[str, Any]:
    if role == "target":
        return {
            "schema": "fortgym.m1b-runtime-fault-profile/v1",
            "cohort_kind": "oom_256m_target_peer",
            "role": "target",
            "name": _OOM_FAULT_PROFILE,
            "memory_bytes": _OOM_MEMORY_BYTES,
            "memory_swap_bytes": _OOM_MEMORY_BYTES,
            "test_only": True,
        }
    if role == "peer":
        return {
            "schema": "fortgym.m1b-runtime-fault-profile/v1",
            "cohort_kind": "oom_256m_target_peer",
            "role": "peer",
            "name": "normal_4g",
            "memory_bytes": _NORMAL_MEMORY_BYTES,
            "memory_swap_bytes": _NORMAL_MEMORY_BYTES,
            "test_only": True,
        }
    raise AssertionError("invalid runtime fault profile role")


def _validate_runtime_fault_profile_launch(
    launch: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    expected_role: str | None,
    expected_counterpart_run_id: str | None,
    control_root: Path,
    db_path: Path,
    artifacts_root: Path,
    read_bytes: Callable[[Path], bytes],
    path_exists: Callable[[Path], bool],
) -> None:
    if expected_role is None:
        if "runtime_fault_profile" in launch:
            raise FaultEvidenceError(
                "ordinary post-readiness loader rejects runtime fault profiles"
            )
        return
    if expected_role not in {"target", "peer"}:
        raise AssertionError("invalid expected runtime fault profile role")
    profile = _mapping("runtime fault profile", launch.get("runtime_fault_profile"))
    if dict(profile) != _runtime_fault_profile_identity(expected_role):
        raise FaultEvidenceError("runtime fault profile identity differs")
    cotenancy = _mapping("runtime fault cotenancy", contract.get("cotenancy"))
    peer_ids = cotenancy.get("peer_run_ids")
    if (
        cotenancy.get("cohort_size") != 2
        or not isinstance(peer_ids, list)
        or len(peer_ids) != 1
        or not isinstance(peer_ids[0], str)
    ):
        raise FaultEvidenceError(
            "OOM runtime fault profile requires one exact target and peer"
        )
    counterpart_id = peer_ids[0]
    if (
        expected_counterpart_run_id is not None
        and counterpart_id != expected_counterpart_run_id
    ):
        raise FaultEvidenceError("OOM runtime fault counterpart differs")
    counterpart_path = control_root / counterpart_id / "launch.json"
    if not path_exists(counterpart_path):
        raise OwnedRunEvidencePending("symmetric OOM counterpart launch is absent")
    try:
        raw = read_bytes(counterpart_path)
    except FileNotFoundError as exc:
        raise OwnedRunEvidencePending(
            "symmetric OOM counterpart launch is absent"
        ) from exc
    if not isinstance(raw, bytes) or len(raw) > 256 * 1024:
        raise FaultEvidenceError("symmetric OOM counterpart launch is oversized")
    try:
        counterpart_launch = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultEvidenceError(
            "symmetric OOM counterpart launch is invalid JSON"
        ) from exc
    counterpart = _mapping("symmetric OOM counterpart launch", counterpart_launch)
    _exact_keys(
        "symmetric OOM counterpart launch",
        counterpart,
        {
            "schema",
            "run_id",
            "created_at",
            "contract",
            "request",
            "runtime_fault_profile",
        },
    )
    if (
        counterpart.get("schema") != "fortgym.m1b-service-launch/v1"
        or counterpart.get("run_id") != counterpart_id
        or not isinstance(counterpart.get("created_at"), str)
        or dict(
            _mapping(
                "symmetric OOM counterpart profile",
                counterpart.get("runtime_fault_profile"),
            )
        )
        != _runtime_fault_profile_identity(
            "peer" if expected_role == "target" else "target"
        )
    ):
        raise FaultEvidenceError("symmetric OOM counterpart profile differs")
    counterpart_contract = _mapping(
        "symmetric OOM counterpart contract", counterpart.get("contract")
    )
    _validate_canonical_launch_contract(
        counterpart_contract,
        run_id=counterpart_id,
        expected_control_root=control_root,
        expected_db_path=db_path,
        expected_artifacts_root=artifacts_root,
    )
    counterpart_cotenancy = _mapping(
        "symmetric OOM counterpart cotenancy",
        counterpart_contract.get("cotenancy"),
    )
    if (
        counterpart_cotenancy.get("cohort_sha256") != cotenancy.get("cohort_sha256")
        or counterpart_cotenancy.get("cohort_size") != 2
        or counterpart_cotenancy.get("peer_run_ids") != [contract.get("run_id")]
        or counterpart.get("request") != launch.get("request")
    ):
        raise FaultEvidenceError("symmetric OOM counterpart cotenancy differs")


def _workspace_fault_profile_identity(role: str) -> dict[str, Any]:
    if role == "target":
        return {
            "schema": WORKSPACE_FAULT_PROFILE_SCHEMA,
            "cohort_kind": "enospc_16m_target_peer",
            "role": "target",
            "name": _ENOSPC_WORKSPACE_PROFILE,
            "filesystem": "tmpfs",
            "size_bytes": MAX_WORKSPACE_FAULT_BYTES,
            "test_only": True,
        }
    if role == "peer":
        return {
            "schema": WORKSPACE_FAULT_PROFILE_SCHEMA,
            "cohort_kind": "enospc_16m_target_peer",
            "role": "peer",
            "name": _NORMAL_WORKSPACE_PROFILE,
            "filesystem": "host",
            "size_bytes": None,
            "test_only": True,
        }
    raise AssertionError("invalid workspace fault profile role")


def _validate_workspace_fault_profile_launch(
    launch: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    expected_role: str | None,
    expected_counterpart_run_id: str | None,
    control_root: Path,
    db_path: Path,
    artifacts_root: Path,
    read_bytes: Callable[[Path], bytes],
    path_exists: Callable[[Path], bool],
) -> None:
    if expected_role is None:
        if "workspace_fault_profile" in launch:
            raise FaultEvidenceError(
                "ordinary post-readiness loader rejects workspace fault profiles"
            )
        return
    if expected_role not in {"target", "peer"}:
        raise AssertionError("invalid expected workspace fault profile role")
    profile = _mapping("workspace fault profile", launch.get("workspace_fault_profile"))
    if dict(profile) != _workspace_fault_profile_identity(expected_role):
        raise FaultEvidenceError("workspace fault profile identity differs")
    cotenancy = _mapping("workspace fault cotenancy", contract.get("cotenancy"))
    peer_ids = cotenancy.get("peer_run_ids")
    if (
        cotenancy.get("cohort_size") != 2
        or not isinstance(peer_ids, list)
        or len(peer_ids) != 1
        or not isinstance(peer_ids[0], str)
    ):
        raise FaultEvidenceError(
            "ENOSPC workspace profile requires one exact target and peer"
        )
    counterpart_id = peer_ids[0]
    if (
        expected_counterpart_run_id is not None
        and counterpart_id != expected_counterpart_run_id
    ):
        raise FaultEvidenceError("ENOSPC workspace counterpart differs")
    counterpart_path = control_root / counterpart_id / "launch.json"
    if not path_exists(counterpart_path):
        raise OwnedRunEvidencePending("symmetric ENOSPC counterpart launch is absent")
    try:
        raw = read_bytes(counterpart_path)
    except FileNotFoundError as exc:
        raise OwnedRunEvidencePending(
            "symmetric ENOSPC counterpart launch is absent"
        ) from exc
    if not isinstance(raw, bytes) or len(raw) > 256 * 1024:
        raise FaultEvidenceError("symmetric ENOSPC counterpart launch is oversized")
    try:
        counterpart_launch = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultEvidenceError(
            "symmetric ENOSPC counterpart launch is invalid JSON"
        ) from exc
    counterpart = _mapping("symmetric ENOSPC counterpart launch", counterpart_launch)
    _exact_keys(
        "symmetric ENOSPC counterpart launch",
        counterpart,
        {
            "schema",
            "run_id",
            "created_at",
            "contract",
            "request",
            "workspace_fault_profile",
        },
    )
    if (
        counterpart.get("schema") != "fortgym.m1b-service-launch/v1"
        or counterpart.get("run_id") != counterpart_id
        or not isinstance(counterpart.get("created_at"), str)
        or dict(
            _mapping(
                "symmetric ENOSPC counterpart profile",
                counterpart.get("workspace_fault_profile"),
            )
        )
        != _workspace_fault_profile_identity(
            "peer" if expected_role == "target" else "target"
        )
    ):
        raise FaultEvidenceError("symmetric ENOSPC counterpart profile differs")
    counterpart_contract = _mapping(
        "symmetric ENOSPC counterpart contract", counterpart.get("contract")
    )
    _validate_canonical_launch_contract(
        counterpart_contract,
        run_id=counterpart_id,
        expected_control_root=control_root,
        expected_db_path=db_path,
        expected_artifacts_root=artifacts_root,
    )
    counterpart_cotenancy = _mapping(
        "symmetric ENOSPC counterpart cotenancy",
        counterpart_contract.get("cotenancy"),
    )
    if (
        counterpart_cotenancy.get("cohort_sha256") != cotenancy.get("cohort_sha256")
        or counterpart_cotenancy.get("cohort_size") != 2
        or counterpart_cotenancy.get("peer_run_ids") != [contract.get("run_id")]
        or counterpart.get("request") != launch.get("request")
    ):
        raise FaultEvidenceError("symmetric ENOSPC counterpart cotenancy differs")


def _validate_container_created_receipt(
    receipt: Mapping[str, Any],
    *,
    run_id: str,
    contract_sha256: str,
    nonce: str,
    cohort_sha256: str,
    expected_fault_profile: str | None,
    expected_memory_bytes: int,
) -> tuple[str, str]:
    _exact_keys(
        "runtime container-created receipt",
        receipt,
        {
            "schema",
            "ok",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "container_name",
            "container_id",
            "image_reference",
            "fault_profile",
            "memory_bytes",
            "memory_swap_bytes",
        },
    )
    container_id = receipt.get("container_id")
    container_name = receipt.get("container_name")
    expected_name = f"fortgym-m1b-{run_id}-{contract_sha256[:12]}"
    if (
        receipt.get("schema") != "fortgym.m1b-container-created/v1"
        or receipt.get("ok") is not True
        or receipt.get("run_id") != run_id
        or receipt.get("contract_sha256") != contract_sha256
        or receipt.get("nonce_sha256") != _nonce_sha256(nonce)
        or receipt.get("cohort_sha256") != cohort_sha256
        or not isinstance(container_id, str)
        or not _CONTAINER_ID_RE.fullmatch(container_id)
        or container_name != expected_name
        or not isinstance(receipt.get("image_reference"), str)
        or not receipt.get("image_reference")
        or receipt.get("fault_profile") != expected_fault_profile
        or receipt.get("memory_bytes") != expected_memory_bytes
        or receipt.get("memory_swap_bytes") != expected_memory_bytes
    ):
        raise FaultEvidenceError("runtime container-created identity differs")
    return container_id, container_name


def _validate_container_inspection_identity(
    inspection: Mapping[str, Any],
    *,
    run_id: str,
    contract_sha256: str,
    nonce: str,
    cohort_sha256: str,
    container_name: str,
    container_id: str,
    expected_fault_profile: str | None,
    expected_memory_bytes: int,
    expected_running: bool,
    expected_oom_killed: bool,
    expected_exit_code: int | None,
) -> int:
    config = _mapping("Docker container Config", inspection.get("Config"))
    host_config = _mapping("Docker container HostConfig", inspection.get("HostConfig"))
    state = _mapping("Docker container State", inspection.get("State"))
    labels = _mapping("Docker container labels", config.get("Labels"))
    environment = _environment_index(config.get("Env"))
    observed_name = str(inspection.get("Name") or "").removeprefix("/")
    if (
        str(inspection.get("Id") or "").lower() != container_id
        or observed_name != container_name
        or labels.get("fortgym.m1b.managed") != "true"
        or labels.get("fortgym.m1b.run_id") != run_id
        or labels.get("fortgym.m1b.contract_sha256") != contract_sha256
        or labels.get("fortgym.m1b.cohort_sha256") != cohort_sha256
        or environment.get("FORTGYM_RUN_ID") != run_id
        or environment.get("FORTGYM_CONTRACT_SHA256") != contract_sha256
        or environment.get("FORTGYM_RUN_NONCE") != nonce
        or host_config.get("Memory") != expected_memory_bytes
        or host_config.get("MemorySwap") != expected_memory_bytes
        or state.get("Running") is not expected_running
        or bool(state.get("OOMKilled", False)) is not expected_oom_killed
    ):
        raise FaultEvidenceError("Docker container binding or state differs")
    observed_profile = labels.get("fortgym.m1b.fault_profile")
    if expected_fault_profile is None:
        if "fortgym.m1b.fault_profile" in labels:
            raise FaultEvidenceError("normal container carries a fault profile")
    elif observed_profile != expected_fault_profile:
        raise FaultEvidenceError("Docker container fault profile differs")
    if expected_exit_code is not None and state.get("ExitCode") != expected_exit_code:
        raise FaultEvidenceError("Docker container exit code differs")
    init_pid = state.get("Pid")
    if expected_running:
        return _positive_evidence_int(init_pid, "container init host PID")
    if isinstance(init_pid, bool) or not isinstance(init_pid, int) or init_pid < 0:
        raise FaultEvidenceError("stopped container init PID is invalid")
    return init_pid


def _validate_live_container_binding(
    inspection: Mapping[str, Any],
    *,
    run_id: str,
    contract: Mapping[str, Any],
    container_name: str,
    container_id: str,
    expected_fault_profile: str | None,
    expected_memory_bytes: int,
) -> int:
    init_pid = _validate_container_inspection_identity(
        inspection,
        run_id=run_id,
        contract_sha256=str(contract["contract_sha256"]),
        nonce=str(contract["rpc"]["nonce"]),
        cohort_sha256=str(contract["cotenancy"]["cohort_sha256"]),
        container_name=container_name,
        container_id=container_id,
        expected_fault_profile=expected_fault_profile,
        expected_memory_bytes=expected_memory_bytes,
        expected_running=True,
        expected_oom_killed=False,
        expected_exit_code=None,
    )
    config = _mapping("Docker container Config", inspection.get("Config"))
    configured_image = str(config.get("Image") or "")
    runtime_image = str(inspection.get("Image") or "")
    expected_images = {
        f"sha256:{contract['runtime']['image_manifest_sha256']}",
        f"sha256:{contract['runtime']['image_config_sha256']}",
    }
    if configured_image not in expected_images or runtime_image not in expected_images:
        raise FaultEvidenceError("Docker image identity differs from launch contract")
    return init_pid


def _validate_live_oom_container_binding(
    inspection: Mapping[str, Any],
    *,
    target: PreReadinessOomTarget,
    container_id: str,
) -> int:
    return _validate_container_inspection_identity(
        inspection,
        run_id=target.run_id,
        contract_sha256=target.contract_sha256,
        nonce=target.nonce,
        cohort_sha256=target.cohort_sha256,
        container_name=target.container_name,
        container_id=container_id,
        expected_fault_profile=_OOM_FAULT_PROFILE,
        expected_memory_bytes=_OOM_MEMORY_BYTES,
        expected_running=True,
        expected_oom_killed=False,
        expected_exit_code=None,
    )


def _validate_stopped_oom_container_binding(
    inspection: Mapping[str, Any],
    *,
    target: PreReadinessOomTarget,
    container_id: str,
) -> None:
    _validate_container_inspection_identity(
        inspection,
        run_id=target.run_id,
        contract_sha256=target.contract_sha256,
        nonce=target.nonce,
        cohort_sha256=target.cohort_sha256,
        container_name=target.container_name,
        container_id=container_id,
        expected_fault_profile=_OOM_FAULT_PROFILE,
        expected_memory_bytes=_OOM_MEMORY_BYTES,
        expected_running=False,
        expected_oom_killed=True,
        expected_exit_code=137,
    )


def _container_init_cgroup_identity(
    *,
    container_id: str,
    container_init_host_pid: int,
    read_text: Callable[[Path], str],
    path_exists: Callable[[Path], bool],
) -> str:
    init_root = Path(f"/proc/{container_init_host_pid}")
    if not path_exists(init_root):
        raise OwnedRunEvidencePending("container init process is not live")
    try:
        init_paths = _proc_cgroup_paths(read_text(init_root / "cgroup"))
    except (FileNotFoundError, OSError) as exc:
        raise OwnedRunEvidencePending("container init cgroup is not readable") from exc
    init_container_paths = {path for path in init_paths if container_id in path}
    if len(init_container_paths) != 1:
        raise FaultEvidenceError("container init cgroup identity is ambiguous")
    return next(iter(init_container_paths))


def _discover_unique_dwarf_process(
    *,
    container_id: str,
    container_init_host_pid: int,
    process_ids: Sequence[int],
    read_text: Callable[[Path], str],
    path_exists: Callable[[Path], bool],
) -> tuple[int, int, str]:
    expected_cgroup = _container_init_cgroup_identity(
        container_id=container_id,
        container_init_host_pid=container_init_host_pid,
        read_text=read_text,
        path_exists=path_exists,
    )
    candidates: list[tuple[int, int, str]] = []
    for pid in sorted(set(process_ids)):
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
            raise FaultEvidenceError("process scan returned an invalid PID")
        proc_root = Path(f"/proc/{pid}")
        if not path_exists(proc_root):
            continue
        try:
            if read_text(proc_root / "comm").strip() != "Dwarf_Fortress":
                continue
            namespace_pids = _proc_status_nspid(read_text(proc_root / "status"))
            cgroup_paths = _proc_cgroup_paths(read_text(proc_root / "cgroup"))
        except (FileNotFoundError, OSError):
            continue
        matching_paths = {path for path in cgroup_paths if container_id in path}
        if len(matching_paths) == 1 and expected_cgroup in matching_paths:
            if (
                len(namespace_pids) < 2
                or namespace_pids[0] != pid
                or namespace_pids[-1] <= 1
                or namespace_pids[-1] == pid
            ):
                raise FaultEvidenceError(
                    "Dwarf_Fortress process lacks an exact host/container PID mapping"
                )
            candidates.append((pid, namespace_pids[-1], expected_cgroup))
    if not candidates:
        raise OwnedRunEvidencePending(
            "unique Dwarf_Fortress host/container PID is not live yet"
        )
    if len(candidates) != 1:
        raise FaultEvidenceError(
            "multiple Dwarf_Fortress processes claim the exact container cgroup"
        )
    return candidates[0]


def _cohort_start_from_container_created(
    receipt: Mapping[str, Any],
    target: PreReadinessOomTarget,
    *,
    role: str,
) -> dict[str, Any]:
    if role != "target":
        raise AssertionError("pre-readiness OOM receipt can only describe target")
    return {
        "schema": COHORT_START_SCHEMA,
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce": target.nonce,
        "cohort_sha256": target.cohort_sha256,
        "container_id": receipt["container_id"],
        "role": role,
        "memory_bytes": receipt["memory_bytes"],
        "memory_swap_bytes": receipt["memory_swap_bytes"],
        "fault_profile": receipt["fault_profile"],
        "provider_free": True,
        "state": "container_created",
        "durable": True,
        "journal_record_sha256": _payload_sha256(receipt),
    }


def _pre_readiness_oom_state(
    target: PreReadinessOomTarget,
    armed: _ArmedOomIdentity,
    *,
    phase: str,
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    if phase not in {"before", "after"}:
        raise AssertionError("invalid pre-readiness OOM phase")
    return {
        "schema": PRE_READINESS_OOM_STATE_SCHEMA,
        "gate": FaultGate.OOM.value,
        "phase": phase,
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce_sha256": _nonce_sha256(target.nonce),
        "container_id": armed.container_id,
        "container_init_host_pid": armed.container_init_host_pid,
        "container_cgroup_path": armed.container_cgroup_path,
        "facts": dict(facts),
    }


def _validate_pre_readiness_oom_receipt(
    receipt: Mapping[str, Any],
    *,
    target: PreReadinessOomTarget,
    container_id: str,
) -> None:
    _exact_keys(
        "pre-readiness OOM receipt",
        receipt,
        {
            "schema",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "container_name",
            "container_id",
            "fault_profile",
            "memory_bytes",
            "memory_swap_bytes",
            "state",
        },
    )
    state = _mapping("pre-readiness OOM state", receipt.get("state"))
    _exact_keys(
        "pre-readiness OOM state", state, {"running", "oom_killed", "exit_code"}
    )
    if (
        receipt.get("schema") != "fortgym.m1b-pre-readiness-oom-observation/v1"
        or receipt.get("run_id") != target.run_id
        or receipt.get("contract_sha256") != target.contract_sha256
        or receipt.get("nonce_sha256") != _nonce_sha256(target.nonce)
        or receipt.get("container_name") != target.container_name
        or receipt.get("container_id") != container_id
        or receipt.get("fault_profile") != _OOM_FAULT_PROFILE
        or receipt.get("memory_bytes") != _OOM_MEMORY_BYTES
        or receipt.get("memory_swap_bytes") != _OOM_MEMORY_BYTES
        or dict(state) != {"running": False, "oom_killed": True, "exit_code": 137}
    ):
        raise FaultEvidenceError("pre-readiness OOM receipt differs")


def _validate_pre_readiness_oom_hold_ready(
    receipt: Mapping[str, Any], *, target: PreReadinessOomTarget
) -> None:
    _exact_keys(
        "pre-readiness OOM hold-ready receipt",
        receipt,
        {
            "schema",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "fault_profile",
            "memory_bytes",
            "memory_swap_bytes",
        },
    )
    if dict(receipt) != {
        "schema": "fortgym.m1b-pre-readiness-oom-hold-ready/v1",
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce_sha256": _nonce_sha256(target.nonce),
        "cohort_sha256": target.cohort_sha256,
        "fault_profile": _OOM_FAULT_PROFILE,
        "memory_bytes": _OOM_MEMORY_BYTES,
        "memory_swap_bytes": _OOM_MEMORY_BYTES,
    }:
        raise FaultEvidenceError("pre-readiness OOM hold-ready receipt differs")


def _validate_pre_readiness_oom_facts(
    *,
    target_run_id: str,
    cohort_sha256: str,
    container_id: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    peer_before_release: Mapping[str, Any],
    peer_after: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fact_keys = {
        "runtime_identity",
        "runtime_exit_code",
        "cgroup_memory_events",
        "host_oom_counter",
        "unattributed_host_oom_delta",
    }
    _exact_keys("pre-readiness OOM before", before, expected_fact_keys)
    _exact_keys("pre-readiness OOM after", after, expected_fact_keys)
    before_events = _memory_events(
        before.get("cgroup_memory_events"), "pre-readiness OOM before"
    )
    after_events = _memory_events(
        after.get("cgroup_memory_events"), "pre-readiness OOM after"
    )
    target_local_oom_kill_delta = _counter_delta(
        before_events["oom_kill"],
        after_events["oom_kill"],
        "target memory.events.local oom_kill",
    )
    global_oom_kill_delta = _counter_delta(
        before.get("host_oom_counter"),
        after.get("host_oom_counter"),
        "global /proc/vmstat oom_kill",
    )
    unattributed_host_oom_delta = global_oom_kill_delta - target_local_oom_kill_delta
    if (
        before.get("runtime_identity") != container_id
        or before.get("runtime_exit_code") is not None
        or before.get("unattributed_host_oom_delta") is not None
        or after.get("runtime_identity") != container_id
        or after.get("runtime_exit_code") != 137
        or target_local_oom_kill_delta < 1
        or after_events["oom"] < before_events["oom"]
        or after.get("unattributed_host_oom_delta") != unattributed_host_oom_delta
        or unattributed_host_oom_delta != 0
    ):
        raise FaultEvidenceError(
            "pre-readiness OOM lacks target-local proof or has an unattributed host OOM"
        )
    ready = _validate_oom_peer_before_release(
        peer_before_release,
        target_run_id=target_run_id,
        cohort_sha256=cohort_sha256,
    )
    _exact_keys(
        "pre-readiness OOM peer-after",
        peer_after,
        {
            "step",
            "healthy",
            "runtime_ready",
            "reconnected",
            "continued_after_fault",
            "target_run_id",
            "cohort_sha256",
            "connection_generation",
        },
    )
    if (
        peer_after.get("target_run_id") != target_run_id
        or peer_after.get("cohort_sha256") != ready["cohort_sha256"]
        or _nonnegative_int(peer_after.get("step"), "OOM peer-after step")
        < max(3, int(ready["step"]) + 1)
        or peer_after.get("healthy") is not True
        or peer_after.get("runtime_ready") is not True
        or peer_after.get("reconnected") is not False
        or peer_after.get("continued_after_fault") is not True
        or peer_after.get("connection_generation") != ready["connection_generation"]
    ):
        raise FaultEvidenceError("normal-cap peer did not prove healthy continuation")
    return {
        "runtime_identity": {"expected": container_id, "observed": container_id},
        "runtime_exit_code": 137,
        "cgroup_memory_events": {"before": before_events, "after": after_events},
    }


def _validate_completed_pre_readiness_oom(
    payload: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_contract_sha256: str,
    expected_nonce_sha256: str,
) -> None:
    target = _mapping("completed pre-readiness OOM target", payload.get("target"))
    _exact_keys(
        "completed pre-readiness OOM target",
        target,
        {
            "identity_kind",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "container_name",
            "container_id",
            "container_init_host_pid",
            "container_cgroup_path",
            "db_path",
            "workspace",
        },
    )
    container_id = str(target.get("container_id") or "")
    init_pid = target.get("container_init_host_pid")
    cgroup_path = str(target.get("container_cgroup_path") or "")
    if (
        target.get("identity_kind") != "pre_readiness_oom"
        or target.get("run_id") != expected_run_id
        or target.get("contract_sha256") != expected_contract_sha256
        or target.get("nonce_sha256") != expected_nonce_sha256
        or not _SHA256_RE.fullmatch(str(target.get("cohort_sha256") or ""))
        or not _CONTAINER_ID_RE.fullmatch(container_id)
        or isinstance(init_pid, bool)
        or not isinstance(init_pid, int)
        or init_pid <= 1
        or not cgroup_path.startswith("/")
        or container_id not in cgroup_path
    ):
        raise FaultEvidenceError("completed pre-readiness OOM target differs")
    ownership = _mapping(
        "completed pre-readiness OOM ownership", payload.get("ownership")
    )
    target_ownership = _mapping(
        "completed pre-readiness OOM target ownership", ownership.get("target")
    )
    _exact_keys(
        "completed pre-readiness OOM target ownership",
        target_ownership,
        {
            "schema",
            *set(target),
            "fault_profile",
            "memory_bytes",
            "memory_swap_bytes",
            "hold_ready_sha256",
        },
    )
    if (
        target_ownership.get("schema") != "fortgym.m1b-pre-readiness-oom-ownership/v1"
        or any(target_ownership.get(key) != value for key, value in target.items())
        or target_ownership.get("fault_profile") != _OOM_FAULT_PROFILE
        or target_ownership.get("memory_bytes") != _OOM_MEMORY_BYTES
        or target_ownership.get("memory_swap_bytes") != _OOM_MEMORY_BYTES
        or not _SHA256_RE.fullmatch(
            str(target_ownership.get("hold_ready_sha256") or "")
        )
    ):
        raise FaultEvidenceError(
            "completed pre-readiness OOM ownership binding differs"
        )
    barrier = _mapping("completed pre-readiness OOM barrier", payload.get("barrier"))
    target_barrier = _mapping(
        "completed pre-readiness OOM target barrier", barrier.get("target")
    )
    peer_barrier = _mapping(
        "completed pre-readiness OOM peer barrier", barrier.get("peer")
    )
    barrier_keys = {
        "schema",
        "run_id",
        "contract_sha256",
        "nonce_sha256",
        "cohort_sha256",
        "container_id",
        "role",
        "memory_bytes",
        "memory_swap_bytes",
        "fault_profile",
        "provider_free",
        "state",
        "durable",
        "journal_record_sha256",
    }
    _exact_keys("completed OOM target barrier", target_barrier, barrier_keys)
    _exact_keys("completed OOM peer barrier", peer_barrier, barrier_keys)
    if (
        target_barrier.get("schema") != COHORT_START_SCHEMA
        or target_barrier.get("role") != "target"
        or target_barrier.get("container_id") != container_id
        or target_barrier.get("cohort_sha256") != target.get("cohort_sha256")
        or target_barrier.get("memory_bytes") != _OOM_MEMORY_BYTES
        or target_barrier.get("memory_swap_bytes") != _OOM_MEMORY_BYTES
        or target_barrier.get("fault_profile") != _OOM_FAULT_PROFILE
        or target_barrier.get("provider_free") is not True
        or target_barrier.get("state") != "container_created"
        or peer_barrier.get("schema") != COHORT_START_SCHEMA
        or peer_barrier.get("role") != "peer"
        or peer_barrier.get("cohort_sha256") != target.get("cohort_sha256")
        or peer_barrier.get("memory_bytes") != _NORMAL_MEMORY_BYTES
        or peer_barrier.get("memory_swap_bytes") != _NORMAL_MEMORY_BYTES
        or peer_barrier.get("fault_profile") is not None
        or peer_barrier.get("provider_free") is not True
        or peer_barrier.get("state") != "container_created"
    ):
        raise FaultEvidenceError("completed pre-readiness OOM barriers differ")
    expected_state_keys = {
        "schema",
        "gate",
        "phase",
        "run_id",
        "contract_sha256",
        "nonce_sha256",
        "container_id",
        "container_init_host_pid",
        "container_cgroup_path",
        "facts",
    }
    before = _mapping("completed pre-readiness OOM before", payload.get("before"))
    after = _mapping("completed pre-readiness OOM after", payload.get("after"))
    _exact_keys("completed pre-readiness OOM before", before, expected_state_keys)
    _exact_keys("completed pre-readiness OOM after", after, expected_state_keys)
    for phase, state in (("before", before), ("after", after)):
        if (
            state.get("schema") != PRE_READINESS_OOM_STATE_SCHEMA
            or state.get("gate") != FaultGate.OOM.value
            or state.get("phase") != phase
            or state.get("run_id") != expected_run_id
            or state.get("contract_sha256") != expected_contract_sha256
            or state.get("nonce_sha256") != expected_nonce_sha256
            or state.get("container_id") != container_id
            or state.get("container_init_host_pid") != init_pid
            or state.get("container_cgroup_path") != cgroup_path
        ):
            raise FaultEvidenceError(
                f"completed pre-readiness OOM {phase} binding differs"
            )
    peer_after = _mapping(
        "completed pre-readiness OOM peer-after", payload.get("peer_after")
    )
    peer_before_release = _mapping(
        "completed pre-readiness OOM peer-before-release",
        payload.get("peer_before_release"),
    )
    peer = _mapping("completed pre-readiness OOM peer", payload.get("peer"))
    peer_state_keys = {
        "schema",
        "gate",
        "phase",
        "run_id",
        "contract_sha256",
        "nonce_sha256",
        "container_id",
        "runtime_host_pid",
        "runtime_container_pid",
        "harness_pid",
        "workspace",
        "facts",
    }
    for phase, state in (
        ("peer_before_release", peer_before_release),
        ("peer_after", peer_after),
    ):
        _exact_keys(f"completed pre-readiness OOM {phase}", state, peer_state_keys)
        if (
            state.get("schema") != FAULT_STATE_SCHEMA
            or state.get("gate") != FaultGate.OOM.value
            or state.get("phase") != phase
            or any(
                state.get(key) != peer.get(key)
                for key in (
                    "run_id",
                    "contract_sha256",
                    "nonce_sha256",
                    "container_id",
                    "runtime_host_pid",
                    "runtime_container_pid",
                    "harness_pid",
                    "workspace",
                )
            )
        ):
            raise FaultEvidenceError(
                f"completed pre-readiness OOM {phase} binding differs"
            )
    classifier = _validate_pre_readiness_oom_facts(
        target_run_id=expected_run_id,
        cohort_sha256=str(target.get("cohort_sha256") or ""),
        container_id=container_id,
        before=_mapping("completed OOM before facts", before.get("facts")),
        after=_mapping("completed OOM after facts", after.get("facts")),
        peer_before_release=_mapping(
            "completed OOM peer-before-release facts",
            peer_before_release.get("facts"),
        ),
        peer_after=_mapping("completed OOM peer-after facts", peer_after.get("facts")),
    )
    if (
        dict(_mapping("completed OOM classifier", payload.get("classifier_evidence")))
        != classifier
    ):
        raise FaultEvidenceError(
            "completed pre-readiness OOM classifier subset differs"
        )
    if payload.get("pending_external_checks") != [
        "target_cleanup_verified",
        "cleanup_double_audit",
    ]:
        raise FaultEvidenceError("completed pre-readiness OOM cleanup checks differ")


def _environment_index(value: Any) -> dict[str, str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or "=" not in item for item in value
    ):
        raise FaultEvidenceError("Docker environment is not inspectable")
    return {item.split("=", 1)[0]: item.split("=", 1)[1] for item in value}


def _proc_status_nspid(status: str) -> tuple[int, ...]:
    for line in status.splitlines():
        if not line.startswith("NSpid:"):
            continue
        fields = line.split()[1:]
        if not fields or any(not field.isdigit() for field in fields):
            raise FaultEvidenceError("/proc status NSpid is malformed")
        return tuple(int(field) for field in fields)
    raise FaultEvidenceError("/proc status lacks NSpid")


def _proc_cgroup_paths(value: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in value.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3 or not fields[2].startswith("/"):
            raise FaultEvidenceError("/proc cgroup record is malformed")
        paths.append(fields[2])
    if not paths:
        raise FaultEvidenceError("/proc cgroup is empty")
    return tuple(paths)


def _key_value_int_file(value: str, name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in value.splitlines():
        fields = line.split()
        if len(fields) != 2 or not fields[1].isdigit():
            raise FaultEvidenceError(f"{name} is malformed")
        result[fields[0]] = int(fields[1])
    if not result:
        raise FaultEvidenceError(f"{name} is empty")
    return result


def _linux_process_ids() -> tuple[int, ...]:
    values: list[int] = []
    for path in Path("/proc").iterdir():
        if path.name.isdigit() and int(path.name) > 1:
            values.append(int(path.name))
    return tuple(values)


def _linux_process_group_members(process_group_id: int) -> tuple[int, ...]:
    members: list[int] = []
    for pid in _linux_process_ids():
        try:
            if os.getpgid(pid) == process_group_id:
                members.append(pid)
        except OSError:
            continue
    return tuple(members)


def _read_bounded_json_path(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FaultEvidenceError(f"{label} is absent") from exc
    if len(raw) > 64 * 1024:
        raise FaultEvidenceError(f"{label} is oversized")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultEvidenceError(f"{label} is invalid JSON") from exc
    return _mapping(label, value)


def _validate_prelaunch_enospc_receipt(
    value: Mapping[str, Any], target: PrelaunchEnospcTarget
) -> None:
    source = f"fortgym-m1b-enospc-{target.run_id}"
    mount_argv = [
        "/bin/mount",
        "-t",
        "tmpfs",
        "-o",
        f"size={MAX_WORKSPACE_FAULT_BYTES},nosuid,nodev,noexec,mode=0700",
        source,
        str(target.workspace),
    ]
    expected_keys = {
        "schema",
        "ok",
        "run_id",
        "contract_sha256",
        "nonce_sha256",
        "cohort_sha256",
        "peer_run_id",
        "workspace",
        "filesystem",
        "size_bytes",
        "source",
        "marker_sha256",
        "mount_argv",
        "shell",
        "prepared_before_manager",
    }
    _exact_keys("prelaunch ENOSPC workspace receipt", value, expected_keys)
    if (
        value.get("schema") != PRELAUNCH_ENOSPC_RECEIPT_SCHEMA
        or value.get("ok") is not True
        or value.get("run_id") != target.run_id
        or value.get("contract_sha256") != target.contract_sha256
        or value.get("nonce_sha256") != _nonce_sha256(target.nonce)
        or value.get("cohort_sha256") != target.cohort_sha256
        or value.get("peer_run_id") != target.peer_run_id
        or value.get("workspace") != str(target.workspace)
        or value.get("filesystem") != "tmpfs"
        or value.get("size_bytes") != MAX_WORKSPACE_FAULT_BYTES
        or value.get("source") != source
        or not _SHA256_RE.fullmatch(str(value.get("marker_sha256") or ""))
        or value.get("mount_argv") != mount_argv
        or value.get("shell") is not False
        or value.get("prepared_before_manager") is not True
    ):
        raise FaultEvidenceError("prelaunch ENOSPC workspace receipt differs")


def _find_mount_with_runner(
    runner: FaultCommandRunner, path: Path
) -> Mapping[str, Any] | None:
    argv = (
        "/usr/bin/findmnt",
        "--json",
        "--bytes",
        "--target",
        str(path),
        "--output",
        "TARGET,FSTYPE,SIZE,OPTIONS,SOURCE",
    )
    result = runner.run(argv, timeout_seconds=10.0)
    if not isinstance(result, FaultCommandResult) or result.argv != argv:
        raise FaultEvidenceError("findmnt command evidence differs")
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(_bounded_capture(result.stdout))
    except json.JSONDecodeError as exc:
        raise FaultEvidenceError("findmnt returned invalid JSON") from exc
    filesystems = payload.get("filesystems") if isinstance(payload, Mapping) else None
    if not isinstance(filesystems, list) or len(filesystems) != 1:
        raise FaultEvidenceError("findmnt did not return one exact mount")
    row = _mapping("findmnt row", filesystems[0])
    try:
        size_bytes = int(row.get("size", 0))
    except (TypeError, ValueError) as exc:
        raise FaultEvidenceError("findmnt size is invalid") from exc
    return {
        "target": row.get("target"),
        "filesystem": row.get("fstype"),
        "size_bytes": size_bytes,
        "options": row.get("options"),
        "source": row.get("source"),
    }


def _find_exact_mount_with_runner(
    runner: FaultCommandRunner, path: Path
) -> Mapping[str, Any] | None:
    observed = _find_mount_with_runner(runner, path)
    if observed is None:
        return None
    target = observed.get("target")
    if not isinstance(target, str) or not Path(target).is_absolute():
        raise FaultEvidenceError("findmnt exact target is invalid")
    # --target reports the containing filesystem, not necessarily a mount at
    # the requested workspace. Keep general filesystem observations separate.
    return observed if Path(target) == path else None


def _validate_private_tmpfs_mount(
    observed: Mapping[str, Any] | None,
    run: OwnedRun | PrelaunchEnospcTarget,
    *,
    source: str,
) -> None:
    if observed is None:
        raise FaultEvidenceError("private tmpfs mount is absent")
    options = str(observed.get("options") or "").split(",")
    if (
        Path(str(observed.get("target"))).resolve(strict=False) != run.workspace
        or observed.get("filesystem") != "tmpfs"
        or observed.get("size_bytes") != MAX_WORKSPACE_FAULT_BYTES
        or observed.get("source") != source
        or not {"nosuid", "nodev", "noexec"}.issubset(set(options))
    ):
        raise FaultEvidenceError("private tmpfs mount identity or bounds differ")


def _validate_workspace_marker(
    value: Mapping[str, Any],
    run: OwnedRun | PrelaunchEnospcTarget,
    *,
    peer_run_id: str,
) -> None:
    _exact_keys(
        "workspace owner marker",
        value,
        {
            "schema",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "peer_run_id",
            "profile",
            "path",
            "filesystem",
            "size_bytes",
            "source",
        },
    )
    if (
        value.get("schema") != WORKSPACE_OWNER_SCHEMA
        or value.get("run_id") != run.run_id
        or value.get("contract_sha256") != run.contract_sha256
        or value.get("nonce_sha256") != _nonce_sha256(run.nonce)
        or value.get("cohort_sha256") != run.cohort_sha256
        or value.get("peer_run_id") != peer_run_id
        or value.get("profile") != _ENOSPC_WORKSPACE_PROFILE
        or Path(str(value.get("path"))).resolve(strict=False) != run.workspace
        or value.get("filesystem") != "tmpfs"
        or value.get("size_bytes") != MAX_WORKSPACE_FAULT_BYTES
        or value.get("source") != f"fortgym-m1b-enospc-{run.run_id}"
    ):
        raise FaultEvidenceError("workspace owner marker identity or bound differs")


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > 16 * 1024:
        raise FaultEvidenceError("workspace owner marker exceeds its bound")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write to workspace owner marker")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _write_once_json_durable(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > 16 * 1024:
        raise FaultEvidenceError("prelaunch workspace receipt exceeds its bound")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write to prelaunch workspace receipt")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FaultEvidenceError(f"{name} must be a mapping")
    return value


def _validate_daemon_callback_fields(value: Mapping[str, Any]) -> None:
    expected = {"schema", "host_controller", "inside_container", "invoked"}
    guard = {
        "outer_guard_verified", "outer_guard_stdout_sha256",
        "outer_guard_broker_evidence_sha256",
    }
    if set(value).intersection(guard):
        expected |= guard
        if value.get("outer_guard_verified") is not True or any(
            not isinstance(value.get(name), str)
            or not _SHA256_RE.fullmatch(value[name])
            for name in guard - {"outer_guard_verified"}
        ):
            raise FaultEvidenceError("daemon callback outer guard evidence differs")
    _exact_keys("daemon restart callback result", value, expected)


def _exact_keys(name: str, value: Mapping[str, Any], expected: set[str]) -> None:
    observed = set(value)
    if observed != expected:
        raise FaultEvidenceError(
            f"{name} keys differ; missing={sorted(expected - observed)!r}, "
            f"unexpected={sorted(observed - expected)!r}"
        )


def _bounded_string(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\0" in value:
        raise ValueError(f"{name} must be a non-empty bounded NUL-free string")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FaultEvidenceError(f"{name} must be a non-negative integer")
    return value


def _finite_nonnegative_seconds(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def _counter_delta(before: Any, after: Any, name: str) -> int:
    before_value = _nonnegative_int(before, f"{name} before")
    after_value = _nonnegative_int(after, f"{name} after")
    if after_value < before_value:
        raise FaultEvidenceError(f"{name} moved backwards")
    return after_value - before_value


def _positive_int_sequence(value: Any, name: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise FaultEvidenceError(f"{name} must be a sequence")
    values = tuple(value)
    if len(set(values)) != len(values) or any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 1
        for item in values
    ):
        raise FaultEvidenceError(f"{name} contains invalid process identities")
    return values


__all__ = [
    "CANARY_OBSERVATION_SCHEMA",
    "COHORT_START_SCHEMA",
    "DAEMON_RESTART_CALLBACK_SCHEMA",
    "FAULT_DRIVER_OBSERVATION_SCHEMA",
    "FAULT_STATE_SCHEMA",
    "PRELAUNCH_ENOSPC_RECEIPT_SCHEMA",
    "PRELAUNCH_ENOSPC_TARGET_SCHEMA",
    "PRE_READINESS_OOM_ARM_SCHEMA",
    "PRE_READINESS_OOM_FINALIZE_SCHEMA",
    "PRE_READINESS_OOM_STATE_SCHEMA",
    "RUN_OWNERSHIP_SCHEMA",
    "STEP2_BARRIER_SCHEMA",
    "TMPFS_LIFECYCLE_SCHEMA",
    "WORKSPACE_FAULT_PROFILE_SCHEMA",
    "WORKSPACE_OWNER_SCHEMA",
    "EnospcWorkspaceCleanupTarget",
    "FaultActionError",
    "FaultAuthorizationError",
    "FaultCommandResult",
    "FaultCommandRunner",
    "FaultDriverError",
    "FaultEvidenceError",
    "FaultEvidenceTimeout",
    "FaultGate",
    "FaultInjectionResult",
    "FaultTestAuthorization",
    "LinuxHostFaultProbe",
    "M1BFaultDriver",
    "OwnedRun",
    "OwnedRunEvidenceLoader",
    "OwnedRunEvidencePending",
    "PreReadinessOomMonitor",
    "PreReadinessOomTarget",
    "PrelaunchEnospcTarget",
    "PrelaunchEnospcWorkspace",
    "PrivateTmpfsWorkspace",
    "ProtectedCanary",
    "SubprocessFaultCommandRunner",
    "authorize_private_m1b_fault",
    "fault_observation_journal_path",
    "load_completed_fault_observation",
]
