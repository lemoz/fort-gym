#!/opt/fortgym-m1b/venv/bin/python -I
"""Concrete, provider-free Linux runner for the frozen M1b acceptance batch.

This is the sole host entrypoint for the live matrix.  It constructs every
test-only capability in memory, supplies no API or environment fault knobs,
routes privileged host work through the narrow root broker, accounts the
frozen attempt permits, snapshots evidence into the batch root, and delegates
the append-only ledger and final seal to :mod:`live_acceptance`.

The module remains importable with injected command/service seams so its host
policy can be tested without Docker, networking, a cloud VM, or root access.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import platform
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any, Protocol, Self, TypeVar

_BOOTSTRAP_CANONICAL_REPO = Path("/opt/fort-gym-m1a")
_BOOTSTRAP_SOURCE_REPO = Path(__file__).absolute().parents[2]


def _caller_owned_process_ids() -> tuple[int, ...]:
    """Scope nonroot preflight to its UID; root unmount rechecks all processes."""
    owner_uid = os.geteuid()
    result = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            metadata = path.stat()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if metadata.st_uid == owner_uid:
            result.append(int(path.name))
    return tuple(sorted(result))


def _bootstrap_repo_import() -> None:
    candidate = Path(os.path.normpath(str(_BOOTSTRAP_SOURCE_REPO)))
    if sys.flags.isolated == 1 and candidate != _BOOTSTRAP_CANONICAL_REPO:
        raise RuntimeError("isolated host runner is outside the canonical source root")
    if candidate == _BOOTSTRAP_CANONICAL_REPO:
        current = Path(candidate.anchor)
        for component in candidate.parts[1:]:
            current /= component
            metadata = current.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise RuntimeError("canonical source ancestry is mutable or linked")
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)


_bootstrap_repo_import()

from infra.m1b.diagnostics import capture_run_diagnostics, describe_exception  # noqa: E402

from fort_gym.bench.eval.fort_eval_easy_p1 import p1_measurement_code_digest
from fort_gym.bench.run.fault_driver import (
    FaultCommandResult,
    FaultGate,
    LinuxHostFaultProbe,
    M1BFaultDriver,
    OwnedRun,
    OwnedRunEvidenceLoader,
    PrelaunchEnospcWorkspace,
    PreReadinessOomMonitor,
    ProtectedCanary,
    SubprocessFaultCommandRunner,
    authorize_private_m1b_fault,
    load_completed_fault_observation,
)
from fort_gym.bench.run.fault_session import (
    FaultSessionIdentity,
    FaultSessionParticipant,
    FaultSessionStore,
)
from fort_gym.bench.run.live_acceptance import (
    FROZEN_ACCEPTANCE_SHA256,
    FROZEN_GATE_PLAN,
    FROZEN_PLAN_SHA256,
    MAX_REAL_RUNTIME_ATTEMPTS,
    CleanupPassContext,
    CleanupPassResult,
    GateExecutionContext,
    GateExecutionResult,
    LiveAcceptanceBatchController,
    LiveAcceptanceOutcome,
    LocalCreditImport,
    LocalCreditScope,
    PrivilegedCommandResult,
    SourceManifestLock,
    authorize_private_m1b_live_acceptance,
)
from fort_gym.bench.run.process_supervisor import (
    PortLease,
    PortLeaseError,
    SupervisorError,
    validate_terminal_chain,
)
from fort_gym.bench.run.provider_network_isolation import ProviderNetworkHostConfig
from fort_gym.bench.run.residue_audit import (
    BatchResidueAuditor,
    ResidueExpectation,
)
from fort_gym.bench.run.runtime_controller import (
    CommandResult as RuntimeCommandResult,
)
from fort_gym.bench.run.runtime_controller import (
    DockerRuntimeController,
    RuntimeTestFault,
)
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import SupervisedRunManager
from fort_gym.bench.run.supervision_service import (
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionConfigurationError,
    SupervisionService,
)

# ``infra`` is a namespace package in the source tree and remains importable in
# the packet.  Importing constants keeps the client/broker protocol byte-exact.
from infra.m1b.root_broker import (
    FROZEN_ACCEPTANCE_SHA256 as BROKER_ACCEPTANCE_SHA256,
)
from infra.m1b.root_broker import (
    RECEIPT_SCHEMA,
    REQUEST_SCHEMA,
    broker_policy_sha256,
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_PROVIDER_VARIABLE_RE = re.compile(
    r"(?:^|_)(?:OPENAI|ANTHROPIC|OPENROUTER|GEMINI|GOOGLE|MISTRAL|COHERE)(?:_|$)"
)
_FAULT_ENV_RE = re.compile(r"^FORT_GYM_.*(?:FAULT|TEST|INJECT|OPENROUTER)")
_CANONICAL_STATE_ROOT = Path("/var/lib/fortgym-m1b")
_CANONICAL_REPO_ROOT = Path("/opt/fort-gym-m1a")
_CANONICAL_PACKET_ROOT = Path("/opt/fortgym-m1b/packet")
_CANONICAL_DFROOT = Path("/opt/dwarf-fortress")
_CANONICAL_RUNTIME_ARCHIVE = Path("/opt/fortgym-m1b/runtime-image.tar.zst")
_BROKER_EXECUTABLE = Path("/usr/local/libexec/fortgym-m1b-root-broker")
_ROOT_EVIDENCE_ROOT = Path("/var/lib/fortgym-m1b-root-evidence")
_SUDO = Path("/usr/bin/sudo")
_HELPER = Path("/usr/local/libexec/fortgym-provider-network-helper")
_BPF_OBJECT = Path("/usr/local/lib/fortgym/provider_network.bpf.o")
_CGROUP_ROOT = Path("/sys/fs/cgroup/fortgym-provider-net")
_BPFFS_ROOT = Path("/sys/fs/bpf/fortgym-provider-net")
_CONTAINER_ENTRYPOINT = "/opt/fortgym-m1b/runtime_entrypoint.sh"
_CONTAINER_EVIDENCE_DIR = "/artifacts"
_CONTAINER_INSPECT_PROJECTION_SCHEMA = "fortgym.m1b-container-inspect-projection/v1"
_RUNTIME_ATTESTATION_PROJECTION_SCHEMA = "fortgym.m1b-runtime-attestation-projection/v1"
_CLEANUP_CRITERIA = next(
    gate.criteria for gate in FROZEN_GATE_PLAN if gate.gate_id == "CLEANUP"
)
_GATE_IDS = tuple(gate.gate_id for gate in FROZEN_GATE_PLAN)
_LOCAL_CREDIT_ORDER = (
    ("PORT-1", LocalCreditScope.COMPLETE_LOCAL_GATE),
    ("ORPHAN-1", LocalCreditScope.LOCAL_SUBPROCEDURE),
    ("PROVIDER-ENV", LocalCreditScope.COMPLETE_LOCAL_GATE),
    ("CAP-FAKE", LocalCreditScope.COMPLETE_LOCAL_GATE),
)
_LOCAL_CREDIT_NODES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "PORT-1": (
            (
                "tests/test_process_supervisor.py::"
                "test_port_lease_32_way_race_has_one_winner_and_31_conflicts"
            ),
        ),
        "ORPHAN-1": (
            (
                "tests/test_runtime_controller.py::"
                "test_reconcile_removes_only_exact_contract_owned_and_leaves_foreign_canary"
            ),
            (
                "tests/test_supervised_manager.py::"
                "test_reconcile_reaps_exact_orphan_process_group_and_leaves_foreign_canary"
            ),
            (
                "tests/test_residue_audit.py::"
                "test_clean_batch_is_audited_twice_and_retains_only_evidence"
            ),
        ),
        "PROVIDER-ENV": (
            (
                "tests/test_provider_environment_subprocess.py::"
                "test_scripted_runtime_contract_child_has_exact_provider_free_environment"
            ),
        ),
        "CAP-FAKE": (
            (
                "tests/test_cap_fake_end_to_end.py::"
                "test_cap_fake_contract_clarifies_zero_remaining_positive_cap"
            ),
            (
                "tests/test_cap_fake_end_to_end.py::"
                "test_one_fake_response_reaches_positive_cap_and_persists_terminal_reason"
            ),
        ),
    }
)
_POST_READINESS_GATES = frozenset(
    {"DF-KILL", "HARNESS-KILL", "ENOSPC", "CONTAINER-RESTART", "DAEMON-RESTART"}
)
_EXPECTED_PACKET_AUTHORITY = {
    "provider_calls": 0,
    "provider_cost_usd": 0,
    "paid_models": "forbidden",
    "production_access": "forbidden",
    "production_mutation": "forbidden",
    "publish_deploy_push_tag_e1": "forbidden",
    "infrastructure_daily_ceiling_usd": 210,
    "infrastructure_authorized_local_date": "2026-09-05",
    "infrastructure_authority_expires_at": "2026-09-06T12:00:00Z",
    "ephemeral_only": True,
}

if BROKER_ACCEPTANCE_SHA256 != FROZEN_ACCEPTANCE_SHA256:
    raise RuntimeError("root broker and live controller acceptance digests differ")
if (
    len(FROZEN_GATE_PLAN) != 16
    or sum(gate.real_runtime_attempts for gate in FROZEN_GATE_PLAN)
    != MAX_REAL_RUNTIME_ATTEMPTS
):
    raise RuntimeError("host runner imported a noncanonical live acceptance plan")


class HostRunnerError(RuntimeError):
    """The concrete host runner could not prove a bounded live action."""


class HostPolicyError(HostRunnerError):
    """The host or explicit invocation violates the frozen safety policy."""


class BrokerClientError(HostRunnerError):
    """The root-broker transport or receipt is invalid."""


class GateExecutionError(HostRunnerError):
    """A live gate did not produce its exact durable result."""


@dataclass(frozen=True)
class HostLiveAcceptanceOutcome:
    controller: LiveAcceptanceOutcome
    post_seal_cleanup_path: Path
    post_seal_cleanup_sha256: str
    broker_attestation_path: Path
    broker_attestation_sha256: str
    broker_attestation_reference_path: Path
    broker_attestation_receipt_path: Path

    @property
    def batch_id(self) -> str:
        return self.controller.batch_id

    @property
    def decision(self) -> Any:
        return self.controller.decision

    @property
    def real_runtime_attempts_started(self) -> int:
        return self.controller.real_runtime_attempts_started

    @property
    def real_runtime_attempts_completed(self) -> int:
        return self.controller.real_runtime_attempts_completed

    @property
    def non_runtime_attempts_started(self) -> int:
        return self.controller.non_runtime_attempts_started

    @property
    def non_runtime_attempts_completed(self) -> int:
        return self.controller.non_runtime_attempts_completed

    @property
    def gate_results_path(self) -> Path:
        return self.controller.gate_results_path

    @property
    def decision_path(self) -> Path:
        return self.controller.decision_path

    @property
    def evidence_manifest_path(self) -> Path:
        return self.controller.evidence_manifest_path

    @property
    def seal_path(self) -> Path:
        return self.controller.seal_path


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HostRunnerError("non-finite evidence value is forbidden")
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_json(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _safe_json(dataclasses.asdict(value))
    return repr(value)


def _write_once_json(path: Path, payload: Mapping[str, Any]) -> Path:
    encoded = _canonical_bytes(_safe_json(dict(payload))) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short host-runner evidence write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return path


def _require_root_nonwritable_ancestry(path: Path) -> None:
    current = path
    while True:
        metadata = current.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise HostPolicyError(f"trusted host ancestry is mutable: {current}")
        if current == Path(current.anchor):
            return
        current = current.parent


def _copy_once(source: Path, target: Path) -> Path:
    if not source.is_absolute() or not source.is_file() or source.is_symlink():
        raise HostPolicyError("input evidence must be an absolute regular file")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("short input evidence copy")
                    view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if _sha256_file(source) != _sha256_file(target):
        raise HostRunnerError("copied input evidence digest differs")
    return target


def _copy_or_verify(source: Path, target: Path) -> Path:
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise HostPolicyError("existing immutable input is unsafe")
        if _sha256_file(source) != _sha256_file(target):
            raise HostPolicyError("existing immutable input digest differs")
        return target
    return _copy_once(source, target)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise HostPolicyError("required JSON input is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostPolicyError("required JSON input is invalid") from exc
    if not isinstance(value, dict):
        raise HostPolicyError("required JSON input must be an object")
    return value


def _read_jsonl_objects(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise HostPolicyError("required JSONL evidence is unsafe")
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise HostPolicyError("required JSONL evidence is empty or partial")
    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HostPolicyError("required JSONL evidence is invalid") from exc
        if not isinstance(value, dict):
            raise HostPolicyError("required JSONL record is not an object")
        records.append(value)
    return tuple(records)


@dataclass(frozen=True)
class HostPaths:
    batch_id: str
    packet_root: Path
    state_root: Path
    repo_root: Path = _CANONICAL_REPO_ROOT
    dfroot: Path = _CANONICAL_DFROOT
    runtime_archive_path: Path = _CANONICAL_RUNTIME_ARCHIVE
    broker_executable: Path = _BROKER_EXECUTABLE
    sudo_executable: Path = _SUDO
    require_canonical_host: bool = True

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.batch_id):
            raise HostPolicyError("batch ID is invalid")
        for name in (
            "packet_root",
            "state_root",
            "repo_root",
            "dfroot",
            "runtime_archive_path",
            "broker_executable",
            "sudo_executable",
        ):
            value = Path(getattr(self, name))
            if not value.is_absolute() or "\0" in str(value):
                raise HostPolicyError(f"{name} must be absolute and NUL-free")
            object.__setattr__(self, name, Path(os.path.normpath(str(value))))
        if self.require_canonical_host and (
            self.packet_root != _CANONICAL_PACKET_ROOT
            or self.state_root != _CANONICAL_STATE_ROOT
            or self.repo_root != _CANONICAL_REPO_ROOT
            or self.dfroot != _CANONICAL_DFROOT
            or self.runtime_archive_path != _CANONICAL_RUNTIME_ARCHIVE
            or self.broker_executable != _BROKER_EXECUTABLE
            or self.sudo_executable != _SUDO
        ):
            raise HostPolicyError(
                "live host paths differ from the pinned packet layout"
            )

    @property
    def evidence_root(self) -> Path:
        return self.state_root / "evidence" / self.batch_id

    @property
    def service_control_root(self) -> Path:
        return self.state_root / "control"

    @property
    def artifacts_root(self) -> Path:
        return self.state_root / "artifacts"

    @property
    def db_path(self) -> Path:
        # state_root is root-owned on the canonical host. SQLite needs write
        # access to the containing directory for its journal/WAL.
        return self.service_control_root / "registry.sqlite3"

    @property
    def broker_request_root(self) -> Path:
        return self.state_root / "broker" / "requests"

    @property
    def acceptance_path(self) -> Path:
        return self.repo_root / "infra" / "m1b" / "acceptance.yaml"

    @property
    def source_manifest_path(self) -> Path:
        return self.packet_root / "source-manifest.json"

    @property
    def packet_manifest_path(self) -> Path:
        return self.packet_root / "PACKET.json"


@dataclass(frozen=True)
class PreparedInputs:
    contract_path: Path
    source_manifest: SourceManifestLock
    local_credits: tuple[LocalCreditImport, ...]


def _source_manifest_file_sha256(paths: HostPaths, relative: str) -> str:
    manifest = _read_json_object(paths.source_manifest_path)
    files = manifest.get("files")
    matches = (
        [
            item
            for item in files
            if isinstance(item, Mapping) and item.get("path") == relative
        ]
        if isinstance(files, list)
        else []
    )
    installed = paths.repo_root / relative
    if (
        manifest.get("schema") != "fortgym.m1b-live-source-manifest/v1"
        or len(matches) != 1
        or not _SHA256_RE.fullmatch(str(matches[0].get("sha256") or ""))
        or not installed.is_file()
        or installed.is_symlink()
        or matches[0].get("sha256") != _sha256_file(installed)
        or matches[0].get("size_bytes") != installed.stat().st_size
    ):
        raise HostPolicyError(f"broker source manifest binding differs: {relative}")
    return str(matches[0]["sha256"])


def validate_host_policy(
    paths: HostPaths,
    *,
    environment: Mapping[str, str] | None = None,
    system_name: str | None = None,
    machine: str | None = None,
    effective_uid: int | None = None,
) -> None:
    environment = os.environ if environment is None else environment
    system_name = platform.system() if system_name is None else system_name
    machine = platform.machine() if machine is None else machine
    effective_uid = os.geteuid() if effective_uid is None else effective_uid
    if system_name != "Linux" or machine not in {"x86_64", "amd64"}:
        raise HostPolicyError("live acceptance requires isolated x86-64 Linux")
    if effective_uid == 0:
        raise HostPolicyError("live acceptance main process must remain nonroot")
    if paths.require_canonical_host and sys.flags.isolated != 1:
        raise HostPolicyError("live acceptance requires Python isolated mode")
    if sys.version_info[:2] != (3, 11):
        raise HostPolicyError("live acceptance requires the pinned Python 3.11 runtime")
    forbidden = sorted(
        name
        for name, value in environment.items()
        if value
        and (
            _PROVIDER_VARIABLE_RE.search(name.upper())
            or _FAULT_ENV_RE.search(name.upper())
        )
    )
    if forbidden:
        raise HostPolicyError(
            "provider credentials or ambient fault knobs are forbidden: "
            + ", ".join(forbidden)
        )
    for path in (
        paths.packet_root,
        paths.state_root,
        paths.repo_root,
        paths.broker_request_root,
    ):
        if not path.is_dir() or path.is_symlink():
            raise HostPolicyError(
                f"required host directory is absent or unsafe: {path}"
            )
    for path in (
        paths.acceptance_path,
        paths.source_manifest_path,
        paths.packet_manifest_path,
        paths.runtime_archive_path,
        paths.broker_executable,
        paths.sudo_executable,
        _HELPER,
        _BPF_OBJECT,
    ):
        if not path.is_file() or path.is_symlink():
            raise HostPolicyError(f"required host file is absent or unsafe: {path}")
    if _sha256_file(paths.acceptance_path) != FROZEN_ACCEPTANCE_SHA256:
        raise HostPolicyError("acceptance contract digest differs")
    if not os.access(paths.broker_executable, os.X_OK) or not os.access(
        paths.sudo_executable, os.X_OK
    ):
        raise HostPolicyError("root broker transport is not executable")
    for path in (
        paths.repo_root,
        paths.packet_root,
        paths.packet_manifest_path,
        paths.source_manifest_path,
        paths.runtime_archive_path,
        paths.broker_executable,
        _BPF_OBJECT,
    ):
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise HostPolicyError(f"trusted host path is mutable or linked: {path}")
        _require_root_nonwritable_ancestry(path)
    helper = _HELPER.lstat()
    if (
        not stat.S_ISREG(helper.st_mode)
        or helper.st_uid != 0
        or stat.S_IMODE(helper.st_mode) != 0o4750
        or not os.access(_HELPER, os.X_OK)
    ):
        raise HostPolicyError("provider-network helper identity or mode differs")


def prepare_inputs(paths: HostPaths) -> PreparedInputs:
    """Verify the packet and generate fresh source-bound local credits."""

    root = paths.evidence_root
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            raise HostPolicyError("batch evidence root is unsafe")
    else:
        root.mkdir(parents=True, mode=0o700)
    inputs = root / "inputs"
    inputs.mkdir(exist_ok=True, mode=0o700)
    contract = _copy_or_verify(paths.acceptance_path, inputs / "acceptance.yaml")
    if _sha256_file(contract) != FROZEN_ACCEPTANCE_SHA256:
        raise HostPolicyError("copied acceptance contract digest differs")
    source_payload = _read_json_object(paths.source_manifest_path)
    packet_payload = _read_json_object(paths.packet_manifest_path)
    source_record = packet_payload.get("source")
    runtime_archive = packet_payload.get("runtime_archive")
    files = source_payload.get("files")
    if (
        packet_payload.get("schema") != "fortgym.m1b-live-input-packet/v1"
        or packet_payload.get("authority") != _EXPECTED_PACKET_AUTHORITY
        or packet_payload.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
        or not isinstance(source_record, Mapping)
        or source_record.get("manifest") != "source-manifest.json"
        or source_payload.get("schema") != "fortgym.m1b-live-source-manifest/v1"
        or not isinstance(files, list)
        or not files
        or source_payload.get("file_count") != len(files)
        or source_payload.get("tree_sha256") != _sha256_bytes(_canonical_bytes(files))
        or source_record.get("tree_sha256") != source_payload.get("tree_sha256")
        or source_record.get("extract_root") != str(paths.repo_root)
        or not isinstance(runtime_archive, Mapping)
        or runtime_archive.get("platform") != "linux/amd64"
        or runtime_archive.get("manifest_sha256")
        != "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
        or runtime_archive.get("config_sha256")
        != "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
        or not _SHA256_RE.fullmatch(str(runtime_archive.get("compressed_sha256") or ""))
        or isinstance(runtime_archive.get("size_bytes"), bool)
        or not isinstance(runtime_archive.get("size_bytes"), int)
        or runtime_archive.get("size_bytes", 0) <= 0
    ):
        raise HostPolicyError("packet/source-manifest identity differs")
    expected_files: dict[str, Mapping[str, Any]] = {}
    for item in files:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise HostPolicyError("source manifest file record is invalid")
        relative = str(item["path"])
        if (
            relative in expected_files
            or relative.startswith("/")
            or ".." in Path(relative).parts
        ):
            raise HostPolicyError("source manifest path is unsafe or duplicated")
        expected_files[relative] = item
    required_source_paths = {
        "infra/m1b/run_live_acceptance.py",
        "infra/m1b/root_broker.py",
        "fort_gym/bench/run/live_acceptance.py",
        *(
            node.split("::", 1)[0]
            for nodes in _LOCAL_CREDIT_NODES.values()
            for node in nodes
        ),
    }
    for relative in required_source_paths:
        record = expected_files.get(relative)
        path = paths.repo_root / relative
        if (
            record is None
            or not path.is_file()
            or path.is_symlink()
            or record.get("sha256") != _sha256_file(path)
            or record.get("size_bytes") != path.stat().st_size
        ):
            raise HostPolicyError(f"current source differs from packet: {relative}")
    source = _copy_or_verify(
        paths.source_manifest_path,
        inputs / "source-manifest.json",
    )
    source_lock = SourceManifestLock(path=source, sha256=_sha256_file(source))
    credits: list[LocalCreditImport] = []
    for gate_id, scope in _LOCAL_CREDIT_ORDER:
        gate = next(gate for gate in FROZEN_GATE_PLAN if gate.gate_id == gate_id)
        evidence = _run_fresh_local_credit(
            paths,
            gate_id=gate_id,
            node_ids=_LOCAL_CREDIT_NODES[gate_id],
            source_manifest_sha256=source_lock.sha256,
        )
        credits.append(
            LocalCreditImport(
                gate_id=gate_id,
                scope=scope,
                criteria_passed=gate.criteria,
                evidence_paths=evidence,
            )
        )
    return PreparedInputs(
        contract_path=contract,
        source_manifest=source_lock,
        local_credits=tuple(credits),
    )


def _junit_counts(path: Path, *, node_ids: Sequence[str]) -> dict[str, int]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise HostPolicyError("fresh local-credit JUnit is invalid") from exc
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise HostPolicyError("fresh local-credit JUnit lacks a test suite")
    counts = {
        name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }
    cases = [case for suite in suites for case in suite.findall("testcase")]
    expected_names = sorted(node.rsplit("::", 1)[-1] for node in node_ids)
    observed_names = sorted(str(case.attrib.get("name") or "") for case in cases)
    if (
        counts["tests"] != len(node_ids)
        or len(cases) != len(node_ids)
        or observed_names != expected_names
        or any(counts[name] != 0 for name in ("failures", "errors", "skipped"))
        or any(case.find("skipped") is not None for case in cases)
    ):
        raise HostPolicyError("fresh local-credit JUnit results differ")
    return counts


def _run_fresh_local_credit(
    paths: HostPaths,
    *,
    gate_id: str,
    node_ids: Sequence[str],
    source_manifest_sha256: str,
) -> tuple[Path, ...]:
    credit_dir = paths.evidence_root / "inputs" / "local" / gate_id
    credit_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    junit = credit_dir / "pytest.xml"
    receipt = credit_dir / "receipt.json"
    if junit.exists() or receipt.exists():
        if (
            not (junit.is_file() and receipt.is_file())
            or junit.is_symlink()
            or receipt.is_symlink()
        ):
            raise HostPolicyError("partial local-credit evidence cannot be resumed")
        recorded = _read_json_object(receipt)
        counts = _junit_counts(junit, node_ids=node_ids)
        if (
            recorded.get("schema") != "fortgym.m1b-fresh-local-credit/v1"
            or recorded.get("gate_id") != gate_id
            or recorded.get("source_manifest_sha256") != source_manifest_sha256
            or recorded.get("node_ids") != list(node_ids)
            or recorded.get("junit_sha256") != _sha256_file(junit)
            or recorded.get("counts") != counts
            or recorded.get("returncode") != 0
        ):
            raise HostPolicyError("resumed local-credit receipt differs")
        return junit, receipt

    argv = (
        str(Path(sys.executable).absolute()),
        "-I",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--junitxml",
        str(junit),
        *node_ids,
    )
    environment = {
        "DF_PROTO_ENABLED": "1",
        "FORT_GYM_DISABLE_DOTENV": "1",
        "HOME": "/home/fortgym",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "LOGNAME": "fortgym",
        "PATH": "/opt/fortgym-m1b/venv/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "USER": "fortgym",
    }
    completed = subprocess.run(
        argv,
        cwd=paths.repo_root,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        shell=False,
        timeout=600.0,
    )
    if completed.returncode != 0 or not junit.is_file() or junit.is_symlink():
        raise HostPolicyError(f"fresh {gate_id} local-credit tests failed")
    counts = _junit_counts(junit, node_ids=node_ids)
    payload = {
        "schema": "fortgym.m1b-fresh-local-credit/v1",
        "gate_id": gate_id,
        "source_manifest_sha256": source_manifest_sha256,
        "argv": list(argv),
        "node_ids": list(node_ids),
        "interpreter": str(Path(sys.executable).absolute()),
        "python_version": platform.python_version(),
        "pytest_plugin_autoload": False,
        "provider_environment_names": [],
        "returncode": completed.returncode,
        "counts": counts,
        "junit_sha256": _sha256_file(junit),
        "stdout_sha256": _sha256_bytes(completed.stdout.encode("utf-8")),
        "stderr_sha256": _sha256_bytes(completed.stderr.encode("utf-8")),
    }
    _write_once_json(receipt, payload)
    return junit, receipt


@dataclass(frozen=True)
class PublicRunBinding:
    attempt_id: str
    attempt_identity_sha256: str
    run_id: str
    contract_sha256: str
    nonce_sha256: str
    cohort_sha256: str
    port: int
    peer_run_id: str | None = None
    session_sha256: str | None = None

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.attempt_id):
            raise ValueError("run binding attempt ID is invalid")
        if not _ID_RE.fullmatch(self.run_id):
            raise ValueError("run binding ID is invalid")
        for name in (
            "attempt_identity_sha256",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
        ):
            if not _SHA256_RE.fullmatch(str(getattr(self, name))):
                raise ValueError(f"run binding {name} is invalid")
        if self.peer_run_id is not None and (
            not _ID_RE.fullmatch(self.peer_run_id) or self.peer_run_id == self.run_id
        ):
            raise ValueError("run binding peer ID is invalid")
        if self.session_sha256 is not None and not _SHA256_RE.fullmatch(
            self.session_sha256
        ):
            raise ValueError("run binding session digest is invalid")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not (1 <= self.port <= 65_535)
        ):
            raise ValueError("run binding port is invalid")


@dataclass(frozen=True)
class BrokerReceipt:
    action: str
    ok: bool
    logical_argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    stdout_sha256: str
    stderr_sha256: str
    policy_sha256: str
    broker_source_sha256: str
    result: Mapping[str, Any] | None
    request_id: str
    evidence_path: Path


BrokerTransport = Callable[
    [Sequence[str], float, Mapping[str, str]], subprocess.CompletedProcess[str]
]


def _subprocess_transport(
    argv: Sequence[str],
    timeout_seconds: float,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tuple(argv),
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(environment),
        shell=False,
        timeout=timeout_seconds,
    )


class RootBrokerClient:
    """Nonroot, shell-free client for one semantic root-broker request."""

    def __init__(
        self,
        *,
        paths: HostPaths,
        gate_id: str,
        transport: BrokerTransport = _subprocess_transport,
    ) -> None:
        if gate_id not in {*_GATE_IDS, "BATCH-CANARY"}:
            raise ValueError("broker client gate is not frozen")
        self.paths = paths
        self.gate_id = gate_id
        self._transport = transport
        self._lock = threading.Lock()
        self._evidence_dir = paths.evidence_root / "broker-client" / gate_id
        self._error_dir = paths.evidence_root / "broker-errors" / gate_id
        self._container_ids: dict[str, str] = {}
        self._expected_policy_sha256 = broker_policy_sha256(
            repo_root=paths.repo_root,
            state_root=paths.state_root,
        )
        self._expected_broker_source_sha256 = _source_manifest_file_sha256(
            paths,
            "infra/m1b/root_broker.py",
        )

    def execute(
        self,
        logical_argv: Sequence[str],
        *,
        binding: PublicRunBinding | None,
        timeout_seconds: float,
        action: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> BrokerReceipt:
        argv = tuple(str(item) for item in logical_argv)
        if not argv or any(not item or "\0" in item for item in argv):
            raise BrokerClientError("logical broker command is invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 600
        ):
            raise BrokerClientError("broker timeout is invalid")
        selected_action, selected_parameters = (
            (action, dict(parameters or {}))
            if action is not None
            else self._classify(argv, binding)
        )
        if not isinstance(selected_action, str) or not selected_action:
            raise BrokerClientError("broker action is invalid")
        semantic_argv = self._semantic_logical_argv(argv, action=selected_action)
        request_id = secrets.token_hex(32)
        request = {
            "schema": REQUEST_SCHEMA,
            "request_id": request_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "batch_id": self.paths.batch_id,
            "gate_id": self.gate_id,
            "grant_kind": "attempt" if binding is not None else "batch_canary",
            "attempt_id": binding.attempt_id if binding is not None else None,
            "attempt_identity_sha256": (
                binding.attempt_identity_sha256 if binding is not None else None
            ),
            "action": selected_action,
            "run_id": binding.run_id if binding is not None else None,
            "peer_run_id": binding.peer_run_id if binding is not None else None,
            "contract_sha256": (
                binding.contract_sha256 if binding is not None else None
            ),
            "nonce_sha256": binding.nonce_sha256 if binding is not None else None,
            "cohort_sha256": binding.cohort_sha256 if binding is not None else None,
            "logical_argv_sha256": _sha256_bytes(_canonical_bytes(list(semantic_argv))),
            "parameters": selected_parameters,
        }
        request_path = self.paths.broker_request_root / f"{request_id}.json"
        request_sha256 = _sha256_bytes(_canonical_bytes(request) + b"\n")
        with self._lock:
            _write_once_json(request_path, request)
        command = (
            str(self.paths.sudo_executable),
            "--non-interactive",
            "--",
            str(self.paths.broker_executable),
            "--request",
            str(request_path),
        )
        environment = {
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        }
        try:
            completed = self._transport(
                command, min(float(timeout_seconds) + 30.0, 630.0), environment
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BrokerClientError("root broker transport failed") from exc
        if completed.returncode != 0:
            error_code = "unparsed_broker_rejection"
            reason_sha256 = None
            try:
                failure = json.loads(completed.stdout)
            except (TypeError, json.JSONDecodeError):
                failure = None
            if (
                isinstance(failure, Mapping)
                and set(failure) == {"schema", "ok", "error_code", "reason_sha256"}
                and failure.get("schema") == "fortgym.m1b-root-broker-error/v1"
                and failure.get("ok") is False
                and isinstance(failure.get("error_code"), str)
                and _SHA256_RE.fullmatch(str(failure.get("reason_sha256") or ""))
            ):
                error_code = str(failure["error_code"])
                reason_sha256 = str(failure["reason_sha256"])
            try:
                _write_once_json(
                    self._error_dir / f"{request_id}.json",
                    {
                        "schema": "fortgym.m1b-root-broker-client-error/v1",
                        "request_id": request_id,
                        "request_sha256": request_sha256,
                        "gate_id": self.gate_id,
                        "attempt_id": request["attempt_id"],
                        "attempt_identity_sha256": request["attempt_identity_sha256"],
                        "action": selected_action,
                        "logical_argv_sha256": request["logical_argv_sha256"],
                        "error_code": error_code,
                        "reason_sha256": reason_sha256,
                        "returncode": completed.returncode,
                        "stdout_sha256": _sha256_bytes(
                            completed.stdout.encode("utf-8", errors="replace")
                        ),
                        "stderr_sha256": _sha256_bytes(
                            completed.stderr.encode("utf-8", errors="replace")
                        ),
                    },
                )
            except (OSError, TypeError, ValueError):
                pass
            suffix = f" [{reason_sha256}]" if reason_sha256 is not None else ""
            raise BrokerClientError(
                "root broker rejected the semantic request" + suffix
            )
        try:
            receipt = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BrokerClientError("root broker returned invalid JSON") from exc
        if not isinstance(receipt, Mapping):
            raise BrokerClientError("root broker receipt is not an object")
        expected_receipt_fields = {
            "schema",
            "ok",
            "request_id",
            "request_sha256",
            "acceptance_sha256",
            "policy_sha256",
            "broker_source_sha256",
            "batch_id",
            "gate_id",
            "grant_kind",
            "attempt_id",
            "attempt_identity_sha256",
            "action",
            "binding",
            "logical_argv_sha256",
            "returncode",
            "stdout",
            "stderr",
            "stdout_sha256",
            "stderr_sha256",
            "result",
            "shell",
            "action_grant_sha256",
        }
        if (
            set(receipt) != expected_receipt_fields
            or receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("request_id") != request_id
            or receipt.get("request_sha256") != request_sha256
            or receipt.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or receipt.get("batch_id") != self.paths.batch_id
            or receipt.get("gate_id") != self.gate_id
            or receipt.get("grant_kind") != request["grant_kind"]
            or receipt.get("attempt_id") != request["attempt_id"]
            or receipt.get("attempt_identity_sha256")
            != request["attempt_identity_sha256"]
            or receipt.get("action") != selected_action
            or not self._receipt_binding_matches(
                receipt.get("binding"),
                binding=binding,
                action=selected_action,
                stdout=receipt.get("stdout"),
                returncode=receipt.get("returncode"),
            )
            or receipt.get("logical_argv_sha256") != request["logical_argv_sha256"]
            or receipt.get("shell") is not False
            or receipt.get("policy_sha256") != self._expected_policy_sha256
            or receipt.get("broker_source_sha256")
            != self._expected_broker_source_sha256
            or not _SHA256_RE.fullmatch(str(receipt.get("action_grant_sha256") or ""))
        ):
            raise BrokerClientError("root broker receipt identity differs")
        stdout = receipt.get("stdout")
        stderr = receipt.get("stderr")
        returncode = receipt.get("returncode")
        if (
            not isinstance(stdout, str)
            or not isinstance(stderr, str)
            or isinstance(returncode, bool)
            or not isinstance(returncode, int)
            or receipt.get("ok") is not (returncode == 0)
            or receipt.get("stdout_sha256") != _sha256_bytes(stdout.encode("utf-8"))
            or receipt.get("stderr_sha256") != _sha256_bytes(stderr.encode("utf-8"))
        ):
            raise BrokerClientError("root broker output digest differs")
        safe_result = receipt.get("result")
        if selected_action == "attest_broker_evidence" and returncode == 0:
            try:
                parsed_stdout = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise BrokerClientError(
                    "root broker attestation result is invalid"
                ) from exc
            if (
                not isinstance(safe_result, Mapping)
                or dict(safe_result) != parsed_stdout
            ):
                raise BrokerClientError("root broker attestation result differs")
            safe_result = dict(safe_result)
        elif safe_result is not None:
            raise BrokerClientError("root broker exposed an unexpected action result")
        public_receipt = {
            key: value
            for key, value in receipt.items()
            if key not in {"stdout", "stderr"}
        }
        evidence_path = _write_once_json(
            self._evidence_dir / f"{request_id}.json", public_receipt
        )
        return BrokerReceipt(
            action=selected_action,
            ok=returncode == 0,
            logical_argv=argv,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_sha256=str(receipt["stdout_sha256"]),
            stderr_sha256=str(receipt["stderr_sha256"]),
            policy_sha256=str(receipt["policy_sha256"]),
            broker_source_sha256=str(receipt["broker_source_sha256"]),
            result=safe_result,
            request_id=request_id,
            evidence_path=evidence_path,
        )

    @staticmethod
    def _semantic_logical_argv(
        argv: tuple[str, ...], *, action: str
    ) -> tuple[str, ...]:
        if (
            argv
            and Path(argv[0]).name == "docker"
            and action.startswith(("docker_", "canary_"))
        ):
            return ("docker", *argv[1:])
        return argv

    def _receipt_binding_matches(
        self,
        value: Any,
        *,
        binding: PublicRunBinding | None,
        action: str,
        stdout: Any,
        returncode: Any,
    ) -> bool:
        if binding is None:
            return value is None
        if not isinstance(value, Mapping) or set(value) != {
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "container_name",
            "container_id",
            "port",
        }:
            return False
        container_name = f"fortgym-m1b-{binding.run_id}-{binding.contract_sha256[:12]}"
        if any(
            (
                value.get("run_id") != binding.run_id,
                value.get("contract_sha256") != binding.contract_sha256,
                value.get("nonce_sha256") != binding.nonce_sha256,
                value.get("cohort_sha256") != binding.cohort_sha256,
                value.get("container_name") != container_name,
                value.get("port") != binding.port,
            )
        ):
            return False
        observed_id = value.get("container_id")
        if action in {"docker_image_inspect", "mount_enospc"}:
            return observed_id is None
        if action == "docker_container_inspect" and observed_id is None:
            return (
                not isinstance(returncode, bool)
                and isinstance(returncode, int)
                and returncode != 0
                and stdout == ""
            )
        if action == "docker_managed_list" and observed_id is None:
            # Once cleanup has removed the authenticated container, the root
            # broker binds the run identity but correctly has no live
            # container ID.  An rc=0, byte-empty filtered inventory is the
            # positive absence proof.  Requiring an ID here rejected that
            # proof client-side after PORT-2 even though the root receipt was
            # valid and no managed container remained.
            return returncode == 0 and not isinstance(returncode, bool) and stdout == ""
        if action == "unmount_enospc" and observed_id is None:
            # Unmount follows verified container removal. The root broker
            # independently checks process/container absence and mount identity;
            # its receipt binds the run but must not invent a live container ID.
            return returncode == 0 and not isinstance(returncode, bool) and stdout == ""
        if not isinstance(observed_id, str) or not _CONTAINER_ID_RE.fullmatch(
            observed_id
        ):
            return False
        observed_id = observed_id.lower()
        expected_id = self._container_ids.get(binding.run_id)
        if expected_id is None:
            expected_id = self._durable_container_id(binding)
        if expected_id is None and action in {"docker_run", "docker_create"}:
            if not isinstance(stdout, str) or stdout.strip().lower() != observed_id:
                return False
            expected_id = observed_id
        if expected_id != observed_id:
            return False
        self._container_ids[binding.run_id] = observed_id
        return True

    def _durable_container_id(self, binding: PublicRunBinding) -> str | None:
        path = (
            self.paths.service_control_root
            / binding.run_id
            / "attempts"
            / "attempt-0001"
            / "runtime"
            / "container-created.json"
        )
        if not path.exists():
            return None
        try:
            payload = _read_json_object(path)
        except HostPolicyError:
            return None
        container_id = str(payload.get("container_id") or "").lower()
        if (
            payload.get("schema") != "fortgym.m1b-container-created/v1"
            or payload.get("run_id") != binding.run_id
            or payload.get("contract_sha256") != binding.contract_sha256
            or payload.get("nonce_sha256") != binding.nonce_sha256
            or payload.get("container_name")
            != f"fortgym-m1b-{binding.run_id}-{binding.contract_sha256[:12]}"
            or not _CONTAINER_ID_RE.fullmatch(container_id)
        ):
            return None
        return container_id

    def _classify(
        self,
        argv: tuple[str, ...],
        binding: PublicRunBinding | None,
    ) -> tuple[str, dict[str, Any]]:
        executable = Path(argv[0]).name
        if executable == "docker":
            if argv[1:3] == ("image", "inspect") and len(argv) == 4:
                suffix = argv[3].removeprefix("sha256:")
                kind = (
                    "manifest"
                    if suffix
                    == "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
                    else "config"
                    if suffix
                    == "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
                    else None
                )
                if kind is None:
                    raise BrokerClientError("Docker image inspect is not pinned")
                return "docker_image_inspect", {"reference_kind": kind}
            if len(argv) >= 2 and argv[1] in {"run", "create"}:
                return f"docker_{argv[1]}", {}
            if len(argv) == 3 and argv[1] == "start":
                return "docker_start", {}
            if argv[1:4] == ("inspect", "--type", "container") and len(argv) == 5:
                return "docker_container_inspect", {"identifier": argv[4]}
            if argv[1:5] == ("logs", "--timestamps", "--tail", "10000"):
                return "docker_logs", {}
            if argv[1:3] == ("rm", "--force") and len(argv) == 4:
                return "docker_remove", {}
            if len(argv) >= 2 and argv[1] == "ps":
                return "docker_managed_list", {}
            if len(argv) >= 2 and argv[1] == "exec":
                return "docker_exec_attest", {}
            if argv[1:4] == ("restart", "--time", "0") and len(argv) == 5:
                return "docker_restart", {}
        if argv[:3] == ("/bin/kill", "-KILL", "--") and len(argv) == 4:
            action = {
                "DF-KILL": "signal_runtime",
                "HARNESS-KILL": "signal_harness",
                "ORPHAN-1": "signal_supervisor",
                "ORPHAN-2": "signal_supervisor",
            }.get(self.gate_id)
            if action is not None:
                return action, {}
        if argv[:3] == ("/bin/kill", "-STOP", "--") and len(argv) == 4:
            if self.gate_id == "PORT-2":
                return "pause_peer_harness", {}
            if self.gate_id == "CO-8":
                return "pause_cohort_harness", {}
        if argv[:3] == ("/bin/kill", "-CONT", "--") and len(argv) == 4:
            if self.gate_id == "PORT-2":
                return "resume_peer_harness", {}
            if self.gate_id == "CO-8":
                return "resume_cohort_harness", {}
        if argv and argv[0] == "/bin/mount":
            return "mount_enospc", {}
        if argv[:2] == ("/bin/umount", "--"):
            return "unmount_enospc", {}
        if argv == ("/bin/systemctl", "restart", "docker.service"):
            if binding is None or binding.session_sha256 is None:
                raise BrokerClientError("daemon restart lacks a fault session")
            return "restart_docker", {"session_sha256": binding.session_sha256}
        if argv == (
            "/usr/sbin/nft",
            "--json",
            "list",
            "table",
            "inet",
            "fortgym_m1b_outer",
        ):
            return "verify_outer_guard", {}
        raise BrokerClientError("logical command has no root-broker action")


def _exact_projection_mapping(
    value: Any,
    *,
    name: str,
    keys: frozenset[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BrokerClientError(f"{name} fields differ")
    return value


def _rehydrate_container_inspect_projection(
    stdout: str,
    *,
    controller: DockerRuntimeController,
) -> str:
    """Validate the broker's secret-free projection, then restore local values.

    The root broker never returns raw environment values or host bind sources.
    The controller already owns those values through its immutable contract, so
    this adapter restores them only after every corresponding broker digest and
    every public container field has matched exactly.
    """

    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BrokerClientError("container inspect projection is invalid JSON") from exc
    if (
        not isinstance(document, list)
        or len(document) != 1
        or not isinstance(document[0], Mapping)
    ):
        raise BrokerClientError("container inspect projection cardinality differs")
    inspected = _exact_projection_mapping(
        document[0],
        name="container inspect projection",
        keys=frozenset(
            {
                "FortGymProjectionSchema",
                "Id",
                "Name",
                "Image",
                "RestartCount",
                "State",
                "Config",
                "HostConfig",
                "EnvAttestations",
                "MountAttestations",
            }
        ),
    )
    if inspected.get("FortGymProjectionSchema") != (
        _CONTAINER_INSPECT_PROJECTION_SCHEMA
    ):
        raise BrokerClientError("container inspect projection schema differs")
    container_id = inspected.get("Id")
    if (
        not isinstance(container_id, str)
        or len(container_id) != 64
        or not _CONTAINER_ID_RE.fullmatch(container_id)
        or inspected.get("Name") != f"/{controller.container_name}"
    ):
        raise BrokerClientError("container inspect projection identity differs")

    state = _exact_projection_mapping(
        inspected.get("State"),
        name="container inspect State projection",
        keys=frozenset(
            {
                "Status",
                "Running",
                "Dead",
                "Restarting",
                "OOMKilled",
                "ExitCode",
                "Pid",
            }
        ),
    )
    if (
        not isinstance(state.get("Status"), str)
        or any(
            not isinstance(state.get(name), bool)
            for name in ("Running", "Dead", "Restarting", "OOMKilled")
        )
        or any(
            isinstance(state.get(name), bool) or not isinstance(state.get(name), int)
            for name in ("ExitCode", "Pid")
        )
        or int(state["Pid"]) < 0
    ):
        raise BrokerClientError("container inspect State projection differs")

    config = _exact_projection_mapping(
        inspected.get("Config"),
        name="container inspect Config projection",
        keys=frozenset({"Image", "Labels", "Entrypoint", "Cmd"}),
    )
    labels = config.get("Labels")
    if (
        not isinstance(labels, Mapping)
        or dict(labels) != controller.expected_labels
        or config.get("Image")
        not in {controller.image_reference, controller.image_config_reference}
        or inspected.get("Image")
        not in {controller.image_reference, controller.image_config_reference}
        or config.get("Image") != controller.resolved_image_reference
        or config.get("Entrypoint") != ["/bin/bash"]
        or config.get("Cmd") != [_CONTAINER_ENTRYPOINT]
    ):
        raise BrokerClientError("container inspect Config projection differs")

    host = _exact_projection_mapping(
        inspected.get("HostConfig"),
        name="container inspect HostConfig projection",
        keys=frozenset(
            {
                "NetworkMode",
                "Memory",
                "MemorySwap",
                "PidsLimit",
                "CapDrop",
                "SecurityOpt",
                "RestartPolicy",
                "CpusetCpus",
            }
        ),
    )
    security_opt = host.get("SecurityOpt")
    normalized_security = (
        {
            "no-new-privileges" if value == "no-new-privileges:true" else value
            for value in security_opt
        }
        if isinstance(security_opt, list)
        else set()
    )
    if (
        host.get("NetworkMode") != "host"
        or host.get("Memory") != controller.memory_bytes
        or host.get("MemorySwap") != controller.memory_bytes
        or host.get("PidsLimit") != 256
        or host.get("CapDrop") != ["ALL"]
        or normalized_security != {"no-new-privileges", "seccomp=unconfined"}
        or host.get("RestartPolicy") != {"Name": "no", "MaximumRetryCount": 0}
        or host.get("CpusetCpus") != (controller.cpuset_cpus or "")
        or inspected.get("RestartCount") != 0
    ):
        raise BrokerClientError("container inspect HostConfig projection differs")

    expected_environment = controller.container_environment()
    expected_env_attestations = [
        {
            "name": name,
            "value_sha256": _sha256_bytes(value.encode("utf-8")),
        }
        for name, value in sorted(expected_environment.items())
    ]
    if inspected.get("EnvAttestations") != expected_env_attestations:
        raise BrokerClientError("container environment attestations differ")
    expected_mount_attestations = [
        {
            "destination": _CONTAINER_EVIDENCE_DIR,
            "source_sha256": _sha256_bytes(
                str(controller.evidence_dir).encode("utf-8")
            ),
            "rw": True,
            "type": "bind",
        },
        {
            "destination": _CONTAINER_ENTRYPOINT,
            "source_sha256": _sha256_bytes(
                str(controller.entrypoint_path).encode("utf-8")
            ),
            "rw": False,
            "type": "bind",
        },
    ]
    expected_mount_attestations.sort(key=lambda item: item["destination"])
    if inspected.get("MountAttestations") != expected_mount_attestations:
        raise BrokerClientError("container mount attestations differ")

    legacy = {
        "Id": container_id,
        "Name": inspected["Name"],
        "Image": inspected["Image"],
        "RestartCount": inspected["RestartCount"],
        "State": dict(state),
        "Config": {
            **dict(config),
            "Labels": dict(labels),
            "Env": [
                f"{name}={value}"
                for name, value in sorted(expected_environment.items())
            ],
        },
        "HostConfig": {
            **dict(host),
            "SecurityOpt": ["no-new-privileges", "seccomp=unconfined"],
        },
        "Mounts": [
            {
                "Destination": _CONTAINER_ENTRYPOINT,
                "Source": str(controller.entrypoint_path),
                "RW": False,
                "Type": "bind",
            },
            {
                "Destination": _CONTAINER_EVIDENCE_DIR,
                "Source": str(controller.evidence_dir),
                "RW": True,
                "Type": "bind",
            },
        ],
    }
    return json.dumps([legacy], sort_keys=True, separators=(",", ":")) + "\n"


def _rehydrate_runtime_attestation_projection(
    stdout: str,
    *,
    controller: DockerRuntimeController,
) -> str:
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BrokerClientError(
            "runtime attestation projection is invalid JSON"
        ) from exc
    projected = _exact_projection_mapping(
        document,
        name="runtime attestation projection",
        keys=frozenset(
            {
                "schema",
                "run_id",
                "nonce_sha256",
                "contract_sha256",
                "seed_tree_sha256",
                "seed_world_sha256",
                "image_manifest_sha256",
                "image_config_sha256",
                "image_archive_sha256",
                "map_state",
            }
        ),
    )
    contract = controller.contract
    expected = {
        "schema": _RUNTIME_ATTESTATION_PROJECTION_SCHEMA,
        "run_id": contract.run_id,
        "nonce_sha256": _sha256_bytes(contract.nonce.encode("utf-8")),
        "contract_sha256": contract.contract_sha256,
        "seed_tree_sha256": contract.seed_tree_sha256,
        "seed_world_sha256": contract.seed_world_sha256,
        "image_manifest_sha256": contract.image_manifest_sha256,
        "image_config_sha256": contract.image_config_sha256,
        "image_archive_sha256": contract.image_archive_sha256,
    }
    if any(projected.get(name) != value for name, value in expected.items()) or (
        projected.get("map_state") not in {"MAP_LOADED", "MAP_NOT_LOADED"}
    ):
        raise BrokerClientError("runtime attestation projection identity differs")
    fields = (
        "FORTGYM_ATTEST",
        contract.run_id,
        contract.nonce,
        contract.contract_sha256,
        contract.seed_tree_sha256,
        contract.seed_world_sha256,
        contract.image_manifest_sha256,
        contract.image_config_sha256,
        contract.image_archive_sha256,
        str(projected["map_state"]),
    )
    return "\t".join(fields) + "\n"


class BrokeredRuntimeCommandRunner:
    """Runtime-controller runner: Docker via broker, ``ss`` unprivileged."""

    def __init__(
        self,
        *,
        broker: RootBrokerClient,
        binding: PublicRunBinding,
        controller: DockerRuntimeController,
        local_run: Callable[[Sequence[str], float], RuntimeCommandResult] | None = None,
    ) -> None:
        self.broker = broker
        self.binding = binding
        self.controller = controller
        self._local_run = local_run or self._run_local

    def run(
        self, argv: Sequence[str], *, timeout_seconds: float
    ) -> RuntimeCommandResult:
        normalized = tuple(str(item) for item in argv)
        if Path(normalized[0]).name == "docker":
            result = self.broker.execute(
                normalized, binding=self.binding, timeout_seconds=timeout_seconds
            )
            stdout = result.stdout
            if result.returncode == 0 and result.action == "docker_container_inspect":
                stdout = _rehydrate_container_inspect_projection(
                    result.stdout,
                    controller=self.controller,
                )
            elif result.returncode == 0 and result.action == "docker_exec_attest":
                stdout = _rehydrate_runtime_attestation_projection(
                    result.stdout,
                    controller=self.controller,
                )
            return RuntimeCommandResult(
                argv=normalized,
                returncode=result.returncode,
                stdout=stdout,
                stderr=result.stderr,
            )
        if Path(normalized[0]).name != "ss":
            raise BrokerClientError(
                "runtime controller requested an unallowlisted local command"
            )
        return self._local_run(normalized, timeout_seconds)

    @staticmethod
    def _run_local(argv: Sequence[str], timeout_seconds: float) -> RuntimeCommandResult:
        completed = subprocess.run(
            tuple(argv),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout_seconds,
        )
        return RuntimeCommandResult(
            argv=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class BrokeredFaultCommandRunner:
    """Fault-driver runner with exact broker routing and no shell."""

    def __init__(
        self,
        *,
        broker: RootBrokerClient,
        binding: PublicRunBinding,
        controller_resolver: Callable[[Sequence[str]], DockerRuntimeController | None]
        | None = None,
        inspection_binding_resolver: Callable[[Sequence[str]], PublicRunBinding] | None = None,
        batch_canary: ProtectedCanary | None = None,
        canary_state_sha256: str | None = None,
    ) -> None:
        self.broker = broker
        self.binding = binding
        self.controller_resolver = controller_resolver
        self.inspection_binding_resolver = inspection_binding_resolver
        self.batch_canary = batch_canary
        self.canary_state_sha256 = canary_state_sha256

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> FaultCommandResult:
        normalized = tuple(str(item) for item in argv)
        canary = self.batch_canary
        if canary is not None and (
            len(normalized) == 5
            and Path(normalized[0]).name == "docker"
            and normalized[1:4] == ("inspect", "--type", "container")
            and normalized[4].lower() == canary.container_id
        ):
            result = self.broker.execute(
                ("docker", "inspect", "--type", "container", canary.name),
                binding=None,
                timeout_seconds=timeout_seconds,
                action="canary_inspect",
                parameters={"canary_name": canary.name},
            )
            observed_state = _canary_inspect_state_sha256(
                result.stdout,
                name=canary.name,
                container_id=canary.container_id,
            )
            if (
                self.canary_state_sha256 is None
                or observed_state != self.canary_state_sha256
            ):
                raise GateExecutionError("protected Docker canary state changed")
            return FaultCommandResult(
                argv=normalized,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        brokered = Path(normalized[0]).name == "docker" or normalized[0] in {
            "/bin/kill",
            "/bin/mount",
            "/bin/umount",
            "/bin/systemctl",
        }
        if brokered:
            binding = self.binding
            if (
                len(normalized) == 5
                and Path(normalized[0]).name == "docker"
                and normalized[1:4] == ("inspect", "--type", "container")
                and self.inspection_binding_resolver is not None
            ):
                binding = self.inspection_binding_resolver(normalized)
                if (
                    binding.run_id not in {self.binding.run_id, self.binding.peer_run_id}
                    or binding.cohort_sha256 != self.binding.cohort_sha256
                ):
                    raise BrokerClientError("fault inspection escaped its target/peer cohort")
            result = self.broker.execute(
                normalized, binding=binding, timeout_seconds=timeout_seconds
            )
            stdout = result.stdout
            if result.returncode == 0 and result.action == "docker_container_inspect":
                controller = (
                    self.controller_resolver(normalized)
                    if self.controller_resolver is not None
                    else None
                )
                if controller is None:
                    raise BrokerClientError(
                        "container inspect projection lacks a local controller"
                    )
                stdout = _rehydrate_container_inspect_projection(
                    result.stdout,
                    controller=controller,
                )
            return FaultCommandResult(
                argv=normalized,
                returncode=result.returncode,
                stdout=stdout,
                stderr=result.stderr,
            )
        if normalized[:3] != (
            str(Path(sys.executable).resolve()),
            "-I",
            "-c",
        ):
            raise BrokerClientError(
                "fault driver requested an unallowlisted local command"
            )
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
        return FaultCommandResult(
            argv=normalized,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class BrokerPrivilegedCommandExecutor:
    """The live-controller privilege seam, backed only by the root broker."""

    def __init__(
        self,
        resolver: Callable[
            [Sequence[str]], tuple[RootBrokerClient, PublicRunBinding | None]
        ],
    ) -> None:
        self._resolver = resolver

    def execute(
        self,
        logical_argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> PrivilegedCommandResult:
        argv = tuple(str(item) for item in logical_argv)
        broker, binding = self._resolver(argv)
        result = broker.execute(argv, binding=binding, timeout_seconds=timeout_seconds)
        return PrivilegedCommandResult(
            logical_argv=argv,
            returncode=result.returncode,
            stdout_sha256=result.stdout_sha256,
            stderr_sha256=result.stderr_sha256,
            executor_identity_sha256=result.policy_sha256,
            shell=False,
        )


@dataclass
class FaultSessionBinding:
    store: FaultSessionStore | None = None


AttemptHook = Callable[[str], None]
RuntimeControllerObserver = Callable[[str, DockerRuntimeController], None]


class BrokeredSupervisionService(SupervisionService):
    """Programmatic service with Docker and fault sessions injected in memory."""

    def __init__(
        self,
        *,
        broker_factory: Callable[[str], RootBrokerClient],
        gate_id: str,
        attempt_hook: AttemptHook,
        binding_factory: Callable[[Any], PublicRunBinding],
        runtime_controller_observer: RuntimeControllerObserver,
        fault_session: FaultSessionBinding,
        nonruntime_port_conflict_run_ids: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        self._host_broker_factory = broker_factory
        self._host_gate_id = gate_id
        self._host_attempt_hook = attempt_hook
        self._host_binding_factory = binding_factory
        self._host_runtime_controller_observer = runtime_controller_observer
        self._host_fault_session = fault_session
        self._host_nonruntime_port_conflict_run_ids = frozenset(
            str(run_id) for run_id in nonruntime_port_conflict_run_ids
        )
        super().__init__(**kwargs)

    def run_reserved(self, run_id: str) -> Any:
        self._host_attempt_hook(run_id)
        return super().run_reserved(run_id)

    def _runtime_controller(self, record: Any, run_dir: Path) -> Any:
        controller = super()._runtime_controller(record, run_dir)
        if not isinstance(controller, DockerRuntimeController):
            raise GateExecutionError(
                "live acceptance service did not construct a Docker controller"
            )
        contract = self._load_contract(record.run_id)
        binding = self._host_binding_factory(contract)
        broker = self._host_broker_factory(self._host_gate_id)
        runner = BrokeredRuntimeCommandRunner(
            broker=broker,
            binding=binding,
            controller=controller,
        )
        controller.runner = runner
        if controller.runner is not runner:
            raise GateExecutionError("Docker controller rejected its brokered runner")
        if record.run_id in self._host_nonruntime_port_conflict_run_ids:
            controller.configure_nonruntime_port_conflict_cleanup()
        runner_receipt = {
            "schema": "fortgym.m1b-brokered-runtime-runner/v1",
            "run_id": binding.run_id,
            "gate_id": self._host_gate_id,
            "attempt_id": binding.attempt_id,
            "attempt_identity_sha256": binding.attempt_identity_sha256,
            "contract_sha256": binding.contract_sha256,
            "nonce_sha256": binding.nonce_sha256,
            "cohort_sha256": binding.cohort_sha256,
            "broker_policy_sha256": broker._expected_policy_sha256,
            "broker_source_sha256": broker._expected_broker_source_sha256,
            "runner_type": type(runner).__name__,
        }
        runner_receipt_path = run_dir / "brokered-runtime-runner.json"
        if runner_receipt_path.exists():
            if _read_json_object(runner_receipt_path) != runner_receipt:
                raise GateExecutionError(
                    "durable brokered-runtime runner identity changed"
                )
        else:
            _write_once_json(runner_receipt_path, runner_receipt)
        self._host_runtime_controller_observer(record.run_id, controller)
        return controller


def public_binding(
    contract: Any,
    *,
    attempt_id: str,
    attempt_identity_sha256: str,
    peer_run_id: str | None = None,
    session_sha256: str | None = None,
) -> PublicRunBinding:
    return PublicRunBinding(
        attempt_id=attempt_id,
        attempt_identity_sha256=attempt_identity_sha256,
        run_id=str(contract.run_id),
        contract_sha256=str(contract.contract_sha256),
        nonce_sha256=_sha256_bytes(str(contract.nonce).encode("utf-8")),
        cohort_sha256=str(contract.cohort_digest),
        port=int(contract.port),
        peer_run_id=peer_run_id,
        session_sha256=session_sha256,
    )


def fault_session_manager_factory(
    session_binding: FaultSessionBinding,
    *,
    isolated_homes: bool = False,
) -> Callable[..., SupervisedRunManager]:
    """Inject the step-2 worker environment and pre-cleanup observer."""

    def factory(**kwargs: Any) -> SupervisedRunManager:
        store = session_binding.store
        if store is None and not isolated_homes:
            return SupervisedRunManager(**kwargs)
        contract_factory = kwargs["contract_factory"]

        def bound_contract_factory(
            record: Any, attempt_dir: Path, controller: Any
        ) -> Any:
            spec = contract_factory(record, attempt_dir, controller)
            additions = (
                dict(store.worker_environment(record.run_id))
                if store is not None
                else {}
            )
            if isolated_homes:
                home = attempt_dir / "home"
                temporary = attempt_dir / "tmp"
                home.mkdir(mode=0o700)
                temporary.mkdir(mode=0o700)
                additions.update({"HOME": str(home), "TMPDIR": str(temporary)})
                home_info = home.lstat()
                temporary_info = temporary.lstat()
                _write_once_json(
                    attempt_dir / "isolated-home.json",
                    {
                        "schema": "fortgym.m1b-isolated-harness-home/v1",
                        "run_id": record.run_id,
                        "home": str(home),
                        "home_device": home_info.st_dev,
                        "home_inode": home_info.st_ino,
                        "tmpdir": str(temporary),
                        "tmpdir_device": temporary_info.st_dev,
                        "tmpdir_inode": temporary_info.st_ino,
                    },
                )
            environment = dict(spec.env)
            environment.update(additions)
            allowlist = tuple(sorted(set(spec.env_allowlist).union(additions)))
            return dataclasses.replace(
                spec,
                env=environment,
                env_allowlist=allowlist,
            )

        kwargs["contract_factory"] = bound_contract_factory

        def observer_factory(
            record: Any,
            _run_dir: Path,
            _controller: Any,
            _spec: Any,
        ) -> Callable[[Mapping[str, Any]], Mapping[str, Any]] | None:
            participant = store.session.participant(record.run_id)
            if participant.role == "peer" and store.session.gate != "DAEMON-RESTART":
                return None
            return store.pre_cleanup_observer(record.run_id)

        if store is not None:
            kwargs["pre_cleanup_observer_factory"] = observer_factory
        return SupervisedRunManager(**kwargs)

    return factory


@dataclass
class GateResources:
    run_ids: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    process_group_ids: list[int] = field(default_factory=list)
    mount_paths: list[Path] = field(default_factory=list)
    retained_evidence_paths: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class VerifiedGateReceipt:
    path: Path
    criteria_passed: tuple[str, ...]


@dataclass
class ForeignCanaryState:
    name: str
    container_id: str
    process: subprocess.Popen[bytes]
    workspace: Path
    identity: ProtectedCanary
    process_start_ticks: int
    workspace_device: int
    workspace_inode: int
    container_state_sha256: str
    creation_broker_evidence: Path


@dataclass
class _FaultSessionFailureGuard:
    """Fail closed and unblock held supervisors when coordination raises.

    The session release and completion files are write-once decisions. Track
    successful releases locally so unwinding never tries to overwrite one
    with an abort. This context must be entered *after* the executor so its
    ``__exit__`` runs first and releases held workers before the executor joins.
    """

    store: FaultSessionStore
    service: SupervisionService
    run_ids: tuple[str, ...]
    evidence_path: Path
    enospc_target_run_id: str | None = None
    released_run_ids: set[str] = field(default_factory=set)
    completion_persisted: bool = False

    def __enter__(self) -> Self:
        return self

    def note_release(self, run_id: str) -> None:
        if run_id not in self.run_ids:
            raise GateExecutionError("fault-session release run is not bound")
        self.released_run_ids.add(run_id)

    def note_completion(self) -> None:
        self.completion_persisted = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            return False
        actions: dict[str, Any] = {
            "participant_decisions": {},
            "completion": "already_persisted",
            "enospc_authorization_discarded": False,
        }
        for run_id in self.run_ids:
            if run_id in self.released_run_ids:
                actions["participant_decisions"][run_id] = "release_already_requested"
                continue
            try:
                self.store.abort(run_id, reason_code="host_gate_failed")
            except Exception as unwind_error:  # noqa: BLE001 - preserve root cause
                actions["participant_decisions"][run_id] = {
                    "abort_error_type": type(unwind_error).__name__,
                }
            else:
                actions["participant_decisions"][run_id] = "abort_requested"
        if not self.completion_persisted:
            try:
                self.store.abort_completion(reason_code="host_gate_failed")
            except Exception as unwind_error:  # noqa: BLE001 - preserve root cause
                actions["completion"] = {
                    "abort_error_type": type(unwind_error).__name__,
                }
            else:
                actions["completion"] = "abort_requested"
        if self.enospc_target_run_id is not None:
            try:
                self.service._discard_enospc_fault_authorization(
                    self.enospc_target_run_id
                )
            except Exception as unwind_error:  # noqa: BLE001 - preserve root cause
                actions["enospc_authorization_discard_error_type"] = type(
                    unwind_error
                ).__name__
            else:
                actions["enospc_authorization_discarded"] = True
        try:
            _write_once_json(
                self.evidence_path,
                {
                    "schema": "fortgym.m1b-fault-session-unwind/v1",
                    "ok": False,
                    "error_type": exc_type.__name__,
                    "actions": actions,
                },
            )
        except (OSError, TypeError, ValueError):
            # The original gate exception remains authoritative; the generic
            # gate-failure receipt still makes an unwind-receipt failure fatal.
            return False
        return False


@dataclass(frozen=True)
class _PausedHarness:
    run_id: str
    harness_pid: int
    binding: PublicRunBinding
    resume_action: str


@dataclass
class _PausedHarnessUnwindGuard:
    """Bound every paused harness to retryable resume or authenticated abort."""

    broker: RootBrokerClient
    registry: Any
    gate_id: str
    evidence_path: Path
    futures: Mapping[str, Any]
    join_timeout_seconds: float = 120.0
    paused: dict[str, _PausedHarness] = field(default_factory=dict)
    entries: dict[str, _PausedHarness] = field(default_factory=dict)

    def __enter__(self) -> Self:
        return self

    def note_pause(
        self,
        *,
        run_id: str,
        harness_pid: int,
        binding: PublicRunBinding,
        resume_action: str,
    ) -> None:
        if run_id in self.entries or binding.run_id != run_id:
            raise GateExecutionError("paused harness binding is contradictory")
        entry = _PausedHarness(
            run_id=run_id,
            harness_pid=harness_pid,
            binding=binding,
            resume_action=resume_action,
        )
        self.entries[run_id] = entry
        self.paused[run_id] = entry

    def resume(self, run_id: str) -> BrokerReceipt:
        entry = self.paused.get(run_id)
        if entry is None:
            raise GateExecutionError("paused harness is not registered")
        errors: list[str] = []
        for _attempt in range(3):
            try:
                receipt = self.broker.execute(
                    ("/bin/kill", "-CONT", "--", str(entry.harness_pid)),
                    binding=entry.binding,
                    timeout_seconds=10.0,
                    action=entry.resume_action,
                    parameters={},
                )
            except Exception as exc:  # noqa: BLE001 - bounded retry below
                errors.append(type(exc).__name__)
                continue
            if receipt.returncode == 0:
                del self.paused[run_id]
                return receipt
            errors.append(f"returncode_{receipt.returncode}")
        raise GateExecutionError(
            "paused harness resume failed after bounded retries: " + ",".join(errors)
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        if exc_type is None and not self.paused:
            return False
        missing_resume = exc_type is None
        evidence_error_type = exc_type or GateExecutionError
        actions: dict[str, Any] = {}
        aborted_run_ids: set[str] = set()
        for run_id in tuple(self.paused):
            entry = self.paused.get(run_id)
            if entry is None:
                continue
            try:
                resumed = self.resume(run_id)
            except Exception as resume_error:  # noqa: BLE001 - force exact abort
                action: dict[str, Any] = {
                    "resume": f"failed_{type(resume_error).__name__}",
                }
                try:
                    aborted = self.broker.execute(
                        ("/bin/kill", "-KILL", "--", str(entry.harness_pid)),
                        binding=entry.binding,
                        timeout_seconds=10.0,
                        action="abort_paused_harness",
                        parameters={},
                    )
                except Exception as abort_error:  # noqa: BLE001 - preserve root cause
                    action["abort"] = f"failed_{type(abort_error).__name__}"
                else:
                    action["abort"] = (
                        "requested" if aborted.returncode == 0 else "nonzero"
                    )
                    if aborted.returncode == 0:
                        self.paused.pop(run_id, None)
                        aborted_run_ids.add(run_id)
                actions[run_id] = action
            else:
                actions[run_id] = {
                    "resume": "requested",
                    "resume_receipt_sha256": _sha256_file(resumed.evidence_path),
                    "abort": "not_needed",
                }
        # A cohort can fail before every manager reaches owned/paused evidence.
        # Stop every submitted run, not only entries which were already paused,
        # so an early peer failure cannot strand the rest of the cohort.
        for run_id in dict.fromkeys((*self.entries, *self.futures)):
            try:
                self.registry.request_stop(run_id)
            except Exception as stop_error:  # noqa: BLE001 - preserve root cause
                actions.setdefault(run_id, {})["registry_stop"] = (
                    f"failed_{type(stop_error).__name__}"
                )
            else:
                actions.setdefault(run_id, {})["registry_stop"] = "requested"
        for run_id, future in self.futures.items():
            if future.done():
                actions.setdefault(run_id, {})["join"] = "already_done"
                continue
            try:
                future.result(timeout=self.join_timeout_seconds)
            except Exception as join_error:  # noqa: BLE001 - bounded unwind evidence
                actions.setdefault(run_id, {})["join"] = (
                    f"bounded_{type(join_error).__name__}"
                )
                entry = self.entries.get(run_id)
                if entry is not None and run_id not in aborted_run_ids:
                    try:
                        aborted = self.broker.execute(
                            ("/bin/kill", "-KILL", "--", str(entry.harness_pid)),
                            binding=entry.binding,
                            timeout_seconds=10.0,
                            action="abort_paused_harness",
                            parameters={},
                        )
                    except Exception as abort_error:  # noqa: BLE001
                        actions.setdefault(run_id, {})["bounded_join_abort"] = (
                            f"failed_{type(abort_error).__name__}"
                        )
                    else:
                        actions.setdefault(run_id, {})["bounded_join_abort"] = (
                            "requested" if aborted.returncode == 0 else "nonzero"
                        )
                        if aborted.returncode == 0:
                            self.paused.pop(run_id, None)
                            aborted_run_ids.add(run_id)
            else:
                actions.setdefault(run_id, {})["join"] = "completed"
        try:
            _write_once_json(
                self.evidence_path,
                {
                    "schema": "fortgym.m1b-paused-harness-unwind/v1",
                    "ok": not self.paused,
                    "gate_id": self.gate_id,
                    "error_type": evidence_error_type.__name__,
                    "remaining_paused_run_ids": sorted(self.paused),
                    "actions": actions,
                },
            )
        except (OSError, TypeError, ValueError):
            pass
        if missing_resume:
            raise GateExecutionError("gate completed with a paused harness")
        return False


def _process_start_ticks(pid: int) -> int:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        raise GateExecutionError("process identity PID is invalid")
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError as exc:
        raise GateExecutionError("process identity stat is unreadable") from exc
    closing = value.rfind(")")
    if closing < 2 or closing + 2 >= len(value):
        raise GateExecutionError("process identity stat is malformed")
    fields = value[closing + 2 :].split()
    if len(fields) <= 19 or not fields[19].isdigit():
        raise GateExecutionError("process identity start ticks are malformed")
    start_ticks = int(fields[19])
    if start_ticks <= 0:
        raise GateExecutionError("process identity start ticks are invalid")
    return start_ticks


@dataclass
class _OrphanChildUnwindGuard:
    """Bound a forked manager child to exact kill, reap, and reconciliation."""

    broker: RootBrokerClient
    binding: PublicRunBinding
    service: SupervisionService
    run_id: str
    gate_id: str
    evidence_path: Path
    wait_timeout_seconds: float = 10.0
    waitpid: Callable[[int, int], tuple[int, int]] = os.waitpid
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    start_ticks_probe: Callable[[int], int] = _process_start_ticks
    child_pid: int | None = None
    child_start_ticks: int | None = None
    owned_supervisor_pid: int | None = None
    identity_bound: bool = False
    reconciliation: Mapping[str, Any] | None = None
    completed: bool = False

    def __enter__(self) -> Self:
        return self

    def note_child(self, pid: int) -> None:
        if self.child_pid is not None:
            raise GateExecutionError("orphan child identity was already recorded")
        self.child_pid = pid
        self.child_start_ticks = self.start_ticks_probe(pid)

    def bind_owned(self, owned: OwnedRun) -> None:
        if self.child_pid is None or self.child_start_ticks is None:
            raise GateExecutionError("orphan child identity is not initialized")
        if owned.run_id != self.run_id or owned.supervisor_pid != self.child_pid:
            raise GateExecutionError("orphan ownership supervisor PID differs")
        if self.start_ticks_probe(self.child_pid) != self.child_start_ticks:
            raise GateExecutionError("orphan ownership process start time differs")
        self.owned_supervisor_pid = owned.supervisor_pid
        self.identity_bound = True

    def _bounded_wait(self) -> dict[str, Any]:
        pid = self.child_pid
        result: dict[str, Any] = {
            "timeout_seconds": self.wait_timeout_seconds,
            "wnohang_only": True,
            "calls": 0,
            "outcome": "child_not_recorded",
            "waited_pid": None,
            "raw_status": None,
            "exit_code": None,
            "signal": None,
        }
        if pid is None:
            return result
        deadline = self.monotonic() + self.wait_timeout_seconds
        while True:
            try:
                waited_pid, raw_status = self.waitpid(pid, os.WNOHANG)
            except InterruptedError:
                continue
            except ChildProcessError:
                result["outcome"] = "already_reaped_without_status"
                return result
            result["calls"] = int(result["calls"]) + 1
            if waited_pid == pid:
                result["waited_pid"] = waited_pid
                result["raw_status"] = raw_status
                if os.WIFSIGNALED(raw_status):
                    result["outcome"] = "signaled"
                    result["signal"] = os.WTERMSIG(raw_status)
                elif os.WIFEXITED(raw_status):
                    result["outcome"] = "exited"
                    result["exit_code"] = os.WEXITSTATUS(raw_status)
                else:
                    result["outcome"] = "unexpected_status"
                return result
            if waited_pid != 0:
                result["outcome"] = "different_pid"
                result["waited_pid"] = waited_pid
                result["raw_status"] = raw_status
                return result
            if self.monotonic() >= deadline:
                result["outcome"] = "timeout"
                return result
            self.sleep(0.05)

    def _finish(self, *, trigger_error_type: str | None) -> bool:
        if self.completed:
            raise GateExecutionError("orphan child unwind ran more than once")
        self.completed = True
        identity_current = False
        if (
            self.identity_bound
            and self.child_pid is not None
            and self.child_start_ticks is not None
        ):
            try:
                identity_current = (
                    self.start_ticks_probe(self.child_pid) == self.child_start_ticks
                )
            except GateExecutionError:
                identity_current = False

        broker_evidence: dict[str, Any] = {
            "attempted": False,
            "action": "signal_supervisor",
            "returncode": None,
            "receipt_sha256": None,
            "error_type": None,
            "registry_stop_error_type": None,
        }
        if identity_current and self.child_pid is not None:
            broker_evidence["attempted"] = True
            try:
                killed = self.broker.execute(
                    ("/bin/kill", "-KILL", "--", str(self.child_pid)),
                    binding=self.binding,
                    timeout_seconds=10.0,
                    action="signal_supervisor",
                    parameters={
                        "supervisor_start_ticks": self.child_start_ticks,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - persist typed unwind failure
                broker_evidence["error_type"] = type(exc).__name__
            else:
                broker_evidence["returncode"] = killed.returncode
                broker_evidence["receipt_sha256"] = _sha256_file(killed.evidence_path)

        kill_ok = (
            broker_evidence["attempted"] is True and broker_evidence["returncode"] == 0
        )
        if not kill_ok:
            try:
                self.service.registry.request_stop(self.run_id)
            except Exception as exc:  # noqa: BLE001 - reconciliation remains mandatory
                broker_evidence["registry_stop_error_type"] = type(exc).__name__
        wait_evidence = self._bounded_wait()

        reconciliation_evidence: dict[str, Any] = {
            "attempted": True,
            "run_present": False,
            "error_type": None,
        }
        try:
            reconciliation = self.service.reconcile_all()
        except Exception as exc:  # noqa: BLE001 - persist typed unwind failure
            reconciliation_evidence["error_type"] = type(exc).__name__
            reconciliation = None
        else:
            if not isinstance(reconciliation, Mapping):
                reconciliation_evidence["error_type"] = "InvalidMapping"
            else:
                self.reconciliation = reconciliation
                reconciliation_evidence["run_present"] = self.run_id in reconciliation

        ok = bool(
            self.identity_bound
            and identity_current
            and kill_ok
            and wait_evidence["outcome"] == "signaled"
            and wait_evidence["signal"] == signal.SIGKILL
            and reconciliation_evidence["run_present"] is True
            and reconciliation_evidence["error_type"] is None
        )
        payload = {
            "schema": "fortgym.m1b-orphan-child-unwind/v1",
            "ok": ok,
            "gate_id": self.gate_id,
            "run_id": self.run_id,
            "trigger_error_type": trigger_error_type,
            "child": {
                "pid": self.child_pid,
                "start_ticks": self.child_start_ticks,
                "owned_supervisor_pid": self.owned_supervisor_pid,
                "identity_bound": self.identity_bound,
                "identity_current": identity_current,
            },
            "broker_kill": broker_evidence,
            "wait": wait_evidence,
            "reconciliation": reconciliation_evidence,
        }
        _write_once_json(self.evidence_path, payload)
        return ok

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        try:
            ok = self._finish(
                trigger_error_type=exc_type.__name__ if exc_type is not None else None
            )
        except Exception:
            if exc_type is None:
                raise
            return False
        if exc_type is None and not ok:
            raise GateExecutionError("orphan child unwind did not complete exactly")
        return False


class GateBackend(Protocol):
    def execute(self, context: GateExecutionContext) -> GateExecutionResult: ...

    def cleanup(self, context: CleanupPassContext) -> CleanupPassResult: ...


class LinuxM1BHostAdapter:
    """Narrow controller adapter; concrete work lives in ``LinuxGateBackend``."""

    def __init__(self, backend: GateBackend, *, two_fort_diagnostic: bool = False) -> None:
        if not isinstance(two_fort_diagnostic, bool):
            raise TypeError("two_fort_diagnostic must be a literal boolean")
        self.backend = backend
        self.two_fort_diagnostic = two_fort_diagnostic

    def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
        if (
            context.acceptance_sha256 != FROZEN_ACCEPTANCE_SHA256
            or context.plan_sha256 != FROZEN_PLAN_SHA256
            or context.gate_id not in _GATE_IDS
        ):
            raise GateExecutionError("live gate context is not frozen")
        if self.two_fort_diagnostic and context.gate_id != "DF-KILL":
            # Preserve the frozen ledger order and cleanup passes. This is an
            # explicit incomplete matrix, never synthetic credit for omitted
            # work, and no permit is started for a non-selected live gate.
            path = context.evidence_root / "gates" / context.gate_id / "not-selected.json"
            _write_once_json(path, {
                "schema": "fortgym.m1b-diagnostic-selection/v1",
                "mode": "two-fort-diagnostic", "selected_gate": "DF-KILL",
                "gate_id": context.gate_id, "runtime_attempts_started": 0,
                "m1b_acceptance_credit": False,
            })
            return GateExecutionResult(
                gate_id=context.gate_id, criteria_passed=(), evidence_paths=(path,),
                failure_code="diagnostic_not_selected",
            )
        return self.backend.execute(context)

    def cleanup_pass(self, context: CleanupPassContext) -> CleanupPassResult:
        if (
            context.acceptance_sha256 != FROZEN_ACCEPTANCE_SHA256
            or context.plan_sha256 != FROZEN_PLAN_SHA256
            or context.pass_index not in {1, 2}
        ):
            raise GateExecutionError("cleanup context is not frozen")
        return self.backend.cleanup(context)


T = TypeVar("T")


def _wait_until(
    loader: Callable[[], T | None],
    *,
    timeout_seconds: float,
    label: str,
) -> T:
    deadline = time.monotonic() + timeout_seconds
    while True:
        value = loader()
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            raise GateExecutionError(f"timed out waiting for {label}")
        time.sleep(0.05)


def _fault_ready_while_running(
    store: FaultSessionStore, run_id: str, run_futures: Mapping[str, Any]
) -> Any:
    for participant_id, future in run_futures.items():
        if future.done():
            # Propagate worker exceptions; a normal terminal return also means
            # this cohort can no longer reach the live fault barrier.
            future.result()
            raise GateExecutionError(
                f"fault participant {participant_id} terminated before the step-2 barrier"
            )
    return store.ready(run_id)


def _result_summary(result: Any) -> dict[str, Any]:
    return {
        "status": str(getattr(result, "status", "unknown")),
        "reason": _safe_json(getattr(result, "reason", None)),
        "attempt_dir": str(getattr(result, "attempt_dir", "")),
    }


def _terminal_proof(result: Any) -> dict[str, Any]:
    control_dir = Path(getattr(result, "control_dir", ""))
    if (
        getattr(result, "finalized", None) is not True
        or getattr(result, "action", None) not in {"finalized", "already_terminal"}
        or not control_dir.is_absolute()
    ):
        raise GateExecutionError("managed result is not durably finalized")
    manager_terminal_path = control_dir / "manager-terminal.json"
    manager_terminal = _read_json_object(manager_terminal_path)
    reason = manager_terminal.get("reason")
    supervision = manager_terminal.get("supervision")
    cleanup = supervision.get("cleanup") if isinstance(supervision, Mapping) else None
    stages = cleanup.get("stages") if isinstance(cleanup, Mapping) else None
    if (
        manager_terminal.get("schema") != "fortgym.supervised-manager-terminal/v1"
        or manager_terminal.get("run_id") != getattr(result, "run_id", None)
        or manager_terminal.get("status") != getattr(result, "status", None)
        or not isinstance(reason, Mapping)
        or reason.get("code")
        != (
            result.reason.get("code")
            if isinstance(getattr(result, "reason", None), Mapping)
            else None
        )
        or not isinstance(cleanup, Mapping)
        or cleanup.get("ok") is not True
        or not isinstance(stages, list)
        or not stages
        or any(
            not isinstance(stage, Mapping) or stage.get("ok") is not True
            for stage in stages
        )
    ):
        raise GateExecutionError("manager terminal or cleanup proof differs")
    manager_events = tuple(
        str(row.get("event"))
        for row in _read_jsonl_objects(control_dir / "manager-journal.jsonl")
    )
    attempt_dir = control_dir / "attempts" / "attempt-0001"
    try:
        terminal_chain = validate_terminal_chain(
            attempt_dir,
            supervision,
            run_id=result.run_id,
            require_cleanup_success=True,
        )
    except (OSError, SupervisorError) as exc:
        raise GateExecutionError("managed result terminal chain is incomplete") from exc
    attempt_events = tuple(
        str(row.get("event"))
        for row in _read_jsonl_objects(attempt_dir / "attempt-journal.jsonl")
    )
    if (
        manager_events.count("cleanup_completion_recorded") != 1
        or manager_events.count("registry_terminal_recorded") != 1
        or manager_events.index("cleanup_completion_recorded")
        > manager_events.index("registry_terminal_recorded")
        or attempt_events.count("cleanup_recorded") != 1
        or attempt_events.count("terminal_pending") != 1
        or attempt_events.index("cleanup_recorded")
        > attempt_events.index("terminal_pending")
    ):
        raise GateExecutionError("cleanup-to-terminal durable order differs")
    return {
        "run_id": result.run_id,
        "status": result.status,
        "reason_code": reason.get("code"),
        "recovered": bool(getattr(result, "recovered", False)),
        "action": result.action,
        "cleanup": _safe_json(cleanup),
        "manager_terminal_sha256": _sha256_file(manager_terminal_path),
        "manager_journal_sha256": _sha256_file(control_dir / "manager-journal.jsonl"),
        "attempt_journal_sha256": _sha256_file(attempt_dir / "attempt-journal.jsonl"),
        "terminal_chain": _safe_json(terminal_chain),
    }


def _port2_conflict_terminal_proof(result: Any) -> dict[str, Any]:
    """Require the planned non-runtime contender's exact durable terminal proof."""

    proof = _terminal_proof(result)
    if (
        getattr(result, "status", None) != "failed"
        or proof.get("reason_code") != "port_lease_busy"
    ):
        raise GateExecutionError("PORT-2 contender terminal proof differs")
    return proof


