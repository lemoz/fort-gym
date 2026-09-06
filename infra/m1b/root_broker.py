#!/opt/fortgym-m1b/venv/bin/python -I
"""Narrow root broker for the isolated M1b acceptance host.

The acceptance runner is intentionally not a member of the Docker group and
is never allowed to sudo Docker, ``kill``, ``mount``, ``umount``, or
``systemctl`` directly.  It may sudo only an installed, root-owned copy of
this file with one request path.  The request names a semantic action and a
public run binding; this broker reconstructs the command from durable control
evidence.  A caller can neither select an executable nor smuggle an arbitrary
argument vector through the privilege boundary.

Requests are single use.  A root-owned claim is fsynced before a command is
started and a root-owned receipt is published afterwards.  Completed and
interrupted request identities are both rejected on replay, so no privileged
action can execute twice.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REQUEST_SCHEMA: Final = "fortgym.m1b-root-broker-request/v1"
RECEIPT_SCHEMA: Final = "fortgym.m1b-root-broker-receipt/v1"
CLAIM_SCHEMA: Final = "fortgym.m1b-root-broker-claim/v1"
GRANT_SCHEMA: Final = "fortgym.m1b-root-broker-action-grant/v1"
ACTIVE_BATCH_SCHEMA: Final = "fortgym.m1b-root-broker-active-batch/v1"
STATE_RECORD_SCHEMA: Final = "fortgym.m1b-root-broker-state-record/v1"
CONTAINER_BINDING_SCHEMA: Final = "fortgym.m1b-root-container-binding/v1"
FINAL_ATTESTATION_SCHEMA: Final = "fortgym.m1b-root-broker-attestation/v1"
FROZEN_ACCEPTANCE_SHA256: Final = (
    "b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf"
)
FROZEN_PLAN_SHA256: Final = (
    "d37cad75e7e052ed4463353f0b3138f64143ca1e50337e6ad5eb29cbbca47194"
)
AUTHORITY_EXPIRES_AT: Final = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_STDOUT_BYTES = 4 * 1024 * 1024
_MAX_STDERR_BYTES = 256 * 1024
_MAX_LEDGER_BYTES = 32 * 1024 * 1024
_MAX_LEDGER_RECORDS = 8192
_MAX_EVIDENCE_BYTES = _MAX_STDOUT_BYTES + _MAX_STDERR_BYTES + 128 * 1024
_ZERO_SHA256 = "0" * 64
_INSTALLED_BROKER = Path("/usr/local/libexec/fortgym-m1b-root-broker")
_DOCKER = "/usr/bin/docker"
_KILL = "/bin/kill"
_MOUNT = "/bin/mount"
_UMOUNT = "/bin/umount"
_SYSTEMCTL = "/bin/systemctl"
_NFT = "/usr/sbin/nft"

_RUNTIME_IMAGE_MANIFEST_SHA256: Final = (
    "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
)
_RUNTIME_IMAGE_CONFIG_SHA256: Final = (
    "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
)
_RUNTIME_ARCHIVE_SHA256: Final = (
    "87d66d26553cb271af1b784405d63ea6b95f3bbe20e9429f05e6412133d1f43a"
)
_RUNTIME_IMAGE_LABELS: Final = {
    "org.opencontainers.image.description": (
        "Private ephemeral feasibility image; no publication authorization"
    ),
    "org.opencontainers.image.revision": "236d3187c548b9bc03c4c99829d479d381a008d5",
    "org.opencontainers.image.title": "Fort-Gym M1a DF runtime",
    "org.opencontainers.image.version": "df-0.47.05_dfhack-0.47.05-r8",
}
_RUNTIME_IMAGE_ENVIRONMENT: Final = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}
_SEED_TREE_SHA256: Final = (
    "49ba1de07b62e7afda93b42059b6c566598bb0f4c83d11ae1dfdb78b54cd9ec0"
)
_SEED_WORLD_SHA256: Final = (
    "070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d"
)
_RUNTIME_BINDING_SHA256: Final = (
    "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f"
)
_CANONICAL_DFROOT = Path("/opt/dwarf-fortress")
_CANONICAL_PACKET_ROOT = Path("/opt/fortgym-m1b/packet")
_CANONICAL_PROVIDER_HELPER = Path("/usr/local/libexec/fortgym-provider-network-helper")
_CANONICAL_PROVIDER_BPF = Path("/usr/local/lib/fortgym/provider_network.bpf.o")
_FROZEN_GATE_ORDER: Final = (
    "PORT-1",
    "PORT-2",
    "COLD-RETRY",
    "CO-8",
    "DF-KILL",
    "HARNESS-KILL",
    "OOM",
    "ENOSPC",
    "CONTAINER-RESTART",
    "DAEMON-RESTART",
    "ORPHAN-1",
    "ORPHAN-2",
    "PROVIDER-ENV",
    "PROVIDER-NET",
    "CAP-FAKE",
    "CLEANUP",
)

_ACTIONS = frozenset(
    {
        "docker_image_inspect",
        "docker_run",
        "docker_create",
        "docker_start",
        "docker_container_inspect",
        "docker_logs",
        "docker_remove",
        "docker_managed_list",
        "docker_exec_attest",
        "docker_restart",
        "signal_runtime",
        "signal_harness",
        "signal_supervisor",
        "pause_peer_harness",
        "resume_peer_harness",
        "pause_cohort_harness",
        "resume_cohort_harness",
        "abort_paused_harness",
        "stop_peer_harness",
        "mount_enospc",
        "unmount_enospc",
        "restart_docker",
        "verify_outer_guard",
        "canary_create",
        "canary_inspect",
        "canary_remove",
        "canary_absence",
        "attest_broker_evidence",
    }
)

_READ_ONLY_ACTIONS = frozenset(
    {
        "docker_image_inspect",
        "docker_container_inspect",
        "docker_logs",
        "docker_managed_list",
        "docker_exec_attest",
        "canary_inspect",
        "canary_absence",
        "verify_outer_guard",
    }
)

# PORT-2's second permit is deliberately not a real-runtime permit.  Its only
# root-bound operation is the exact-name absence probe needed to prove that no
# second container was created.  The successful-result validator below rejects
# a present object, so this exception cannot be used to observe or adopt a
# runtime.
_NON_RUNTIME_CONFLICT_ACTIONS = frozenset({"docker_container_inspect"})

_FROZEN_ATTEMPTS: Final[Mapping[str, tuple[str, str, str]]] = {
    "g02-a01-peer_a": ("PORT-2", "peer_a", "real_runtime"),
    "g02-a02-contender_b": ("PORT-2", "contender_b", "non_runtime_conflict"),
    "g03-a01-suppressed_first": ("COLD-RETRY", "suppressed_first", "real_runtime"),
    "g03-a02-replacement_second": ("COLD-RETRY", "replacement_second", "real_runtime"),
    **{
        f"g04-a{index:02d}-run_{index:02d}": (
            "CO-8",
            f"run_{index:02d}",
            "real_runtime",
        )
        for index in range(1, 9)
    },
    "g05-a01-target": ("DF-KILL", "target", "real_runtime"),
    "g05-a02-peer": ("DF-KILL", "peer", "real_runtime"),
    "g06-a01-target": ("HARNESS-KILL", "target", "real_runtime"),
    "g06-a02-peer": ("HARNESS-KILL", "peer", "real_runtime"),
    "g07-a01-target": ("OOM", "target", "real_runtime"),
    "g07-a02-peer": ("OOM", "peer", "real_runtime"),
    "g08-a01-target": ("ENOSPC", "target", "real_runtime"),
    "g08-a02-peer": ("ENOSPC", "peer", "real_runtime"),
    "g09-a01-target": ("CONTAINER-RESTART", "target", "real_runtime"),
    "g09-a02-peer": ("CONTAINER-RESTART", "peer", "real_runtime"),
    "g10-a01-target": ("DAEMON-RESTART", "target", "real_runtime"),
    "g10-a02-peer": ("DAEMON-RESTART", "peer", "real_runtime"),
    "g11-a01-managed_orphan": ("ORPHAN-1", "managed_orphan", "real_runtime"),
    "g12-a01-target": ("ORPHAN-2", "target", "real_runtime"),
    "g14-a01-target": ("PROVIDER-NET", "target", "real_runtime"),
}

_ACTION_ROLES: Final[Mapping[str, frozenset[str]]] = {
    "signal_runtime": frozenset({"target"}),
    "signal_harness": frozenset({"target"}),
    "signal_supervisor": frozenset({"managed_orphan", "target"}),
    "pause_peer_harness": frozenset({"peer_a"}),
    "resume_peer_harness": frozenset({"peer_a"}),
    "pause_cohort_harness": frozenset({f"run_{index:02d}" for index in range(1, 9)}),
    "resume_cohort_harness": frozenset({f"run_{index:02d}" for index in range(1, 9)}),
    "abort_paused_harness": frozenset(
        {"peer_a", *(f"run_{index:02d}" for index in range(1, 9))}
    ),
    "stop_peer_harness": frozenset({"peer_a"}),
    "mount_enospc": frozenset({"target"}),
    "unmount_enospc": frozenset({"target"}),
    "restart_docker": frozenset({"target"}),
    "verify_outer_guard": frozenset({"target"}),
    "docker_restart": frozenset({"target"}),
}

_ONE_SHOT_ACTIONS = frozenset(
    {
        "docker_run",
        "docker_create",
        "docker_start",
        "docker_remove",
        "docker_restart",
        "signal_runtime",
        "signal_harness",
        "signal_supervisor",
        "pause_peer_harness",
        "resume_peer_harness",
        "pause_cohort_harness",
        "resume_cohort_harness",
        "abort_paused_harness",
        "stop_peer_harness",
        "mount_enospc",
        "unmount_enospc",
        "restart_docker",
        "canary_create",
        "canary_remove",
        "attest_broker_evidence",
    }
)

_ACTION_GATES: Final[Mapping[str, frozenset[str]]] = {
    "signal_runtime": frozenset({"DF-KILL"}),
    "signal_harness": frozenset({"HARNESS-KILL"}),
    "signal_supervisor": frozenset({"ORPHAN-1", "ORPHAN-2"}),
    "pause_peer_harness": frozenset({"PORT-2"}),
    "resume_peer_harness": frozenset({"PORT-2"}),
    "pause_cohort_harness": frozenset({"CO-8"}),
    "resume_cohort_harness": frozenset({"CO-8"}),
    "abort_paused_harness": frozenset({"PORT-2", "CO-8"}),
    "stop_peer_harness": frozenset({"PORT-2"}),
    "mount_enospc": frozenset({"ENOSPC"}),
    "unmount_enospc": frozenset({"ENOSPC", "CLEANUP"}),
    "restart_docker": frozenset({"DAEMON-RESTART"}),
    "verify_outer_guard": frozenset({"DAEMON-RESTART"}),
    "docker_restart": frozenset({"CONTAINER-RESTART"}),
    "canary_create": frozenset({"BATCH-CANARY"}),
    "canary_inspect": frozenset(
        {
            "BATCH-CANARY",
            "PORT-1",
            "PORT-2",
            "COLD-RETRY",
            "CO-8",
            "DF-KILL",
            "HARNESS-KILL",
            "OOM",
            "ENOSPC",
            "CONTAINER-RESTART",
            "DAEMON-RESTART",
            "ORPHAN-1",
            "ORPHAN-2",
            "PROVIDER-ENV",
            "PROVIDER-NET",
            "CAP-FAKE",
            "CLEANUP",
        }
    ),
    "canary_remove": frozenset({"CLEANUP"}),
    "canary_absence": frozenset({"CLEANUP"}),
    "attest_broker_evidence": frozenset({"CLEANUP"}),
}

_MUTATING_ACTIONS: Final = frozenset(
    {
        "docker_run",
        "docker_create",
        "docker_start",
        "docker_remove",
        "docker_restart",
        "signal_runtime",
        "signal_harness",
        "signal_supervisor",
        "pause_peer_harness",
        "resume_peer_harness",
        "pause_cohort_harness",
        "resume_cohort_harness",
        "abort_paused_harness",
        "stop_peer_harness",
        "mount_enospc",
        "unmount_enospc",
        "restart_docker",
        "canary_create",
        "canary_remove",
        "attest_broker_evidence",
    }
)

_PROVIDER_ENV_NAMES = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "FORT_GYM_M1B_OPENROUTER_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "MISTRAL_API_KEY",
        "COHERE_API_KEY",
    }
)


class BrokerError(RuntimeError):
    """The broker could not prove an exact authorized action."""


@dataclass(frozen=True)
class BrokerLayout:
    """Fixed trusted host layout; injectable only for provider-free tests."""

    repo_root: Path = Path("/opt/fort-gym-m1a")
    state_root: Path = Path("/var/lib/fortgym-m1b")
    venv_python: Path = Path("/opt/fortgym-m1b/venv/bin/python")
    image_archive: Path = Path("/opt/fortgym-m1b/runtime-image.tar.zst")
    root_evidence_root: Path = Path("/var/lib/fortgym-m1b-root-evidence")
    packet_root: Path = _CANONICAL_PACKET_ROOT

    def __post_init__(self) -> None:
        for name in (
            "repo_root",
            "state_root",
            "venv_python",
            "image_archive",
            "root_evidence_root",
            "packet_root",
        ):
            value = Path(getattr(self, name))
            if not value.is_absolute() or "\0" in str(value):
                raise ValueError(f"{name} must be an absolute NUL-free path")
            object.__setattr__(self, name, Path(os.path.normpath(str(value))))
        if self.state_root == Path(self.state_root.anchor):
            raise ValueError("state_root cannot be a filesystem root")

    @property
    def control_root(self) -> Path:
        return self.state_root / "control"

    @property
    def artifacts_root(self) -> Path:
        return self.state_root / "artifacts"

    @property
    def broker_root(self) -> Path:
        return self.state_root / "broker"

    @property
    def request_root(self) -> Path:
        return self.broker_root / "requests"

    @property
    def claim_root(self) -> Path:
        return self.broker_root / "claims"

    @property
    def incoming_root(self) -> Path:
        return self.claim_root / "incoming"

    @property
    def grant_root(self) -> Path:
        return self.broker_root / "grants"

    @property
    def receipt_root(self) -> Path:
        return self.broker_root / "receipts"

    @property
    def broker_state_root(self) -> Path:
        return self.broker_root / "state"

    @property
    def broker_state_ledger(self) -> Path:
        return self.broker_state_root / "state.jsonl"

    @property
    def broker_lock_path(self) -> Path:
        return self.broker_state_root / "broker.lock"

    @property
    def inflight_root(self) -> Path:
        return self.broker_state_root / "inflight"

    def batch_evidence_root(self, batch_id: str) -> Path:
        if not _ID_RE.fullmatch(batch_id):
            raise BrokerError("batch evidence root identity is invalid")
        return self.state_root / "evidence" / batch_id

    @property
    def acceptance_path(self) -> Path:
        return self.repo_root / "infra" / "m1b" / "acceptance.yaml"

    @property
    def entrypoint_path(self) -> Path:
        return self.repo_root / "infra" / "m1b" / "runtime_entrypoint.sh"

    @property
    def db_path(self) -> Path:
        # state_root is deliberately root-owned. SQLite must be able to create
        # its journal/WAL beside the database, so the registry belongs in the
        # private service-owned control directory.
        return self.control_root / "registry.sqlite3"

    @property
    def trusted_paths_evidence(self) -> Path:
        return self.root_evidence_root / "trusted-paths.json"

    @property
    def control_ssh_flow_evidence(self) -> Path:
        return self.root_evidence_root / "control-ssh-flow.json"

    @property
    def packet_manifest_path(self) -> Path:
        return self.packet_root / "PACKET.json"

    @property
    def source_manifest_path(self) -> Path:
        return self.packet_root / "source-manifest.json"

    @property
    def bootstrap_receipt_path(self) -> Path:
        return self.root_evidence_root / "bootstrap.json"

    def broker_attestation_path(self, batch_id: str) -> Path:
        if not _ID_RE.fullmatch(batch_id):
            raise BrokerError("broker attestation batch identity is invalid")
        return (
            self.root_evidence_root / "batches" / batch_id / "broker-attestation.json"
        )

    @property
    def bind_source_root(self) -> Path:
        return self.root_evidence_root / "bind-sources"


@dataclass(frozen=True)
class CommandCapture:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


CommandExecutor = Callable[[Sequence[str], float], CommandCapture]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def broker_policy_sha256(*, repo_root: Path, state_root: Path) -> str:
    """Return the exact public policy identity a client must require."""

    policy = {
        "schema": "fortgym.m1b-root-broker-policy/v1",
        "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
        "plan_sha256": FROZEN_PLAN_SHA256,
        "authority_expires_at": AUTHORITY_EXPIRES_AT.isoformat(),
        "actions": sorted(_ACTIONS),
        "read_only_actions": sorted(_READ_ONLY_ACTIONS),
        "one_shot_actions": sorted(_ONE_SHOT_ACTIONS),
        "non_runtime_conflict_actions": sorted(_NON_RUNTIME_CONFLICT_ACTIONS),
        "action_gates": {
            key: sorted(value) for key, value in sorted(_ACTION_GATES.items())
        },
        "repo_root": str(Path(repo_root)),
        "state_root": str(Path(state_root)),
        "shell": False,
    }
    return _sha256_bytes(_canonical_bytes(policy))


def _read_fd_bounded(
    descriptor: int,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > maximum:
            raise BrokerError("file exceeds its broker size bound")
    if size == 0 and not allow_empty:
        raise BrokerError("required broker evidence is empty")
    return b"".join(chunks)


def _read_regular_nofollow(
    path: Path,
    *,
    maximum: int,
    owner_uid: int | None = None,
    require_nlink_one: bool = True,
    exact_mode: int | None = None,
    allow_empty: bool = False,
) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise BrokerError("required broker evidence is unreadable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (owner_uid is not None and metadata.st_uid != owner_uid)
            or (require_nlink_one and metadata.st_nlink != 1)
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or (exact_mode is not None and stat.S_IMODE(metadata.st_mode) != exact_mode)
            or (metadata.st_size <= 0 and not allow_empty)
            or metadata.st_size > maximum
        ):
            raise BrokerError("required broker evidence metadata is unsafe")
        raw = _read_fd_bounded(
            descriptor,
            maximum=maximum,
            allow_empty=allow_empty,
        )
        after = os.fstat(descriptor)
        if (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BrokerError("required broker evidence changed during read")
        return raw
    finally:
        os.close(descriptor)


def _sha256_file(
    path: Path,
    *,
    maximum: int | None = None,
    owner_uid: int | None = None,
    allow_empty: bool = False,
) -> str:
    limit = maximum or 1024 * 1024 * 1024
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise BrokerError("required broker evidence is unreadable") from exc
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (owner_uid is not None and before.st_uid != owner_uid)
            or stat.S_IMODE(before.st_mode) & 0o022
            or (before.st_size <= 0 and not allow_empty)
            or before.st_size > limit
        ):
            raise BrokerError("required broker evidence metadata is unsafe")
        observed = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > limit:
                raise BrokerError("file exceeds its broker size bound")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if observed != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BrokerError("required broker evidence changed during hashing")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _read_json(
    path: Path,
    *,
    maximum: int = _MAX_REQUEST_BYTES,
    owner_uid: int | None = None,
) -> dict[str, Any]:
    raw = _read_regular_nofollow(
        path,
        maximum=maximum,
        owner_uid=owner_uid,
        require_nlink_one=False,
    )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError("required broker evidence is invalid JSON") from exc
    if not isinstance(value, dict):
        raise BrokerError("required broker evidence must be an object")
    return value


def _read_json_with_digest(
    path: Path,
    *,
    maximum: int = _MAX_REQUEST_BYTES,
    owner_uid: int | None = None,
) -> tuple[dict[str, Any], str]:
    raw = _read_regular_nofollow(
        path,
        maximum=maximum,
        owner_uid=owner_uid,
        require_nlink_one=False,
    )
    return _parse_json_object(raw, label="required broker evidence"), _sha256_bytes(raw)


def _validate_directory(
    path: Path,
    *,
    owner_uid: int,
    exact_mode: int | None = None,
) -> os.stat_result:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise BrokerError("broker directory is absent or unsafe") from exc
    try:
        metadata = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != owner_uid
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or (exact_mode is not None and stat.S_IMODE(metadata.st_mode) != exact_mode)
    ):
        raise BrokerError("broker directory ownership or mode is unsafe")
    return metadata


def _write_once(
    path: Path,
    payload: Mapping[str, Any],
    *,
    mode: int = 0o600,
    owner_uid: int = 0,
) -> None:
    encoded = _canonical_bytes(dict(payload)) + b"\n"
    _validate_directory(path.parent, owner_uid=owner_uid, exact_mode=0o700)
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    descriptor = -1
    try:
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
            dir_fd=directory_fd,
        )
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short broker evidence write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.fsync(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_fd)


def _write_bytes_once(
    path: Path,
    encoded: bytes,
    *,
    owner_uid: int = 0,
    mode: int = 0o600,
) -> None:
    if not encoded:
        raise BrokerError("broker evidence bytes cannot be empty")
    _validate_directory(path.parent, owner_uid=owner_uid, exact_mode=0o700)
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    descriptor = -1
    try:
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
            dir_fd=directory_fd,
        )
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short broker evidence write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.fsync(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_fd)


def _parse_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise BrokerError(f"{label} must be an object")
    return value


def _bounded_text(value: str, maximum: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= maximum:
        return value
    marker = b"\n[fortgym broker capture truncated to tail]\n"
    return (marker + encoded[-(maximum - len(marker)) :]).decode(
        "utf-8", errors="replace"
    )


def _subprocess_execute(
    argv: Sequence[str],
    timeout_seconds: float,
    *,
    pass_fds: Sequence[int] = (),
) -> CommandCapture:
    normalized = tuple(str(item) for item in argv)
    if not normalized or any(not item or "\0" in item for item in normalized):
        raise BrokerError("derived broker command is invalid")
    environment = {
        "HOME": "/root",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    }
    try:
        completed = subprocess.run(
            normalized,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            pass_fds=tuple(pass_fds),
            shell=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrokerError("derived broker command failed before completion") from exc
    return CommandCapture(
        argv=normalized,
        returncode=completed.returncode,
        stdout=_bounded_text(completed.stdout, _MAX_STDOUT_BYTES),
        stderr=_bounded_text(completed.stderr, _MAX_STDERR_BYTES),
    )


def _default_execute(argv: Sequence[str], timeout_seconds: float) -> CommandCapture:
    return _subprocess_execute(argv, timeout_seconds)


def _request_owner_uid() -> int:
    raw = os.environ.get("SUDO_UID")
    if raw is None or not raw.isdigit() or int(raw) <= 0:
        raise BrokerError("broker requires a nonroot sudo caller identity")
    return int(raw)


def validate_request_path(
    path: Path,
    *,
    layout: BrokerLayout,
    caller_uid: int,
) -> Path:
    """Validate only the lexical request name; opening is one atomic operation."""

    candidate = Path(path)
    if not candidate.is_absolute() or "\0" in str(candidate):
        raise BrokerError("request path must be absolute and NUL-free")
    if (
        candidate.parent != layout.request_root
        or not _SHA256_RE.fullmatch(candidate.stem)
        or candidate.suffix != ".json"
    ):
        raise BrokerError("request path is outside the canonical request directory")
    _validate_directory(layout.request_root, owner_uid=caller_uid, exact_mode=0o700)
    return candidate


def validate_request(payload: Mapping[str, Any], *, filename_id: str) -> dict[str, Any]:
    expected = {
        "schema",
        "request_id",
        "acceptance_sha256",
        "batch_id",
        "gate_id",
        "grant_kind",
        "attempt_id",
        "attempt_identity_sha256",
        "action",
        "run_id",
        "peer_run_id",
        "contract_sha256",
        "nonce_sha256",
        "cohort_sha256",
        "logical_argv_sha256",
        "parameters",
    }
    if set(payload) != expected or payload.get("schema") != REQUEST_SCHEMA:
        raise BrokerError("broker request schema or fields differ")
    request_id = payload.get("request_id")
    if request_id != filename_id or not isinstance(request_id, str):
        raise BrokerError("broker request identity differs from its path")
    if payload.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256:
        raise BrokerError("broker acceptance digest differs")
    for name in ("batch_id", "gate_id"):
        value = payload.get(name)
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise BrokerError(f"broker {name} is invalid")
    action = payload.get("action")
    if action not in _ACTIONS:
        raise BrokerError("broker action is not allowlisted")
    restricted_gates = _ACTION_GATES.get(str(action))
    if restricted_gates is not None and payload["gate_id"] not in restricted_gates:
        raise BrokerError("broker action is forbidden for this gate")
    for name in ("run_id", "peer_run_id"):
        value = payload.get(name)
        if value is not None and (
            not isinstance(value, str) or not _ID_RE.fullmatch(value)
        ):
            raise BrokerError(f"broker {name} is invalid")
    for name in (
        "attempt_identity_sha256",
        "contract_sha256",
        "nonce_sha256",
        "cohort_sha256",
        "logical_argv_sha256",
    ):
        value = payload.get(name)
        if value is not None and (
            not isinstance(value, str) or not _SHA256_RE.fullmatch(value)
        ):
            raise BrokerError(f"broker {name} is invalid")
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict) or len(_canonical_bytes(parameters)) > 8192:
        raise BrokerError("broker parameters are invalid")
    serialized = _canonical_bytes(payload).decode("ascii")
    lowered = serialized.lower()
    if any(name.lower() in lowered for name in _PROVIDER_ENV_NAMES):
        raise BrokerError("provider material is forbidden in broker requests")
    if any(marker in lowered for marker in ("sk-", "api_key", "authorization")):
        raise BrokerError("credential-shaped broker request content is forbidden")
    grant_kind = payload.get("grant_kind")
    if grant_kind == "attempt":
        attempt_id = payload.get("attempt_id")
        if not isinstance(attempt_id, str) or attempt_id not in _FROZEN_ATTEMPTS:
            raise BrokerError("attempt grant identity is not frozen")
        if not isinstance(payload.get("attempt_identity_sha256"), str):
            raise BrokerError("attempt grant lacks its durable identity")
        if payload.get("run_id") is None:
            raise BrokerError("attempt grant lacks one exact run identity")
        if any(
            not isinstance(payload.get(name), str)
            for name in ("contract_sha256", "nonce_sha256", "cohort_sha256")
        ):
            raise BrokerError("run-bound broker request lacks exact public identity")
    elif grant_kind == "batch_canary":
        if action not in {
            "canary_create",
            "canary_inspect",
            "canary_remove",
            "canary_absence",
            "attest_broker_evidence",
        }:
            raise BrokerError("batch-canary grant cannot authorize run work")
        if any(
            payload.get(name) is not None
            for name in (
                "attempt_id",
                "attempt_identity_sha256",
                "run_id",
                "peer_run_id",
                "contract_sha256",
                "nonce_sha256",
                "cohort_sha256",
            )
        ):
            raise BrokerError("batch-canary grant carries a run identity")
    else:
        raise BrokerError("broker grant kind is invalid")
    return dict(payload)


@dataclass(frozen=True)
class _RunBinding:
    run_id: str
    contract_sha256: str
    nonce_sha256: str
    cohort_sha256: str
    container_name: str
    container_id: str | None
    port: int
    runtime_controller: Any
    launch: Mapping[str, Any]
    launch_sha256: str


@dataclass(frozen=True)
class _BatchPhase:
    active_gate: str | None
    cleanup_scope: str | None
    cleanup_gate_id: str | None
    batch_head_sha256: str
    gate_start_heads: Mapping[str, str]
    finalized: bool


@dataclass(frozen=True)
class _AttemptMirror:
    attempt_id: str
    gate_id: str
    role: str
    kind: str
    identity_sha256: str | None
    completed: bool


@dataclass(frozen=True)
class _LedgerSnapshot:
    batch_records: tuple[Mapping[str, Any], ...]
    attempt_records: tuple[Mapping[str, Any], ...]
    phase: _BatchPhase
    attempts: Mapping[str, _AttemptMirror]
    batch_file_sha256: str
    attempt_file_sha256: str

    @property
    def batch_hashes(self) -> tuple[str, ...]:
        return tuple(str(record["record_sha256"]) for record in self.batch_records)

    @property
    def attempt_hashes(self) -> tuple[str, ...]:
        return tuple(str(record["record_sha256"]) for record in self.attempt_records)


@dataclass(frozen=True)
class _ProcessIdentity:
    pid: int
    starttime: int
    process_group_id: int
    parent_pid: int
    environment_sha256: str
    command_sha256: str
    role: str


@dataclass(frozen=True)
class _MountIdentity:
    path: Path
    device: int
    inode: int
    ancestry: tuple[tuple[str, int, int], ...]
    expect_mounted: bool


@dataclass(frozen=True)
class _RecoveryDecision:
    epoch: int
    noop: bool
    reason: str | None


class RootBroker:
    """Validate, derive, execute, and durably receipt one request."""

    def __init__(
        self,
        *,
        layout: BrokerLayout | None = None,
        execute: CommandExecutor = _default_execute,
        caller_uid: int | None = None,
        trusted_uid: int = 0,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.layout = layout or BrokerLayout()
        self._command_executor = execute
        self._uses_default_executor = execute is _default_execute
        self._caller_uid = caller_uid
        self._trusted_uid = trusted_uid
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._evidence_owner_uid: int | None = None
        self._measurement_code_sha256: str | None = None
        self._execution_process_identity: _ProcessIdentity | None = None
        self._execution_supervisor_child_identity: _ProcessIdentity | None = None
        self._execution_mount_identity: _MountIdentity | None = None
        self._execution_mount_fd: int | None = None
        self._execution_mount_parent_fd: int | None = None
        self._execution_mount_parent_restore: tuple[int, int, int, int, int] | None = (
            None
        )
        self._derived_target_pid: int | None = None
        self._trusted_runtime_verified = False
        self._broker_lock_descriptor: int | None = None

    def handle(self, request_path: Path) -> dict[str, Any]:
        if os.geteuid() != 0 and self._caller_uid is None:
            raise BrokerError("installed root broker must execute as root")
        observed_now = self._now()
        if (
            observed_now.tzinfo is None
            or observed_now.astimezone(UTC) >= AUTHORITY_EXPIRES_AT
        ):
            raise BrokerError("M1b root-broker authority has expired")
        caller_uid = (
            self._caller_uid if self._caller_uid is not None else _request_owner_uid()
        )
        # A broker object is reusable in tests, but installed trust is re-proved
        # for every request.  The flag only suppresses duplicate verification
        # by imports made later during this same request.
        self._trusted_runtime_verified = False
        self._evidence_owner_uid = caller_uid
        self._verify_trusted_runtime()
        if (
            _sha256_file(
                self.layout.acceptance_path,
                maximum=256 * 1024,
                owner_uid=self._trusted_uid,
            )
            != FROZEN_ACCEPTANCE_SHA256
        ):
            raise BrokerError("installed acceptance contract digest differs")
        self._ensure_root_evidence_directories()
        with self._exclusive_broker_lock():
            return self._handle_locked(Path(request_path), caller_uid=caller_uid)

    def _handle_locked(
        self,
        request_path: Path,
        *,
        caller_uid: int,
    ) -> dict[str, Any]:
        path, raw = self._claim_request(request_path, caller_uid=caller_uid)
        payload = validate_request(
            _parse_json_object(raw, label="broker request"), filename_id=path.stem
        )
        with self._request_execution_lock(path.stem):
            return self._handle_claimed(
                path=path,
                raw=raw,
                payload=payload,
                caller_uid=caller_uid,
            )

    def _handle_claimed(
        self,
        *,
        path: Path,
        raw: bytes,
        payload: Mapping[str, Any],
        caller_uid: int,
    ) -> dict[str, Any]:
        request_sha256 = _sha256_bytes(raw)
        claim_path = self.layout.claim_root / f"{path.stem}.json"
        receipt_path = self.layout.receipt_root / f"{path.stem}.json"
        claim = {
            "schema": CLAIM_SCHEMA,
            "request_id": path.stem,
            "request_sha256": request_sha256,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "batch_id": payload["batch_id"],
            "gate_id": payload["gate_id"],
            "grant_kind": payload["grant_kind"],
            "attempt_id": payload["attempt_id"],
            "action": payload["action"],
        }
        try:
            _write_once(claim_path, claim)
        except FileExistsError as exc:
            raise BrokerError(
                "broker request is already claimed without a completed receipt"
            ) from exc

        phase = self._validate_grant(payload, caller_uid=caller_uid, strict=False)
        snapshot = self._strict_ledger_snapshot(payload, caller_uid=caller_uid)
        if phase is not None and phase != snapshot.phase:
            raise BrokerError("strict request phase differs from grant phase")
        self._reconcile_root_mirror(payload, snapshot=snapshot)
        binding = self._load_binding(payload, caller_uid=caller_uid)
        if binding is not None and binding.launch_sha256 != payload.get(
            "attempt_identity_sha256"
        ):
            raise BrokerError("attempt identity differs from its durable launch")
        logical_argv, actual_argv, timeout_seconds = self._derive_command(
            payload, binding
        )
        logical_digest = _sha256_bytes(_canonical_bytes(list(logical_argv)))
        if logical_digest != payload.get("logical_argv_sha256"):
            raise BrokerError("derived logical command digest differs")
        recovery = self._recovery_decision(payload, binding=binding)
        grant_path = self._consume_action_grant(
            payload,
            logical_digest=logical_digest,
            phase=phase,
            recovery_epoch=recovery.epoch,
        )
        self._append_state_record(
            payload,
            event="action_claimed",
            data={
                "action": payload["action"],
                "attempt_id": payload["attempt_id"],
                "request_sha256": request_sha256,
                "grant_sha256": _sha256_file(
                    grant_path,
                    maximum=64 * 1024,
                    owner_uid=self._trusted_uid,
                ),
                "logical_argv_sha256": logical_digest,
                "batch_head_sha256": snapshot.phase.batch_head_sha256,
                "attempt_head_sha256": (
                    snapshot.attempt_hashes[-1]
                    if snapshot.attempt_hashes
                    else _ZERO_SHA256
                ),
                "recovery_epoch": recovery.epoch,
                "recovery_noop": recovery.noop,
                "recovery_reason": recovery.reason,
                "target_pid": self._derived_target_pid,
                "binding": self._public_binding(binding),
            },
        )
        self._confirm_caller_snapshot(
            payload,
            snapshot=snapshot,
            binding=binding,
            caller_uid=caller_uid,
        )
        self._execution_process_identity = None
        self._execution_supervisor_child_identity = None
        self._execution_mount_identity = None
        if self._execution_mount_fd is not None:
            raise BrokerError("prior mount target descriptor remains open")
        if self._execution_mount_parent_fd is not None:
            raise BrokerError("prior mount parent descriptor remains open")
        try:
            with self._execution_guard(payload, binding, actual_argv) as guarded_argv:
                self._revalidate_execution_target(payload, binding)
                if recovery.noop:
                    capture = self._recovery_noop_capture(
                        payload,
                        binding=binding,
                        actual_argv=actual_argv,
                        reason=recovery.reason,
                    )
                elif payload["action"] == "attest_broker_evidence":
                    capture = self._execute_final_attestation(
                        payload,
                        grant_path=grant_path,
                        snapshot=snapshot,
                        actual_argv=actual_argv,
                    )
                elif payload["action"] in {
                    "signal_runtime",
                    "signal_harness",
                    "signal_supervisor",
                    "pause_peer_harness",
                    "resume_peer_harness",
                    "pause_cohort_harness",
                    "resume_cohort_harness",
                    "abort_paused_harness",
                    "stop_peer_harness",
                }:
                    capture = self._execute_pidfd_signal(
                        payload,
                        actual_argv=actual_argv,
                    )
                elif payload["action"] in {"mount_enospc", "unmount_enospc"}:
                    capture = self._execute_mount_fd_bound(
                        actual_argv,
                        timeout_seconds=timeout_seconds,
                    )
                else:
                    capture = self._execute(guarded_argv, timeout_seconds)
                    if tuple(guarded_argv) != tuple(actual_argv):
                        if capture.argv != tuple(guarded_argv):
                            raise BrokerError(
                                "broker command executor changed the guarded argv"
                            )
                        capture = CommandCapture(
                            argv=tuple(actual_argv),
                            returncode=capture.returncode,
                            stdout=capture.stdout,
                            stderr=capture.stderr,
                        )
                if capture.argv != tuple(actual_argv):
                    raise BrokerError("broker command executor changed the exact argv")
                if (
                    payload["action"] == "verify_outer_guard"
                    and capture.returncode == 0
                ):
                    self._validate_outer_guard_capture(capture.stdout)
                capture = self._validate_command_result(payload, binding, capture)
        finally:
            if self._execution_mount_fd is not None:
                os.close(self._execution_mount_fd)
                self._execution_mount_fd = None
            if self._execution_mount_parent_fd is not None:
                parent_descriptor = self._execution_mount_parent_fd
                restore = self._execution_mount_parent_restore
                try:
                    if restore is None:
                        raise BrokerError("mount parent restore identity is absent")
                    owner_uid, owner_gid, mode, device, inode = restore
                    metadata = os.fstat(parent_descriptor)
                    if (metadata.st_dev, metadata.st_ino) != (device, inode):
                        raise BrokerError("mount parent identity changed")
                    os.fchown(parent_descriptor, owner_uid, owner_gid)
                    os.fchmod(parent_descriptor, mode)
                    restored = os.fstat(parent_descriptor)
                    if (
                        restored.st_uid != owner_uid
                        or restored.st_gid != owner_gid
                        or stat.S_IMODE(restored.st_mode) != mode
                    ):
                        raise BrokerError("mount parent protection restore failed")
                finally:
                    os.close(parent_descriptor)
                    self._execution_mount_parent_fd = None
                    self._execution_mount_parent_restore = None
        self._update_canary_state(
            payload,
            capture=capture,
        )
        safe_result: Mapping[str, Any] | None = None
        if payload["action"] == "attest_broker_evidence" and capture.returncode == 0:
            try:
                parsed_result = json.loads(capture.stdout)
            except json.JSONDecodeError as exc:
                raise BrokerError("final attestation result is invalid JSON") from exc
            if not isinstance(parsed_result, Mapping):
                raise BrokerError("final attestation result is not an object")
            safe_result = dict(parsed_result)
        receipt_binding = self._public_binding(binding)
        if (
            binding is not None
            and payload["action"] in {"docker_run", "docker_create"}
            and capture.returncode == 0
        ):
            container_id = self._root_container_id(binding.run_id)
            if container_id is None:
                raise BrokerError("successful Docker launch lacks a root binding")
            if receipt_binding is None:
                raise BrokerError("successful Docker launch lacks a public binding")
            receipt_binding = {**receipt_binding, "container_id": container_id}
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "ok": capture.returncode == 0,
            "request_id": payload["request_id"],
            "request_sha256": request_sha256,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "policy_sha256": self.policy_sha256,
            "broker_source_sha256": _sha256_file(
                Path(__file__), maximum=2 * 1024 * 1024, owner_uid=self._trusted_uid
            ),
            "batch_id": payload["batch_id"],
            "gate_id": payload["gate_id"],
            "grant_kind": payload["grant_kind"],
            "attempt_id": payload["attempt_id"],
            "attempt_identity_sha256": payload["attempt_identity_sha256"],
            "action": payload["action"],
            "binding": receipt_binding,
            "logical_argv_sha256": logical_digest,
            "returncode": capture.returncode,
            "stdout": capture.stdout,
            "stderr": capture.stderr,
            "stdout_sha256": _sha256_bytes(capture.stdout.encode("utf-8")),
            "stderr_sha256": _sha256_bytes(capture.stderr.encode("utf-8")),
            "result": safe_result,
            "shell": False,
            "action_grant_sha256": _sha256_file(
                grant_path,
                maximum=64 * 1024,
                owner_uid=self._trusted_uid,
            ),
        }
        _write_once(receipt_path, receipt)
        self._append_state_record(
            payload,
            event=("action_completed" if capture.returncode == 0 else "action_failed"),
            data={
                "action": payload["action"],
                "attempt_id": payload["attempt_id"],
                "request_sha256": request_sha256,
                "receipt_sha256": _sha256_file(
                    receipt_path,
                    maximum=_MAX_EVIDENCE_BYTES,
                    owner_uid=self._trusted_uid,
                ),
                "returncode": capture.returncode,
                "recovery_epoch": recovery.epoch,
                "recovery_noop": recovery.noop,
                "binding": receipt_binding,
            },
        )
        if payload["action"] in _MUTATING_ACTIONS and capture.returncode != 0:
            raise BrokerError("privileged mutation returned nonzero")
        return receipt

    @property
    def policy_sha256(self) -> str:
        return broker_policy_sha256(
            repo_root=self.layout.repo_root,
            state_root=self.layout.state_root,
        )

    @contextlib.contextmanager
    def _exclusive_broker_lock(self) -> Any:
        _validate_directory(
            self.layout.broker_state_root,
            owner_uid=self._trusted_uid,
            exact_mode=0o700,
        )
        descriptor = os.open(
            self.layout.broker_lock_path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self._trusted_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise BrokerError("root broker lock metadata is unsafe")
            if self._broker_lock_descriptor is not None:
                raise BrokerError("root broker state lock is already held")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._broker_lock_descriptor = descriptor
            yield
        finally:
            try:
                if self._broker_lock_descriptor == descriptor:
                    self._broker_lock_descriptor = None
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _execute(self, argv: Sequence[str], timeout_seconds: float) -> CommandCapture:
        """Run external work without holding the global root-state lock."""

        with self._released_state_lock():
            return self._command_executor(argv, timeout_seconds)

    @contextlib.contextmanager
    def _released_state_lock(self) -> Any:
        descriptor = self._broker_lock_descriptor
        if descriptor is None:
            yield
            return
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        self._broker_lock_descriptor = None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._broker_lock_descriptor = descriptor

    def _execute_with_pass_fd(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
        *,
        descriptor: int,
    ) -> CommandCapture:
        with self._released_state_lock():
            capture = (
                _subprocess_execute(
                    argv,
                    timeout_seconds,
                    pass_fds=(descriptor,),
                )
                if self._uses_default_executor
                else self._command_executor(argv, timeout_seconds)
            )
        if capture.argv != tuple(str(item) for item in argv):
            raise BrokerError("fd-bound command executor changed the exact argv")
        return capture

    @contextlib.contextmanager
    def _request_execution_lock(self, request_id: str) -> Any:
        """Keep one exact request live while allowing distinct slot commands."""

        if not _SHA256_RE.fullmatch(request_id):
            raise BrokerError("in-flight request identity is invalid")
        _validate_directory(
            self.layout.inflight_root,
            owner_uid=self._trusted_uid,
            exact_mode=0o700,
        )
        path = self.layout.inflight_root / f"{request_id}.lock"
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self._trusted_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise BrokerError("in-flight request lock metadata is unsafe")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BrokerError("broker request is already executing") from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _request_is_inflight(self, request_id: str) -> bool:
        if not _SHA256_RE.fullmatch(request_id):
            raise BrokerError("pending request identity is invalid")
        path = self.layout.inflight_root / f"{request_id}.lock"
        try:
            descriptor = os.open(
                path,
                os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise BrokerError("pending request lock is unreadable") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self._trusted_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise BrokerError("pending request lock metadata is unsafe")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            return False
        finally:
            os.close(descriptor)

    def _state_records(self) -> list[dict[str, Any]]:
        path = self.layout.broker_state_ledger
        if not path.exists():
            return []
        raw = _read_regular_nofollow(
            path,
            maximum=_MAX_LEDGER_BYTES,
            owner_uid=self._trusted_uid,
            require_nlink_one=True,
        )
        if not raw.endswith(b"\n"):
            raise BrokerError("root state ledger lacks its terminal newline")
        previous = _ZERO_SHA256
        records: list[dict[str, Any]] = []
        expected = {
            "schema",
            "sequence",
            "previous_record_sha256",
            "acceptance_sha256",
            "plan_sha256",
            "batch_id",
            "request_id",
            "event",
            "data",
            "record_sha256",
        }
        for sequence, line in enumerate(raw.splitlines(), start=1):
            record = _parse_json_object(line, label="root state record")
            claimed = record.get("record_sha256")
            hashed = dict(record)
            hashed.pop("record_sha256", None)
            if (
                set(record) != expected
                or record.get("schema") != STATE_RECORD_SCHEMA
                or record.get("sequence") != sequence
                or record.get("previous_record_sha256") != previous
                or record.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
                or record.get("plan_sha256") != FROZEN_PLAN_SHA256
                or not isinstance(record.get("batch_id"), str)
                or not _ID_RE.fullmatch(str(record["batch_id"]))
                or (
                    record.get("request_id") is not None
                    and not _SHA256_RE.fullmatch(str(record["request_id"]))
                )
                or record.get("event")
                not in {
                    "ledger_observed",
                    "action_claimed",
                    "action_completed",
                    "action_failed",
                    "container_bound",
                    "container_removed",
                    "image_selected",
                    "execution_target_bound",
                    "recovery_boundary",
                }
                or not isinstance(record.get("data"), dict)
                or not isinstance(claimed, str)
                or not _SHA256_RE.fullmatch(claimed)
                or _sha256_bytes(_canonical_bytes(hashed)) != claimed
            ):
                raise BrokerError("root state ledger identity or chain differs")
            records.append(record)
            previous = claimed
        return records

    def _append_state_record(
        self,
        request: Mapping[str, Any],
        *,
        event: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        records = self._state_records()
        if len(records) >= _MAX_LEDGER_RECORDS:
            raise BrokerError("root state ledger reached its record bound")
        record = {
            "schema": STATE_RECORD_SCHEMA,
            "sequence": len(records) + 1,
            "previous_record_sha256": (
                str(records[-1]["record_sha256"]) if records else _ZERO_SHA256
            ),
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "batch_id": request["batch_id"],
            "request_id": request.get("request_id"),
            "event": event,
            "data": dict(data),
        }
        record["record_sha256"] = _sha256_bytes(_canonical_bytes(record))
        encoded = _canonical_bytes(record) + b"\n"
        descriptor = os.open(
            self.layout.broker_state_ledger,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self._trusted_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise BrokerError("root state ledger metadata is unsafe")
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short root state append")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory_fd = os.open(
            self.layout.broker_state_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return record

    def _reconcile_root_mirror(
        self,
        request: Mapping[str, Any],
        *,
        snapshot: _LedgerSnapshot,
    ) -> None:
        records = self._state_records()
        observed = [
            record
            for record in records
            if record["event"] == "ledger_observed"
            and record["batch_id"] == request["batch_id"]
        ]
        if observed:
            previous = observed[-1]["data"]
            old_batch = tuple(previous.get("batch_record_sha256s", ()))
            old_attempt = tuple(previous.get("attempt_record_sha256s", ()))
            if (
                snapshot.batch_hashes[: len(old_batch)] != old_batch
                or snapshot.attempt_hashes[: len(old_attempt)] != old_attempt
            ):
                raise BrokerError("caller ledger rewrote a root-observed prefix")
        pending: dict[str, Mapping[str, Any]] = {}
        for record in records:
            request_id = record.get("request_id")
            if record["batch_id"] != request["batch_id"] or not isinstance(
                request_id, str
            ):
                continue
            if record["event"] == "action_claimed":
                pending[request_id] = record
            elif record["event"] in {"action_completed", "action_failed"}:
                pending.pop(request_id, None)
        pending_mutations = {
            request_id: record
            for request_id, record in pending.items()
            if record["data"].get("action") in _MUTATING_ACTIONS
        }
        active_pending = {
            request_id: record
            for request_id, record in pending_mutations.items()
            if self._request_is_inflight(request_id)
        }
        ambiguous_pending = {
            request_id: record
            for request_id, record in pending_mutations.items()
            if request_id not in active_pending
        }
        if active_pending:
            current_attempt_id = request.get("attempt_id")
            if current_attempt_id is None or snapshot.phase.active_gate is None:
                raise BrokerError("a live root mutation blocks batch-scoped work")
            for record in active_pending.values():
                pending_attempt_id = record["data"].get("attempt_id")
                if (
                    not isinstance(pending_attempt_id, str)
                    or pending_attempt_id == current_attempt_id
                    or pending_attempt_id not in _FROZEN_ATTEMPTS
                    or _FROZEN_ATTEMPTS[pending_attempt_id][0]
                    != snapshot.phase.active_gate
                    or _FROZEN_ATTEMPTS[str(current_attempt_id)][0]
                    != snapshot.phase.active_gate
                ):
                    raise BrokerError(
                        "a live root mutation conflicts with this exact slot"
                    )
        if ambiguous_pending:
            if request["action"] == "attest_broker_evidence":
                self._require_failed_seal_for_recovery_attestation(request)
            recovery_actions = {
                "attest_broker_evidence",
                "docker_container_inspect",
                "docker_logs",
                "docker_managed_list",
                "docker_remove",
                "unmount_enospc",
                "canary_inspect",
                "canary_remove",
                "canary_absence",
                "pause_peer_harness",
                "resume_peer_harness",
                "pause_cohort_harness",
                "resume_cohort_harness",
                "abort_paused_harness",
                "stop_peer_harness",
            }
            if request["action"] not in recovery_actions:
                raise BrokerError(
                    "an ambiguous prior root action requires cleanup recovery"
                )
            self._append_state_record(
                request,
                event="recovery_boundary",
                data={"pending_request_ids": sorted(ambiguous_pending)},
            )
        self._validate_root_action_transition(
            request, snapshot=snapshot, records=records
        )
        self._append_state_record(
            request,
            event="ledger_observed",
            data={
                "batch_record_sha256s": list(snapshot.batch_hashes),
                "attempt_record_sha256s": list(snapshot.attempt_hashes),
            },
        )

    def _validate_root_action_transition(
        self,
        request: Mapping[str, Any],
        *,
        snapshot: _LedgerSnapshot,
        records: Sequence[Mapping[str, Any]],
    ) -> None:
        action = str(request["action"])
        attempt_id = request.get("attempt_id")
        if attempt_id is None:
            return
        attempt = snapshot.attempts[str(attempt_id)]
        planned_gate, planned_role, planned_kind = _FROZEN_ATTEMPTS[str(attempt_id)]
        if (
            attempt.gate_id != planned_gate
            or attempt.role != planned_role
            or attempt.kind != planned_kind
        ):
            raise BrokerError("root slot mirror differs from the frozen plan")
        if planned_kind != "real_runtime" and not (
            planned_kind == "non_runtime_conflict"
            and action in _NON_RUNTIME_CONFLICT_ACTIONS
        ):
            raise BrokerError("non-runtime conflict cannot cross the root boundary")
        if action == "docker_create" and not (
            planned_gate == "OOM" and planned_role == "target"
        ):
            raise BrokerError("Docker create is reserved for the OOM target")
        if action == "docker_start" and not (
            planned_gate == "OOM" and planned_role == "target"
        ):
            raise BrokerError("Docker start is reserved for the OOM target")
        if (
            action == "docker_run"
            and planned_gate == "OOM"
            and planned_role == "target"
        ):
            raise BrokerError("OOM target must use the held create/start lifecycle")
        completed_actions = [
            record["data"].get("action")
            for record in records
            if record["event"] == "action_completed"
            and record["data"].get("attempt_id") == attempt_id
        ]
        claimed_actions = [
            record["data"].get("action")
            for record in records
            if record["event"] == "action_claimed"
            and record["data"].get("attempt_id") == attempt_id
        ]
        if "docker_remove" in completed_actions and action in {
            "docker_run",
            "docker_create",
            "docker_start",
            "docker_restart",
            "signal_runtime",
            "signal_harness",
            "signal_supervisor",
        }:
            raise BrokerError("runtime mutation follows root-observed removal")
        if (
            any(
                terminal_action in completed_actions
                for terminal_action in ("abort_paused_harness", "stop_peer_harness")
            )
            and action not in _READ_ONLY_ACTIONS | {"docker_remove"}
            and not (
                action in {"abort_paused_harness", "stop_peer_harness"}
                and completed_actions.count(action) == 1
            )
        ):
            raise BrokerError("runtime mutation follows a root terminal signal")
        if attempt.completed and action not in _READ_ONLY_ACTIONS:
            raise BrokerError("runtime mutation follows durable attempt completion")
        if action == "docker_start" and "docker_create" not in claimed_actions:
            raise BrokerError("Docker start lacks the root-owned create transition")
        if action in {"resume_peer_harness", "resume_cohort_harness"} and not any(
            paused in completed_actions
            for paused in ("pause_peer_harness", "pause_cohort_harness")
        ):
            raise BrokerError("harness resume lacks a root-observed pause")
        if action == "stop_peer_harness" and not {
            "pause_peer_harness",
            "resume_peer_harness",
        }.issubset(set(completed_actions)):
            raise BrokerError("PORT-2 stop lacks its root pause/resume sequence")
        if action == "abort_paused_harness" and not any(
            paused in completed_actions
            for paused in ("pause_peer_harness", "pause_cohort_harness")
        ):
            raise BrokerError("failure unwind lacks a root-observed pause")

    def _ensure_root_evidence_directories(self) -> None:
        _validate_directory(
            self.layout.broker_root,
            owner_uid=self._trusted_uid,
        )
        for path in (
            self.layout.claim_root,
            self.layout.incoming_root,
            self.layout.grant_root,
            self.layout.receipt_root,
            self.layout.broker_state_root,
            self.layout.inflight_root,
        ):
            parent = path.parent
            _validate_directory(parent, owner_uid=self._trusted_uid)
            try:
                os.mkdir(path, mode=0o700)
            except FileExistsError:
                pass
            _validate_directory(
                path,
                owner_uid=self._trusted_uid,
                exact_mode=0o700,
            )
        batches = self.layout.root_evidence_root / "batches"
        _validate_directory(
            self.layout.root_evidence_root,
            owner_uid=self._trusted_uid,
            exact_mode=0o700,
        )
        try:
            os.mkdir(batches, mode=0o700)
        except FileExistsError:
            pass
        _validate_directory(
            batches,
            owner_uid=self._trusted_uid,
            exact_mode=0o700,
        )
        try:
            os.mkdir(self.layout.bind_source_root, mode=0o700)
        except FileExistsError:
            pass
        _validate_directory(
            self.layout.bind_source_root,
            owner_uid=self._trusted_uid,
            exact_mode=0o700,
        )

    def _verify_trusted_runtime(self) -> None:
        """Reject mutable/symlinked code before adding the repository to sys.path."""

        if self._trusted_runtime_verified:
            return

        roots = (self.layout.repo_root, self.layout.venv_python.parent.parent)
        for root in roots:
            if self._trusted_uid == 0:
                current = Path(root.anchor)
                for component in root.parts[1:]:
                    current /= component
                    try:
                        metadata = current.lstat()
                    except OSError as exc:
                        raise BrokerError(
                            "trusted runtime path is unavailable"
                        ) from exc
                    if (
                        stat.S_ISLNK(metadata.st_mode)
                        or metadata.st_uid != 0
                        or stat.S_IMODE(metadata.st_mode) & 0o022
                    ):
                        raise BrokerError(
                            "trusted runtime ancestry is mutable or linked"
                        )
        for path in (Path(__file__), self.layout.acceptance_path):
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise BrokerError("trusted runtime file is unavailable") from exc
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self._trusted_uid
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise BrokerError("trusted runtime file is mutable or linked")
        interpreter_link = self.layout.venv_python.lstat()
        interpreter = self.layout.venv_python.resolve(strict=True)
        interpreter_metadata = interpreter.stat()
        if (
            interpreter_link.st_uid != self._trusted_uid
            or stat.S_IMODE(interpreter_link.st_mode) & 0o022
            or not stat.S_ISREG(interpreter_metadata.st_mode)
            or interpreter_metadata.st_uid != self._trusted_uid
            or stat.S_IMODE(interpreter_metadata.st_mode) & 0o022
        ):
            raise BrokerError("trusted Python interpreter is mutable")
        if self._trusted_uid == 0 and sys.flags.isolated != 1:
            raise BrokerError("installed root broker requires Python isolated mode")
        if self._trusted_uid == 0:
            if (
                self.layout.repo_root != Path("/opt/fort-gym-m1a")
                or self.layout.state_root != Path("/var/lib/fortgym-m1b")
                or self.layout.venv_python != Path("/opt/fortgym-m1b/venv/bin/python")
                or self.layout.image_archive
                != Path("/opt/fortgym-m1b/runtime-image.tar.zst")
                or self.layout.root_evidence_root
                != Path("/var/lib/fortgym-m1b-root-evidence")
                or self.layout.packet_root != _CANONICAL_PACKET_ROOT
            ):
                raise BrokerError(
                    "installed broker layout differs from canonical paths"
                )
            evidence = _read_json(
                self.layout.trusted_paths_evidence,
                maximum=64 * 1024,
                owner_uid=0,
            )
            self._validate_trusted_paths_document(evidence)
            self._verify_bootstrap_attestations(evidence)
        self._trusted_runtime_verified = True

    @staticmethod
    def _validate_trusted_paths_document(evidence: Mapping[str, Any]) -> None:
        required_flags = {
            "source_root_owned_nonwritable",
            "venv_owned_nonwritable",
            "interpreter_owned_nonwritable",
            "site_packages_owned_nonwritable",
            "isolated_source_pth_exact",
            "broker_owned_nonwritable",
            "packet_metadata_root_owned_readable",
            "packet_archives_root_only",
            "broker_receipts_root_only",
            "docker_server_29_1_3_containerd_store",
            "runtime_archive_digest_exact",
            "provider_helper_bpf_attested",
        }
        digest_keys = {
            "docker_runtime_attestation_sha256",
            "runtime_archive_attestation_sha256",
            "provider_helper_bpf_attestation_sha256",
            "docker_image_descriptor_attestation_sha256",
        }
        expected = {"schema", "ok", *required_flags, *digest_keys}
        if (
            set(evidence) != expected
            or evidence.get("schema") != "fortgym.m1b-trusted-host-paths/v1"
            or evidence.get("ok") is not True
            or any(evidence.get(name) is not True for name in required_flags)
            or any(
                not _SHA256_RE.fullmatch(str(evidence.get(name) or ""))
                for name in digest_keys
            )
        ):
            raise BrokerError("trusted bootstrap path evidence differs")

    def _verify_bootstrap_attestations(
        self,
        trusted_paths: Mapping[str, Any],
    ) -> None:
        """Revalidate every root-owned bootstrap trust link for every request."""

        trusted_keys = {
            "schema",
            "ok",
            "source_root_owned_nonwritable",
            "venv_owned_nonwritable",
            "interpreter_owned_nonwritable",
            "site_packages_owned_nonwritable",
            "isolated_source_pth_exact",
            "broker_owned_nonwritable",
            "packet_metadata_root_owned_readable",
            "packet_archives_root_only",
            "broker_receipts_root_only",
            "docker_server_29_1_3_containerd_store",
            "runtime_archive_digest_exact",
            "provider_helper_bpf_attested",
            "docker_runtime_attestation_sha256",
            "runtime_archive_attestation_sha256",
            "provider_helper_bpf_attestation_sha256",
            "docker_image_descriptor_attestation_sha256",
        }
        self._validate_trusted_paths_document(trusted_paths)
        if set(trusted_paths) != trusted_keys:
            raise BrokerError("trusted bootstrap path key set differs")

        def root_json(
            name: str, *, maximum: int = 2 * 1024 * 1024
        ) -> tuple[dict[str, Any], str]:
            path = self.layout.root_evidence_root / name
            raw = _read_regular_nofollow(
                path,
                maximum=maximum,
                owner_uid=0,
                require_nlink_one=True,
                exact_mode=0o600,
            )
            return _parse_json_object(raw, label=name), _sha256_bytes(raw)

        docker, docker_sha = root_json("docker-runtime-attestation.json")
        archive, archive_sha = root_json("runtime-archive-attestation.json")
        provider, provider_sha = root_json("provider-helper-bpf-attestation.json")
        descriptor, descriptor_sha = root_json(
            "docker-image-descriptor-attestation.json"
        )
        expected_links = {
            "docker_runtime_attestation_sha256": docker_sha,
            "runtime_archive_attestation_sha256": archive_sha,
            "provider_helper_bpf_attestation_sha256": provider_sha,
            "docker_image_descriptor_attestation_sha256": descriptor_sha,
        }
        if any(
            trusted_paths.get(key) != value for key, value in expected_links.items()
        ):
            raise BrokerError("trusted path subordinate digest differs")

        docker_keys = {
            "schema",
            "ok",
            "docker_server_version",
            "containerd_version",
            "containerd_snapshotter_driver",
            "docker_server_29_1_3_containerd_store",
            "daemon_configured_before_first_start",
            "userland_proxy_disabled",
            "offline_packet_packages_only",
            "distro_docker_io_installed",
            "signed_repository_verified",
            "runtime_manifest_sha256",
            "installed_binaries",
        }
        if (
            set(docker) != docker_keys
            or docker.get("schema") != "fortgym.m1b-docker-runtime-attestation/v1"
            or docker.get("ok") is not True
            or docker.get("docker_server_version") != "29.1.3"
            or docker.get("containerd_version") != "2.2.1"
            or docker.get("containerd_snapshotter_driver")
            != "io.containerd.snapshotter.v1"
            or docker.get("docker_server_29_1_3_containerd_store") is not True
            or docker.get("daemon_configured_before_first_start") is not True
            or docker.get("userland_proxy_disabled") is not True
            or docker.get("offline_packet_packages_only") is not True
            or docker.get("distro_docker_io_installed") is not False
            or docker.get("signed_repository_verified") is not True
        ):
            raise BrokerError("Docker runtime attestation differs")
        binaries = docker.get("installed_binaries")
        if not isinstance(binaries, list) or len(binaries) != 8:
            raise BrokerError("Docker installed-binary attestation differs")
        expected_binary_paths = {
            "/usr/bin/containerd",
            "/usr/bin/containerd-shim-runc-v2",
            "/usr/bin/ctr",
            "/usr/bin/docker",
            "/usr/bin/docker-proxy",
            "/usr/bin/dockerd",
            "/usr/bin/runc",
            "/usr/libexec/docker/docker-init",
        }
        observed_binary_paths: set[str] = set()
        expected_binary_packages = {
            "/usr/bin/containerd": "containerd.io",
            "/usr/bin/containerd-shim-runc-v2": "containerd.io",
            "/usr/bin/ctr": "containerd.io",
            "/usr/bin/docker": "docker-ce-cli",
            "/usr/bin/docker-proxy": "docker-ce",
            "/usr/bin/dockerd": "docker-ce",
            "/usr/bin/runc": "containerd.io",
            "/usr/libexec/docker/docker-init": "docker-ce",
        }
        for item in binaries:
            if not isinstance(item, Mapping) or set(item) != {
                "architecture",
                "mode",
                "package",
                "path",
                "sha256",
                "size_bytes",
            }:
                raise BrokerError("Docker installed-binary record differs")
            path_value = item.get("path")
            if (
                path_value not in expected_binary_paths
                or path_value in observed_binary_paths
                or item.get("architecture") != "amd64"
                or item.get("mode") != "0755"
                or item.get("package") != expected_binary_packages.get(str(path_value))
                or not _SHA256_RE.fullmatch(str(item.get("sha256") or ""))
                or isinstance(item.get("size_bytes"), bool)
                or not isinstance(item.get("size_bytes"), int)
                or int(item["size_bytes"]) <= 0
            ):
                raise BrokerError("Docker installed-binary identity differs")
            observed_binary_paths.add(str(path_value))
            metadata = Path(str(path_value)).lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) != 0o755
                or metadata.st_size != item["size_bytes"]
                or _sha256_file(
                    Path(str(path_value)),
                    maximum=128 * 1024 * 1024,
                    owner_uid=0,
                )
                != item["sha256"]
            ):
                raise BrokerError("Docker installed-binary metadata drifted")
        if observed_binary_paths != expected_binary_paths:
            raise BrokerError("Docker installed-binary path set differs")

        archive_keys = {
            "schema",
            "ok",
            "path",
            "sha256",
            "size_bytes",
            "runtime_archive_digest_exact",
            "root_owned_mode_0600",
        }
        archive_metadata = self.layout.image_archive.lstat()
        if (
            set(archive) != archive_keys
            or archive.get("schema") != "fortgym.m1b-runtime-archive-attestation/v1"
            or archive.get("ok") is not True
            or archive.get("path") != str(self.layout.image_archive)
            or archive.get("sha256") != _RUNTIME_ARCHIVE_SHA256
            or archive.get("size_bytes") != archive_metadata.st_size
            or archive.get("runtime_archive_digest_exact") is not True
            or archive.get("root_owned_mode_0600") is not True
            or not stat.S_ISREG(archive_metadata.st_mode)
            or archive_metadata.st_uid != 0
            or stat.S_IMODE(archive_metadata.st_mode) != 0o600
            or _sha256_file(
                self.layout.image_archive,
                maximum=8 * 1024 * 1024 * 1024,
                owner_uid=0,
            )
            != _RUNTIME_ARCHIVE_SHA256
        ):
            raise BrokerError("runtime archive attestation differs")

        descriptor_expected = {
            "schema": "fortgym.m1b-docker-image-descriptor-attestation/v1",
            "ok": True,
            "image_reference": "fortgym-df:m1a-stock-0.47.05-r8",
            "image_id": f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}",
            "manifest_digest": f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}",
            "manifest_media_type": "application/vnd.oci.image.manifest.v1+json",
            "manifest_size_bytes": 2306,
            "config_digest": f"sha256:{_RUNTIME_IMAGE_CONFIG_SHA256}",
            "platform": "linux/amd64",
            "containerd_image_store_descriptor_attested": True,
        }
        if descriptor != descriptor_expected:
            raise BrokerError("Docker image descriptor attestation differs")

        provider_keys = {
            "schema",
            "ok",
            "provider_helper_bpf_attested",
            "source_tree_sha256",
            "source_manifest_sha256",
            "helper_path",
            "helper_sha256",
            "helper_mode",
            "bpf_object_path",
            "bpf_object_sha256",
            "bpf_object_mode",
            "reproducible_build_outputs_match",
            "installed_outputs_match_build",
            "root_owned_nonwritable_ancestry",
            "live_setuid_helper_exercised_as_nonroot",
            "kernel_bpf_load_attested",
            "cgroup_hooks_attached",
            "default_deny_negative_canary_attested",
            "negative_canary_event_count",
            "exact_loopback_allow_attested",
            "zero_lost_events",
            "cleanup_idempotent",
            "capability_probe_sha256",
            "prepare_sha256",
            "snapshot_sha256",
            "guard_attestation_sha256",
            "inner_allow_probe_sha256",
            "cleanup_sha256",
            "cleanup_idempotent_sha256",
        }
        required_true = {
            "ok",
            "provider_helper_bpf_attested",
            "reproducible_build_outputs_match",
            "installed_outputs_match_build",
            "root_owned_nonwritable_ancestry",
            "live_setuid_helper_exercised_as_nonroot",
            "kernel_bpf_load_attested",
            "cgroup_hooks_attached",
            "default_deny_negative_canary_attested",
            "exact_loopback_allow_attested",
            "zero_lost_events",
            "cleanup_idempotent",
        }
        if (
            set(provider) != provider_keys
            or provider.get("schema")
            != "fortgym.m1b-provider-helper-bpf-attestation/v1"
            or any(provider.get(name) is not True for name in required_true)
            or provider.get("negative_canary_event_count") != 6
            or provider.get("helper_path") != str(_CANONICAL_PROVIDER_HELPER)
            or provider.get("helper_mode") != "4750"
            or provider.get("bpf_object_path") != str(_CANONICAL_PROVIDER_BPF)
            or provider.get("bpf_object_mode") != "0644"
        ):
            raise BrokerError("provider helper/BPF attestation differs")
        for path, digest_key, mode in (
            (_CANONICAL_PROVIDER_HELPER, "helper_sha256", 0o4750),
            (_CANONICAL_PROVIDER_BPF, "bpf_object_sha256", 0o644),
        ):
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) != mode
                or _sha256_file(path, maximum=64 * 1024 * 1024, owner_uid=0)
                != provider.get(digest_key)
            ):
                raise BrokerError("provider installed artifact drifted")
        provider_links = {
            "capability_probe_sha256": "provider-capability-probe.json",
            "prepare_sha256": "provider-prepare.json",
            "snapshot_sha256": "provider-snapshot.json",
            "guard_attestation_sha256": "provider-bootstrap-guard.json",
            "inner_allow_probe_sha256": "provider-bootstrap-inner.json",
            "cleanup_sha256": "provider-cleanup.json",
            "cleanup_idempotent_sha256": "provider-cleanup-idempotent.json",
        }
        for digest_key, filename in provider_links.items():
            _document, digest = root_json(filename)
            if provider.get(digest_key) != digest:
                raise BrokerError("provider subordinate receipt digest differs")

        packet_raw = _read_regular_nofollow(
            self.layout.packet_manifest_path,
            maximum=2 * 1024 * 1024,
            owner_uid=0,
            require_nlink_one=True,
        )
        packet = _parse_json_object(packet_raw, label="PACKET.json")
        source_raw = _read_regular_nofollow(
            self.layout.source_manifest_path,
            maximum=16 * 1024 * 1024,
            owner_uid=0,
            require_nlink_one=True,
        )
        source = _parse_json_object(source_raw, label="source-manifest.json")
        runtime = packet.get("runtime_archive")
        packet_source = packet.get("source")
        authority = packet.get("authority")
        proto = packet.get("runtime_proto")
        packet_keys = {
            "schema",
            "authority",
            "acceptance_sha256",
            "source",
            "runtime_archive",
            "docker_runtime",
            "wheelhouse",
            "seed",
            "runtime_proto",
            "packet_build_tools",
        }
        authority_keys = {
            "provider_calls",
            "provider_cost_usd",
            "paid_models",
            "production_access",
            "production_mutation",
            "publish_deploy_push_tag_e1",
            "infrastructure_daily_ceiling_usd",
            "infrastructure_authorized_local_date",
            "infrastructure_authority_expires_at",
            "ephemeral_only",
        }
        source_keys = {
            "schema",
            "base_head",
            "branch",
            "file_count",
            "file_bytes",
            "tree_sha256",
            "files",
            "runtime_proto",
        }
        if (
            set(packet) != packet_keys
            or packet.get("schema") != "fortgym.m1b-live-input-packet/v1"
            or packet.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or not isinstance(authority, Mapping)
            or set(authority) != authority_keys
            or authority.get("publish_deploy_push_tag_e1") != "forbidden"
            or authority.get("infrastructure_daily_ceiling_usd") != 210
            or authority.get("infrastructure_authorized_local_date") != "2026-09-05"
            or authority.get("ephemeral_only") is not True
            or not isinstance(runtime, Mapping)
            or runtime.get("manifest_sha256") != _RUNTIME_IMAGE_MANIFEST_SHA256
            or runtime.get("config_sha256") != _RUNTIME_IMAGE_CONFIG_SHA256
            or runtime.get("compressed_sha256") != _RUNTIME_ARCHIVE_SHA256
            or not isinstance(packet_source, Mapping)
            or set(packet_source)
            != {"archive", "archive_sha256", "manifest", "tree_sha256", "extract_root"}
            or packet_source.get("archive") != "fortgym-m1b-source.tar"
            or packet_source.get("manifest") != "source-manifest.json"
            or packet_source.get("extract_root") != str(self.layout.repo_root)
            or not _SHA256_RE.fullmatch(str(packet_source.get("archive_sha256") or ""))
            or packet_source.get("tree_sha256") != source.get("tree_sha256")
            or set(source) != source_keys
            or source.get("schema") != "fortgym.m1b-live-source-manifest/v1"
            or not _SHA256_RE.fullmatch(str(source.get("tree_sha256") or ""))
            or authority.get("provider_calls") != 0
            or authority.get("provider_cost_usd") != 0
            or authority.get("paid_models") != "forbidden"
            or authority.get("production_access") != "forbidden"
            or authority.get("production_mutation") != "forbidden"
            or authority.get("infrastructure_authority_expires_at")
            != "2026-09-06T12:00:00Z"
            or not isinstance(proto, Mapping)
            or proto.get("runtime_binding_sha256") != _RUNTIME_BINDING_SHA256
            or provider.get("source_tree_sha256") != source.get("tree_sha256")
            or provider.get("source_manifest_sha256") != _sha256_bytes(source_raw)
        ):
            raise BrokerError("root packet authority or runtime pins differ")
        self._verify_installed_source_manifest(source)
        docker_manifest_path = self.layout.packet_root / "docker-runtime-manifest.json"
        if docker.get("runtime_manifest_sha256") != _sha256_file(
            docker_manifest_path,
            maximum=2 * 1024 * 1024,
            owner_uid=0,
        ):
            raise BrokerError("Docker runtime manifest attestation differs")

        nonroot, _nonroot_sha = root_json("nonroot-isolated-import.json")
        nonroot_keys = {
            "schema",
            "ok",
            "effective_uid_nonzero",
            "python_isolated",
            "source_root",
            "package_file",
            "source_pth",
            "source_pth_sha256",
            "runtime_binding_sha256",
            "measurement_code_sha256",
            "provider_environment_present",
        }
        if (
            set(nonroot) != nonroot_keys
            or nonroot.get("schema") != "fortgym.m1b-nonroot-isolated-import/v1"
            or nonroot.get("ok") is not True
            or nonroot.get("effective_uid_nonzero") is not True
            or nonroot.get("python_isolated") is not True
            or nonroot.get("source_root") != str(self.layout.repo_root)
            or nonroot.get("package_file")
            != str(self.layout.repo_root / "fort_gym" / "__init__.py")
            or nonroot.get("source_pth")
            != "/opt/fortgym-m1b/venv/lib/python3.11/site-packages/fortgym-m1b-source.pth"
            or not _SHA256_RE.fullmatch(str(nonroot.get("source_pth_sha256") or ""))
            or nonroot.get("runtime_binding_sha256") != _RUNTIME_BINDING_SHA256
            or nonroot.get("provider_environment_present") is not False
            or not _SHA256_RE.fullmatch(
                str(nonroot.get("measurement_code_sha256") or "")
            )
        ):
            raise BrokerError("nonroot isolated-import attestation differs")

        bootstrap, _bootstrap_sha = root_json("bootstrap.json")
        bootstrap_keys = {
            "schema",
            "ok",
            "acceptance_sha256",
            "authority_expires_at",
            "bootstrap_completed_at",
            "manifest_sha256_out_of_band",
            "packet_copied_to_root_staging",
            "runtime_archive_path",
            "runtime_image_id",
            "runtime_image_manifest_digest",
            "runtime_image_manifest_media_type",
            "runtime_image_manifest_size_bytes",
            "safe_archive_preflight_completed",
            "docker_runtime_manifest_sha256",
            "docker_runtime_attestation_sha256",
            "runtime_archive_attestation_sha256",
            "provider_helper_bpf_attestation_sha256",
            "docker_image_descriptor_attestation_sha256",
            "trusted_paths_sha256",
            "docker_server_version",
            "containerd_version",
            "docker_server_29_1_3_containerd_store",
            "runtime_archive_digest_exact",
            "provider_helper_bpf_attested",
            "containerd_image_store_descriptor_attested",
            "docker_install_mode",
            "distro_docker_io_installed",
            "daemon_configured_before_first_start",
            "docker_userland_proxy_disabled",
            "root_broker_sha256",
            "root_broker_is_only_sudo_target",
            "service_user_in_docker_group",
            "expiry_timer_next_elapse",
            "python_major_minor",
            "dependency_install_mode",
            "dependency_waivers",
            "source_pth_path",
            "source_pth_sha256",
            "nonroot_isolated_import_ok",
            "nonroot_measurement_code_digest_ok",
            "measurement_code_sha256",
            "source_path_preserves_repo_file",
            "root_evidence_private",
            "provider_calls",
            "provider_cost_usd",
        }
        bootstrap_links = {
            "docker_runtime_attestation_sha256": docker_sha,
            "runtime_archive_attestation_sha256": archive_sha,
            "provider_helper_bpf_attestation_sha256": provider_sha,
            "docker_image_descriptor_attestation_sha256": descriptor_sha,
            "trusted_paths_sha256": _sha256_file(
                self.layout.trusted_paths_evidence,
                maximum=64 * 1024,
                owner_uid=0,
            ),
        }
        if (
            set(bootstrap) != bootstrap_keys
            or bootstrap.get("schema") != "fortgym.m1b-live-host-bootstrap/v1"
            or bootstrap.get("ok") is not True
            or bootstrap.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or bootstrap.get("runtime_archive_path") != str(self.layout.image_archive)
            or bootstrap.get("authority_expires_at") != "2026-09-06T12:00:00Z"
            or bootstrap.get("packet_copied_to_root_staging") is not True
            or bootstrap.get("safe_archive_preflight_completed") is not True
            or bootstrap.get("runtime_image_id")
            != f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}"
            or bootstrap.get("docker_server_version") != "29.1.3"
            or bootstrap.get("containerd_version") != "2.2.1"
            or bootstrap.get("docker_server_29_1_3_containerd_store") is not True
            or bootstrap.get("runtime_archive_digest_exact") is not True
            or bootstrap.get("provider_helper_bpf_attested") is not True
            or bootstrap.get("containerd_image_store_descriptor_attested") is not True
            or bootstrap.get("docker_install_mode")
            != "offline-packet-bound-docker-ce-debs"
            or bootstrap.get("distro_docker_io_installed") is not False
            or bootstrap.get("docker_userland_proxy_disabled") is not True
            or bootstrap.get("root_broker_is_only_sudo_target") is not True
            or bootstrap.get("service_user_in_docker_group") is not False
            or bootstrap.get("python_major_minor") != "3.11"
            or bootstrap.get("dependency_waivers") is not False
            or bootstrap.get("dependency_install_mode")
            != "python3.11-venv-offline-pinned-wheels"
            or bootstrap.get("source_pth_path") != nonroot.get("source_pth")
            or bootstrap.get("source_pth_sha256") != nonroot.get("source_pth_sha256")
            or bootstrap.get("nonroot_isolated_import_ok") is not True
            or bootstrap.get("nonroot_measurement_code_digest_ok") is not True
            or bootstrap.get("source_path_preserves_repo_file") is not True
            or bootstrap.get("root_evidence_private") is not True
            or bootstrap.get("measurement_code_sha256")
            != nonroot.get("measurement_code_sha256")
            or bootstrap.get("provider_calls") != 0
            or bootstrap.get("provider_cost_usd") != 0
            or any(
                bootstrap.get(key) != value for key, value in bootstrap_links.items()
            )
            or bootstrap.get("root_broker_sha256")
            != _sha256_file(Path(__file__), maximum=1024 * 1024, owner_uid=0)
        ):
            raise BrokerError("bootstrap receipt trust chain differs")
        self._measurement_code_sha256 = str(nonroot["measurement_code_sha256"])

    def _verify_installed_source_manifest(
        self,
        source: Mapping[str, Any],
    ) -> None:
        files = source.get("files")
        runtime_proto = source.get("runtime_proto")
        if (
            source.get("base_head") != "236d3187c548b9bc03c4c99829d479d381a008d5"
            or not isinstance(source.get("branch"), str)
            or not source["branch"]
            or not isinstance(files, list)
            or not files
            or len(files) > 8192
            or not isinstance(runtime_proto, Mapping)
            or set(runtime_proto) != {"canonical_runtime", "wire_reference"}
            or not all(isinstance(value, Mapping) for value in runtime_proto.values())
            or runtime_proto["canonical_runtime"].get("runtime_binding_sha256")
            != _RUNTIME_BINDING_SHA256
        ):
            raise BrokerError("source manifest metadata differs")
        normalized: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        seen_directories: set[Path] = set()
        total_bytes = 0
        for item in files:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"path", "sha256", "size_bytes", "mode"}
                or not isinstance(item.get("path"), str)
                or not _SHA256_RE.fullmatch(str(item.get("sha256") or ""))
                or isinstance(item.get("size_bytes"), bool)
                or not isinstance(item.get("size_bytes"), int)
                or int(item["size_bytes"]) < 0
                or item.get("mode") not in {"0644", "0755"}
            ):
                raise BrokerError("source manifest file record differs")
            relative = str(item["path"])
            relative_path = Path(relative)
            if (
                relative_path.is_absolute()
                or relative in {"", "."}
                or ".." in relative_path.parts
                or "\0" in relative
                or relative in seen_paths
            ):
                raise BrokerError("source manifest path is unsafe or duplicated")
            seen_paths.add(relative)
            path = self.layout.repo_root / relative_path
            for directory in (path.parent, *path.parent.parents):
                if directory == self.layout.repo_root.parent:
                    break
                if directory in seen_directories:
                    continue
                metadata = directory.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != self._trusted_uid
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                ):
                    raise BrokerError("installed source directory is mutable or linked")
                seen_directories.add(directory)
                if directory == self.layout.repo_root:
                    break
            metadata = path.lstat()
            expected_mode = int(str(item["mode"]), 8)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self._trusted_uid
                or stat.S_IMODE(metadata.st_mode) != expected_mode
                or metadata.st_size != item["size_bytes"]
                or _sha256_file(
                    path,
                    maximum=64 * 1024 * 1024,
                    owner_uid=self._trusted_uid,
                    allow_empty=True,
                )
                != item["sha256"]
            ):
                raise BrokerError("installed source file differs from root manifest")
            total_bytes += int(item["size_bytes"])
            normalized.append(dict(item))
        paths = [item["path"] for item in normalized]
        if (
            paths != sorted(paths, key=lambda value: str(value).encode("utf-8"))
            or source.get("file_count") != len(normalized)
            or source.get("file_bytes") != total_bytes
            or source.get("tree_sha256") != _sha256_bytes(_canonical_bytes(normalized))
        ):
            raise BrokerError("source manifest aggregate differs")

    def _claim_request(self, path: Path, *, caller_uid: int) -> tuple[Path, bytes]:
        candidate = validate_request_path(
            path,
            layout=self.layout,
            caller_uid=caller_uid,
        )
        request_dir_fd = os.open(
            self.layout.request_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        incoming_dir_fd = os.open(
            self.layout.incoming_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        request_fd = -1
        linked_name = f".{candidate.stem}.untrusted"
        try:
            # Create a no-replace hard link in the root-only incoming directory,
            # then remove the caller-visible name.  Unlike rename(2), link(2)
            # cannot replace a crash remnant with the same request identity.
            os.link(
                candidate.name,
                linked_name,
                src_dir_fd=request_dir_fd,
                dst_dir_fd=incoming_dir_fd,
                follow_symlinks=False,
            )
            os.unlink(candidate.name, dir_fd=request_dir_fd)
            os.fsync(request_dir_fd)
            os.fsync(incoming_dir_fd)
            request_fd = os.open(
                linked_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=incoming_dir_fd,
            )
            before = os.fstat(request_fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != caller_uid
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
                or before.st_size <= 0
                or before.st_size > _MAX_REQUEST_BYTES
            ):
                raise BrokerError("request file ownership or mode is invalid")
            os.fchown(request_fd, self._trusted_uid, -1)
            os.fchmod(request_fd, 0o600)
            os.fsync(request_fd)
            stable = os.fstat(request_fd)
            if (
                stable.st_dev != before.st_dev
                or stable.st_ino != before.st_ino
                or stable.st_size != before.st_size
                or stable.st_uid != self._trusted_uid
                or stat.S_IMODE(stable.st_mode) != 0o600
                or stable.st_nlink != 1
            ):
                raise BrokerError("request inode changed while it was claimed")
            raw = _read_fd_bounded(request_fd, maximum=_MAX_REQUEST_BYTES)
            after = os.fstat(request_fd)
            if (
                stable.st_dev,
                stable.st_ino,
                stable.st_size,
                stable.st_mtime_ns,
                stable.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise BrokerError("request changed during its atomic claim")
            frozen = self.layout.incoming_root / f"{candidate.stem}.json"
            _write_bytes_once(frozen, raw, owner_uid=self._trusted_uid)
            os.unlink(linked_name, dir_fd=incoming_dir_fd)
            os.fsync(incoming_dir_fd)
            return candidate, raw
        except FileExistsError as exc:
            raise BrokerError("request identity was already consumed") from exc
        finally:
            if request_fd >= 0:
                os.close(request_fd)
            os.close(incoming_dir_fd)
            os.close(request_dir_fd)

    def _ledger_records(
        self,
        path: Path,
        *,
        schema: str,
        batch_id: str,
        caller_uid: int,
    ) -> list[dict[str, Any]]:
        raw = _read_regular_nofollow(
            path,
            maximum=_MAX_LEDGER_BYTES,
            owner_uid=caller_uid,
        )
        return self._decode_ledger_records(
            raw,
            schema=schema,
            batch_id=batch_id,
        )

    def _decode_ledger_records(
        self,
        raw: bytes,
        *,
        schema: str,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        if not raw and schema == "fortgym.m1b-live-acceptance-attempt-ledger/v1":
            return []
        if not raw.endswith(b"\n"):
            raise BrokerError("acceptance ledger lacks its terminal newline")
        lines = raw.splitlines()
        if not lines or len(lines) > _MAX_LEDGER_RECORDS:
            raise BrokerError("acceptance ledger record count is invalid")
        records: list[dict[str, Any]] = []
        previous = _ZERO_SHA256
        expected_keys = {
            "schema",
            "batch_id",
            "acceptance_sha256",
            "plan_sha256",
            "sequence",
            "previous_record_sha256",
            "at",
            "event",
            "payload",
            "record_sha256",
        }
        for sequence, line in enumerate(lines, start=1):
            if not line or len(line) > 128 * 1024:
                raise BrokerError("acceptance ledger record size is invalid")
            record = _parse_json_object(line, label="acceptance ledger record")
            hash_input = dict(record)
            claimed = hash_input.pop("record_sha256", None)
            if (
                set(record) != expected_keys
                or record.get("schema") != schema
                or record.get("batch_id") != batch_id
                or record.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
                or record.get("plan_sha256") != FROZEN_PLAN_SHA256
                or record.get("sequence") != sequence
                or record.get("previous_record_sha256") != previous
                or not isinstance(record.get("at"), str)
                or not isinstance(record.get("event"), str)
                or not isinstance(record.get("payload"), dict)
                or not isinstance(claimed, str)
                or not _SHA256_RE.fullmatch(claimed)
                or _sha256_bytes(_canonical_bytes(hash_input)) != claimed
            ):
                raise BrokerError("acceptance ledger identity or hash chain differs")
            records.append(record)
            previous = claimed
        return records

    def _batch_phase(
        self,
        records: Sequence[Mapping[str, Any]],
    ) -> _BatchPhase:
        active_gate: str | None = None
        cleanup_scope: str | None = None
        cleanup_gate_id: str | None = None
        finalized = False
        gate_start_heads: dict[str, str] = {}
        for index, record in enumerate(records):
            event = record["event"]
            payload = record["payload"]
            if index == 0 and event != "batch_opened":
                raise BrokerError("acceptance batch is not opened")
            if finalized:
                raise BrokerError("acceptance ledger continues after finalization")
            if event == "gate_started":
                gate = payload.get("gate")
                gate_id = gate.get("id") if isinstance(gate, Mapping) else None
                if (
                    active_gate is not None
                    or cleanup_scope is not None
                    or not isinstance(gate_id, str)
                ):
                    raise BrokerError("acceptance gate phase is invalid")
                active_gate = gate_id
                gate_start_heads[gate_id] = str(record["record_sha256"])
            elif event == "gate_completed":
                gate = payload.get("gate")
                gate_id = gate.get("id") if isinstance(gate, Mapping) else None
                if gate_id != active_gate:
                    raise BrokerError("acceptance gate completion differs")
                active_gate = None
            elif event == "cleanup_started":
                if active_gate is not None or cleanup_scope is not None:
                    raise BrokerError("acceptance cleanup phase overlaps another phase")
                scope = payload.get("scope")
                gate_id = payload.get("gate_id")
                if scope not in {"gate", "batch"}:
                    raise BrokerError("acceptance cleanup scope is invalid")
                cleanup_scope = str(scope)
                cleanup_gate_id = str(gate_id) if gate_id is not None else None
            elif event == "cleanup_completed":
                if (
                    payload.get("scope") != cleanup_scope
                    or payload.get("gate_id") != cleanup_gate_id
                ):
                    raise BrokerError("acceptance cleanup completion differs")
                cleanup_scope = None
                cleanup_gate_id = None
            elif event == "batch_finalized":
                if active_gate is not None or cleanup_scope is not None:
                    raise BrokerError("acceptance finalized during an active phase")
                finalized = True
        return _BatchPhase(
            active_gate=active_gate,
            cleanup_scope=cleanup_scope,
            cleanup_gate_id=cleanup_gate_id,
            batch_head_sha256=str(records[-1]["record_sha256"]),
            gate_start_heads=gate_start_heads,
            finalized=finalized,
        )

    def _strict_ledger_snapshot(
        self,
        request: Mapping[str, Any],
        *,
        caller_uid: int,
    ) -> _LedgerSnapshot:
        """Replay both caller ledgers against the independently frozen plan."""

        batch_id = str(request["batch_id"])
        root = self.layout.batch_evidence_root(batch_id) / "control"
        batch_path = root / "batch-ledger.jsonl"
        attempt_path = root / "attempt-ledger.jsonl"
        if (
            request.get("grant_kind") == "batch_canary"
            and request.get("gate_id") == "BATCH-CANARY"
            and request.get("action") in {"canary_create", "canary_inspect"}
            and not batch_path.exists()
            and not attempt_path.exists()
        ):
            attempts = self._strict_attempt_replay(())
            return _LedgerSnapshot(
                batch_records=(),
                attempt_records=(),
                phase=_BatchPhase(
                    active_gate=None,
                    cleanup_scope=None,
                    cleanup_gate_id=None,
                    batch_head_sha256=_ZERO_SHA256,
                    gate_start_heads={},
                    finalized=False,
                ),
                attempts=attempts,
                batch_file_sha256=_ZERO_SHA256,
                attempt_file_sha256=_ZERO_SHA256,
            )
        batch_raw = _read_regular_nofollow(
            batch_path,
            maximum=_MAX_LEDGER_BYTES,
            owner_uid=caller_uid,
        )
        attempt_raw = _read_regular_nofollow(
            attempt_path,
            maximum=_MAX_LEDGER_BYTES,
            owner_uid=caller_uid,
            allow_empty=True,
        )
        batch_records = self._decode_ledger_records(
            batch_raw,
            schema="fortgym.m1b-live-acceptance-batch-ledger/v1",
            batch_id=batch_id,
        )
        attempt_records = self._decode_ledger_records(
            attempt_raw,
            schema="fortgym.m1b-live-acceptance-attempt-ledger/v1",
            batch_id=batch_id,
        )
        attempts = self._strict_attempt_replay(attempt_records)
        phase = self._strict_batch_replay(
            batch_records,
            attempt_records=attempt_records,
            attempts=attempts,
        )
        for record in attempt_records:
            if record["event"] != "attempt_started":
                continue
            gate_id = str(record["payload"]["gate_id"])
            if record["payload"].get(
                "batch_ledger_head_sha256"
            ) != phase.gate_start_heads.get(gate_id):
                raise BrokerError("attempt start is not crosslinked to its gate start")
        requested_attempt = request.get("attempt_id")
        if requested_attempt is not None:
            mirror = attempts.get(str(requested_attempt))
            if mirror is None or mirror.identity_sha256 is None:
                raise BrokerError("broker request lacks a frozen durable attempt start")
            request_gate = request.get("gate_id")
            cleanup_read = (
                request_gate == "CLEANUP"
                and request.get("action") in _READ_ONLY_ACTIONS
                and phase.cleanup_scope == "batch"
            )
            if (
                request_gate != mirror.gate_id and not cleanup_read
            ) or mirror.identity_sha256 != request.get("attempt_identity_sha256"):
                raise BrokerError("broker request differs from the frozen slot mirror")
            if mirror.kind != "real_runtime" and not (
                mirror.kind == "non_runtime_conflict"
                and request.get("action") in _NON_RUNTIME_CONFLICT_ACTIONS
            ):
                raise BrokerError("non-runtime conflict cannot authorize runtime work")
        return _LedgerSnapshot(
            batch_records=tuple(batch_records),
            attempt_records=tuple(attempt_records),
            phase=phase,
            attempts=attempts,
            batch_file_sha256=_sha256_bytes(batch_raw),
            attempt_file_sha256=_sha256_bytes(attempt_raw),
        )

    def _strict_attempt_replay(
        self,
        records: Sequence[Mapping[str, Any]],
    ) -> dict[str, _AttemptMirror]:
        mutable: dict[str, dict[str, Any]] = {
            attempt_id: {
                "attempt_id": attempt_id,
                "gate_id": values[0],
                "role": values[1],
                "kind": values[2],
                "identity_sha256": None,
                "completed": False,
                "authorization_bound": False,
            }
            for attempt_id, values in _FROZEN_ATTEMPTS.items()
        }
        observed_identities: set[str] = set()
        last_gate_position = -1
        for record in records:
            event = record["event"]
            payload = record["payload"]
            attempt_id = payload.get("attempt_id")
            if attempt_id not in mutable:
                raise BrokerError("attempt ledger names a non-frozen slot")
            state = mutable[str(attempt_id)]
            if payload.get("gate_id") != state["gate_id"]:
                raise BrokerError("attempt ledger gate binding differs")
            gate_position = _FROZEN_GATE_ORDER.index(str(state["gate_id"]))
            if gate_position < last_gate_position:
                raise BrokerError("attempt records interleave across frozen gates")
            last_gate_position = gate_position
            if event == "attempt_started":
                expected = {
                    "gate_id",
                    "attempt_id",
                    "kind",
                    "role",
                    "identity_sha256",
                    "batch_ledger_head_sha256",
                }
                if (
                    set(payload) != expected
                    or state["identity_sha256"] is not None
                    or payload.get("kind") != state["kind"]
                    or payload.get("role") != state["role"]
                    or not _SHA256_RE.fullmatch(
                        str(payload.get("identity_sha256") or "")
                    )
                    or not _SHA256_RE.fullmatch(
                        str(payload.get("batch_ledger_head_sha256") or "")
                    )
                ):
                    raise BrokerError("attempt start is not one exact frozen slot")
                identity_sha256 = str(payload["identity_sha256"])
                if identity_sha256 in observed_identities:
                    raise BrokerError("attempt launch identity is reused across slots")
                state["identity_sha256"] = identity_sha256
                observed_identities.add(identity_sha256)
            elif event == "private_authorization_bound":
                if (
                    set(payload)
                    != {
                        "gate_id",
                        "attempt_id",
                        "authorization_identity_sha256",
                    }
                    or state["gate_id"] != "ENOSPC"
                    or state["role"] != "target"
                    or state["identity_sha256"] is None
                    or state["completed"]
                    or state["authorization_bound"]
                    or not _SHA256_RE.fullmatch(
                        str(payload.get("authorization_identity_sha256") or "")
                    )
                ):
                    raise BrokerError("private attempt authorization differs")
                state["authorization_bound"] = True
            elif event == "attempt_completed":
                evidence = payload.get("evidence")
                if (
                    set(payload)
                    != {"gate_id", "attempt_id", "outcome_code", "evidence"}
                    or state["identity_sha256"] is None
                    or state["completed"]
                    or not isinstance(payload.get("outcome_code"), str)
                    or not _ID_RE.fullmatch(str(payload["outcome_code"]))
                    or not isinstance(evidence, list)
                    or not evidence
                    or (
                        state["gate_id"] == "ENOSPC"
                        and state["role"] == "target"
                        and not state["authorization_bound"]
                    )
                ):
                    raise BrokerError("attempt completion is noncanonical")
                state["completed"] = True
            else:
                raise BrokerError("attempt ledger contains an unknown event")
        real_started = sum(
            item["kind"] == "real_runtime" and item["identity_sha256"] is not None
            for item in mutable.values()
        )
        nonruntime_started = sum(
            item["kind"] == "non_runtime_conflict"
            and item["identity_sha256"] is not None
            for item in mutable.values()
        )
        if real_started > 26 or nonruntime_started > 1:
            raise BrokerError("attempt ledger exceeds the frozen slot budget")
        return {
            key: _AttemptMirror(
                attempt_id=key,
                gate_id=str(value["gate_id"]),
                role=str(value["role"]),
                kind=str(value["kind"]),
                identity_sha256=(
                    str(value["identity_sha256"])
                    if value["identity_sha256"] is not None
                    else None
                ),
                completed=bool(value["completed"]),
            )
            for key, value in mutable.items()
        }

    def _strict_batch_replay(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        attempt_records: Sequence[Mapping[str, Any]],
        attempts: Mapping[str, _AttemptMirror],
    ) -> _BatchPhase:
        self._install_repo_import_path()
        from fort_gym.bench.run.live_acceptance import FROZEN_GATE_PLAN

        frozen_payloads = {
            gate.gate_id: gate.payload(gate_index=index)
            for index, gate in enumerate(FROZEN_GATE_PLAN, start=1)
        }
        frozen_plan = {
            "schema": "fortgym.m1b-live-acceptance-plan/v1",
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "max_real_runtime_attempts": 26,
            "required_cleanup_passes": 2,
            "gates": [frozen_payloads[gate_id] for gate_id in _FROZEN_GATE_ORDER],
        }
        local_credit_scopes = {
            "PORT-1": "complete_local_gate",
            "ORPHAN-1": "local_subprocedure",
            "PROVIDER-ENV": "complete_local_gate",
            "CAP-FAKE": "complete_local_gate",
        }
        local_credit_order = tuple(local_credit_scopes)

        def valid_references(value: Any, *, required: bool) -> bool:
            if not isinstance(value, list) or (required and not value):
                return False
            paths: list[str] = []
            for reference in value:
                if (
                    not isinstance(reference, Mapping)
                    or set(reference) != {"path", "sha256", "size_bytes"}
                    or not isinstance(reference.get("path"), str)
                    or not _SHA256_RE.fullmatch(str(reference.get("sha256") or ""))
                    or isinstance(reference.get("size_bytes"), bool)
                    or not isinstance(reference.get("size_bytes"), int)
                    or int(reference["size_bytes"]) < 0
                ):
                    return False
                relative = str(reference["path"])
                parsed = Path(relative)
                if (
                    relative in {"", "."}
                    or parsed.is_absolute()
                    or ".." in parsed.parts
                    or "\0" in relative
                ):
                    return False
                paths.append(relative)
            # LiveAcceptanceBatchController preserves the adapter's evidence
            # order while requiring unique paths.  That order is part of the
            # hash-chained record; the broker must replay it rather than
            # inventing a second lexicographic canonicalization.  In
            # particular, cleanup records intentionally bind the cleanup
            # receipt before the protected-canary receipt.
            return len(paths) == len(set(paths))

        def valid_criteria(value: Any, expected: Sequence[str]) -> bool:
            return (
                isinstance(value, list)
                and all(isinstance(item, str) for item in value)
                and len(value) == len(set(value))
                and value == [item for item in expected if item in set(value)]
            )

        substantive = _FROZEN_GATE_ORDER[:-1]
        opened = False
        finalized = False
        active_gate: str | None = None
        cleanup_scope: str | None = None
        cleanup_gate_id: str | None = None
        completed_gates: list[str] = []
        cleaned_gates: list[str] = []
        cleanup_passes: list[dict[str, Any]] = []
        gate_start_heads: dict[str, str] = {}
        cleanup_gate_seen = False
        batch_cleanup_completed = False
        last_attempt_head = _ZERO_SHA256
        attempt_first_previous: dict[str, str] = {}
        attempt_last_head: dict[str, str] = {}
        imported_local_credits: list[str] = []
        imported_credit_payloads: dict[str, dict[str, Any]] = {}
        for attempt_record in attempt_records:
            gate_id = str(attempt_record["payload"]["gate_id"])
            attempt_first_previous.setdefault(
                gate_id,
                str(attempt_record["previous_record_sha256"]),
            )
            attempt_last_head[gate_id] = str(attempt_record["record_sha256"])
        for record in records:
            event = str(record["event"])
            payload = record["payload"]
            if finalized:
                raise BrokerError("batch ledger continues after finalization")
            if event == "batch_opened":
                source_reference = payload.get("source_manifest")
                batch_id = str(record["batch_id"])
                source_copy = (
                    self.layout.batch_evidence_root(batch_id)
                    / "inputs"
                    / "source-manifest.json"
                )
                source_copy_metadata = source_copy.lstat()
                source_copy_sha256 = _sha256_file(
                    source_copy,
                    maximum=16 * 1024 * 1024,
                    owner_uid=self._evidence_owner_uid,
                )
                packet_source_sha256 = _sha256_file(
                    self.layout.source_manifest_path,
                    maximum=16 * 1024 * 1024,
                    owner_uid=self._trusted_uid,
                )
                if (
                    opened
                    or record["sequence"] != 1
                    or set(payload)
                    != {
                        "plan",
                        "plan_sha256",
                        "source_manifest",
                        "local_credit_boundaries",
                    }
                    or payload.get("plan") != frozen_plan
                    or payload.get("plan_sha256") != FROZEN_PLAN_SHA256
                    or payload.get("local_credit_boundaries") != local_credit_scopes
                    or not isinstance(source_reference, Mapping)
                    or set(source_reference) != {"path", "sha256", "size_bytes"}
                    or source_reference.get("path") != "inputs/source-manifest.json"
                    or source_reference.get("sha256") != source_copy_sha256
                    or source_copy_sha256 != packet_source_sha256
                    or source_reference.get("size_bytes")
                    != source_copy_metadata.st_size
                ):
                    raise BrokerError("batch opening is duplicated or displaced")
                opened = True
                continue
            if not opened:
                raise BrokerError("batch event precedes its opening")
            if event == "local_credit_imported":
                gate_id = str(payload.get("gate_id") or "")
                gate_plan = next(
                    (gate for gate in FROZEN_GATE_PLAN if gate.gate_id == gate_id),
                    None,
                )
                evidence = payload.get("evidence")
                if (
                    active_gate is not None
                    or completed_gates
                    or set(payload)
                    != {"gate_id", "scope", "criteria_passed", "evidence"}
                    or len(imported_local_credits) >= len(local_credit_order)
                    or gate_id != local_credit_order[len(imported_local_credits)]
                    or payload.get("scope") != local_credit_scopes.get(gate_id)
                    or gate_plan is None
                    or payload.get("criteria_passed") != list(gate_plan.criteria)
                    or not isinstance(evidence, list)
                    or not evidence
                    or not valid_references(evidence, required=True)
                ):
                    raise BrokerError("local credit follows gate execution")
                imported_local_credits.append(gate_id)
                imported_credit_payloads[gate_id] = dict(payload)
                continue
            if event == "gate_started":
                expected_index = len(completed_gates)
                gate = payload.get("gate")
                gate_id = gate.get("id") if isinstance(gate, Mapping) else None
                if (
                    active_gate is not None
                    or cleanup_scope is not None
                    or tuple(imported_local_credits) != local_credit_order
                    or expected_index >= len(substantive)
                    or gate_id != substantive[expected_index]
                    or dict(gate) != frozen_payloads.get(str(gate_id))
                    or set(payload) != {"gate", "attempt_ledger_head_sha256"}
                    or payload.get("attempt_ledger_head_sha256") != last_attempt_head
                    or (
                        str(gate_id) in attempt_first_previous
                        and attempt_first_previous[str(gate_id)] != last_attempt_head
                    )
                    or (completed_gates and completed_gates[-1] not in cleaned_gates)
                ):
                    raise BrokerError("batch gate start differs from frozen order")
                active_gate = str(gate_id)
                gate_start_heads[active_gate] = str(record["record_sha256"])
                continue
            if event == "gate_completed":
                gate = payload.get("gate")
                gate_id = gate.get("id") if isinstance(gate, Mapping) else None
                expected_result_keys = {
                    "gate",
                    "status",
                    "criteria_passed",
                    "failure_code",
                    "evidence",
                    "local_credit",
                    "attempts",
                    "authorization_identity_sha256",
                    "attempt_ledger_head_sha256",
                }
                if (
                    gate_id != active_gate
                    or set(payload) != expected_result_keys
                    or dict(gate) != frozen_payloads.get(str(gate_id))
                    or payload.get("status") not in {"PASS", "PASS_LOCAL", "FAIL"}
                    or not isinstance(payload.get("criteria_passed"), list)
                    or not isinstance(payload.get("evidence"), list)
                    or not isinstance(payload.get("attempts"), Mapping)
                ):
                    raise BrokerError("batch gate completion differs")
                gate_attempts = [
                    item for item in attempts.values() if item.gate_id == active_gate
                ]
                gate_plan = next(
                    item for item in FROZEN_GATE_PLAN if item.gate_id == gate_id
                )
                attempt_summary = payload.get("attempts")
                expected_summary = {
                    "planned": len(gate_attempts),
                    "started": sum(
                        item.identity_sha256 is not None for item in gate_attempts
                    ),
                    "completed": sum(item.completed for item in gate_attempts),
                    "real_runtime_started": sum(
                        item.kind == "real_runtime" and item.identity_sha256 is not None
                        for item in gate_attempts
                    ),
                    "real_runtime_completed": sum(
                        item.kind == "real_runtime" and item.completed
                        for item in gate_attempts
                    ),
                    "non_runtime_started": sum(
                        item.kind == "non_runtime_conflict"
                        and item.identity_sha256 is not None
                        for item in gate_attempts
                    ),
                    "non_runtime_completed": sum(
                        item.kind == "non_runtime_conflict" and item.completed
                        for item in gate_attempts
                    ),
                }
                if dict(attempt_summary) != expected_summary:
                    raise BrokerError("gate attempt summary differs from its ledger")
                status = str(payload["status"])
                criteria = payload["criteria_passed"]
                evidence = payload["evidence"]
                failure_code = payload.get("failure_code")
                expected_credit = imported_credit_payloads.get(str(gate_id))
                if (
                    not valid_criteria(criteria, tuple(gate_plan.criteria))
                    or not valid_references(
                        evidence,
                        required=status in {"PASS", "PASS_LOCAL"},
                    )
                    or payload.get("local_credit") != expected_credit
                    or (
                        status in {"PASS", "PASS_LOCAL"}
                        and (
                            criteria != list(gate_plan.criteria)
                            or failure_code is not None
                        )
                    )
                    or (
                        status == "FAIL"
                        and (
                            not isinstance(failure_code, str)
                            or not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", failure_code)
                        )
                    )
                    or (
                        status == "PASS_LOCAL"
                        and local_credit_scopes.get(str(gate_id))
                        != "complete_local_gate"
                    )
                    or (
                        str(gate_id) == "ENOSPC"
                        and status in {"PASS", "PASS_LOCAL"}
                        and not _SHA256_RE.fullmatch(
                            str(payload.get("authorization_identity_sha256") or "")
                        )
                    )
                    or (
                        str(gate_id) != "ENOSPC"
                        and payload.get("authorization_identity_sha256") is not None
                    )
                ):
                    raise BrokerError("gate result evidence or criteria differs")
                if payload.get("status") in {"PASS", "PASS_LOCAL"} and (
                    any(item.identity_sha256 is None for item in gate_attempts)
                    or any(not item.completed for item in gate_attempts)
                ):
                    raise BrokerError("passing gate lacks all frozen slot terminals")
                claimed_attempt_head = str(
                    payload.get("attempt_ledger_head_sha256") or ""
                )
                expected_attempt_head = attempt_last_head.get(
                    str(active_gate), last_attempt_head
                )
                if (
                    not _SHA256_RE.fullmatch(claimed_attempt_head)
                    or claimed_attempt_head != expected_attempt_head
                ):
                    raise BrokerError("gate completion attempt head is invalid")
                # `_strict_ledger_snapshot` separately verifies that every
                # attempt start crosslinks to its exact gate-start record.  A
                # completion checkpoint may advance only for a gate that owns
                # every newly observed record.
                if not gate_attempts and claimed_attempt_head != last_attempt_head:
                    raise BrokerError("attempt-free gate advanced the attempt head")
                completed_gates.append(str(active_gate))
                active_gate = None
                last_attempt_head = claimed_attempt_head
                continue
            if event == "cleanup_started":
                scope = payload.get("scope")
                gate_id = payload.get("gate_id")
                expected_gate = completed_gates[-1] if completed_gates else None
                if (
                    active_gate is not None
                    or cleanup_scope is not None
                    or scope not in {"gate", "batch"}
                    or set(payload) != {"scope", "gate_id", "required_passes"}
                    or payload.get("required_passes") != 2
                    or (scope == "gate" and gate_id != expected_gate)
                    or (scope == "batch" and gate_id is not None)
                ):
                    raise BrokerError("batch cleanup start is noncanonical")
                cleanup_scope = str(scope)
                cleanup_gate_id = str(gate_id) if gate_id is not None else None
                cleanup_passes = []
                continue
            if event == "cleanup_pass_completed":
                pass_index = payload.get("pass_index")
                cleanup_gate = next(
                    gate for gate in FROZEN_GATE_PLAN if gate.gate_id == "CLEANUP"
                )
                cleanup_status = payload.get("status")
                if (
                    cleanup_scope is None
                    or set(payload)
                    != {
                        "scope",
                        "gate_id",
                        "pass_index",
                        "status",
                        "criteria_passed",
                        "failure_code",
                        "evidence",
                    }
                    or payload.get("scope") != cleanup_scope
                    or payload.get("gate_id") != cleanup_gate_id
                    or pass_index != len(cleanup_passes) + 1
                    or pass_index not in {1, 2}
                    or cleanup_status not in {"PASS", "FAIL"}
                    or not valid_criteria(
                        payload.get("criteria_passed"), cleanup_gate.criteria
                    )
                    or not valid_references(
                        payload.get("evidence"), required=cleanup_status == "PASS"
                    )
                    or (
                        cleanup_status == "PASS"
                        and (
                            payload.get("criteria_passed")
                            != list(cleanup_gate.criteria)
                            or payload.get("failure_code") is not None
                        )
                    )
                    or (
                        cleanup_status == "FAIL"
                        and (
                            not isinstance(payload.get("failure_code"), str)
                            or not re.fullmatch(
                                r"[a-z][a-z0-9_]{0,127}",
                                str(payload.get("failure_code")),
                            )
                        )
                    )
                ):
                    raise BrokerError("batch cleanup pass is noncanonical")
                cleanup_passes.append(dict(payload))
                continue
            if event == "cleanup_completed":
                expected_cleanup_status = (
                    "PASS"
                    if all(item["status"] == "PASS" for item in cleanup_passes)
                    else "FAIL"
                )
                if (
                    cleanup_scope is None
                    or [item["pass_index"] for item in cleanup_passes] != [1, 2]
                    or dict(payload)
                    != {
                        "scope": cleanup_scope,
                        "gate_id": cleanup_gate_id,
                        "status": expected_cleanup_status,
                        "required_passes": 2,
                        "passes": cleanup_passes,
                    }
                ):
                    raise BrokerError("batch cleanup completion differs")
                if cleanup_scope == "gate" and cleanup_gate_id is not None:
                    cleaned_gates.append(cleanup_gate_id)
                if cleanup_scope == "batch":
                    batch_cleanup_completed = True
                cleanup_scope = None
                cleanup_gate_id = None
                cleanup_passes = []
                continue
            if event == "cleanup_gate_completed":
                gate = payload.get("gate")
                cleanup_gate_plan = next(
                    item for item in FROZEN_GATE_PLAN if item.gate_id == "CLEANUP"
                )
                cleanup_status = payload.get("status")
                if (
                    cleanup_gate_seen
                    or active_gate is not None
                    or cleanup_scope is not None
                    or not batch_cleanup_completed
                    or not isinstance(gate, Mapping)
                    or gate.get("id") != "CLEANUP"
                    or set(payload)
                    != {
                        "gate",
                        "status",
                        "criteria_passed",
                        "failure_code",
                        "evidence",
                        "local_credit",
                        "attempts",
                        "authorization_identity_sha256",
                        "attempt_ledger_head_sha256",
                    }
                    or dict(gate) != frozen_payloads["CLEANUP"]
                    or cleanup_status not in {"PASS", "FAIL"}
                    or not valid_criteria(
                        payload.get("criteria_passed"), cleanup_gate_plan.criteria
                    )
                    or not valid_references(
                        payload.get("evidence"), required=cleanup_status == "PASS"
                    )
                    or payload.get("local_credit") is not None
                    or payload.get("authorization_identity_sha256") is not None
                    or payload.get("attempts")
                    != {
                        "planned": 0,
                        "started": 0,
                        "completed": 0,
                        "real_runtime_started": 0,
                        "real_runtime_completed": 0,
                        "non_runtime_started": 0,
                        "non_runtime_completed": 0,
                    }
                    or payload.get("attempt_ledger_head_sha256") != last_attempt_head
                    or (
                        cleanup_status == "PASS"
                        and (
                            payload.get("criteria_passed")
                            != list(cleanup_gate_plan.criteria)
                            or payload.get("failure_code") is not None
                        )
                    )
                    or (
                        cleanup_status == "FAIL"
                        and (
                            not isinstance(payload.get("failure_code"), str)
                            or not re.fullmatch(
                                r"[a-z][a-z0-9_]{0,127}",
                                str(payload.get("failure_code")),
                            )
                        )
                    )
                ):
                    raise BrokerError("cleanup gate record differs")
                cleanup_gate_seen = True
                continue
            if event == "batch_finalized":
                real_started = sum(
                    item.kind == "real_runtime" and item.identity_sha256 is not None
                    for item in attempts.values()
                )
                real_completed = sum(
                    item.kind == "real_runtime" and item.completed
                    for item in attempts.values()
                )
                nonruntime_started = sum(
                    item.kind == "non_runtime_conflict"
                    and item.identity_sha256 is not None
                    for item in attempts.values()
                )
                nonruntime_completed = sum(
                    item.kind == "non_runtime_conflict" and item.completed
                    for item in attempts.values()
                )
                expected_final_keys = {
                    "decision",
                    "gate_results_sha256",
                    "decision_sha256",
                    "real_runtime_attempts_started",
                    "real_runtime_attempts_completed",
                    "non_runtime_attempts_started",
                    "non_runtime_attempts_completed",
                }
                if (
                    active_gate is not None
                    or cleanup_scope is not None
                    or not cleanup_gate_seen
                    or set(payload) != expected_final_keys
                    or payload.get("decision") not in {"GO", "INCOMPLETE_NO_GO"}
                    or any(
                        not _SHA256_RE.fullmatch(str(payload.get(name) or ""))
                        for name in ("gate_results_sha256", "decision_sha256")
                    )
                    or payload.get("real_runtime_attempts_started") != real_started
                    or payload.get("real_runtime_attempts_completed") != real_completed
                    or payload.get("non_runtime_attempts_started") != nonruntime_started
                    or payload.get("non_runtime_attempts_completed")
                    != nonruntime_completed
                    or (
                        payload.get("decision") == "GO"
                        and (
                            completed_gates != list(substantive)
                            or cleaned_gates != list(substantive)
                            or (real_started, real_completed) != (26, 26)
                            or (nonruntime_started, nonruntime_completed) != (1, 1)
                        )
                    )
                ):
                    raise BrokerError("batch finalization differs")
                finalized = True
                continue
            raise BrokerError("batch ledger contains an unknown event")
        if not opened:
            raise BrokerError("batch ledger lacks its opening")
        started_gates = {
            item.gate_id
            for item in attempts.values()
            if item.identity_sha256 is not None
        }
        allowed_gates = set(completed_gates)
        if active_gate is not None:
            allowed_gates.add(active_gate)
        if not started_gates.issubset(allowed_gates):
            raise BrokerError("attempt ledger escapes the active batch gate")
        return _BatchPhase(
            active_gate=active_gate,
            cleanup_scope=cleanup_scope,
            cleanup_gate_id=cleanup_gate_id,
            batch_head_sha256=str(records[-1]["record_sha256"]),
            gate_start_heads=gate_start_heads,
            finalized=finalized,
        )

    def _lock_active_batch(self, batch_id: str) -> None:
        path = self.layout.grant_root / "active-batch.json"
        payload = {
            "schema": ACTIVE_BATCH_SCHEMA,
            "batch_id": batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "authority_expires_at": AUTHORITY_EXPIRES_AT.isoformat(),
        }
        try:
            _write_once(path, payload, owner_uid=self._trusted_uid)
        except FileExistsError:
            existing = _read_json(
                path,
                maximum=64 * 1024,
                owner_uid=self._trusted_uid,
            )
            if existing != payload:
                raise BrokerError("root broker is locked to another batch")

    def _validate_grant(
        self,
        request: Mapping[str, Any],
        *,
        caller_uid: int,
        strict: bool = False,
    ) -> _BatchPhase | None:
        batch_id = str(request["batch_id"])
        self._lock_active_batch(batch_id)
        if request["grant_kind"] == "batch_canary":
            action = str(request["action"])
            if action == "canary_create":
                if request["gate_id"] != "BATCH-CANARY":
                    raise BrokerError("batch canary creation gate differs")
                return None
            active_path = self.layout.grant_root / "batch-canary-active.json"
            active = _read_json(
                active_path,
                maximum=64 * 1024,
                owner_uid=self._trusted_uid,
            )
            if (
                set(active) != {"schema", "batch_id", "name", "created", "container_id"}
                or active.get("schema") != "fortgym.m1b-root-broker-canary/v1"
                or active.get("batch_id") != batch_id
                or active.get("name")
                != "fortgym-m1b-foreign-" + _sha256_bytes(batch_id.encode("utf-8"))[:16]
                or active.get("created") is not True
                or not _CONTAINER_ID_RE.fullmatch(str(active.get("container_id") or ""))
            ):
                raise BrokerError("batch canary root grant differs")
            removed_path = self.layout.grant_root / "batch-canary-removed.json"
            removed = removed_path.exists()
            ledger_path = (
                self.layout.batch_evidence_root(batch_id)
                / "control"
                / "batch-ledger.jsonl"
            )
            if action == "canary_inspect" and request["gate_id"] == "BATCH-CANARY":
                if removed or ledger_path.exists():
                    raise BrokerError("initial batch canary inspection phase differs")
                return None
            records = self._ledger_records(
                ledger_path,
                schema="fortgym.m1b-live-acceptance-batch-ledger/v1",
                batch_id=batch_id,
                caller_uid=caller_uid,
            )
            phase = self._batch_phase(records)
            if action == "canary_remove":
                if removed and len(self._matching_action_grants(request)) != 1:
                    raise BrokerError("batch canary removal recovery is exhausted")
                if not phase.finalized or request["gate_id"] != "CLEANUP":
                    raise BrokerError("batch canary removal requires a finalized batch")
                seal = _read_json(
                    self.layout.batch_evidence_root(batch_id) / "control" / "seal.json",
                    maximum=256 * 1024,
                    owner_uid=caller_uid,
                )
                if (
                    seal.get("schema") != "fortgym.m1b-live-acceptance-seal/v1"
                    or seal.get("batch_id") != batch_id
                    or seal.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
                    or seal.get("plan_sha256") != FROZEN_PLAN_SHA256
                ):
                    raise BrokerError("batch canary removal seal identity differs")
            if action in {"canary_inspect", "canary_absence"}:
                expected_gate = (
                    "CLEANUP"
                    if phase.finalized
                    else (
                        phase.active_gate
                        if phase.active_gate is not None
                        else phase.cleanup_gate_id
                        if phase.cleanup_scope == "gate"
                        else "CLEANUP"
                        if phase.cleanup_scope == "batch"
                        else None
                    )
                )
                if request["gate_id"] != expected_gate:
                    raise BrokerError("batch canary inspection phase differs")
                if action == "canary_absence" and (not phase.finalized or not removed):
                    raise BrokerError("batch canary absence requires finalized removal")
            if action == "attest_broker_evidence":
                absence = self.layout.grant_root / "batch-canary-absence.json"
                if (
                    not phase.finalized
                    or not removed
                    or request["gate_id"] != "CLEANUP"
                    or not absence.exists()
                ):
                    raise BrokerError(
                        "final broker attestation requires sealed canary absence"
                    )
            if removed:
                removed_document = _read_json(
                    removed_path,
                    maximum=64 * 1024,
                    owner_uid=self._trusted_uid,
                )
                if set(removed_document) != {
                    "schema",
                    "batch_id",
                    "name",
                    "created",
                    "container_id",
                    "removed",
                } or removed_document != {**active, "removed": True}:
                    raise BrokerError("batch canary removal state differs")
            if action == "attest_broker_evidence":
                absence_document = _read_json(
                    self.layout.grant_root / "batch-canary-absence.json",
                    maximum=64 * 1024,
                    owner_uid=self._trusted_uid,
                )
                if absence_document != {
                    "schema": "fortgym.m1b-root-broker-canary-absence/v1",
                    "batch_id": batch_id,
                    "name": active["name"],
                    "container_id": active["container_id"],
                    "removed": True,
                    "absence_verified": True,
                    "stdout_sha256": _sha256_bytes(b""),
                }:
                    raise BrokerError("batch canary absence state differs")
            if strict:
                strict_phase = self._strict_ledger_snapshot(
                    request, caller_uid=caller_uid
                ).phase
                if strict_phase != phase:
                    raise BrokerError("strict batch phase differs from public phase")
            return phase

        batch_records = self._ledger_records(
            self.layout.batch_evidence_root(batch_id)
            / "control"
            / "batch-ledger.jsonl",
            schema="fortgym.m1b-live-acceptance-batch-ledger/v1",
            batch_id=batch_id,
            caller_uid=caller_uid,
        )
        attempt_records = self._ledger_records(
            self.layout.batch_evidence_root(batch_id)
            / "control"
            / "attempt-ledger.jsonl",
            schema="fortgym.m1b-live-acceptance-attempt-ledger/v1",
            batch_id=batch_id,
            caller_uid=caller_uid,
        )
        phase = self._batch_phase(batch_records)
        if phase.finalized:
            raise BrokerError("attempt action follows batch finalization")
        attempt_id = str(request["attempt_id"])
        planned_gate, planned_role, planned_kind = _FROZEN_ATTEMPTS[attempt_id]
        starts = [
            record
            for record in attempt_records
            if record["event"] == "attempt_started"
            and record["payload"].get("attempt_id") == attempt_id
        ]
        completions = [
            record
            for record in attempt_records
            if record["event"] == "attempt_completed"
            and record["payload"].get("attempt_id") == attempt_id
        ]
        if len(starts) != 1 or len(completions) > 1:
            raise BrokerError("attempt grant does not have one durable start")
        started = starts[0]["payload"]
        if (
            started.get("gate_id") != planned_gate
            or started.get("role") != planned_role
            or started.get("kind") != planned_kind
            or started.get("identity_sha256") != request.get("attempt_identity_sha256")
            or started.get("batch_ledger_head_sha256")
            != phase.gate_start_heads.get(planned_gate)
        ):
            raise BrokerError("attempt grant identity or batch crosslink differs")
        action = str(request["action"])
        allowed_roles = _ACTION_ROLES.get(action)
        if allowed_roles is not None and planned_role not in allowed_roles:
            raise BrokerError("attempt role cannot authorize this broker action")
        if phase.active_gate is not None:
            if (
                phase.active_gate != request["gate_id"]
                or planned_gate != request["gate_id"]
                or completions
            ):
                raise BrokerError("attempt action is outside its live gate")
        elif phase.cleanup_scope == "gate":
            if (
                request["gate_id"] != phase.cleanup_gate_id
                or action not in _READ_ONLY_ACTIONS
                or planned_gate != phase.cleanup_gate_id
            ):
                raise BrokerError("attempt action is outside exact gate cleanup")
        elif phase.cleanup_scope == "batch":
            if request["gate_id"] != "CLEANUP" or action not in _READ_ONLY_ACTIONS:
                raise BrokerError("attempt action is outside final batch cleanup")
        else:
            raise BrokerError("attempt action has no active acceptance phase")
        if strict:
            strict_phase = self._strict_ledger_snapshot(
                request, caller_uid=caller_uid
            ).phase
            if strict_phase != phase:
                raise BrokerError("strict attempt phase differs from public phase")
        return phase

    def _update_canary_state(
        self,
        request: Mapping[str, Any],
        *,
        capture: CommandCapture,
    ) -> None:
        action = str(request["action"])
        if capture.returncode != 0 or action not in {
            "canary_create",
            "canary_remove",
            "canary_absence",
        }:
            return
        parameters = request.get("parameters")
        if not isinstance(parameters, Mapping):
            raise BrokerError("batch canary state lacks exact parameters")
        payload = {
            "schema": "fortgym.m1b-root-broker-canary/v1",
            "batch_id": request["batch_id"],
            "name": parameters.get("canary_name"),
            "created": True,
        }
        if action == "canary_create":
            container_id = capture.stdout.strip().lower()
            if not _CONTAINER_ID_RE.fullmatch(container_id):
                raise BrokerError("canary root state lacks its container identity")
            _write_once(
                self.layout.grant_root / "batch-canary-active.json",
                {**payload, "container_id": container_id},
                owner_uid=self._trusted_uid,
            )
            return
        active = _read_json(
            self.layout.grant_root / "batch-canary-active.json",
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        if action == "canary_remove":
            removed_payload = {
                **payload,
                "container_id": active.get("container_id"),
                "removed": True,
            }
            removed_path = self.layout.grant_root / "batch-canary-removed.json"
            if removed_path.exists():
                if (
                    _read_json(
                        removed_path,
                        maximum=64 * 1024,
                        owner_uid=self._trusted_uid,
                    )
                    != removed_payload
                ):
                    raise BrokerError("existing canary removal state differs")
            else:
                _write_once(
                    removed_path,
                    removed_payload,
                    owner_uid=self._trusted_uid,
                )
            return
        if capture.stdout != "" or capture.stderr != "":
            raise BrokerError("canary absence state lacks an exact empty result")
        removed = _read_json(
            self.layout.grant_root / "batch-canary-removed.json",
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        _write_once(
            self.layout.grant_root / "batch-canary-absence.json",
            {
                "schema": "fortgym.m1b-root-broker-canary-absence/v1",
                "batch_id": request["batch_id"],
                "name": parameters.get("canary_name"),
                "container_id": removed.get("container_id"),
                "removed": True,
                "absence_verified": True,
                "stdout_sha256": _sha256_bytes(b""),
            },
            owner_uid=self._trusted_uid,
        )

    def _consume_action_grant(
        self,
        request: Mapping[str, Any],
        *,
        logical_digest: str,
        phase: _BatchPhase | None,
        recovery_epoch: int = 0,
    ) -> Path:
        action = str(request["action"])
        identity = {
            "batch_id": request["batch_id"],
            "grant_kind": request["grant_kind"],
            "attempt_id": request["attempt_id"],
            "attempt_identity_sha256": request["attempt_identity_sha256"],
            "gate_id": request["gate_id"],
            "action": action,
            "logical_argv_sha256": logical_digest,
            "recovery_epoch": recovery_epoch,
        }
        if action in _READ_ONLY_ACTIONS:
            identity["request_id"] = request["request_id"]
        grant_id = _sha256_bytes(_canonical_bytes(identity))
        path = self.layout.grant_root / f"{grant_id}.json"
        payload = {
            "schema": GRANT_SCHEMA,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            **identity,
            "request_id": request["request_id"],
            "batch_ledger_head_sha256": (
                phase.batch_head_sha256 if phase is not None else None
            ),
            "one_shot": action in _ONE_SHOT_ACTIONS,
        }
        try:
            _write_once(path, payload, owner_uid=self._trusted_uid)
        except FileExistsError as exc:
            raise BrokerError("root action grant was already consumed") from exc
        return path

    def _matching_action_grants(
        self,
        request: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for path in sorted(self.layout.grant_root.glob("*.json")):
            document = _read_json(
                path,
                maximum=64 * 1024,
                owner_uid=self._trusted_uid,
            )
            if document.get("schema") != GRANT_SCHEMA:
                continue
            expected_one_shot = str(document.get("action")) in _ONE_SHOT_ACTIONS
            if set(document) != {
                "schema",
                "acceptance_sha256",
                "plan_sha256",
                "batch_id",
                "grant_kind",
                "attempt_id",
                "attempt_identity_sha256",
                "gate_id",
                "action",
                "logical_argv_sha256",
                "recovery_epoch",
                "request_id",
                "batch_ledger_head_sha256",
                "one_shot",
            } or (
                document.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
                or document.get("plan_sha256") != FROZEN_PLAN_SHA256
                or type(document.get("one_shot")) is not bool
                or document.get("one_shot") is not expected_one_shot
                or document.get("recovery_epoch") not in {0, 1}
                or not _SHA256_RE.fullmatch(str(document.get("request_id") or ""))
                or not _SHA256_RE.fullmatch(
                    str(document.get("logical_argv_sha256") or "")
                )
            ):
                raise BrokerError("root action grant schema differs")
            if (
                document.get("batch_id") == request.get("batch_id")
                and document.get("grant_kind") == request.get("grant_kind")
                and document.get("attempt_id") == request.get("attempt_id")
                and document.get("attempt_identity_sha256")
                == request.get("attempt_identity_sha256")
                and document.get("gate_id") == request.get("gate_id")
                and document.get("action") == request.get("action")
                and document.get("logical_argv_sha256")
                == request.get("logical_argv_sha256")
            ):
                matches.append(document)
        return matches

    def _recovery_decision(
        self,
        request: Mapping[str, Any],
        *,
        binding: _RunBinding | None,
    ) -> _RecoveryDecision:
        action = str(request["action"])
        if action not in _ONE_SHOT_ACTIONS:
            return _RecoveryDecision(epoch=0, noop=False, reason=None)
        matching_records = [
            record
            for record in self._state_records()
            if record["batch_id"] == request["batch_id"]
            and record["data"].get("action") == action
            and record["data"].get("attempt_id") == request.get("attempt_id")
            and (
                binding is None
                or (
                    isinstance(record["data"].get("binding"), Mapping)
                    and record["data"]["binding"].get("run_id") == binding.run_id
                    and record["data"]["binding"].get("contract_sha256")
                    == binding.contract_sha256
                    and record["data"]["binding"].get("nonce_sha256")
                    == binding.nonce_sha256
                    and record["data"]["binding"].get("cohort_sha256")
                    == binding.cohort_sha256
                )
            )
        ]
        claims = [
            record for record in matching_records if record["event"] == "action_claimed"
        ]
        grants = self._matching_action_grants(request)
        if not claims and not grants:
            return _RecoveryDecision(epoch=0, noop=False, reason=None)
        if len(claims) > 1 or len(grants) > 1:
            raise BrokerError("root mutation recovery budget is exhausted")
        recoverable = {
            "docker_remove",
            "unmount_enospc",
            "canary_remove",
            "pause_peer_harness",
            "resume_peer_harness",
            "pause_cohort_harness",
            "resume_cohort_harness",
            "abort_paused_harness",
            "stop_peer_harness",
        }
        if action not in recoverable:
            raise BrokerError("ambiguous root mutation is not safely retryable")
        noop, reason = self._root_live_recovery_state(
            request,
            binding=binding,
        )
        return _RecoveryDecision(epoch=1, noop=noop, reason=reason)

    def _root_live_recovery_state(
        self,
        request: Mapping[str, Any],
        *,
        binding: _RunBinding | None,
    ) -> tuple[bool, str]:
        action = str(request["action"])
        if action == "docker_remove":
            if binding is None:
                raise BrokerError("container recovery lacks a run binding")
            document, _capture = self._inspect_container_live(
                binding,
                allow_absent=True,
            )
            return document is None, (
                "container_already_absent"
                if document is None
                else "container_still_present"
            )
        if action == "canary_remove":
            present = self._inspect_canary_live(request, allow_absent=True) is not None
            return not present, (
                "canary_already_absent" if not present else "canary_still_present"
            )
        if action == "unmount_enospc":
            if binding is None:
                raise BrokerError("unmount recovery lacks a run binding")
            mounted = (
                self._mount_record(self.layout.artifacts_root / binding.run_id)
                is not None
            )
            return not mounted, (
                "workspace_already_unmounted"
                if not mounted
                else "workspace_still_mounted"
            )
        if binding is None:
            raise BrokerError("signal recovery lacks a run binding")
        if action in {"abort_paused_harness", "stop_peer_harness"}:
            prior_pid = self._prior_signal_target_pid(request)
            if prior_pid is None:
                raise BrokerError("terminal signal recovery lacks a root PID binding")
            try:
                self._read_proc_bytes(prior_pid, "stat", 64 * 1024)
            except BrokerError as exc:
                if "process is absent" in str(exc):
                    return True, "process_already_absent"
                raise
        try:
            identity, process_state = self._process_identity_for_action(
                request, binding
            )
        except BrokerError as exc:
            if action in {"abort_paused_harness", "stop_peer_harness"} and (
                "process is absent" in str(exc)
                or "ownership evidence is unavailable" in str(exc)
            ):
                return True, "process_already_absent"
            raise
        del identity
        if action in {"pause_peer_harness", "pause_cohort_harness"}:
            stopped = process_state in {"T", "t"}
            return stopped, "process_already_stopped" if stopped else "process_running"
        if action in {"resume_peer_harness", "resume_cohort_harness"}:
            running = process_state not in {"T", "t"}
            return running, "process_already_running" if running else "process_stopped"
        return False, "terminal_signal_process_still_present"

    def _recovery_noop_capture(
        self,
        request: Mapping[str, Any],
        *,
        binding: _RunBinding | None,
        actual_argv: Sequence[str],
        reason: str | None,
    ) -> CommandCapture:
        action = str(request["action"])
        if reason not in {
            "container_already_absent",
            "canary_already_absent",
            "workspace_already_unmounted",
            "process_already_stopped",
            "process_already_running",
            "process_already_absent",
        }:
            raise BrokerError("root recovery no-op lacks a live postcondition")
        stdout = ""
        if action == "docker_remove" and binding is not None:
            stdout = f"{binding.container_id or binding.container_name}\n"
        elif action == "canary_remove":
            stdout = f"{request['parameters']['canary_name']}\n"
        return CommandCapture(
            argv=tuple(str(value) for value in actual_argv),
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    def _confirm_caller_snapshot(
        self,
        request: Mapping[str, Any],
        *,
        snapshot: _LedgerSnapshot,
        binding: _RunBinding | None,
        caller_uid: int,
    ) -> None:
        """Close caller-evidence TOCTOU after the root grant is durable."""

        batch_root = self.layout.batch_evidence_root(str(request["batch_id"]))
        control = batch_root / "control"
        if snapshot.batch_records:
            batch_sha256 = _sha256_file(
                control / "batch-ledger.jsonl",
                maximum=_MAX_LEDGER_BYTES,
                owner_uid=caller_uid,
            )
        else:
            batch_sha256 = _ZERO_SHA256
            if (control / "batch-ledger.jsonl").exists():
                raise BrokerError("initial canary ledger appeared after authorization")
        if snapshot.attempt_records or snapshot.batch_records:
            attempt_sha256 = _sha256_file(
                control / "attempt-ledger.jsonl",
                maximum=_MAX_LEDGER_BYTES,
                owner_uid=caller_uid,
                allow_empty=True,
            )
        else:
            attempt_sha256 = _ZERO_SHA256
            if (control / "attempt-ledger.jsonl").exists():
                raise BrokerError(
                    "initial canary attempt ledger appeared after authorization"
                )
        if (
            batch_sha256 != snapshot.batch_file_sha256
            or attempt_sha256 != snapshot.attempt_file_sha256
        ):
            raise BrokerError("caller ledgers changed after the root grant")
        if binding is not None:
            launch_path = self.layout.control_root / binding.run_id / "launch.json"
            if (
                _sha256_file(
                    launch_path,
                    maximum=256 * 1024,
                    owner_uid=caller_uid,
                )
                != binding.launch_sha256
            ):
                raise BrokerError("durable launch changed after root validation")

    @contextlib.contextmanager
    def _execution_guard(
        self,
        request: Mapping[str, Any],
        binding: _RunBinding | None,
        actual_argv: Sequence[str],
    ) -> Any:
        """Stage caller-writable Docker input below a root-stable pathname."""

        action = str(request["action"])
        if action not in {"docker_run", "docker_create"}:
            yield tuple(str(item) for item in actual_argv)
            return
        if binding is None:
            raise BrokerError("Docker launch guard lacks a run binding")
        source = Path(binding.runtime_controller.evidence_dir)
        before = self._stable_directory_identity(
            source,
            owner_uid=self._required_evidence_owner_uid(),
            exact_mode=0o1777,
        )
        if self._mount_record(source) is not None:
            raise BrokerError("Docker evidence source is already a mountpoint")
        try:
            source_descriptor = os.open(
                source,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as exc:
            raise BrokerError("Docker bind source descriptor is unavailable") from exc
        source_metadata = os.fstat(source_descriptor)
        if (source_metadata.st_dev, source_metadata.st_ino) != (before[0], before[1]):
            os.close(source_descriptor)
            raise BrokerError("Docker bind source descriptor identity differs")
        staging = self._root_staged_evidence_path(binding.run_id)
        run_root = staging.parent
        try:
            try:
                os.mkdir(run_root, mode=0o700)
            except FileExistsError:
                pass
            _validate_directory(run_root, owner_uid=self._trusted_uid, exact_mode=0o700)
            try:
                os.mkdir(staging, mode=0o700)
            except FileExistsError:
                pass
            _validate_directory(staging, owner_uid=self._trusted_uid, exact_mode=0o700)
            if self._mount_record(staging) is not None:
                raise BrokerError("root Docker staging target is already mounted")
            fd_source = f"/proc/self/fd/{source_descriptor}"
            mount_argv = (_MOUNT, "--bind", fd_source, str(staging))
            mounted = self._execute_with_pass_fd(
                mount_argv,
                30.0,
                descriptor=source_descriptor,
            )
            if (
                mounted.argv != mount_argv
                or mounted.returncode != 0
                or mounted.stdout
                or mounted.stderr
            ):
                raise BrokerError("root-stable Docker bind source pin failed")
            staged_metadata = staging.stat()
            record = self._mount_record(staging)
            if (staged_metadata.st_dev, staged_metadata.st_ino) != (
                source_metadata.st_dev,
                source_metadata.st_ino,
            ) or record is None:
                raise BrokerError("Docker bind source identity changed while pinning")
            original_volume = f"{source}:/artifacts"
            staged_volume = f"{staging}:/artifacts"
            guarded = tuple(
                staged_volume if str(item) == original_volume else str(item)
                for item in actual_argv
            )
            if guarded.count(staged_volume) != 1 or original_volume in guarded:
                raise BrokerError("Docker bind source argv could not be staged exactly")
            try:
                yield guarded
            except BaseException:
                document, _capture = self._inspect_container_live(
                    binding,
                    allow_absent=True,
                )
                if document is None:
                    self._release_root_staged_evidence(binding.run_id)
                raise
            document, _capture = self._inspect_container_live(
                binding,
                allow_absent=True,
            )
            if document is None:
                self._release_root_staged_evidence(binding.run_id)
                return
            final_source = os.fstat(source_descriptor)
            final_staged = staging.stat()
            if (
                (final_source.st_dev, final_source.st_ino)
                != (source_metadata.st_dev, source_metadata.st_ino)
                or (final_staged.st_dev, final_staged.st_ino)
                != (source_metadata.st_dev, source_metadata.st_ino)
                or self._mount_record(staging) is None
            ):
                raise BrokerError("Docker bind source pin changed during launch")
        finally:
            os.close(source_descriptor)

    def _root_staged_evidence_path(self, run_id: str) -> Path:
        if not _ID_RE.fullmatch(run_id):
            raise BrokerError("Docker staging run identity is invalid")
        return self.layout.bind_source_root / run_id / "artifacts"

    def _release_root_staged_evidence(self, run_id: str) -> None:
        staging = self._root_staged_evidence_path(run_id)
        run_root = staging.parent
        if not staging.exists() and not run_root.exists():
            return
        _validate_directory(run_root, owner_uid=self._trusted_uid, exact_mode=0o700)
        if not staging.exists():
            raise BrokerError("root Docker staging leaf disappeared")
        record = self._mount_record(staging)
        if record is not None:
            unmount_argv = (_UMOUNT, "--", str(staging))
            released = self._execute(unmount_argv, 30.0)
            if (
                released.argv != unmount_argv
                or released.returncode != 0
                or released.stdout
                or released.stderr
                or self._mount_record(staging) is not None
            ):
                raise BrokerError("root-stable Docker bind source release failed")
        _validate_directory(staging, owner_uid=self._trusted_uid, exact_mode=0o700)
        try:
            os.rmdir(staging)
            os.rmdir(run_root)
        except OSError as exc:
            raise BrokerError("root Docker staging directory cleanup failed") from exc

    def _required_evidence_owner_uid(self) -> int:
        if self._evidence_owner_uid is None:
            raise BrokerError("caller evidence owner is unavailable")
        return self._evidence_owner_uid

    @staticmethod
    def _stable_directory_identity(
        path: Path,
        *,
        owner_uid: int,
        exact_mode: int,
    ) -> tuple[int, int, int, int]:
        current = Path(path)
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
            after = current.lstat()
        except OSError as exc:
            raise BrokerError("execution directory identity is unavailable") from exc
        if (
            resolved != current
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != owner_uid
            or stat.S_IMODE(metadata.st_mode) != exact_mode
            or (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_ctime_ns)
        ):
            raise BrokerError("execution directory identity is unsafe")
        for ancestor in (current, *current.parents):
            ancestor_info = ancestor.lstat()
            if stat.S_ISLNK(ancestor_info.st_mode):
                raise BrokerError("execution directory ancestry contains a symlink")
            if ancestor == Path(current.anchor):
                break
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_ctime_ns,
            stat.S_IMODE(metadata.st_mode),
        )

    @staticmethod
    def _decode_mount_path(value: str) -> str:
        replacements = {"\\040": " ", "\\011": "\t", "\\012": "\n", "\\134": "\\"}
        for encoded, decoded in replacements.items():
            value = value.replace(encoded, decoded)
        return value

    def _mount_record(self, path: Path) -> Mapping[str, Any] | None:
        try:
            descriptor = os.open(
                "/proc/self/mountinfo", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
        except OSError as exc:
            raise BrokerError("root mount table is unreadable") from exc
        try:
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise BrokerError("root mount table exceeds its bound")
                chunks.append(chunk)
        finally:
            os.close(descriptor)
        target = str(path)
        matches: list[dict[str, Any]] = []
        for raw_line in b"".join(chunks).decode("utf-8", errors="strict").splitlines():
            fields = raw_line.split()
            try:
                separator = fields.index("-")
            except ValueError as exc:
                raise BrokerError("root mount table record is malformed") from exc
            if len(fields) < 6 or separator + 3 >= len(fields):
                raise BrokerError("root mount table record is truncated")
            mountpoint = self._decode_mount_path(fields[4])
            if mountpoint != target:
                continue
            matches.append(
                {
                    "mount_id": fields[0],
                    "parent_id": fields[1],
                    "device": fields[2],
                    "root": self._decode_mount_path(fields[3]),
                    "mountpoint": mountpoint,
                    "options": tuple(fields[5].split(",")),
                    "filesystem": fields[separator + 1],
                    "source": self._decode_mount_path(fields[separator + 2]),
                    "super_options": tuple(fields[separator + 3].split(",")),
                }
            )
        if len(matches) > 1:
            raise BrokerError("execution target has stacked mounts")
        return matches[0] if matches else None

    @staticmethod
    def _read_proc_bytes(pid: int, name: str, maximum: int) -> bytes:
        path = Path("/proc") / str(pid) / name
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError as exc:
            raise BrokerError("execution target process is absent") from exc
        except OSError as exc:
            raise BrokerError(
                "execution target process identity is unreadable"
            ) from exc
        try:
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise BrokerError("execution target process identity is oversized")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @classmethod
    def _proc_snapshot(
        cls, pid: int
    ) -> tuple[int, int, int, str, dict[str, str], bytes]:
        if isinstance(pid, bool) or pid <= 1 or pid in {os.getpid(), os.getppid()}:
            raise BrokerError("execution target PID is unsafe")
        stat_raw = cls._read_proc_bytes(pid, "stat", 64 * 1024).decode(
            "utf-8", errors="strict"
        )
        closing = stat_raw.rfind(")")
        if closing <= 0:
            raise BrokerError("execution target process stat is malformed")
        fields = stat_raw[closing + 2 :].split()
        if len(fields) < 20:
            raise BrokerError("execution target process stat is truncated")
        try:
            state = fields[0]
            parent_pid = int(fields[1])
            process_group_id = int(fields[2])
            starttime = int(fields[19])
        except ValueError as exc:
            raise BrokerError("execution target process stat is invalid") from exc
        environment_raw = cls._read_proc_bytes(pid, "environ", 256 * 1024)
        environment: dict[str, str] = {}
        for item in environment_raw.rstrip(b"\0").split(b"\0"):
            if not item:
                continue
            if b"=" not in item:
                raise BrokerError("execution target environment is malformed")
            raw_name, raw_value = item.split(b"=", 1)
            try:
                env_name = raw_name.decode("utf-8", errors="strict")
                env_value = raw_value.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise BrokerError("execution target environment is not UTF-8") from exc
            if not env_name or env_name in environment:
                raise BrokerError("execution target environment names are not unique")
            environment[env_name] = env_value
        cmdline = cls._read_proc_bytes(pid, "cmdline", 64 * 1024)
        return starttime, process_group_id, parent_pid, state, environment, cmdline

    def _process_identity_for_action(
        self,
        request: Mapping[str, Any],
        binding: _RunBinding,
    ) -> tuple[_ProcessIdentity, str]:
        self._execution_supervisor_child_identity = None
        action = str(request["action"])
        owned = self._load_owned_run(request)
        if action == "signal_runtime":
            pid = int(owned.runtime_host_pid)
            role = "runtime"
        elif action == "signal_supervisor":
            pid = int(owned.supervisor_pid)
            role = "supervisor"
        else:
            pid = int(owned.harness_pid)
            role = "harness"
        if (
            binding.container_id is None
            or str(owned.container_id).lower() != binding.container_id
        ):
            raise BrokerError("process evidence container differs from root binding")
        self._inspect_container_live(binding, allow_absent=False)
        if self._derived_target_pid is not None and pid != self._derived_target_pid:
            raise BrokerError("derived signal PID changed before execution")
        first = self._proc_snapshot(pid)
        second = self._proc_snapshot(pid)
        # Scheduling state (R/S/D/T) is volatile, not process identity. Keep
        # starttime, PGID, parent, environment and command comparisons exact.
        if first[:3] + first[4:] != second[:3] + second[4:]:
            raise BrokerError("execution target identity changed during revalidation")
        starttime, process_group_id, parent_pid, process_state, environment, cmdline = (
            second
        )
        if first[3] in {"X", "x", "Z"} or process_state in {"X", "x", "Z"}:
            raise BrokerError("execution target is already terminal")
        expected_contract_name = (
            "FORTGYM_CONTRACT_SHA256"
            if role == "runtime"
            else "FORT_GYM_RUN_CONTRACT_SHA256"
        )
        expected_nonce_name = (
            "FORTGYM_RUN_NONCE" if role == "runtime" else "FORT_GYM_RUN_NONCE"
        )
        expected_run_name = "FORTGYM_RUN_ID" if role == "runtime" else "FORT_GYM_RUN_ID"
        if role != "supervisor" and (
            environment.get(expected_run_name) != binding.run_id
            or environment.get(expected_contract_name) != binding.contract_sha256
            or _sha256_bytes(environment.get(expected_nonce_name, "").encode("utf-8"))
            != binding.nonce_sha256
        ):
            raise BrokerError("execution target environment identity differs")
        if role == "harness" and (
            process_group_id != int(owned.harness_process_group_id)
            or process_group_id != pid
            or f"--external-run-id\0{binding.run_id}\0".encode()
            not in b"\0" + cmdline + b"\0"
        ):
            raise BrokerError("harness process group or command identity differs")
        if role == "runtime":
            cgroup = self._read_proc_bytes(pid, "cgroup", 64 * 1024).decode(
                "utf-8", errors="strict"
            )
            comm = (
                self._read_proc_bytes(pid, "comm", 4096)
                .decode("utf-8", errors="strict")
                .strip()
            )
            if (
                binding.container_id is None
                or binding.container_id not in cgroup
                or Path(comm).name != "Dwarf_Fortress"
            ):
                raise BrokerError("runtime PID does not belong to the root container")
        if role == "supervisor":
            requested = request["parameters"].get("supervisor_start_ticks")
            if requested != starttime:
                raise BrokerError(
                    "supervisor starttime differs from caller cross-check"
                )
            harness_pid = owned.harness_pid
            if (
                isinstance(harness_pid, bool)
                or not isinstance(harness_pid, int)
                or harness_pid <= 1
                or harness_pid == pid
            ):
                raise BrokerError("supervisor child PID binding is invalid")
            child_first = self._proc_snapshot(harness_pid)
            child_second = self._proc_snapshot(harness_pid)
            if child_first[:3] + child_first[4:] != child_second[:3] + child_second[4:]:
                raise BrokerError(
                    "supervisor child identity changed during revalidation"
                )
            (
                child_starttime,
                child_process_group_id,
                child_parent_pid,
                child_state,
                child_environment,
                child_cmdline,
            ) = child_second
            if child_first[3] in {"X", "x", "Z"} or child_state in {"X", "x", "Z"}:
                raise BrokerError("supervisor child is already terminal")
            if (
                child_parent_pid != pid
                or child_process_group_id != int(owned.harness_process_group_id)
                or child_process_group_id != harness_pid
            ):
                raise BrokerError(
                    "supervisor is not the live parent of the owned harness"
                )
            if (
                child_environment.get("FORT_GYM_RUN_ID") != binding.run_id
                or child_environment.get("FORT_GYM_RUN_CONTRACT_SHA256")
                != binding.contract_sha256
                or _sha256_bytes(
                    child_environment.get("FORT_GYM_RUN_NONCE", "").encode("utf-8")
                )
                != binding.nonce_sha256
                or f"--external-run-id\0{binding.run_id}\0".encode()
                not in b"\0" + child_cmdline + b"\0"
                or any(name in child_environment for name in _PROVIDER_ENV_NAMES)
            ):
                raise BrokerError("supervisor child run identity differs")
            self._execution_supervisor_child_identity = _ProcessIdentity(
                pid=harness_pid,
                starttime=child_starttime,
                process_group_id=child_process_group_id,
                parent_pid=child_parent_pid,
                environment_sha256=_sha256_bytes(_canonical_bytes(child_environment)),
                command_sha256=_sha256_bytes(child_cmdline),
                role="harness",
            )
        if any(name in environment for name in _PROVIDER_ENV_NAMES):
            raise BrokerError("execution target contains forbidden provider material")
        identity = _ProcessIdentity(
            pid=pid,
            starttime=starttime,
            process_group_id=process_group_id,
            parent_pid=parent_pid,
            environment_sha256=_sha256_bytes(
                environment_raw := _canonical_bytes(environment)
            ),
            command_sha256=_sha256_bytes(cmdline),
            role=role,
        )
        del environment_raw
        return identity, process_state

    def _prior_signal_target_pid(self, request: Mapping[str, Any]) -> int | None:
        matches = [
            record["data"].get("target_pid")
            for record in self._state_records()
            if record["batch_id"] == request["batch_id"]
            and record["event"] == "action_claimed"
            and record["data"].get("attempt_id") == request.get("attempt_id")
            and record["data"].get("action") == request.get("action")
        ]
        if not matches:
            return None
        if (
            len(matches) != 1
            or isinstance(matches[0], bool)
            or not isinstance(matches[0], int)
        ):
            raise BrokerError("prior signal target binding is ambiguous")
        return matches[0]

    @staticmethod
    def _pidfd_target_pid(descriptor: int) -> int:
        try:
            raw = RootBroker._read_proc_bytes(
                os.getpid(), f"fdinfo/{descriptor}", 64 * 1024
            )
        except BrokerError as exc:
            raise BrokerError("pidfd identity is unreadable") from exc
        matches = [
            line.split(":", 1)[1].strip()
            for line in raw.decode("utf-8", errors="strict").splitlines()
            if line.startswith("Pid:")
        ]
        if len(matches) != 1:
            raise BrokerError("pidfd identity is malformed")
        try:
            pid = int(matches[0])
        except ValueError as exc:
            raise BrokerError("pidfd target PID is invalid") from exc
        if pid <= 1:
            raise BrokerError("pidfd target is already absent or unsafe")
        return pid

    def _execute_pidfd_signal(
        self,
        request: Mapping[str, Any],
        *,
        actual_argv: Sequence[str],
    ) -> CommandCapture:
        identity = self._execution_process_identity
        pidfd_open = getattr(os, "pidfd_open", None)
        pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
        if identity is None:
            # A terminal recovery no-op is handled before this method; every
            # delivered signal must have a live, root-authenticated target.
            raise BrokerError("pidfd signal lacks a root process binding")
        if not callable(pidfd_open) or not callable(pidfd_send_signal):
            raise BrokerError("Linux pidfd signal delivery is unavailable")
        expected_signal = (
            "-STOP"
            if request["action"] in {"pause_peer_harness", "pause_cohort_harness"}
            else "-CONT"
            if request["action"] in {"resume_peer_harness", "resume_cohort_harness"}
            else "-TERM"
            if request["action"] == "stop_peer_harness"
            else "-KILL"
        )
        expected_argv = (_KILL, expected_signal, "--", str(identity.pid))
        if tuple(actual_argv) != expected_argv:
            raise BrokerError("pidfd signal differs from its logical command")
        try:
            descriptor = int(pidfd_open(identity.pid, 0))
        except (OSError, TypeError, ValueError) as exc:
            raise BrokerError("pidfd target could not be opened") from exc
        try:
            if self._pidfd_target_pid(descriptor) != identity.pid:
                raise BrokerError("pidfd target differs from the root PID binding")
            observed = self._proc_snapshot(identity.pid)
            observed_environment_sha256 = _sha256_bytes(_canonical_bytes(observed[4]))
            if (
                observed[0] != identity.starttime
                or observed[1] != identity.process_group_id
                or observed[2] != identity.parent_pid
                or observed_environment_sha256 != identity.environment_sha256
                or _sha256_bytes(observed[5]) != identity.command_sha256
            ):
                raise BrokerError("pidfd target identity changed before delivery")
            if request["action"] == "signal_supervisor":
                child = self._execution_supervisor_child_identity
                if child is None or child.parent_pid != identity.pid:
                    raise BrokerError(
                        "pidfd supervisor lacks an owned harness child binding"
                    )
                child_observed = self._proc_snapshot(child.pid)
                if (
                    child_observed[0] != child.starttime
                    or child_observed[1] != child.process_group_id
                    or child_observed[2] != identity.pid
                    or child_observed[3] in {"X", "x", "Z"}
                    or _sha256_bytes(_canonical_bytes(child_observed[4]))
                    != child.environment_sha256
                    or _sha256_bytes(child_observed[5]) != child.command_sha256
                ):
                    raise BrokerError(
                        "owned harness child changed before supervisor delivery"
                    )
            signal_value = {
                "-STOP": signal.SIGSTOP,
                "-CONT": signal.SIGCONT,
                "-TERM": signal.SIGTERM,
                "-KILL": signal.SIGKILL,
            }[expected_signal]
            try:
                with self._released_state_lock():
                    pidfd_send_signal(descriptor, signal_value, None, 0)
            except OSError as exc:
                raise BrokerError("pidfd signal delivery failed closed") from exc
        finally:
            os.close(descriptor)
        return CommandCapture(
            argv=expected_argv,
            returncode=0,
            stdout="",
            stderr="",
        )

    def _execute_mount_fd_bound(
        self,
        actual_argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> CommandCapture:
        descriptor = self._execution_mount_fd
        identity = self._execution_mount_identity
        parent_descriptor = self._execution_mount_parent_fd
        if descriptor is None or identity is None or parent_descriptor is None:
            raise BrokerError("fd-bound mount lacks a root target binding")
        parent_metadata = os.fstat(parent_descriptor)
        if (
            parent_metadata.st_uid != self._trusted_uid
            or stat.S_IMODE(parent_metadata.st_mode) != 0o711
        ):
            raise BrokerError("fd-bound mount parent protection disappeared")
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != (identity.device, identity.inode):
            raise BrokerError("fd-bound mount target identity changed")
        normalized = tuple(str(item) for item in actual_argv)
        if not normalized or normalized[-1] != str(identity.path):
            raise BrokerError("fd-bound mount command target differs")
        if normalized[0] == _UMOUNT:
            # An open descriptor on the mounted filesystem itself makes umount
            # busy. The root-protected parent prevents caller rename/replacement
            # and anchors lookup without retaining a reference into the mount.
            os.close(descriptor)
            self._execution_mount_fd = None
            fd_argv = (*normalized[:-1], f"/proc/self/fd/{parent_descriptor}/{identity.path.name}")
            capture = self._execute_with_pass_fd(
                fd_argv, timeout_seconds, descriptor=parent_descriptor,
            )
            protected = os.fstat(parent_descriptor)
            if (
                (protected.st_dev, protected.st_ino) != (parent_metadata.st_dev, parent_metadata.st_ino)
                or protected.st_uid != self._trusted_uid
                or stat.S_IMODE(protected.st_mode) != 0o711
            ):
                raise BrokerError("fd-bound unmount parent protection changed")
            return CommandCapture(
                argv=normalized, returncode=capture.returncode,
                stdout=capture.stdout, stderr=capture.stderr,
            )
        fd_argv = (*normalized[:-1], f"/proc/self/fd/{descriptor}")
        capture = self._execute_with_pass_fd(
            fd_argv,
            timeout_seconds,
            descriptor=descriptor,
        )
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino) != (identity.device, identity.inode):
            raise BrokerError("fd-bound mount target changed during execution")
        return CommandCapture(
            argv=normalized,
            returncode=capture.returncode,
            stdout=capture.stdout,
            stderr=capture.stderr,
        )

    def _revalidate_execution_target(
        self,
        request: Mapping[str, Any],
        binding: _RunBinding | None,
    ) -> None:
        action = str(request["action"])
        signal_actions = {
            "signal_runtime",
            "signal_harness",
            "signal_supervisor",
            "pause_peer_harness",
            "resume_peer_harness",
            "pause_cohort_harness",
            "resume_cohort_harness",
            "abort_paused_harness",
            "stop_peer_harness",
        }
        if action in signal_actions:
            if binding is None:
                raise BrokerError("signal action lacks a run binding")
            try:
                identity, _state = self._process_identity_for_action(request, binding)
            except BrokerError as exc:
                if action in {"abort_paused_harness", "stop_peer_harness"} and (
                    "process is absent" in str(exc)
                ):
                    return
                raise
            self._execution_process_identity = identity
            self._append_state_record(
                request,
                event="execution_target_bound",
                data={
                    "action": action,
                    "attempt_id": request.get("attempt_id"),
                    "pid": identity.pid,
                    "starttime": identity.starttime,
                    "process_group_id": identity.process_group_id,
                    "parent_pid": identity.parent_pid,
                    "environment_sha256": identity.environment_sha256,
                    "command_sha256": identity.command_sha256,
                    "role": identity.role,
                    "supervisor_child": (
                        None
                        if self._execution_supervisor_child_identity is None
                        else {
                            "pid": self._execution_supervisor_child_identity.pid,
                            "starttime": (
                                self._execution_supervisor_child_identity.starttime
                            ),
                            "process_group_id": (
                                self._execution_supervisor_child_identity.process_group_id
                            ),
                            "parent_pid": (
                                self._execution_supervisor_child_identity.parent_pid
                            ),
                            "environment_sha256": (
                                self._execution_supervisor_child_identity.environment_sha256
                            ),
                            "command_sha256": (
                                self._execution_supervisor_child_identity.command_sha256
                            ),
                            "role": self._execution_supervisor_child_identity.role,
                        }
                    ),
                    "binding": self._public_binding(binding),
                },
            )
            return
        if action in {"mount_enospc", "unmount_enospc"}:
            if binding is None:
                raise BrokerError("mount action lacks a run binding")
            target = self.layout.artifacts_root / binding.run_id
            identity = self._stable_directory_identity(
                target,
                owner_uid=self._required_evidence_owner_uid(),
                exact_mode=0o700,
            )
            try:
                target_descriptor = os.open(
                    target,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
            except OSError as exc:
                raise BrokerError("mount target descriptor is unavailable") from exc
            target_metadata = os.fstat(target_descriptor)
            if (
                not stat.S_ISDIR(target_metadata.st_mode)
                or target_metadata.st_uid != self._required_evidence_owner_uid()
                or stat.S_IMODE(target_metadata.st_mode) != 0o700
                or (target_metadata.st_dev, target_metadata.st_ino)
                != (identity[0], identity[1])
            ):
                os.close(target_descriptor)
                raise BrokerError("mount target descriptor identity differs")
            self._execution_mount_fd = target_descriptor
            parent = self.layout.artifacts_root
            try:
                parent_descriptor = os.open(
                    parent,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
            except OSError as exc:
                raise BrokerError("mount parent descriptor is unavailable") from exc
            parent_metadata = os.fstat(parent_descriptor)
            parent_path_metadata = parent.lstat()
            if (
                not stat.S_ISDIR(parent_metadata.st_mode)
                or parent_metadata.st_uid != self._required_evidence_owner_uid()
                or stat.S_IMODE(parent_metadata.st_mode) != 0o700
                or (parent_metadata.st_dev, parent_metadata.st_ino)
                != (parent_path_metadata.st_dev, parent_path_metadata.st_ino)
            ):
                os.close(parent_descriptor)
                raise BrokerError("mount parent identity differs")
            self._execution_mount_parent_fd = parent_descriptor
            self._execution_mount_parent_restore = (
                parent_metadata.st_uid,
                parent_metadata.st_gid,
                stat.S_IMODE(parent_metadata.st_mode),
                parent_metadata.st_dev,
                parent_metadata.st_ino,
            )
            try:
                os.fchown(parent_descriptor, self._trusted_uid, parent_metadata.st_gid)
                os.fchmod(parent_descriptor, 0o711)
            except OSError as exc:
                raise BrokerError("mount parent could not be root-protected") from exc
            protected = os.fstat(parent_descriptor)
            target_after_protection = target.lstat()
            if (
                protected.st_uid != self._trusted_uid
                or stat.S_IMODE(protected.st_mode) != 0o711
                or (target_after_protection.st_dev, target_after_protection.st_ino)
                != (target_metadata.st_dev, target_metadata.st_ino)
            ):
                raise BrokerError("mount target changed before parent protection")
            mounted = self._mount_record(target)
            if action == "mount_enospc" and mounted is not None:
                raise BrokerError("ENOSPC target is already mounted")
            peer_run_id = self._require_peer_id(request)
            loader = self._load_evidence_loader()
            try:
                target_evidence = (
                    loader.load_prelaunch_enospc_target(
                        binding.run_id,
                        mountpoint_created=True,
                    )
                    if action == "mount_enospc"
                    else loader.load_enospc_cleanup_target(
                        binding.run_id,
                        peer_run_id=peer_run_id,
                    )
                    if mounted is not None
                    else None
                )
            except Exception as exc:
                raise BrokerError("ENOSPC root target evidence differs") from exc
            if target_evidence is not None and (
                target_evidence.run_id != binding.run_id
                or target_evidence.contract_sha256 != binding.contract_sha256
                or _sha256_bytes(target_evidence.nonce.encode("utf-8"))
                != binding.nonce_sha256
                or target_evidence.cohort_sha256 != binding.cohort_sha256
                or target_evidence.peer_run_id != peer_run_id
                or Path(target_evidence.workspace) != target
            ):
                raise BrokerError("ENOSPC cleanup identity differs from root binding")
            self._execution_mount_identity = _MountIdentity(
                path=target,
                device=identity[0],
                inode=identity[1],
                ancestry=(),
                expect_mounted=mounted is not None,
            )
            if action == "mount_enospc":
                self._append_state_record(
                    request,
                    event="execution_target_bound",
                    data={
                        "action": action,
                        "binding": self._public_binding(binding),
                        "covered_directory": {
                            "path": str(target), "device": identity[0], "inode": identity[1]
                        },
                    },
                )
            return
        if (
            action
            in {
                "docker_start",
                "docker_container_inspect",
                "docker_logs",
                "docker_remove",
                "docker_exec_attest",
                "docker_restart",
            }
            and binding is not None
        ):
            attempt_id = str(request.get("attempt_id") or "")
            if (
                action == "docker_container_inspect"
                and attempt_id in _FROZEN_ATTEMPTS
                and _FROZEN_ATTEMPTS[attempt_id][2] == "non_runtime_conflict"
            ):
                argv = (
                    _DOCKER,
                    "inspect",
                    "--type",
                    "container",
                    binding.container_name,
                )
                capture = self._execute(argv, 30.0)
                if capture.argv != argv:
                    raise BrokerError(
                        "non-runtime absence inspector changed the exact argv"
                    )
                if capture.returncode == 0:
                    raise BrokerError(
                        "non-runtime conflict unexpectedly found a container"
                    )
                if not self._docker_not_found(capture):
                    raise BrokerError("non-runtime container absence is unproved")
                return
            self._inspect_container_live(
                binding,
                allow_absent=action in {"docker_container_inspect", "docker_remove"},
            )

    def _has_ambiguous_launch(self, run_id: str) -> bool:
        active = False
        for record in self._state_records():
            data = record["data"]
            if record["event"] == "container_removed" and data.get("run_id") == run_id:
                active = False
                continue
            binding = data.get("binding")
            if not isinstance(binding, Mapping) or binding.get("run_id") != run_id:
                continue
            if record["event"] == "action_claimed" and data.get("action") in {
                "docker_run",
                "docker_create",
            }:
                active = True
        return active

    def _container_binding_data(
        self,
        binding: _RunBinding,
        container_id: str,
    ) -> dict[str, Any]:
        if not _CONTAINER_ID_RE.fullmatch(container_id):
            raise BrokerError("root container identity is invalid")
        staging = self._root_staged_evidence_path(binding.run_id)
        try:
            metadata = staging.stat()
        except OSError as exc:
            raise BrokerError("root Docker bind source is unavailable") from exc
        if self._mount_record(staging) is None:
            raise BrokerError("root Docker bind source is not pinned")
        return {
            "run_id": binding.run_id,
            "contract_sha256": binding.contract_sha256,
            "nonce_sha256": binding.nonce_sha256,
            "cohort_sha256": binding.cohort_sha256,
            "container_name": binding.container_name,
            "container_id": container_id,
            "launch_sha256": binding.launch_sha256,
            "bind_source_path": str(staging),
            "bind_source_device": metadata.st_dev,
            "bind_source_inode": metadata.st_ino,
        }

    def _require_failed_seal_for_recovery_attestation(
        self, request: Mapping[str, Any]
    ) -> None:
        # Preserve forensic evidence without admitting GO after an ambiguous
        # root mutation. The normal final attestation still replays every
        # controller document and independently verifies live cleanup.
        batch_root = self.layout.batch_evidence_root(str(request["batch_id"]))
        path = batch_root / "control" / "seal.json"
        self._validate_batch_artifact_path(path, batch_root=batch_root)
        seal = _read_json(
            path, maximum=64 * 1024, owner_uid=self._required_evidence_owner_uid()
        )
        if (
            seal.get("schema") != "fortgym.m1b-live-acceptance-seal/v1"
            or seal.get("batch_id") != request["batch_id"]
            or seal.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or seal.get("plan_sha256") != FROZEN_PLAN_SHA256
            or seal.get("decision") != "INCOMPLETE_NO_GO"
        ):
            raise BrokerError("ambiguous root action permits only failed-seal attestation")

    def _validate_recovery_attestation_decision(
        self, request: Mapping[str, Any], seal: Mapping[str, Any]
    ) -> None:
        recovery = any(
            record["batch_id"] == request["batch_id"]
            and record.get("request_id") == request["request_id"]
            and record["event"] == "recovery_boundary"
            for record in self._state_records()
        )
        if recovery and seal.get("decision") != "INCOMPLETE_NO_GO":
            raise BrokerError("recovery attestation cannot export a GO decision")

    def _execute_final_attestation(
        self,
        request: Mapping[str, Any],
        *,
        grant_path: Path,
        snapshot: _LedgerSnapshot,
        actual_argv: Sequence[str],
    ) -> CommandCapture:
        """Write one self-excluding, root-owned export of the sealed batch."""

        caller_uid = self._required_evidence_owner_uid()
        batch_id = str(request["batch_id"])
        batch_root = self.layout.batch_evidence_root(batch_id)
        control = batch_root / "control"
        paths = {
            "gate_results": control / "gate-results.json",
            "decision": control / "decision.json",
            "evidence_manifest": control / "evidence-manifest.json",
            "seal": control / "seal.json",
            "post_seal_cleanup": batch_root / "post-seal-host-cleanup.json",
        }
        documents: dict[str, dict[str, Any]] = {}
        digests: dict[str, str] = {}
        for name, path in paths.items():
            self._validate_batch_artifact_path(path, batch_root=batch_root)
            document, digest = _read_json_with_digest(
                path,
                maximum=16 * 1024 * 1024,
                owner_uid=caller_uid,
            )
            documents[name] = document
            digests[name] = digest
        seal = documents["seal"]
        self._validate_recovery_attestation_decision(request, seal)
        expected_seal_keys = {
            "schema",
            "batch_id",
            "acceptance_sha256",
            "plan_sha256",
            "decision",
            "gate_results_sha256",
            "decision_sha256",
            "evidence_manifest_sha256",
        }
        if (
            set(seal) != expected_seal_keys
            or seal.get("schema") != "fortgym.m1b-live-acceptance-seal/v1"
            or seal.get("batch_id") != batch_id
            or seal.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or seal.get("plan_sha256") != FROZEN_PLAN_SHA256
            or seal.get("decision") not in {"GO", "INCOMPLETE_NO_GO"}
            or seal.get("gate_results_sha256") != digests["gate_results"]
            or seal.get("decision_sha256") != digests["decision"]
            or seal.get("evidence_manifest_sha256") != digests["evidence_manifest"]
            or digests["seal"] != request["parameters"]["controller_seal_sha256"]
            or digests["post_seal_cleanup"]
            != request["parameters"]["post_seal_cleanup_sha256"]
        ):
            raise BrokerError("controller seal or requested content address differs")
        attempts = self._validate_final_controller_documents(
            batch_id=batch_id,
            batch_root=batch_root,
            documents=documents,
            digests=digests,
            snapshot=snapshot,
            caller_uid=caller_uid,
        )
        canary = self._validate_final_canary_cleanup(
            request,
            post=documents["post_seal_cleanup"],
            seal_sha256=digests["seal"],
            caller_uid=caller_uid,
        )
        self._validate_final_live_residue(
            request,
            snapshot=snapshot,
            canary_name=str(canary["name"]),
        )
        root_records, public_receipts = self._final_receipt_inventory(
            request,
            batch_root=batch_root,
            caller_uid=caller_uid,
        )
        request_id = str(request["request_id"])
        claim_path = self.layout.claim_root / f"{request_id}.json"
        claim_sha256 = _sha256_file(
            claim_path,
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        grant_sha256 = _sha256_file(
            grant_path,
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        claim = _read_json(
            claim_path,
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        request_sha256 = str(claim.get("request_sha256") or "")
        if (
            claim.get("schema") != CLAIM_SCHEMA
            or claim.get("request_id") != request_id
            or not _SHA256_RE.fullmatch(request_sha256)
        ):
            raise BrokerError("current attestation claim identity differs")
        excluded_self = {
            "request_id": request_id,
            "request_sha256": request_sha256,
            "claim_sha256": claim_sha256,
            "grant_sha256": grant_sha256,
            "predicted_receipt_path": (f"broker-client/CLEANUP/{request_id}.json"),
            "predicted_receipt_digest_derivation": (
                "sha256(canonical_json(root_receipt_without_stdout_stderr)+LF)"
            ),
            "root_records_excludes": ["claim", "grant", "receipt"],
            "public_receipts_excludes": ["receipt"],
            "reason": "self_referential_final_attestation_boundary",
        }
        attestation = {
            "schema": FINAL_ATTESTATION_SCHEMA,
            "ok": True,
            "batch_id": batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "authority_expires_at": AUTHORITY_EXPIRES_AT.isoformat(),
            "packet": {
                "packet_sha256": _sha256_file(
                    self.layout.packet_manifest_path,
                    maximum=16 * 1024 * 1024,
                    owner_uid=self._trusted_uid,
                ),
                "source_manifest_sha256": _sha256_file(
                    self.layout.source_manifest_path,
                    maximum=16 * 1024 * 1024,
                    owner_uid=self._trusted_uid,
                ),
            },
            "controller": {
                "batch_ledger_sha256": snapshot.batch_file_sha256,
                "attempt_ledger_sha256": snapshot.attempt_file_sha256,
                "batch_head_sha256": snapshot.phase.batch_head_sha256,
                "attempt_head_sha256": (
                    snapshot.attempt_hashes[-1]
                    if snapshot.attempt_hashes
                    else _ZERO_SHA256
                ),
                "seal_sha256": digests["seal"],
                "post_seal_cleanup_sha256": digests["post_seal_cleanup"],
                "decision": seal["decision"],
                "decision_sha256": digests["decision"],
                "gate_results_sha256": digests["gate_results"],
                "evidence_manifest_sha256": digests["evidence_manifest"],
            },
            "attempts": attempts,
            "root_records": root_records,
            "public_receipts": public_receipts,
            "excluded_self": excluded_self,
            "canary": {
                "created": True,
                "removed": True,
                "absence_verified": True,
            },
            "provider_calls": 0,
            "provider_cost_usd": 0,
            "shell": False,
        }
        # Recheck every controller file after inventory construction; the root
        # export never signs a mixture of caller generations.
        for name, path in paths.items():
            if (
                _sha256_file(
                    path,
                    maximum=16 * 1024 * 1024,
                    owner_uid=caller_uid,
                )
                != digests[name]
            ):
                raise BrokerError("sealed controller evidence changed during export")
        output_path = self.layout.broker_attestation_path(batch_id)
        output_directory = output_path.parent
        batches = output_directory.parent
        _validate_directory(batches, owner_uid=self._trusted_uid, exact_mode=0o700)
        try:
            os.mkdir(output_directory, mode=0o700)
        except FileExistsError:
            pass
        _validate_directory(
            output_directory, owner_uid=self._trusted_uid, exact_mode=0o700
        )
        _write_once(output_path, attestation, owner_uid=self._trusted_uid)
        output_sha256 = _sha256_file(
            output_path,
            maximum=16 * 1024 * 1024,
            owner_uid=self._trusted_uid,
        )
        safe = {
            "schema": "fortgym.m1b-root-broker-attestation-result/v1",
            "ok": True,
            "batch_id": batch_id,
            "path": str(output_path),
            "sha256": output_sha256,
        }
        return CommandCapture(
            argv=tuple(str(item) for item in actual_argv),
            returncode=0,
            stdout=json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n",
            stderr="",
        )

    @staticmethod
    def _validate_batch_artifact_path(path: Path, *, batch_root: Path) -> None:
        if not path.is_absolute() or "\0" in str(path):
            raise BrokerError("sealed evidence path is invalid")
        try:
            path.relative_to(batch_root)
        except ValueError as exc:
            raise BrokerError("sealed evidence path escaped its batch") from exc
        current = path.parent
        while True:
            try:
                metadata = current.lstat()
            except OSError as exc:
                raise BrokerError("sealed evidence ancestry is unavailable") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise BrokerError("sealed evidence ancestry is unsafe")
            if current == batch_root:
                break
            if batch_root not in current.parents:
                raise BrokerError("sealed evidence ancestry escaped its batch")
            current = current.parent

    def _validate_final_controller_documents(
        self,
        *,
        batch_id: str,
        batch_root: Path,
        documents: Mapping[str, Mapping[str, Any]],
        digests: Mapping[str, str],
        snapshot: _LedgerSnapshot,
        caller_uid: int,
    ) -> dict[str, int]:
        gate_results = documents["gate_results"]
        decision = documents["decision"]
        manifest = documents["evidence_manifest"]
        if (
            set(gate_results)
            != {"schema", "batch_id", "acceptance_sha256", "plan_sha256", "gates"}
            or gate_results.get("schema")
            != "fortgym.m1b-live-acceptance-gate-results/v1"
            or gate_results.get("batch_id") != batch_id
            or gate_results.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or gate_results.get("plan_sha256") != FROZEN_PLAN_SHA256
            or not isinstance(gate_results.get("gates"), list)
            or len(gate_results["gates"]) != len(_FROZEN_GATE_ORDER)
        ):
            raise BrokerError("sealed gate results identity differs")
        self._install_repo_import_path()
        from fort_gym.bench.run.live_acceptance import FROZEN_GATE_PLAN

        for index, (row, gate) in enumerate(
            zip(gate_results["gates"], FROZEN_GATE_PLAN), start=1
        ):
            if (
                not isinstance(row, Mapping)
                or set(row)
                != {
                    "gate",
                    "status",
                    "criteria_passed",
                    "failure_code",
                    "evidence",
                    "local_credit",
                    "attempts",
                    "authorization_identity_sha256",
                    "attempt_ledger_head_sha256",
                }
                or row.get("gate") != gate.payload(gate_index=index)
                or row.get("status") not in {"PASS", "PASS_LOCAL", "FAIL", "NOT_RUN"}
                or not isinstance(row.get("criteria_passed"), list)
                or not isinstance(row.get("evidence"), list)
                or not isinstance(row.get("attempts"), Mapping)
                or not _SHA256_RE.fullmatch(
                    str(row.get("attempt_ledger_head_sha256") or "")
                )
            ):
                raise BrokerError("sealed gate result row differs from frozen plan")
        decision_keys = {
            "schema",
            "batch_id",
            "acceptance_sha256",
            "plan_sha256",
            "decision",
            "hard_gate_count",
            "hard_gates_passed",
            "failed_or_incomplete_gates",
            "real_runtime_attempt_limit",
            "real_runtime_attempts_started",
            "real_runtime_attempts_completed",
            "non_runtime_attempts_started",
            "non_runtime_attempts_completed",
            "incomplete_attempt_ids",
            "missing_attempt_ids",
            "reasons",
            "provider_calls",
            "provider_cost_usd",
        }
        real_started = sum(
            attempt.kind == "real_runtime" and attempt.identity_sha256 is not None
            for attempt in snapshot.attempts.values()
        )
        real_completed = sum(
            attempt.kind == "real_runtime" and attempt.completed
            for attempt in snapshot.attempts.values()
        )
        nonruntime_started = sum(
            attempt.kind == "non_runtime_conflict"
            and attempt.identity_sha256 is not None
            for attempt in snapshot.attempts.values()
        )
        nonruntime_completed = sum(
            attempt.kind == "non_runtime_conflict" and attempt.completed
            for attempt in snapshot.attempts.values()
        )
        incomplete = sorted(
            attempt.attempt_id
            for attempt in snapshot.attempts.values()
            if attempt.identity_sha256 is not None and not attempt.completed
        )
        missing = sorted(
            attempt.attempt_id
            for attempt in snapshot.attempts.values()
            if attempt.identity_sha256 is None
        )
        if (
            set(decision) != decision_keys
            or decision.get("schema") != "fortgym.m1b-live-acceptance-decision/v1"
            or decision.get("batch_id") != batch_id
            or decision.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or decision.get("plan_sha256") != FROZEN_PLAN_SHA256
            or decision.get("decision") not in {"GO", "INCOMPLETE_NO_GO"}
            or decision.get("hard_gate_count") != len(_FROZEN_GATE_ORDER)
            or isinstance(decision.get("hard_gates_passed"), bool)
            or not isinstance(decision.get("hard_gates_passed"), int)
            or not 0 <= int(decision["hard_gates_passed"]) <= len(_FROZEN_GATE_ORDER)
            or decision.get("real_runtime_attempt_limit") != 26
            or decision.get("real_runtime_attempts_started") != real_started
            or decision.get("real_runtime_attempts_completed") != real_completed
            or decision.get("non_runtime_attempts_started") != nonruntime_started
            or decision.get("non_runtime_attempts_completed") != nonruntime_completed
            or decision.get("incomplete_attempt_ids") != incomplete
            or decision.get("missing_attempt_ids") != missing
            or decision.get("provider_calls") != 0
            or decision.get("provider_cost_usd") != 0
            or not isinstance(decision.get("failed_or_incomplete_gates"), list)
            or not isinstance(decision.get("reasons"), list)
        ):
            raise BrokerError("sealed controller decision differs from root replay")
        if decision["decision"] == "GO" and (
            (real_started, real_completed) != (26, 26)
            or (nonruntime_started, nonruntime_completed) != (1, 1)
            or incomplete
            or missing
            or decision["hard_gates_passed"] != len(_FROZEN_GATE_ORDER)
            or decision["failed_or_incomplete_gates"]
            or decision["reasons"]
            or any(
                row["status"] not in {"PASS", "PASS_LOCAL"}
                for row in gate_results["gates"]
            )
        ):
            raise BrokerError("GO decision lacks the complete frozen matrix")
        if decision["decision"] == "INCOMPLETE_NO_GO" and not decision["reasons"]:
            raise BrokerError("incomplete decision lacks a bounded reason")
        self._validate_final_manifest(
            manifest,
            batch_id=batch_id,
            batch_root=batch_root,
            caller_uid=caller_uid,
        )
        if (
            documents["seal"].get("decision") != decision["decision"]
            or documents["seal"].get("decision_sha256") != digests["decision"]
        ):
            raise BrokerError("sealed decision binding differs")
        return {
            "planned": 27,
            "real_runtime_started": real_started,
            "real_runtime_completed": real_completed,
            "non_runtime_started": nonruntime_started,
            "non_runtime_completed": nonruntime_completed,
        }

    def _validate_final_manifest(
        self,
        manifest: Mapping[str, Any],
        *,
        batch_id: str,
        batch_root: Path,
        caller_uid: int,
    ) -> None:
        artifacts = manifest.get("artifacts")
        if (
            set(manifest)
            != {"schema", "batch_id", "acceptance_sha256", "plan_sha256", "artifacts"}
            or manifest.get("schema")
            != "fortgym.m1b-live-acceptance-evidence-manifest/v1"
            or manifest.get("batch_id") != batch_id
            or manifest.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or manifest.get("plan_sha256") != FROZEN_PLAN_SHA256
            or not isinstance(artifacts, list)
            or not artifacts
            or len(artifacts) > 4096
        ):
            raise BrokerError("sealed evidence manifest identity differs")
        observed_paths: list[str] = []
        for reference in artifacts:
            if (
                not isinstance(reference, Mapping)
                or set(reference) != {"path", "sha256", "size_bytes"}
                or not isinstance(reference.get("path"), str)
                or not _SHA256_RE.fullmatch(str(reference.get("sha256") or ""))
                or isinstance(reference.get("size_bytes"), bool)
                or not isinstance(reference.get("size_bytes"), int)
                or int(reference["size_bytes"]) < 0
            ):
                raise BrokerError("sealed manifest reference is malformed")
            relative = str(reference["path"])
            relative_path = Path(relative)
            if (
                relative_path.is_absolute()
                or relative in {"", "."}
                or ".." in relative_path.parts
                or "\0" in relative
            ):
                raise BrokerError("sealed manifest reference escaped its batch")
            observed_paths.append(relative)
            if relative == "contract/infra/m1b/acceptance.yaml":
                artifact_path = self.layout.acceptance_path
                owner_uid = self._trusted_uid
            else:
                artifact_path = batch_root / relative_path
                self._validate_batch_artifact_path(artifact_path, batch_root=batch_root)
                owner_uid = caller_uid
            metadata = artifact_path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != owner_uid
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or metadata.st_size != reference["size_bytes"]
                or _sha256_file(
                    artifact_path,
                    maximum=64 * 1024 * 1024,
                    owner_uid=owner_uid,
                    allow_empty=True,
                )
                != reference["sha256"]
            ):
                raise BrokerError("sealed manifest artifact differs")
        if observed_paths != sorted(observed_paths) or len(set(observed_paths)) != len(
            observed_paths
        ):
            raise BrokerError("sealed manifest paths are not sorted and unique")

    def _validate_final_canary_cleanup(
        self,
        request: Mapping[str, Any],
        *,
        post: Mapping[str, Any],
        seal_sha256: str,
        caller_uid: int,
    ) -> Mapping[str, Any]:
        cleanup = post.get("cleanup")
        expected_post_keys = {
            "schema",
            "batch_id",
            "acceptance_sha256",
            "plan_sha256",
            "controller_seal_sha256",
            "cleanup",
        }
        expected_cleanup_keys = {
            "present",
            "removed",
            "name",
            "container_id",
            "container_absent",
            "container_absence_returncode",
            "process_id",
            "process_start_ticks",
            "process_absent",
            "workspace",
            "workspace_absent",
            "initial_container_state_sha256",
            "pre_removal_container_state_sha256",
            "pre_removal_broker_evidence_sha256",
            "creation_broker_evidence_sha256",
            "removal_broker_evidence_sha256",
            "absence_broker_evidence_sha256",
        }
        active = _read_json(
            self.layout.grant_root / "batch-canary-active.json",
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        removed = _read_json(
            self.layout.grant_root / "batch-canary-removed.json",
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        absence = _read_json(
            self.layout.grant_root / "batch-canary-absence.json",
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        if (
            set(post) != expected_post_keys
            or post.get("schema") != "fortgym.m1b-post-seal-host-cleanup/v1"
            or post.get("batch_id") != request["batch_id"]
            or post.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or post.get("plan_sha256") != FROZEN_PLAN_SHA256
            or post.get("controller_seal_sha256") != seal_sha256
            or not isinstance(cleanup, Mapping)
            or set(cleanup) != expected_cleanup_keys
            or cleanup.get("present") is not True
            or cleanup.get("removed") is not True
            or cleanup.get("name") != active.get("name")
            or cleanup.get("container_id") != active.get("container_id")
            or cleanup.get("container_absent") is not True
            or cleanup.get("container_absence_returncode") != 0
            or cleanup.get("process_absent") is not True
            or cleanup.get("workspace_absent") is not True
            or removed != {**active, "removed": True}
            or absence.get("absence_verified") is not True
            or absence.get("stdout_sha256") != _sha256_bytes(b"")
            or absence.get("container_id") != active.get("container_id")
        ):
            raise BrokerError("post-seal canary cleanup differs from root evidence")
        workspace = Path(str(cleanup.get("workspace") or ""))
        expected_workspace = (
            self.layout.state_root / "canary" / str(request["batch_id"])
        )
        if workspace != expected_workspace or workspace.exists():
            raise BrokerError("post-seal canary workspace residue differs")
        for name in (
            "initial_container_state_sha256",
            "pre_removal_container_state_sha256",
            "pre_removal_broker_evidence_sha256",
            "creation_broker_evidence_sha256",
            "removal_broker_evidence_sha256",
            "absence_broker_evidence_sha256",
        ):
            if not _SHA256_RE.fullmatch(str(cleanup.get(name) or "")):
                raise BrokerError("post-seal canary digest is invalid")
        if (
            cleanup["initial_container_state_sha256"]
            != cleanup["pre_removal_container_state_sha256"]
        ):
            raise BrokerError("canary state changed before removal")
        del caller_uid
        return dict(cleanup)

    def _validate_final_live_residue(
        self,
        request: Mapping[str, Any],
        *,
        snapshot: _LedgerSnapshot,
        canary_name: str,
    ) -> None:
        canary_argv = (
            _DOCKER,
            "ps",
            "--all",
            "--no-trunc",
            "--filter",
            f"name=^/{canary_name}$",
            "--format",
            "{{.ID}}",
        )
        canary_capture = self._execute(canary_argv, 30.0)
        if (
            canary_capture.argv != canary_argv
            or canary_capture.returncode != 0
            or canary_capture.stdout != ""
            or canary_capture.stderr != ""
        ):
            raise BrokerError("final root canary absence recheck failed")
        managed_argv = (
            _DOCKER,
            "ps",
            "--all",
            "--no-trunc",
            "--filter",
            "label=fortgym.m1b.managed=true",
            "--format",
            "{{.ID}}",
        )
        managed_capture = self._execute(managed_argv, 30.0)
        if (
            managed_capture.argv != managed_argv
            or managed_capture.returncode != 0
            or managed_capture.stdout != ""
            or managed_capture.stderr != ""
        ):
            raise BrokerError("final root managed-container residue recheck failed")
        _validate_directory(
            self.layout.bind_source_root,
            owner_uid=self._trusted_uid,
            exact_mode=0o700,
        )
        if self._mount_record(self.layout.bind_source_root) is not None or any(
            self.layout.bind_source_root.iterdir()
        ):
            raise BrokerError("final root Docker staging residue remains")
        started_run_ids = {
            self._expected_run_id(str(request["batch_id"]), item.gate_id, item.role)
            for item in snapshot.attempts.values()
            if item.kind == "real_runtime" and item.identity_sha256 is not None
        }
        for run_id in started_run_ids:
            if self._root_container_id(run_id) is not None:
                raise BrokerError("root container mirror retains live residue")
            if self._mount_record(self.layout.artifacts_root / run_id) is not None:
                raise BrokerError("root mount table retains run residue")
        for proc_path in Path("/proc").iterdir():
            if not proc_path.name.isdigit():
                continue
            pid = int(proc_path.name)
            try:
                environment_raw = self._read_proc_bytes(pid, "environ", 256 * 1024)
            except BrokerError:
                continue
            for item in environment_raw.split(b"\0"):
                if item.startswith((b"FORT_GYM_RUN_ID=", b"FORTGYM_RUN_ID=")):
                    run_id = item.split(b"=", 1)[1].decode("utf-8", errors="replace")
                    if run_id in started_run_ids:
                        raise BrokerError("root process table retains run residue")

    @staticmethod
    def _expected_run_id(batch_id: str, gate_id: str, role: str) -> str:
        return (
            f"m1b-{gate_id.lower().replace('-', '')}-{role.replace('_', '')}-"
            + _sha256_bytes(f"{batch_id}\0{gate_id}".encode())[:12]
        )

    def _final_receipt_inventory(
        self,
        request: Mapping[str, Any],
        *,
        batch_root: Path,
        caller_uid: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        current_id = str(request["request_id"])
        inventories: dict[str, list[dict[str, str]]] = {
            "claims": [],
            "grants": [],
            "receipts": [],
        }
        root_receipts: dict[str, tuple[dict[str, Any], str]] = {}
        for label, root, schema in (
            ("claims", self.layout.claim_root, CLAIM_SCHEMA),
            ("grants", self.layout.grant_root, GRANT_SCHEMA),
            ("receipts", self.layout.receipt_root, RECEIPT_SCHEMA),
        ):
            for path in sorted(root.glob("*.json")):
                document = _read_json(
                    path,
                    maximum=_MAX_EVIDENCE_BYTES,
                    owner_uid=self._trusted_uid,
                )
                if document.get("schema") != schema:
                    continue
                if document.get("batch_id") != request["batch_id"]:
                    continue
                request_id = str(document.get("request_id") or "")
                if not _SHA256_RE.fullmatch(request_id):
                    raise BrokerError("root record request identity is malformed")
                if request_id == current_id:
                    continue
                digest = _sha256_file(
                    path,
                    maximum=_MAX_EVIDENCE_BYTES,
                    owner_uid=self._trusted_uid,
                )
                inventories[label].append({"id": path.stem, "sha256": digest})
                if label == "receipts":
                    root_receipts[request_id] = (document, digest)
        if any(
            len(items) != len({item["id"] for item in items})
            for items in inventories.values()
        ):
            raise BrokerError("root record inventory contains duplicate identities")
        aggregate_sha256 = _sha256_bytes(_canonical_bytes(inventories))
        root_records: dict[str, Any] = {
            **inventories,
            "aggregate_sha256": aggregate_sha256,
        }
        public_root = batch_root / "broker-client"
        try:
            public_metadata = public_root.lstat()
        except OSError as exc:
            raise BrokerError("public broker receipt root is absent") from exc
        if stat.S_ISLNK(public_metadata.st_mode) or not stat.S_ISDIR(
            public_metadata.st_mode
        ):
            raise BrokerError("public broker receipt root is unsafe")
        public: list[dict[str, Any]] = []
        for path in sorted(public_root.rglob("*.json")):
            relative = path.relative_to(batch_root).as_posix()
            if path.is_symlink():
                raise BrokerError("public broker receipt is a symlink")
            document, digest = _read_json_with_digest(
                path,
                maximum=_MAX_EVIDENCE_BYTES,
                owner_uid=caller_uid,
            )
            request_id = str(document.get("request_id") or "")
            if request_id == current_id:
                raise BrokerError("current attestation receipt exists before export")
            root_item = root_receipts.get(request_id)
            if root_item is None:
                raise BrokerError("public broker receipt lacks a root counterpart")
            root_document, root_digest = root_item
            expected_public = {
                key: value
                for key, value in root_document.items()
                if key not in {"stdout", "stderr"}
            }
            if document != expected_public:
                raise BrokerError("public broker receipt differs from root evidence")
            public.append(
                {
                    "request_id": request_id,
                    "path": relative,
                    "sha256": digest,
                    "root_receipt_sha256": root_digest,
                }
            )
        return root_records, public

    def _load_binding(
        self,
        request: Mapping[str, Any],
        *,
        caller_uid: int,
    ) -> _RunBinding | None:
        run_id = request.get("run_id")
        if run_id is None:
            return None
        self._install_repo_import_path()
        from fort_gym.bench.run.runtime_contract import ProviderPolicy, RuntimeContract
        from fort_gym.bench.run.runtime_controller import (
            DockerRuntimeController,
            RuntimeFaultProfile,
            RuntimeTestFault,
        )

        launch_path = self.layout.control_root / str(run_id) / "launch.json"
        launch, launch_sha256 = _read_json_with_digest(
            launch_path,
            maximum=256 * 1024,
            owner_uid=caller_uid,
        )
        expected_launch_keys = {"schema", "run_id", "created_at", "contract", "request"}
        attempt_id = str(request.get("attempt_id") or "")
        planned_gate, planned_role, _planned_kind = _FROZEN_ATTEMPTS[attempt_id]
        if planned_gate == "COLD-RETRY" and planned_role == "suppressed_first":
            expected_launch_keys.add("test_fault")
        if planned_gate == "OOM":
            expected_launch_keys.add("runtime_fault_profile")
        if planned_gate == "ENOSPC":
            expected_launch_keys.add("workspace_fault_profile")
        if (
            set(launch) != expected_launch_keys
            or launch.get("schema") != "fortgym.m1b-service-launch/v1"
            or launch.get("run_id") != run_id
        ):
            raise BrokerError("durable service launch identity differs")
        created_at = launch.get("created_at")
        try:
            created = datetime.fromisoformat(str(created_at))
        except ValueError as exc:
            raise BrokerError("durable service launch timestamp is invalid") from exc
        if (
            created.tzinfo is None
            or created.utcoffset() is None
            or created.utcoffset().total_seconds() != 0
        ):
            raise BrokerError("durable service launch timestamp is not UTC")
        identity = launch.get("contract")
        if not isinstance(identity, Mapping):
            raise BrokerError("durable service launch lacks a contract")
        try:
            runtime = identity["runtime"]
            seed = identity["seed"]
            rpc = identity["rpc"]
            paths = identity["paths"]
            cotenancy = identity["cotenancy"]
            if not all(
                isinstance(item, Mapping)
                for item in (runtime, seed, rpc, paths, cotenancy)
            ):
                raise TypeError
            peers = tuple(str(value) for value in cotenancy["peer_run_ids"])
            contract = RuntimeContract(
                run_id=str(identity["run_id"]),
                backend=str(identity["backend"]),
                model=str(identity["model"]),
                port=int(rpc["port"]),
                nonce=str(rpc["nonce"]),
                image_manifest_sha256=str(runtime["image_manifest_sha256"]),
                image_config_sha256=str(runtime["image_config_sha256"]),
                image_archive_sha256=str(runtime["image_archive_sha256"]),
                seed_tree_sha256=str(seed["tree_sha256"]),
                seed_world_sha256=str(seed["world_sha256"]),
                code_sha256=str(identity["code_sha256"]),
                db_path=Path(str(paths["db"])),
                artifacts_root=Path(str(paths["artifacts_root"])),
                control_root=Path(str(paths["control_root"])),
                dfroot=Path(str(paths["dfroot"])),
                seed_save=str(seed["seed_save"]),
                runtime_save=str(seed["runtime_save"]),
                cohort_run_ids=tuple(sorted((str(run_id), *peers))),
                provider=ProviderPolicy(),
                scripted=True,
                runtime_classification=str(runtime["classification"]),
                source_reproducible=bool(runtime["source_reproducible"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerError("durable launch contract is malformed") from exc
        nonce_sha256 = _sha256_bytes(contract.nonce.encode("utf-8"))
        expected_run_id = (
            f"m1b-{planned_gate.lower().replace('-', '')}-"
            f"{planned_role.replace('_', '')}-"
            + _sha256_bytes(f"{request['batch_id']}\0{planned_gate}".encode())[:12]
        )
        cohort_roles: tuple[str, ...]
        if planned_gate == "CO-8":
            cohort_roles = tuple(f"run_{index:02d}" for index in range(1, 9))
        elif planned_gate in {
            "DF-KILL",
            "HARNESS-KILL",
            "OOM",
            "ENOSPC",
            "CONTAINER-RESTART",
            "DAEMON-RESTART",
        }:
            cohort_roles = ("target", "peer")
        else:
            cohort_roles = (planned_role,)
        cohort_prefix = _sha256_bytes(
            f"{request['batch_id']}\0{planned_gate}".encode()
        )[:12]
        expected_cohort = tuple(
            sorted(
                f"m1b-{planned_gate.lower().replace('-', '')}-"
                f"{role.replace('_', '')}-{cohort_prefix}"
                for role in cohort_roles
            )
        )
        expected_port = (
            58_001
            if (planned_gate == "COLD-RETRY" and planned_role == "replacement_second")
            else 58_000 + contract.cohort_run_ids.index(contract.run_id)
        )
        launch_request = {
            "max_steps": 20,
            "ticks_per_step": 200,
            "evaluation_protocol": None,
            "preserve_save": False,
            "memory_window": 0,
            "safe": True,
        }
        if (
            contract.environment_identity() != dict(identity)
            or contract.run_id != run_id
            or contract.run_id != expected_run_id
            or contract.cohort_run_ids != expected_cohort
            or contract.contract_sha256 != request.get("contract_sha256")
            or nonce_sha256 != request.get("nonce_sha256")
            or contract.cohort_digest != request.get("cohort_sha256")
            or contract.db_path != self.layout.db_path
            or contract.control_root != self.layout.control_root
            or contract.artifacts_root != self.layout.artifacts_root
            or contract.dfroot != _CANONICAL_DFROOT
            or contract.provider.enabled
            or not contract.scripted
            or contract.backend != "dfhack"
            or contract.model != "dfhack-governed-scripted"
            or contract.runtime_classification != "private_stock_archive_seeded"
            or contract.source_reproducible is not False
            or contract.image_manifest_sha256 != _RUNTIME_IMAGE_MANIFEST_SHA256
            or contract.image_config_sha256 != _RUNTIME_IMAGE_CONFIG_SHA256
            or contract.image_archive_sha256 != _RUNTIME_ARCHIVE_SHA256
            or contract.seed_tree_sha256 != _SEED_TREE_SHA256
            or contract.seed_world_sha256 != _SEED_WORLD_SHA256
            or contract.seed_save != "seed_region3_fresh"
            or contract.runtime_save != f"m1b-{run_id}"
            or contract.port != expected_port
            or (
                self._measurement_code_sha256 is not None
                and contract.code_sha256 != self._measurement_code_sha256
            )
            or launch.get("request") != launch_request
        ):
            raise BrokerError("broker request does not match the durable run contract")

        expected_test_fault = (
            {
                "schema": "fortgym.m1b-test-startup-fault/v1",
                "name": "suppress_rpc_readiness",
                "injected": True,
                "attempt_index": 1,
            }
            if planned_gate == "COLD-RETRY" and planned_role == "suppressed_first"
            else None
        )
        if launch.get("test_fault") != expected_test_fault:
            raise BrokerError("startup fault profile differs from its frozen slot")

        expected_runtime_profile: Mapping[str, Any] | None = None
        if planned_gate == "OOM":
            if planned_role == "target":
                expected_runtime_profile = {
                    "schema": "fortgym.m1b-runtime-fault-profile/v1",
                    "cohort_kind": "oom_256m_target_peer",
                    "role": "target",
                    "name": "oom_256m",
                    "memory_bytes": 268_435_456,
                    "memory_swap_bytes": 268_435_456,
                    "test_only": True,
                }
            else:
                expected_runtime_profile = {
                    "schema": "fortgym.m1b-runtime-fault-profile/v1",
                    "cohort_kind": "oom_256m_target_peer",
                    "role": "peer",
                    "name": "normal_4g",
                    "memory_bytes": 4_294_967_296,
                    "memory_swap_bytes": 4_294_967_296,
                    "test_only": True,
                }
        if launch.get("runtime_fault_profile") != expected_runtime_profile:
            raise BrokerError("runtime fault profile differs from its frozen slot")

        expected_workspace_profile: Mapping[str, Any] | None = None
        if planned_gate == "ENOSPC":
            expected_workspace_profile = {
                "schema": "fortgym.m1b-workspace-fault-profile/v1",
                "cohort_kind": "enospc_16m_target_peer",
                "role": planned_role,
                "name": "enospc_16m"
                if planned_role == "target"
                else "normal_workspace",
                "filesystem": "tmpfs" if planned_role == "target" else "host",
                "size_bytes": 16_777_216 if planned_role == "target" else None,
                "test_only": True,
            }
        if launch.get("workspace_fault_profile") != expected_workspace_profile:
            raise BrokerError("workspace fault profile differs from its frozen slot")
        peer_run_id = request.get("peer_run_id")
        if peer_run_id is not None and (
            peer_run_id not in contract.cohort_run_ids or peer_run_id == contract.run_id
        ):
            raise BrokerError("broker peer identity escapes the exact cohort")

        profile = None
        profile_value = launch.get("runtime_fault_profile")
        if isinstance(profile_value, Mapping) and profile_value.get("role") == "target":
            if profile_value.get("name") != RuntimeFaultProfile.OOM_256M.value:
                raise BrokerError("runtime fault profile is unsupported")
            profile = RuntimeFaultProfile.OOM_256M
        test_fault = None
        test_value = launch.get("test_fault")
        if isinstance(test_value, Mapping):
            if test_value.get("name") != RuntimeTestFault.SUPPRESS_RPC_READINESS.value:
                raise BrokerError("startup fault profile is unsupported")
            test_fault = RuntimeTestFault.SUPPRESS_RPC_READINESS
        controller = DockerRuntimeController(
            contract,
            entrypoint_path=self.layout.entrypoint_path,
            evidence_dir=self.layout.control_root
            / contract.run_id
            / "attempts"
            / "attempt-0001"
            / "runtime",
            image_archive_path=self.layout.image_archive,
            docker_executable="docker",
            allow_test_faults=test_fault is not None,
            test_fault=test_fault,
            allow_test_fault_profile=profile is not None,
            fault_profile=profile,
        )
        selected_reference = self._root_image_reference(str(request["batch_id"]))
        if selected_reference is not None:
            controller._resolved_image_reference = selected_reference
        container_id = self._container_id_for_action(
            contract.run_id,
            str(request.get("action") or ""),
        )
        result = _RunBinding(
            run_id=contract.run_id,
            contract_sha256=contract.contract_sha256,
            nonce_sha256=nonce_sha256,
            cohort_sha256=contract.cohort_digest,
            container_name=controller.container_name,
            container_id=container_id,
            port=contract.port,
            runtime_controller=controller,
            launch=launch,
            launch_sha256=launch_sha256,
        )
        if (
            container_id is None
            and request.get("action")
            not in {"docker_image_inspect", "docker_run", "docker_create"}
            and self._has_ambiguous_launch(result.run_id)
        ):
            document, _capture = self._inspect_container_live(
                result,
                allow_absent=True,
            )
            if document is not None:
                container_id = str(document["Id"]).lower()
                self._append_state_record(
                    request,
                    event="container_bound",
                    data=self._container_binding_data(result, container_id),
                )
                result = _RunBinding(
                    run_id=result.run_id,
                    contract_sha256=result.contract_sha256,
                    nonce_sha256=result.nonce_sha256,
                    cohort_sha256=result.cohort_sha256,
                    container_name=result.container_name,
                    container_id=container_id,
                    port=result.port,
                    runtime_controller=result.runtime_controller,
                    launch=result.launch,
                    launch_sha256=result.launch_sha256,
                )
        return result

    def _derive_command(
        self,
        request: Mapping[str, Any],
        binding: _RunBinding | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...], float]:
        action = str(request["action"])
        parameters = request["parameters"]
        if not isinstance(parameters, Mapping):
            raise BrokerError("broker action parameters are invalid")
        if action == "attest_broker_evidence":
            expected = {"controller_seal_sha256", "post_seal_cleanup_sha256"}
            if (
                binding is not None
                or request.get("grant_kind") != "batch_canary"
                or set(parameters) != expected
                or any(
                    not _SHA256_RE.fullmatch(str(parameters.get(name) or ""))
                    for name in expected
                )
            ):
                raise BrokerError("final broker attestation parameters differ")
            logical = (
                "fortgym-root-broker",
                "attest-broker-evidence",
                str(request["batch_id"]),
                str(parameters["controller_seal_sha256"]),
                str(parameters["post_seal_cleanup_sha256"]),
            )
            return logical, logical, 60.0
        if action.startswith("canary_"):
            if binding is not None or request.get("grant_kind") != "batch_canary":
                raise BrokerError("canary action escaped its batch grant")
            return self._derive_canary(action, request, parameters)
        if binding is None:
            raise BrokerError("broker action requires one exact run binding")
        controller = binding.runtime_controller
        if action == "docker_image_inspect":
            if set(parameters) != {"reference_kind"}:
                raise BrokerError("image inspect parameters differ")
            kind = parameters.get("reference_kind")
            reference = (
                controller.image_reference
                if kind == "manifest"
                else controller.image_config_reference
                if kind == "config"
                else None
            )
            if reference is None:
                raise BrokerError("image inspect reference is not pinned")
            logical = ("docker", "image", "inspect", reference)
            return logical, (_DOCKER, *logical[1:]), 30.0
        if action in {"docker_run", "docker_create"}:
            if parameters:
                raise BrokerError("Docker launch accepts no caller parameters")
            if self._root_image_reference(str(request["batch_id"])) is None:
                raise BrokerError("Docker launch lacks a root-selected pinned image")
            logical = (
                controller.docker_run_argv()
                if action == "docker_run"
                else controller.docker_create_argv()
            )
            return logical, (_DOCKER, *logical[1:]), 60.0
        if action == "docker_container_inspect":
            if set(parameters) != {"identifier"}:
                raise BrokerError("container inspect parameters differ")
            identifier = str(parameters.get("identifier") or "").lower()
            allowed = {binding.container_name.lower()}
            if binding.container_id is not None:
                allowed.add(binding.container_id)
            if identifier not in allowed:
                raise BrokerError("container inspection escaped its run binding")
            logical = ("docker", "inspect", "--type", "container", identifier)
            return logical, (_DOCKER, *logical[1:]), 30.0
        if action in {
            "docker_start",
            "docker_logs",
            "docker_remove",
            "docker_restart",
        }:
            container_id = self._require_container_id(binding)
            if parameters:
                raise BrokerError("container action accepts no caller parameters")
            if action == "docker_start":
                logical = ("docker", "start", container_id)
                timeout = 60.0
            elif action == "docker_logs":
                logical = (
                    "docker",
                    "logs",
                    "--timestamps",
                    "--tail",
                    "10000",
                    container_id,
                )
                timeout = 30.0
            elif action == "docker_remove":
                logical = ("docker", "rm", "--force", container_id)
                timeout = 60.0
            else:
                logical = ("docker", "restart", "--time", "0", container_id)
                timeout = 60.0
                # Preserve the frozen logical request, but execute the supported
                # Docker 28+ spelling. Deprecated flag warnings must not enter
                # the exact container-identity output channel.
                return logical, (_DOCKER, "restart", "--timeout", "0", container_id), timeout
            return logical, (_DOCKER, *logical[1:]), timeout
        if action == "docker_managed_list":
            if parameters:
                raise BrokerError("managed listing accepts no caller parameters")
            logical = (
                "docker",
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                "label=fortgym.m1b.managed=true",
                "--filter",
                f"label=fortgym.m1b.contract_sha256={binding.contract_sha256}",
                "--format",
                "{{json .}}",
            )
            return logical, (_DOCKER, *logical[1:]), 30.0
        if action == "docker_exec_attest":
            if parameters:
                raise BrokerError("runtime attestation accepts no caller parameters")
            container_id = self._require_container_id(binding)
            lua = (
                "local f=io.open('/run/fortgym/run-identity.tsv','r'); "
                "local v=f and f:read('*a') or ''; if f then f:close() end; "
                "local s=(v:gsub('%s+$','')); "
                "print('FORTGYM_ATTEST\\t'..s..'\\t'.."
                "(dfhack.isMapLoaded() and 'MAP_LOADED' or 'MAP_NOT_LOADED'))"
            )
            logical = (
                "docker",
                "exec",
                "--env",
                f"DFHACK_PORT={binding.port}",
                binding.container_name,
                "/opt/dwarf-fortress/dfhack-run",
                "lua",
                lua,
            )
            actual = (*logical[:4], container_id, *logical[5:])
            return logical, (_DOCKER, *actual[1:]), 10.0
        if action in {
            "signal_runtime",
            "signal_harness",
            "signal_supervisor",
            "pause_peer_harness",
            "resume_peer_harness",
            "pause_cohort_harness",
            "resume_cohort_harness",
            "abort_paused_harness",
            "stop_peer_harness",
        }:
            if action == "signal_supervisor":
                start_ticks = parameters.get("supervisor_start_ticks")
                if (
                    set(parameters) != {"supervisor_start_ticks"}
                    or isinstance(start_ticks, bool)
                    or not isinstance(start_ticks, int)
                    or start_ticks <= 0
                ):
                    raise BrokerError(
                        "supervisor signal requires one positive starttime binding"
                    )
            elif parameters:
                raise BrokerError("signal action accepts no caller parameters")
            try:
                owned = self._load_owned_run(request)
            except Exception as exc:  # recovery may follow a delivered terminal signal
                pid = self._prior_signal_target_pid(request)
                if pid is None or action not in {
                    "abort_paused_harness",
                    "stop_peer_harness",
                }:
                    raise BrokerError(
                        "signal target ownership evidence is unavailable"
                    ) from exc
            else:
                pid = (
                    owned.runtime_host_pid
                    if action == "signal_runtime"
                    else owned.harness_pid
                    if action
                    in {
                        "signal_harness",
                        "pause_peer_harness",
                        "resume_peer_harness",
                        "pause_cohort_harness",
                        "resume_cohort_harness",
                        "abort_paused_harness",
                        "stop_peer_harness",
                    }
                    else owned.supervisor_pid
                )
            signal_name = (
                "-STOP"
                if action in {"pause_peer_harness", "pause_cohort_harness"}
                else "-CONT"
                if action in {"resume_peer_harness", "resume_cohort_harness"}
                else "-TERM"
                if action == "stop_peer_harness"
                else "-KILL"
            )
            self._derived_target_pid = int(pid)
            logical = (_KILL, signal_name, "--", str(pid))
            return logical, logical, 10.0
        if action == "mount_enospc":
            if parameters:
                raise BrokerError("ENOSPC mount accepts no caller parameters")
            self._require_peer_id(request)
            workspace = self.layout.artifacts_root / binding.run_id
            source = f"fortgym-m1b-enospc-{binding.run_id}"
            logical = (
                _MOUNT,
                "-t",
                "tmpfs",
                "-o",
                "size=16777216,nosuid,nodev,noexec,mode=0700",
                source,
                str(workspace),
            )
            return logical, logical, 30.0
        if action == "unmount_enospc":
            if parameters:
                raise BrokerError("ENOSPC unmount accepts no caller parameters")
            self._require_peer_id(request)
            logical = (
                _UMOUNT,
                "--",
                str(self.layout.artifacts_root / binding.run_id),
            )
            return logical, logical, 30.0
        if action == "restart_docker":
            self._validate_daemon_session(request, binding)
            logical = (_SYSTEMCTL, "restart", "docker.service")
            return logical, logical, 120.0
        if action == "verify_outer_guard":
            if parameters:
                raise BrokerError("outer guard verification accepts no parameters")
            logical = (
                _NFT,
                "--json",
                "list",
                "table",
                "inet",
                "fortgym_m1b_outer",
            )
            return logical, logical, 30.0
        raise BrokerError("broker action has no command derivation")

    def _derive_canary(
        self,
        action: str,
        request: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], tuple[str, ...], float]:
        expected_keys = {"canary_name"}
        if set(parameters) != expected_keys:
            raise BrokerError("canary parameters differ")
        name = str(parameters.get("canary_name") or "")
        expected_name = (
            "fortgym-m1b-foreign-"
            + _sha256_bytes(str(request["batch_id"]).encode("utf-8"))[:16]
        )
        if name != expected_name:
            raise BrokerError("foreign canary name is not batch-derived")
        image = (
            "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
        )
        if action == "canary_create":
            logical = (
                "docker",
                "create",
                "--name",
                name,
                "--network",
                "none",
                "--memory",
                "128m",
                "--memory-swap",
                "128m",
                "--pids-limit",
                "16",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--restart",
                "no",
                "--entrypoint",
                "/bin/sleep",
                image,
                "28800",
            )
            return logical, (_DOCKER, *logical[1:]), 60.0
        if action == "canary_inspect":
            logical = ("docker", "inspect", "--type", "container", name)
            return logical, (_DOCKER, *logical[1:]), 30.0
        if action == "canary_absence":
            logical = (
                "docker",
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                f"name=^/{name}$",
                "--format",
                "{{.ID}}",
            )
            return logical, (_DOCKER, *logical[1:]), 30.0
        logical = ("docker", "rm", "--force", name)
        return logical, (_DOCKER, *logical[1:]), 60.0

    def _root_container_id(self, run_id: str) -> str | None:
        container_id: str | None = None
        for record in self._state_records():
            data = record["data"]
            if data.get("run_id") != run_id:
                continue
            if record["event"] == "container_bound":
                if set(data) != {
                    "run_id",
                    "contract_sha256",
                    "nonce_sha256",
                    "cohort_sha256",
                    "container_name",
                    "container_id",
                    "launch_sha256",
                    "bind_source_path",
                    "bind_source_device",
                    "bind_source_inode",
                }:
                    raise BrokerError("root container binding key set differs")
                observed = str(data.get("container_id") or "").lower()
                if not _CONTAINER_ID_RE.fullmatch(observed):
                    raise BrokerError("root container binding is malformed")
                if container_id is not None and container_id != observed:
                    raise BrokerError("root container identity changed")
                container_id = observed
            elif record["event"] == "container_removed":
                if data.get("container_id") != container_id:
                    raise BrokerError("root container removal binding differs")
                container_id = None
        return container_id

    def _container_id_for_action(self, run_id: str, action: str) -> str | None:
        container_id = self._root_container_id(run_id)
        if container_id is None and action in {
            "docker_container_inspect",
            "docker_remove",
        }:
            return self._prior_removed_container_id(run_id)
        return container_id

    def _root_bind_source_identity(self, run_id: str) -> tuple[str, int, int] | None:
        identity: tuple[str, int, int] | None = None
        for record in self._state_records():
            data = record["data"]
            if data.get("run_id") != run_id:
                continue
            if record["event"] == "container_bound":
                path = data.get("bind_source_path")
                device = data.get("bind_source_device")
                inode = data.get("bind_source_inode")
                if (
                    path != str(self._root_staged_evidence_path(run_id))
                    or isinstance(device, bool)
                    or not isinstance(device, int)
                    or device < 0
                    or isinstance(inode, bool)
                    or not isinstance(inode, int)
                    or inode <= 0
                ):
                    raise BrokerError("root bind-source identity is malformed")
                observed = (str(path), device, inode)
                if identity is not None and identity != observed:
                    raise BrokerError("root bind-source identity changed")
                identity = observed
            elif record["event"] == "container_removed":
                identity = None
        return identity

    def _prior_removed_container_id(self, run_id: str) -> str | None:
        observed: list[str] = []
        for record in self._state_records():
            if record["event"] != "container_removed":
                continue
            data = record["data"]
            if data.get("run_id") != run_id:
                continue
            container_id = str(data.get("container_id") or "").lower()
            if not _CONTAINER_ID_RE.fullmatch(container_id):
                raise BrokerError("prior root removal identity is malformed")
            observed.append(container_id)
        if not observed:
            return None
        if len(set(observed)) != 1:
            raise BrokerError("prior root removal identity is ambiguous")
        return observed[-1]

    def _root_image_reference(self, batch_id: str) -> str | None:
        selected: str | None = None
        allowed = {
            f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}",
            f"sha256:{_RUNTIME_IMAGE_CONFIG_SHA256}",
        }
        for record in self._state_records():
            if record["batch_id"] != batch_id or record["event"] != "image_selected":
                continue
            reference = record["data"].get("reference")
            if reference not in allowed:
                raise BrokerError("root image selection is malformed")
            if selected is not None and selected != reference:
                raise BrokerError("root image selection changed within the batch")
            selected = str(reference)
        return selected

    def _inspect_container_live(
        self,
        binding: _RunBinding,
        *,
        allow_absent: bool,
    ) -> tuple[dict[str, Any] | None, CommandCapture]:
        argv = (_DOCKER, "inspect", "--type", "container", binding.container_name)
        capture = self._execute(argv, 30.0)
        if capture.argv != argv:
            raise BrokerError("live Docker inspector changed argv")
        if capture.returncode != 0:
            lowered = capture.stderr.lower()
            if allow_absent and any(
                marker in lowered for marker in ("no such object", "no such container")
            ):
                return None, capture
            raise BrokerError("live Docker container inspection failed")
        try:
            value = json.loads(capture.stdout)
        except json.JSONDecodeError as exc:
            raise BrokerError("live Docker inspection is invalid JSON") from exc
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise BrokerError("live Docker inspection must contain one object")
        document = value[0]
        self._validate_owned_container_document(binding, document)
        return document, capture

    @staticmethod
    def _docker_not_found(capture: CommandCapture) -> bool:
        if capture.returncode == 0:
            return False
        message = f"{capture.stderr}\n{capture.stdout}".lower()
        return any(
            marker in message
            for marker in ("no such object", "no such container", "no such image")
        )

    def _inspect_canary_live(
        self,
        request: Mapping[str, Any],
        *,
        allow_absent: bool,
    ) -> dict[str, Any] | None:
        parameters = request.get("parameters")
        if not isinstance(parameters, Mapping):
            raise BrokerError("canary live inspection lacks parameters")
        name = str(parameters.get("canary_name") or "")
        argv = (_DOCKER, "inspect", "--type", "container", name)
        capture = self._execute(argv, 30.0)
        if capture.argv != argv:
            raise BrokerError("canary inspector changed the exact argv")
        if capture.returncode != 0:
            if allow_absent and self._docker_not_found(capture):
                return None
            raise BrokerError("canary live inspection failed")
        try:
            value = json.loads(capture.stdout)
        except json.JSONDecodeError as exc:
            raise BrokerError("canary live inspection is invalid JSON") from exc
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise BrokerError("canary live inspection cardinality differs")
        document = value[0]
        self._validate_canary_document(request, document)
        return document

    def _validate_canary_document(
        self,
        request: Mapping[str, Any],
        document: Mapping[str, Any],
    ) -> None:
        parameters = request.get("parameters")
        if not isinstance(parameters, Mapping):
            raise BrokerError("canary document lacks parameters")
        expected_name = str(parameters.get("canary_name") or "")
        expected_image = f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}"
        state = document.get("State")
        config = document.get("Config")
        host = document.get("HostConfig")
        container_id = str(document.get("Id") or "").lower()
        environment = config.get("Env") if isinstance(config, Mapping) else None
        environment_names: list[str] = []
        if environment is not None:
            if not isinstance(environment, list) or any(
                not isinstance(item, str) or "=" not in item for item in environment
            ):
                raise BrokerError("canary environment is malformed")
            environment_names = [item.split("=", 1)[0] for item in environment]
            if len(environment_names) != len(set(environment_names)) or any(
                name in _PROVIDER_ENV_NAMES
                or any(
                    token in name.upper()
                    for token in (
                        "OPENAI",
                        "ANTHROPIC",
                        "OPENROUTER",
                        "GEMINI",
                        "GOOGLE_API",
                        "MISTRAL",
                        "COHERE",
                    )
                )
                for name in environment_names
            ):
                raise BrokerError("canary environment escapes provider-free policy")
        if (
            not _CONTAINER_ID_RE.fullmatch(container_id)
            or document.get("Name") != f"/{expected_name}"
            or document.get("Image")
            not in {
                expected_image,
                f"sha256:{_RUNTIME_IMAGE_CONFIG_SHA256}",
            }
            or document.get("RestartCount", 0) != 0
            or not isinstance(state, Mapping)
            or set(state).isdisjoint({"Status", "Running", "Dead", "Restarting"})
            or state.get("Status") != "created"
            or state.get("Running") is not False
            or state.get("Dead") is not False
            or state.get("Restarting") is not False
            or not isinstance(config, Mapping)
            or config.get("Image") != expected_image
            or config.get("Entrypoint") != ["/bin/sleep"]
            or config.get("Cmd") != ["28800"]
            or not isinstance(host, Mapping)
            or host.get("NetworkMode") != "none"
            or host.get("Memory") != 134_217_728
            or host.get("MemorySwap") != 134_217_728
            or host.get("PidsLimit") != 16
            or host.get("CapDrop") != ["ALL"]
            or host.get("CapAdd") not in (None, [])
            or host.get("Privileged") is not False
            or host.get("Devices") not in (None, [])
            or host.get("SecurityOpt")
            not in (["no-new-privileges"], ["no-new-privileges:true"])
            or host.get("RestartPolicy") != {"Name": "no", "MaximumRetryCount": 0}
            or document.get("Mounts") not in (None, [])
        ):
            raise BrokerError("live foreign canary identity differs")

    @staticmethod
    def _sanitize_canary_inspection(document: Mapping[str, Any]) -> str:
        state = document.get("State")
        config = document.get("Config")
        host = document.get("HostConfig")
        if not all(isinstance(value, Mapping) for value in (state, config, host)):
            raise BrokerError("validated canary inspection disappeared")
        safe = {
            "Id": document.get("Id"),
            "Name": document.get("Name"),
            "Image": document.get("Image"),
            "RestartCount": document.get("RestartCount", 0),
            "State": {
                key: state.get(key)
                for key in ("Status", "Running", "Dead", "Restarting")
            },
            "Config": {key: config.get(key) for key in ("Image", "Entrypoint", "Cmd")},
            "HostConfig": {
                key: host.get(key)
                for key in (
                    "NetworkMode",
                    "Memory",
                    "MemorySwap",
                    "PidsLimit",
                    "CapDrop",
                    "SecurityOpt",
                    "RestartPolicy",
                )
            },
        }
        return json.dumps([safe], sort_keys=True, separators=(",", ":")) + "\n"

    def _validate_command_result(
        self,
        request: Mapping[str, Any],
        binding: _RunBinding | None,
        capture: CommandCapture,
    ) -> CommandCapture:
        action = str(request["action"])
        if (
            not isinstance(capture.returncode, int)
            or isinstance(capture.returncode, bool)
            or not isinstance(capture.stdout, str)
            or not isinstance(capture.stderr, str)
            or len(capture.stdout.encode("utf-8", errors="replace")) > _MAX_STDOUT_BYTES
            or len(capture.stderr.encode("utf-8", errors="replace")) > _MAX_STDERR_BYTES
        ):
            raise BrokerError("broker command capture exceeds its exact bounds")
        if capture.returncode != 0:
            if action in {"docker_container_inspect", "docker_image_inspect"} and (
                self._docker_not_found(capture)
            ):
                return CommandCapture(
                    argv=capture.argv,
                    returncode=capture.returncode,
                    stdout="",
                    stderr="Error: no such object\n",
                )
            return CommandCapture(
                argv=capture.argv,
                returncode=capture.returncode,
                stdout="",
                stderr="fortgym-root-broker: command returned nonzero\n",
            )
        if capture.stderr and action != "docker_logs":
            raise BrokerError("successful broker command wrote unexpected stderr")

        stdout = capture.stdout
        stderr = ""
        if action == "docker_image_inspect":
            try:
                value = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise BrokerError("Docker image inspection is invalid JSON") from exc
            if (
                not isinstance(value, list)
                or len(value) != 1
                or not isinstance(value[0], Mapping)
            ):
                raise BrokerError("Docker image inspection cardinality differs")
            observed_id = str(value[0].get("Id") or "")
            reference_kind = request["parameters"].get("reference_kind")
            allowed_id = (
                {
                    f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}",
                    f"sha256:{_RUNTIME_IMAGE_CONFIG_SHA256}",
                }
                if reference_kind == "manifest"
                else {f"sha256:{_RUNTIME_IMAGE_CONFIG_SHA256}"}
            )
            if observed_id not in allowed_id:
                raise BrokerError("Docker image inspection escaped fixed digests")
            reference = (
                f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}"
                if reference_kind == "manifest"
                else f"sha256:{_RUNTIME_IMAGE_CONFIG_SHA256}"
            )
            selected = self._root_image_reference(str(request["batch_id"]))
            if selected is not None and selected != reference:
                raise BrokerError("Docker image resolution changed within the batch")
            if selected is None:
                self._append_state_record(
                    request,
                    event="image_selected",
                    data={"reference": reference, "observed_image_id": observed_id},
                )
            stdout = (
                json.dumps([{"Id": observed_id}], sort_keys=True, separators=(",", ":"))
                + "\n"
            )
        elif action in {"docker_run", "docker_create"}:
            if binding is None:
                raise BrokerError("Docker launch result lacks a run binding")
            container_id = stdout.strip().lower()
            if not _CONTAINER_ID_RE.fullmatch(container_id):
                raise BrokerError("Docker launch did not return one container ID")
            document, _inspection = self._inspect_container_live(
                binding,
                allow_absent=False,
            )
            if (
                document is None
                or str(document.get("Id") or "").lower() != container_id
            ):
                raise BrokerError("Docker launch output differs from live identity")
            if self._root_container_id(binding.run_id) is not None:
                raise BrokerError("run already has a root container binding")
            self._append_state_record(
                request,
                event="container_bound",
                data=self._container_binding_data(binding, container_id),
            )
            stdout = container_id + "\n"
        elif action == "docker_start":
            if binding is None or binding.container_id is None:
                raise BrokerError("Docker start result lacks a container binding")
            if stdout.strip().lower() not in {
                binding.container_id,
                binding.container_name.lower(),
            }:
                raise BrokerError("Docker start output differs from root binding")
            document, _inspection = self._inspect_container_live(
                binding, allow_absent=False
            )
            state = document.get("State") if document is not None else None
            if not isinstance(state, Mapping) or state.get("Running") is not True:
                raise BrokerError("Docker start did not produce a running container")
            stdout = binding.container_id + "\n"
        elif action == "docker_container_inspect":
            if binding is None:
                raise BrokerError("Docker inspect result lacks a run binding")
            try:
                value = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise BrokerError(
                    "Docker container inspection is invalid JSON"
                ) from exc
            if (
                not isinstance(value, list)
                or len(value) != 1
                or not isinstance(value[0], Mapping)
            ):
                raise BrokerError("Docker container inspection cardinality differs")
            attempt_id = str(request.get("attempt_id") or "")
            if (
                attempt_id in _FROZEN_ATTEMPTS
                and _FROZEN_ATTEMPTS[attempt_id][2] == "non_runtime_conflict"
            ):
                raise BrokerError("non-runtime conflict unexpectedly found a container")
            self._validate_owned_container_document(binding, value[0])
            stdout = self._sanitize_container_inspection(binding, value[0])
        elif action == "docker_logs":
            stdout = (
                json.dumps(
                    {
                        "schema": "fortgym.m1b-secretless-log-capture/v1",
                        "stdout_bytes": len(stdout.encode("utf-8", errors="replace")),
                        "stdout_sha256": _sha256_bytes(stdout.encode("utf-8")),
                        "stderr_bytes": len(
                            capture.stderr.encode("utf-8", errors="replace")
                        ),
                        "stderr_sha256": _sha256_bytes(capture.stderr.encode("utf-8")),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        elif action == "docker_managed_list":
            if binding is None:
                raise BrokerError("Docker managed list lacks a run binding")
            identifiers: list[str] = []
            for line in stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BrokerError("Docker managed list is invalid JSONL") from exc
                if not isinstance(row, Mapping):
                    raise BrokerError("Docker managed list row is malformed")
                identifier = str(row.get("ID") or row.get("Id") or "").lower()
                if not _CONTAINER_ID_RE.fullmatch(identifier):
                    raise BrokerError("Docker managed list ID is malformed")
                if identifier in identifiers:
                    raise BrokerError("Docker managed list contains a duplicate")
                if binding.container_id is None or identifier != binding.container_id:
                    raise BrokerError("Docker managed list contains an unbound object")
                self._inspect_container_live(binding, allow_absent=False)
                identifiers.append(identifier)
            stdout = "".join(
                json.dumps({"ID": identifier}, sort_keys=True, separators=(",", ":"))
                + "\n"
                for identifier in identifiers
            )
        elif action == "docker_exec_attest":
            if binding is None:
                raise BrokerError("runtime attestation lacks a run binding")
            clean = _ANSI_RE.sub("", stdout)
            attestation_lines = [
                line.rstrip()
                for line in clean.splitlines()
                if line.startswith("FORTGYM_ATTEST\t")
            ]
            if len(attestation_lines) != 1:
                raise BrokerError("runtime attestation marker cardinality differs")
            fields = tuple(attestation_lines[0].split("\t"))
            contract = binding.runtime_controller.contract
            if (
                len(fields) != 10
                or fields[0] != "FORTGYM_ATTEST"
                or fields[1] != binding.run_id
                or _sha256_bytes(fields[2].encode("utf-8")) != binding.nonce_sha256
                or fields[3] != binding.contract_sha256
                or fields[4] != contract.seed_tree_sha256
                or fields[5] != contract.seed_world_sha256
                or fields[6] != contract.image_manifest_sha256
                or fields[7] != contract.image_config_sha256
                or fields[8] != contract.image_archive_sha256
                or fields[9] not in {"MAP_LOADED", "MAP_NOT_LOADED"}
            ):
                raise BrokerError("runtime attestation identity differs")
            stdout = (
                json.dumps(
                    {
                        "schema": "fortgym.m1b-runtime-attestation-projection/v1",
                        "run_id": binding.run_id,
                        "nonce_sha256": binding.nonce_sha256,
                        "contract_sha256": binding.contract_sha256,
                        "seed_tree_sha256": contract.seed_tree_sha256,
                        "seed_world_sha256": contract.seed_world_sha256,
                        "image_manifest_sha256": contract.image_manifest_sha256,
                        "image_config_sha256": contract.image_config_sha256,
                        "image_archive_sha256": contract.image_archive_sha256,
                        "map_state": fields[9],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        elif action in {
            "signal_runtime",
            "signal_harness",
            "signal_supervisor",
            "pause_peer_harness",
            "resume_peer_harness",
            "pause_cohort_harness",
            "resume_cohort_harness",
            "abort_paused_harness",
            "stop_peer_harness",
            "mount_enospc",
            "unmount_enospc",
            "restart_docker",
        }:
            if stdout:
                raise BrokerError("successful fixed root mutation wrote stdout")
            if action in {"pause_peer_harness", "pause_cohort_harness"}:
                self._require_post_signal_state(stopped=True)
            elif action in {"resume_peer_harness", "resume_cohort_harness"}:
                self._require_post_signal_state(stopped=False)
            elif action == "mount_enospc":
                self._validate_enospc_mount_result(request, binding, mounted=True)
            elif action == "unmount_enospc":
                self._validate_enospc_mount_result(request, binding, mounted=False)
        elif action == "docker_remove":
            if binding is None or binding.container_id is None:
                raise BrokerError("Docker removal result lacks a container binding")
            if stdout.strip().lower() not in {
                binding.container_id,
                binding.container_name.lower(),
            }:
                raise BrokerError("Docker removal output differs from root binding")
            document, _inspection = self._inspect_container_live(
                binding, allow_absent=True
            )
            if document is not None:
                raise BrokerError("Docker removal left the bound container present")
            self._release_root_staged_evidence(binding.run_id)
            if self._prior_removed_container_id(binding.run_id) is None:
                self._append_state_record(
                    request,
                    event="container_removed",
                    data={
                        "run_id": binding.run_id,
                        "container_id": binding.container_id,
                    },
                )
            stdout = binding.container_id + "\n"
        elif action == "docker_restart":
            if binding is None or binding.container_id is None:
                raise BrokerError("Docker restart result lacks a binding")
            if stdout.strip().lower() not in {
                binding.container_id,
                binding.container_name.lower(),
            }:
                raise BrokerError("Docker restart output differs from root binding")
            self._inspect_container_live(binding, allow_absent=False)
            stdout = binding.container_id + "\n"
        elif action == "canary_create":
            container_id = stdout.strip().lower()
            if not _CONTAINER_ID_RE.fullmatch(container_id):
                raise BrokerError("canary creation did not return one container ID")
            document = self._inspect_canary_live(request, allow_absent=False)
            if (
                document is None
                or str(document.get("Id") or "").lower() != container_id
            ):
                raise BrokerError("canary creation output differs from live identity")
            stdout = container_id + "\n"
        elif action == "canary_inspect":
            try:
                value = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise BrokerError("canary inspection is invalid JSON") from exc
            if (
                not isinstance(value, list)
                or len(value) != 1
                or not isinstance(value[0], Mapping)
            ):
                raise BrokerError("canary inspection cardinality differs")
            self._validate_canary_document(request, value[0])
            stdout = self._sanitize_canary_inspection(value[0])
        elif action == "canary_remove":
            name = str(request["parameters"]["canary_name"])
            if stdout.strip().lower() != name.lower():
                raise BrokerError("canary removal output differs")
            if self._inspect_canary_live(request, allow_absent=True) is not None:
                raise BrokerError("canary remains after removal")
            stdout = name + "\n"
        elif action == "canary_absence":
            if stdout != "":
                raise BrokerError("canary absence filter returned an object")
        elif action == "verify_outer_guard":
            stdout = (
                json.dumps(
                    {
                        "schema": "fortgym.m1b-outer-guard-projection/v1",
                        "verified": True,
                        "ruleset_sha256": _sha256_bytes(stdout.encode("utf-8")),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        return CommandCapture(
            argv=capture.argv,
            returncode=0,
            stdout=stdout,
            stderr=stderr,
        )

    def _require_post_signal_state(self, *, stopped: bool) -> None:
        identity = self._execution_process_identity
        if identity is None:
            raise BrokerError("signal result lacks a root process binding")
        # pidfd_send_signal() returning means the signal was delivered to the
        # bound task, not that Linux has already exposed the resulting state in
        # /proc.  Poll the same PID/starttime/process-group identity for a
        # strictly bounded two seconds before failing closed.  The previous
        # single read raced a real SIGSTOP during PORT-2 and stranded an
        # otherwise correctly bound stopped harness as an ambiguous mutation.
        for observation_index in range(81):
            observed = self._proc_snapshot(identity.pid)
            if (
                observed[0] != identity.starttime
                or observed[1] != identity.process_group_id
            ):
                raise BrokerError("signal target PID identity changed after execution")
            is_stopped = observed[3] in {"T", "t"}
            if is_stopped is stopped:
                return
            if observation_index != 80:
                self._sleep(0.025)
        raise BrokerError("signal did not reach its required process state")

    def _enospc_covered_directory(
        self, request: Mapping[str, Any], binding: _RunBinding
    ) -> tuple[int, int]:
        identities = []
        public = self._public_binding(binding)
        immutable_keys = (
            "run_id", "contract_sha256", "nonce_sha256", "cohort_sha256", "container_name", "port"
        )
        for record in self._state_records():
            data = record["data"]
            recorded_binding = data.get("binding")
            if (
                record["batch_id"] != request["batch_id"]
                or record["event"] != "execution_target_bound"
                or data.get("action") != "mount_enospc"
                or not isinstance(recorded_binding, dict)
                or any(recorded_binding.get(key) != public[key] for key in immutable_keys)
            ):
                continue
            covered = data.get("covered_directory")
            if (
                not isinstance(covered, dict)
                or set(covered) != {"path", "device", "inode"}
                or covered["path"] != str(self.layout.artifacts_root / binding.run_id)
                or type(covered["device"]) is not int
                or type(covered["inode"]) is not int
                or covered["device"] < 0
                or covered["inode"] <= 0
            ):
                raise BrokerError("ENOSPC covered directory record is invalid")
            identities.append((covered["device"], covered["inode"]))
        if len(identities) != 1:
            raise BrokerError("ENOSPC covered directory identity is unavailable or ambiguous")
        return identities[0]

    def _validate_enospc_mount_result(
        self,
        request: Mapping[str, Any],
        binding: _RunBinding | None,
        *,
        mounted: bool,
    ) -> None:
        if binding is None or self._execution_mount_identity is None:
            raise BrokerError("mount result lacks a root target binding")
        target = self.layout.artifacts_root / binding.run_id
        current = target.lstat()
        expected = self._execution_mount_identity
        if not mounted:
            covered_identity = (
                self._enospc_covered_directory(request, binding)
                if expected.expect_mounted
                else (expected.device, expected.inode)
            )
            if (current.st_dev, current.st_ino) != covered_identity:
                raise BrokerError("mount target identity changed during execution")
            self._stable_directory_identity(
                target, owner_uid=self._required_evidence_owner_uid(), exact_mode=0o700
            )
        record = self._mount_record(target)
        if not mounted:
            if record is not None:
                raise BrokerError("ENOSPC target remains mounted")
            return
        source = f"fortgym-m1b-enospc-{binding.run_id}"
        if (
            record is None
            or record.get("filesystem") != "tmpfs"
            or record.get("source") != source
            or not {"rw", "nosuid", "nodev", "noexec"}.issubset(
                set(record.get("options", ()))
            )
            or not any(
                value in {"size=16384k", "size=16777216"}
                for value in record.get("super_options", ())
            )
            or "mode=700" not in set(record.get("super_options", ()))
        ):
            raise BrokerError("ENOSPC mount postcondition differs")
        # mount(8) creates the tmpfs root as root even when the covered
        # directory belongs to the runner. Transfer only this verified mount
        # root, through a no-follow descriptor, while its parent is protected.
        descriptor = os.open(
            target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino)
                or metadata.st_uid != self._trusted_uid
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise BrokerError("ENOSPC mounted root identity differs")
            os.fchown(descriptor, self._required_evidence_owner_uid(), -1)
            owned = os.fstat(descriptor)
            path_now = target.lstat()
            if (
                owned.st_uid != self._required_evidence_owner_uid()
                or stat.S_IMODE(owned.st_mode) != 0o700
                or (path_now.st_dev, path_now.st_ino) != (owned.st_dev, owned.st_ino)
            ):
                raise BrokerError("ENOSPC mounted root ownership handoff differs")
        finally:
            os.close(descriptor)

    def _validate_owned_container_document(
        self,
        binding: _RunBinding,
        document: Mapping[str, Any],
    ) -> None:
        controller = binding.runtime_controller
        observed_id = str(document.get("Id") or "").lower()
        config = document.get("Config")
        host = document.get("HostConfig")
        state = document.get("State")
        mounts = document.get("Mounts")
        if (
            not _CONTAINER_ID_RE.fullmatch(observed_id)
            or str(document.get("Name") or "").removeprefix("/")
            != binding.container_name
            or not isinstance(config, Mapping)
            or not isinstance(host, Mapping)
            or not isinstance(state, Mapping)
            or not isinstance(mounts, list)
        ):
            raise BrokerError("live container identity shape differs")
        labels = config.get("Labels")
        expected_labels = {
            **_RUNTIME_IMAGE_LABELS,
            **controller.expected_labels,
        }
        if not isinstance(labels, Mapping) or dict(labels) != expected_labels:
            raise BrokerError("live container labels differ from root contract")
        environment = config.get("Env")
        if not isinstance(environment, list) or any(
            not isinstance(item, str) or "=" not in item for item in environment
        ):
            raise BrokerError("live container environment is malformed")
        environment_pairs = [item.split("=", 1) for item in environment]
        environment_names = [pair[0] for pair in environment_pairs]
        if any(not name for name in environment_names) or len(
            set(environment_names)
        ) != len(environment_names):
            raise BrokerError("live container environment names are not unique")
        environment_index = dict(environment_pairs)
        expected_environment = {
            **_RUNTIME_IMAGE_ENVIRONMENT,
            **controller.container_environment(),
        }
        if (
            len(environment) != len(expected_environment)
            or set(environment_index) != set(expected_environment)
            or environment_index != dict(expected_environment)
            or any(
                name in _PROVIDER_ENV_NAMES
                or any(
                    token in name.upper()
                    for token in (
                        "OPENAI",
                        "ANTHROPIC",
                        "OPENROUTER",
                        "GEMINI",
                        "GOOGLE_API",
                        "MISTRAL",
                        "COHERE",
                    )
                )
                for name in environment_index
            )
        ):
            raise BrokerError("live container environment escapes provider-free policy")
        configured_image = str(config.get("Image") or "")
        runtime_image = str(document.get("Image") or "")
        expected_configured_image = str(controller.resolved_image_reference)
        expected_runtime_image = f"sha256:{_RUNTIME_IMAGE_MANIFEST_SHA256}"
        restart_policy = host.get("RestartPolicy")
        security = host.get("SecurityOpt")
        cap_drop = host.get("CapDrop")
        normalized_security = (
            {
                "no-new-privileges" if value == "no-new-privileges:true" else value
                for value in security
            }
            if isinstance(security, list)
            and all(isinstance(value, str) for value in security)
            else set()
        )
        if (
            configured_image != expected_configured_image
            or runtime_image != expected_runtime_image
            or config.get("Entrypoint") != ["/bin/bash"]
            or config.get("Cmd") != ["/opt/fortgym-m1b/runtime_entrypoint.sh"]
            or host.get("NetworkMode") != "host"
            or host.get("Memory") != controller.memory_bytes
            or host.get("MemorySwap") != controller.memory_bytes
            or host.get("PidsLimit") != 256
            or host.get("CpusetCpus") != (controller.cpuset_cpus or "")
            or not isinstance(restart_policy, Mapping)
            or dict(restart_policy) != {"Name": "no", "MaximumRetryCount": 0}
            or normalized_security != {"no-new-privileges", "seccomp=unconfined"}
            or cap_drop != ["ALL"]
            or host.get("Privileged") is not False
            or host.get("CapAdd") not in (None, [])
            or host.get("Devices") not in (None, [])
        ):
            raise BrokerError("live container isolation profile differs")
        if len(mounts) != 2 or any(not isinstance(item, Mapping) for item in mounts):
            raise BrokerError("live container mount cardinality differs")
        mount_destinations = [str(item.get("Destination")) for item in mounts]
        if len(set(mount_destinations)) != len(mount_destinations):
            raise BrokerError("live container mount destinations are duplicated")
        mount_index = {str(item.get("Destination")): item for item in mounts}
        entrypoint_mount = mount_index.get("/opt/fortgym-m1b/runtime_entrypoint.sh")
        evidence_mount = mount_index.get("/artifacts")
        staged_evidence = self._root_staged_evidence_path(binding.run_id)
        try:
            staged_metadata = staged_evidence.stat()
        except OSError as exc:
            raise BrokerError("live container bind source is unavailable") from exc
        root_stage_identity = self._root_bind_source_identity(binding.run_id)
        if (
            len(mount_index) != 2
            or not isinstance(entrypoint_mount, Mapping)
            or Path(str(entrypoint_mount.get("Source"))) != controller.entrypoint_path
            or entrypoint_mount.get("RW") is not False
            or entrypoint_mount.get("Type") != "bind"
            or not isinstance(evidence_mount, Mapping)
            or Path(str(evidence_mount.get("Source"))) != staged_evidence
            or evidence_mount.get("RW") is not True
            or evidence_mount.get("Type") != "bind"
            or self._mount_record(staged_evidence) is None
            or (
                root_stage_identity is not None
                and root_stage_identity
                != (
                    str(staged_evidence),
                    staged_metadata.st_dev,
                    staged_metadata.st_ino,
                )
            )
        ):
            raise BrokerError("live container bind sources differ")
        if binding.container_id is not None and observed_id != binding.container_id:
            raise BrokerError("live container ID differs from root binding")

    def _sanitize_container_inspection(
        self,
        binding: _RunBinding,
        document: Mapping[str, Any],
    ) -> str:
        config = document["Config"]
        host = document["HostConfig"]
        state = document["State"]
        mounts = document["Mounts"]
        expected_environment = binding.runtime_controller.container_environment()
        environment = config.get("Env")
        if not isinstance(environment, list):
            raise BrokerError("validated container environment disappeared")
        index = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in environment
            if isinstance(item, str) and "=" in item
        }
        mount_index = {
            str(item.get("Destination")): item
            for item in mounts
            if isinstance(item, Mapping)
        }
        safe = {
            "FortGymProjectionSchema": ("fortgym.m1b-container-inspect-projection/v1"),
            "Id": document.get("Id"),
            "Name": document.get("Name"),
            "Image": document.get("Image"),
            "RestartCount": document.get("RestartCount", 0),
            "State": {
                key: state.get(key)
                for key in (
                    "Status",
                    "Running",
                    "Dead",
                    "Restarting",
                    "OOMKilled",
                    "ExitCode",
                    "Pid",
                )
            },
            "Config": {
                "Image": config.get("Image"),
                "Labels": dict(binding.runtime_controller.expected_labels),
                "Entrypoint": config.get("Entrypoint"),
                "Cmd": config.get("Cmd"),
            },
            "HostConfig": {
                key: host.get(key)
                for key in (
                    "NetworkMode",
                    "Memory",
                    "MemorySwap",
                    "PidsLimit",
                    "CapDrop",
                    "SecurityOpt",
                    "RestartPolicy",
                    "CpusetCpus",
                )
            },
            "EnvAttestations": [
                {
                    "name": name,
                    "value_sha256": _sha256_bytes(index[name].encode("utf-8")),
                }
                for name in sorted(expected_environment)
            ],
            "MountAttestations": [
                {
                    "destination": destination,
                    "source_sha256": _sha256_bytes(
                        str(
                            binding.runtime_controller.evidence_dir
                            if destination == "/artifacts"
                            else mount_index[destination]["Source"]
                        ).encode("utf-8")
                    ),
                    "rw": mount_index[destination]["RW"],
                    "type": mount_index[destination]["Type"],
                }
                for destination in sorted(
                    {"/opt/fortgym-m1b/runtime_entrypoint.sh", "/artifacts"}
                )
            ],
        }
        return json.dumps([safe], sort_keys=True, separators=(",", ":")) + "\n"

    def _load_owned_run(self, request: Mapping[str, Any]) -> Any:
        loader = self._load_evidence_loader()
        run_id = str(request["run_id"])
        gate = str(request["gate_id"])
        peer = request.get("peer_run_id")
        if gate == "ENOSPC":
            if not isinstance(peer, str):
                raise BrokerError("ENOSPC owned run requires its peer")
            return loader.load_enospc_target(run_id, peer_run_id=peer)
        return loader.load(run_id)

    def _load_evidence_loader(self) -> Any:
        self._install_repo_import_path()
        from fort_gym.bench.run.fault_driver import OwnedRunEvidenceLoader

        return OwnedRunEvidenceLoader(
            control_root=self.layout.control_root,
            db_path=self.layout.db_path,
            artifacts_root=self.layout.artifacts_root,
        )

    def _validate_daemon_session(
        self, request: Mapping[str, Any], binding: _RunBinding
    ) -> None:
        parameters = request["parameters"]
        if not isinstance(parameters, Mapping):
            raise BrokerError("daemon restart parameters are invalid")
        # Kept for defensive compatibility if the exact action derivation is
        # called directly in tests; normal validation requires this key.
        if set(parameters) != {"session_sha256"}:
            raise BrokerError("daemon restart requires one fault-session digest")
        session_sha256 = parameters.get("session_sha256")
        if not isinstance(session_sha256, str) or not _SHA256_RE.fullmatch(
            session_sha256
        ):
            raise BrokerError("daemon fault-session digest is invalid")
        self._install_repo_import_path()
        from fort_gym.bench.run.fault_session import (
            FaultSessionIdentity,
            FaultSessionStore,
        )

        manifest = _read_json(
            self.layout.control_root
            / "_fault-sessions"
            / session_sha256
            / "session.json",
            maximum=256 * 1024,
            owner_uid=self._evidence_owner_uid,
        )
        session = FaultSessionIdentity.from_payload(manifest)
        if (
            session.session_sha256 != session_sha256
            or session.gate != "DAEMON-RESTART"
            or session.authority_sha256 != FROZEN_ACCEPTANCE_SHA256
            or session.target.run_id != binding.run_id
            or session.peer.run_id != request.get("peer_run_id")
        ):
            raise BrokerError("daemon fault-session binding differs")
        store = FaultSessionStore(
            control_root=self.layout.control_root, session=session
        )
        if any(store.ready(item.run_id) is None for item in session.participants):
            raise BrokerError("daemon restart requires both exact step-2 receipts")
        loader = self._load_evidence_loader()
        target = loader.load(session.target.run_id)
        peer = loader.load(session.peer.run_id)
        if target.cohort_sha256 != peer.cohort_sha256:
            raise BrokerError("daemon restart cohort identity differs")

    def _validate_outer_guard_capture(self, stdout: str) -> None:
        """Prove Docker restart did not weaken the root-owned nft fail-close."""

        try:
            document = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise BrokerError("outer guard live ruleset is invalid JSON") from exc
        flow_document = _read_json(
            self.layout.control_ssh_flow_evidence,
            maximum=64 * 1024,
            owner_uid=self._trusted_uid,
        )
        if (
            flow_document.get("schema") != "fortgym.m1b-control-ssh-flow/v1"
            or flow_document.get("exact_flow_count") != 1
            or not isinstance(flow_document.get("flow"), Mapping)
        ):
            raise BrokerError("outer guard control-flow evidence differs")
        flow = flow_document["flow"]
        entries = document.get("nftables") if isinstance(document, Mapping) else None
        if not isinstance(entries, list):
            raise BrokerError("outer guard live ruleset is malformed")
        objects: list[tuple[str, Mapping[str, Any]]] = []
        for entry in entries:
            if not isinstance(entry, Mapping) or len(entry) != 1:
                raise BrokerError("outer guard live entry is malformed")
            kind, value = next(iter(entry.items()))
            if kind == "metainfo":
                continue
            if not isinstance(kind, str) or not isinstance(value, Mapping):
                raise BrokerError("outer guard live object is malformed")
            if (
                value.get("family") == "inet"
                and value.get("table", value.get("name")) == "fortgym_m1b_outer"
            ):
                objects.append((kind, value))
        tables = [value for kind, value in objects if kind == "table"]
        chains = {
            value.get("name"): value for kind, value in objects if kind == "chain"
        }
        counters = {
            value.get("name"): value for kind, value in objects if kind == "counter"
        }
        rules = [value for kind, value in objects if kind == "rule"]
        if (
            len(tables) != 1
            or set(chains) != {"output", "forward"}
            or set(counters) != {"output_denied", "forward_denied"}
        ):
            raise BrokerError("outer guard table, chain, or counter set differs")
        for name, hook, priority in (
            ("output", "output", -200),
            ("forward", "forward", -10),
        ):
            chain = chains[name]
            if (
                chain.get("type") != "filter"
                or chain.get("hook") != hook
                or chain.get("prio") != priority
                or chain.get("policy") != "drop"
            ):
                raise BrokerError("outer guard base-chain fail-close differs")
        output_rules = [rule for rule in rules if rule.get("chain") == "output"]
        forward_rules = [rule for rule in rules if rule.get("chain") == "forward"]
        if len(output_rules) != 3 or len(forward_rules) != 1 or len(rules) != 4:
            raise BrokerError("outer guard exact rule count differs")

        def encoded(rule: Mapping[str, Any]) -> str:
            return json.dumps(rule.get("expr"), sort_keys=True, separators=(",", ":"))

        loopback, ssh_reply, output_deny = (encoded(rule) for rule in output_rules)
        forward_deny = encoded(forward_rules[0])
        if (
            not all(
                token in loopback
                for token in ('"oifname"', '"lo"', '"accept"', '"counter"')
            )
            or '"reject"' in loopback
        ):
            raise BrokerError("outer guard loopback rule differs")
        family = flow.get("family")
        if family not in {"ipv4", "ipv6"}:
            raise BrokerError("outer guard SSH flow family differs")
        expected_tokens = (
            '"saddr"',
            '"daddr"',
            '"sport"',
            '"dport"',
            "22",
            str(flow.get("server_address")),
            str(flow.get("client_address")),
            str(flow.get("client_port")),
            '"accept"',
            '"ip"' if family == "ipv4" else '"ip6"',
        )
        if not all(token in ssh_reply for token in expected_tokens) or any(
            token in ssh_reply for token in ('"state"', '"related"', '"udp"')
        ):
            raise BrokerError("outer guard exact SSH reply rule differs")
        if (
            not all(token in output_deny for token in ('"output_denied"', '"reject"'))
            or '"accept"' in output_deny
            or not all(
                token in forward_deny for token in ('"forward_denied"', '"reject"')
            )
            or '"accept"' in forward_deny
        ):
            raise BrokerError("outer guard deny rules differ")

    @staticmethod
    def _require_container_id(binding: _RunBinding) -> str:
        if binding.container_id is None:
            raise BrokerError("container action lacks its durable created receipt")
        return binding.container_id

    @staticmethod
    def _require_peer_id(request: Mapping[str, Any]) -> str:
        peer = request.get("peer_run_id")
        if not isinstance(peer, str) or not _ID_RE.fullmatch(peer):
            raise BrokerError("broker action requires one exact peer binding")
        return peer

    @staticmethod
    def _public_binding(binding: _RunBinding | None) -> dict[str, Any] | None:
        if binding is None:
            return None
        return {
            "run_id": binding.run_id,
            "contract_sha256": binding.contract_sha256,
            "nonce_sha256": binding.nonce_sha256,
            "cohort_sha256": binding.cohort_sha256,
            "container_name": binding.container_name,
            "container_id": binding.container_id,
            "port": binding.port,
        }

    def _install_repo_import_path(self) -> None:
        self._verify_trusted_runtime()
        value = str(self.layout.repo_root)
        if value not in sys.path:
            sys.path.insert(0, value)


def _ensure_isolated_main() -> None:
    if sys.flags.isolated == 1:
        return
    if os.geteuid() != 0:
        raise BrokerError("root broker isolation re-exec requires root")
    sudo_uid = os.environ.get("SUDO_UID", "")
    if not sudo_uid.isdigit() or int(sudo_uid) <= 0:
        raise BrokerError("root broker isolation re-exec lacks its sudo caller")
    layout = BrokerLayout()
    broker_metadata = _INSTALLED_BROKER.lstat()
    if (
        stat.S_ISLNK(broker_metadata.st_mode)
        or not stat.S_ISREG(broker_metadata.st_mode)
        or broker_metadata.st_uid != 0
        or stat.S_IMODE(broker_metadata.st_mode) & 0o022
    ):
        raise BrokerError("root broker isolation executable is unsafe")
    interpreter_link = layout.venv_python.lstat()
    interpreter = layout.venv_python.resolve(strict=True)
    interpreter_metadata = interpreter.stat()
    if (
        interpreter_link.st_uid != 0
        or stat.S_IMODE(interpreter_link.st_mode) & 0o022
        or not stat.S_ISREG(interpreter_metadata.st_mode)
        or interpreter_metadata.st_uid != 0
        or stat.S_IMODE(interpreter_metadata.st_mode) & 0o022
    ):
        raise BrokerError("root broker isolated interpreter is unsafe")
    clean_environment = {
        "HOME": "/root",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "SUDO_UID": sudo_uid,
    }
    os.execve(
        str(layout.venv_python),
        (
            str(layout.venv_python),
            "-I",
            str(_INSTALLED_BROKER),
            *sys.argv[1:],
        ),
        clean_environment,
    )
    raise BrokerError("root broker isolation re-exec returned unexpectedly")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute one exact Fort Gym M1b root-broker request"
    )
    parser.add_argument("--request", required=True, type=Path)
    return parser


def _failure_payload(exc: Exception) -> dict[str, Any]:
    reason_sha256 = _sha256_bytes(str(exc).encode("utf-8", errors="replace"))
    return {
        "schema": "fortgym.m1b-root-broker-error/v1",
        "ok": False,
        "error_code": f"broker_{type(exc).__name__.lower()}",
        "reason_sha256": reason_sha256,
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        _ensure_isolated_main()
        args = _parser().parse_args(argv)
        receipt = RootBroker().handle(args.request)
    except (BrokerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps(_failure_payload(exc), sort_keys=True, separators=(",", ":")))
        return 64
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by installed host
    raise SystemExit(main())
