"""Exact, provider-free Docker lifecycle control for M1b DF runtimes.

The controller owns only the DF/DFHack container.  ``ProcessSupervisor`` owns
the host port lease and harness process group, and calls :meth:`prepare` only
after acquiring that lease.  Every Docker command is an argument vector run
without a shell, and the command runner is injectable so the ownership and
failure contracts can be tested without a Docker daemon.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .runtime_contract import RuntimeContract

_CONTAINER_ENTRYPOINT = "/opt/fortgym-m1b/runtime_entrypoint.sh"
_CONTAINER_EVIDENCE_DIR = "/artifacts"
_STARTUP_TERMINAL_NAME = "startup-terminal.json"
_OOM_HOLD_READY_NAME = "pre-readiness-oom-hold-ready.json"
_OOM_RELEASE_MARKER_NAME = "pre-readiness-oom-release"
_OOM_EXIT_ACK_MARKER_NAME = "pre-readiness-oom-exit-ack"
_OOM_RELEASE_EVIDENCE_NAME = "pre-readiness-oom-release.json"
_MEMORY_LIMIT = "4g"
_MEMORY_BYTES = 4 * 1024 * 1024 * 1024
_OOM_TEST_MEMORY_LIMIT = "256m"
_OOM_TEST_MEMORY_BYTES = 256 * 1024 * 1024
_PIDS_LIMIT = 256
_MAX_CAPTURE_BYTES = 2 * 1024 * 1024
_CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CPUSET_RE = re.compile(r"^[0-9]+(?:[-,][0-9]+)*$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_NOT_FOUND_MARKERS = ("no such object", "no such container", "no such image")

MANAGED_LABEL = "fortgym.m1b.managed"
RUN_ID_LABEL = "fortgym.m1b.run_id"
CONTRACT_LABEL = "fortgym.m1b.contract_sha256"
COHORT_LABEL = "fortgym.m1b.cohort_sha256"
IMAGE_LABEL = "fortgym.m1b.image_manifest_sha256"
IMAGE_CONFIG_LABEL = "fortgym.m1b.image_config_sha256"
IMAGE_ARCHIVE_LABEL = "fortgym.m1b.image_archive_sha256"
ENTRYPOINT_LABEL = "fortgym.m1b.entrypoint_sha256"
TEST_FAULT_LABEL = "fortgym.m1b.test_fault"
FAULT_PROFILE_LABEL = "fortgym.m1b.fault_profile"


class RuntimeControllerError(RuntimeError):
    """Base class for bounded runtime-controller failures."""


class RuntimeCommandError(RuntimeControllerError):
    """A required shell-free command could not be executed or decoded."""


class RuntimeStartError(RuntimeControllerError):
    """The exact runtime could not be started."""


class RuntimeContainerCreateFailure(RuntimeStartError):
    """A durably evidenced Docker create/start failure."""

    terminal_code = "container_create_failure"

    def __init__(self, *, evidence: Mapping[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__("Docker container create/start failed")


class RuntimeAttestationError(RuntimeControllerError):
    """The running runtime failed identity, listener, or map attestation."""


class RuntimeReadinessTimeout(RuntimeAttestationError):
    """A durably evidenced RPC-readiness timeout."""

    terminal_code = "rpc_readiness_timeout"

    def __init__(self, *, injected: bool, evidence: Mapping[str, Any]) -> None:
        self.injected = injected
        self.evidence = dict(evidence)
        qualifier = "injected " if injected else ""
        super().__init__(f"{qualifier}RPC readiness timeout")


class RuntimeMapReadinessTimeout(RuntimeAttestationError):
    """A durably evidenced map-readiness timeout."""

    terminal_code = "map_readiness_timeout"

    def __init__(self, *, evidence: Mapping[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__("DFHack map readiness timeout")


class RuntimeOomPreReadiness(RuntimeAttestationError):
    """An exact OOM test container exited 137 before harness readiness.

    This is routing evidence, not a final ``runtime_oom`` classification.  The
    latter still requires the strict external fault-driver journal proving the
    cgroup counter delta, peer health, and host/container identity.
    """

    terminal_code = "oom_256m_pre_readiness"

    def __init__(self, *, evidence: Mapping[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__("exact oom_256m runtime exited 137 before readiness")


class RuntimeOomHoldFailure(RuntimeAttestationError):
    """A typed, non-credit failure in the authorized held OOM lifecycle."""

    terminal_code = "oom_256m_hold_failure"

    def __init__(self, *, evidence: Mapping[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__(
            f"held oom_256m lifecycle failed at {self.evidence.get('stage', 'unknown')}"
        )


class RuntimeOwnershipError(RuntimeControllerError):
    """A container did not prove that this controller owns it."""


class RuntimeCleanupError(RuntimeControllerError):
    """Scoped cleanup did not prove absence of all run resources."""


class RuntimeTestFault(str, Enum):
    """Explicit, test-only runtime faults; never sourced from ambient env."""

    SUPPRESS_RPC_READINESS = "suppress_rpc_readiness"


class RuntimeFaultProfile(str, Enum):
    """Explicit create-time test profile for a frozen runtime fault gate."""

    OOM_256M = "oom_256m"


@dataclass(frozen=True)
class CommandResult:
    """Bounded text result from one shell-free host command."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Injected command boundary used by :class:`DockerRuntimeController`."""

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> CommandResult: ...


class ArchiveMemberReader(Protocol):
    """Shell-free reader for exact small members of a compressed OCI tar."""

    def __call__(
        self,
        archive_path: Path,
        members: frozenset[str],
        *,
        timeout_seconds: float,
    ) -> Mapping[str, bytes]: ...