def _cleanup_elapsed_seconds(result: Any) -> float:
    attempt_dir = Path(getattr(result, "control_dir", "")) / "attempts" / "attempt-0001"
    rows = _read_jsonl_objects(attempt_dir / "attempt-journal.jsonl")
    starts = [row for row in rows if row.get("event") == "cleanup_started"]
    terminals = [row for row in rows if row.get("event") == "terminal_pending"]
    if len(starts) != 1 or len(terminals) != 1:
        raise GateExecutionError("cleanup timing events are not unique")
    start_ns = starts[0].get("monotonic_ns")
    terminal_ns = terminals[0].get("monotonic_ns")
    if (
        isinstance(start_ns, bool)
        or not isinstance(start_ns, int)
        or isinstance(terminal_ns, bool)
        or not isinstance(terminal_ns, int)
        or terminal_ns < start_ns
    ):
        raise GateExecutionError("cleanup timing evidence is invalid")
    return (terminal_ns - start_ns) / 1_000_000_000


def _bounded_cross_run_artifact_scan(
    artifact_roots: Mapping[str, Path],
) -> tuple[int, Mapping[str, Any]]:
    """Scan only gameplay outputs, with explicit file and byte bounds."""

    allowed_names = frozenset({"trace.jsonl", "child.stdout.log", "child.stderr.log"})
    total_bytes = 0
    files = 0
    references: list[dict[str, str]] = []
    digests: dict[str, str] = {}
    for owner_run_id, root in sorted(artifact_roots.items()):
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise GateExecutionError("CO-8 artifact root is not a directory")
        candidates = sorted(
            path for path in resolved_root.rglob("*") if path.name in allowed_names
        )
        if not candidates:
            raise GateExecutionError("CO-8 gameplay artifact set is empty")
        for path in candidates:
            metadata = path.lstat()
            resolved = path.resolve(strict=True)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or not resolved.is_relative_to(resolved_root)
                or metadata.st_size > 16 * 1024 * 1024
            ):
                raise GateExecutionError(
                    "CO-8 gameplay artifact is unsafe or oversized"
                )
            files += 1
            total_bytes += metadata.st_size
            if files > 64 or total_bytes > 64 * 1024 * 1024:
                raise GateExecutionError(
                    "CO-8 gameplay artifact scan exceeds its bound"
                )
            payload = path.read_bytes()
            relative = f"{owner_run_id}/{resolved.relative_to(resolved_root)}"
            digests[relative] = _sha256_bytes(payload)
            for foreign_run_id in artifact_roots:
                if (
                    foreign_run_id != owner_run_id
                    and foreign_run_id.encode() in payload
                ):
                    references.append(
                        {
                            "owner_run_id": owner_run_id,
                            "foreign_run_id": foreign_run_id,
                            "path": relative,
                        }
                    )
    return len(references), {
        "files_scanned": files,
        "bytes_scanned": total_bytes,
        "allowed_names": sorted(allowed_names),
        "file_sha256": digests,
        "references": references,
    }


