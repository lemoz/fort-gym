"""Fail-closed PROVIDER-NET control for an isolated x86-64 Linux host.

This module deliberately does not install an application-only fallback.  The
existing early Python address guard remains one layer, while a separately
attested privileged helper must join the harness to an already-filtered cgroup
before ``exec``.  The helper's cgroup-BPF policy default-denies every network
operation except TCP ``connect4`` to the assigned DFHack loopback port and
captures ``connect4``, ``connect6``, ``sendmsg4``, and ``sendmsg6`` events.

``ProcessSupervisor`` supports this controller only through an explicit opt-in
argument. It validates the pinned wrapper, merges the exact Python guard, and
uses :meth:`ProviderNetworkIsolationController.enter_argv` as the launched
command. A real gate still requires the privileged helper/BPF artifacts and an
isolated Linux run; fake/local tests are not gate evidence.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

CAPABILITY_SCHEMA = "fortgym.provider-network-capabilities/v1"
PREPARE_SCHEMA = "fortgym.provider-network-prepare/v1"
INSPECT_SCHEMA = "fortgym.provider-network-inspect/v1"
SNAPSHOT_SCHEMA = "fortgym.provider-network-capture/v1"
CLEANUP_SCHEMA = "fortgym.provider-network-cleanup/v1"
REPORT_SCHEMA = "fortgym.provider-network-report/v1"
MANIFEST_SCHEMA = "fortgym.provider-network-manifest/v1"
PYTHON_GUARD_ATTESTATION_SCHEMA = "fortgym.python-network-guard-attestation/v1"

REQUIRED_HOOKS = ("connect4", "connect6", "sendmsg4", "sendmsg6")
LINUX_CLASSIFICATION = "isolated_x86_linux_provider_network_control"
INTEGRATION_STATUS = "process-supervisor-atomic-wrapper-v1"

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|secret|^nonce$)",
    re.IGNORECASE,
)
_MAX_COMMAND_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_CAPTURE_EVENTS = 100_000
_NEGATIVE_DNS_HOST = "198.51.100.53"
_NEGATIVE_HTTPS_HOST = "198.51.100.10"


class ProviderNetworkIsolationError(RuntimeError):
    """Base class for strict provider-network control failures."""


class ProviderNetworkCapabilityError(ProviderNetworkIsolationError):
    """The host cannot prove every required Linux enforcement capability."""


class ProviderNetworkOwnershipError(ProviderNetworkIsolationError):
    """Durable ownership evidence is absent or contradictory."""


class ProviderNetworkEvidenceError(ProviderNetworkIsolationError):
    """Capture or policy evidence is absent, malformed, or contradictory."""


class ProviderNetworkCleanupError(ProviderNetworkIsolationError):
    """Scoped cleanup did not prove exact absence and canary preservation."""


class ProviderNetworkConfigurationError(ProviderNetworkIsolationError):
    """An explicit operational host configuration is unsafe or contradictory."""


@dataclass(frozen=True)
class CommandResult:
    """Bounded result from one shell-free privileged-helper command."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Dependency-injected shell-free command boundary."""

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> CommandResult: ...