class PreReadinessOomMonitor(Protocol):
    """Injected host monitor for the no-harness OOM target lifecycle."""

    def arm(self, container_created: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def finalize(self, pre_readiness_oom: Mapping[str, Any]) -> Mapping[str, Any]: ...


class SubprocessCommandRunner:
    """Production shell-free command runner."""

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> CommandResult:
        normalized = tuple(str(item) for item in argv)
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
            raise RuntimeCommandError(
                f"command failed before completion: {normalized[0]}: {type(exc).__name__}"
            ) from exc
        return CommandResult(
            argv=normalized,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class ZstdTarArchiveReader:
    """Stream a Zstandard tar through Python without extraction or a shell."""

    def __init__(self, zstd_executable: str = "zstd") -> None:
        if not zstd_executable or "\0" in zstd_executable:
            raise ValueError("zstd_executable must be non-empty and NUL-free")
        self.zstd_executable = zstd_executable

    def __call__(
        self,
        archive_path: Path,
        members: frozenset[str],
        *,
        timeout_seconds: float,
    ) -> Mapping[str, bytes]:
        if not 0 < timeout_seconds <= 3_600:
            raise ValueError("archive timeout_seconds must be 0-3600")
        if not members or any(
            not member
            or member.startswith(("/", "../"))
            or "/../" in member
            or "\0" in member
            for member in members
        ):
            raise RuntimeStartError("OCI archive member selection is invalid")
        try:
            process = subprocess.Popen(
                (
                    self.zstd_executable,
                    "-dc",
                    "--",
                    str(archive_path),
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as exc:
            raise RuntimeStartError(
                "preserved OCI archive decompressor could not start"
            ) from exc
        assert process.stdout is not None
        assert process.stderr is not None
        timed_out = threading.Event()

        def kill_on_timeout() -> None:
            timed_out.set()
            try:
                process.kill()
            except OSError:
                pass

        timer = threading.Timer(timeout_seconds, kill_on_timeout)
        timer.daemon = True
        timer.start()
        selected: dict[str, bytes] = {}
        member_count = 0
        declared_size = 0
        read_error: BaseException | None = None
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    member_count += 1
                    declared_size += max(0, member.size)
                    if member_count > 100_000 or declared_size > 16 * 1024**3:
                        raise RuntimeStartError(
                            "preserved OCI archive exceeds its traversal bound"
                        )
                    if member.name not in members:
                        continue
                    if member.name in selected or not member.isfile():
                        raise RuntimeStartError(
                            "preserved OCI archive member is duplicate or not regular"
                        )
                    if member.size <= 0 or member.size > _MAX_CAPTURE_BYTES:
                        raise RuntimeStartError(
                            "preserved OCI archive member has an invalid size"
                        )
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise RuntimeStartError(
                            "preserved OCI archive member cannot be read"
                        )
                    data = handle.read(_MAX_CAPTURE_BYTES + 1)
                    if len(data) != member.size:
                        raise RuntimeStartError(
                            "preserved OCI archive member size differs"
                        )
                    selected[member.name] = data
        except (OSError, tarfile.TarError, RuntimeStartError) as exc:
            read_error = exc
        finally:
            try:
                process.stdout.close()
            except OSError:
                pass
            try:
                returncode = process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=5.0)
            timer.cancel()
            stderr = process.stderr.read(_MAX_CAPTURE_BYTES + 1)
            process.stderr.close()
        if timed_out.is_set():
            raise RuntimeStartError("preserved OCI archive verification timed out")
        if read_error is not None:
            if isinstance(read_error, RuntimeStartError):
                raise read_error
            raise RuntimeStartError(
                "preserved OCI archive is not a valid tar"
            ) from read_error
        if returncode != 0:
            message = " ".join(stderr.decode("utf-8", errors="replace").split())[:400]
            raise RuntimeStartError(
                f"preserved OCI archive decompression failed: {message or returncode}"
            )
        missing = members.difference(selected)
        if missing:
            raise RuntimeStartError(
                "preserved OCI archive lacks required members: "
                + ", ".join(sorted(missing))
            )
        return selected


def _absolute_path(name: str, value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute() or "\0" in str(path):
        raise ValueError(f"{name} must be an absolute NUL-free path")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_error(result: CommandResult) -> str:
    message = " ".join((result.stderr or result.stdout).split())
    return message[:500] or f"return code {result.returncode}"


def _is_not_found(result: CommandResult) -> bool:
    if result.returncode == 0:
        return False
    message = f"{result.stderr}\n{result.stdout}".lower()
    return any(marker in message for marker in _NOT_FOUND_MARKERS)


def _bounded_bytes(value: str, *, maximum: int = _MAX_CAPTURE_BYTES) -> bytes:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= maximum:
        return encoded
    marker = b"\n[fort-gym capture truncated to tail]\n"
    return marker + encoded[-(maximum - len(marker)) :]


def _atomic_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            # Apply before publication, independent of the host's strict umask.
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class DockerRuntimeController:
    """Lifecycle controller for one checksum-pinned M1b DF runtime.

    The DF container is always provider-free, including when the separately
    supervised harness contract has an explicitly gated provider policy.
    """

    def __init__(
        self,
        contract: RuntimeContract,
        *,
        entrypoint_path: Path | str,
        evidence_dir: Path | str | None = None,
        cpuset_cpus: str | None = None,
        runner: CommandRunner | None = None,
        docker_executable: str = "docker",
        zstd_executable: str = "zstd",
        archive_member_reader: ArchiveMemberReader | None = None,
        image_archive_path: Path | str | None = None,
        listener_executable: str = "ss",
        readiness_attempts: int = 330,
        readiness_interval_seconds: float = 1.0,
        allow_test_faults: bool = False,
        test_fault: RuntimeTestFault | None = None,
        allow_test_fault_profile: bool = False,
        fault_profile: RuntimeFaultProfile | None = None,
        pre_readiness_oom_monitor: PreReadinessOomMonitor | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if contract.backend != "dfhack":
            raise ValueError("Docker runtime controller requires backend='dfhack'")
        if not docker_executable or "\0" in docker_executable:
            raise ValueError("docker_executable must be non-empty and NUL-free")
        if not zstd_executable or "\0" in zstd_executable:
            raise ValueError("zstd_executable must be non-empty and NUL-free")
        if not listener_executable or "\0" in listener_executable:
            raise ValueError("listener_executable must be non-empty and NUL-free")
        if (
            isinstance(readiness_attempts, bool)
            or not isinstance(readiness_attempts, int)
            or readiness_attempts <= 0
        ):
            raise ValueError("readiness_attempts must be a positive integer")
        if readiness_interval_seconds < 0:
            raise ValueError("readiness_interval_seconds cannot be negative")
        if not isinstance(allow_test_faults, bool):
            raise TypeError("allow_test_faults must be a boolean")
        if test_fault is not None and not isinstance(test_fault, RuntimeTestFault):
            raise TypeError("test_fault must be a RuntimeTestFault or None")
        if test_fault is not None and not allow_test_faults:
            raise ValueError("test faults require explicit test-only authorization")
        if not isinstance(allow_test_fault_profile, bool):
            raise TypeError("allow_test_fault_profile must be a boolean")
        if fault_profile is not None and not isinstance(
            fault_profile, RuntimeFaultProfile
        ):
            raise TypeError("fault_profile must be a RuntimeFaultProfile or None")
        if fault_profile is not None and not allow_test_fault_profile:
            raise ValueError("fault profiles require explicit test-only authorization")
        if pre_readiness_oom_monitor is not None and (
            allow_test_fault_profile is not True
            or fault_profile is not RuntimeFaultProfile.OOM_256M
        ):
            raise ValueError(
                "pre-readiness OOM monitor requires the authorized oom_256m profile"
            )
        if pre_readiness_oom_monitor is not None and (
            not callable(getattr(pre_readiness_oom_monitor, "arm", None))
            or not callable(getattr(pre_readiness_oom_monitor, "finalize", None))
        ):
            raise TypeError("pre_readiness_oom_monitor has an invalid interface")

        entrypoint = _absolute_path("entrypoint_path", entrypoint_path).resolve()
        if not entrypoint.is_file():
            raise ValueError("entrypoint_path must name an existing regular file")
        selected_evidence = (
            contract.control_root / contract.run_id / "runtime"
            if evidence_dir is None
            else _absolute_path("evidence_dir", evidence_dir)
        ).resolve()
        run_control_root = (contract.control_root / contract.run_id).resolve()
        try:
            evidence_relative = selected_evidence.relative_to(run_control_root)
        except ValueError as exc:
            raise ValueError(
                "evidence_dir must be inside the run control root"
            ) from exc
        if not evidence_relative.parts:
            raise ValueError(
                "evidence_dir must be below, not equal to, the run control root"
            )
        if cpuset_cpus is not None:
            cpuset_cpus = str(cpuset_cpus).strip()
            if not _CPUSET_RE.fullmatch(cpuset_cpus):
                raise ValueError("cpuset_cpus must be a bounded numeric CPU set")
        selected_archive: Path | None = None
        if image_archive_path is not None:
            selected_archive = _absolute_path(
                "image_archive_path", image_archive_path
            ).resolve()
            if not selected_archive.is_file():
                raise ValueError(
                    "image_archive_path must name an existing regular file"
                )

        self.contract = contract
        self.entrypoint_path = entrypoint
        self.evidence_dir = selected_evidence
        self.cpuset_cpus = cpuset_cpus
        self.runner = runner or SubprocessCommandRunner()
        self.docker_executable = docker_executable
        self.zstd_executable = zstd_executable
        self._archive_member_reader = archive_member_reader or ZstdTarArchiveReader(
            zstd_executable
        )
        self.image_archive_path = selected_archive
        self.listener_executable = listener_executable
        self.readiness_attempts = readiness_attempts
        self.readiness_interval_seconds = float(readiness_interval_seconds)
        self.allow_test_faults = allow_test_faults
        self.test_fault = test_fault
        self.allow_test_fault_profile = allow_test_fault_profile
        self.fault_profile = fault_profile
        self.pre_readiness_oom_monitor = pre_readiness_oom_monitor
        self._sleep = sleep
        self._entrypoint_sha256 = _sha256_file(entrypoint)
        self._container_id: str | None = None
        self._preserve_shared_listener_without_container = False
        self._resolved_image_reference: str | None = None
        self._image_resolution: dict[str, Any] | None = None
        self._oom_monitor_armed = False
        self._oom_release_written = False
        self._oom_monitor_arm_result: dict[str, Any] | None = None

    @property
    def container_name(self) -> str:
        return (
            f"fortgym-m1b-{self.contract.run_id}-{self.contract.contract_sha256[:12]}"
        )

    def configure_nonruntime_port_conflict_cleanup(self) -> None:
        """Permit one peer-owned loopback listener when this runtime never existed.

        The M1b PORT-2 loser is deliberately a non-runtime attempt: it loses the
        port lease before ``prepare`` and must not treat the winning peer's
        listener as its own residue. This programmatic switch is never read
        from environment or API input, and cleanup still fails closed if this
        controller's exact container exists or the listener is non-loopback.
        """

        if self._container_id is not None:
            raise RuntimeCleanupError(
                "shared-listener cleanup cannot follow runtime creation"
            )
        self._preserve_shared_listener_without_container = True

    @property
    def image_reference(self) -> str:
        return f"sha256:{self.contract.image_manifest_sha256}"

    @property
    def image_config_reference(self) -> str:
        return f"sha256:{self.contract.image_config_sha256}"

    @property
    def resolved_image_reference(self) -> str:
        """Return the exact local image reference selected during prepare."""

        return self._resolved_image_reference or self.image_reference

    @property
    def memory_limit(self) -> str:
        if self.fault_profile is RuntimeFaultProfile.OOM_256M:
            return _OOM_TEST_MEMORY_LIMIT
        return _MEMORY_LIMIT

    @property
    def memory_bytes(self) -> int:
        if self.fault_profile is RuntimeFaultProfile.OOM_256M:
            return _OOM_TEST_MEMORY_BYTES
        return _MEMORY_BYTES

    @property
    def expected_labels(self) -> dict[str, str]:
        labels = {
            MANAGED_LABEL: "true",
            RUN_ID_LABEL: self.contract.run_id,
            CONTRACT_LABEL: self.contract.contract_sha256,
            COHORT_LABEL: self.contract.cohort_digest,
            IMAGE_LABEL: self.contract.image_manifest_sha256,
            IMAGE_CONFIG_LABEL: self.contract.image_config_sha256,
            IMAGE_ARCHIVE_LABEL: self.contract.image_archive_sha256,
            ENTRYPOINT_LABEL: self._entrypoint_sha256,
        }
        if self.test_fault is not None:
            labels[TEST_FAULT_LABEL] = self.test_fault.value
        if self.fault_profile is not None:
            labels[FAULT_PROFILE_LABEL] = self.fault_profile.value
        return labels

    def container_environment(self) -> dict[str, str]:
        """Translate only the exact child identity required by the DF runtime."""

        child = self.contract.child_environment()
        required = {
            "DFHACK_PORT": "DFHACK_PORT",
            "FORT_GYM_RUN_ID": "FORTGYM_RUN_ID",
            "FORT_GYM_RUN_NONCE": "FORTGYM_RUN_NONCE",
            "FORT_GYM_RUN_CONTRACT_SHA256": "FORTGYM_CONTRACT_SHA256",
            "FORT_GYM_RUNTIME_SAVE": "FORTGYM_RUNTIME_SAVE",
            "FORT_GYM_RUNTIME_PREPARED": "FORTGYM_RUNTIME_PREPARED",
            "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256": (
                "FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256"
            ),
            "FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256": (
                "FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256"
            ),
            "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256": (
                "FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256"
            ),
            "FORT_GYM_EXPECTED_SEED_TREE_SHA256": ("FORTGYM_EXPECTED_SEED_TREE_SHA256"),
            "FORT_GYM_EXPECTED_SEED_WORLD_SHA256": (
                "FORTGYM_EXPECTED_SEED_WORLD_SHA256"
            ),
        }
        translated: dict[str, str] = {}
        for child_name, container_name in required.items():
            value = child.get(child_name)
            if not value:
                raise RuntimeStartError(f"runtime contract lacks {child_name}")
            translated[container_name] = value
        if self.test_fault is RuntimeTestFault.SUPPRESS_RPC_READINESS:
            translated["FORTGYM_ALLOW_TEST_FAULTS"] = "1"
            translated["FORTGYM_TEST_SUPPRESS_RPC_READY"] = "1"
        if self.fault_profile is RuntimeFaultProfile.OOM_256M:
            translated["FORTGYM_ALLOW_TEST_FAULT_PROFILE"] = "1"
            translated["FORTGYM_FAULT_PROFILE"] = RuntimeFaultProfile.OOM_256M.value
            translated["FORTGYM_COHORT_SHA256"] = self.contract.cohort_digest
        return translated

    def docker_run_argv(self) -> tuple[str, ...]:
        """Return the exact, shell-free Docker create/start command."""

        return self._docker_launch_argv("run")

    def docker_create_argv(self) -> tuple[str, ...]:
        """Return the held OOM target's exact shell-free create command."""

        if self.fault_profile is not RuntimeFaultProfile.OOM_256M:
            raise RuntimeStartError(
                "docker create is reserved for the oom_256m profile"
            )
        return self._docker_launch_argv("create")

    def _docker_launch_argv(self, operation: str) -> tuple[str, ...]:
        if operation not in {"run", "create"}:
            raise ValueError("Docker launch operation must be run or create")

        arguments: list[str] = [
            self.docker_executable,
            operation,
        ]
        if operation == "run":
            arguments.append("--detach")
        arguments.extend(
            [
                "--name",
                self.container_name,
            ]
        )
        for name, value in sorted(self.expected_labels.items()):
            arguments.extend(("--label", f"{name}={value}"))
        arguments.extend(("--network", "host"))
        if self.cpuset_cpus is not None:
            arguments.extend(("--cpuset-cpus", self.cpuset_cpus))
        arguments.extend(
            (
                "--memory",
                self.memory_limit,
                "--memory-swap",
                self.memory_limit,
                "--pids-limit",
                str(_PIDS_LIMIT),
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--security-opt",
                "seccomp=unconfined",
                "--restart",
                "no",
            )
        )
        for name, value in sorted(self.container_environment().items()):
            arguments.extend(("--env", f"{name}={value}"))
        arguments.extend(
            (
                "--volume",
                f"{self.entrypoint_path}:{_CONTAINER_ENTRYPOINT}:ro",
                "--volume",
                f"{self.evidence_dir}:{_CONTAINER_EVIDENCE_DIR}",
                "--entrypoint",
                "/bin/bash",
                self.resolved_image_reference,
                _CONTAINER_ENTRYPOINT,
            )
        )
        return tuple(arguments)

    def prepare(self) -> Mapping[str, Any]:
        """Start and attest the exact container after the caller leases its port."""

        if (
            self.fault_profile is RuntimeFaultProfile.OOM_256M
            and self.pre_readiness_oom_monitor is None
        ):
            raise RuntimeStartError(
                "oom_256m prepare requires the explicit pre-readiness monitor"
            )
        self._prepare_evidence_directory()
        if self.fault_profile is RuntimeFaultProfile.OOM_256M and any(
            (self.evidence_dir / name).exists()
            for name in (
                _OOM_HOLD_READY_NAME,
                _OOM_RELEASE_MARKER_NAME,
                _OOM_EXIT_ACK_MARKER_NAME,
                _OOM_RELEASE_EVIDENCE_NAME,
            )
        ):
            raise RuntimeStartError(
                "OOM hold evidence must be absent before exact container creation"
            )
        existing = self._inspect(self.container_name, allow_absent=True)
        if existing is not None:
            raise RuntimeStartError(
                f"refusing to replace existing container name {self.container_name}"
            )

        image_payload, image_resolution = self._resolve_image_reference()
        _atomic_write(
            self.evidence_dir / "image.inspect.json",
            (json.dumps(image_payload, sort_keys=True, indent=2) + "\n").encode(
                "utf-8"
            ),
        )
        self._write_json_evidence("image-resolution.json", image_resolution)

        held_oom_target = self.fault_profile is RuntimeFaultProfile.OOM_256M
        launch_argv = (
            self.docker_create_argv() if held_oom_target else self.docker_run_argv()
        )
        try:
            result = self._command(launch_argv, timeout_seconds=60.0)
        except Exception as exc:
            if held_oom_target:
                synthetic = CommandResult(
                    argv=launch_argv,
                    returncode=-1,
                    stdout="",
                    stderr=type(exc).__name__,
                )
                self._record_docker_lifecycle_command(
                    "create",
                    launch_argv,
                    synthetic,
                    ok=False,
                    outcome="command_exception",
                    container_id=None,
                )
                self._raise_oom_hold_failure(
                    "create",
                    exc,
                    container_id=None,
                )
            startup_terminal = self._record_startup_terminal(
                terminal_code="container_create_failure",
                injected=False,
            )
            raise RuntimeContainerCreateFailure(evidence=startup_terminal) from exc
        if result.returncode != 0:
            if held_oom_target:
                self._record_docker_lifecycle_command(
                    "create",
                    launch_argv,
                    result,
                    ok=False,
                    outcome="command_failed",
                    container_id=None,
                )
                self._raise_oom_hold_failure(
                    "create",
                    RuntimeStartError("held OOM docker create command failed"),
                    container_id=None,
                )
            startup_terminal = self._record_startup_terminal(
                terminal_code="container_create_failure",
                injected=False,
            )
            raise RuntimeContainerCreateFailure(evidence=startup_terminal)
        container_id = result.stdout.strip().lower()
        if not _CONTAINER_ID_RE.fullmatch(container_id):
            if held_oom_target:
                self._record_docker_lifecycle_command(
                    "create",
                    launch_argv,
                    result,
                    ok=False,
                    outcome="invalid_container_id",
                    container_id=None,
                )
                self._raise_oom_hold_failure(
                    "create",
                    RuntimeStartError("held OOM docker create returned an invalid ID"),
                    container_id=None,
                )
            startup_terminal = self._record_startup_terminal(
                terminal_code="container_create_failure",
                injected=False,
            )
            raise RuntimeContainerCreateFailure(evidence=startup_terminal)
        self._container_id = container_id
        if held_oom_target:
            self._record_docker_lifecycle_command(
                "create",
                launch_argv,
                result,
                ok=True,
                outcome="created",
                container_id=container_id,
            )

        inspection = self._inspect(self.container_name, allow_absent=False)
        assert inspection is not None
        self._assert_owned(
            inspection, require_running=False, require_expected_name=True
        )
        observed_id = str(inspection.get("Id") or "").lower()
        if observed_id != container_id:
            raise RuntimeOwnershipError("docker run and inspect container IDs differ")
        host_config = inspection.get("HostConfig")
        assert isinstance(host_config, Mapping)
        container_created = {
            "schema": "fortgym.m1b-container-created/v1",
            "ok": True,
            "run_id": self.contract.run_id,
            "contract_sha256": self.contract.contract_sha256,
            "nonce_sha256": hashlib.sha256(
                self.contract.nonce.encode("utf-8")
            ).hexdigest(),
            "cohort_sha256": self.contract.cohort_digest,
            "container_name": self.container_name,
            "container_id": container_id,
            "image_reference": self.resolved_image_reference,
            "fault_profile": (
                self.fault_profile.value if self.fault_profile is not None else None
            ),
            "memory_bytes": host_config["Memory"],
            "memory_swap_bytes": host_config["MemorySwap"],
        }
        self._write_json_evidence("container-created.json", container_created)
        self._append_lifecycle_evidence(container_created)
        if held_oom_target:
            start_argv = (self.docker_executable, "start", container_id)
            try:
                start_result = self._command(start_argv, timeout_seconds=60.0)
            except Exception as exc:  # noqa: BLE001 - preserve non-credit routing
                synthetic = CommandResult(
                    argv=start_argv,
                    returncode=-1,
                    stdout="",
                    stderr=type(exc).__name__,
                )
                self._record_docker_lifecycle_command(
                    "start",
                    start_argv,
                    synthetic,
                    ok=False,
                    outcome="command_exception",
                    container_id=container_id,
                )
                self._raise_oom_hold_failure(
                    "start",
                    exc,
                    container_id=container_id,
                )
            start_output = start_result.stdout.strip().lower()
            start_ok = start_result.returncode == 0 and start_output == container_id
            self._record_docker_lifecycle_command(
                "start",
                start_argv,
                start_result,
                ok=start_ok,
                outcome="started" if start_ok else "command_or_identity_failed",
                container_id=container_id,
            )
            if not start_ok:
                self._raise_oom_hold_failure(
                    "start",
                    RuntimeStartError(
                        "held OOM docker start command or identity failed"
                    ),
                    container_id=container_id,
                )

            try:
                hold_ready = self._wait_for_oom_hold_ready()
            except (RuntimeOomHoldFailure, RuntimeOomPreReadiness):
                raise
            except Exception as exc:  # noqa: BLE001 - convert the held boundary
                self._raise_oom_hold_failure(
                    "hold_ready",
                    exc,
                    container_id=container_id,
                )
            if self.pre_readiness_oom_monitor is not None:
                try:
                    monitor_arm = self.pre_readiness_oom_monitor.arm(container_created)
                    self._record_oom_monitor_result("arm", monitor_arm)
                    start_capture = getattr(
                        self.pre_readiness_oom_monitor, "start_counter_capture", None,
                    )
                    if callable(start_capture):
                        start_capture()
                except Exception as exc:  # noqa: BLE001 - fail closed at monitor seam
                    self._raise_oom_hold_failure(
                        "monitor_arm",
                        exc,
                        container_id=container_id,
                    )
                self._oom_monitor_armed = True
            release = {
                "schema": "fortgym.m1b-pre-readiness-oom-release/v1",
                "run_id": self.contract.run_id,
                "contract_sha256": self.contract.contract_sha256,
                "nonce_sha256": hashlib.sha256(
                    self.contract.nonce.encode("utf-8")
                ).hexdigest(),
                "container_id": container_id,
                "hold_ready_sha256": hashlib.sha256(
                    json.dumps(
                        hold_ready,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
            release_token = hashlib.sha256(
                b"\0".join(
                    value.encode("utf-8")
                    for value in (
                        "fortgym.m1b-pre-readiness-oom-release-token/v1",
                        self.contract.run_id,
                        self.contract.contract_sha256,
                        self.contract.nonce,
                    )
                )
            ).hexdigest()
            release["release_token_sha256"] = release_token
            try:
                self._write_json_evidence(_OOM_RELEASE_EVIDENCE_NAME, release)
                _atomic_write(
                    self.evidence_dir / _OOM_RELEASE_MARKER_NAME,
                    f"{release_token}\n".encode("ascii"),
                    # Only a derived digest, never the raw run nonce. The
                    # capability-dropped container cannot read host-owned 0600.
                    mode=0o644,
                )
                self._oom_release_written = True
                self._append_lifecycle_evidence(release)
            except Exception as exc:  # noqa: BLE001 - preserve non-credit routing
                self._raise_oom_hold_failure(
                    "release",
                    exc,
                    container_id=container_id,
                )

        readiness = self._wait_for_readiness()
        prepare_result = {
            "schema": "fortgym.m1b-runtime-prepare/v1",
            "ok": True,
            "container_name": self.container_name,
            "container_id": container_id,
            "image_reference": self.resolved_image_reference,
            "image_resolution": image_resolution,
            "entrypoint_sha256": self._entrypoint_sha256,
            "run_id": self.contract.run_id,
            "port": self.contract.port,
            "contract_sha256": self.contract.contract_sha256,
            "seed_tree_sha256": self.contract.seed_tree_sha256,
            "seed_world_sha256": self.contract.seed_world_sha256,
            "image_manifest_sha256": self.contract.image_manifest_sha256,
            "image_config_sha256": self.contract.image_config_sha256,
            "image_archive_sha256": self.contract.image_archive_sha256,
            "listener": readiness["listener"],
            "attestation": readiness["attestation"],
            "readiness_attempt": readiness["attempt"],
            "fault_profile": (
                self.fault_profile.value if self.fault_profile is not None else None
            ),
        }
        self._write_json_evidence("prepare.json", prepare_result)
        self._append_lifecycle_evidence(prepare_result)
        return prepare_result

    def cleanup(self) -> Mapping[str, Any]:
        """Capture evidence, remove only the exact owned container, and verify."""

        stop_capture = getattr(
            self.pre_readiness_oom_monitor, "stop_counter_capture", None,
        )
        if callable(stop_capture):
            stop_capture()
        self.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        lookup_identity = self._container_id or self.container_name
        inspection = self._inspect(lookup_identity, allow_absent=True)
        if inspection is None:
            listener = self._listener_status()
            listener_absent = not listener["present"] and not listener["unsafe"]
            shared_listener_preserved = bool(
                self._preserve_shared_listener_without_container
                and listener["present"]
                and not listener["unsafe"]
            )
            listener_clean = listener_absent or shared_listener_preserved
            if listener_clean:
                os.chmod(self.evidence_dir, 0o700)
            result = {
                "schema": "fortgym.m1b-runtime-cleanup/v1",
                "ok": listener_clean,
                "already_absent": True,
                "container_name": self.container_name,
                "container_absent": True,
                "listener_absent": listener_absent,
                "shared_listener_preserved": shared_listener_preserved,
                "port": self.contract.port,
            }
            self._write_json_evidence("cleanup.json", result)
            self._append_lifecycle_evidence(result)
            if not listener_clean:
                raise RuntimeCleanupError(
                    "container absent but assigned listener remains"
                )
            return result

        self._assert_owned(
            inspection, require_running=False, require_expected_name=True
        )
        owned_container_id = str(inspection.get("Id") or "").lower()
        if not _CONTAINER_ID_RE.fullmatch(owned_container_id):
            raise RuntimeOwnershipError("owned container ID is invalid")
        errors: list[str] = []

        try:
            self._capture_container(inspection, prefix="container")
        except Exception as exc:  # noqa: BLE001 - removal must still be attempted
            errors.append(f"inspect capture failed: {type(exc).__name__}")
        try:
            logs_result = self._command(
                (
                    self.docker_executable,
                    "logs",
                    "--timestamps",
                    "--tail",
                    "10000",
                    owned_container_id,
                ),
                timeout_seconds=30.0,
            )
            _atomic_write(
                self.evidence_dir / "container.logs.stdout.txt",
                _bounded_bytes(logs_result.stdout),
            )
            _atomic_write(
                self.evidence_dir / "container.logs.stderr.txt",
                _bounded_bytes(logs_result.stderr),
            )
            if logs_result.returncode != 0:
                errors.append(f"log capture failed: {_bounded_error(logs_result)}")
        except Exception as exc:  # noqa: BLE001 - removal must still be attempted
            errors.append(f"log capture failed: {type(exc).__name__}")

        try:
            remove_result = self._command(
                (self.docker_executable, "rm", "--force", owned_container_id),
                timeout_seconds=60.0,
            )
            if remove_result.returncode != 0:
                errors.append(
                    f"container removal failed: {_bounded_error(remove_result)}"
                )
        except Exception as exc:  # noqa: BLE001 - absence checks must still run
            errors.append(f"container removal failed: {type(exc).__name__}")
        try:
            container_absent = (
                self._inspect(owned_container_id, allow_absent=True) is None
            )
        except Exception as exc:  # noqa: BLE001 - preserve remaining cleanup evidence
            container_absent = False
            errors.append(f"container absence check failed: {type(exc).__name__}")
        if not container_absent and not any(
            error.startswith("container absence check failed") for error in errors
        ):
            errors.append("container remains after scoped removal")
        try:
            listener = self._listener_status()
            listener_clean = not listener["present"] and not listener["unsafe"]
        except Exception as exc:  # noqa: BLE001 - preserve cleanup result
            listener_clean = False
            errors.append(f"listener absence check failed: {type(exc).__name__}")
        if not listener_clean and not any(
            error.startswith("listener absence check failed") for error in errors
        ):
            errors.append("assigned listener remains after container removal")
        if container_absent:
            os.chmod(self.evidence_dir, 0o700)

        result = {
            "schema": "fortgym.m1b-runtime-cleanup/v1",
            "ok": not errors,
            "already_absent": False,
            "container_name": self.container_name,
            "container_id": owned_container_id,
            "container_absent": container_absent,
            "listener_absent": listener_clean,
            "port": self.contract.port,
            "errors": errors,
        }
        self._write_json_evidence("cleanup.json", result)
        self._append_lifecycle_evidence(result)
        if errors:
            raise RuntimeCleanupError("; ".join(errors))
        return result

    def reconcile(self) -> Mapping[str, Any]:
        """Reap exact contract-owned orphans and leave every mismatch untouched."""

        self.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        list_result = self._command(
            (
                self.docker_executable,
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                f"label={MANAGED_LABEL}=true",
                "--filter",
                f"label={CONTRACT_LABEL}={self.contract.contract_sha256}",
                "--format",
                "{{json .}}",
            ),
            timeout_seconds=30.0,
        )
        if list_result.returncode != 0:
            raise RuntimeCleanupError(
                f"managed-container listing failed: {_bounded_error(list_result)}"
            )

        candidates = self._parse_container_list(list_result.stdout)
        removed: list[str] = []
        skipped_foreign: list[str] = []
        errors: list[str] = []
        for candidate_id in candidates:
            inspection = self._inspect(candidate_id, allow_absent=True)
            if inspection is None:
                continue
            try:
                self._assert_reconcilable(inspection)
            except RuntimeOwnershipError:
                skipped_foreign.append(candidate_id)
                continue

            try:
                self._capture_container(
                    inspection,
                    prefix=f"reconcile-{candidate_id[:12]}",
                )
            except Exception as exc:  # noqa: BLE001 - reap exact orphan regardless
                errors.append(
                    f"failed to capture managed container {candidate_id}: "
                    f"{type(exc).__name__}"
                )
            try:
                remove_result = self._command(
                    (self.docker_executable, "rm", "--force", candidate_id),
                    timeout_seconds=60.0,
                )
            except Exception as exc:  # noqa: BLE001 - continue reconciling peers
                errors.append(
                    f"failed to remove managed container {candidate_id}: "
                    f"{type(exc).__name__}"
                )
                continue
            if remove_result.returncode != 0:
                errors.append(f"failed to remove managed container {candidate_id}")
                continue
            try:
                remains = self._inspect(candidate_id, allow_absent=True) is not None
            except Exception as exc:  # noqa: BLE001 - continue reconciling peers
                errors.append(
                    f"failed to verify managed container {candidate_id}: "
                    f"{type(exc).__name__}"
                )
                continue
            if remains:
                errors.append(f"managed container remains after removal {candidate_id}")
                continue
            removed.append(candidate_id)

        try:
            listener = self._listener_status()
            listener_clean = not listener["present"] and not listener["unsafe"]
        except Exception as exc:  # noqa: BLE001 - preserve reconciliation result
            listener_clean = False
            errors.append(f"listener absence check failed: {type(exc).__name__}")
        if removed and not listener_clean:
            errors.append("assigned listener remains after orphan reconciliation")
        if removed and listener_clean:
            os.chmod(self.evidence_dir, 0o700)
        result = {
            "schema": "fortgym.m1b-runtime-reconcile/v1",
            "ok": not errors,
            "managed_candidates": len(candidates),
            "removed_container_ids": removed,
            "skipped_foreign_container_ids": skipped_foreign,
            "listener_absent": listener_clean,
            "noop": not removed,
            "errors": errors,
        }
        self._write_json_evidence("reconcile.json", result)
        self._append_lifecycle_evidence(result)
        if errors:
            raise RuntimeCleanupError("; ".join(errors))
        return result

    def classify_runtime_fault(
        self, observation: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Map only strict, completed driver evidence to a typed fault result."""

        from .fault_driver import FaultGate, load_completed_fault_observation

        null_result = {
            "schema": "fortgym.runtime-fault-classifier-result/v1",
            "terminal_class": None,
            "evidence": {},
        }
        if not isinstance(observation, Mapping):
            raise RuntimeAttestationError("runtime fault observation must be a mapping")
        cleanup = observation.get("cleanup")
        if (
            observation.get("run_id") != self.contract.run_id
            or not isinstance(cleanup, Mapping)
            or cleanup.get("ok") is not True
        ):
            raise RuntimeAttestationError(
                "runtime fault observation lacks bound cleanup evidence"
            )
        completed = load_completed_fault_observation(
            control_root=self.contract.control_root,
            run_id=self.contract.run_id,
            contract_sha256=self.contract.contract_sha256,
            nonce=self.contract.nonce,
        )
        if completed is None:
            return null_result
        try:
            gate = FaultGate(completed["gate"])
            payload = completed["payload"]
            evidence = payload["classifier_evidence"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeAttestationError(
                "completed fault-driver evidence cannot be classified"
            ) from exc
        if not isinstance(payload, Mapping) or not isinstance(evidence, Mapping):
            raise RuntimeAttestationError(
                "completed fault-driver classifier evidence is malformed"
            )
        terminal_by_gate = {
            FaultGate.DF_KILL: "runtime_df_killed",
            FaultGate.HARNESS_KILL: "harness_killed",
            FaultGate.OOM: "runtime_oom",
            FaultGate.ENOSPC: "workspace_enospc",
            FaultGate.CONTAINER_RESTART: "runtime_container_restarted",
            FaultGate.DAEMON_RESTART: "docker_daemon_restarted",
        }
        return {
            "schema": "fortgym.runtime-fault-classifier-result/v1",
            "terminal_class": terminal_by_gate[gate],
            "evidence": dict(evidence),
        }

    def _record_docker_lifecycle_command(
        self,
        stage: str,
        argv: Sequence[str],
        result: CommandResult,
        *,
        ok: bool,
        outcome: str,
        container_id: str | None,
    ) -> None:
        if stage not in {"create", "start"}:
            raise ValueError("Docker lifecycle command stage is invalid")
        normalized = tuple(str(value) for value in argv)
        vector_digest = hashlib.sha256()
        for value in normalized:
            vector_digest.update(value.encode("utf-8"))
            vector_digest.update(b"\0")
        payload = {
            "schema": "fortgym.m1b-docker-lifecycle-command/v1",
            "ok": ok,
            "stage": stage,
            "outcome": outcome,
            "run_id": self.contract.run_id,
            "contract_sha256": self.contract.contract_sha256,
            "container_name": self.container_name,
            "container_id": container_id,
            "argv_sha256": vector_digest.hexdigest(),
            "argv_count": len(normalized),
            "shell": False,
            "returncode": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
        }
        self._write_json_evidence(f"container-{stage}-command.json", payload)
        self._append_lifecycle_evidence(payload)

    def _raise_oom_hold_failure(
        self,
        stage: str,
        cause: BaseException,
        *,
        container_id: str | None,
    ) -> None:
        allowed_stages = {
            "create",
            "start",
            "hold_ready",
            "monitor_arm",
            "release",
            "pre_release_exit",
            "monitor_finalize",
        }
        if stage not in allowed_stages:
            raise ValueError("held OOM failure stage is invalid")
        evidence = {
            "schema": "fortgym.m1b-oom-hold-failure/v1",
            "run_id": self.contract.run_id,
            "contract_sha256": self.contract.contract_sha256,
            "nonce_sha256": hashlib.sha256(
                self.contract.nonce.encode("utf-8")
            ).hexdigest(),
            "container_name": self.container_name,
            "container_id": container_id,
            "stage": stage,
            "failure_type": type(cause).__name__,
            "monitor_armed": self._oom_monitor_armed,
            "release_written": self._oom_release_written,
            "credit_eligible": False,
        }
        self._write_json_evidence("oom-hold-failure.json", evidence)
        self._append_lifecycle_evidence(evidence)
        raise RuntimeOomHoldFailure(evidence=evidence) from cause

    def _wait_for_oom_hold_ready(self) -> dict[str, Any]:
        expected = {
            "schema": "fortgym.m1b-pre-readiness-oom-hold-ready/v1",
            "run_id": self.contract.run_id,
            "contract_sha256": self.contract.contract_sha256,
            "nonce_sha256": hashlib.sha256(
                self.contract.nonce.encode("utf-8")
            ).hexdigest(),
            "cohort_sha256": self.contract.cohort_digest,
            "fault_profile": RuntimeFaultProfile.OOM_256M.value,
            "memory_bytes": _OOM_TEST_MEMORY_BYTES,
            "memory_swap_bytes": _OOM_TEST_MEMORY_BYTES,
        }
        path = self.evidence_dir / _OOM_HOLD_READY_NAME
        for attempt in range(1, self.readiness_attempts + 1):
            inspection = self._inspect(self.container_name, allow_absent=False)
            assert inspection is not None
            self._assert_owned(
                inspection,
                require_running=False,
                require_expected_name=True,
            )
            state = inspection.get("State")
            assert isinstance(state, Mapping)
            if state.get("Running") is not True:
                self._raise_pre_readiness_exit(inspection)
            try:
                observed = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                observed = None
            except json.JSONDecodeError as exc:
                raise RuntimeAttestationError(
                    "pre-readiness OOM hold receipt is invalid JSON"
                ) from exc
            if observed is not None:
                if not isinstance(observed, dict) or observed != expected:
                    raise RuntimeAttestationError(
                        "pre-readiness OOM hold receipt identity differs"
                    )
                self._write_json_evidence(
                    "pre-readiness-oom-hold-attested.json",
                    expected,
                )
                self._append_lifecycle_evidence(expected)
                return expected
            if attempt < self.readiness_attempts:
                self._sleep(self.readiness_interval_seconds)
        raise RuntimeAttestationError(
            "pre-readiness OOM hold did not become ready within the bounded attempts"
        )

    def _wait_for_readiness(self) -> dict[str, Any]:
        expected = (
            "FORTGYM_ATTEST",
            self.contract.run_id,
            self.contract.nonce,
            self.contract.contract_sha256,
            self.contract.seed_tree_sha256,
            self.contract.seed_world_sha256,
            self.contract.image_manifest_sha256,
            self.contract.image_config_sha256,
            self.contract.image_archive_sha256,
            "MAP_LOADED",
        )
        lua = (
            "local f=io.open('/run/fortgym/run-identity.tsv','r'); "
            "local v=f and f:read('*a') or ''; if f then f:close() end; "
            "local s=(v:gsub('%s+$','')); "
            "print('FORTGYM_ATTEST\\t'..s..'\\t'.."
            "(dfhack.isMapLoaded() and 'MAP_LOADED' or 'MAP_NOT_LOADED'))"
        )
        last_observation = "not attempted"
        for attempt in range(1, self.readiness_attempts + 1):
            inspection = self._inspect(self.container_name, allow_absent=False)
            assert inspection is not None
            self._assert_owned(
                inspection,
                require_running=False,
                require_expected_name=True,
            )
            state = inspection.get("State")
            assert isinstance(state, Mapping)
            if state.get("Running") is not True:
                self._raise_pre_readiness_exit(inspection)
            listener = self._listener_status()
            capture = getattr(self.pre_readiness_oom_monitor, "capture_live_oom", None)
            if self._oom_monitor_armed and self._oom_release_written and callable(capture):
                if capture(inspection):
                    token = hashlib.sha256(b"\0".join(value.encode("utf-8") for value in (
                        "fortgym.m1b-pre-readiness-oom-exit-ack/v1", self.contract.run_id,
                        self.contract.contract_sha256, self.contract.nonce,
                    ))).hexdigest()
                    _atomic_write(
                        self.evidence_dir / _OOM_EXIT_ACK_MARKER_NAME,
                        f"{token}\n".encode("ascii"), mode=0o644,
                    )
            if listener["unsafe"]:
                raise RuntimeAttestationError("DFHack listener is not loopback-only")
            if listener["present"]:
                exec_result = self._command(
                    (
                        self.docker_executable,
                        "exec",
                        "--env",
                        f"DFHACK_PORT={self.contract.port}",
                        self.container_name,
                        "/opt/dwarf-fortress/dfhack-run",
                        "lua",
                        lua,
                    ),
                    timeout_seconds=10.0,
                )
                if exec_result.returncode == 0:
                    observed = self._parse_attestation(exec_result.stdout)
                    if observed is not None:
                        if observed[:-1] != expected[:-1]:
                            raise RuntimeAttestationError(
                                "DFHack runtime identity or seed attestation mismatch"
                            )
                        if observed[-1] == "MAP_LOADED":
                            attestation = {
                                "run_id": observed[1],
                                "nonce": observed[2],
                                "contract_sha256": observed[3],
                                "seed_tree_sha256": observed[4],
                                "seed_world_sha256": observed[5],
                                "image_manifest_sha256": observed[6],
                                "image_config_sha256": observed[7],
                                "image_archive_sha256": observed[8],
                                "map_loaded": True,
                            }
                            return {
                                "attempt": attempt,
                                "listener": listener["lines"],
                                "attestation": attestation,
                            }
                        last_observation = "map not loaded"
                    else:
                        last_observation = "RPC output lacked attestation marker"
                else:
                    last_observation = f"RPC exec failed: {_bounded_error(exec_result)}"
            else:
                last_observation = "listener not present"
            if attempt < self.readiness_attempts:
                self._sleep(self.readiness_interval_seconds)
        final_inspection = self._inspect(self.container_name, allow_absent=False)
        assert final_inspection is not None
        self._assert_owned(
            final_inspection,
            require_running=False,
            require_expected_name=True,
        )
        final_state = final_inspection.get("State")
        assert isinstance(final_state, Mapping)
        if final_state.get("Running") is not True:
            self._raise_pre_readiness_exit(final_inspection)
        startup_terminal = self._read_startup_terminal()
        if startup_terminal is not None:
            self._raise_startup_terminal(startup_terminal)
        raise RuntimeAttestationError(
            f"runtime readiness exhausted after {self.readiness_attempts} attempts: "
            f"{last_observation}"
        )

    def _raise_pre_readiness_exit(self, inspection: Mapping[str, Any]) -> None:
        """Raise one exact typed startup exit or a generic attestation error."""

        startup_terminal = self._read_startup_terminal()
        state = inspection.get("State")
        assert isinstance(state, Mapping)
        is_exact_oom_profile = (
            self.allow_test_fault_profile is True
            and self.fault_profile is RuntimeFaultProfile.OOM_256M
            and state.get("Running") is False
            and state.get("OOMKilled") is True
            and state.get("ExitCode") == 137
        )
        if is_exact_oom_profile:
            if startup_terminal is not None:
                raise RuntimeAttestationError(
                    "pre-readiness OOM contradicts startup terminal evidence"
                )
            if self.pre_readiness_oom_monitor is not None and (
                self._oom_monitor_armed is not True
                or self._oom_release_written is not True
            ):
                self._raise_oom_hold_failure(
                    "pre_release_exit",
                    RuntimeAttestationError(
                        "OOM target exited before monitor arm and durable release"
                    ),
                    container_id=str(inspection.get("Id") or "").lower(),
                )
            evidence = {
                "schema": "fortgym.m1b-pre-readiness-oom-observation/v1",
                "run_id": self.contract.run_id,
                "contract_sha256": self.contract.contract_sha256,
                "nonce_sha256": hashlib.sha256(
                    self.contract.nonce.encode("utf-8")
                ).hexdigest(),
                "container_name": self.container_name,
                "container_id": str(inspection.get("Id") or "").lower(),
                "fault_profile": RuntimeFaultProfile.OOM_256M.value,
                "memory_bytes": _OOM_TEST_MEMORY_BYTES,
                "memory_swap_bytes": _OOM_TEST_MEMORY_BYTES,
                "state": {
                    "running": False,
                    "oom_killed": True,
                    "exit_code": 137,
                },
            }
            self._write_json_evidence("pre-readiness-oom.json", evidence)
            self._append_lifecycle_evidence(evidence)
            if self.pre_readiness_oom_monitor is not None:
                try:
                    monitor_finalize = self.pre_readiness_oom_monitor.finalize(evidence)
                    self._record_oom_monitor_result("finalize", monitor_finalize)
                except Exception as exc:  # noqa: BLE001 - fail closed at monitor seam
                    self._raise_oom_hold_failure(
                        "monitor_finalize",
                        exc,
                        container_id=str(inspection.get("Id") or "").lower(),
                    )
            raise RuntimeOomPreReadiness(evidence=evidence)
        if startup_terminal is not None:
            self._raise_startup_terminal(startup_terminal)
        raise RuntimeAttestationError("container exited before readiness")

    def _read_startup_terminal(self) -> dict[str, Any] | None:
        path = self.evidence_dir / _STARTUP_TERMINAL_NAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            raise RuntimeAttestationError(
                "startup terminal evidence is invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeAttestationError("startup terminal evidence must be an object")
        expected_keys = {
            "schema",
            "run_id",
            "contract_sha256",
            "terminal_code",
            "injected",
        }
        if set(payload) != expected_keys:
            raise RuntimeAttestationError("startup terminal evidence fields differ")
        if (
            payload.get("schema") != "fortgym.m1b-startup-terminal/v1"
            or payload.get("run_id") != self.contract.run_id
            or payload.get("contract_sha256") != self.contract.contract_sha256
            or payload.get("terminal_code")
            not in {
                "container_create_failure",
                "rpc_readiness_timeout",
                "map_readiness_timeout",
            }
            or not isinstance(payload.get("injected"), bool)
        ):
            raise RuntimeAttestationError("startup terminal evidence identity differs")
        injected = payload["injected"]
        if injected is not (self.test_fault is RuntimeTestFault.SUPPRESS_RPC_READINESS):
            raise RuntimeAttestationError("startup terminal injection identity differs")
        return payload

    def _record_startup_terminal(
        self, *, terminal_code: str, injected: bool
    ) -> dict[str, Any]:
        if terminal_code not in {
            "container_create_failure",
            "rpc_readiness_timeout",
            "map_readiness_timeout",
        }:
            raise ValueError("startup terminal code is not supported")
        payload = {
            "schema": "fortgym.m1b-startup-terminal/v1",
            "run_id": self.contract.run_id,
            "contract_sha256": self.contract.contract_sha256,
            "terminal_code": terminal_code,
            "injected": injected,
        }
        self._write_json_evidence(_STARTUP_TERMINAL_NAME, payload)
        return payload

    @staticmethod
    def _raise_startup_terminal(payload: Mapping[str, Any]) -> None:
        if payload.get("terminal_code") == "rpc_readiness_timeout":
            raise RuntimeReadinessTimeout(
                injected=payload.get("injected") is True,
                evidence=payload,
            )
        if payload.get("terminal_code") == "map_readiness_timeout":
            raise RuntimeMapReadinessTimeout(evidence=payload)
        if payload.get("terminal_code") == "container_create_failure":
            raise RuntimeContainerCreateFailure(evidence=payload)
        raise RuntimeAttestationError("unsupported startup terminal evidence")

    def _resolve_image_reference(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Resolve either supported Docker-store identity without using a tag."""

        manifest_result = self._command(
            (
                self.docker_executable,
                "image",
                "inspect",
                self.image_reference,
            ),
            timeout_seconds=30.0,
        )
        archive_verification: dict[str, Any] | None = None
        resolution_mode: str
        if manifest_result.returncode == 0:
            payload = self._json_list(
                manifest_result, operation="manifest image inspect"
            )
            if len(payload) != 1:
                raise RuntimeStartError(
                    "manifest image inspect did not return exactly one image"
                )
            observed_id = str(payload[0].get("Id") or "")
            if observed_id not in {
                self.image_reference,
                self.image_config_reference,
            }:
                raise RuntimeStartError(
                    "manifest-addressed image resolved to an unpinned config"
                )
            resolved_reference = self.image_reference
            resolution_mode = "manifest_descriptor"
        elif _is_not_found(manifest_result):
            archive_verification = self._verify_image_archive_chain()
            config_result = self._command(
                (
                    self.docker_executable,
                    "image",
                    "inspect",
                    self.image_config_reference,
                ),
                timeout_seconds=30.0,
            )
            payload = self._json_list(config_result, operation="config image inspect")
            if len(payload) != 1:
                raise RuntimeStartError(
                    "config image inspect did not return exactly one image"
                )
            observed_id = str(payload[0].get("Id") or "")
            if observed_id != self.image_config_reference:
                raise RuntimeStartError(
                    "config-addressed image does not match the pinned config digest"
                )
            resolved_reference = self.image_config_reference
            resolution_mode = "config_id_fallback"
        else:
            raise RuntimeStartError(
                f"manifest image inspect failed: {_bounded_error(manifest_result)}"
            )

        self._resolved_image_reference = resolved_reference
        resolution = {
            "schema": "fortgym.m1b-image-resolution/v1",
            "mode": resolution_mode,
            "resolved_reference": resolved_reference,
            "observed_image_id": observed_id,
            "image_manifest_sha256": self.contract.image_manifest_sha256,
            "image_config_sha256": self.contract.image_config_sha256,
            "image_archive_sha256": self.contract.image_archive_sha256,
        }
        if archive_verification is not None:
            resolution["archive_verification"] = archive_verification
        self._image_resolution = resolution
        return payload, resolution

    def _verify_image_archive_chain(self) -> dict[str, Any]:
        """Bind a config-ID fallback to the preserved OCI archive identity."""

        archive_path = self.image_archive_path
        if archive_path is None:
            raise RuntimeStartError(
                "config-ID fallback requires an explicit preserved OCI archive"
            )
        try:
            before = archive_path.stat()
            archive_sha256 = _sha256_file(archive_path)
        except OSError as exc:
            raise RuntimeStartError("preserved OCI archive is unreadable") from exc
        if archive_sha256 != self.contract.image_archive_sha256:
            raise RuntimeStartError(
                "preserved OCI archive compressed SHA-256 does not match contract"
            )

        index, _index_bytes = self._read_archive_json_member("index.json")
        manifests = index.get("manifests")
        if (
            index.get("schemaVersion") != 2
            or not isinstance(manifests, list)
            or len(manifests) != 1
            or not isinstance(manifests[0], Mapping)
            or manifests[0].get("mediaType")
            != "application/vnd.oci.image.manifest.v1+json"
            or manifests[0].get("digest") != self.image_reference
        ):
            raise RuntimeStartError(
                "preserved OCI index does not bind the pinned manifest digest"
            )

        manifest_member = f"blobs/sha256/{self.contract.image_manifest_sha256}"
        manifest, manifest_bytes = self._read_archive_json_member(manifest_member)
        if hashlib.sha256(manifest_bytes).hexdigest() != (
            self.contract.image_manifest_sha256
        ):
            raise RuntimeStartError(
                "preserved OCI manifest bytes do not match the pinned digest"
            )
        if manifests[0].get("size") != len(manifest_bytes):
            raise RuntimeStartError(
                "preserved OCI index manifest size does not match its blob"
            )
        config = manifest.get("config")
        layers = manifest.get("layers")
        if (
            manifest.get("schemaVersion") != 2
            or manifest.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
            or not isinstance(config, Mapping)
            or config.get("mediaType") != "application/vnd.oci.image.config.v1+json"
            or config.get("digest") != self.image_config_reference
            or not isinstance(layers, list)
            or not layers
            or any(not isinstance(layer, Mapping) for layer in layers)
        ):
            raise RuntimeStartError(
                "preserved OCI manifest does not bind the pinned config digest"
            )

        config_member = f"blobs/sha256/{self.contract.image_config_sha256}"
        _config, config_bytes = self._read_archive_json_member(config_member)
        if hashlib.sha256(config_bytes).hexdigest() != (
            self.contract.image_config_sha256
        ):
            raise RuntimeStartError(
                "preserved OCI config bytes do not match the pinned digest"
            )
        if config.get("size") != len(config_bytes):
            raise RuntimeStartError(
                "preserved OCI manifest config size does not match its blob"
            )
        try:
            after = archive_path.stat()
        except OSError as exc:
            raise RuntimeStartError(
                "preserved OCI archive disappeared during verification"
            ) from exc
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise RuntimeStartError("preserved OCI archive changed during verification")
        return {
            "schema": "fortgym.m1b-oci-archive-verification/v1",
            "archive_path": str(archive_path),
            "compressed_sha256": archive_sha256,
            "archive_size_bytes": before.st_size,
            "manifest_digest": self.image_reference,
            "config_digest": self.image_config_reference,
            "index_manifest_count": 1,
        }

    def _read_archive_json_member(self, member: str) -> tuple[dict[str, Any], bytes]:
        archive_path = self.image_archive_path
        if archive_path is None:
            raise RuntimeStartError("preserved OCI archive path is unavailable")
        try:
            selected = self._archive_member_reader(
                archive_path,
                frozenset({member}),
                timeout_seconds=120.0,
            )
        except RuntimeControllerError:
            raise
        except Exception as exc:
            raise RuntimeStartError("preserved OCI archive reader failed") from exc
        if set(selected) != {member} or not isinstance(selected.get(member), bytes):
            raise RuntimeStartError(
                "preserved OCI archive reader returned contradictory members"
            )
        encoded = selected[member]
        if not encoded or len(encoded) > _MAX_CAPTURE_BYTES:
            raise RuntimeStartError(
                f"preserved OCI archive member {member} has an invalid size"
            )
        try:
            payload = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeStartError(
                f"preserved OCI archive member {member} is invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeStartError(
                f"preserved OCI archive member {member} is not an object"
            )
        return payload, encoded

    @staticmethod
    def _parse_attestation(output: str) -> tuple[str, ...] | None:
        clean = _ANSI_RE.sub("", output)
        for line in clean.splitlines():
            if not line.startswith("FORTGYM_ATTEST\t"):
                continue
            fields = tuple(line.rstrip().split("\t"))
            if len(fields) != 10 or fields[-1] not in {
                "MAP_LOADED",
                "MAP_NOT_LOADED",
            }:
                raise RuntimeAttestationError("malformed DFHack runtime attestation")
            return fields
        return None

    def _listener_status(self) -> dict[str, Any]:
        result = self._command(
            (
                self.listener_executable,
                "-Hlnpt",
                f"sport = :{self.contract.port}",
            ),
            timeout_seconds=10.0,
        )
        if result.returncode != 0:
            raise RuntimeCommandError(
                f"listener inspection failed: {_bounded_error(result)}"
            )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        endpoints: list[str] = []
        unsafe = False
        suffix = f":{self.contract.port}"
        for line in lines:
            for token in line.split():
                endpoint = token.rstrip(",")
                if not endpoint.endswith(suffix):
                    continue
                host = endpoint[: -len(suffix)]
                if host.startswith("[") and host.endswith("]"):
                    host = host[1:-1]
                endpoints.append(endpoint)
                if host not in {"127.0.0.1", "::1"}:
                    unsafe = True
                break
        return {
            "present": bool(endpoints),
            "unsafe": unsafe or (bool(lines) and not endpoints),
            "lines": lines[:20],
        }

    def _inspect(self, identifier: str, *, allow_absent: bool) -> dict[str, Any] | None:
        result = self._command(
            (
                self.docker_executable,
                "inspect",
                "--type",
                "container",
                identifier,
            ),
            timeout_seconds=30.0,
        )
        if _is_not_found(result):
            if allow_absent:
                return None
            raise RuntimeAttestationError(f"container disappeared: {identifier}")
        payload = self._json_list(result, operation="container inspect")
        if len(payload) != 1:
            raise RuntimeCommandError(
                "container inspect did not return exactly one object"
            )
        return payload[0]

    @staticmethod
    def _json_list(result: CommandResult, *, operation: str) -> list[dict[str, Any]]:
        if result.returncode != 0:
            raise RuntimeCommandError(f"{operation} failed: {_bounded_error(result)}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeCommandError(f"{operation} returned invalid JSON") from exc
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise RuntimeCommandError(f"{operation} returned an unexpected JSON shape")
        return payload

    def _assert_owned(
        self,
        inspection: Mapping[str, Any],
        *,
        require_running: bool,
        require_expected_name: bool,
        require_current_id: bool = True,
    ) -> None:
        config = inspection.get("Config")
        host_config = inspection.get("HostConfig")
        state = inspection.get("State")
        mounts = inspection.get("Mounts")
        if not isinstance(config, Mapping) or not isinstance(host_config, Mapping):
            raise RuntimeOwnershipError("container inspection lacks configuration")
        if not isinstance(state, Mapping) or not isinstance(mounts, list):
            raise RuntimeOwnershipError("container inspection lacks state or mounts")
        labels = config.get("Labels")
        if not isinstance(labels, Mapping):
            raise RuntimeOwnershipError("container inspection lacks ownership labels")
        mismatches = {
            name: {"expected": value, "observed": labels.get(name)}
            for name, value in self.expected_labels.items()
            if labels.get(name) != value
        }
        for name, expected in (
            (
                TEST_FAULT_LABEL,
                self.test_fault.value if self.test_fault is not None else None,
            ),
            (
                FAULT_PROFILE_LABEL,
                self.fault_profile.value if self.fault_profile is not None else None,
            ),
        ):
            if labels.get(name) != expected or (expected is None and name in labels):
                mismatches[name] = {
                    "expected": expected,
                    "observed": labels.get(name),
                }
        if mismatches:
            raise RuntimeOwnershipError(
                "container ownership labels do not match contract"
            )

        observed_name = str(inspection.get("Name") or "").removeprefix("/")
        if require_expected_name and observed_name != self.container_name:
            raise RuntimeOwnershipError("container name does not match contract")
        observed_id = str(inspection.get("Id") or "").lower()
        if not _CONTAINER_ID_RE.fullmatch(observed_id):
            raise RuntimeOwnershipError("container inspection has invalid ID")
        if (
            require_current_id
            and self._container_id
            and observed_id != self._container_id
        ):
            raise RuntimeOwnershipError("container name was reused by another object")

        configured_image = str(config.get("Image") or "")
        runtime_image = str(inspection.get("Image") or "")
        if configured_image not in {
            self.image_reference,
            self.image_config_reference,
        }:
            raise RuntimeOwnershipError(
                "container was not created from pinned image reference"
            )
        if (
            self._resolved_image_reference is not None
            and configured_image != self._resolved_image_reference
        ):
            raise RuntimeOwnershipError(
                "container configured image differs from resolved image reference"
            )
        if runtime_image not in {self.image_reference, self.image_config_reference}:
            raise RuntimeOwnershipError(
                "container runtime image digest does not match contract"
            )
        if require_running and state.get("Running") is not True:
            raise RuntimeAttestationError("container exited before readiness")

        observed_environment = config.get("Env")
        if not isinstance(observed_environment, list) or any(
            not isinstance(item, str) or "=" not in item
            for item in observed_environment
        ):
            raise RuntimeOwnershipError("container environment is not inspectable")
        environment = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in observed_environment
        }
        expected_environment = self.container_environment()
        if any(
            environment.get(name) != value
            for name, value in expected_environment.items()
        ):
            raise RuntimeOwnershipError(
                "container runtime identity environment differs"
            )
        if any(self._is_provider_environment_name(name) for name in environment):
            raise RuntimeOwnershipError("provider material entered the DF container")
        entrypoint = config.get("Entrypoint")
        command = config.get("Cmd")
        if entrypoint != ["/bin/bash"] or command != [_CONTAINER_ENTRYPOINT]:
            raise RuntimeOwnershipError("container entrypoint command differs")

        restart_policy = host_config.get("RestartPolicy")
        security_opt = host_config.get("SecurityOpt")
        cap_drop = host_config.get("CapDrop")
        if (
            host_config.get("NetworkMode") != "host"
            or host_config.get("Memory") != self.memory_bytes
            or host_config.get("MemorySwap") != self.memory_bytes
            or host_config.get("PidsLimit") != _PIDS_LIMIT
            or not isinstance(restart_policy, Mapping)
            or restart_policy.get("Name") != "no"
            or not isinstance(cap_drop, list)
            or "ALL" not in cap_drop
            or not isinstance(security_opt, list)
            or "no-new-privileges" not in security_opt
        ):
            raise RuntimeOwnershipError(
                "container isolation settings do not match contract"
            )
        if host_config.get("CpusetCpus") != (self.cpuset_cpus or ""):
            raise RuntimeOwnershipError("container CPU set does not match contract")

        mount_index = {
            str(item.get("Destination")): item
            for item in mounts
            if isinstance(item, Mapping)
        }
        entrypoint_mount = mount_index.get(_CONTAINER_ENTRYPOINT)
        evidence_mount = mount_index.get(_CONTAINER_EVIDENCE_DIR)
        if (
            not isinstance(entrypoint_mount, Mapping)
            or Path(str(entrypoint_mount.get("Source"))) != self.entrypoint_path
            or entrypoint_mount.get("RW") is not False
            or not isinstance(evidence_mount, Mapping)
            or Path(str(evidence_mount.get("Source"))) != self.evidence_dir
            or evidence_mount.get("RW") is not True
        ):
            raise RuntimeOwnershipError("container bind mounts do not match contract")

    def _assert_reconcilable(self, inspection: Mapping[str, Any]) -> None:
        """Prove durable label ownership without depending on current source bytes."""

        config = inspection.get("Config")
        host_config = inspection.get("HostConfig")
        if not isinstance(config, Mapping) or not isinstance(host_config, Mapping):
            raise RuntimeOwnershipError("container inspection lacks configuration")
        labels = config.get("Labels")
        if not isinstance(labels, Mapping):
            raise RuntimeOwnershipError("container inspection lacks ownership labels")
        durable_labels = {
            MANAGED_LABEL: "true",
            RUN_ID_LABEL: self.contract.run_id,
            CONTRACT_LABEL: self.contract.contract_sha256,
            COHORT_LABEL: self.contract.cohort_digest,
            IMAGE_LABEL: self.contract.image_manifest_sha256,
            IMAGE_CONFIG_LABEL: self.contract.image_config_sha256,
            IMAGE_ARCHIVE_LABEL: self.contract.image_archive_sha256,
        }
        if self.test_fault is not None:
            durable_labels[TEST_FAULT_LABEL] = self.test_fault.value
        if self.fault_profile is not None:
            durable_labels[FAULT_PROFILE_LABEL] = self.fault_profile.value
        if any(labels.get(name) != value for name, value in durable_labels.items()):
            raise RuntimeOwnershipError(
                "container does not match durable run ownership"
            )
        for name, expected in (
            (
                TEST_FAULT_LABEL,
                self.test_fault.value if self.test_fault is not None else None,
            ),
            (
                FAULT_PROFILE_LABEL,
                self.fault_profile.value if self.fault_profile is not None else None,
            ),
        ):
            if labels.get(name) != expected or (expected is None and name in labels):
                raise RuntimeOwnershipError(
                    "container test profile does not match durable contract"
                )
        if (
            host_config.get("Memory") != self.memory_bytes
            or host_config.get("MemorySwap") != self.memory_bytes
            or host_config.get("CpusetCpus") != (self.cpuset_cpus or "")
        ):
            raise RuntimeOwnershipError(
                "container resource profile does not match durable contract"
            )
        observed_id = str(inspection.get("Id") or "").lower()
        if not _CONTAINER_ID_RE.fullmatch(observed_id):
            raise RuntimeOwnershipError("container inspection has invalid ID")
        configured_image = str(config.get("Image") or "")
        runtime_image = str(inspection.get("Image") or "")
        if configured_image not in {
            self.image_reference,
            self.image_config_reference,
        } or runtime_image not in {
            self.image_reference,
            self.image_config_reference,
        }:
            raise RuntimeOwnershipError(
                "container image does not match durable contract"
            )

    @staticmethod
    def _is_provider_environment_name(name: str) -> bool:
        upper = name.upper()
        if upper.startswith(
            (
                "ANTHROPIC_",
                "GEMINI_",
                "GOOGLE_",
                "LLM_",
                "OPENAI_",
                "OPENROUTER_",
            )
        ):
            return True
        return upper.endswith(("_API_KEY", "_ACCESS_TOKEN", "_AUTH_TOKEN"))

    def _capture_container(self, inspection: Mapping[str, Any], *, prefix: str) -> None:
        encoded = (json.dumps(inspection, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        if len(encoded) > _MAX_CAPTURE_BYTES:
            raise RuntimeCleanupError(
                "container inspection exceeds evidence capture bound"
            )
        _atomic_write(self.evidence_dir / f"{prefix}.inspect.json", encoded)

    def _prepare_evidence_directory(self) -> None:
        """Create the per-attempt bind with sticky write access for image UID 1000."""

        self.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.evidence_dir, 0o1777)

    def _write_json_evidence(self, name: str, payload: Mapping[str, Any]) -> None:
        _atomic_write(
            self.evidence_dir / name,
            (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )

    def _record_oom_monitor_result(self, phase: str, result: Mapping[str, Any]) -> None:
        expected_schema = f"fortgym.m1b-pre-readiness-oom-monitor-{phase}/v1"
        if not isinstance(result, Mapping):
            raise RuntimeAttestationError(
                f"pre-readiness OOM monitor {phase} result must be a mapping"
            )
        payload = dict(result)
        if payload.get("schema") != expected_schema or payload.get("ok") is not True:
            raise RuntimeAttestationError(
                f"pre-readiness OOM monitor {phase} did not prove success"
            )
        common = {
            "schema",
            "ok",
            "run_id",
            "contract_sha256",
            "nonce_sha256",
            "cohort_sha256",
            "container_id",
            "journal_path",
        }
        phase_keys = {
            "arm": common
            | {
                "container_init_host_pid",
                "container_cgroup_path",
                "peer_run_id",
                "peer_container_id",
                "peer_readiness_sha256",
            },
            "finalize": common
            | {
                "completed_record_sha256",
                "classifier_evidence_sha256",
            },
        }
        if phase not in phase_keys or set(payload) != phase_keys[phase]:
            raise RuntimeAttestationError(
                f"pre-readiness OOM monitor {phase} fields differ"
            )
        expected_journal = (
            self.contract.control_root
            / self.contract.run_id
            / "fault-driver-observations.jsonl"
        )
        if (
            payload.get("run_id") != self.contract.run_id
            or payload.get("contract_sha256") != self.contract.contract_sha256
            or payload.get("nonce_sha256")
            != hashlib.sha256(self.contract.nonce.encode("utf-8")).hexdigest()
            or payload.get("cohort_sha256") != self.contract.cohort_digest
            or payload.get("container_id") != self._container_id
            or payload.get("journal_path") != str(expected_journal)
        ):
            raise RuntimeAttestationError(
                f"pre-readiness OOM monitor {phase} identity differs"
            )
        if phase == "arm":
            peer_run_ids = [
                run_id
                for run_id in self.contract.cohort_run_ids
                if run_id != self.contract.run_id
            ]
            init_pid = payload.get("container_init_host_pid")
            cgroup_path = payload.get("container_cgroup_path")
            peer_container_id = payload.get("peer_container_id")
            peer_readiness_sha256 = payload.get("peer_readiness_sha256")
            if (
                len(peer_run_ids) != 1
                or payload.get("peer_run_id") != peer_run_ids[0]
                or isinstance(init_pid, bool)
                or not isinstance(init_pid, int)
                or init_pid <= 1
                or not isinstance(cgroup_path, str)
                or not cgroup_path.startswith("/")
                or cgroup_path == "/"
                or "\0" in cgroup_path
                or ".." in Path(cgroup_path).parts
                or not isinstance(peer_container_id, str)
                or not _CONTAINER_ID_RE.fullmatch(peer_container_id)
                or peer_container_id == self._container_id
                or not isinstance(peer_readiness_sha256, str)
                or not _SHA256_RE.fullmatch(peer_readiness_sha256)
            ):
                raise RuntimeAttestationError(
                    "pre-readiness OOM monitor arm target or peer proof differs"
                )
            self._oom_monitor_arm_result = payload
        else:
            arm = self._oom_monitor_arm_result
            if (
                arm is None
                or payload.get("journal_path") != arm.get("journal_path")
                or any(
                    not isinstance(payload.get(name), str)
                    or not _SHA256_RE.fullmatch(str(payload.get(name)))
                    for name in (
                        "completed_record_sha256",
                        "classifier_evidence_sha256",
                    )
                )
            ):
                raise RuntimeAttestationError(
                    "pre-readiness OOM monitor finalize proof differs"
                )
        try:
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise RuntimeAttestationError(
                f"pre-readiness OOM monitor {phase} evidence is not JSON-safe"
            ) from exc
        self._write_json_evidence(f"pre-readiness-oom-monitor-{phase}.json", payload)
        self._append_lifecycle_evidence(payload)

    def _append_lifecycle_evidence(self, payload: Mapping[str, Any]) -> None:
        encoded = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_CAPTURE_BYTES:
            raise RuntimeControllerError("lifecycle evidence record exceeds bound")
        path = self.evidence_dir / "lifecycle.jsonl"
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short append")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _parse_container_list(stdout: str) -> list[str]:
        identifiers: list[str] = []
        for raw_line in stdout.splitlines():
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise RuntimeCommandError("docker ps returned malformed JSONL") from exc
            if not isinstance(row, Mapping):
                raise RuntimeCommandError("docker ps returned a non-object row")
            identifier = str(row.get("ID") or row.get("Id") or "").lower()
            if not _CONTAINER_ID_RE.fullmatch(identifier):
                raise RuntimeCommandError("docker ps returned an invalid container ID")
            if identifier not in identifiers:
                identifiers.append(identifier)
        return identifiers

    def _command(self, argv: Sequence[str], *, timeout_seconds: float) -> CommandResult:
        normalized = tuple(str(item) for item in argv)
        if not normalized or any("\0" in item for item in normalized):
            raise RuntimeCommandError("refusing empty or NUL-containing command")
        result = self.runner.run(normalized, timeout_seconds=timeout_seconds)
        if tuple(result.argv) != normalized:
            raise RuntimeCommandError(
                "command runner returned evidence for different argv"
            )
        return result


RuntimeController = DockerRuntimeController

__all__ = [
    "COHORT_LABEL",
    "CONTRACT_LABEL",
    "ENTRYPOINT_LABEL",
    "FAULT_PROFILE_LABEL",
    "IMAGE_ARCHIVE_LABEL",
    "IMAGE_CONFIG_LABEL",
    "IMAGE_LABEL",
    "MANAGED_LABEL",
    "RUN_ID_LABEL",
    "TEST_FAULT_LABEL",
    "ArchiveMemberReader",
    "CommandResult",
    "CommandRunner",
    "DockerRuntimeController",
    "PreReadinessOomMonitor",
    "RuntimeAttestationError",
    "RuntimeCleanupError",
    "RuntimeCommandError",
    "RuntimeContainerCreateFailure",
    "RuntimeController",
    "RuntimeControllerError",
    "RuntimeFaultProfile",
    "RuntimeMapReadinessTimeout",
    "RuntimeOomHoldFailure",
    "RuntimeOomPreReadiness",
    "RuntimeOwnershipError",
    "RuntimeReadinessTimeout",
    "RuntimeStartError",
    "RuntimeTestFault",
    "SubprocessCommandRunner",
    "ZstdTarArchiveReader",
]