def _canary_inspect_state_sha256(
    stdout: str,
    *,
    name: str,
    container_id: str,
) -> str:
    """Validate and hash the complete semantic state of the inert canary."""

    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GateExecutionError(
            "foreign Docker canary inspect is invalid JSON"
        ) from exc
    if (
        not isinstance(document, list)
        or len(document) != 1
        or not isinstance(document[0], Mapping)
    ):
        raise GateExecutionError("foreign Docker canary inspect cardinality differs")
    inspected = document[0]
    state = inspected.get("State")
    config = inspected.get("Config")
    host = inspected.get("HostConfig")
    restart = host.get("RestartPolicy") if isinstance(host, Mapping) else None
    security_opt = host.get("SecurityOpt") if isinstance(host, Mapping) else None
    if (
        str(inspected.get("Id") or "").lower() != container_id
        or inspected.get("Name") != f"/{name}"
        or inspected.get("Image")
        != "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
        or not isinstance(state, Mapping)
        or state.get("Status") != "created"
        or state.get("Running") is not False
        or state.get("Dead") is not False
        or state.get("Restarting") is not False
        or not isinstance(config, Mapping)
        or config.get("Image")
        != "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
        or config.get("Entrypoint") != ["/bin/sleep"]
        or config.get("Cmd") != ["28800"]
        or not isinstance(host, Mapping)
        or host.get("NetworkMode") != "none"
        or host.get("Memory") != 134_217_728
        or host.get("MemorySwap") != 134_217_728
        or host.get("PidsLimit") != 16
        or host.get("CapDrop") != ["ALL"]
        or not isinstance(security_opt, list)
        or len(security_opt) != 1
        or security_opt[0] not in {"no-new-privileges", "no-new-privileges:true"}
        or not isinstance(restart, Mapping)
        or dict(restart) != {"Name": "no", "MaximumRetryCount": 0}
        or inspected.get("RestartCount") != 0
    ):
        raise GateExecutionError("foreign Docker canary semantic state differs")
    return _sha256_bytes(_canonical_bytes(inspected))