class SubprocessCommandRunner:
    """Execute one exact argument vector without a shell."""

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
            raise ProviderNetworkIsolationError(
                f"required helper command failed before completion: {type(exc).__name__}"
            ) from exc
        return CommandResult(
            argv=normalized,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


ForeignCanaryProbe = Callable[[int], Mapping[str, Any]]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _absolute_path(name: str, value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute() or "\0" in str(path):
        raise ValueError(f"{name} must be an absolute NUL-free path")
    return path.resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short evidence write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("short lifecycle evidence write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_mapping(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if required:
            raise ProviderNetworkEvidenceError(
                f"required evidence is absent: {path.name}"
            ) from None
        return None
    if len(raw) > _MAX_COMMAND_OUTPUT_BYTES:
        raise ProviderNetworkEvidenceError(f"evidence is oversized: {path.name}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderNetworkEvidenceError(
            f"evidence is malformed: {path.name}"
        ) from exc
    if not isinstance(value, Mapping):
        raise ProviderNetworkEvidenceError(f"evidence is not a mapping: {path.name}")
    return dict(value)


def _assert_no_sensitive_material(
    value: Any,
    *,
    forbidden_values: Sequence[str] = (),
    path: str = "evidence",
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                raise ProviderNetworkEvidenceError(
                    f"sensitive field is forbidden in {path}: {key_text}"
                )
            _assert_no_sensitive_material(
                item,
                forbidden_values=forbidden_values,
                path=f"{path}.{key_text}",
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_no_sensitive_material(
                item,
                forbidden_values=forbidden_values,
                path=f"{path}[{index}]",
            )
        return
    if isinstance(value, str):
        for forbidden in forbidden_values:
            if forbidden and forbidden in value:
                raise ProviderNetworkEvidenceError(
                    f"forbidden secret material is present in {path}"
                )


def _plain_evidence(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_evidence(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_plain_evidence(item) for item in value]
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderNetworkEvidenceError(f"{name} must be a boolean")
    return value


def _require_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderNetworkEvidenceError(f"{name} must be a nonnegative integer")
    return value


def _canonical_identity_digest(
    *,
    run_id: str,
    contract_sha256: str,
    nonce: str,
    host: str,
    port: int,
) -> str:
    encoded = "\0".join(
        (
            MANIFEST_SCHEMA,
            run_id,
            contract_sha256,
            nonce,
            host,
            str(port),
        )
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _kernel_policy(*, host: str, port: int) -> dict[str, Any]:
    return {
        "mode": "cgroup_bpf_default_deny",
        "hooks": list(REQUIRED_HOOKS),
        "allow": {
            "hook": "connect4",
            "family": "AF_INET",
            "protocol": "tcp",
            "host": host,
            "port": port,
        },
        "deny": {
            "connect4_nonmatching": True,
            "connect6": True,
            "sendmsg4": True,
            "sendmsg6": True,
        },
    }


def _guard_attestation(
    *,
    identity_sha256: str,
    host: str,
    port: int,
    evidence_path_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": PYTHON_GUARD_ATTESTATION_SCHEMA,
        "installed": True,
        "identity_sha256": identity_sha256,
        "policy": "loopback-port-only",
        "allowed_host": host,
        "allowed_port": port,
        "evidence_path_sha256": evidence_path_sha256,
    }


def _validate_provider_budget(provider_budget: Mapping[str, Any]) -> dict[str, Any]:
    required_zero_ints = ("calls", "events_seen", "total_tokens")
    for name in required_zero_ints:
        if provider_budget.get(name) != 0:
            raise ProviderNetworkEvidenceError(f"provider budget {name} is not zero")
    cost = provider_budget.get("total_cost_usd")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or float(cost) != 0:
        raise ProviderNetworkEvidenceError("provider budget total_cost_usd is not zero")
    if provider_budget.get("provider_enabled") is not False:
        raise ProviderNetworkEvidenceError("provider budget must be provider-disabled")
    for name in ("providers", "requested_models", "resolved_models"):
        if provider_budget.get(name) != []:
            raise ProviderNetworkEvidenceError(f"provider budget {name} is not empty")
    return {
        "provider_calls": 0,
        "provider_cost_usd": 0.0,
        "provider_events": 0,
        "provider_tokens": 0,
    }


def validate_provider_network_capture(
    capture: Mapping[str, Any],
    *,
    identity_sha256: str,
    host: str,
    port: int,
    poison_sink_host: str,
    poison_sink_port: int,
    evidence_path_sha256: str,
    provider_budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one final kernel capture and return a secret-free report."""

    _assert_no_sensitive_material(capture, path="kernel capture")
    if capture.get("schema") != SNAPSHOT_SCHEMA:
        raise ProviderNetworkEvidenceError("kernel capture schema mismatch")
    if capture.get("identity_sha256") != identity_sha256:
        raise ProviderNetworkEvidenceError("kernel capture identity mismatch")
    if capture.get("final") is not True:
        raise ProviderNetworkEvidenceError("kernel capture is not final")
    if capture.get("policy") != _kernel_policy(host=host, port=port):
        raise ProviderNetworkEvidenceError("kernel capture policy contradiction")
    hooks = capture.get("hooks")
    if hooks != list(REQUIRED_HOOKS):
        raise ProviderNetworkEvidenceError("kernel capture hooks are incomplete")
    if capture.get("lost_events") != 0:
        raise ProviderNetworkEvidenceError("kernel capture lost events")
    expected_guard = _guard_attestation(
        identity_sha256=identity_sha256,
        host=host,
        port=port,
        evidence_path_sha256=evidence_path_sha256,
    )
    if capture.get("python_guard") != expected_guard:
        raise ProviderNetworkEvidenceError("Python guard attestation contradiction")

    events = capture.get("events")
    if not isinstance(events, list) or len(events) > _MAX_CAPTURE_EVENTS:
        raise ProviderNetworkEvidenceError("kernel capture events are invalid")
    if capture.get("event_count") != len(events):
        raise ProviderNetworkEvidenceError("kernel capture event count mismatch")

    assigned_connections = 0
    dns_connections = 0
    port_443_connections = 0
    poison_sink_connections = 0
    denied_attempts = 0
    denied_dns_attempts = 0
    denied_443_attempts = 0
    denied_poison_attempts = 0
    required_negative_canaries = {
        ("connect4", _NEGATIVE_DNS_HOST, 53),
        ("connect4", _NEGATIVE_HTTPS_HOST, 443),
        ("connect4", poison_sink_host, poison_sink_port),
        ("connect6", "::1", port),
        ("sendmsg4", _NEGATIVE_DNS_HOST, 53),
        ("sendmsg6", "::1", 53),
    }
    observed_negative_canaries: set[tuple[str, str, int]] = set()
    for expected_sequence, raw_event in enumerate(events, start=1):
        if not isinstance(raw_event, Mapping):
            raise ProviderNetworkEvidenceError("kernel capture event is not a mapping")
        event = dict(raw_event)
        if event.get("sequence") != expected_sequence:
            raise ProviderNetworkEvidenceError("kernel capture sequence is not contiguous")
        if event.get("identity_sha256") != identity_sha256:
            raise ProviderNetworkEvidenceError("kernel event identity mismatch")
        hook = event.get("hook")
        if hook not in REQUIRED_HOOKS:
            raise ProviderNetworkEvidenceError("kernel event hook is unsupported")
        expected_operation = "connect" if hook.startswith("connect") else "sendmsg"
        if event.get("operation") != expected_operation:
            raise ProviderNetworkEvidenceError("kernel event operation contradicts hook")
        destination_host = event.get("destination_host")
        destination_port = event.get("destination_port")
        if not isinstance(destination_host, str):
            raise ProviderNetworkEvidenceError("kernel event host is invalid")
        try:
            destination_ip = ipaddress.ip_address(destination_host)
        except ValueError as exc:
            raise ProviderNetworkEvidenceError("kernel event host is invalid") from exc
        expected_ip_version = 4 if hook.endswith("4") else 6
        expected_family = "AF_INET" if expected_ip_version == 4 else "AF_INET6"
        if (
            destination_ip.version != expected_ip_version
            or event.get("family") != expected_family
        ):
            raise ProviderNetworkEvidenceError("kernel event family contradicts hook")
        if (
            isinstance(destination_port, bool)
            or not isinstance(destination_port, int)
            or not 0 <= destination_port <= 65_535
        ):
            raise ProviderNetworkEvidenceError("kernel event port is invalid")
        decision = event.get("decision")
        if decision not in {"allow", "deny"}:
            raise ProviderNetworkEvidenceError("kernel event decision is invalid")
        is_assigned = (
            hook == "connect4"
            and event.get("family") == "AF_INET"
            and event.get("protocol") == "tcp"
            and destination_host == host
            and destination_port == port
        )
        is_dns = destination_port == 53
        is_443 = destination_port == 443
        is_poison = (
            destination_host == poison_sink_host
            and destination_port == poison_sink_port
        )
        if decision == "allow":
            if event.get("errno") != 0 or not is_assigned:
                raise ProviderNetworkEvidenceError(
                    "kernel policy allowed a non-assigned connection"
                )
            assigned_connections += 1
            dns_connections += int(is_dns)
            port_443_connections += int(is_443)
            poison_sink_connections += int(is_poison)
        else:
            if is_assigned:
                raise ProviderNetworkEvidenceError(
                    "kernel policy denied the assigned DFHack connection"
                )
            if event.get("errno") not in {"EACCES", "EPERM"}:
                raise ProviderNetworkEvidenceError(
                    "denied kernel event lacks fail-closed errno"
                )
            denied_attempts += 1
            denied_dns_attempts += int(is_dns)
            denied_443_attempts += int(is_443)
            denied_poison_attempts += int(is_poison)
            canary_identity = (str(hook), destination_host, destination_port)
            if canary_identity in required_negative_canaries:
                observed_negative_canaries.add(canary_identity)

    if assigned_connections < 1:
        raise ProviderNetworkEvidenceError("assigned DFHack connection was not observed")
    if any((dns_connections, port_443_connections, poison_sink_connections)):
        raise ProviderNetworkEvidenceError("forbidden connection was observed")
    if observed_negative_canaries != required_negative_canaries:
        raise ProviderNetworkEvidenceError(
            "kernel negative canary hook coverage is incomplete"
        )

    report = {
        "schema": REPORT_SCHEMA,
        "ok": True,
        "classification": LINUX_CLASSIFICATION,
        "identity_sha256": identity_sha256,
        "dns_connections": 0,
        "port_443_connections": 0,
        "poison_sink_connections": 0,
        "only_assigned_dfhack_connection": True,
        "assigned_dfhack_connections": assigned_connections,
        "denied_attempts": denied_attempts,
        "denied_dns_attempts": denied_dns_attempts,
        "denied_443_attempts": denied_443_attempts,
        "denied_poison_attempts": denied_poison_attempts,
        "negative_canary_attested": True,
        "denied_hooks": list(REQUIRED_HOOKS),
        "lost_events": 0,
        "python_guard_attested": True,
        "kernel_enforcement_attested": True,
    }
    if provider_budget is not None:
        report.update(_validate_provider_budget(provider_budget))
    return report


class ProviderNetworkIsolationController:
    """Own one exact cgroup-BPF provider-network policy and its evidence."""

    def __init__(
        self,
        *,
        run_id: str,
        contract_sha256: str,
        nonce: str,
        assigned_port: int,
        control_root: Path | str,
        gameplay_workspace: Path | str,
        helper_path: Path | str,
        helper_sha256: str,
        bpf_object_path: Path | str,
        bpf_object_sha256: str,
        cgroup_root: Path | str,
        bpffs_root: Path | str,
        foreign_canary_pid: int,
        foreign_canary_probe: ForeignCanaryProbe,
        runner: CommandRunner | None = None,
        poison_sink_host: str = "203.0.113.254",
        poison_sink_port: int = 44_443,
    ) -> None:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise ValueError("run_id must be bounded and filesystem-safe")
        if not _SHA256_RE.fullmatch(contract_sha256):
            raise ValueError("contract_sha256 must be lowercase SHA-256")
        if not _NONCE_RE.fullmatch(nonce):
            raise ValueError("nonce must be a bounded opaque identity")
        if (
            isinstance(assigned_port, bool)
            or not isinstance(assigned_port, int)
            or not 1 <= assigned_port <= 65_535
            or assigned_port in {53, 443}
        ):
            raise ValueError("assigned_port must be a non-provider TCP port")
        try:
            parsed_poison_host = ipaddress.ip_address(poison_sink_host)
        except ValueError as exc:
            raise ValueError("poison_sink_host must be an IP address") from exc
        if parsed_poison_host.version != 4 or poison_sink_host == "127.0.0.1":
            raise ValueError("poison_sink_host must be a non-loopback IPv4 address")
        if (
            isinstance(poison_sink_port, bool)
            or not isinstance(poison_sink_port, int)
            or not 1 <= poison_sink_port <= 65_535
            or (poison_sink_host, poison_sink_port)
            in {(_NEGATIVE_DNS_HOST, 53), (_NEGATIVE_HTTPS_HOST, 443)}
        ):
            raise ValueError("poison_sink endpoint must be valid and canary-distinct")
        if (
            isinstance(foreign_canary_pid, bool)
            or not isinstance(foreign_canary_pid, int)
            or foreign_canary_pid <= 1
        ):
            raise ValueError("foreign_canary_pid must be a positive non-init PID")
        if not callable(foreign_canary_probe):
            raise TypeError("foreign_canary_probe must be callable")
        if not _SHA256_RE.fullmatch(helper_sha256):
            raise ValueError("helper_sha256 must be lowercase SHA-256")
        if not _SHA256_RE.fullmatch(bpf_object_sha256):
            raise ValueError("bpf_object_sha256 must be lowercase SHA-256")

        selected_control_root = _absolute_path("control_root", control_root)
        selected_workspace = _absolute_path("gameplay_workspace", gameplay_workspace)
        selected_helper = _absolute_path("helper_path", helper_path)
        selected_object = _absolute_path("bpf_object_path", bpf_object_path)
        selected_cgroup_root = _absolute_path("cgroup_root", cgroup_root)
        selected_bpffs_root = _absolute_path("bpffs_root", bpffs_root)
        if not selected_helper.is_file() or not selected_object.is_file():
            raise ValueError("helper and BPF object must be existing regular files")
        if not os.access(selected_helper, os.X_OK):
            raise ValueError("helper binary must be executable")
        if _sha256_file(selected_helper) != helper_sha256:
            raise ValueError("helper binary digest mismatch")
        if _sha256_file(selected_object) != bpf_object_sha256:
            raise ValueError("BPF object digest mismatch")

        evidence_dir = (selected_control_root / run_id / "provider-network").resolve()
        if not _is_within(evidence_dir, selected_control_root / run_id):
            raise ValueError("evidence directory escaped the run control root")
        if _is_within(evidence_dir, selected_workspace) or _is_within(
            selected_workspace, evidence_dir
        ):
            raise ValueError("network evidence and gameplay workspace must be disjoint")

        self.run_id = run_id
        self.contract_sha256 = contract_sha256
        self._nonce = nonce
        self.assigned_host = "127.0.0.1"
        self.assigned_port = assigned_port
        self.control_root = selected_control_root
        self.gameplay_workspace = selected_workspace
        self.helper_path = selected_helper
        self.helper_sha256 = helper_sha256
        self.bpf_object_path = selected_object
        self.bpf_object_sha256 = bpf_object_sha256
        self.foreign_canary_pid = foreign_canary_pid
        self.foreign_canary_probe = foreign_canary_probe
        self.runner = runner or SubprocessCommandRunner()
        self.poison_sink_host = str(parsed_poison_host)
        self.poison_sink_port = poison_sink_port
        self.evidence_dir = evidence_dir
        self.identity_sha256 = _canonical_identity_digest(
            run_id=run_id,
            contract_sha256=contract_sha256,
            nonce=nonce,
            host=self.assigned_host,
            port=assigned_port,
        )
        resource_name = f"{run_id}-{self.identity_sha256[:16]}"
        self.cgroup_path = (selected_cgroup_root / resource_name).resolve()
        self.pin_root = (selected_bpffs_root / resource_name).resolve()
        if not _is_within(self.cgroup_path, selected_cgroup_root):
            raise ValueError("derived cgroup path escaped cgroup_root")
        if not _is_within(self.pin_root, selected_bpffs_root):
            raise ValueError("derived pin path escaped bpffs_root")

    def __repr__(self) -> str:
        return (
            "ProviderNetworkIsolationController("
            f"run_id={self.run_id!r}, identity_sha256={self.identity_sha256!r}, "
            f"assigned_endpoint={self.assigned_host}:{self.assigned_port})"
        )

    @property
    def manifest_path(self) -> Path:
        return self.evidence_dir / "ownership.json"

    @property
    def capture_path(self) -> Path:
        return self.evidence_dir / "kernel-connect-capture.json"

    @property
    def python_denials_path(self) -> Path:
        return self.evidence_dir / "python-network-denials.jsonl"

    @property
    def guard_attestation_path(self) -> Path:
        return self.evidence_dir / "python-guard-attestation.json"

    @property
    def lifecycle_path(self) -> Path:
        return self.evidence_dir / "lifecycle.jsonl"

    @property
    def kernel_policy(self) -> dict[str, Any]:
        return _kernel_policy(host=self.assigned_host, port=self.assigned_port)

    def public_identity(self) -> dict[str, Any]:
        """Return the bounded non-secret identity safe for terminal evidence."""

        return {
            "schema": MANIFEST_SCHEMA,
            "classification": LINUX_CLASSIFICATION,
            "integration_status": INTEGRATION_STATUS,
            "run_id": self.run_id,
            "contract_sha256": self.contract_sha256,
            "identity_sha256": self.identity_sha256,
            "assigned_host": self.assigned_host,
            "assigned_port": self.assigned_port,
            "poison_sink_host": self.poison_sink_host,
            "poison_sink_port": self.poison_sink_port,
            "nonce_matched": True,
        }

    def python_guard_environment(self) -> dict[str, str]:
        """Return the existing early-Python guard contract for this attempt."""

        return {
            "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
            "FORT_GYM_NETWORK_ALLOWED_HOST": self.assigned_host,
            "FORT_GYM_NETWORK_ALLOWED_PORT": str(self.assigned_port),
            "FORT_GYM_NETWORK_EVIDENCE_PATH": str(self.python_denials_path),
            "FORT_GYM_RUN_ID": self.run_id,
            "FORT_GYM_RUN_CONTRACT_SHA256": self.contract_sha256,
            "FORT_GYM_RUN_NONCE": self._nonce,
        }

    def integration_requirements(self) -> tuple[str, ...]:
        """Describe the explicit supervisor contract required for execution."""

        return (
            "pass this exact controller explicitly to ProcessSupervisor.run",
            "retain the supervisor-owned assigned port lease through cleanup",
            "retain enter_argv and inner canonical worker argv with pinned wrapper journal",
            "validate final capture and zero-spend evidence before terminalization",
            "reconcile only exact manifest-owned resources after orphan reaping",
            "fail closed when any helper capability or durable identity is absent",
        )

    def probe_argv(self) -> tuple[str, ...]:
        return (
            str(self.helper_path),
            "probe",
            "--bpf-object",
            str(self.bpf_object_path),
            "--format",
            "json",
        )

    def prepare_argv(self) -> tuple[str, ...]:
        return (
            str(self.helper_path),
            "prepare",
            "--bpf-object",
            str(self.bpf_object_path),
            "--expected-helper-sha256",
            self.helper_sha256,
            "--expected-bpf-object-sha256",
            self.bpf_object_sha256,
            "--cgroup",
            str(self.cgroup_path),
            "--pin-root",
            str(self.pin_root),
            "--identity-sha256",
            self.identity_sha256,
            "--allow-connect4",
            f"{self.assigned_host}:{self.assigned_port}",
            "--negative-canary-poison",
            f"{self.poison_sink_host}:{self.poison_sink_port}",
            "--deny-connect6",
            "--deny-sendmsg4",
            "--deny-sendmsg6",
            "--format",
            "json",
        )

    def enter_argv(self, child_argv: Sequence[str]) -> tuple[str, ...]:
        """Return the required join-before-exec wrapper for the harness."""

        normalized = tuple(str(item) for item in child_argv)
        if not normalized or not normalized[0] or any("\0" in item for item in normalized):
            raise ValueError("child_argv must be a non-empty NUL-free vector")
        return (
            str(self.helper_path),
            "enter",
            "--cgroup",
            str(self.cgroup_path),
            "--identity-sha256",
            self.identity_sha256,
            "--require-python-policy",
            "loopback-port-only",
            "--guard-attestation",
            str(self.guard_attestation_path),
            "--",
            *normalized,
        )

    def snapshot_argv(self) -> tuple[str, ...]:
        return (
            str(self.helper_path),
            "snapshot",
            "--cgroup",
            str(self.cgroup_path),
            "--pin-root",
            str(self.pin_root),
            "--identity-sha256",
            self.identity_sha256,
            "--guard-attestation",
            str(self.guard_attestation_path),
            "--format",
            "json",
        )

    def inspect_argv(self) -> tuple[str, ...]:
        return (
            str(self.helper_path),
            "inspect",
            "--cgroup",
            str(self.cgroup_path),
            "--pin-root",
            str(self.pin_root),
            "--identity-sha256",
            self.identity_sha256,
            "--format",
            "json",
        )

    def cleanup_argv(self) -> tuple[str, ...]:
        return (
            str(self.helper_path),
            "cleanup",
            "--cgroup",
            str(self.cgroup_path),
            "--pin-root",
            str(self.pin_root),
            "--identity-sha256",
            self.identity_sha256,
            "--format",
            "json",
        )

    def _run_json(
        self,
        argv: Sequence[str],
        *,
        operation: str,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        normalized = tuple(str(item) for item in argv)
        try:
            result = self.runner.run(normalized, timeout_seconds=timeout_seconds)
        except Exception:  # noqa: BLE001 - redact injected runner failures
            raise ProviderNetworkIsolationError(
                f"required helper {operation} command failed before completion"
            ) from None
        if tuple(result.argv) != normalized:
            raise ProviderNetworkIsolationError(
                f"required helper {operation} command identity mismatch"
            )
        if result.returncode != 0:
            raise ProviderNetworkIsolationError(
                f"required helper {operation} command failed closed"
            )
        raw = result.stdout.encode("utf-8", errors="replace")
        if len(raw) > _MAX_COMMAND_OUTPUT_BYTES:
            raise ProviderNetworkIsolationError(
                f"required helper {operation} output is oversized"
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderNetworkIsolationError(
                f"required helper {operation} output is malformed"
            ) from exc
        if not isinstance(value, Mapping):
            raise ProviderNetworkIsolationError(
                f"required helper {operation} output is not a mapping"
            )
        normalized_value = dict(value)
        _assert_no_sensitive_material(
            normalized_value,
            forbidden_values=(self._nonce,),
            path=f"helper.{operation}",
        )
        return normalized_value

    def _probe_canary(self) -> dict[str, Any]:
        try:
            raw = self.foreign_canary_probe(self.foreign_canary_pid)
        except Exception:  # noqa: BLE001 - redact injected probe failures
            raise ProviderNetworkIsolationError("foreign canary probe failed") from None
        if not isinstance(raw, Mapping):
            raise ProviderNetworkIsolationError("foreign canary probe is invalid")
        if raw.get("pid") != self.foreign_canary_pid or raw.get("alive") is not True:
            raise ProviderNetworkIsolationError("foreign canary is not live")
        identity = raw.get("identity_sha256")
        cgroup = raw.get("cgroup")
        if not isinstance(identity, str) or not _SHA256_RE.fullmatch(identity):
            raise ProviderNetworkIsolationError("foreign canary identity is invalid")
        if not isinstance(cgroup, str) or not cgroup.startswith("/") or "\0" in cgroup:
            raise ProviderNetworkIsolationError("foreign canary cgroup is invalid")
        return {
            "pid": self.foreign_canary_pid,
            "alive": True,
            "identity_sha256": identity,
            "cgroup": cgroup,
        }

    @staticmethod
    def _same_canary(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
        return dict(first) == dict(second)

    def _validate_capabilities(self, payload: Mapping[str, Any]) -> None:
        expected = {
            "schema": CAPABILITY_SCHEMA,
            "ok": True,
            "os": "linux",
            "architecture": "x86_64",
            "cgroup_version": 2,
            "bpffs": True,
            "cgroup_bpf": True,
            "default_deny": True,
            "structured_capture": True,
            "join_before_exec": True,
            "hooks": list(REQUIRED_HOOKS),
            "helper_sha256": self.helper_sha256,
            "bpf_object_sha256": self.bpf_object_sha256,
        }
        if dict(payload) != expected:
            raise ProviderNetworkCapabilityError(
                "required isolated-x86 Linux network capabilities are absent"
            )

    def _validate_prepare(self, payload: Mapping[str, Any]) -> None:
        expected = {
            "schema": PREPARE_SCHEMA,
            "ok": True,
            "identity_sha256": self.identity_sha256,
            "cgroup_path": str(self.cgroup_path),
            "pin_root": str(self.pin_root),
            "policy": self.kernel_policy,
            "hooks": list(REQUIRED_HOOKS),
            "evidence_external": True,
        }
        if dict(payload) != expected:
            raise ProviderNetworkEvidenceError("kernel prepare evidence mismatch")

    def _validate_inspect(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if payload.get("schema") != INSPECT_SCHEMA or payload.get("ok") is not True:
            raise ProviderNetworkEvidenceError("kernel residue inspection failed")
        if payload.get("identity_sha256") != self.identity_sha256:
            raise ProviderNetworkOwnershipError("kernel residue identity mismatch")
        cgroup_exists = _require_bool(payload.get("cgroup_exists"), "cgroup_exists")
        pins_exist = _require_bool(payload.get("pins_exist"), "pins_exist")
        members = payload.get("member_pids")
        if (
            not isinstance(members, list)
            or any(
                isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1
                for pid in members
            )
            or len(set(members)) != len(members)
        ):
            raise ProviderNetworkEvidenceError("kernel residue members are invalid")
        if members and not cgroup_exists:
            raise ProviderNetworkEvidenceError("members reported for absent cgroup")
        return {
            "cgroup_exists": cgroup_exists,
            "pins_exist": pins_exist,
            "member_pids": list(members),
        }

    def _manifest_payload(
        self,
        *,
        state: str,
        foreign_canary: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            **self.public_identity(),
            "state": state,
            "helper_sha256": self.helper_sha256,
            "bpf_object_sha256": self.bpf_object_sha256,
            "cgroup_path": str(self.cgroup_path),
            "pin_root": str(self.pin_root),
            "evidence_dir": str(self.evidence_dir),
            "foreign_canary": dict(foreign_canary),
        }

    def _load_manifest(self, *, required: bool = True) -> dict[str, Any] | None:
        manifest = _load_mapping(self.manifest_path, required=required)
        if manifest is None:
            return None
        _assert_no_sensitive_material(
            manifest,
            forbidden_values=(self._nonce,),
            path="ownership manifest",
        )
        state = manifest.get("state")
        canary = manifest.get("foreign_canary")
        if state not in {"preparing", "prepared", "cleaned"} or not isinstance(
            canary, Mapping
        ):
            raise ProviderNetworkOwnershipError("ownership manifest is malformed")
        expected = self._manifest_payload(state=str(state), foreign_canary=canary)
        if manifest != expected:
            raise ProviderNetworkOwnershipError("ownership manifest identity mismatch")
        return manifest

    def _inspect(self) -> dict[str, Any]:
        return self._validate_inspect(
            self._run_json(self.inspect_argv(), operation="inspect")
        )

    def prepare(self) -> Mapping[str, Any]:
        """Attest capabilities and attach a deny-default policy before launch."""

        self.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.manifest_path.exists():
            raise ProviderNetworkOwnershipError(
                "provider-network ownership manifest already exists"
            )
        if (
            _sha256_file(self.helper_path) != self.helper_sha256
            or _sha256_file(self.bpf_object_path) != self.bpf_object_sha256
        ):
            raise ProviderNetworkCapabilityError(
                "pinned provider-network artifact changed before probe"
            )
        capabilities = self._run_json(self.probe_argv(), operation="probe")
        self._validate_capabilities(capabilities)
        if (
            _sha256_file(self.helper_path) != self.helper_sha256
            or _sha256_file(self.bpf_object_path) != self.bpf_object_sha256
        ):
            raise ProviderNetworkCapabilityError(
                "pinned provider-network artifact changed after probe"
            )
        foreign_canary = self._probe_canary()
        _atomic_json(
            self.manifest_path,
            self._manifest_payload(state="preparing", foreign_canary=foreign_canary),
        )
        prepared = self._run_json(self.prepare_argv(), operation="prepare")
        self._validate_prepare(prepared)
        if (
            _sha256_file(self.helper_path) != self.helper_sha256
            or _sha256_file(self.bpf_object_path) != self.bpf_object_sha256
        ):
            raise ProviderNetworkCapabilityError(
                "pinned provider-network artifact changed during prepare"
            )
        _atomic_json(
            self.manifest_path,
            self._manifest_payload(state="prepared", foreign_canary=foreign_canary),
        )
        result = {
            "schema": PREPARE_SCHEMA,
            "ok": True,
            "identity": self.public_identity(),
            "policy": self.kernel_policy,
            "foreign_canary": foreign_canary,
            "launch_integration": INTEGRATION_STATUS,
        }
        _append_jsonl(self.lifecycle_path, {"event": "prepared", **result})
        return result

    def _capture(self) -> dict[str, Any]:
        capture = self._run_json(self.snapshot_argv(), operation="snapshot")
        report = validate_provider_network_capture(
            capture,
            identity_sha256=self.identity_sha256,
            host=self.assigned_host,
            port=self.assigned_port,
            poison_sink_host=self.poison_sink_host,
            poison_sink_port=self.poison_sink_port,
            evidence_path_sha256=_sha256_bytes(
                str(self.python_denials_path).encode("utf-8")
            ),
        )
        _atomic_json(self.capture_path, capture)
        return report

    def _validate_cleanup_result(self, payload: Mapping[str, Any]) -> None:
        expected = {
            "schema": CLEANUP_SCHEMA,
            "ok": True,
            "identity_sha256": self.identity_sha256,
            "cgroup_absent": True,
            "pins_absent": True,
        }
        if dict(payload) != expected:
            raise ProviderNetworkCleanupError("kernel cleanup evidence mismatch")

    def abort(self, *, recovered: bool = False) -> Mapping[str, Any]:
        """Detach an owned policy when no harness child was successfully launched.

        No connection capture is required because the supervisor durably proves
        that ``Popen`` never returned a child. Ownership, empty membership,
        exact residue, and the foreign canary are still validated fail closed.
        """

        manifest = self._load_manifest(required=False)
        before = self._inspect()
        if manifest is None:
            if before["cgroup_exists"] or before["pins_exist"] or before["member_pids"]:
                raise ProviderNetworkOwnershipError(
                    "managed-looking network resources lack an ownership manifest"
                )
            canary = self._probe_canary()
            result = {
                "schema": CLEANUP_SCHEMA,
                "ok": True,
                "aborted_before_launch": True,
                "already_absent": True,
                "recovered": recovered,
                "identity": self.public_identity(),
                "foreign_canary_untouched": True,
                "foreign_canary": canary,
            }
            _append_jsonl(self.lifecycle_path, {"event": "abort_noop", **result})
            return result

        baseline_raw = manifest["foreign_canary"]
        assert isinstance(baseline_raw, Mapping)
        baseline = dict(baseline_raw)
        current_canary = self._probe_canary()
        if not self._same_canary(baseline, current_canary):
            raise ProviderNetworkCleanupError("foreign canary identity changed")
        if before["member_pids"]:
            raise ProviderNetworkCleanupError(
                "prelaunch provider-network cgroup unexpectedly has members"
            )

        already_absent = not before["cgroup_exists"] and not before["pins_exist"]
        if not already_absent:
            cleanup_payload = self._run_json(self.cleanup_argv(), operation="cleanup")
            self._validate_cleanup_result(cleanup_payload)
        after = self._inspect()
        if after["cgroup_exists"] or after["pins_exist"] or after["member_pids"]:
            raise ProviderNetworkCleanupError(
                "provider-network prelaunch residue remains"
            )
        final_canary = self._probe_canary()
        if not self._same_canary(baseline, final_canary):
            raise ProviderNetworkCleanupError("foreign canary was disturbed")
        _atomic_json(
            self.manifest_path,
            self._manifest_payload(state="cleaned", foreign_canary=baseline),
        )
        result = {
            "schema": CLEANUP_SCHEMA,
            "ok": True,
            "aborted_before_launch": True,
            "already_absent": already_absent,
            "recovered": recovered,
            "identity": self.public_identity(),
            "residue": after,
            "foreign_canary_untouched": True,
            "foreign_canary": final_canary,
        }
        _append_jsonl(
            self.lifecycle_path,
            {"event": "abort_reconciled" if recovered else "aborted", **result},
        )
        return result

    def _cleanup(self, *, recovered: bool) -> Mapping[str, Any]:
        manifest = self._load_manifest(required=False)
        before = self._inspect()
        if manifest is None:
            if before["cgroup_exists"] or before["pins_exist"] or before["member_pids"]:
                raise ProviderNetworkOwnershipError(
                    "managed-looking network resources lack an ownership manifest"
                )
            canary = self._probe_canary()
            return {
                "schema": CLEANUP_SCHEMA,
                "ok": True,
                "already_absent": True,
                "recovered": recovered,
                "identity": self.public_identity(),
                "foreign_canary_untouched": True,
                "foreign_canary": canary,
            }

        baseline_canary_raw = manifest["foreign_canary"]
        assert isinstance(baseline_canary_raw, Mapping)
        baseline_canary = dict(baseline_canary_raw)
        current_canary = self._probe_canary()
        if not self._same_canary(baseline_canary, current_canary):
            raise ProviderNetworkCleanupError("foreign canary identity changed")

        if manifest["state"] == "cleaned":
            if before["cgroup_exists"] or before["pins_exist"] or before["member_pids"]:
                raise ProviderNetworkCleanupError(
                    "cleaned ownership manifest contradicts live residue"
                )
            retained_capture = _load_mapping(self.capture_path, required=True)
            assert retained_capture is not None
            _assert_no_sensitive_material(
                retained_capture,
                forbidden_values=(self._nonce,),
                path="retained kernel capture",
            )
            validate_provider_network_capture(
                retained_capture,
                identity_sha256=self.identity_sha256,
                host=self.assigned_host,
                port=self.assigned_port,
                poison_sink_host=self.poison_sink_host,
                poison_sink_port=self.poison_sink_port,
                evidence_path_sha256=_sha256_bytes(
                    str(self.python_denials_path).encode("utf-8")
                ),
            )
            result = {
                "schema": CLEANUP_SCHEMA,
                "ok": True,
                "already_absent": True,
                "recovered": recovered,
                "identity": self.public_identity(),
                "foreign_canary_untouched": True,
                "foreign_canary": current_canary,
            }
            _append_jsonl(self.lifecycle_path, {"event": "cleanup_noop", **result})
            return result

        if before["member_pids"]:
            raise ProviderNetworkCleanupError(
                "harness cgroup still has members; refusing to detach enforcement"
            )
        if not before["cgroup_exists"] or not before["pins_exist"]:
            raise ProviderNetworkCleanupError(
                "provider-network resources disappeared before evidence snapshot"
            )

        capture_report = self._capture()
        cleanup_payload = self._run_json(self.cleanup_argv(), operation="cleanup")
        self._validate_cleanup_result(cleanup_payload)
        after = self._inspect()
        if after["cgroup_exists"] or after["pins_exist"] or after["member_pids"]:
            raise ProviderNetworkCleanupError("provider-network residue remains")
        final_canary = self._probe_canary()
        if not self._same_canary(baseline_canary, final_canary):
            raise ProviderNetworkCleanupError("foreign canary was disturbed")

        _atomic_json(
            self.manifest_path,
            self._manifest_payload(state="cleaned", foreign_canary=baseline_canary),
        )
        result = {
            "schema": CLEANUP_SCHEMA,
            "ok": True,
            "already_absent": False,
            "recovered": recovered,
            "identity": self.public_identity(),
            "capture": capture_report,
            "residue": after,
            "foreign_canary_untouched": True,
            "foreign_canary": final_canary,
        }
        _append_jsonl(self.lifecycle_path, {"event": "reconciled" if recovered else "cleaned", **result})
        return result

    def cleanup(self) -> Mapping[str, Any]:
        """Snapshot, detach, and prove exact absence; safe to call twice."""

        return self._cleanup(recovered=False)

    def reconcile(self) -> Mapping[str, Any]:
        """Recover only exact manifest-owned resources; never infer ownership."""

        return self._cleanup(recovered=True)

    def residue(self) -> Mapping[str, Any]:
        """Inspect exact managed residue and prove the foreign canary is unchanged."""

        manifest = self._load_manifest(required=False)
        inspection = self._inspect()
        canary = self._probe_canary()
        canary_untouched = True
        if manifest is not None:
            baseline = manifest.get("foreign_canary")
            canary_untouched = isinstance(baseline, Mapping) and self._same_canary(
                baseline, canary
            )
        ok = (
            not inspection["cgroup_exists"]
            and not inspection["pins_exist"]
            and not inspection["member_pids"]
            and canary_untouched
        )
        return {
            "schema": INSPECT_SCHEMA,
            "ok": ok,
            "identity": self.public_identity(),
            "residue": inspection,
            "foreign_canary_untouched": canary_untouched,
            "foreign_canary": canary,
        }

    def validate_evidence(self, provider_budget: Mapping[str, Any]) -> Mapping[str, Any]:
        """Validate retained final capture plus the exact zero-spend budget."""

        capture = _load_mapping(self.capture_path, required=True)
        assert capture is not None
        _assert_no_sensitive_material(
            capture,
            forbidden_values=(self._nonce,),
            path="kernel capture",
        )
        return validate_provider_network_capture(
            capture,
            identity_sha256=self.identity_sha256,
            host=self.assigned_host,
            port=self.assigned_port,
            poison_sink_host=self.poison_sink_host,
            poison_sink_port=self.poison_sink_port,
            evidence_path_sha256=_sha256_bytes(
                str(self.python_denials_path).encode("utf-8")
            ),
            provider_budget=provider_budget,
        )


@dataclass(frozen=True)
class ProviderNetworkHostConfig:
    """Pinned, non-ambient construction authority for the Linux host control.

    This immutable value is intentionally not populated from environment
    variables or API input.  Its service factory accepts only the canonical
    provider-free scripted DFHack ``RuntimeContract`` and the exact first
    attempt ``RunSpec`` persisted by ``SupervisionService``.  Reconstructing
    the same inputs therefore produces the same public controller identity
    without serializing the private runtime nonce.
    """

    helper_path: Path
    helper_sha256: str
    bpf_object_path: Path
    bpf_object_sha256: str
    cgroup_root: Path
    bpffs_root: Path
    foreign_canary_pid: int
    foreign_canary_probe: ForeignCanaryProbe = field(repr=False, compare=False)
    poison_sink_host: str = "203.0.113.254"
    poison_sink_port: int = 44_443
    runner: CommandRunner | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        selected_paths = {
            "helper_path": _absolute_path("helper_path", self.helper_path),
            "bpf_object_path": _absolute_path(
                "bpf_object_path", self.bpf_object_path
            ),
            "cgroup_root": _absolute_path("cgroup_root", self.cgroup_root),
            "bpffs_root": _absolute_path("bpffs_root", self.bpffs_root),
        }
        for name, path in selected_paths.items():
            object.__setattr__(self, name, path)
        if selected_paths["cgroup_root"] != Path(
            "/sys/fs/cgroup/fortgym-provider-net"
        ):
            raise ProviderNetworkConfigurationError(
                "cgroup_root must match the pinned helper root"
            )
        if selected_paths["bpffs_root"] != Path("/sys/fs/bpf/fortgym-provider-net"):
            raise ProviderNetworkConfigurationError(
                "bpffs_root must match the pinned helper root"
            )
        helper_path = selected_paths["helper_path"]
        object_path = selected_paths["bpf_object_path"]
        if not helper_path.is_file() or not os.access(helper_path, os.X_OK):
            raise ProviderNetworkConfigurationError(
                "helper_path must name an executable regular file"
            )
        if not object_path.is_file():
            raise ProviderNetworkConfigurationError(
                "bpf_object_path must name a regular file"
            )
        if not isinstance(self.helper_sha256, str) or not _SHA256_RE.fullmatch(
            self.helper_sha256
        ):
            raise ProviderNetworkConfigurationError(
                "helper_sha256 must be lowercase SHA-256"
            )
        if not isinstance(self.bpf_object_sha256, str) or not _SHA256_RE.fullmatch(
            self.bpf_object_sha256
        ):
            raise ProviderNetworkConfigurationError(
                "bpf_object_sha256 must be lowercase SHA-256"
            )
        if _sha256_file(helper_path) != self.helper_sha256:
            raise ProviderNetworkConfigurationError("helper binary digest mismatch")
        if _sha256_file(object_path) != self.bpf_object_sha256:
            raise ProviderNetworkConfigurationError("BPF object digest mismatch")
        if (
            isinstance(self.foreign_canary_pid, bool)
            or not isinstance(self.foreign_canary_pid, int)
            or self.foreign_canary_pid <= 1
        ):
            raise ProviderNetworkConfigurationError(
                "foreign_canary_pid must be a positive non-init integer"
            )
        if not callable(self.foreign_canary_probe):
            raise ProviderNetworkConfigurationError(
                "foreign_canary_probe must be callable"
            )
        if self.runner is not None and not callable(getattr(self.runner, "run", None)):
            raise ProviderNetworkConfigurationError("runner must define run()")
        try:
            poison = ipaddress.ip_address(self.poison_sink_host)
        except ValueError as exc:
            raise ProviderNetworkConfigurationError(
                "poison_sink_host must be an IPv4 address"
            ) from exc
        if poison.version != 4 or poison.is_loopback:
            raise ProviderNetworkConfigurationError(
                "poison_sink_host must be a non-loopback IPv4 address"
            )
        if (
            isinstance(self.poison_sink_port, bool)
            or not isinstance(self.poison_sink_port, int)
            or not 1 <= self.poison_sink_port <= 65_535
        ):
            raise ProviderNetworkConfigurationError(
                "poison_sink_port must be an integer in the TCP port range"
            )

    def service_factory(self) -> Callable[[Any, Path, Any, Any], ProviderNetworkIsolationController]:
        """Return the explicit constructor-only SupervisionService factory."""

        pinned = self

        def build(
            contract: Any,
            run_dir: Path,
            runtime_controller: Any,
            spec: Any,
        ) -> ProviderNetworkIsolationController:
            # Local imports avoid coupling the standalone host controller to
            # service/API modules at import time.
            from .process_supervisor import RunSpec
            from .runtime_contract import RuntimeContract

            if not isinstance(contract, RuntimeContract):
                raise ProviderNetworkConfigurationError(
                    "provider-network factory requires a RuntimeContract"
                )
            if not isinstance(spec, RunSpec):
                raise ProviderNetworkConfigurationError(
                    "provider-network factory requires a RunSpec"
                )
            if runtime_controller is None:
                raise ProviderNetworkConfigurationError(
                    "provider-network factory requires the bound runtime controller"
                )
            expected_run_dir = (contract.control_root / contract.run_id).resolve(
                strict=False
            )
            expected_attempt = (
                expected_run_dir / "attempts" / "attempt-0001"
            ).resolve(strict=False)
            expected_workspace = (
                contract.artifacts_root / contract.run_id
            ).resolve(strict=False)
            expected_trace = (expected_workspace / "trace.jsonl").resolve(
                strict=False
            )
            expected_env = contract.child_environment(attempt_dir=expected_attempt)
            if (
                contract.backend != "dfhack"
                or contract.model != "dfhack-governed-scripted"
                or contract.scripted is not True
                or contract.provider.enabled is not False
                or Path(run_dir).resolve(strict=False) != expected_run_dir
                or spec.run_id != contract.run_id
                or spec.artifact_dir.resolve(strict=False) != expected_attempt
                or spec.trace_path is None
                or spec.trace_path.resolve(strict=False) != expected_trace
                or spec.port != contract.port
                or spec.scripted is not True
                or spec.provider_enabled is not False
                or _plain_evidence(spec.environment_identity)
                != contract.environment_identity()
                or dict(spec.env) != expected_env
                or tuple(spec.env_allowlist) != tuple(sorted(expected_env))
                or spec.port_lock_dir.resolve(strict=False)
                != (contract.control_root / "port-leases").resolve(strict=False)
            ):
                raise ProviderNetworkConfigurationError(
                    "service runtime/run/attempt identity is contradictory"
                )
            return ProviderNetworkIsolationController(
                run_id=contract.run_id,
                contract_sha256=contract.contract_sha256,
                nonce=contract.nonce,
                assigned_port=contract.port,
                control_root=contract.control_root,
                gameplay_workspace=expected_workspace,
                helper_path=pinned.helper_path,
                helper_sha256=pinned.helper_sha256,
                bpf_object_path=pinned.bpf_object_path,
                bpf_object_sha256=pinned.bpf_object_sha256,
                cgroup_root=pinned.cgroup_root,
                bpffs_root=pinned.bpffs_root,
                foreign_canary_pid=pinned.foreign_canary_pid,
                foreign_canary_probe=pinned.foreign_canary_probe,
                runner=pinned.runner,
                poison_sink_host=pinned.poison_sink_host,
                poison_sink_port=pinned.poison_sink_port,
            )

        return build


__all__ = [
    "CAPABILITY_SCHEMA",
    "CLEANUP_SCHEMA",
    "INSPECT_SCHEMA",
    "INTEGRATION_STATUS",
    "LINUX_CLASSIFICATION",
    "MANIFEST_SCHEMA",
    "PREPARE_SCHEMA",
    "PYTHON_GUARD_ATTESTATION_SCHEMA",
    "REPORT_SCHEMA",
    "REQUIRED_HOOKS",
    "SNAPSHOT_SCHEMA",
    "CommandResult",
    "CommandRunner",
    "ProviderNetworkCapabilityError",
    "ProviderNetworkCleanupError",
    "ProviderNetworkConfigurationError",
    "ProviderNetworkEvidenceError",
    "ProviderNetworkHostConfig",
    "ProviderNetworkIsolationController",
    "ProviderNetworkIsolationError",
    "ProviderNetworkOwnershipError",
    "SubprocessCommandRunner",
    "validate_provider_network_capture",
]