def _validate_canary_absence_receipt(
    receipt: BrokerReceipt,
    *,
    name: str,
) -> None:
    expected = (
        "docker",
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        f"name=^/{name}$",
        "--format",
        "{{.ID}}",
    )
    if (
        receipt.action != "canary_absence"
        or receipt.logical_argv != expected
        or receipt.ok is not True
        or receipt.returncode != 0
        or receipt.stdout != ""
        or receipt.stderr != ""
        or receipt.stdout_sha256 != _sha256_bytes(b"")
        or receipt.stderr_sha256 != _sha256_bytes(b"")
    ):
        raise GateExecutionError("foreign Docker canary exact absence listing failed")


class LinuxGateBackend:
    """Concrete programmatic implementations of the fifteen substantive gates."""

    def __init__(self, *, paths: HostPaths) -> None:
        self.paths = paths
        self.registry = RunRegistry(
            db_path=paths.db_path,
            artifacts_root=paths.artifacts_root,
        )
        self.resources: dict[str, GateResources] = {
            gate.gate_id: GateResources()
            for gate in FROZEN_GATE_PLAN
            if not gate.derived
        }
        self._permit_by_run: dict[str, Any] = {}
        self._attempt_identity_by_run: dict[str, str] = {}
        self._permit_lock = threading.Lock()
        self._broker_cache: dict[str, RootBrokerClient] = {}
        self._bindings: dict[str, PublicRunBinding] = {}
        self._runtime_controllers: dict[str, DockerRuntimeController] = {}
        self._run_futures: dict[str, Any] = {}
        self._run_sessions: dict[str, str] = {}
        self._canary: ForeignCanaryState | None = None
        self._active_gate: str | None = None
        self._failure_stage: str | None = None

    def broker(self, gate_id: str) -> RootBrokerClient:
        broker = self._broker_cache.get(gate_id)
        if broker is None:
            broker = RootBrokerClient(paths=self.paths, gate_id=gate_id)
            self._broker_cache[gate_id] = broker
        return broker

    def execute(self, context: GateExecutionContext) -> GateExecutionResult:
        self._active_gate = context.gate_id
        self._failure_stage = "gate_dispatch"
        try:
            method = getattr(self, f"_gate_{context.gate_id.lower().replace('-', '_')}")
            receipt = method(context)
            if not isinstance(receipt, VerifiedGateReceipt):
                raise GateExecutionError(
                    "gate did not return verified criterion evidence"
                )
            result = GateExecutionResult(
                gate_id=context.gate_id,
                criteria_passed=receipt.criteria_passed,
                evidence_paths=(receipt.path,),
                failure_code=(
                    None
                    if receipt.criteria_passed == context.required_criteria
                    else "gate_criteria_unproved"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - seal a typed gate failure
            failure = self._gate_path(context.gate_id, "gate-failure.json")
            if not failure.exists():
                _write_once_json(
                    failure,
                    {
                        "schema": "fortgym.m1b-host-gate-failure/v1",
                        "gate_id": context.gate_id,
                        "error_type": type(exc).__name__,
                        "stage": self._failure_stage,
                    },
                )
            # Keep this separate from any gate-specific failure receipt already
            # written during unwinding. Neither receipt is overwritten.
            exception_path = self._gate_path(context.gate_id, "exception.json")
            _write_once_json(
                exception_path,
                {
                    "schema": "fortgym.m1b-gate-exception/v1",
                    "gate_id": context.gate_id,
                    "stage": self._failure_stage,
                    **describe_exception(exc),
                },
            )
            result = GateExecutionResult(
                gate_id=context.gate_id,
                criteria_passed=(),
                evidence_paths=(failure, exception_path),
                failure_code=f"host_{type(exc).__name__.lower()}"[:128],
            )
        finally:
            self._active_gate = None
            self._failure_stage = None
        diagnostics, capture_ok = self._capture_diagnostics(
            context.gate_id, "gate-return", self.resources[context.gate_id].run_ids
        )
        return dataclasses.replace(
            result,
            evidence_paths=(*result.evidence_paths, *diagnostics),
            criteria_passed=result.criteria_passed if capture_ok else (),
            failure_code=result.failure_code or (
                None if capture_ok else "diagnostic_capture_incomplete"
            ),
        )

    def _capture_diagnostics(
        self, gate_id: str, phase: str, run_ids: Sequence[str]
    ) -> tuple[tuple[Path, ...], bool]:
        paths: list[Path] = []
        complete = True
        for run_id in sorted(set(run_ids)):
            path = self._gate_path(gate_id, f"diagnostics/{phase}/{run_id}.json")
            payload: dict[str, Any] = {
                "schema": "fortgym.m1b-run-diagnostics/v1", "run_id": run_id,
            }
            try:
                payload.update(capture_run_diagnostics(
                    control_root=self.paths.service_control_root,
                    artifacts_root=self.paths.artifacts_root,
                    run_id=run_id,
                    session_sha256=self._run_sessions.get(run_id),
                ))
                record = self.registry.get(run_id)
                payload["registry"] = None if record is None else {
                    "status": record.status, "step": record.step,
                }
                future = self._run_futures.get(run_id)
                if future is not None:
                    payload["worker_future"] = {
                        "done": future.done(), "cancelled": future.cancelled(),
                    }
                    if future.done() and not future.cancelled():
                        error = future.exception()
                        if error is not None:
                            payload["worker_future"]["exception"] = describe_exception(error)
            except Exception as exc:  # noqa: BLE001 - preserve export failure too
                payload.update(capture_ok=False, exception=describe_exception(exc))
            _write_once_json(path, payload)
            paths.append(path)
            complete = complete and payload["capture_ok"] is True
        return tuple(paths), complete

    def cleanup(self, context: CleanupPassContext) -> CleanupPassResult:
        gate_ids = (
            [context.gate_id]
            if context.scope == "gate" and context.gate_id is not None
            else list(self.resources)
        )
        selected = [self.resources[gate_id] for gate_id in gate_ids]
        canary_gate = context.gate_id if context.gate_id is not None else "CLEANUP"
        canary_receipt = self.paths.evidence_root / "batch-canary-created.json"
        if not self._canary_alive(canary_gate):
            path = self._cleanup_path(context)
            if not path.exists():
                _write_once_json(
                    path,
                    {
                        "schema": "fortgym.m1b-canary-residue-failure/v1",
                        "ok": False,
                        "scope": context.scope,
                        "gate_id": context.gate_id,
                        "pass_index": context.pass_index,
                    },
                )
            return CleanupPassResult(
                scope=context.scope,
                gate_id=context.gate_id,
                pass_index=context.pass_index,
                criteria_passed=(),
                evidence_paths=(path, canary_receipt),
                failure_code="foreign_canary_changed",
            )
        run_ids = [run_id for item in selected for run_id in item.run_ids]
        if not run_ids:
            # ResidueExpectation requires a non-empty exact set. A local-only
            # gate has no live resources, so record an explicit empty audit.
            path = self._cleanup_path(context)
            _write_once_json(
                path,
                {
                    "schema": "fortgym.m1b-empty-residue-audit/v1",
                    "ok": True,
                    "scope": context.scope,
                    "gate_id": context.gate_id,
                    "pass_index": context.pass_index,
                    "run_ids": [],
                    "foreign_canary_untouched": True,
                },
            )
            return CleanupPassResult(
                scope=context.scope,
                gate_id=context.gate_id,
                pass_index=context.pass_index,
                criteria_passed=_CLEANUP_CRITERIA,
                evidence_paths=(path, canary_receipt),
            )
        reports = self._audit_selected_resources(
            gate_id=canary_gate,
            selected=selected,
        )
        ok = all(report["ok"] is True for report in reports)
        diagnostic_paths: tuple[Path, ...] = ()
        capture_ok = True
        if context.scope == "batch" and context.pass_index == 2:
            diagnostic_paths, capture_ok = self._capture_diagnostics(
                "CLEANUP", "final-cleanup", run_ids
            )
            ok = ok and capture_ok
        path = self._cleanup_path(context)
        _write_once_json(
            path,
            {
                "schema": "fortgym.m1b-partitioned-residue-audit/v1",
                "ok": ok,
                "scope": context.scope,
                "gate_id": context.gate_id,
                "pass_index": context.pass_index,
                "reports": reports,
                "diagnostic_capture_ok": capture_ok,
            },
        )
        return CleanupPassResult(
            scope=context.scope,
            gate_id=context.gate_id,
            pass_index=context.pass_index,
            criteria_passed=_CLEANUP_CRITERIA if ok else (),
            evidence_paths=(path, canary_receipt, *diagnostic_paths),
            failure_code=(
                "diagnostic_capture_incomplete" if not capture_ok
                else None if ok else "residue_audit_failed"
            ),
        )

    def _audit_selected_resources(
        self,
        *,
        gate_id: str,
        selected: Sequence[GateResources],
    ) -> list[dict[str, Any]]:
        """Audit each run/port pair separately so reused ports remain provable."""

        pairs = [
            (run_id, port)
            for resources in selected
            for run_id, port in zip(resources.run_ids, resources.ports, strict=True)
        ]
        if not pairs:
            return []
        if len({run_id for run_id, _port in pairs}) != len(pairs):
            raise GateExecutionError("residue audit run identities are duplicated")
        canary = self._canary
        if canary is None:
            raise GateExecutionError("residue audit lacks the batch canary")
        process_groups = tuple(
            pid for resources in selected for pid in resources.process_group_ids
        )
        mounts = tuple(path for resources in selected for path in resources.mount_paths)
        retained = tuple(
            path for resources in selected for path in resources.retained_evidence_paths
        )
        auditor = BatchResidueAuditor(
            command_probe=self._residue_command_probe(gate_id)
        )
        reports: list[dict[str, Any]] = []
        for index, (run_id, port) in enumerate(pairs):
            expectation = ResidueExpectation(
                run_ids=(run_id,),
                ports=(port,),
                process_group_ids=process_groups if index == 0 else (),
                mount_paths=mounts if index == 0 else (),
                retained_evidence_paths=retained if index == 0 else (),
                foreign_process_ids=(canary.process.pid,),
                foreign_container_ids=(canary.container_id,),
                port_lock_dir=self.paths.service_control_root / "port-leases",
            )
            reports.append(
                {
                    "partition_index": index + 1,
                    "run_id": run_id,
                    "port": port,
                    **auditor.audit(expectation).payload(),
                }
            )
        return reports

    def _internal_double_audit(self, gate_id: str) -> Mapping[str, Any]:
        selected = (self.resources[gate_id],)
        passes = (
            self._audit_selected_resources(gate_id=gate_id, selected=selected),
            self._audit_selected_resources(gate_id=gate_id, selected=selected),
        )
        if any(
            not reports or any(report["ok"] is not True for report in reports)
            for reports in passes
        ):
            raise GateExecutionError(f"{gate_id} post-terminal residue audit failed")
        return {
            "schema": "fortgym.m1b-internal-double-residue-audit/v1",
            "gate_id": gate_id,
            "passes": passes,
        }

    def _service(
        self,
        *,
        gate_id: str,
        run_ids: Sequence[str],
        fault_session: FaultSessionBinding | None = None,
        allow_startup_faults: bool = False,
        allow_runtime_faults: bool = False,
        allow_workspace_faults: bool = False,
        oom_monitor_factory: Callable[[Any, Any], Any] | None = None,
        provider_network_factory: Callable[..., Any] | None = None,
        enospc: bool = False,
        base_port: int = 58_000,
        isolated_homes: bool = False,
        nonruntime_port_conflict_run_ids: Sequence[str] = (),
    ) -> BrokeredSupervisionService:
        identifiers = iter(tuple(run_ids))
        session_binding = fault_session or FaultSessionBinding()

        def id_factory() -> str:
            try:
                return next(identifiers)
            except StopIteration as exc:
                raise GateExecutionError(
                    "service requested an unplanned run identity"
                ) from exc

        config = ServiceConfig(
            db_path=self.paths.db_path,
            artifacts_root=self.paths.artifacts_root,
            control_root=self.paths.service_control_root,
            repo_root=self.paths.repo_root,
            python_executable=Path(sys.executable),
            entrypoint_path=self.paths.repo_root
            / "infra"
            / "m1b"
            / "runtime_entrypoint.sh",
            dfroot=self.paths.dfroot,
            code_sha256=p1_measurement_code_digest(),
            base_port=base_port,
            max_cohort=8,
            allow_test_startup_faults=allow_startup_faults,
            allow_test_runtime_fault_profiles=allow_runtime_faults,
            allow_test_workspace_fault_profiles=allow_workspace_faults,
            image_archive_path=self.paths.runtime_archive_path,
        )
        loader = self._evidence_loader(gate_id) if enospc else None
        workspace = (
            PrelaunchEnospcWorkspace(
                command_runner=self._fault_runner_for_unbound(gate_id)
            )
            if enospc
            else None
        )
        return BrokeredSupervisionService(
            registry=self.registry,
            config=config,
            manager_factory=fault_session_manager_factory(
                session_binding,
                isolated_homes=isolated_homes,
            ),
            pre_readiness_oom_monitor_factory=oom_monitor_factory,
            provider_network_controller_factory=provider_network_factory,
            enospc_evidence_loader=loader,
            enospc_workspace=workspace,
            id_factory=id_factory,
            broker_factory=self.broker,
            gate_id=gate_id,
            attempt_hook=self._start_run_attempt,
            binding_factory=self._binding_for_contract,
            runtime_controller_observer=self._remember_runtime_controller,
            fault_session=session_binding,
            nonruntime_port_conflict_run_ids=nonruntime_port_conflict_run_ids,
        )

    def _request(self, *, cohort_size: int = 1) -> SupervisedRunRequest:
        return SupervisedRunRequest(
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=20,
            ticks_per_step=200,
            cohort_size=cohort_size,
            safe=True,
            preserve_save=False,
            memory_window=0,
        )

    def _planned_ids(self, gate_id: str, roles: Sequence[str]) -> tuple[str, ...]:
        prefix = hashlib.sha256(
            f"{self.paths.batch_id}\0{gate_id}".encode()
        ).hexdigest()[:12]
        return tuple(
            f"m1b-{gate_id.lower().replace('-', '')}-{role.replace('_', '')}-{prefix}"
            for role in roles
        )

    def _bind_permits(
        self,
        run_ids: Sequence[str],
        permits: Sequence[Any],
    ) -> None:
        if len(run_ids) != len(permits):
            raise GateExecutionError("run and permit cardinality differs")
        with self._permit_lock:
            for run_id, permit in zip(run_ids, permits, strict=True):
                if run_id in self._permit_by_run:
                    raise GateExecutionError("run permit was already bound")
                self._permit_by_run[run_id] = permit

    def _start_run_attempt(self, run_id: str) -> None:
        with self._permit_lock:
            permit = self._permit_by_run.get(run_id)
        if permit is None:
            raise GateExecutionError("external run lacks its exact permit")
        launch = self.paths.service_control_root / run_id / "launch.json"
        identity = _sha256_file(launch)
        with self._permit_lock:
            previous = self._attempt_identity_by_run.get(run_id)
            if previous is not None and previous != identity:
                raise GateExecutionError("durable attempt identity changed")
            if permit.started:
                if previous is None:
                    raise GateExecutionError("started attempt lacks its host identity")
                return
            permit.start(identity_sha256=identity)
            self._attempt_identity_by_run[run_id] = identity

    def _binding_for_contract(
        self,
        contract: Any,
        *,
        peer_run_id: str | None = None,
        session_sha256: str | None = None,
    ) -> PublicRunBinding:
        with self._permit_lock:
            permit = self._permit_by_run.get(str(contract.run_id))
        if permit is None or not permit.started:
            raise GateExecutionError("run binding lacks a durable started permit")
        launch = self.paths.service_control_root / str(contract.run_id) / "launch.json"
        identity = _sha256_file(launch)
        if self._attempt_identity_by_run.get(str(contract.run_id)) != identity:
            raise GateExecutionError("run binding identity differs from attempt start")
        binding = public_binding(
            contract,
            attempt_id=str(permit.attempt_id),
            attempt_identity_sha256=identity,
            peer_run_id=peer_run_id,
            session_sha256=session_sha256,
        )
        previous = self._bindings.get(str(contract.run_id))
        if previous is not None and (
            dataclasses.replace(
                previous,
                peer_run_id=peer_run_id,
                session_sha256=session_sha256,
            )
            != binding
        ):
            raise GateExecutionError("run binding changed after attempt start")
        self._bindings[str(contract.run_id)] = binding
        return binding

    def _remember_runtime_controller(
        self,
        run_id: str,
        controller: DockerRuntimeController,
    ) -> None:
        if controller.contract.run_id != run_id:
            raise GateExecutionError("runtime-controller run identity differs")
        with self._permit_lock:
            previous = self._runtime_controllers.get(run_id)
            if previous is not None and (
                previous.contract.environment_identity()
                != controller.contract.environment_identity()
                or previous.entrypoint_path != controller.entrypoint_path
                or previous.evidence_dir != controller.evidence_dir
            ):
                raise GateExecutionError("runtime-controller identity changed")
            self._runtime_controllers[run_id] = controller

    def _runtime_controller_for_docker_argv(
        self,
        argv: Sequence[str],
    ) -> DockerRuntimeController | None:
        normalized = tuple(str(item) for item in argv)
        if (
            len(normalized) != 5
            or Path(normalized[0]).name != "docker"
            or normalized[1:4] != ("inspect", "--type", "container")
        ):
            return None
        identifier = normalized[4].removeprefix("/").lower()
        with self._permit_lock:
            controllers = tuple(self._runtime_controllers.values())
        matches = [
            controller
            for controller in controllers
            if identifier
            in {
                controller.container_name.lower(),
                str(controller._container_id or "").lower(),
            }
        ]
        if not matches:
            # Orphan managers run in a separate process; their in-memory
            # observer cannot populate the parent's controller dictionary.
            # Recreate only inspection context from the durable bound launch.
            run_id = self._run_id_from_docker_argv(normalized)
            permit = self._permit_by_run.get(run_id)
            if permit is not None and permit.gate_id in {"ORPHAN-1", "ORPHAN-2"}:
                service = self._service(gate_id=permit.gate_id, run_ids=())
                contract = service._load_contract(run_id)
                self._binding_for_contract(contract)
                record = self.registry.get(run_id)
                if record is None:
                    raise GateExecutionError("orphan inspection registry record is absent")
                resolution = _read_json_object(
                    self.paths.service_control_root / run_id / "attempts"
                    / "attempt-0001" / "runtime" / "image-resolution.json"
                )
                if (
                    resolution.get("schema") != "fortgym.m1b-image-resolution/v1"
                    or any(
                        resolution.get(name) != getattr(contract, name)
                        for name in (
                            "image_manifest_sha256", "image_config_sha256",
                            "image_archive_sha256",
                        )
                    )
                    or resolution.get("resolved_reference") not in {
                        f"sha256:{contract.image_manifest_sha256}",
                        f"sha256:{contract.image_config_sha256}",
                    }
                ):
                    raise GateExecutionError("orphan inspection image resolution differs")
                controller = service._runtime_controller(
                    record, self.paths.service_control_root / run_id
                )
                controller._resolved_image_reference = resolution["resolved_reference"]
                # The broker response still verifies exact container, image,
                # environment and mount digests in the projection adapter.
                return controller
        if len(matches) != 1:
            raise GateExecutionError(
                "Docker inspect does not identify one local runtime controller"
            )
        return matches[0]

    def _inspection_binding_for_docker_argv(self, argv: Sequence[str]) -> PublicRunBinding:
        run_id = self._run_id_from_docker_argv(argv)
        with self._permit_lock:
            binding = self._bindings.get(run_id)
        if binding is None:
            raise GateExecutionError("Docker inspection lacks an exact run binding")
        return binding

    def _complete_attempt(
        self, permit: Any, payload: Mapping[str, Any], outcome: str
    ) -> Path:
        path = self._gate_path(permit.gate_id, f"attempts/{permit.attempt_id}.json")
        _write_once_json(
            path,
            {
                "schema": "fortgym.m1b-host-attempt/v1",
                "gate_id": permit.gate_id,
                "attempt_id": permit.attempt_id,
                "role": permit.role,
                "kind": permit.kind.value,
                "outcome": outcome,
                "payload": _safe_json(payload),
            },
        )
        permit.complete(outcome_code=outcome, evidence_paths=(path,))
        return path

    def _wait_for_reusable_port(
        self, port: int, *, timeout_seconds: float = 120.0
    ) -> None:
        """Wait until a prior gate's loopback socket is genuinely reusable.

        The frozen broker contract intentionally reuses ports across gates.
        Cleanup proves that the supervisor lease and listener are gone, while
        the kernel can still refuse an immediate rebind during connection
        teardown. Acquire and release the production PortLease itself before
        starting the next permit so this transient cannot consume an attempt.
        """

        deadline = time.monotonic() + timeout_seconds
        lock_dir = self.paths.service_control_root / "port-leases"
        while True:
            lease = PortLease(port, lock_dir)
            try:
                lease.acquire()
            except PortLeaseError:
                if time.monotonic() >= deadline:
                    raise GateExecutionError(
                        f"loopback port {port} did not become reusable"
                    ) from None
                time.sleep(0.05)
                continue
            lease.release()
            return

    def _record_contracts(
        self, gate_id: str, service: SupervisionService, run_ids: Sequence[str]
    ) -> tuple[Any, ...]:
        contracts = tuple(service._load_contract(run_id) for run_id in run_ids)
        resources = self.resources[gate_id]
        for contract in contracts:
            resources.run_ids.append(contract.run_id)
            resources.ports.append(contract.port)
            resources.retained_evidence_paths.append(
                self.paths.service_control_root / contract.run_id
            )
            permit = self._permit_by_run.get(contract.run_id)
            if permit is not None:
                # Concurrent managers must not race the frozen attempt ledger.
                # Reserve has already persisted launch.json, so start every
                # permit in the contract's deterministic cohort order before
                # any worker thread reaches run_reserved().  The service hook
                # remains as an idempotent fail-closed check.
                if not permit.started:
                    self._wait_for_reusable_port(contract.port)
                self._start_run_attempt(contract.run_id)
                self._binding_for_contract(contract)
        return contracts

    def _gate_port_2(self, context: GateExecutionContext) -> Path:
        self._failure_stage = "bind_planned_attempts"
        peer_id, contender_id = self._planned_ids(
            context.gate_id, ("peer_a", "contender_b")
        )
        peer_permit, contender_permit = context.attempts
        self._bind_permits((peer_id, contender_id), (peer_permit, contender_permit))
        self._failure_stage = "reserve_peer"
        peer_service = self._service(gate_id=context.gate_id, run_ids=(peer_id,))
        launch = peer_service.reserve(self._request())
        peer_contract = self._record_contracts(
            context.gate_id, peer_service, launch.run_ids
        )[0]
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="m1b-port2")
        futures: dict[str, Any] = {}
        unwind = _PausedHarnessUnwindGuard(
            broker=self.broker(context.gate_id),
            registry=self.registry,
            gate_id=context.gate_id,
            evidence_path=self._gate_path(context.gate_id, "pause-unwind.json"),
            futures=futures,
        )
        try:
            with unwind:
                self._failure_stage = "launch_peer"
                peer_future = pool.submit(peer_service.run_reserved, peer_id)
                futures[peer_id] = peer_future
                self._run_futures[peer_id] = peer_future

                def load_owned_peer() -> OwnedRun | None:
                    if not peer_future.done():
                        try:
                            return self._evidence_loader(context.gate_id).try_load(
                                peer_id
                            )
                        except Exception:
                            if not peer_future.done():
                                raise
                    try:
                        early_result = peer_future.result()
                    except Exception as early_exc:  # noqa: BLE001 - sealed type only
                        result_evidence: Mapping[str, Any] = {
                            "future_error_type": type(early_exc).__name__,
                        }
                    else:
                        result_evidence = {
                            "future_error_type": None,
                            "result": _result_summary(early_result),
                            "finalized": getattr(early_result, "finalized", None),
                            "action": getattr(early_result, "action", None),
                        }
                    run_control = self.paths.service_control_root / peer_id
                    diagnostic_files: list[dict[str, Any]] = []
                    for candidate in (
                        run_control / "brokered-runtime-runner.json",
                        run_control / "manager-terminal.json",
                        run_control / "manager-journal.jsonl",
                        run_control
                        / "attempts"
                        / "attempt-0001"
                        / "attempt-journal.jsonl",
                        run_control / "attempts" / "attempt-0001" / "terminal.json",
                        run_control
                        / "attempts"
                        / "attempt-0001"
                        / "runtime"
                        / "startup-terminal.json",
                    ):
                        if candidate.is_file() and not candidate.is_symlink():
                            diagnostic_files.append(
                                {
                                    "path": str(candidate.relative_to(run_control)),
                                    "sha256": _sha256_file(candidate),
                                    "size_bytes": candidate.stat().st_size,
                                }
                            )
                    broker_errors: list[Mapping[str, Any]] = []
                    error_root = (
                        self.paths.evidence_root / "broker-errors" / context.gate_id
                    )
                    if error_root.is_dir() and not error_root.is_symlink():
                        for error_path in sorted(error_root.glob("*.json")):
                            if error_path.is_file() and not error_path.is_symlink():
                                broker_errors.append(_read_json_object(error_path))
                    _write_once_json(
                        self._gate_path(context.gate_id, "gate-failure.json"),
                        {
                            "schema": "fortgym.m1b-host-gate-failure/v1",
                            "gate_id": context.gate_id,
                            "error_type": "ManagedRunTerminatedBeforeOwnedEvidence",
                            "run_id": peer_id,
                            **result_evidence,
                            "diagnostic_files": diagnostic_files,
                            "broker_errors": broker_errors,
                        },
                    )
                    raise GateExecutionError(
                        "PORT-2 peer terminated before owned runtime evidence settled"
                    )

                self._failure_stage = "wait_for_owned_peer"
                owned_peer = _wait_until(
                    load_owned_peer,
                    timeout_seconds=180.0,
                    label="PORT-2 live peer",
                )
                self._record_owned_resources(context.gate_id, owned_peer)
                peer_binding = self._binding_for_contract(peer_contract)
                self._failure_stage = "pause_peer_harness"
                paused_result = self.broker(context.gate_id).execute(
                    ("/bin/kill", "-STOP", "--", str(owned_peer.harness_pid)),
                    binding=peer_binding,
                    timeout_seconds=10.0,
                    action="pause_peer_harness",
                    parameters={},
                )
                if paused_result.returncode != 0:
                    raise GateExecutionError("PORT-2 peer hold failed")
                unwind.note_pause(
                    run_id=peer_id,
                    harness_pid=owned_peer.harness_pid,
                    binding=peer_binding,
                    resume_action="resume_peer_harness",
                )
                self._failure_stage = "capture_peer_before_conflict"
                before_identity = peer_service.environment_identity(peer_id)
                before_screen = peer_service.capture_screen(peer_id)
                self._failure_stage = "reserve_contender"
                contender_service = self._service(
                    gate_id=context.gate_id,
                    run_ids=(contender_id,),
                    nonruntime_port_conflict_run_ids=(contender_id,),
                )
                contender_launch = contender_service.reserve(self._request())
                self._start_run_attempt(contender_id)
                contender_contract = self._record_contracts(
                    context.gate_id, contender_service, contender_launch.run_ids
                )[0]
                if contender_contract.port != peer_contract.port:
                    raise GateExecutionError(
                        "PORT-2 contender did not reuse the peer port"
                    )
                started = time.monotonic()
                self._failure_stage = "run_contender"
                contender_result = contender_service.run_reserved(contender_id)
                elapsed = time.monotonic() - started
                self._failure_stage = "capture_peer_after_conflict"
                after_identity = peer_service.environment_identity(peer_id)
                after_screen = peer_service.capture_screen(peer_id)
                if peer_future.done():
                    raise GateExecutionError("PORT-2 held peer terminated early")
                self._failure_stage = "resume_peer_harness"
                resumed_result = unwind.resume(peer_id)
                self._failure_stage = "request_durable_peer_stop"
                if not self.registry.request_stop(peer_id):
                    raise GateExecutionError("PORT-2 durable peer stop request failed")
                self._failure_stage = "join_stopped_peer"
                peer_result = peer_future.result(timeout=120.0)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        contender_reason = getattr(contender_result, "reason", {})
        contender_attempt = (
            self.paths.service_control_root / contender_id / "attempts" / "attempt-0001"
        )
        contender_events = tuple(
            str(row.get("event"))
            for row in _read_jsonl_objects(contender_attempt / "attempt-journal.jsonl")
        )
        second_runtime_started = (
            contender_attempt / "runtime" / "container-created.json"
        ).exists()
        second_harness_started = "child_started" in contender_events
        self._failure_stage = "validate_contender_terminal"
        contender_terminal_proof = _port2_conflict_terminal_proof(contender_result)
        before_rpc = {
            "run_id": peer_id,
            "contract_sha256": peer_contract.contract_sha256,
            "nonce_sha256": _sha256_bytes(peer_contract.nonce.encode()),
            "container_id": owned_peer.container_id,
            "runtime_host_pid": owned_peer.runtime_host_pid,
            "rpc_method": "get_screen",
            "response_sha256": _sha256_bytes(_canonical_bytes(before_screen)),
            "ok": True,
        }
        after_rpc = {
            **before_rpc,
            "response_sha256": _sha256_bytes(_canonical_bytes(after_screen)),
        }
        peer_identity_unchanged = before_identity == after_identity and all(
            before_rpc[name] == after_rpc[name]
            for name in (
                "run_id",
                "contract_sha256",
                "nonce_sha256",
                "container_id",
                "runtime_host_pid",
                "rpc_method",
                "ok",
            )
        )
        self._failure_stage = "validate_conflict_evidence"
        if (
            elapsed > 5.0
            or getattr(contender_result, "status", None) != "failed"
            or not isinstance(contender_reason, Mapping)
            or contender_reason.get("code") != "port_lease_busy"
            or second_runtime_started
            or second_harness_started
            or not peer_identity_unchanged
        ):
            raise GateExecutionError("PORT-2 exact conflict evidence differs")
        self._failure_stage = "validate_peer_terminal_chain"
        peer_terminal_proof = _terminal_proof(peer_result)
        peer_terminal = _read_json_object(
            Path(peer_result.control_dir)
            / "attempts"
            / "attempt-0001"
            / "terminal.json"
        )
        self._failure_stage = "validate_peer_stop_outcome"
        if (
            getattr(peer_result, "status", None) != "stopped"
            or peer_terminal_proof["reason_code"] != "external_worker_stopped"
            or peer_terminal.get("primary_terminal_class") != "child_exit"
            or peer_terminal.get("returncode") != 21
        ):
            raise GateExecutionError("PORT-2 peer durable-stop terminal differs")
        self._failure_stage = "complete_attempt_permits"
        self._complete_attempt(
            contender_permit,
            {
                "elapsed_seconds": elapsed,
                "result": _result_summary(contender_result),
                "terminal_proof": contender_terminal_proof,
            },
            "port_lease_conflict",
        )
        self._complete_attempt(
            peer_permit,
            {
                **_result_summary(peer_result),
                "terminal_proof": peer_terminal_proof,
                "resume_receipt_sha256": _sha256_file(resumed_result.evidence_path),
            },
            "external_worker_stopped",
        )
        self._failure_stage = "write_gate_receipt"
        return self._gate_receipt(
            context,
            {
                "elapsed_seconds": elapsed,
                "peer_identity_unchanged": peer_identity_unchanged,
                "peer_rpc_before": before_rpc,
                "peer_rpc_after": after_rpc,
                "peer_held_during_conflict": True,
                "peer_durable_stop_requested": True,
                "contender": _result_summary(contender_result),
                "contender_terminal_proof": contender_terminal_proof,
                "peer": _result_summary(peer_result),
                "peer_terminal_proof": peer_terminal_proof,
            },
            facts={
                "fail_closed_seconds_lte": elapsed,
                "second_runtime_started": second_runtime_started,
                "second_harness_started": second_harness_started,
                "peer_nonce_and_rpc_unchanged": peer_identity_unchanged,
            },
        )

    def _gate_cold_retry(self, context: GateExecutionContext) -> Path:
        self._failure_stage = "bind_planned_attempts"
        run_ids = self._planned_ids(
            context.gate_id, ("suppressed_first", "replacement_second")
        )
        self._bind_permits(run_ids, context.attempts)
        self._failure_stage = "reserve_suppressed_attempt"
        first_service = self._service(
            gate_id=context.gate_id,
            run_ids=(run_ids[0],),
            allow_startup_faults=True,
            base_port=58_000,
        )
        first_launch = first_service._reserve(
            self._request(),
            test_fault=RuntimeTestFault.SUPPRESS_RPC_READINESS,
        )
        first_contract = self._record_contracts(
            context.gate_id, first_service, first_launch.run_ids
        )[0]
        self._failure_stage = "run_suppressed_attempt"
        first_result = first_service.run_reserved(run_ids[0])
        self._failure_stage = "validate_suppressed_terminal"
        first_proof = _terminal_proof(first_result)
        first_code = first_proof["reason_code"]
        _write_once_json(
            self._gate_path(context.gate_id, "suppressed-terminal-diagnostic.json"),
            {
                "schema": "fortgym.m1b-cold-terminal-diagnostic/v1",
                "result": _result_summary(first_result),
                "terminal_proof": first_proof,
            },
        )
        if first_code != "rpc_readiness_timeout":
            raise GateExecutionError("COLD-RETRY first terminal differs")

        self._failure_stage = "reserve_replacement_attempt"
        second_service = self._service(
            gate_id=context.gate_id,
            run_ids=(run_ids[1],),
            allow_startup_faults=False,
            base_port=58_001,
        )
        second_launch = second_service.reserve(self._request())
        second_contract = self._record_contracts(
            context.gate_id, second_service, second_launch.run_ids
        )[0]
        self._failure_stage = "run_replacement_attempt"
        second_result = second_service.run_reserved(run_ids[1])
        self._failure_stage = "validate_replacement_terminal"
        second_proof = _terminal_proof(second_result)
        if getattr(second_result, "status", None) != "completed":
            raise GateExecutionError("COLD-RETRY replacement did not complete")
        production_rejected = False
        try:
            second_service.run_cold_retry_preflight(self._request())
        except SupervisionConfigurationError:
            production_rejected = True
        if not production_rejected:
            raise GateExecutionError("production mode accepted a startup fault knob")

        contracts = (first_contract, second_contract)
        results = (first_result, second_result)
        container_ids: list[str] = []
        for contract in contracts:
            created = _read_json_object(
                self.paths.service_control_root
                / contract.run_id
                / "attempts"
                / "attempt-0001"
                / "runtime"
                / "container-created.json"
            )
            container_id = str(created.get("container_id") or "").lower()
            if not _CONTAINER_ID_RE.fullmatch(container_id):
                raise GateExecutionError("COLD-RETRY container identity differs")
            container_ids.append(container_id)
        fresh_fields = {
            "run_id": first_contract.run_id != second_contract.run_id,
            "port": first_contract.port != second_contract.port,
            "nonce": first_contract.nonce != second_contract.nonce,
            "contract_sha256": (
                first_contract.contract_sha256 != second_contract.contract_sha256
            ),
            "runtime_save": (
                first_contract.runtime_save != second_contract.runtime_save
            ),
            "container_id": container_ids[0] != container_ids[1],
            "artifact_dir": (
                self.paths.artifacts_root / first_contract.run_id
                != self.paths.artifacts_root / second_contract.run_id
            ),
        }
        if not all(fresh_fields.values()):
            raise GateExecutionError("COLD-RETRY reused an identity or resource")
        for permit, contract, result, proof in zip(
            context.attempts,
            contracts,
            results,
            (first_proof, second_proof),
            strict=True,
        ):
            if not permit.started:
                raise GateExecutionError("COLD-RETRY attempt was not accounted")
            self._complete_attempt(
                permit,
                {
                    "contract_sha256": contract.contract_sha256,
                    "terminal_proof": proof,
                    **_result_summary(result),
                },
                str(proof["reason_code"] or result.status),
            )
        return self._gate_receipt(
            context,
            {
                "run_ids": list(run_ids),
                "replacement_kind": "test_injector_invalid_rerun",
                "first_terminal_proof": first_proof,
                "second_terminal_proof": second_proof,
                "fresh_fields": fresh_fields,
                "production_mode_fault_knob_rejected": production_rejected,
            },
            facts={
                "first_terminal": first_code,
                "first_cleanup_verified": True,
                "second_uses_fresh_identity_and_resources": all(fresh_fields.values()),
                "second_completes": second_result.status == "completed",
                "production_mode_accepts_fault_knob": not production_rejected,
            },
        )

    def _gate_co_8(self, context: GateExecutionContext) -> Path:
        self._failure_stage = "bind_planned_attempts"
        roles = tuple(permit.role for permit in context.attempts)
        run_ids = self._planned_ids(context.gate_id, roles)
        self._bind_permits(run_ids, context.attempts)
        service = self._service(
            gate_id=context.gate_id,
            run_ids=run_ids,
            isolated_homes=True,
        )
        self._failure_stage = "reserve_cohort"
        launch = service.reserve(self._request(cohort_size=8))
        self._failure_stage = "start_ordered_attempts"
        contracts = self._record_contracts(context.gate_id, service, launch.run_ids)
        self._failure_stage = "launch_cohort"
        start_barrier = threading.Barrier(8)
        start_samples: dict[str, int] = {}
        start_lock = threading.Lock()

        def run_one(run_id: str) -> Any:
            start_barrier.wait(timeout=30.0)
            with start_lock:
                start_samples[run_id] = time.monotonic_ns()
            return service.run_reserved(run_id)

        owned: dict[str, OwnedRun] = {}
        pause_receipts: dict[str, str] = {}
        resume_receipts: dict[str, str] = {}
        rpc_receipts: dict[str, Mapping[str, Any]] = {}
        pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="m1b-co8")
        futures: dict[str, Any] = {}
        unwind = _PausedHarnessUnwindGuard(
            broker=self.broker(context.gate_id),
            registry=self.registry,
            gate_id=context.gate_id,
            evidence_path=self._gate_path(context.gate_id, "pause-unwind.json"),
            futures=futures,
        )
        try:
            with unwind:
                futures.update(
                    {run_id: pool.submit(run_one, run_id) for run_id in launch.run_ids}
                )
                self._run_futures.update(futures)
                self._failure_stage = "wait_for_owned_cohort"
                for contract in contracts:
                    run = _wait_until(
                        lambda run_id=contract.run_id: self._evidence_loader(
                            context.gate_id
                        ).try_load(run_id),
                        timeout_seconds=300.0,
                        label=f"CO-8 ready runtime {contract.run_id}",
                    )
                    owned[contract.run_id] = run
                    self._record_owned_resources(context.gate_id, run)
                    binding = self._binding_for_contract(contract)
                    held = self.broker(context.gate_id).execute(
                        ("/bin/kill", "-STOP", "--", str(run.harness_pid)),
                        binding=binding,
                        timeout_seconds=10.0,
                        action="pause_cohort_harness",
                        parameters={},
                    )
                    if held.returncode != 0:
                        raise GateExecutionError("CO-8 harness hold failed")
                    unwind.note_pause(
                        run_id=contract.run_id,
                        harness_pid=run.harness_pid,
                        binding=binding,
                        resume_action="resume_cohort_harness",
                    )
                    pause_receipts[contract.run_id] = _sha256_file(held.evidence_path)
                simultaneous = (
                    len(owned) == 8
                    and all(not future.done() for future in futures.values())
                    and all(
                        Path(f"/proc/{run.harness_pid}").is_dir()
                        for run in owned.values()
                    )
                    and all(
                        Path(f"/proc/{run.runtime_host_pid}").is_dir()
                        for run in owned.values()
                    )
                )
                if not simultaneous:
                    raise GateExecutionError(
                        "CO-8 did not prove simultaneous cotenancy"
                    )
                for contract in contracts:
                    screen = service.capture_screen(contract.run_id)
                    rpc_receipts[contract.run_id] = {
                        "run_id": contract.run_id,
                        "contract_sha256": contract.contract_sha256,
                        "nonce_sha256": _sha256_bytes(contract.nonce.encode()),
                        "port": contract.port,
                        "container_id": owned[contract.run_id].container_id,
                        "rpc_method": "get_screen",
                        "response_sha256": _sha256_bytes(_canonical_bytes(screen)),
                        "ok": True,
                    }
                for contract in reversed(contracts):
                    resumed = unwind.resume(contract.run_id)
                    resume_receipts[contract.run_id] = _sha256_file(
                        resumed.evidence_path
                    )
                results = {
                    run_id: future.result(timeout=3600)
                    for run_id, future in futures.items()
                }
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if any(
            getattr(result, "status", None) != "completed"
            for result in results.values()
        ):
            raise GateExecutionError("CO-8 contains a non-completing run")
        terminal_proofs = {
            run_id: _terminal_proof(result) for run_id, result in results.items()
        }
        identities = [contract.environment_identity() for contract in contracts]
        home_records = {
            contract.run_id: _read_json_object(
                self.paths.service_control_root
                / contract.run_id
                / "attempts"
                / "attempt-0001"
                / "isolated-home.json"
            )
            for contract in contracts
        }
        distinct_sets = {
            "ports": {contract.port for contract in contracts},
            "nonces": {contract.nonce for contract in contracts},
            "saves": {contract.runtime_save for contract in contracts},
            "containers": {run.container_id for run in owned.values()},
            "runtime_pids": {run.runtime_host_pid for run in owned.values()},
            "harness_pids": {run.harness_pid for run in owned.values()},
            "homes": {str(record.get("home")) for record in home_records.values()},
            "artifacts": {
                str(self.paths.artifacts_root / contract.run_id)
                for contract in contracts
            },
        }
        if any(len(values) != 8 for values in distinct_sets.values()):
            raise GateExecutionError("CO-8 identities are not distinct")
        cohort_ids = tuple(sorted(run_ids))
        symmetric = all(
            tuple(contract.cohort_run_ids) == cohort_ids
            and contract.cotenancy()["peer_run_ids"]
            == [run_id for run_id in cohort_ids if run_id != contract.run_id]
            and contract.cohort_digest == contracts[0].cohort_digest
            for contract in contracts
        )
        if not symmetric:
            raise GateExecutionError("CO-8 cohort graph is not symmetric")
        seed_count = len(
            {
                (contract.seed_tree_sha256, contract.seed_world_sha256)
                for contract in contracts
            }
        )
        rpc_matches = all(
            receipt.get("run_id") == contract.run_id
            and receipt.get("contract_sha256") == contract.contract_sha256
            and receipt.get("nonce_sha256") == _sha256_bytes(contract.nonce.encode())
            and receipt.get("port") == contract.port
            and receipt.get("container_id") == owned[contract.run_id].container_id
            and receipt.get("ok") is True
            for contract in contracts
            for receipt in (rpc_receipts[contract.run_id],)
        )
        artifact_roots = {
            contract.run_id: self.paths.artifacts_root / contract.run_id
            for contract in contracts
        }
        cross_run_artifact_references, artifact_scan = _bounded_cross_run_artifact_scan(
            artifact_roots
        )
        for contract in contracts:
            record = home_records[contract.run_id]
            attempt_root = (
                self.paths.service_control_root
                / contract.run_id
                / "attempts"
                / "attempt-0001"
            ).resolve(strict=True)
            home = Path(str(record["home"]))
            temporary = Path(str(record["tmpdir"]))
            home_metadata = home.lstat()
            temporary_metadata = temporary.lstat()
            if (
                record.get("schema") != "fortgym.m1b-isolated-harness-home/v1"
                or record.get("run_id") != contract.run_id
                or home.resolve(strict=True) != attempt_root / "home"
                or temporary.resolve(strict=True) != attempt_root / "tmp"
                or stat.S_ISLNK(home_metadata.st_mode)
                or stat.S_ISLNK(temporary_metadata.st_mode)
                or not stat.S_ISDIR(home_metadata.st_mode)
                or not stat.S_ISDIR(temporary_metadata.st_mode)
                or home_metadata.st_dev != record.get("home_device")
                or home_metadata.st_ino != record.get("home_inode")
                or temporary_metadata.st_dev != record.get("tmpdir_device")
                or temporary_metadata.st_ino != record.get("tmpdir_inode")
            ):
                raise GateExecutionError("CO-8 isolated home path differs")
            shutil.rmtree(attempt_root / "home")
            shutil.rmtree(attempt_root / "tmp")
        for permit, contract in zip(context.attempts, contracts, strict=True):
            self._complete_attempt(
                permit,
                {
                    "contract_sha256": contract.contract_sha256,
                    "result": _result_summary(results[contract.run_id]),
                    "terminal_proof": terminal_proofs[contract.run_id],
                },
                "completed",
            )
        return self._gate_receipt(
            context,
            {
                "logical_runs_completed": 8,
                "identities_sha256": _sha256_bytes(_canonical_bytes(identities)),
                "cohort_sha256": contracts[0].cohort_digest,
                "barrier_start_monotonic_ns": start_samples,
                "simultaneous_cotenancy": simultaneous,
                "pause_receipts": pause_receipts,
                "resume_receipts": resume_receipts,
                "rpc_receipts": rpc_receipts,
                "terminal_proofs": terminal_proofs,
                "gameplay_artifact_scan": artifact_scan,
            },
            facts={
                "logical_runs_completed": len(results),
                "seed_attestation_unique_count": seed_count,
                "distinct_ports_nonces_containers_pids_homes_saves_artifacts": all(
                    len(values) == 8 for values in distinct_sets.values()
                ),
                "rpc_receipts_match_run_nonce": rpc_matches,
                "symmetric_cotenancy_graph": symmetric and simultaneous,
                "cross_run_artifact_references": cross_run_artifact_references,
            },
        )

    def _gate_df_kill(self, context: GateExecutionContext) -> Path:
        return self._post_readiness_fault(context, FaultGate.DF_KILL)

    def _gate_harness_kill(self, context: GateExecutionContext) -> Path:
        return self._post_readiness_fault(context, FaultGate.HARNESS_KILL)

    def _gate_enospc(self, context: GateExecutionContext) -> Path:
        return self._post_readiness_fault(context, FaultGate.ENOSPC)

    def _gate_container_restart(self, context: GateExecutionContext) -> Path:
        return self._post_readiness_fault(context, FaultGate.CONTAINER_RESTART)

    def _gate_daemon_restart(self, context: GateExecutionContext) -> Path:
        return self._post_readiness_fault(context, FaultGate.DAEMON_RESTART)

    def _post_readiness_fault(
        self, context: GateExecutionContext, fault_gate: FaultGate
    ) -> Path:
        self._failure_stage = "reserve_fault_cohort"
        roles = ("target", "peer")
        run_ids = self._planned_ids(context.gate_id, roles)
        self._bind_permits(run_ids, context.attempts)
        session_binding = FaultSessionBinding()
        enospc = fault_gate is FaultGate.ENOSPC
        service = self._service(
            gate_id=context.gate_id,
            run_ids=run_ids,
            fault_session=session_binding,
            allow_workspace_faults=enospc,
            enospc=enospc,
        )
        request = self._request(cohort_size=2)
        launch = (
            service.reserve_enospc_preflight_cohort(request)
            if enospc
            else service.reserve(request)
        )
        contracts = self._record_contracts(context.gate_id, service, launch.run_ids)
        target_contract, peer_contract = contracts
        participants = (
            FaultSessionParticipant(
                run_id=target_contract.run_id,
                role="target",
                contract_sha256=target_contract.contract_sha256,
                nonce_sha256=_sha256_bytes(target_contract.nonce.encode("utf-8")),
                cohort_sha256=target_contract.cohort_digest,
            ),
            FaultSessionParticipant(
                run_id=peer_contract.run_id,
                role="peer",
                contract_sha256=peer_contract.contract_sha256,
                nonce_sha256=_sha256_bytes(peer_contract.nonce.encode("utf-8")),
                cohort_sha256=peer_contract.cohort_digest,
            ),
        )
        session = FaultSessionIdentity(
            packet_id=f"{self.paths.batch_id}-{context.gate_id.lower().replace('-', '')}",
            authority_sha256=FROZEN_ACCEPTANCE_SHA256,
            gate=context.gate_id,
            participants=participants,
        )
        store = FaultSessionStore(
            control_root=self.paths.service_control_root, session=session
        )
        store.initialize()
        session_binding.store = store
        self._run_sessions.update({run_id: session.session_sha256 for run_id in launch.run_ids})
        loader = self._evidence_loader(context.gate_id)
        failure_guard = _FaultSessionFailureGuard(
            store=store,
            service=service,
            run_ids=tuple(launch.run_ids),
            evidence_path=self._gate_path(context.gate_id, "fault-session-unwind.json"),
            enospc_target_run_id=(target_contract.run_id if enospc else None),
        )
        with (
            ThreadPoolExecutor(max_workers=3, thread_name_prefix="m1b-fault") as pool,
            failure_guard,
        ):
            if enospc:
                service.prepare_enospc_preflight_target(target_contract.run_id)
            run_futures = {
                run_id: pool.submit(service.run_reserved, run_id)
                for run_id in launch.run_ids
            }
            self._run_futures.update(run_futures)
            for run_id in launch.run_ids:
                self._failure_stage = f"wait_for_step2:{run_id}"
                _wait_until(
                    lambda run_id=run_id: _fault_ready_while_running(
                        store, run_id, run_futures
                    ),
                    timeout_seconds=300.0,
                    label=f"{context.gate_id} {run_id} step-2 receipt",
                )
            self._failure_stage = "wait_for_target_ownership"
            target = _wait_until(
                lambda: (
                    loader.try_load_enospc_target(
                        target_contract.run_id, peer_run_id=peer_contract.run_id
                    )
                    if enospc
                    else loader.try_load(target_contract.run_id)
                ),
                timeout_seconds=180.0,
                label=f"{context.gate_id} target ownership",
            )
            self._failure_stage = "wait_for_peer_ownership"
            peer = _wait_until(
                lambda: (
                    loader.try_load_enospc_peer(
                        peer_contract.run_id, target_run_id=target_contract.run_id
                    )
                    if enospc
                    else loader.try_load(peer_contract.run_id)
                ),
                timeout_seconds=180.0,
                label=f"{context.gate_id} peer ownership",
            )
            self._record_owned_resources(context.gate_id, target, peer)
            authorization = (
                service._take_enospc_fault_authorization(
                    target_run_id=target.run_id,
                    peer_run_id=peer.run_id,
                )
                if enospc
                else authorize_private_m1b_fault(
                    test_mode=True,
                    gate=fault_gate,
                    target_run_id=target.run_id,
                    peer_run_id=peer.run_id,
                )
            )
            if enospc:
                authorization_identity = _sha256_bytes(
                    _canonical_bytes(
                        {
                            "gate": fault_gate.value,
                            "target_run_id": target.run_id,
                            "peer_run_id": peer.run_id,
                        }
                    )
                )
                context.attempts[0].bind_private_authorization(
                    authorization_identity_sha256=authorization_identity
                )
            probe = LinuxHostFaultProbe(
                target_run_id=target.run_id,
                command_runner=BrokeredFaultCommandRunner(
                    broker=self.broker(context.gate_id),
                    binding=self._binding_for_contract(
                        target_contract,
                        peer_run_id=peer.run_id,
                        session_sha256=session.session_sha256,
                    ),
                    controller_resolver=self._runtime_controller_for_docker_argv,
                    inspection_binding_resolver=self._inspection_binding_for_docker_argv,
                    batch_canary=(self._canary.identity if self._canary else None),
                    canary_state_sha256=(
                        self._canary.container_state_sha256 if self._canary else None
                    ),
                ),
            )
            driver = M1BFaultDriver(
                barrier_probe=probe.barrier_probe,
                ownership_probe=probe.ownership_probe,
                state_probe=probe.state_probe,
                state_diagnostic_probe=probe.peer_health_diagnostics,
                # Real DF needs more than the target detector's polling window
                # to commit steps 3-5. Stay below the session's 180-second hold.
                peer_state_poll_attempts=480 if fault_gate is FaultGate.DF_KILL else None,
                canary_probe=probe.canary_probe,
                command_runner=BrokeredFaultCommandRunner(
                    broker=self.broker(context.gate_id),
                    binding=self._binding_for_contract(
                        target_contract,
                        peer_run_id=peer.run_id,
                        session_sha256=session.session_sha256,
                    ),
                    controller_resolver=self._runtime_controller_for_docker_argv,
                    inspection_binding_resolver=self._inspection_binding_for_docker_argv,
                    batch_canary=(self._canary.identity if self._canary else None),
                    canary_state_sha256=(
                        self._canary.container_state_sha256 if self._canary else None
                    ),
                ),
                daemon_restart_callback=(
                    self._daemon_restart_callback(
                        target_contract, peer.run_id, session.session_sha256
                    )
                    if fault_gate is FaultGate.DAEMON_RESTART
                    else None
                ),
            )
            self._failure_stage = "inject_fault"
            driver_future = pool.submit(
                driver.inject,
                authorization=authorization,
                target=target,
                peer=peer,
                protected_canaries=(self._canary.identity,) if self._canary else (),
            )
            self._failure_stage = "wait_for_fault_action"
            action_digest = _wait_until(
                store.action_attempted_sha256,
                timeout_seconds=300.0,
                label=f"{context.gate_id} action-attempted receipt",
            )
            for run_id in launch.run_ids:
                store.release(run_id, trigger_record_sha256=action_digest)
                failure_guard.note_release(run_id)
            self._failure_stage = "join_fault_driver"
            injection = driver_future.result(timeout=600.0)
            store.persist_completed_claims(
                injection.observation,
                target_nonce=target_contract.nonce,
            )
            failure_guard.note_completion()
            self._failure_stage = "join_fault_workers"
            results = {
                run_id: future.result(timeout=600.0)
                for run_id, future in run_futures.items()
            }
        self._failure_stage = "validate_completed_fault_observation"
        completed = load_completed_fault_observation(
            control_root=self.paths.service_control_root,
            run_id=target_contract.run_id,
            contract_sha256=target_contract.contract_sha256,
            nonce=target_contract.nonce,
            expected_gate=fault_gate,
        )
        if completed is None:
            raise GateExecutionError("completed fault observation is absent")
        payload = completed.get("payload")
        if not isinstance(payload, Mapping):
            raise GateExecutionError("completed fault payload is invalid")
        classifier = payload.get("classifier_evidence")
        timing = payload.get("timing")
        peer_after = payload.get("peer_after")
        target_after = payload.get("after")
        if any(
            not isinstance(value, Mapping)
            for value in (classifier, timing, peer_after, target_after)
        ):
            raise GateExecutionError("completed fault proof components are invalid")
        peer_facts = peer_after.get("facts")
        target_after_facts = target_after.get("facts")
        if not isinstance(peer_facts, Mapping) or not isinstance(
            target_after_facts, Mapping
        ):
            raise GateExecutionError("completed fault state facts are invalid")
        expected_pending = {
            FaultGate.DF_KILL: ["cleanup_seconds_lte_30", "cleanup_double_audit"],
            FaultGate.HARNESS_KILL: [
                "process_group_reaped",
                "runtime_listener_and_lease_removed",
                "cleanup_double_audit",
            ],
            FaultGate.ENOSPC: [
                "private_tmpfs_unmounted_and_absent",
                "cleanup_double_audit",
            ],
            FaultGate.CONTAINER_RESTART: [
                "target_cleanup_verified",
                "cleanup_double_audit",
            ],
            FaultGate.DAEMON_RESTART: [
                "all_affected_runs_terminalized",
                "cleanup_double_audit",
            ],
        }[fault_gate]
        if payload.get("pending_external_checks") != expected_pending:
            raise GateExecutionError("fault observation cleanup obligations differ")
        terminal_proofs = {
            run_id: _terminal_proof(result) for run_id, result in results.items()
        }
        expected_target = {
            FaultGate.DF_KILL: "runtime_df_killed",
            FaultGate.HARNESS_KILL: "harness_killed",
            FaultGate.ENOSPC: "workspace_enospc",
            FaultGate.CONTAINER_RESTART: "runtime_container_restarted",
            FaultGate.DAEMON_RESTART: "docker_daemon_restarted",
        }[fault_gate]
        target_code = terminal_proofs[target_contract.run_id]["reason_code"]
        if target_code != expected_target:
            raise GateExecutionError("fault target terminal classification differs")
        if fault_gate is FaultGate.DAEMON_RESTART and (
            terminal_proofs[peer_contract.run_id]["reason_code"]
            != "docker_daemon_restarted"
        ):
            raise GateExecutionError("daemon restart did not terminalize both runs")
        cleanup_audit = self._internal_double_audit(context.gate_id)
        cleanup_seconds = (
            _cleanup_elapsed_seconds(results[target_contract.run_id])
            if fault_gate is FaultGate.DF_KILL
            else None
        )
        peer_step = peer_facts.get("step")
        peer_continues = (
            peer_facts.get("healthy") is True
            and peer_facts.get("continued_after_fault") is True
        )
        facts_by_gate: dict[FaultGate, dict[str, Any]] = {
            FaultGate.DF_KILL: {
                "target_terminal": target_code,
                "target_oom_killed": classifier.get("oom_killed"),
                "detection_seconds_lte": timing.get("target_detection_seconds"),
                "cleanup_seconds_lte": cleanup_seconds,
                "peer_minimum_step": peer_step,
                "peer_reconnected": peer_facts.get("reconnected"),
            },
            FaultGate.HARNESS_KILL: {
                "target_terminal": target_code,
                "target_process_group_reaped": True,
                "target_runtime_listener_and_lease_removed": True,
                "peer_minimum_step": peer_step,
            },
            FaultGate.ENOSPC: {
                "target_terminal": target_code,
                "errno": classifier.get("errno"),
                "control_plane_journal_survives": True,
                "peer_continues": peer_continues,
                "maximum_fault_bytes": (
                    classifier.get("workspace", {}).get("maximum_fault_bytes")
                    if isinstance(classifier.get("workspace"), Mapping)
                    else None
                ),
            },
            FaultGate.CONTAINER_RESTART: {
                "target_terminal": target_code,
                "silent_reconnect": target_after_facts.get("reconnected"),
                "peer_continues": peer_continues,
            },
            FaultGate.DAEMON_RESTART: {
                "affected_terminal": target_code,
                "silent_continuation": target_after_facts.get("silent_continuation"),
                "reconciliation_seconds_lte": timing.get(
                    "all_required_observations_seconds"
                ),
                "supervisor_remains_operational": target_after_facts.get(
                    "supervisor_operational"
                ),
            },
        }
        for permit, contract in zip(context.attempts, contracts, strict=True):
            result = results[contract.run_id]
            reason = getattr(result, "reason", {})
            outcome = (
                str(reason.get("code"))
                if isinstance(reason, Mapping) and reason.get("code")
                else str(getattr(result, "status", "terminal"))
            )
            self._complete_attempt(
                permit,
                {
                    "result": _result_summary(result),
                    "session_sha256": session.session_sha256,
                    "driver_journal_sha256": _sha256_file(injection.journal_path),
                    "terminal_proof": terminal_proofs[contract.run_id],
                },
                outcome,
            )
        return self._gate_receipt(
            context,
            {
                "fault_gate": fault_gate.value,
                "session_sha256": session.session_sha256,
                "driver_journal_sha256": _sha256_file(injection.journal_path),
                "classifier_evidence": injection.classifier_evidence,
                "completed_observation_sha256": _sha256_bytes(
                    _canonical_bytes(_safe_json(completed))
                ),
                "terminal_proofs": terminal_proofs,
                "cleanup_double_audit": cleanup_audit,
                "results": {
                    run_id: _result_summary(result)
                    for run_id, result in results.items()
                },
            },
            facts=facts_by_gate[fault_gate],
        )

    def _gate_oom(self, context: GateExecutionContext) -> Path:
        roles = ("target", "peer")
        run_ids = self._planned_ids(context.gate_id, roles)
        self._bind_permits(run_ids, context.attempts)
        loader = self._evidence_loader(context.gate_id)
        canary = self._canary

        def monitor_factory(
            target_contract: Any, peer_contract: Any
        ) -> PreReadinessOomMonitor:
            target = loader.load_pre_readiness_oom_target(target_contract.run_id)
            binding = self._binding_for_contract(
                target_contract,
                peer_run_id=peer_contract.run_id,
            )
            probe = LinuxHostFaultProbe(
                target_run_id=target_contract.run_id,
                command_runner=BrokeredFaultCommandRunner(
                    broker=self.broker(context.gate_id),
                    binding=binding,
                    controller_resolver=self._runtime_controller_for_docker_argv,
                    inspection_binding_resolver=self._inspection_binding_for_docker_argv,
                    batch_canary=(self._canary.identity if self._canary else None),
                    canary_state_sha256=(
                        self._canary.container_state_sha256 if self._canary else None
                    ),
                ),
            )
            return PreReadinessOomMonitor(
                authorization=authorize_private_m1b_fault(
                    test_mode=True,
                    gate=FaultGate.OOM,
                    target_run_id=target_contract.run_id,
                    peer_run_id=peer_contract.run_id,
                ),
                target=target,
                peer_run_id=peer_contract.run_id,
                peer_loader=lambda: loader.try_load_oom_peer(
                    peer_contract.run_id,
                    target_run_id=target_contract.run_id,
                ),
                peer_cohort_start_probe=probe.cohort_start_probe,
                peer_ownership_probe=probe.ownership_probe,
                peer_state_probe=probe.state_probe,
                canary_probe=probe.canary_probe,
                protected_canaries=(canary.identity,) if canary else (),
                command_runner=BrokeredFaultCommandRunner(
                    broker=self.broker(context.gate_id),
                    binding=binding,
                    controller_resolver=self._runtime_controller_for_docker_argv,
                    inspection_binding_resolver=self._inspection_binding_for_docker_argv,
                    batch_canary=(self._canary.identity if self._canary else None),
                    canary_state_sha256=(
                        self._canary.container_state_sha256 if self._canary else None
                    ),
                ),
            )

        service = self._service(
            gate_id=context.gate_id,
            run_ids=run_ids,
            allow_runtime_faults=True,
            oom_monitor_factory=monitor_factory,
        )
        launch = service.reserve_oom_preflight_cohort(self._request(cohort_size=2))
        contracts = self._record_contracts(context.gate_id, service, launch.run_ids)
        start_barrier = threading.Barrier(2)

        def run_one(run_id: str) -> Any:
            start_barrier.wait(timeout=30.0)
            return service.run_reserved(run_id)

        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="fortgym-m1b-oom-preflight",
        ) as executor:
            futures = {
                run_id: executor.submit(run_one, run_id) for run_id in launch.run_ids
            }
            self._run_futures.update(futures)
            results = {run_id: futures[run_id].result() for run_id in launch.run_ids}
        target_contract, peer_contract = contracts
        completed = load_completed_fault_observation(
            control_root=self.paths.service_control_root,
            run_id=target_contract.run_id,
            contract_sha256=target_contract.contract_sha256,
            nonce=target_contract.nonce,
            expected_gate=FaultGate.OOM,
        )
        if completed is None:
            raise GateExecutionError("OOM completed observation is absent")
        payload = completed.get("payload")
        if not isinstance(payload, Mapping) or payload.get(
            "pending_external_checks"
        ) != ["target_cleanup_verified", "cleanup_double_audit"]:
            raise GateExecutionError("OOM completed cleanup obligations differ")
        classifier = payload.get("classifier_evidence")
        before = payload.get("before")
        after = payload.get("after")
        peer_after = payload.get("peer_after")
        if any(
            not isinstance(value, Mapping)
            for value in (classifier, before, after, peer_after)
        ):
            raise GateExecutionError("OOM completed evidence components are invalid")
        before_facts = before.get("facts")
        after_facts = after.get("facts")
        peer_facts = peer_after.get("facts")
        memory_events = classifier.get("cgroup_memory_events")
        if (
            not isinstance(before_facts, Mapping)
            or not isinstance(after_facts, Mapping)
            or not isinstance(peer_facts, Mapping)
            or not isinstance(memory_events, Mapping)
            or not isinstance(memory_events.get("before"), Mapping)
            or not isinstance(memory_events.get("after"), Mapping)
        ):
            raise GateExecutionError("OOM classifier evidence is incomplete")
        local_delta = (
            memory_events["after"].get("oom_kill", -1)
            - memory_events["before"].get("oom_kill", -1)
            if all(
                isinstance(memory_events[key].get("oom_kill"), int)
                and not isinstance(memory_events[key].get("oom_kill"), bool)
                for key in ("before", "after")
            )
            else -1
        )
        terminal_proofs = {
            run_id: _terminal_proof(result) for run_id, result in results.items()
        }
        target_code = terminal_proofs[target_contract.run_id]["reason_code"]
        peer_healthy = (
            peer_facts.get("healthy") is True
            and peer_facts.get("runtime_ready") is True
            and peer_facts.get("continued_after_fault") is True
            and peer_facts.get("reconnected") is False
            and getattr(results[peer_contract.run_id], "status", None) == "completed"
        )
        cleanup_audit = self._internal_double_audit(context.gate_id)
        facts = {
            "target_terminal": target_code,
            "cgroup_memory_events_proves_oom": local_delta >= 1,
            "target_memory_events_local_oom_kill_delta_gte": local_delta,
            "exit_137_alone_is_sufficient": False,
            "peer_healthy": peer_healthy,
            "host_oom_counter_delta": after_facts.get("unattributed_host_oom_delta"),
            "host_oom_counter_definition": (
                "global_proc_vmstat_oom_kill_delta minus "
                "target_memory_events_local_oom_kill_delta"
            ),
        }
        if target_code != "runtime_oom":
            raise GateExecutionError("OOM target terminal classification differs")
        for permit, contract in zip(context.attempts, contracts, strict=True):
            result = results[contract.run_id]
            reason = getattr(result, "reason", {})
            outcome = str(
                reason.get("code") if isinstance(reason, Mapping) else result.status
            )
            self._complete_attempt(
                permit,
                {
                    "result": _result_summary(result),
                    "terminal_proof": terminal_proofs[contract.run_id],
                },
                outcome or str(result.status),
            )
        return self._gate_receipt(
            context,
            {
                "results": {
                    key: _result_summary(value) for key, value in results.items()
                },
                "classifier_evidence": classifier,
                "terminal_proofs": terminal_proofs,
                "cleanup_double_audit": cleanup_audit,
            },
            facts=facts,
        )

    def _gate_orphan_1(self, context: GateExecutionContext) -> Path:
        return self._orphan_gate(context, expected_code=None)

    def _gate_orphan_2(self, context: GateExecutionContext) -> Path:
        return self._orphan_gate(context, expected_code="supervisor_lost")

    def _orphan_gate(
        self, context: GateExecutionContext, expected_code: str | None
    ) -> Path:
        role = "target" if expected_code is not None else "managed_orphan"
        run_id = self._planned_ids(context.gate_id, (role,))[0]
        permit = context.attempts[0]
        self._bind_permits((run_id,), (permit,))
        service = self._service(gate_id=context.gate_id, run_ids=(run_id,))
        launch = service.reserve(self._request())
        contract = self._record_contracts(context.gate_id, service, launch.run_ids)[0]
        # The parent owns acceptance accounting. Its exact durable transition
        # must precede fork; the child inherits and revalidates the same launch
        # identity but cannot mutate the parent's permit state.
        self._start_run_attempt(run_id)
        binding = self._binding_for_contract(contract)
        attempt_root = self.paths.service_control_root / run_id / "attempts"
        orphan_unwind_path = self._gate_path(
            context.gate_id, "orphan-child-unwind.json"
        )
        orphan_guard = _OrphanChildUnwindGuard(
            broker=self.broker(context.gate_id),
            binding=binding,
            service=service,
            run_id=run_id,
            gate_id=context.gate_id,
            evidence_path=orphan_unwind_path,
        )
        with orphan_guard:
            child_pid = os.fork()
            if child_pid == 0:  # pragma: no cover - live Linux only
                try:
                    child_registry = RunRegistry(
                        db_path=self.paths.db_path,
                        artifacts_root=self.paths.artifacts_root,
                        recover_interrupted=False,
                    )
                    child = self._service(gate_id=context.gate_id, run_ids=())
                    child.registry = child_registry
                    child.run_reserved(run_id)
                finally:
                    os._exit(0)
            orphan_guard.note_child(child_pid)
            owned = _wait_until(
                lambda: self._evidence_loader(context.gate_id).try_load(run_id),
                timeout_seconds=300.0,
                label=f"{context.gate_id} managed orphan",
            )
            orphan_guard.bind_owned(owned)
            self._record_owned_resources(context.gate_id, owned)
            attempts_before = tuple(
                sorted(path.name for path in attempt_root.iterdir())
            )
        first = orphan_guard.reconciliation
        if not isinstance(first, Mapping):
            raise GateExecutionError("orphan reconciliation result is absent")
        first_result = first.get(run_id)
        if first_result is None:
            raise GateExecutionError("orphan reconciliation did not finalize target")
        terminal_proof = _terminal_proof(first_result)
        manager_journal = (
            self.paths.service_control_root / run_id / "manager-journal.jsonl"
        )
        journal_after_first = manager_journal.read_bytes()
        attempts_after_first = tuple(
            sorted(path.name for path in attempt_root.iterdir())
        )
        second = service.reconcile_all()
        journal_after_second = manager_journal.read_bytes()
        attempts_after_second = tuple(
            sorted(path.name for path in attempt_root.iterdir())
        )
        second_noop = (
            not second
            and journal_after_second == journal_after_first
            and attempts_after_second == attempts_after_first
        )
        if not second_noop:
            raise GateExecutionError("orphan reconciliation was not one-shot")
        attempt_events = tuple(
            str(row.get("event"))
            for row in _read_jsonl_objects(
                attempt_root / "attempt-0001" / "attempt-journal.jsonl"
            )
        )
        run_resumed = (
            attempts_before != ("attempt-0001",)
            or attempts_after_first != attempts_before
            or attempt_events.count("child_started") != 1
        )
        record = self.registry.get(run_id)
        reason = (
            record.metadata.get("terminal_reason", {}) if record is not None else {}
        )
        if expected_code is not None and (
            not isinstance(reason, Mapping) or reason.get("code") != expected_code
        ):
            raise GateExecutionError("ORPHAN-2 terminal classification differs")
        if not self._canary_alive(context.gate_id):
            raise GateExecutionError("foreign canary changed during orphan recovery")
        if (
            terminal_proof["recovered"] is not True
            or terminal_proof["action"] != "finalized"
            or run_resumed
        ):
            raise GateExecutionError("orphan recovery resumed or lacks exact recovery")
        cleanup_audit = self._internal_double_audit(context.gate_id)
        self._complete_attempt(
            permit,
            {
                "first": _safe_json(first),
                "second": _safe_json(second),
                "terminal": reason,
                "terminal_proof": terminal_proof,
                "orphan_child_unwind_sha256": _sha256_file(orphan_unwind_path),
            },
            expected_code or "managed_orphan_reaped",
        )
        facts = (
            {
                "managed_orphans_removed": True,
                "foreign_canary_untouched": True,
                "second_reconciliation_noop": second_noop,
            }
            if expected_code is None
            else {
                "run_resumed": run_resumed,
                "target_terminal": terminal_proof["reason_code"],
                "all_managed_resources_reaped": True,
            }
        )
        return self._gate_receipt(
            context,
            {
                "first_reconciliation": _safe_json(first),
                "second_reconciliation": _safe_json(second),
                "foreign_canary_untouched": True,
                "terminal": reason,
                "terminal_proof": terminal_proof,
                "orphan_child_unwind_sha256": _sha256_file(orphan_unwind_path),
                "attempts_before": attempts_before,
                "attempts_after": attempts_after_second,
                "attempt_journal_child_started_count": attempt_events.count(
                    "child_started"
                ),
                "second_journal_byte_identical": (
                    journal_after_first == journal_after_second
                ),
                "cleanup_double_audit": cleanup_audit,
            },
            facts=facts,
        )

    def _gate_provider_net(self, context: GateExecutionContext) -> Path:
        run_id = self._planned_ids(context.gate_id, ("target",))[0]
        permit = context.attempts[0]
        self._bind_permits((run_id,), (permit,))
        canary = self._canary
        if canary is None:
            raise GateExecutionError("provider-network gate lacks the batch canary")
        helper_sha256 = _sha256_file(_HELPER)
        object_sha256 = _sha256_file(_BPF_OBJECT)

        def canary_probe(pid: int) -> Mapping[str, Any]:
            if pid != canary.process.pid or canary.process.poll() is not None:
                raise GateExecutionError("provider-network canary PID differs")
            cgroup = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
            identity = _sha256_bytes(
                _canonical_bytes(
                    {
                        "pid": pid,
                        "start_ticks": Path(f"/proc/{pid}/stat")
                        .read_text(encoding="utf-8")
                        .split()[21],
                        "cgroup": cgroup,
                    }
                )
            )
            return {
                "pid": pid,
                "alive": True,
                "identity_sha256": identity,
                "cgroup": cgroup.splitlines()[0].split(":", 2)[-1],
            }

        network = ProviderNetworkHostConfig(
            helper_path=_HELPER,
            helper_sha256=helper_sha256,
            bpf_object_path=_BPF_OBJECT,
            bpf_object_sha256=object_sha256,
            cgroup_root=_CGROUP_ROOT,
            bpffs_root=_BPFFS_ROOT,
            foreign_canary_pid=canary.process.pid,
            foreign_canary_probe=canary_probe,
        )
        service = self._service(
            gate_id=context.gate_id,
            run_ids=(run_id,),
            provider_network_factory=network.service_factory(),
        )
        results = service.run_blocking(self._request())
        contract = self._record_contracts(context.gate_id, service, (run_id,))[0]
        result = results[run_id]
        provider_dir = self.paths.service_control_root / run_id / "provider-network"
        capture = provider_dir / "kernel-connect-capture.json"
        if getattr(result, "status", None) != "completed" or not capture.is_file():
            raise GateExecutionError("PROVIDER-NET did not complete with a capture")
        terminal_proof = _terminal_proof(result)
        manager_terminal = _read_json_object(
            self.paths.service_control_root / run_id / "manager-terminal.json"
        )
        supervision = manager_terminal.get("supervision")
        provider_record = (
            supervision.get("provider_network")
            if isinstance(supervision, Mapping)
            else None
        )
        launch_evidence = (
            provider_record.get("launch")
            if isinstance(provider_record, Mapping)
            else None
        )
        validation = (
            provider_record.get("validation")
            if isinstance(provider_record, Mapping)
            else None
        )
        identity = (
            launch_evidence.get("provider_network_identity")
            if isinstance(launch_evidence, Mapping)
            else None
        )
        capture_payload = _read_json_object(capture)
        expected_report_keys = {
            "schema",
            "ok",
            "classification",
            "identity_sha256",
            "dns_connections",
            "port_443_connections",
            "poison_sink_connections",
            "only_assigned_dfhack_connection",
            "assigned_dfhack_connections",
            "denied_attempts",
            "denied_dns_attempts",
            "denied_443_attempts",
            "denied_poison_attempts",
            "negative_canary_attested",
            "denied_hooks",
            "lost_events",
            "python_guard_attested",
            "kernel_enforcement_attested",
            "provider_calls",
            "provider_cost_usd",
            "provider_events",
            "provider_tokens",
        }
        if (
            not isinstance(validation, Mapping)
            or set(validation) != expected_report_keys
            or validation.get("schema") != "fortgym.provider-network-report/v1"
            or validation.get("ok") is not True
            or not isinstance(identity, Mapping)
            or identity.get("run_id") != run_id
            or identity.get("contract_sha256") != contract.contract_sha256
            or identity.get("assigned_host") != "127.0.0.1"
            or identity.get("assigned_port") != contract.port
            or validation.get("identity_sha256") != identity.get("identity_sha256")
            or capture_payload.get("identity_sha256")
            != validation.get("identity_sha256")
            or capture_payload.get("final") is not True
            or validation.get("assigned_dfhack_connections", 0) < 1
            or validation.get("denied_attempts", 0) < 6
            or validation.get("negative_canary_attested") is not True
            or validation.get("python_guard_attested") is not True
            or validation.get("kernel_enforcement_attested") is not True
            or validation.get("lost_events") != 0
            or validation.get("provider_events") != 0
            or validation.get("provider_tokens") != 0
        ):
            raise GateExecutionError("PROVIDER-NET strict final report differs")
        facts = {
            "dns_connections": validation.get("dns_connections"),
            "port_443_connections": validation.get("port_443_connections"),
            "poison_sink_connections": validation.get("poison_sink_connections"),
            "only_assigned_dfhack_connection": validation.get(
                "only_assigned_dfhack_connection"
            ),
            "provider_calls": validation.get("provider_calls"),
            "provider_cost_usd": validation.get("provider_cost_usd"),
        }
        cleanup_audit = self._internal_double_audit(context.gate_id)
        self._complete_attempt(
            permit,
            {
                "result": _result_summary(result),
                "capture_sha256": _sha256_file(capture),
                "budget": {
                    "provider_calls": validation["provider_calls"],
                    "provider_cost_usd": validation["provider_cost_usd"],
                    "provider_events": validation["provider_events"],
                    "provider_tokens": validation["provider_tokens"],
                },
                "contract_sha256": contract.contract_sha256,
                "terminal_proof": terminal_proof,
            },
            "completed",
        )
        return self._gate_receipt(
            context,
            {
                "result": _result_summary(result),
                "capture_sha256": _sha256_file(capture),
                "final_report": validation,
                "terminal_proof": terminal_proof,
                "cleanup_double_audit": cleanup_audit,
            },
            facts=facts,
        )

    @staticmethod
    def _verified_gate_criteria(
        gate_id: str,
        facts: Mapping[str, Any],
    ) -> tuple[str, ...]:
        plans = [gate for gate in FROZEN_GATE_PLAN if gate.gate_id == gate_id]
        if len(plans) != 1 or any(name not in plans[0].criteria for name in facts):
            raise GateExecutionError("gate facts are not bound to the frozen plan")
        passed: list[str] = []
        for name, expected in plans[0].pass_contract:
            if name not in facts:
                continue
            observed = facts[name]
            if name.endswith("_seconds_lte"):
                valid = (
                    not isinstance(observed, bool)
                    and isinstance(observed, (int, float))
                    and math.isfinite(float(observed))
                    and 0 <= float(observed) <= float(expected)
                )
            elif name.endswith("_delta_gte") or name == "peer_minimum_step":
                valid = (
                    not isinstance(observed, bool)
                    and isinstance(observed, int)
                    and observed >= int(expected)
                )
            elif name == "maximum_fault_bytes":
                valid = (
                    not isinstance(observed, bool)
                    and isinstance(observed, int)
                    and 0 < observed <= int(expected)
                )
            elif isinstance(expected, bool):
                valid = observed is expected
            elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
                valid = (
                    not isinstance(observed, bool)
                    and isinstance(observed, (int, float))
                    and math.isfinite(float(observed))
                    and float(observed) == float(expected)
                )
            else:
                valid = observed == expected
            if valid:
                passed.append(name)
        return tuple(passed)

    def _gate_receipt(
        self,
        context: GateExecutionContext,
        payload: Mapping[str, Any],
        *,
        facts: Mapping[str, Any],
    ) -> VerifiedGateReceipt:
        criteria_passed = self._verified_gate_criteria(context.gate_id, facts)
        path = self._gate_path(context.gate_id, "gate-result.json")
        _write_once_json(
            path,
            {
                "schema": "fortgym.m1b-host-gate-result/v1",
                "batch_id": context.batch_id,
                "gate_id": context.gate_id,
                "acceptance_sha256": context.acceptance_sha256,
                "plan_sha256": context.plan_sha256,
                "criteria_passed": list(criteria_passed),
                "facts": _safe_json(facts),
                "payload": _safe_json(payload),
            },
        )
        return VerifiedGateReceipt(path=path, criteria_passed=criteria_passed)

    def _gate_path(self, gate_id: str, relative: str) -> Path:
        path = self.paths.evidence_root / "gates" / gate_id / relative
        if not path.resolve(strict=False).is_relative_to(self.paths.evidence_root):
            raise HostRunnerError("gate evidence path escaped its batch root")
        return path

    def _cleanup_path(self, context: CleanupPassContext) -> Path:
        name = f"{context.scope}-{context.gate_id or 'batch'}-pass-{context.pass_index}.json"
        return self.paths.evidence_root / "cleanup" / name

    def _read_enospc_mount(
        self, gate_id: str, argv: Sequence[str], *, timeout_seconds: float
    ) -> FaultCommandResult | None:
        """Inspect only planned ENOSPC workspaces, without root or a live binding."""
        normalized = tuple(str(item) for item in argv)
        if not normalized or normalized[0] != "/usr/bin/findmnt":
            return None
        workspaces = {
            str(self.paths.artifacts_root / run_id)
            for run_id in self._planned_ids("ENOSPC", ("target", "peer"))
        }
        if (
            gate_id != "ENOSPC"
            or len(normalized) != 7
            or normalized[:4] != ("/usr/bin/findmnt", "--json", "--bytes", "--target")
            or normalized[4] not in workspaces
            or normalized[5:] != ("--output", "TARGET,FSTYPE,SIZE,OPTIONS,SOURCE")
            or Path(normalized[4]).resolve(strict=False) != Path(normalized[4])
            or not 0 < timeout_seconds <= 10
        ):
            raise GateExecutionError("mount inspection escaped planned ENOSPC workspace")
        return SubprocessFaultCommandRunner().run(
            normalized, timeout_seconds=timeout_seconds
        )

    def _evidence_loader(self, gate_id: str) -> OwnedRunEvidenceLoader:
        # Binding is selected per run inside the broker client. The loader's
        # command runner is replaced on each concrete load by a late resolver.
        backend = self

        class LateFaultRunner:
            def run(
                self, argv: Sequence[str], *, timeout_seconds: float
            ) -> FaultCommandResult:
                mount = backend._read_enospc_mount(
                    gate_id, argv, timeout_seconds=timeout_seconds
                )
                if mount is not None:
                    return mount
                run_id = backend._run_id_from_docker_argv(argv)
                binding = backend._bindings.get(run_id)
                if binding is None:
                    raise GateExecutionError("Docker probe lacks a run binding")
                return BrokeredFaultCommandRunner(
                    broker=backend.broker(gate_id),
                    binding=binding,
                    controller_resolver=backend._runtime_controller_for_docker_argv,
                    inspection_binding_resolver=backend._inspection_binding_for_docker_argv,
                ).run(argv, timeout_seconds=timeout_seconds)

        return OwnedRunEvidenceLoader(
            control_root=self.paths.service_control_root,
            db_path=self.paths.db_path,
            artifacts_root=self.paths.artifacts_root,
            command_runner=LateFaultRunner(),
            # The unprivileged controller cannot read root process environments.
            # This is only preflight: the root broker independently reconstructs
            # cleanup ownership and scans every PID before authorizing unmount.
            run_process_ids=_caller_owned_process_ids,
        )

    def _fault_runner_for_unbound(self, gate_id: str) -> Any:
        backend = self

        class LateRunner:
            def run(
                self, argv: Sequence[str], *, timeout_seconds: float
            ) -> FaultCommandResult:
                mount = backend._read_enospc_mount(
                    gate_id, argv, timeout_seconds=timeout_seconds
                )
                if mount is not None:
                    return mount
                binding = backend._prelaunch_enospc_binding(gate_id)
                return BrokeredFaultCommandRunner(
                    broker=backend.broker(gate_id),
                    binding=binding,
                    controller_resolver=backend._runtime_controller_for_docker_argv,
                    inspection_binding_resolver=backend._inspection_binding_for_docker_argv,
                ).run(argv, timeout_seconds=timeout_seconds)

        return LateRunner()

    def _prelaunch_enospc_binding(self, gate_id: str) -> PublicRunBinding:
        if gate_id != "ENOSPC":
            raise GateExecutionError("prelaunch workspace binding is ENOSPC-only")
        target_id, peer_id = self._planned_ids(gate_id, ("target", "peer"))
        target_path = self.paths.service_control_root / target_id / "launch.json"
        peer_path = self.paths.service_control_root / peer_id / "launch.json"
        target_launch = _read_json_object(target_path)
        peer_launch = _read_json_object(peer_path)
        target_profile = target_launch.get("workspace_fault_profile")
        peer_profile = peer_launch.get("workspace_fault_profile")
        target_contract = target_launch.get("contract")
        peer_contract = peer_launch.get("contract")
        if (
            not isinstance(target_profile, Mapping)
            or target_profile.get("role") != "target"
            or not isinstance(peer_profile, Mapping)
            or peer_profile.get("role") != "peer"
            or not isinstance(target_contract, Mapping)
            or target_contract.get("run_id") != target_id
            or not isinstance(peer_contract, Mapping)
            or peer_contract.get("run_id") != peer_id
        ):
            raise GateExecutionError("ENOSPC prelaunch identities or roles differ")
        permit = self._permit_by_run.get(target_id)
        if (
            permit is None
            or permit.gate_id != gate_id
            or permit.role != "target"
            or permit.completed
        ):
            raise GateExecutionError("ENOSPC target permit is not live")
        attempt_identity = _sha256_file(target_path)
        if not permit.started:
            # This is the exact accounting transition immediately before the
            # brokered mount action. run_reserved observes the same started
            # permit and cannot consume a second runtime slot.
            permit.start(identity_sha256=attempt_identity)
            self._attempt_identity_by_run[target_id] = attempt_identity
        elif self._attempt_identity_by_run.get(target_id) != attempt_identity:
            raise GateExecutionError("ENOSPC prelaunch attempt identity changed")
        contract_sha256 = target_contract.get("contract_sha256")
        rpc = target_contract.get("rpc")
        cotenancy = target_contract.get("cotenancy")
        if (
            not isinstance(contract_sha256, str)
            or not _SHA256_RE.fullmatch(contract_sha256)
            or not isinstance(rpc, Mapping)
            or not isinstance(rpc.get("nonce"), str)
            or not isinstance(cotenancy, Mapping)
            or not isinstance(cotenancy.get("cohort_sha256"), str)
        ):
            raise GateExecutionError("ENOSPC prelaunch public contract differs")
        binding = PublicRunBinding(
            attempt_id=str(permit.attempt_id),
            attempt_identity_sha256=attempt_identity,
            run_id=target_id,
            contract_sha256=contract_sha256,
            nonce_sha256=_sha256_bytes(str(rpc["nonce"]).encode()),
            cohort_sha256=str(cotenancy["cohort_sha256"]),
            port=int(rpc["port"]),
            peer_run_id=peer_id,
            session_sha256=self._run_sessions.get(target_id),
        )
        previous = self._bindings.get(target_id)
        if previous is not None:
            # _record_contracts binds the immutable identity before the fault
            # session/peer exists. Enrich only those previously absent fields;
            # never replace an already bound foreign peer or session.
            if (
                previous.peer_run_id not in (None, binding.peer_run_id)
                or previous.session_sha256 not in (None, binding.session_sha256)
                or dataclasses.replace(
                    previous,
                    peer_run_id=binding.peer_run_id,
                    session_sha256=binding.session_sha256,
                ) != binding
            ):
                raise GateExecutionError("ENOSPC prelaunch binding changed")
        self._bindings[target_id] = binding
        return binding

    def _run_id_from_docker_argv(self, argv: Sequence[str]) -> str:
        normalized = tuple(str(item) for item in argv)
        if not normalized or Path(normalized[0]).name != "docker":
            raise GateExecutionError("run resolver accepts only Docker argv")
        tokens = {item.lower() for item in normalized[1:]}
        matches: set[str] = set()
        for run_id, binding in self._bindings.items():
            exact_identifiers = {
                run_id.lower(),
                f"fortgym-m1b-{run_id}-{binding.contract_sha256[:12]}".lower(),
                f"fortgym.m1b.run_id={run_id}".lower(),
                f"label=fortgym.m1b.run_id={run_id}".lower(),
                f"fortgym.m1b.contract_sha256={binding.contract_sha256}".lower(),
                (
                    f"label=fortgym.m1b.contract_sha256={binding.contract_sha256}"
                ).lower(),
            }
            created = (
                self.paths.service_control_root
                / run_id
                / "attempts"
                / "attempt-0001"
                / "runtime"
                / "container-created.json"
            )
            if created.is_file():
                payload = _read_json_object(created)
                container_id = str(payload.get("container_id") or "").lower()
                if not _CONTAINER_ID_RE.fullmatch(container_id):
                    raise GateExecutionError("durable container identity is invalid")
                exact_identifiers.add(container_id)
            if tokens.intersection(exact_identifiers):
                matches.add(run_id)
        if len(matches) != 1:
            raise GateExecutionError("Docker probe run binding is ambiguous")
        return next(iter(matches))

    def _record_owned_resources(self, gate_id: str, *runs: OwnedRun) -> None:
        resources = self.resources[gate_id]
        for run in runs:
            if run.harness_process_group_id not in resources.process_group_ids:
                resources.process_group_ids.append(run.harness_process_group_id)
        if gate_id == "ENOSPC":
            resources.mount_paths.append(runs[0].workspace)

    def _daemon_restart_callback(
        self, contract: Any, peer_run_id: str, session_sha256: str
    ) -> Callable[[], Mapping[str, Any]]:
        binding = self._binding_for_contract(
            contract,
            peer_run_id=peer_run_id,
            session_sha256=session_sha256,
        )

        def restart() -> Mapping[str, Any]:
            logical = ("/bin/systemctl", "restart", "docker.service")
            result = self.broker("DAEMON-RESTART").execute(
                logical, binding=binding, timeout_seconds=120.0
            )
            if result.returncode != 0:
                raise GateExecutionError("Docker daemon restart failed")
            guard = self.broker("DAEMON-RESTART").execute(
                (
                    "/usr/sbin/nft",
                    "--json",
                    "list",
                    "table",
                    "inet",
                    "fortgym_m1b_outer",
                ),
                binding=binding,
                timeout_seconds=30.0,
                action="verify_outer_guard",
                parameters={},
            )
            if guard.returncode != 0:
                raise GateExecutionError("outer network guard changed after restart")
            return {
                "schema": "fortgym.m1b-daemon-restart-callback/v1",
                "host_controller": True,
                "inside_container": False,
                "invoked": True,
                "outer_guard_verified": True,
                "outer_guard_stdout_sha256": guard.stdout_sha256,
                "outer_guard_broker_evidence_sha256": _sha256_file(guard.evidence_path),
            }

        return restart

    def _ensure_canary(self, gate_id: str) -> None:
        if self._canary is not None:
            if not self._canary_alive(gate_id):
                raise GateExecutionError("existing foreign canary is not live")
            return
        name = (
            "fortgym-m1b-foreign-"
            + hashlib.sha256(self.paths.batch_id.encode("utf-8")).hexdigest()[:16]
        )
        broker = self.broker(gate_id)
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
            "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c",
            "28800",
        )
        created = broker.execute(
            logical,
            binding=None,
            timeout_seconds=60.0,
            action="canary_create",
            parameters={"canary_name": name},
        )
        container_id = created.stdout.strip().lower()
        if created.returncode != 0 or not _CONTAINER_ID_RE.fullmatch(container_id):
            raise GateExecutionError("foreign Docker canary creation failed")
        inspected = broker.execute(
            ("docker", "inspect", "--type", "container", name),
            binding=None,
            timeout_seconds=30.0,
            action="canary_inspect",
            parameters={"canary_name": name},
        )
        if inspected.returncode != 0:
            raise GateExecutionError("foreign Docker canary initial inspect failed")
        container_state_sha256 = _canary_inspect_state_sha256(
            inspected.stdout,
            name=name,
            container_id=container_id,
        )
        workspace = self.paths.state_root / "canary" / self.paths.batch_id
        workspace.mkdir(parents=True, exist_ok=False, mode=0o700)
        process = subprocess.Popen(
            ("/bin/sleep", "28800"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
        identity = ProtectedCanary(
            name=name,
            container_id=container_id,
            process_ids=(process.pid,),
            workspace=workspace,
        )
        process_start_ticks = int(
            Path(f"/proc/{process.pid}/stat").read_text(encoding="utf-8").split()[21]
        )
        workspace_metadata = workspace.lstat()
        creation_receipt = self.paths.evidence_root / "batch-canary-created.json"
        _write_once_json(
            creation_receipt,
            {
                "schema": "fortgym.m1b-batch-canary-created/v1",
                "batch_id": self.paths.batch_id,
                "name": name,
                "container_id": container_id,
                "process_id": process.pid,
                "process_start_ticks": process_start_ticks,
                "workspace": str(workspace),
                "workspace_device": workspace_metadata.st_dev,
                "workspace_inode": workspace_metadata.st_ino,
                "container_state_sha256": container_state_sha256,
                "broker_evidence_sha256": _sha256_file(created.evidence_path),
                "inspect_broker_evidence_sha256": _sha256_file(inspected.evidence_path),
            },
        )
        self._canary = ForeignCanaryState(
            name=name,
            container_id=container_id,
            process=process,
            workspace=workspace,
            identity=identity,
            process_start_ticks=process_start_ticks,
            workspace_device=workspace_metadata.st_dev,
            workspace_inode=workspace_metadata.st_ino,
            container_state_sha256=container_state_sha256,
            creation_broker_evidence=created.evidence_path,
        )

    def _canary_alive(self, gate_id: str) -> bool:
        canary = self._canary
        if canary is None:
            return False
        if canary.process.poll() is not None or not canary.workspace.is_dir():
            return False
        try:
            start_ticks = int(
                Path(f"/proc/{canary.process.pid}/stat")
                .read_text(encoding="utf-8")
                .split()[21]
            )
            workspace = canary.workspace.lstat()
        except (OSError, ValueError, IndexError):
            return False
        if (
            start_ticks != canary.process_start_ticks
            or workspace.st_dev != canary.workspace_device
            or workspace.st_ino != canary.workspace_inode
        ):
            return False
        logical = ("docker", "inspect", "--type", "container", canary.name)
        try:
            result = self.broker(gate_id).execute(
                logical,
                binding=None,
                timeout_seconds=30.0,
                action="canary_inspect",
                parameters={"canary_name": canary.name},
            )
        except Exception:  # noqa: BLE001 - any broker/probe failure means changed
            return False
        if result.returncode != 0:
            return False
        try:
            state_sha256 = _canary_inspect_state_sha256(
                result.stdout,
                name=canary.name,
                container_id=canary.container_id,
            )
        except GateExecutionError:
            return False
        return state_sha256 == canary.container_state_sha256

    def destroy_canary(self) -> Mapping[str, Any]:
        canary = self._canary
        if canary is None:
            return {"present": False, "removed": True}
        inspected = self.broker("CLEANUP").execute(
            ("docker", "inspect", "--type", "container", canary.name),
            binding=None,
            timeout_seconds=30.0,
            action="canary_inspect",
            parameters={"canary_name": canary.name},
        )
        if inspected.returncode != 0:
            raise GateExecutionError("foreign Docker canary pre-removal inspect failed")
        pre_removal_state_sha256 = _canary_inspect_state_sha256(
            inspected.stdout,
            name=canary.name,
            container_id=canary.container_id,
        )
        if pre_removal_state_sha256 != canary.container_state_sha256:
            raise GateExecutionError("foreign Docker canary changed before removal")
        logical = ("docker", "rm", "--force", canary.name)
        removed = self.broker("CLEANUP").execute(
            logical,
            binding=None,
            timeout_seconds=60.0,
            action="canary_remove",
            parameters={"canary_name": canary.name},
        )
        if removed.returncode != 0:
            raise GateExecutionError("foreign Docker canary removal failed")
        absence_logical = (
            "docker",
            "ps",
            "--all",
            "--no-trunc",
            "--filter",
            f"name=^/{canary.name}$",
            "--format",
            "{{.ID}}",
        )
        absent = self.broker("CLEANUP").execute(
            absence_logical,
            binding=None,
            timeout_seconds=30.0,
            action="canary_absence",
            parameters={"canary_name": canary.name},
        )
        _validate_canary_absence_receipt(absent, name=canary.name)
        try:
            os.killpg(canary.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            canary.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            os.killpg(canary.process.pid, signal.SIGKILL)
            canary.process.wait(timeout=5.0)
        canary.workspace.rmdir()
        if canary.process.poll() is None or canary.workspace.exists():
            raise GateExecutionError("foreign host canary residue remains")
        self._canary = None
        return {
            "present": True,
            "removed": True,
            "name": canary.name,
            "container_id": canary.container_id,
            "container_absent": True,
            "container_absence_returncode": absent.returncode,
            "process_id": canary.process.pid,
            "process_start_ticks": canary.process_start_ticks,
            "process_absent": canary.process.poll() is not None,
            "workspace": str(canary.workspace),
            "workspace_absent": not canary.workspace.exists(),
            "initial_container_state_sha256": canary.container_state_sha256,
            "pre_removal_container_state_sha256": pre_removal_state_sha256,
            "pre_removal_broker_evidence_sha256": _sha256_file(inspected.evidence_path),
            "creation_broker_evidence_sha256": _sha256_file(
                canary.creation_broker_evidence
            ),
            "removal_broker_evidence_sha256": _sha256_file(removed.evidence_path),
            "absence_broker_evidence_sha256": _sha256_file(absent.evidence_path),
        }

    def _residue_command_probe(
        self,
        gate_id: str,
    ) -> Callable[[Sequence[str]], tuple[int, str, str]]:
        backend = self

        def probe(argv: Sequence[str]) -> tuple[int, str, str]:
            normalized = tuple(str(item) for item in argv)
            if normalized and Path(normalized[0]).name == "ss":
                completed = subprocess.run(
                    normalized,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    timeout=15.0,
                )
                return completed.returncode, completed.stdout, completed.stderr
            if normalized[:2] == ("docker", "ps"):
                run_filters = [
                    token.split("=", 2)[-1]
                    for token in normalized
                    if token.startswith("label=fortgym.m1b.run_id=")
                ]
                if len(run_filters) != 1:
                    return 64, "", "run filter differs"
                run_id = run_filters[0]
                binding = backend._bindings.get(run_id)
                if binding is None:
                    return 64, "", "run binding absent"
                permit = backend._permit_by_run.get(run_id)
                if permit is None:
                    return 64, "", "run permit absent"
                if permit.kind.value == "non_runtime_conflict":
                    container_name = (
                        f"fortgym-m1b-{binding.run_id}-{binding.contract_sha256[:12]}"
                    )
                    result = backend.broker(gate_id).execute(
                        (
                            "docker",
                            "inspect",
                            "--type",
                            "container",
                            container_name,
                        ),
                        binding=binding,
                        timeout_seconds=30.0,
                        action="docker_container_inspect",
                        parameters={"identifier": container_name},
                    )
                    if result.returncode == 0:
                        return 1, "", "non-runtime contender container exists"
                    # The root broker admits this nonzero result only after it
                    # has authenticated Docker's exact not-found response for
                    # the one frozen contender identity.  Translate that
                    # attested absence into the residue auditor's rc=0/empty
                    # inventory contract; every other Docker error has already
                    # failed closed in the broker.
                    return 0, "", ""
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
                result = backend.broker(gate_id).execute(
                    logical,
                    binding=binding,
                    timeout_seconds=30.0,
                    action="docker_managed_list",
                    parameters={},
                )
                return result.returncode, result.stdout, result.stderr
            if normalized[:4] == ("docker", "inspect", "--type", "container"):
                canary = backend._canary
                if canary is None or normalized[4] != canary.container_id:
                    return 64, "", "foreign container differs"
                result = backend.broker(gate_id).execute(
                    ("docker", "inspect", "--type", "container", canary.name),
                    binding=None,
                    timeout_seconds=30.0,
                    action="canary_inspect",
                    parameters={"canary_name": canary.name},
                )
                return result.returncode, result.stdout, result.stderr
            return 64, "", "probe command is not allowlisted"

        return probe


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen provider-free Fort Gym M1b live acceptance matrix"
    )
    parser.add_argument("--private-test-mode", action="store_true")
    parser.add_argument(
        "--two-fort-diagnostic", action="store_true",
        help="Run only DF-KILL's target/peer pair; omitted gates keep full M1b NO-GO",
    )
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--packet-root", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    return parser


def _finalize_root_broker_attestation(
    *,
    paths: HostPaths,
    backend: LinuxGateBackend,
    controller_seal_sha256: str,
    post_seal_cleanup_path: Path,
) -> tuple[Path, str, Path, Path]:
    post_seal_cleanup_sha256 = _sha256_file(post_seal_cleanup_path)
    logical = (
        "fortgym-root-broker",
        "attest-broker-evidence",
        paths.batch_id,
        controller_seal_sha256,
        post_seal_cleanup_sha256,
    )
    receipt = backend.broker("CLEANUP").execute(
        logical,
        binding=None,
        timeout_seconds=60.0,
        action="attest_broker_evidence",
        parameters={
            "controller_seal_sha256": controller_seal_sha256,
            "post_seal_cleanup_sha256": post_seal_cleanup_sha256,
        },
    )
    if receipt.returncode != 0 or receipt.stderr != "":
        raise HostRunnerError("root broker final attestation failed")
    try:
        result = json.loads(receipt.stdout)
    except json.JSONDecodeError as exc:
        raise HostRunnerError(
            "root broker final attestation result is invalid"
        ) from exc
    expected_path = (
        _ROOT_EVIDENCE_ROOT / "batches" / paths.batch_id / "broker-attestation.json"
    )
    if (
        not isinstance(result, Mapping)
        or set(result) != {"schema", "ok", "batch_id", "path", "sha256"}
        or result.get("schema") != "fortgym.m1b-root-broker-attestation-result/v1"
        or result.get("ok") is not True
        or result.get("batch_id") != paths.batch_id
        or result.get("path") != str(expected_path)
        or not _SHA256_RE.fullmatch(str(result.get("sha256") or ""))
    ):
        raise HostRunnerError("root broker final attestation identity differs")
    attestation_sha256 = str(result["sha256"])
    reference_path = paths.evidence_root / "root-broker-attestation-reference.json"
    _write_once_json(
        reference_path,
        {
            "schema": "fortgym.m1b-root-broker-attestation-reference/v1",
            "batch_id": paths.batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "controller_seal_sha256": controller_seal_sha256,
            "post_seal_cleanup_path": str(post_seal_cleanup_path),
            "post_seal_cleanup_sha256": post_seal_cleanup_sha256,
            "root_attestation_path": str(expected_path),
            "root_attestation_sha256": attestation_sha256,
            "broker_request_id": receipt.request_id,
            "broker_public_receipt_path": str(receipt.evidence_path),
            "broker_public_receipt_sha256": _sha256_file(receipt.evidence_path),
        },
    )
    return (
        expected_path,
        attestation_sha256,
        reference_path,
        receipt.evidence_path,
    )


def run_live_acceptance(
    paths: HostPaths, *, two_fort_diagnostic: bool = False
) -> HostLiveAcceptanceOutcome:
    validate_host_policy(paths)
    inputs = prepare_inputs(paths)
    backend = LinuxGateBackend(paths=paths)
    adapter = LinuxM1BHostAdapter(backend, two_fort_diagnostic=two_fort_diagnostic)
    backend._ensure_canary("BATCH-CANARY")

    def privilege_resolver(
        _argv: Sequence[str],
    ) -> tuple[RootBrokerClient, PublicRunBinding | None]:
        gate = backend._active_gate
        if gate is None:
            raise HostRunnerError("privileged command has no active gate")
        bindings = [
            binding
            for run_id, binding in backend._bindings.items()
            if run_id in backend.resources[gate].run_ids
        ]
        if len(bindings) != 1:
            raise HostRunnerError("privileged command run binding is ambiguous")
        return backend.broker(gate), bindings[0]

    authorization = authorize_private_m1b_live_acceptance(
        test_mode=True,
        batch_id=paths.batch_id,
        evidence_root=paths.evidence_root,
        contract_path=inputs.contract_path,
    )
    controller = LiveAcceptanceBatchController(
        authorization=authorization,
        adapter=adapter,
        privileged_commands=BrokerPrivilegedCommandExecutor(privilege_resolver),
        source_manifest=inputs.source_manifest,
        local_credits=inputs.local_credits,
    )
    outcome = controller.run()
    if not outcome.seal_path.is_file():
        raise HostRunnerError("controller returned without its exact seal")
    cleanup = backend.destroy_canary()
    cleanup_path = paths.evidence_root / "post-seal-host-cleanup.json"
    _write_once_json(
        cleanup_path,
        {
            "schema": "fortgym.m1b-post-seal-host-cleanup/v1",
            "batch_id": paths.batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "controller_seal_sha256": _sha256_file(outcome.seal_path),
            "cleanup": cleanup,
        },
    )
    controller_seal_sha256 = _sha256_file(outcome.seal_path)
    (
        broker_attestation_path,
        broker_attestation_sha256,
        broker_attestation_reference_path,
        broker_attestation_receipt_path,
    ) = _finalize_root_broker_attestation(
        paths=paths,
        backend=backend,
        controller_seal_sha256=controller_seal_sha256,
        post_seal_cleanup_path=cleanup_path,
    )
    return HostLiveAcceptanceOutcome(
        controller=outcome,
        post_seal_cleanup_path=cleanup_path,
        post_seal_cleanup_sha256=_sha256_file(cleanup_path),
        broker_attestation_path=broker_attestation_path,
        broker_attestation_sha256=broker_attestation_sha256,
        broker_attestation_reference_path=broker_attestation_reference_path,
        broker_attestation_receipt_path=broker_attestation_receipt_path,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.private_test_mode is not True:
        raise SystemExit("--private-test-mode is required literally")
    paths = HostPaths(
        batch_id=args.batch_id,
        packet_root=args.packet_root,
        state_root=args.state_root,
    )
    outcome = (
        run_live_acceptance(paths, two_fort_diagnostic=True)
        if args.two_fort_diagnostic else run_live_acceptance(paths)
    )
    print(
        json.dumps(
            {
                "schema": "fortgym.m1b-host-runner-outcome/v1",
                "batch_id": outcome.batch_id,
                "decision": outcome.decision.value,
                "real_runtime_attempts_started": outcome.real_runtime_attempts_started,
                "real_runtime_attempts_completed": outcome.real_runtime_attempts_completed,
                "non_runtime_attempts_started": outcome.non_runtime_attempts_started,
                "non_runtime_attempts_completed": outcome.non_runtime_attempts_completed,
                "gate_results_path": str(outcome.gate_results_path),
                "decision_path": str(outcome.decision_path),
                "evidence_manifest_path": str(outcome.evidence_manifest_path),
                "seal_path": str(outcome.seal_path),
                "post_seal_cleanup_path": str(outcome.post_seal_cleanup_path),
                "post_seal_cleanup_sha256": outcome.post_seal_cleanup_sha256,
                "broker_attestation_path": str(outcome.broker_attestation_path),
                "broker_attestation_sha256": outcome.broker_attestation_sha256,
                "broker_attestation_reference_path": str(
                    outcome.broker_attestation_reference_path
                ),
                "broker_attestation_reference_sha256": _sha256_file(
                    outcome.broker_attestation_reference_path
                ),
                "broker_attestation_receipt_path": str(
                    outcome.broker_attestation_receipt_path
                ),
                "broker_attestation_receipt_sha256": _sha256_file(
                    outcome.broker_attestation_receipt_path
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - live host entrypoint
    raise SystemExit(main())
