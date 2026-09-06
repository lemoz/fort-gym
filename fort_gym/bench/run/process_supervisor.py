"""Fail-closed process supervision primitives for isolated Fort Gym runs.

The supervisor is intentionally independent of the API and Docker layers. It
owns one harness process group, observes its durable trace, and writes a
terminal record only after process and caller-supplied cleanup have completed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any, Protocol, Self

from . import fault_classification as _fault_classification
from .fault_classification import (
    FAULT_CLASSIFICATION_RECORD_SCHEMA,
    FAULT_OBSERVATION_SCHEMA,
    FaultClassificationError,
    validate_fault_classifier_result,
    validate_pre_readiness_oom_receipt,
)
from .fault_session import (
    PRE_CLEANUP_OBSERVATION_SCHEMA,
    FaultSessionEvidenceError,
    validate_pre_cleanup_snapshot,
)

try:  # pragma: no cover - exercised on POSIX in CI
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - POSIX does not provide msvcrt
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX in CI
    msvcrt = None  # type: ignore[assignment]


DEFAULT_MAX_TOTAL_TOKENS = 128_000
DEFAULT_MAX_COST_USD = 25.0
DEFAULT_ENV_ALLOWLIST = frozenset(
    {
        "LANG",
        "LC_ALL",
        "PATH",
        "SYSTEMROOT",
        "TMPDIR",
        "TMP",
        "TEMP",
    }
)
OPENROUTER_TOOL = "openrouter.chat.completions.create"
PROVIDER_NETWORK_LAUNCH_SCHEMA = "fortgym.provider-network-launch/v1"
PROVIDER_NETWORK_INTEGRATION_STATUS = "process-supervisor-atomic-wrapper-v1"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_TRUSTED_PREPARE_TERMINAL_CODES = frozenset(
    {
        "container_create_failure",
        "rpc_readiness_timeout",
        "map_readiness_timeout",
    }
)
_MAX_EVIDENCE_MAPPING_BYTES = 16_384
_MAX_EVIDENCE_DEPTH = 8
_MAX_EVIDENCE_NODES = 512
EVIDENCE_SNAPSHOT_SCHEMA = "fortgym.process-supervisor-evidence-snapshot/v1"
TERMINAL_CHAIN_EVENTS = (
    "terminal_pending_cleanup",
    "evidence_snapshot_completed",
    "harness_process_group_reaped",
    "runtime_container_removed",
    "cleanup_verified",
    "cleanup_completed",
    "immutable_terminal_classification",
)


class TerminalClass(str, Enum):
    """Exhaustive terminal classes emitted by this supervisor core."""

    COMPLETED = "completed"
    CHILD_EXIT = "child_exit"
    PORT_POLICY_FAILURE = "port_policy_failure"
    PREPARE_FAILURE = "prepare_failure"
    EXTERNAL_SIGNAL = "external_signal"
    CAP_TRIP = "cap_trip"
    PROVIDER_PIN_VIOLATION = "provider_pin_violation"
    TIMEOUT = "timeout"
    CLEANUP_FAILURE = "cleanup_failure"
    RUNTIME_DF_KILLED = "runtime_df_killed"
    HARNESS_KILLED = "harness_killed"
    RUNTIME_OOM = "runtime_oom"
    WORKSPACE_ENOSPC = "workspace_enospc"
    RUNTIME_CONTAINER_RESTARTED = "runtime_container_restarted"
    DOCKER_DAEMON_RESTARTED = "docker_daemon_restarted"
    RUNTIME_FAULT_CLASSIFICATION_FAILURE = (
        _fault_classification.RUNTIME_FAULT_CLASSIFICATION_FAILURE
    )


class SupervisorError(RuntimeError):
    """Base class for supervisor configuration and durability errors."""


class PortLeaseError(SupervisorError):
    """The requested host port could not be leased safely."""


class PortLeaseBusy(PortLeaseError):
    """Another supervisor already holds the host-wide lease."""


class PortUnavailable(PortLeaseError):
    """The leased port is already bound outside the supervisor."""


class RuntimePrepareError(SupervisorError):
    """The caller-owned runtime prepare phase failed before child launch."""


class ProviderNetworkPrepareError(SupervisorError):
    """The explicit provider-network boundary failed before child launch."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_error(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": " ".join(str(exc).split())[:400],
    }


def _trusted_prepare_terminal_code(exc: BaseException) -> str | None:
    """Return only a frozen controller-to-supervisor prepare classification."""

    try:
        terminal_code = getattr(exc, "terminal_code", None)
    except Exception:  # noqa: BLE001 - an unsafe property must not replace the error
        return None
    if isinstance(terminal_code, str) and terminal_code in (
        _TRUSTED_PREPARE_TERMINAL_CODES
    ):
        return terminal_code
    return None


def _trusted_pre_readiness_oom_receipt(
    exc: BaseException,
    spec: RunSpec,
) -> dict[str, Any] | None:
    """Return only the exact runtime-controller OOM receipt shape."""

    exception_type = type(exc)
    if (
        exception_type.__name__ != "RuntimeOomPreReadiness"
        or exception_type.__module__ != "fort_gym.bench.run.runtime_controller"
    ):
        return None
    try:
        terminal_code = exc.terminal_code
        evidence = exc.evidence
    except Exception:  # noqa: BLE001 - unsafe properties are never trusted
        return None
    if terminal_code != "oom_256m_pre_readiness" or not isinstance(evidence, Mapping):
        return None
    try:
        validated = validate_pre_readiness_oom_receipt(
            evidence,
            run_id=spec.run_id,
            environment_identity=spec.environment_identity,
        )
    except FaultClassificationError:
        return None
    return _json_safe(validated)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return repr(value)


def _freeze_evidence_mapping(name: str, value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a bounded JSON value tree and detach it from caller mutation."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    active_container_ids: set[int] = set()
    nodes_seen = 0

    def freeze(item: Any, depth: int) -> Any:
        nonlocal nodes_seen
        nodes_seen += 1
        if nodes_seen > _MAX_EVIDENCE_NODES:
            raise ValueError(f"{name} exceeds {_MAX_EVIDENCE_NODES} JSON nodes")
        if depth > _MAX_EVIDENCE_DEPTH:
            raise ValueError(f"{name} exceeds JSON depth {_MAX_EVIDENCE_DEPTH}")
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{name} contains a non-finite float")
            return item
        if isinstance(item, Mapping):
            container_id = id(item)
            if container_id in active_container_ids:
                raise ValueError(f"{name} contains a cycle")
            active_container_ids.add(container_id)
            try:
                frozen: dict[str, Any] = {}
                for key, nested in item.items():
                    if not isinstance(key, str):
                        raise TypeError(f"{name} contains a non-string JSON key")
                    frozen[key] = freeze(nested, depth + 1)
                return MappingProxyType(frozen)
            finally:
                active_container_ids.remove(container_id)
        if isinstance(item, (list, tuple)):
            container_id = id(item)
            if container_id in active_container_ids:
                raise ValueError(f"{name} contains a cycle")
            active_container_ids.add(container_id)
            try:
                return tuple(freeze(nested, depth + 1) for nested in item)
            finally:
                active_container_ids.remove(container_id)
        raise TypeError(f"{name} contains a non-JSON-safe {type(item).__name__}")

    result = freeze(value, 0)
    if not isinstance(result, Mapping):
        raise TypeError(f"{name} did not freeze to a mapping")
    encoded = json.dumps(
        _json_safe(result),
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_EVIDENCE_MAPPING_BYTES:
        raise ValueError(f"{name} exceeds {_MAX_EVIDENCE_MAPPING_BYTES} encoded bytes")
    return result


def _supervisor_runtime() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def _is_provider_environment_name(name: str) -> bool:
    upper = name.upper()
    if upper.startswith(("OPENROUTER_", "OPENAI_", "ANTHROPIC_")):
        return True
    if upper.endswith(("_API_KEY", "_ACCESS_TOKEN", "_AUTH_TOKEN")):
        return True
    if "PROVIDER" in upper and any(
        marker in upper for marker in ("KEY", "MODEL", "ROUTE", "HOST", "URL", "TOKEN")
    ):
        return True
    return upper in {"LLM_MODEL", "LLM_PROVIDER", "LLM_ROUTE"}


def build_sanitized_environment(
    *,
    allowlist: Sequence[str] = (),
    overrides: Mapping[str, str] | None = None,
    scripted: bool,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal child environment and fail closed on unsafe overrides.

    Ambient provider variables are stripped in scripted mode. Explicitly
    attempting to inject one is rejected so a caller cannot mistake stripping
    for successful configuration.
    """

    allowed = set(DEFAULT_ENV_ALLOWLIST)
    allowed.update(str(name) for name in allowlist)
    invalid_names = sorted(
        name for name in allowed if not name or "=" in name or "\0" in name
    )
    if invalid_names:
        raise ValueError(f"invalid environment names: {invalid_names!r}")
    source_env = os.environ if source is None else source
    child_env: dict[str, str] = {}
    for name in sorted(allowed):
        if scripted and _is_provider_environment_name(name):
            continue
        if name in source_env:
            child_env[name] = str(source_env[name])

    for raw_name, raw_value in (overrides or {}).items():
        name = str(raw_name)
        if name == "FORT_GYM_DISABLE_DOTENV":
            if str(raw_value) != "1":
                raise ValueError("FORT_GYM_DISABLE_DOTENV is fixed to 1")
            continue
        if name not in allowed:
            raise ValueError(f"environment override is not allowlisted: {name}")
        if scripted and _is_provider_environment_name(name):
            raise ValueError(f"scripted mode rejects provider environment: {name}")
        value = str(raw_value)
        if "\0" in value:
            raise ValueError(f"environment value contains NUL: {name}")
        child_env[name] = value

    child_env["FORT_GYM_DISABLE_DOTENV"] = "1"
    return child_env


@dataclass(frozen=True)
class RunSpec:
    """One isolated child-process attempt.

    Provider caps are post-event stop thresholds. The trace monitor terminates
    the process after observing a threshold event; preventing a subsequent call
    requires a separate in-process gate immediately before provider dispatch.
    """

    run_id: str
    argv: Sequence[str]
    artifact_dir: Path
    cwd: Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    env_allowlist: Sequence[str] = field(default_factory=tuple)
    scripted: bool = True
    provider_enabled: bool = False
    provider_route: str | None = None
    provider_model: str | None = None
    provider_name: str | None = None
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS
    max_cost_usd: float = DEFAULT_MAX_COST_USD
    timeout_seconds: float = 3_600.0
    term_grace_seconds: float = 10.0
    poll_interval_seconds: float = 0.1
    trace_path: Path | None = None
    port: int | None = None
    port_lock_dir: Path = Path("/tmp/fort-gym-port-leases")
    environment_identity: Mapping[str, Any] = field(default_factory=dict)
    cotenancy: Mapping[str, Any] = field(default_factory=dict)
    runtime_cleanup_required: bool = False

    def __post_init__(self) -> None:
        if not _RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a bounded filesystem-safe identifier")
        argv = tuple(str(item) for item in self.argv)
        if not argv or not argv[0]:
            raise ValueError("argv must contain an executable")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "artifact_dir", Path(self.artifact_dir))
        if self.cwd is not None:
            object.__setattr__(self, "cwd", Path(self.cwd))
        if self.trace_path is not None:
            object.__setattr__(self, "trace_path", Path(self.trace_path))
        object.__setattr__(self, "port_lock_dir", Path(self.port_lock_dir))
        object.__setattr__(
            self, "env_allowlist", tuple(str(name) for name in self.env_allowlist)
        )
        object.__setattr__(
            self,
            "environment_identity",
            _freeze_evidence_mapping("environment_identity", self.environment_identity),
        )
        object.__setattr__(
            self,
            "cotenancy",
            _freeze_evidence_mapping("cotenancy", self.cotenancy),
        )

        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if not math.isfinite(self.term_grace_seconds) or self.term_grace_seconds <= 0:
            raise ValueError("term_grace_seconds must be positive and finite")
        if (
            not math.isfinite(self.poll_interval_seconds)
            or self.poll_interval_seconds <= 0
        ):
            raise ValueError("poll_interval_seconds must be positive and finite")
        if self.port is not None and not 1 <= self.port <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        if not isinstance(self.runtime_cleanup_required, bool):
            raise TypeError("runtime_cleanup_required must be boolean")

        if self.scripted and self.provider_enabled:
            raise ValueError("scripted runs cannot enable a provider")
        if self.provider_enabled:
            if self.provider_route != "openrouter":
                raise ValueError("provider-enabled runs must pin the openrouter route")
            if not self.provider_model:
                raise ValueError("provider-enabled runs must pin a model")
            if not self.provider_name or not self.provider_name.strip():
                raise ValueError("provider-enabled runs must pin a provider name")
            if self.max_total_tokens <= 0:
                raise ValueError("provider-enabled runs require a positive token cap")
            if not math.isfinite(self.max_cost_usd) or self.max_cost_usd <= 0:
                raise ValueError("provider-enabled runs require a positive USD cap")
        elif any((self.provider_route, self.provider_model, self.provider_name)):
            raise ValueError("provider pins require provider_enabled=True")

        if self.scripted:
            unsafe = sorted(
                name for name in self.env if _is_provider_environment_name(name)
            )
            if unsafe:
                raise ValueError(
                    "scripted runs reject provider environment overrides: "
                    + ", ".join(unsafe)
                )


class PortLease:
    """Host-wide advisory lease plus an immediate loopback bind check.

    Lock files are deliberately retained after release. Unlinking a locked file
    can create a second inode and split what should be one host-wide lease.
    """

    def __init__(self, port: int, lock_dir: Path) -> None:
        if not 1 <= int(port) <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        self.port = int(port)
        self.lock_dir = Path(lock_dir)
        self.path = self.lock_dir / f"tcp-127.0.0.1-{self.port}.lock"
        self._fd: int | None = None

    def acquire(self) -> Self:
        if self._fd is not None:
            raise PortLeaseError("port lease is already held by this object")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            self._lock(fd)
        except OSError as exc:
            os.close(fd)
            raise PortLeaseBusy(f"port {self.port} already has a host lease") from exc

        probe: socket.socket | None = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", self.port))
        except OSError as exc:
            try:
                self._unlock(fd)
            finally:
                os.close(fd)
            raise PortUnavailable(
                f"loopback port {self.port} is already bound"
            ) from exc
        finally:
            if probe is not None:
                probe.close()

        self._fd = fd
        return self

    @classmethod
    def lock_available(cls, port: int, lock_dir: Path) -> bool:
        """Probe only the advisory lock, without testing socket bindability.

        Residue auditing reports listeners and host leases independently.  A
        recently closed TCP listener may leave connections in ``TIME_WAIT``;
        treating that transient bind refusal as a held lease makes an already
        released supervisor lock look like residue.
        """

        probe = cls(port, lock_dir)
        probe.lock_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(probe.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                probe._lock(fd)
            except OSError:
                return False
            probe._unlock(fd)
            return True
        finally:
            os.close(fd)

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            self._unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> Self:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

    @staticmethod
    def _lock(fd: int) -> None:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        if msvcrt is None:  # pragma: no cover - defensive unsupported platform
            raise OSError("no file-lock implementation is available")
        if os.fstat(fd).st_size == 0:  # pragma: no cover - Windows fallback
            os.write(fd, b"\0")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    @staticmethod
    def _unlock(fd: int) -> None:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return
        if msvcrt is None:  # pragma: no cover - defensive unsupported platform
            return
        os.lseek(fd, 0, os.SEEK_SET)  # pragma: no cover - Windows fallback
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


class AttemptJournal:
    """Append complete JSONL records with an fsync after every record."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, event: str, **fields: Any) -> None:
        payload = {
            "schema": "fortgym.process-supervisor-attempt/v1",
            "at": _utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            "supervisor_pid": os.getpid(),
            "event": event,
            **fields,
        }
        encoded = (
            json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(encoded) > 65_536:
            raise SupervisorError("attempt journal record exceeds 64 KiB")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            written = os.write(fd, encoded)
            if written != len(encoded):
                raise SupervisorError("short append to attempt journal")
            os.fsync(fd)
        finally:
            os.close(fd)


@dataclass(frozen=True)
class MonitorViolation:
    terminal_class: TerminalClass
    reason: str
    details: Mapping[str, Any]


class TraceBudgetMonitor:
    """Incrementally tail trace JSONL and enforce OpenRouter pins and caps.

    This is a post-event fail-safe: it reacts only after the child durably emits
    a tool-call event. It does not replace an in-process gate immediately before
    each provider call.
    """

    def __init__(self, trace_path: Path, spec: RunSpec) -> None:
        self.trace_path = Path(trace_path)
        self.spec = spec
        self._offset = 0
        self._identity: tuple[int, int] | None = None
        self._partial = b""
        self.events_seen = 0
        self.calls = 0
        self.total_tokens = 0
        self.total_cost_usd = Decimal(0)
        self.requested_models: set[str] = set()
        self.resolved_models: set[str] = set()
        self.providers: set[str] = set()

    def poll(self) -> MonitorViolation | None:
        try:
            stat = self.trace_path.stat()
        except FileNotFoundError:
            return None
        identity = (stat.st_dev, stat.st_ino)
        if self._identity != identity or stat.st_size < self._offset:
            self._identity = identity
            self._offset = 0
            self._partial = b""

        with self.trace_path.open("rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read()
            self._offset = handle.tell()
        if not chunk:
            return None

        complete = self._partial + chunk
        lines = complete.split(b"\n")
        self._partial = lines.pop()
        for raw_line in lines:
            if not raw_line.strip():
                continue
            violation = self._observe_raw_line(raw_line)
            if violation is not None:
                return violation
        return None

    def finalize(self) -> MonitorViolation | None:
        """Drain the trace and fail closed on any trailing non-empty fragment."""

        violation = self.poll()
        if violation is not None:
            return violation
        raw_line = self._partial
        self._partial = b""
        if not raw_line.strip():
            return None
        return self._observe_raw_line(raw_line)

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider_enabled": self.spec.provider_enabled,
            "events_seen": self.events_seen,
            "calls": self.calls,
            "total_tokens": self.total_tokens,
            "total_cost_usd": float(self.total_cost_usd),
            "max_total_tokens": self.spec.max_total_tokens,
            "max_cost_usd": self.spec.max_cost_usd,
            "requested_models": sorted(self.requested_models),
            "resolved_models": sorted(self.resolved_models),
            "providers": sorted(self.providers),
        }

    @staticmethod
    def _tool_events(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        candidates: list[Any] = []
        if record.get("type") == "tool_call":
            candidates.append(record)
        events = record.get("events")
        if isinstance(events, list):
            candidates.extend(events)
        return [
            event
            for event in candidates
            if isinstance(event, Mapping)
            and event.get("type") == "tool_call"
            and isinstance(event.get("data"), Mapping)
        ]

    def _observe_raw_line(self, raw_line: bytes) -> MonitorViolation | None:
        try:
            record = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return MonitorViolation(
                TerminalClass.CAP_TRIP,
                "trace_accounting_invalid",
                _safe_error(exc),
            )
        if not isinstance(record, Mapping):
            return MonitorViolation(
                TerminalClass.CAP_TRIP,
                "trace_accounting_invalid",
                {"record_type": type(record).__name__},
            )
        for event in self._tool_events(record):
            violation = self._observe_tool_event(event)
            if violation is not None:
                return violation
        return None

    def _observe_tool_event(self, event: Mapping[str, Any]) -> MonitorViolation | None:
        data = event["data"]
        if not isinstance(data, Mapping):
            return MonitorViolation(
                TerminalClass.CAP_TRIP,
                "trace_accounting_invalid",
                {"data_type": type(data).__name__},
            )
        tool = str(data.get("tool") or "")
        if tool != OPENROUTER_TOOL:
            return None
        self.events_seen += 1

        if not self.spec.provider_enabled:
            return MonitorViolation(
                TerminalClass.PROVIDER_PIN_VIOLATION,
                "provider_call_in_provider_disabled_run",
                {"tool": tool},
            )

        input_data = data.get("input") if isinstance(data.get("input"), Mapping) else {}
        output_data = (
            data.get("output") if isinstance(data.get("output"), Mapping) else {}
        )
        generation = (
            output_data.get("generation")
            if isinstance(output_data.get("generation"), Mapping)
            else {}
        )

        route = str(
            data.get("provider_route")
            or input_data.get("provider_route")
            or "openrouter"
        )
        requested_model = str(input_data.get("model") or "")
        resolved_model = str(
            output_data.get("resolved_model") or generation.get("model") or ""
        )
        provider = str(
            generation.get("provider_name") or generation.get("provider") or ""
        ).strip()
        if requested_model:
            self.requested_models.add(requested_model)
        if resolved_model:
            self.resolved_models.add(resolved_model)
        if provider:
            self.providers.add(provider)

        tokens = self._tokens(output_data, data)
        cost = self._cost(output_data, data, generation)
        generation_id = output_data.get("generation_id") or generation.get("id")
        provider_error = output_data.get("provider_error") or output_data.get("error")
        billable = generation_id is not None or tokens is not None or cost is not None

        mismatches: dict[str, Any] = {}
        if route != self.spec.provider_route:
            mismatches["route"] = {
                "expected": self.spec.provider_route,
                "observed": route,
            }
        if requested_model != self.spec.provider_model:
            mismatches["requested_model"] = {
                "expected": self.spec.provider_model,
                "observed": requested_model or None,
            }
        if resolved_model and resolved_model != self.spec.provider_model:
            mismatches["resolved_model"] = {
                "expected": self.spec.provider_model,
                "observed": resolved_model,
            }
        if (provider or billable) and provider != self.spec.provider_name:
            mismatches["provider"] = {
                "expected": self.spec.provider_name,
                "observed": provider or None,
            }
        if mismatches:
            return MonitorViolation(
                TerminalClass.PROVIDER_PIN_VIOLATION,
                "provider_pin_mismatch",
                mismatches,
            )

        if not billable and provider_error:
            return None
        if tokens is None or cost is None:
            return MonitorViolation(
                TerminalClass.CAP_TRIP,
                "provider_usage_unaccounted",
                {
                    "generation_id": generation_id,
                    "tokens_present": tokens is not None,
                    "cost_present": cost is not None,
                },
            )
        if tokens < 0 or cost < 0:
            return MonitorViolation(
                TerminalClass.CAP_TRIP,
                "provider_usage_invalid",
                {"tokens": tokens, "cost_usd": float(cost)},
            )

        self.calls += 1
        self.total_tokens += tokens
        self.total_cost_usd += cost
        if self.total_tokens >= self.spec.max_total_tokens:
            return MonitorViolation(
                TerminalClass.CAP_TRIP,
                "token_cap_reached",
                {
                    "observed": self.total_tokens,
                    "cap": self.spec.max_total_tokens,
                },
            )
        cap = Decimal(str(self.spec.max_cost_usd))
        if self.total_cost_usd >= cap:
            return MonitorViolation(
                TerminalClass.CAP_TRIP,
                "usd_cap_reached",
                {"observed": float(self.total_cost_usd), "cap": self.spec.max_cost_usd},
            )
        return None

    @classmethod
    def _tokens(cls, output: Mapping[str, Any], data: Mapping[str, Any]) -> int | None:
        usage_candidates = [
            output,
            output.get("usage") if isinstance(output.get("usage"), Mapping) else {},
            data.get("usage") if isinstance(data.get("usage"), Mapping) else {},
        ]
        for usage in usage_candidates:
            total = cls._integer(usage.get("total_tokens"))
            if total is not None:
                return total
            prompt = cls._integer(usage.get("prompt_tokens"))
            if prompt is None:
                prompt = cls._integer(usage.get("input_tokens"))
            completion = cls._integer(usage.get("completion_tokens"))
            if completion is None:
                completion = cls._integer(usage.get("output_tokens"))
            if prompt is not None or completion is not None:
                return (prompt or 0) + (completion or 0)
        return None

    @classmethod
    def _cost(
        cls,
        output: Mapping[str, Any],
        data: Mapping[str, Any],
        generation: Mapping[str, Any],
    ) -> Decimal | None:
        usage = output.get("usage") if isinstance(output.get("usage"), Mapping) else {}
        candidates = (
            output.get("cost"),
            usage.get("cost"),
            usage.get("cost_usd"),
            generation.get("total_cost"),
            generation.get("cost"),
            data.get("cost_usd"),
        )
        for candidate in candidates:
            value = cls._decimal(candidate)
            if value is not None:
                return value
        return None

    @staticmethod
    def _integer(value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            integer = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return integer

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return decimal if decimal.is_finite() else None


@dataclass(frozen=True)
class SupervisionResult:
    terminal_class: TerminalClass
    terminal_path: Path
    journal_path: Path
    payload: Mapping[str, Any]


PrepareCallback = Callable[[], Mapping[str, Any] | None]
CleanupCallback = Callable[[], Mapping[str, Any] | None]
FaultClassifier = Callable[[Mapping[str, Any]], Mapping[str, Any]]
PreCleanupObserver = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class ProviderNetworkController(Protocol):
    """Exact opt-in network boundary used around one supervised harness."""

    run_id: str
    contract_sha256: str
    assigned_host: str
    assigned_port: int
    identity_sha256: str
    helper_path: Path
    helper_sha256: str
    cgroup_path: Path
    guard_attestation_path: Path

    def public_identity(self) -> Mapping[str, Any]: ...

    def python_guard_environment(self) -> Mapping[str, str]: ...

    def enter_argv(self, child_argv: Sequence[str]) -> Sequence[str]: ...

    def prepare(self) -> Mapping[str, Any] | None: ...

    def cleanup(self) -> Mapping[str, Any] | None: ...

    def abort(self, *, recovered: bool = False) -> Mapping[str, Any] | None: ...

    def reconcile(self) -> Mapping[str, Any] | None: ...

    def residue(self) -> Mapping[str, Any]: ...

    def validate_evidence(
        self, provider_budget: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ProviderNetworkLaunchPlan:
    """Validated wrapper launch state; raw guard values are never persisted."""

    argv: tuple[str, ...]
    guard_environment: Mapping[str, str] = field(repr=False)
    evidence: Mapping[str, Any]


def canonical_argv_sha256(argv: Sequence[str]) -> str:
    """Digest one exact argument vector without delimiter ambiguity."""

    normalized = tuple(str(item) for item in argv)
    encoded = json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _terminal_chain_identity(
    spec: RunSpec,
    *,
    child_pid: int | None,
) -> dict[str, Any]:
    environment = _json_safe(spec.environment_identity)
    if not isinstance(environment, dict):
        raise SupervisorError("terminal identity environment is not an object")
    contract_sha256 = environment.get("contract_sha256")
    rpc = environment.get("rpc")
    nonce = rpc.get("nonce") if isinstance(rpc, Mapping) else None
    nonce_sha256 = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        if isinstance(nonce, str)
        else None
    )
    if contract_sha256 is not None and (
        not isinstance(contract_sha256, str)
        or not _SHA256_RE.fullmatch(contract_sha256)
        or nonce_sha256 is None
    ):
        raise SupervisorError("terminal identity contract binding is malformed")
    return {
        "run_id": spec.run_id,
        "contract_sha256": contract_sha256,
        "nonce_sha256": nonce_sha256,
        "environment_identity_sha256": _canonical_sha256(environment),
        "child_pid": child_pid,
        "port": spec.port,
    }


def _read_regular_evidence(
    path: Path,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (metadata.st_size == 0 and not allow_empty)
            or metadata.st_size > maximum
        ):
            raise SupervisorError("terminal-chain evidence metadata is unsafe")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise SupervisorError("terminal-chain evidence read was short")
            chunks.append(chunk)
            remaining -= len(chunk)
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
            raise SupervisorError("terminal-chain evidence changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def validate_terminal_chain(
    attempt_dir: Path,
    terminal: Mapping[str, Any],
    *,
    run_id: str,
    require_cleanup_success: bool = False,
) -> Mapping[str, Any]:
    """Validate the exact identity-bound seven-event terminal chain."""

    attempt_root = Path(attempt_dir).resolve(strict=True)
    journal_path = attempt_root / "attempt-journal.jsonl"
    raw_journal = _read_regular_evidence(journal_path, maximum=32 * 1024 * 1024)
    if not raw_journal.endswith(b"\n"):
        raise SupervisorError("terminal-chain journal lacks its final newline")
    try:
        rows = [json.loads(line) for line in raw_journal.splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError("terminal-chain journal is malformed") from exc
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise SupervisorError("terminal-chain journal records are malformed")
    chain = [row for row in rows if row.get("event") in TERMINAL_CHAIN_EVENTS]
    if tuple(row.get("event") for row in chain) != TERMINAL_CHAIN_EVENTS:
        raise SupervisorError("terminal-chain event sequence differs")
    immutable_index = rows.index(chain[-1])
    trailing = rows[immutable_index + 1 :]
    if (
        sum(row.get("event") == "terminal_pending" for row in rows) != 1
        or len(trailing) != 1
        or trailing[0].get("event") != "terminal_pending"
        or trailing[0].get("run_id") != run_id
        or trailing[0].get("terminal_class") != terminal.get("terminal_class")
        or trailing[0].get("cleanup_ok")
        is not (
            isinstance(terminal.get("cleanup"), Mapping)
            and terminal["cleanup"].get("ok") is True
        )
    ):
        raise SupervisorError("terminal-pending durability boundary differs")
    identities = [row.get("identity") for row in chain]
    if not all(isinstance(identity, dict) for identity in identities):
        raise SupervisorError("terminal-chain identity is missing")
    identity = identities[0]
    if any(observed != identity for observed in identities[1:]):
        raise SupervisorError("terminal-chain identities differ")
    expected_identity_keys = {
        "run_id",
        "contract_sha256",
        "nonce_sha256",
        "environment_identity_sha256",
        "child_pid",
        "port",
    }
    environment = terminal.get("environment_identity")
    if (
        set(identity) != expected_identity_keys
        or identity.get("run_id") != run_id
        or terminal.get("run_id") != run_id
        or identity.get("child_pid") != terminal.get("child_pid")
        or identity.get("port") != terminal.get("port")
        or not isinstance(environment, Mapping)
        or identity.get("environment_identity_sha256") != _canonical_sha256(environment)
    ):
        raise SupervisorError("terminal-chain identity contradicts terminal evidence")
    contract_sha256 = environment.get("contract_sha256")
    rpc = environment.get("rpc")
    nonce = rpc.get("nonce") if isinstance(rpc, Mapping) else None
    expected_nonce_sha256 = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        if isinstance(nonce, str)
        else None
    )
    if (
        identity.get("contract_sha256") != contract_sha256
        or identity.get("nonce_sha256") != expected_nonce_sha256
    ):
        raise SupervisorError("terminal-chain contract binding differs")
    supervisor_pid_sequence = [row.get("supervisor_pid") for row in chain]
    monotonic = [row.get("monotonic_ns") for row in chain]
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in supervisor_pid_sequence
        )
        or any(
            isinstance(value, bool) or not isinstance(value, int) for value in monotonic
        )
        or monotonic != sorted(monotonic)
    ):
        raise SupervisorError("terminal-chain process or order binding differs")
    if len(set(supervisor_pid_sequence)) != 1:
        recovery = terminal.get("terminal_chain_recovery")
        if not isinstance(recovery, Mapping) or set(recovery) != {
            "schema",
            "original_supervisor_pid",
            "recovery_manager_pid",
            "resumed_event_count",
        }:
            raise SupervisorError("terminal-chain recovery binding is missing")
        resumed_count = recovery.get("resumed_event_count")
        original_pid = recovery.get("original_supervisor_pid")
        recovery_pid = recovery.get("recovery_manager_pid")
        if (
            recovery.get("schema")
            != "fortgym.process-supervisor-terminal-chain-recovery/v1"
            or isinstance(resumed_count, bool)
            or not isinstance(resumed_count, int)
            or not 1 <= resumed_count < len(TERMINAL_CHAIN_EVENTS)
            or isinstance(original_pid, bool)
            or not isinstance(original_pid, int)
            or original_pid <= 0
            or isinstance(recovery_pid, bool)
            or not isinstance(recovery_pid, int)
            or recovery_pid <= 0
            or original_pid == recovery_pid
            or supervisor_pid_sequence[:resumed_count] != [original_pid] * resumed_count
            or supervisor_pid_sequence[resumed_count:]
            != [recovery_pid] * (len(TERMINAL_CHAIN_EVENTS) - resumed_count)
        ):
            raise SupervisorError("terminal-chain recovery transition differs")

    pending, snapshot_row, reaped, removed, verified, completed, immutable = chain
    primary_reason = terminal.get("primary_reason")
    cleanup = terminal.get("cleanup")
    reason = terminal.get("reason")
    runtime_cleanup_required = terminal.get("runtime_cleanup_required")
    cleanup_sha256 = _canonical_sha256(cleanup)
    if pending.get("primary_terminal_class") != terminal.get(
        "primary_terminal_class"
    ) or pending.get("primary_reason_sha256") != _canonical_sha256(primary_reason):
        raise SupervisorError("terminal pending-cleanup evidence differs")
    snapshot_path = attempt_root / "evidence-snapshot.json"
    snapshot_raw = _read_regular_evidence(snapshot_path, maximum=4 * 1024 * 1024)
    try:
        snapshot = json.loads(snapshot_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError("generic evidence snapshot is malformed") from exc
    snapshot_sha256 = hashlib.sha256(snapshot_raw).hexdigest()
    if (
        snapshot_row.get("ok") is not True
        or snapshot_row.get("snapshot_path") != str(snapshot_path)
        or snapshot_row.get("snapshot_sha256") != snapshot_sha256
        or not isinstance(snapshot, dict)
        or snapshot.get("schema") != EVIDENCE_SNAPSHOT_SCHEMA
        or snapshot.get("identity") != identity
        or snapshot.get("primary_terminal_class")
        != terminal.get("primary_terminal_class")
        or snapshot.get("primary_reason") != primary_reason
    ):
        raise SupervisorError("generic evidence snapshot binding differs")
    child_pid = terminal.get("child_pid")
    cleanup_ok = isinstance(cleanup, Mapping) and cleanup.get("ok") is True
    if (
        not isinstance(reaped.get("ok"), bool)
        or reaped.get("child_pid") != child_pid
        or (child_pid is None and reaped.get("skipped") is not True)
        or (child_pid is not None and reaped.get("skipped") is not False)
        or (
            cleanup_ok
            and child_pid is not None
            and (
                reaped.get("ok") is not True or reaped.get("group_exists") is not False
            )
        )
    ):
        raise SupervisorError("harness reap evidence differs")
    if require_cleanup_success and not cleanup_ok:
        raise SupervisorError("terminal chain does not prove successful cleanup")
    if (
        not isinstance(removed.get("ok"), bool)
        or verified.get("ok") is not cleanup_ok
        or completed.get("ok") is not cleanup_ok
        or verified.get("cleanup_sha256") != cleanup_sha256
        or completed.get("cleanup_sha256") != cleanup_sha256
    ):
        raise SupervisorError("terminal cleanup chain differs")
    if not isinstance(runtime_cleanup_required, bool):
        raise SupervisorError("terminal runtime-cleanup policy is missing")
    if (
        runtime_cleanup_required
        and cleanup_ok
        and (
            removed.get("ok") is not True
            or removed.get("skipped") is not False
            or removed.get("container_absent") is not True
            or (
                removed.get("listener_absent") is not True
                and not (
                    removed.get("shared_listener_preserved") is True
                    and child_pid is None
                    and isinstance(primary_reason, Mapping)
                    and primary_reason.get("code") == "port_lease_busy"
                )
            )
        )
    ):
        raise SupervisorError("runtime removal chain is incomplete")
    if not runtime_cleanup_required and (
        removed.get("ok") is not True or removed.get("skipped") is not True
    ):
        raise SupervisorError("non-runtime terminal removal policy differs")
    if (
        immutable.get("terminal_class") != terminal.get("terminal_class")
        or immutable.get("reason_sha256") != _canonical_sha256(reason)
        or immutable.get("cleanup_sha256") != cleanup_sha256
        or immutable.get("evidence_snapshot_sha256") != snapshot_sha256
    ):
        raise SupervisorError("immutable terminal classification differs")
    return MappingProxyType(
        {
            "identity": MappingProxyType(dict(identity)),
            "events": TERMINAL_CHAIN_EVENTS,
            "snapshot_sha256": snapshot_sha256,
            "cleanup_sha256": cleanup_sha256,
            "terminal_class": terminal.get("terminal_class"),
        }
    )


def write_recovered_terminal_chain(
    attempt_dir: Path,
    terminal: Mapping[str, Any],
    *,
    run_id: str,
) -> Path:
    """Finish one exact manager-recovered chain, including accepted prefixes."""

    attempt_root = Path(attempt_dir).resolve(strict=True)
    terminal_path = attempt_root / "terminal.json"
    if terminal_path.exists():
        raise SupervisorError("recovered terminal already exists")
    journal_path = attempt_root / "attempt-journal.jsonl"
    existing = _read_regular_evidence(journal_path, maximum=32 * 1024 * 1024)
    if not existing.endswith(b"\n"):
        raise SupervisorError("recovery journal lacks its final newline")
    try:
        rows = [json.loads(line) for line in existing.splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError("recovery journal is malformed") from exc
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise SupervisorError("recovery journal records are malformed")
    chain = [row for row in rows if row.get("event") in TERMINAL_CHAIN_EVENTS]
    chain_events = tuple(row.get("event") for row in chain)
    if chain_events != TERMINAL_CHAIN_EVENTS[: len(chain_events)]:
        raise SupervisorError("recovered terminal-chain prefix differs")
    terminal_pending_rows = [
        row for row in rows if row.get("event") == "terminal_pending"
    ]
    if len(terminal_pending_rows) > 1 or (
        terminal_pending_rows and len(chain) != len(TERMINAL_CHAIN_EVENTS)
    ):
        raise SupervisorError("recovered terminal-pending boundary differs")
    cleanup_rows = [row for row in rows if row.get("event") == "cleanup_recorded"]
    if len(cleanup_rows) > 1:
        raise SupervisorError("recovery cleanup record is duplicated")

    selected = dict(terminal)
    recovery_cleanup = selected.get("cleanup")
    if not isinstance(recovery_cleanup, Mapping) or not isinstance(
        recovery_cleanup.get("ok"), bool
    ):
        raise SupervisorError("recovered terminal lacks a typed cleanup result")
    draft_path = attempt_root / "terminal-draft.json"
    draft_raw: bytes | None = None
    if draft_path.exists():
        draft_raw = _read_regular_evidence(draft_path, maximum=4 * 1024 * 1024)
        try:
            draft = json.loads(draft_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupervisorError("terminal draft is malformed") from exc
        if (
            not isinstance(draft, dict)
            or draft.get("schema") != "fortgym.process-supervisor-terminal/v1"
            or draft.get("run_id") != run_id
        ):
            raise SupervisorError("terminal draft identity differs")
        selected = draft
    elif len(chain) >= 5:
        raise SupervisorError("advanced terminal-chain prefix lacks its draft")
    elif cleanup_rows:
        durable_cleanup = cleanup_rows[0].get("cleanup")
        if not isinstance(durable_cleanup, Mapping) or not isinstance(
            durable_cleanup.get("ok"), bool
        ):
            raise SupervisorError("recovery cleanup record is malformed")
        selected["cleanup"] = dict(durable_cleanup)

    environment = selected.get("environment_identity")
    if not isinstance(environment, Mapping):
        raise SupervisorError("recovered terminal lacks environment identity")
    contract_sha256 = environment.get("contract_sha256")
    rpc = environment.get("rpc")
    nonce = rpc.get("nonce") if isinstance(rpc, Mapping) else None
    nonce_sha256 = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        if isinstance(nonce, str)
        else None
    )
    if (
        selected.get("run_id") != run_id
        or not isinstance(contract_sha256, str)
        or not _SHA256_RE.fullmatch(contract_sha256)
        or nonce_sha256 is None
    ):
        raise SupervisorError("recovered terminal contract identity differs")
    identity = {
        "run_id": run_id,
        "contract_sha256": contract_sha256,
        "nonce_sha256": nonce_sha256,
        "environment_identity_sha256": _canonical_sha256(environment),
        "child_pid": selected.get("child_pid"),
        "port": selected.get("port"),
    }

    snapshot_path = attempt_root / "evidence-snapshot.json"
    snapshot: dict[str, Any] | None = None
    snapshot_sha256: str | None = None
    if snapshot_path.exists():
        snapshot_raw = _read_regular_evidence(snapshot_path, maximum=4 * 1024 * 1024)
        try:
            parsed_snapshot = json.loads(snapshot_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupervisorError("generic recovery snapshot is malformed") from exc
        if not isinstance(parsed_snapshot, dict):
            raise SupervisorError("generic recovery snapshot is not an object")
        snapshot = parsed_snapshot
        snapshot_sha256 = hashlib.sha256(snapshot_raw).hexdigest()
        if len(chain) >= 2 and draft_path.exists() is False:
            if (
                snapshot.get("schema") != EVIDENCE_SNAPSHOT_SCHEMA
                or snapshot.get("identity") != identity
            ):
                raise SupervisorError("recovery snapshot identity differs")
            selected["primary_terminal_class"] = snapshot.get("primary_terminal_class")
            selected["primary_reason"] = snapshot.get("primary_reason")
            selected["prepare"] = snapshot.get("prepare") or {}
            selected["termination"] = snapshot.get("termination") or {}

    original_supervisor_pid: int | None = None
    if chain:
        observed_pids = [row.get("supervisor_pid") for row in chain]
        if (
            any(
                isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
                for pid in observed_pids
            )
            or len(set(observed_pids)) != 1
        ):
            raise SupervisorError("recovery prefix supervisor identity differs")
        original_supervisor_pid = int(observed_pids[0])
        if len(chain) < len(TERMINAL_CHAIN_EVENTS) and (
            original_supervisor_pid != os.getpid()
        ):
            selected["terminal_chain_recovery"] = {
                "schema": "fortgym.process-supervisor-terminal-chain-recovery/v1",
                "original_supervisor_pid": original_supervisor_pid,
                "recovery_manager_pid": os.getpid(),
                "resumed_event_count": len(chain),
            }

    cleanup = selected.get("cleanup")
    cleanup_ok = isinstance(cleanup, Mapping) and cleanup.get("ok") is True
    runtime_cleanup_required = selected.get("runtime_cleanup_required")
    if not isinstance(runtime_cleanup_required, bool):
        raise SupervisorError("recovered terminal runtime-cleanup policy is missing")
    cleanup_stages = cleanup.get("stages") if isinstance(cleanup, Mapping) else None
    stage_rows = (
        [stage for stage in cleanup_stages if isinstance(stage, Mapping)]
        if isinstance(cleanup_stages, list)
        else []
    )
    child_pid = selected.get("child_pid")
    harness_stages = [
        stage
        for stage in stage_rows
        if stage.get("stage") == "orphan_harness_process_group"
    ]
    runtime_stages = [
        stage for stage in stage_rows if stage.get("stage") == "runtime_reconcile"
    ]
    harness_details = (
        harness_stages[0].get("details") if len(harness_stages) == 1 else None
    )
    runtime_details = (
        runtime_stages[0].get("details") if len(runtime_stages) == 1 else None
    )
    harness_absent = bool(
        child_pid is None
        or (
            len(harness_stages) == 1
            and harness_stages[0].get("ok") is True
            and isinstance(harness_details, Mapping)
            and harness_details.get("ok") is True
            and (
                harness_details.get("absent") is True
                or harness_details.get("already_absent") is True
            )
        )
    )
    runtime_absent = bool(
        len(runtime_stages) == 1
        and runtime_stages[0].get("ok") is True
        and isinstance(runtime_details, Mapping)
        and runtime_details.get("schema") == "fortgym.m1b-runtime-reconcile/v1"
        and runtime_details.get("ok") is True
        and isinstance(runtime_details.get("managed_candidates"), int)
        and not isinstance(runtime_details.get("managed_candidates"), bool)
        and runtime_details.get("managed_candidates") >= 0
        and isinstance(runtime_details.get("removed_container_ids"), list)
        and isinstance(runtime_details.get("skipped_foreign_container_ids"), list)
        and runtime_details.get("listener_absent") is True
        and isinstance(runtime_details.get("noop"), bool)
        and runtime_details.get("errors") == []
    )
    cleanup_sha256 = _canonical_sha256(cleanup)

    # Validate every durable prefix record before appending any successor.
    if chain:
        identities = [row.get("identity") for row in chain]
        if any(observed != identity for observed in identities):
            raise SupervisorError("recovery prefix chain identity differs")
        monotonic = [row.get("monotonic_ns") for row in chain]
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in monotonic
        ) or monotonic != sorted(monotonic):
            raise SupervisorError("recovery prefix order differs")
        pending = chain[0]
        if pending.get("primary_terminal_class") != selected.get(
            "primary_terminal_class"
        ) or pending.get("primary_reason_sha256") != _canonical_sha256(
            selected.get("primary_reason")
        ):
            raise SupervisorError("recovery pending-cleanup prefix differs")
    if len(chain) >= 2:
        snapshot_row = chain[1]
        if (
            snapshot is None
            or snapshot_sha256 is None
            or snapshot_row.get("ok") is not True
            or snapshot_row.get("snapshot_path") != str(snapshot_path)
            or snapshot_row.get("snapshot_sha256") != snapshot_sha256
            or snapshot.get("schema") != EVIDENCE_SNAPSHOT_SCHEMA
            or snapshot.get("identity") != identity
            or snapshot.get("primary_terminal_class")
            != selected.get("primary_terminal_class")
            or snapshot.get("primary_reason") != selected.get("primary_reason")
        ):
            raise SupervisorError("recovery snapshot prefix differs")
    if len(chain) >= 3:
        reaped = chain[2]
        if (
            reaped.get("child_pid") != child_pid
            or reaped.get("ok") is not True
            or reaped.get("skipped") is not (child_pid is None)
            or (child_pid is not None and reaped.get("group_exists") is not False)
        ):
            raise SupervisorError("recovery harness-reap prefix differs")
    if len(chain) >= 4:
        removed = chain[3]
        if (
            removed.get("ok") is not True
            or removed.get("skipped") is not (not runtime_cleanup_required)
            or (
                runtime_cleanup_required
                and (
                    removed.get("container_absent") is not True
                    or removed.get("listener_absent") is not True
                )
            )
        ):
            raise SupervisorError("recovery runtime-removal prefix differs")
    for index in range(4, min(len(chain), 6)):
        if (
            chain[index].get("ok") is not cleanup_ok
            or chain[index].get("cleanup_sha256") != cleanup_sha256
        ):
            raise SupervisorError("recovery cleanup-boundary prefix differs")
    if len(chain) >= 7:
        immutable = chain[6]
        if (
            immutable.get("terminal_class") != selected.get("terminal_class")
            or immutable.get("reason_sha256")
            != _canonical_sha256(selected.get("reason"))
            or immutable.get("cleanup_sha256") != cleanup_sha256
            or immutable.get("evidence_snapshot_sha256") != snapshot_sha256
        ):
            raise SupervisorError("recovery immutable prefix differs")

    journal = AttemptJournal(journal_path)
    if len(chain) == 0:
        journal.append(
            "terminal_pending_cleanup",
            run_id=run_id,
            identity=identity,
            primary_terminal_class=selected.get("primary_terminal_class"),
            primary_reason_sha256=_canonical_sha256(selected.get("primary_reason")),
        )
    if len(chain) <= 1:
        if snapshot is None:
            files: dict[str, Any] = {}
            for name, evidence_path in (
                ("trace", attempt_root / "trace.jsonl"),
                ("child_stdout", attempt_root / "child.stdout.log"),
                ("child_stderr", attempt_root / "child.stderr.log"),
            ):
                if not evidence_path.exists():
                    files[name] = {"present": False}
                    continue
                raw = _read_regular_evidence(
                    evidence_path,
                    maximum=64 * 1024 * 1024,
                    allow_empty=True,
                )
                files[name] = {
                    "present": True,
                    "path": str(evidence_path.resolve(strict=True)),
                    "size_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            snapshot = {
                "schema": EVIDENCE_SNAPSHOT_SCHEMA,
                "identity": identity,
                "primary_terminal_class": selected.get("primary_terminal_class"),
                "primary_reason": selected.get("primary_reason"),
                "prepare": selected.get("prepare") or {},
                "termination": selected.get("termination") or {},
                "files": files,
                "fault_snapshot": None,
                "fault_snapshot_error": None,
                "recovered_by_manager": True,
            }
            _atomic_write_json(snapshot_path, snapshot)
            snapshot_sha256 = _sha256_file(snapshot_path)
        if snapshot_sha256 is None:
            raise SupervisorError("recovery snapshot digest is unavailable")
        journal.append(
            "evidence_snapshot_completed",
            run_id=run_id,
            identity=identity,
            ok=True,
            snapshot_path=str(snapshot_path),
            snapshot_sha256=snapshot_sha256,
            fault_snapshot_attached=False,
            error=None,
        )
    if len(chain) <= 2:
        journal.append(
            "harness_process_group_reaped",
            run_id=run_id,
            identity=identity,
            ok=harness_absent,
            skipped=child_pid is None,
            child_pid=child_pid,
            group_exists=False if child_pid is not None and harness_absent else None,
        )
    if len(chain) <= 3:
        journal.append(
            "runtime_container_removed",
            run_id=run_id,
            identity=identity,
            ok=runtime_absent,
            skipped=not runtime_cleanup_required,
            container_absent=(
                True if runtime_cleanup_required and runtime_absent else None
            ),
            listener_absent=(
                runtime_details.get("listener_absent")
                if isinstance(runtime_details, Mapping)
                else None
            ),
        )

    if cleanup_rows and cleanup_rows[0].get("cleanup") != cleanup:
        raise SupervisorError("recovery cleanup record differs")
    if not cleanup_rows:
        if len(chain) >= 5:
            raise SupervisorError("recovery cleanup record is out of order")
        journal.append("cleanup_recorded", run_id=run_id, cleanup=cleanup)

    if draft_raw is None:
        _atomic_write_json(draft_path, selected)
    draft_sha256 = _sha256_file(draft_path)
    classification_rows = [
        row
        for row in rows
        if row.get("event") == "runtime_fault_classification_recorded"
    ]
    if len(classification_rows) > 1:
        raise SupervisorError("recovery classification record is duplicated")
    if classification_rows:
        classification = classification_rows[0]
        if (
            classification.get("terminal_draft_path") != str(draft_path)
            or classification.get("terminal_draft_sha256") != draft_sha256
        ):
            raise SupervisorError("recovery classification draft binding differs")
    else:
        if len(chain) >= 5:
            raise SupervisorError("recovery classification record is out of order")
        journal.append(
            "runtime_fault_classification_recorded",
            run_id=run_id,
            fault_classification=selected.get("fault_classification")
            or {
                "schema": FAULT_CLASSIFICATION_RECORD_SCHEMA,
                "attempted": False,
                "ok": True,
                "classified": False,
                "skipped": "manager_recovery_terminal",
            },
            terminal_draft_path=str(draft_path),
            terminal_draft_sha256=draft_sha256,
        )

    if snapshot_sha256 is None:
        snapshot_sha256 = _sha256_file(snapshot_path)
    for index, event in ((4, "cleanup_verified"), (5, "cleanup_completed")):
        if len(chain) <= index:
            journal.append(
                event,
                run_id=run_id,
                identity=identity,
                ok=cleanup_ok,
                cleanup_sha256=cleanup_sha256,
            )
    if len(chain) <= 6:
        journal.append(
            "immutable_terminal_classification",
            run_id=run_id,
            identity=identity,
            terminal_class=selected.get("terminal_class"),
            reason_sha256=_canonical_sha256(selected.get("reason")),
            cleanup_sha256=cleanup_sha256,
            evidence_snapshot_sha256=snapshot_sha256,
        )
    if not terminal_pending_rows:
        journal.append(
            "terminal_pending",
            run_id=run_id,
            terminal_class=selected.get("terminal_class"),
            cleanup_ok=cleanup_ok,
        )
    validate_terminal_chain(attempt_root, selected, run_id=run_id)
    _atomic_write_json(terminal_path, selected)
    return terminal_path


def build_provider_network_launch_plan(
    spec: RunSpec,
    controller: ProviderNetworkController,
) -> ProviderNetworkLaunchPlan:
    """Validate and bind an explicit provider-free cgroup wrapper to ``spec``.

    The caller still owns lifecycle sequencing. This function is side-effect
    free except for reading the pinned helper binary and rejects partial or
    contradictory controller objects before any helper command can run.
    """

    if spec.provider_enabled or not spec.scripted:
        raise ProviderNetworkPrepareError(
            "provider-network isolation requires a provider-free scripted run"
        )
    if spec.port is None:
        raise ProviderNetworkPrepareError(
            "provider-network isolation requires an assigned loopback port"
        )

    environment_identity = spec.environment_identity
    rpc = environment_identity.get("rpc")
    if not isinstance(rpc, Mapping):
        raise ProviderNetworkPrepareError(
            "provider-network isolation requires durable RPC identity"
        )
    contract_sha256 = environment_identity.get("contract_sha256")
    nonce = rpc.get("nonce")
    if (
        environment_identity.get("run_id") != spec.run_id
        or not isinstance(contract_sha256, str)
        or not _SHA256_RE.fullmatch(contract_sha256)
        or rpc.get("host") != "127.0.0.1"
        or rpc.get("port") != spec.port
        or not isinstance(nonce, str)
        or not nonce
    ):
        raise ProviderNetworkPrepareError(
            "provider-network isolation contradicts the durable run identity"
        )

    try:
        public_identity = dict(controller.public_identity())
        guard = {
            str(key): str(value)
            for key, value in controller.python_guard_environment().items()
        }
        helper_path = Path(controller.helper_path)
        cgroup_path = Path(controller.cgroup_path)
        guard_attestation_path = Path(controller.guard_attestation_path)
        helper_sha256 = str(controller.helper_sha256)
        identity_sha256 = str(controller.identity_sha256)
    except Exception as exc:
        raise ProviderNetworkPrepareError(
            "provider-network controller identity is unavailable"
        ) from exc

    expected_public_keys = {
        "schema",
        "classification",
        "integration_status",
        "run_id",
        "contract_sha256",
        "identity_sha256",
        "assigned_host",
        "assigned_port",
        "poison_sink_host",
        "poison_sink_port",
        "nonce_matched",
    }
    if (
        set(public_identity) != expected_public_keys
        or public_identity.get("schema") != "fortgym.provider-network-manifest/v1"
        or public_identity.get("classification")
        != "isolated_x86_linux_provider_network_control"
        or public_identity.get("integration_status")
        != PROVIDER_NETWORK_INTEGRATION_STATUS
        or public_identity.get("run_id") != spec.run_id
        or public_identity.get("contract_sha256") != contract_sha256
        or public_identity.get("identity_sha256") != identity_sha256
        or public_identity.get("assigned_host") != "127.0.0.1"
        or public_identity.get("assigned_port") != spec.port
        or public_identity.get("nonce_matched") is not True
        or not _SHA256_RE.fullmatch(identity_sha256)
    ):
        raise ProviderNetworkPrepareError(
            "provider-network controller public identity is contradictory"
        )
    if (
        controller.run_id != spec.run_id
        or controller.contract_sha256 != contract_sha256
        or controller.assigned_host != "127.0.0.1"
        or controller.assigned_port != spec.port
    ):
        raise ProviderNetworkPrepareError(
            "provider-network controller attributes contradict the run"
        )

    expected_guard = {
        "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
        "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
        "FORT_GYM_NETWORK_ALLOWED_PORT": str(spec.port),
        "FORT_GYM_RUN_ID": spec.run_id,
        "FORT_GYM_RUN_CONTRACT_SHA256": contract_sha256,
        "FORT_GYM_RUN_NONCE": nonce,
    }
    if set(guard) != {*expected_guard, "FORT_GYM_NETWORK_EVIDENCE_PATH"}:
        raise ProviderNetworkPrepareError(
            "provider-network Python guard environment is noncanonical"
        )
    if any(guard.get(name) != value for name, value in expected_guard.items()):
        raise ProviderNetworkPrepareError(
            "provider-network Python guard identity is contradictory"
        )
    evidence_path = Path(guard["FORT_GYM_NETWORK_EVIDENCE_PATH"])
    if not evidence_path.is_absolute() or "\0" in str(evidence_path):
        raise ProviderNetworkPrepareError(
            "provider-network Python evidence path must be absolute"
        )

    for name, expected in expected_guard.items():
        existing = spec.env.get(name)
        if existing is not None and str(existing) != expected:
            raise ProviderNetworkPrepareError(
                f"RunSpec environment contradicts provider-network guard: {name}"
            )
    existing_policy = spec.env.get("FORT_GYM_NETWORK_POLICY")
    if existing_policy is not None and existing_policy != "loopback-port-only":
        raise ProviderNetworkPrepareError(
            "RunSpec network policy contradicts provider-network isolation"
        )

    if (
        not helper_path.is_absolute()
        or not helper_path.is_file()
        or not os.access(helper_path, os.X_OK)
        or not _SHA256_RE.fullmatch(helper_sha256)
        or _sha256_file(helper_path) != helper_sha256
        or not cgroup_path.is_absolute()
        or not guard_attestation_path.is_absolute()
    ):
        raise ProviderNetworkPrepareError(
            "provider-network launch helper is not the pinned executable"
        )

    try:
        launch_argv = tuple(str(item) for item in controller.enter_argv(spec.argv))
    except Exception as exc:
        raise ProviderNetworkPrepareError(
            "provider-network wrapper command is unavailable"
        ) from exc
    expected_wrapper = (
        str(helper_path),
        "enter",
        "--cgroup",
        str(cgroup_path),
        "--identity-sha256",
        identity_sha256,
        "--require-python-policy",
        "loopback-port-only",
        "--guard-attestation",
        str(guard_attestation_path),
        "--",
        *spec.argv,
    )
    if launch_argv != expected_wrapper or any("\0" in item for item in launch_argv):
        raise ProviderNetworkPrepareError(
            "provider-network wrapper command is noncanonical"
        )

    evidence_path_sha256 = hashlib.sha256(
        str(evidence_path).encode("utf-8")
    ).hexdigest()
    evidence = {
        "schema": PROVIDER_NETWORK_LAUNCH_SCHEMA,
        "mode": "cgroup-bpf-join-before-exec",
        "run_id": spec.run_id,
        "provider_network_identity": public_identity,
        "helper": {"path": str(helper_path), "sha256": helper_sha256},
        "inner_argv": list(spec.argv),
        "inner_argv_sha256": canonical_argv_sha256(spec.argv),
        "wrapper_argv": list(launch_argv),
        "wrapper_argv_sha256": canonical_argv_sha256(launch_argv),
        "python_guard": {
            "policy": "loopback-port-only",
            "allowed_host": "127.0.0.1",
            "allowed_port": spec.port,
            "evidence_path_sha256": evidence_path_sha256,
            "run_id": spec.run_id,
            "contract_sha256": contract_sha256,
            "nonce_matched": True,
        },
    }
    return ProviderNetworkLaunchPlan(
        argv=launch_argv,
        guard_environment=MappingProxyType(dict(guard)),
        evidence=_freeze_evidence_mapping("provider-network launch", evidence),
    )


def _validated_provider_network_report(
    value: Mapping[str, Any],
    *,
    identity_sha256: str,
) -> dict[str, Any]:
    expected_keys = {
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
        set(value) != expected_keys
        or value.get("schema") != "fortgym.provider-network-report/v1"
        or value.get("ok") is not True
        or value.get("classification") != "isolated_x86_linux_provider_network_control"
        or value.get("identity_sha256") != identity_sha256
        or value.get("only_assigned_dfhack_connection") is not True
        or value.get("python_guard_attested") is not True
        or value.get("kernel_enforcement_attested") is not True
        or value.get("negative_canary_attested") is not True
        or value.get("denied_hooks") != ["connect4", "connect6", "sendmsg4", "sendmsg6"]
    ):
        raise ProviderNetworkPrepareError(
            "provider-network final validation report is contradictory"
        )
    integer_zero_fields = (
        "dns_connections",
        "port_443_connections",
        "poison_sink_connections",
        "lost_events",
        "provider_calls",
        "provider_events",
        "provider_tokens",
    )
    if any(
        isinstance(value.get(name), bool)
        or not isinstance(value.get(name), int)
        or value.get(name) != 0
        for name in integer_zero_fields
    ):
        raise ProviderNetworkPrepareError(
            "provider-network final validation did not prove zero external activity"
        )
    provider_cost = value.get("provider_cost_usd")
    if (
        isinstance(provider_cost, bool)
        or not isinstance(provider_cost, (int, float))
        or not math.isfinite(float(provider_cost))
        or float(provider_cost) != 0.0
    ):
        raise ProviderNetworkPrepareError(
            "provider-network final validation did not prove zero provider cost"
        )
    count_fields = (
        "assigned_dfhack_connections",
        "denied_attempts",
        "denied_dns_attempts",
        "denied_443_attempts",
        "denied_poison_attempts",
    )
    if any(
        isinstance(value.get(name), bool)
        or not isinstance(value.get(name), int)
        or int(value[name]) < 0
        for name in count_fields
    ):
        raise ProviderNetworkPrepareError(
            "provider-network final validation counters are invalid"
        )
    if int(value["assigned_dfhack_connections"]) <= 0:
        raise ProviderNetworkPrepareError(
            "provider-network final validation lacks the assigned DFHack connection"
        )
    if (
        int(value["denied_attempts"]) < 6
        or int(value["denied_dns_attempts"]) < 3
        or int(value["denied_443_attempts"]) < 1
        or int(value["denied_poison_attempts"]) < 1
    ):
        raise ProviderNetworkPrepareError(
            "provider-network final validation lacks negative canary denials"
        )
    return dict(value)


def _callback_result(
    name: str, value: Mapping[str, Any] | None
) -> tuple[bool, dict[str, Any]]:
    """Validate one callback result without turning failure evidence into success."""

    if value is None:
        return True, {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} callback must return a mapping or None")
    details = _json_safe(value)
    if not isinstance(details, dict):
        raise TypeError(f"{name} callback evidence did not normalize to an object")
    ok = "ok" not in value or value["ok"] is True
    return ok, details


class ProcessSupervisor:
    """Supervise exactly one child process group and produce durable evidence."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._signal_lock = threading.Lock()
        self._external_signal: int | None = None

    def request_stop(self, signum: int = signal.SIGTERM) -> None:
        """Request externally classified termination from a signal handler/thread."""

        with self._signal_lock:
            self._external_signal = int(signum)
            self._stop_event.set()

    def run(
        self,
        spec: RunSpec,
        *,
        prepare: PrepareCallback | None = None,
        cleanup: CleanupCallback | None = None,
        post_cleanup: CleanupCallback | None = None,
        fault_classifier: FaultClassifier | None = None,
        pre_cleanup_observer: PreCleanupObserver | None = None,
        provider_network: ProviderNetworkController | None = None,
    ) -> SupervisionResult:
        if pre_cleanup_observer is not None and not callable(pre_cleanup_observer):
            raise TypeError("pre_cleanup_observer must be callable or None")
        artifact_dir = spec.artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        terminal_path = artifact_dir / "terminal.json"
        journal_path = artifact_dir / "attempt-journal.jsonl"
        if terminal_path.exists():
            raise SupervisorError(f"terminal record already exists for {spec.run_id}")

        with self._signal_lock:
            self._external_signal = None
            self._stop_event.clear()

        journal = AttemptJournal(journal_path)
        trace_path = spec.trace_path or artifact_dir / "trace.jsonl"
        monitor = TraceBudgetMonitor(trace_path, spec)
        supervisor_runtime = _supervisor_runtime()
        started_at = _utc_now()
        started_monotonic = time.monotonic()
        journal.append(
            "attempt_started",
            run_id=spec.run_id,
            scripted=spec.scripted,
            provider_enabled=spec.provider_enabled,
            argv0=spec.argv[0],
            port=spec.port,
            environment_identity=spec.environment_identity,
            cotenancy=spec.cotenancy,
            supervisor_runtime=supervisor_runtime,
        )

        lease: PortLease | None = None
        process: subprocess.Popen[bytes] | None = None
        stdout_handle: Any = None
        stderr_handle: Any = None
        primary_class = TerminalClass.CHILD_EXIT
        reason: dict[str, Any] = {"code": "child_not_started"}
        termination: dict[str, Any] = {}
        prepare_record: dict[str, Any] = {"ok": True, "skipped": True}
        provider_network_plan: ProviderNetworkLaunchPlan | None = None
        provider_network_prepare_started = False
        provider_network_prepare_completed = False
        provider_network_record: dict[str, Any] | None = None

        try:
            if spec.port is not None:
                lease = PortLease(spec.port, spec.port_lock_dir).acquire()
                journal.append("port_leased", run_id=spec.run_id, port=spec.port)

            if provider_network is not None:
                try:
                    provider_network_plan = build_provider_network_launch_plan(
                        spec, provider_network
                    )
                    journal.append(
                        "provider_network_prepare_started",
                        run_id=spec.run_id,
                        launch=provider_network_plan.evidence,
                    )
                    provider_network_prepare_started = True
                    raw_network_prepare = provider_network.prepare()
                    if (
                        not isinstance(raw_network_prepare, Mapping)
                        or raw_network_prepare.get("ok") is not True
                    ):
                        raise ProviderNetworkPrepareError(
                            "provider-network prepare did not report exact success"
                        )
                    provider_network_prepare_completed = True
                    provider_network_record = {
                        "enabled": True,
                        "launch": provider_network_plan.evidence,
                        "prepare": {"ok": True},
                    }
                    journal.append(
                        "provider_network_prepared",
                        run_id=spec.run_id,
                        launch_argv_sha256=provider_network_plan.evidence[
                            "wrapper_argv_sha256"
                        ],
                        inner_argv_sha256=provider_network_plan.evidence[
                            "inner_argv_sha256"
                        ],
                        provider_network_identity_sha256=(
                            provider_network.identity_sha256
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - redact controller failure
                    if isinstance(exc, ProviderNetworkPrepareError):
                        failure = exc
                    else:
                        failure = ProviderNetworkPrepareError(
                            "provider-network prepare failed closed"
                        )
                    provider_network_record = {
                        "enabled": True,
                        "prepare": {
                            "ok": False,
                            "error": {
                                "type": type(failure).__name__,
                                "message": str(failure),
                            },
                        },
                    }
                    if provider_network_plan is not None:
                        provider_network_record["launch"] = (
                            provider_network_plan.evidence
                        )
                    journal.append(
                        "provider_network_prepare_failed",
                        run_id=spec.run_id,
                        provider_network=provider_network_record,
                    )
                    raise failure from None

            if prepare is not None:
                journal.append("runtime_prepare_started", run_id=spec.run_id)
                try:
                    prepare_ok, details = _callback_result("prepare", prepare())
                except Exception as exc:
                    pre_readiness_oom = _trusted_pre_readiness_oom_receipt(exc, spec)
                    terminal_code = _trusted_prepare_terminal_code(exc)
                    if pre_readiness_oom is not None:
                        prepare_record = {
                            "ok": False,
                            "skipped": False,
                            "terminal_code": "oom_256m_pre_readiness",
                            "runtime_oom_classifier_eligible": True,
                            "pre_readiness_oom": pre_readiness_oom,
                            "error": {
                                "type": "RuntimeOomPreReadiness",
                                "message": (
                                    "verified pre-readiness OOM before harness launch"
                                ),
                            },
                        }
                    else:
                        prepare_record = {
                            "ok": False,
                            "skipped": False,
                            "error": _safe_error(exc),
                        }
                        if terminal_code is not None:
                            prepare_record["terminal_code"] = terminal_code
                    journal.append(
                        "runtime_prepare_failed",
                        run_id=spec.run_id,
                        prepare=prepare_record,
                    )
                    raise RuntimePrepareError(
                        "runtime prepare callback failed"
                    ) from exc
                prepare_record = {
                    "ok": prepare_ok,
                    "skipped": False,
                    "details": details,
                }
                if prepare_ok:
                    journal.append(
                        "runtime_prepare_completed",
                        run_id=spec.run_id,
                        prepare=prepare_record,
                    )
                else:
                    journal.append(
                        "runtime_prepare_failed",
                        run_id=spec.run_id,
                        prepare=prepare_record,
                    )
                    raise RuntimePrepareError(
                        "runtime prepare callback reported failure"
                    )

            child_env = build_sanitized_environment(
                allowlist=spec.env_allowlist,
                overrides=spec.env,
                scripted=spec.scripted,
            )
            launch_argv = spec.argv
            if provider_network_plan is not None:
                revalidated_plan = build_provider_network_launch_plan(
                    spec, provider_network
                )
                if (
                    revalidated_plan.argv != provider_network_plan.argv
                    or revalidated_plan.evidence != provider_network_plan.evidence
                    or revalidated_plan.guard_environment
                    != provider_network_plan.guard_environment
                ):
                    raise ProviderNetworkPrepareError(
                        "provider-network launch identity changed before exec"
                    )
                child_env.update(provider_network_plan.guard_environment)
                launch_argv = provider_network_plan.argv
                rpc_identity = spec.environment_identity.get("rpc")
                if not isinstance(rpc_identity, Mapping) or not isinstance(
                    rpc_identity.get("nonce"), str
                ):
                    raise ProviderNetworkPrepareError(
                        "provider-network launch intent lacks the private nonce identity"
                    )
                journal.append(
                    "provider_network_launch_intent",
                    run_id=spec.run_id,
                    launch_argv_sha256=provider_network_plan.evidence[
                        "wrapper_argv_sha256"
                    ],
                    inner_argv_sha256=provider_network_plan.evidence[
                        "inner_argv_sha256"
                    ],
                    provider_network_identity_sha256=(provider_network.identity_sha256),
                    contract_sha256=spec.environment_identity["contract_sha256"],
                    nonce_sha256=hashlib.sha256(
                        str(rpc_identity["nonce"]).encode("utf-8")
                    ).hexdigest(),
                )
            stdout_handle = (artifact_dir / "child.stdout.log").open("ab", buffering=0)
            stderr_handle = (artifact_dir / "child.stderr.log").open("ab", buffering=0)
            popen_kwargs: dict[str, Any] = {
                "cwd": str(spec.cwd) if spec.cwd is not None else None,
                "env": child_env,
                "stdin": subprocess.DEVNULL,
                "stdout": stdout_handle,
                "stderr": stderr_handle,
            }
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            else:  # pragma: no cover - Windows fallback
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(launch_argv, **popen_kwargs)
            child_fields: dict[str, Any] = {}
            if provider_network_plan is not None:
                child_fields = {
                    "launch_mode": "cgroup-bpf-join-before-exec",
                    "launch_argv_sha256": provider_network_plan.evidence[
                        "wrapper_argv_sha256"
                    ],
                    "inner_argv_sha256": provider_network_plan.evidence[
                        "inner_argv_sha256"
                    ],
                    "provider_network_identity_sha256": (
                        provider_network.identity_sha256
                    ),
                }
            journal.append(
                "child_started",
                run_id=spec.run_id,
                child_pid=process.pid,
                **child_fields,
            )

            deadline = started_monotonic + spec.timeout_seconds
            while True:
                violation = monitor.poll()
                if violation is not None:
                    primary_class = violation.terminal_class
                    reason = {"code": violation.reason, **dict(violation.details)}
                    journal.append(
                        "termination_requested",
                        run_id=spec.run_id,
                        terminal_class=primary_class.value,
                        reason=reason,
                    )
                    termination = {
                        "ok": True,
                        "deferred": True,
                        "reason": "terminal_chain_evidence",
                    }
                    break

                with self._signal_lock:
                    external_signal = self._external_signal
                if self._stop_event.is_set():
                    primary_class = TerminalClass.EXTERNAL_SIGNAL
                    reason = {
                        "code": "supervisor_stop_requested",
                        "signal": external_signal,
                    }
                    journal.append(
                        "termination_requested",
                        run_id=spec.run_id,
                        terminal_class=primary_class.value,
                        reason=reason,
                    )
                    termination = {
                        "ok": True,
                        "deferred": True,
                        "reason": "terminal_chain_evidence",
                    }
                    break

                returncode = process.poll()
                if returncode is not None:
                    final_violation = monitor.finalize()
                    if final_violation is not None:
                        primary_class = final_violation.terminal_class
                        reason = {
                            "code": final_violation.reason,
                            **dict(final_violation.details),
                        }
                    elif returncode == 0:
                        primary_class = TerminalClass.COMPLETED
                        reason = {"code": "child_completed"}
                    elif returncode < 0:
                        primary_class = TerminalClass.EXTERNAL_SIGNAL
                        reason = {"code": "child_signaled", "signal": -returncode}
                    else:
                        primary_class = TerminalClass.CHILD_EXIT
                        reason = {
                            "code": "child_nonzero_exit",
                            "returncode": returncode,
                        }
                    break

                now = time.monotonic()
                if now >= deadline:
                    primary_class = TerminalClass.TIMEOUT
                    reason = {"code": "wall_timeout", "seconds": spec.timeout_seconds}
                    journal.append(
                        "termination_requested",
                        run_id=spec.run_id,
                        terminal_class=primary_class.value,
                        reason=reason,
                    )
                    termination = {
                        "ok": True,
                        "deferred": True,
                        "reason": "terminal_chain_evidence",
                    }
                    break
                self._stop_event.wait(min(spec.poll_interval_seconds, deadline - now))
        except RuntimePrepareError:
            primary_class = TerminalClass.PREPARE_FAILURE
            reason = {
                "code": prepare_record.get("terminal_code") or "runtime_prepare_failed",
                **dict(prepare_record.get("error") or {}),
            }
        except ProviderNetworkPrepareError as exc:
            primary_class = TerminalClass.PREPARE_FAILURE
            reason = {"code": "provider_network_prepare_failed", **_safe_error(exc)}
        except PortLeaseBusy as exc:
            primary_class = TerminalClass.PORT_POLICY_FAILURE
            reason = {
                "code": "port_lease_busy",
                "port": spec.port,
                **_safe_error(exc),
            }
            journal.append("port_policy_rejected", run_id=spec.run_id, reason=reason)
        except PortUnavailable as exc:
            primary_class = TerminalClass.PORT_POLICY_FAILURE
            reason = {
                "code": "port_unavailable",
                "port": spec.port,
                **_safe_error(exc),
            }
            journal.append("port_policy_rejected", run_id=spec.run_id, reason=reason)
        except PortLeaseError as exc:
            primary_class = TerminalClass.PORT_POLICY_FAILURE
            reason = {
                "code": "port_lease_error",
                "port": spec.port,
                **_safe_error(exc),
            }
            journal.append("port_policy_rejected", run_id=spec.run_id, reason=reason)
        except Exception as exc:  # noqa: BLE001 - terminal boundary must capture child errors
            primary_class = TerminalClass.CHILD_EXIT
            reason = {"code": "supervisor_start_or_monitor_error", **_safe_error(exc)}
            journal.append("supervisor_error", run_id=spec.run_id, reason=reason)
            if process is not None:
                termination = {
                    "ok": True,
                    "deferred": True,
                    "reason": "terminal_chain_evidence",
                }

        child_pid = process.pid if process is not None else None
        chain_identity = _terminal_chain_identity(spec, child_pid=child_pid)
        journal.append(
            "terminal_pending_cleanup",
            run_id=spec.run_id,
            identity=chain_identity,
            primary_terminal_class=primary_class.value,
            primary_reason_sha256=_canonical_sha256(reason),
        )

        pre_cleanup_snapshot: Mapping[str, Any] | None = None
        pre_cleanup_error: dict[str, str] | None = None
        pre_cleanup_reason_codes = {
            "child_completed",
            "child_nonzero_exit",
            "child_signaled",
            "wall_timeout",
        }
        enospc_trace_candidate = (
            primary_class is TerminalClass.CAP_TRIP
            and reason.get("code") == "trace_accounting_invalid"
            and spec.scripted
            and not spec.provider_enabled
        )
        pre_cleanup_eligible = (
            pre_cleanup_observer is not None
            and process is not None
            and (reason.get("code") in pre_cleanup_reason_codes or enospc_trace_candidate)
        )
        if pre_cleanup_eligible:
            observed_returncode = process.poll()
            observed_child_signal = (
                -observed_returncode
                if isinstance(observed_returncode, int) and observed_returncode < 0
                else None
            )
            pre_cleanup_observation = _freeze_evidence_mapping(
                "pre-cleanup observation",
                {
                    "schema": PRE_CLEANUP_OBSERVATION_SCHEMA,
                    "run_id": spec.run_id,
                    "primary_terminal_class": primary_class.value,
                    "primary_reason": reason,
                    "child_pid": process.pid,
                    "returncode": observed_returncode,
                    "child_signal": observed_child_signal,
                    "environment_identity": spec.environment_identity,
                    "prepare": prepare_record,
                    "termination": termination,
                },
            )
            journal.append(
                "cleanup_started",
                run_id=spec.run_id,
                primary_terminal_class=primary_class.value,
                reason=reason,
            )
            try:
                if pre_cleanup_observer is None:
                    raise SupervisorError(
                        "eligible pre-cleanup evidence observer is unavailable"
                    )
                raw_snapshot = pre_cleanup_observer(pre_cleanup_observation)
                if not isinstance(raw_snapshot, Mapping):
                    raise TypeError("pre-cleanup observer must return a mapping")
                frozen_snapshot = _freeze_evidence_mapping(
                    "pre-cleanup snapshot", raw_snapshot
                )
                pre_cleanup_snapshot = validate_pre_cleanup_snapshot(
                    frozen_snapshot,
                    pre_cleanup_observation,
                )
                journal.append(
                    "fault_evidence_snapshot_attached",
                    run_id=spec.run_id,
                    session_sha256=pre_cleanup_snapshot["session_sha256"],
                    gate=pre_cleanup_snapshot["gate"],
                    role=pre_cleanup_snapshot["role"],
                    source_completed_record_sha256=pre_cleanup_snapshot[
                        "participant_claim"
                    ]["source_completed_record_sha256"],
                )
            except Exception as exc:  # noqa: BLE001 - cleanup must still run
                pre_cleanup_error = _safe_error(exc)
                journal.append(
                    "evidence_snapshot_failed",
                    run_id=spec.run_id,
                    error=pre_cleanup_error,
                )
        elif pre_cleanup_observer is not None:
            journal.append(
                "pre_cleanup_evidence_skipped",
                run_id=spec.run_id,
                primary_terminal_class=primary_class.value,
                reason=reason,
            )

        snapshot_path = artifact_dir / "evidence-snapshot.json"
        snapshot_error: dict[str, str] | None = None
        snapshot_sha256: str | None = None
        try:
            for handle in (stdout_handle, stderr_handle):
                if handle is not None and not handle.closed:
                    os.fsync(handle.fileno())
            files: dict[str, Any] = {}
            for name, evidence_path in (
                ("trace", trace_path),
                ("child_stdout", artifact_dir / "child.stdout.log"),
                ("child_stderr", artifact_dir / "child.stderr.log"),
            ):
                if not evidence_path.exists():
                    files[name] = {"present": False}
                    continue
                metadata = evidence_path.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise SupervisorError(
                        "generic evidence snapshot encountered an unsafe file"
                    )
                files[name] = {
                    "present": True,
                    "path": str(evidence_path.resolve(strict=True)),
                    "size_bytes": metadata.st_size,
                    "sha256": _sha256_file(evidence_path),
                }
            snapshot_payload = {
                "schema": EVIDENCE_SNAPSHOT_SCHEMA,
                "identity": chain_identity,
                "primary_terminal_class": primary_class.value,
                "primary_reason": reason,
                "prepare": prepare_record,
                "termination": termination,
                "files": files,
                "fault_snapshot": (
                    _json_safe(pre_cleanup_snapshot)
                    if pre_cleanup_snapshot is not None
                    else None
                ),
                "fault_snapshot_error": pre_cleanup_error,
            }
            _atomic_write_json(snapshot_path, snapshot_payload)
            snapshot_sha256 = _sha256_file(snapshot_path)
        except Exception as exc:  # noqa: BLE001 - cleanup must still execute
            snapshot_error = _safe_error(exc)
        journal.append(
            "evidence_snapshot_completed",
            run_id=spec.run_id,
            identity=chain_identity,
            ok=snapshot_sha256 is not None,
            snapshot_path=str(snapshot_path.resolve(strict=False)),
            snapshot_sha256=snapshot_sha256,
            fault_snapshot_attached=pre_cleanup_snapshot is not None,
            error=snapshot_error,
        )

        cleanup_stages: list[dict[str, Any]] = [
            {
                "stage": "evidence_snapshot",
                "ok": snapshot_sha256 is not None,
                "path": str(snapshot_path.resolve(strict=False)),
                "sha256": snapshot_sha256,
                "error": snapshot_error,
            }
        ]
        process_cleanup = self._cleanup_process(process, spec.term_grace_seconds)
        cleanup_stages.append(process_cleanup)
        if termination.get("deferred") is True:
            resolved_termination = process_cleanup.get("details")
            termination = (
                dict(resolved_termination)
                if isinstance(resolved_termination, Mapping)
                else {
                    "ok": process_cleanup.get("ok") is True,
                    "error": process_cleanup.get("error"),
                }
            )
        journal.append(
            "harness_process_group_reaped",
            run_id=spec.run_id,
            identity=chain_identity,
            ok=process_cleanup.get("ok") is True,
            skipped=process is None,
            child_pid=child_pid,
            group_exists=process_cleanup.get("group_exists"),
        )
        cleanup_stages.append(self._close_stdio(stdout_handle, stderr_handle))

        if (
            provider_network is not None
            and provider_network_plan is not None
            and provider_network_prepare_started
        ):
            network_cleanup_ok = False
            try:
                if process is None:
                    raw_network_cleanup = provider_network.abort(recovered=False)
                    network_cleanup_mode = "prelaunch_abort"
                else:
                    raw_network_cleanup = provider_network.cleanup()
                    network_cleanup_mode = "launched_cleanup"
                if (
                    not isinstance(raw_network_cleanup, Mapping)
                    or raw_network_cleanup.get("ok") is not True
                    or raw_network_cleanup.get("foreign_canary_untouched") is not True
                ):
                    raise ProviderNetworkPrepareError(
                        "provider-network cleanup did not report exact success"
                    )
                network_cleanup_ok = True
                cleanup_stages.append(
                    {
                        "stage": "provider_network",
                        "ok": True,
                        "mode": network_cleanup_mode,
                        "identity_sha256": provider_network.identity_sha256,
                        "foreign_canary_untouched": True,
                    }
                )
                journal.append(
                    "provider_network_cleanup_recorded",
                    run_id=spec.run_id,
                    ok=True,
                    mode=network_cleanup_mode,
                    identity_sha256=provider_network.identity_sha256,
                )
            except Exception as exc:  # noqa: BLE001 - cleanup evidence must survive
                cleanup_stages.append(
                    {
                        "stage": "provider_network",
                        "ok": False,
                        "error": {
                            "type": type(exc).__name__,
                            "message": "provider-network cleanup failed closed",
                        },
                    }
                )
                journal.append(
                    "provider_network_cleanup_recorded",
                    run_id=spec.run_id,
                    ok=False,
                )

            if process is not None and network_cleanup_ok:
                try:
                    raw_network_validation = provider_network.validate_evidence(
                        monitor.snapshot()
                    )
                    if not isinstance(raw_network_validation, Mapping):
                        raise ProviderNetworkPrepareError(
                            "provider-network validation returned invalid evidence"
                        )
                    network_validation = _validated_provider_network_report(
                        raw_network_validation,
                        identity_sha256=provider_network.identity_sha256,
                    )
                    cleanup_stages.append(
                        {
                            "stage": "provider_network_validation",
                            "ok": True,
                            "details": network_validation,
                        }
                    )
                    journal.append(
                        "provider_network_validated",
                        run_id=spec.run_id,
                        report=network_validation,
                    )
                    if provider_network_record is None:
                        raise ProviderNetworkPrepareError(
                            "provider-network validation lacks its durable prepare record"
                        )
                    provider_network_record["validation"] = network_validation
                except Exception as exc:  # noqa: BLE001 - fail closed before terminal
                    cleanup_stages.append(
                        {
                            "stage": "provider_network_validation",
                            "ok": False,
                            "error": {
                                "type": type(exc).__name__,
                                "message": (
                                    "provider-network evidence validation failed closed"
                                ),
                            },
                        }
                    )
                    journal.append(
                        "provider_network_validation_failed",
                        run_id=spec.run_id,
                    )
            elif process is None:
                cleanup_stages.append(
                    {
                        "stage": "provider_network_validation",
                        "ok": True,
                        "skipped": "child_not_started",
                    }
                )

            if provider_network_record is not None:
                provider_network_record["prepare_completed"] = (
                    provider_network_prepare_completed
                )
        elif provider_network is not None:
            cleanup_stages.append(
                {
                    "stage": "provider_network",
                    "ok": True,
                    "skipped": "prepare_not_started",
                }
            )

        if cleanup is not None:
            try:
                cleanup_ok, details = _callback_result("cleanup", cleanup())
                cleanup_stages.append(
                    {
                        "stage": "callback",
                        "ok": cleanup_ok,
                        "details": details,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - cleanup evidence must survive callbacks
                cleanup_stages.append(
                    {"stage": "callback", "ok": False, "error": _safe_error(exc)}
                )
        else:
            cleanup_stages.append({"stage": "callback", "ok": True, "skipped": True})

        if post_cleanup is not None:
            journal.append("post_cleanup_started", run_id=spec.run_id)
            try:
                post_cleanup_ok, details = _callback_result(
                    "post_cleanup", post_cleanup()
                )
                cleanup_stages.append(
                    {
                        "stage": "post_callback",
                        "ok": post_cleanup_ok,
                        "details": details,
                    }
                )
                journal.append(
                    "post_cleanup_completed",
                    run_id=spec.run_id,
                    ok=post_cleanup_ok,
                    details=details,
                )
            except Exception as exc:  # noqa: BLE001 - preserve cleanup failure
                cleanup_stages.append(
                    {
                        "stage": "post_callback",
                        "ok": False,
                        "error": _safe_error(exc),
                    }
                )
                journal.append(
                    "post_cleanup_completed",
                    run_id=spec.run_id,
                    ok=False,
                    error=_safe_error(exc),
                )
        if lease is not None:
            try:
                lease.release()
                cleanup_stages.append(
                    {"stage": "port_lease", "ok": True, "port": spec.port}
                )
            except Exception as exc:  # noqa: BLE001 - cleanup evidence must survive release
                cleanup_stages.append(
                    {"stage": "port_lease", "ok": False, "error": _safe_error(exc)}
                )
        else:
            cleanup_stages.append({"stage": "port_lease", "ok": True, "skipped": True})

        callback_stages = [
            stage for stage in cleanup_stages if stage.get("stage") == "callback"
        ]
        callback_stage = callback_stages[0] if len(callback_stages) == 1 else None
        callback_details = (
            callback_stage.get("details")
            if isinstance(callback_stage, Mapping)
            and isinstance(callback_stage.get("details"), Mapping)
            else None
        )
        shared_listener_preserved = bool(
            callback_details is not None
            and callback_details.get("shared_listener_preserved") is True
            and primary_class is TerminalClass.PORT_POLICY_FAILURE
            and isinstance(reason, Mapping)
            and reason.get("code") == "port_lease_busy"
            and child_pid is None
        )
        runtime_removal_skipped = not spec.runtime_cleanup_required
        runtime_removed = bool(
            runtime_removal_skipped
            or (
                callback_stage is not None
                and callback_stage.get("ok") is True
                and (
                    not spec.runtime_cleanup_required
                    or (
                        callback_details is not None
                        and callback_details.get("container_absent") is True
                        and (
                            callback_details.get("listener_absent") is True
                            or shared_listener_preserved
                        )
                    )
                )
            )
        )
        if spec.runtime_cleanup_required:
            cleanup_stages.append(
                {
                    "stage": "runtime_removal_verification",
                    "ok": runtime_removed,
                    "container_absent": (
                        callback_details.get("container_absent")
                        if callback_details is not None
                        else None
                    ),
                    "listener_absent": (
                        callback_details.get("listener_absent")
                        if callback_details is not None
                        else None
                    ),
                    "shared_listener_preserved": shared_listener_preserved,
                }
            )
        cleanup_ok = all(bool(stage.get("ok")) for stage in cleanup_stages)
        cleanup_record = {"ok": cleanup_ok, "stages": cleanup_stages}
        journal.append(
            "runtime_container_removed",
            run_id=spec.run_id,
            identity=chain_identity,
            ok=runtime_removed,
            skipped=runtime_removal_skipped,
            container_absent=(
                callback_details.get("container_absent")
                if callback_details is not None
                else None
            ),
            listener_absent=(
                callback_details.get("listener_absent")
                if callback_details is not None
                else None
            ),
            shared_listener_preserved=shared_listener_preserved,
        )
        journal.append("cleanup_recorded", run_id=spec.run_id, cleanup=cleanup_record)

        returncode = process.returncode if process is not None else None
        child_signal = (
            -returncode if isinstance(returncode, int) and returncode < 0 else None
        )
        pre_readiness_oom_classifier_eligible = (
            primary_class is TerminalClass.PREPARE_FAILURE
            and prepare_record.get("terminal_code") == "oom_256m_pre_readiness"
            and prepare_record.get("runtime_oom_classifier_eligible") is True
            and isinstance(prepare_record.get("pre_readiness_oom"), Mapping)
        )
        terminal_class = primary_class
        primary_reason = reason
        # ENOSPC can truncate the last trace line. Only an independently validated
        # completed target ENOSPC session may outrank that accounting symptom;
        # real budget trips and all provider-enabled runs retain precedence.
        enospc_trace_proven = (
            enospc_trace_candidate
            and pre_cleanup_error is None
            and pre_cleanup_snapshot is not None
            and pre_cleanup_snapshot.get("gate") == "ENOSPC"
            and pre_cleanup_snapshot.get("role") == "target"
        )
        fault_record: dict[str, Any]
        if not cleanup_ok:
            terminal_class = TerminalClass.CLEANUP_FAILURE
            fault_record = {
                "schema": FAULT_CLASSIFICATION_RECORD_SCHEMA,
                "attempted": False,
                "ok": True,
                "classified": False,
                "skipped": "cleanup_failure_precedence",
            }
        elif fault_classifier is None and not pre_cleanup_eligible:
            fault_record = {
                "schema": FAULT_CLASSIFICATION_RECORD_SCHEMA,
                "attempted": False,
                "ok": True,
                "classified": False,
                "skipped": "classifier_not_configured",
            }
        elif (
            primary_class
            in {
                TerminalClass.PORT_POLICY_FAILURE,
                TerminalClass.PREPARE_FAILURE,
                TerminalClass.CAP_TRIP,
                TerminalClass.PROVIDER_PIN_VIOLATION,
            }
            and not pre_readiness_oom_classifier_eligible
            and not enospc_trace_proven
        ) or reason.get("code") == "supervisor_stop_requested":
            fault_record = {
                "schema": FAULT_CLASSIFICATION_RECORD_SCHEMA,
                "attempted": False,
                "ok": True,
                "classified": False,
                "skipped": "authoritative_primary_terminal_precedence",
            }
        else:
            observation = _freeze_evidence_mapping(
                "runtime fault observation",
                {
                    "schema": FAULT_OBSERVATION_SCHEMA,
                    "run_id": spec.run_id,
                    "primary_terminal_class": primary_class.value,
                    "primary_reason": reason,
                    "child_pid": child_pid,
                    "returncode": returncode,
                    "child_signal": child_signal,
                    "environment_identity": spec.environment_identity,
                    "prepare": prepare_record,
                    "termination": termination,
                    "cleanup": cleanup_record,
                    **({"scripted": spec.scripted, "provider_enabled": spec.provider_enabled}
                       if enospc_trace_proven else {}),
                },
            )
            try:
                if pre_cleanup_eligible:
                    if pre_cleanup_error is not None:
                        raise FaultSessionEvidenceError(
                            "pre-cleanup evidence snapshot failed: "
                            f"{pre_cleanup_error['type']}"
                        )
                    if pre_cleanup_snapshot is None:
                        raise FaultSessionEvidenceError(
                            "pre-cleanup evidence snapshot is missing"
                        )
                    raw_classification = pre_cleanup_snapshot["classifier_result"]
                else:
                    if fault_classifier is None:
                        raise FaultSessionEvidenceError(
                            "runtime fault classifier is unavailable"
                        )
                    raw_classification = fault_classifier(observation)
                if not isinstance(raw_classification, Mapping):
                    raise TypeError("runtime fault classifier must return a mapping")
                frozen_classification = _freeze_evidence_mapping(
                    "runtime fault classifier result", raw_classification
                )
                classification = validate_fault_classifier_result(
                    frozen_classification,
                    observation,
                    enospc_snapshot=(pre_cleanup_snapshot if enospc_trace_proven else None),
                )
                if classification.classified:
                    if classification.terminal_class is None:
                        raise FaultSessionEvidenceError(
                            "classified runtime fault lacks a terminal class"
                        )
                    terminal_class = TerminalClass(classification.terminal_class)
                    classified_reason = classification.reason()
                    if classified_reason is None:
                        raise FaultSessionEvidenceError(
                            "classified runtime fault lacks a terminal reason"
                        )
                    reason = classified_reason
                fault_record = {
                    "schema": FAULT_CLASSIFICATION_RECORD_SCHEMA,
                    "attempted": True,
                    "ok": True,
                    "classified": classification.classified,
                    "terminal_class": classification.terminal_class,
                    "evidence": _json_safe(classification.evidence),
                }
            except Exception as exc:  # noqa: BLE001 - fail closed before terminal write
                prior_terminal_class = primary_class.value
                prior_reason = reason
                terminal_class = TerminalClass.RUNTIME_FAULT_CLASSIFICATION_FAILURE
                reason = {
                    "code": (
                        _fault_classification.RUNTIME_FAULT_CLASSIFICATION_FAILURE
                    ),
                    "prior_terminal_class": prior_terminal_class,
                    "prior_terminal_reason": prior_reason,
                    "classification_error": _safe_error(exc),
                }
                fault_record = {
                    "schema": FAULT_CLASSIFICATION_RECORD_SCHEMA,
                    "attempted": True,
                    "ok": False,
                    "classified": False,
                    "error": _safe_error(exc),
                }
        payload = {
            "schema": "fortgym.process-supervisor-terminal/v1",
            "run_id": spec.run_id,
            "terminal_class": terminal_class.value,
            "primary_terminal_class": primary_class.value,
            "primary_reason": primary_reason,
            "reason": reason,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
            "child_pid": child_pid,
            "returncode": returncode,
            "child_signal": child_signal,
            "port": spec.port,
            "environment_identity": spec.environment_identity,
            "cotenancy": spec.cotenancy,
            "runtime_cleanup_required": spec.runtime_cleanup_required,
            "supervisor_runtime": supervisor_runtime,
            "budget": monitor.snapshot(),
            "prepare": prepare_record,
            "termination": termination,
            "cleanup": cleanup_record,
            "fault_classification": fault_record,
        }
        if pre_cleanup_observer is not None:
            payload["pre_cleanup_evidence"] = {
                "eligible": pre_cleanup_eligible,
                "snapshot": _json_safe(pre_cleanup_snapshot)
                if pre_cleanup_snapshot is not None
                else None,
                "error": pre_cleanup_error,
            }
        if provider_network_record is not None:
            payload["provider_network"] = provider_network_record
        terminal_draft_path = artifact_dir / "terminal-draft.json"
        _atomic_write_json(terminal_draft_path, payload)
        journal.append(
            "runtime_fault_classification_recorded",
            run_id=spec.run_id,
            fault_classification=fault_record,
            terminal_draft_path=str(terminal_draft_path),
            terminal_draft_sha256=_sha256_file(terminal_draft_path),
        )
        cleanup_sha256 = _canonical_sha256(cleanup_record)
        journal.append(
            "cleanup_verified",
            run_id=spec.run_id,
            identity=chain_identity,
            ok=cleanup_ok,
            cleanup_sha256=cleanup_sha256,
        )
        journal.append(
            "cleanup_completed",
            run_id=spec.run_id,
            identity=chain_identity,
            ok=cleanup_ok,
            cleanup_sha256=cleanup_sha256,
        )
        journal.append(
            "immutable_terminal_classification",
            run_id=spec.run_id,
            identity=chain_identity,
            terminal_class=terminal_class.value,
            reason_sha256=_canonical_sha256(reason),
            cleanup_sha256=cleanup_sha256,
            evidence_snapshot_sha256=snapshot_sha256,
        )
        journal.append(
            "terminal_pending",
            run_id=spec.run_id,
            terminal_class=terminal_class.value,
            cleanup_ok=cleanup_ok,
        )
        _atomic_write_json(terminal_path, payload)
        return SupervisionResult(terminal_class, terminal_path, journal_path, payload)

    @classmethod
    def _cleanup_process(
        cls,
        process: subprocess.Popen[bytes] | None,
        grace_seconds: float,
    ) -> dict[str, Any]:
        if process is None:
            return {"stage": "process_group", "ok": True, "skipped": True}
        try:
            details = cls._terminate_process_group(process, grace_seconds)
            group_exists = cls._process_group_exists(process.pid)
            ok = process.poll() is not None and not group_exists
            return {
                "stage": "process_group",
                "ok": ok,
                "returncode": process.returncode,
                "group_exists": group_exists,
                "details": details,
            }
        except Exception as exc:  # noqa: BLE001 - cleanup failure becomes terminal evidence
            return {"stage": "process_group", "ok": False, "error": _safe_error(exc)}

    @staticmethod
    def _close_stdio(stdout_handle: Any, stderr_handle: Any) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        for handle in (stdout_handle, stderr_handle):
            if handle is None or handle.closed:
                continue
            try:
                os.fsync(handle.fileno())
                handle.close()
            except Exception as exc:  # noqa: BLE001 - attempt every remaining close
                errors.append(_safe_error(exc))
        return {"stage": "stdio", "ok": not errors, "errors": errors}

    @classmethod
    def _terminate_process_group(
        cls,
        process: subprocess.Popen[bytes],
        grace_seconds: float,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            "term_sent": False,
            "kill_sent": False,
            "wait_complete": False,
        }
        if process.poll() is not None and not cls._process_group_exists(process.pid):
            details["wait_complete"] = True
            details["returncode"] = process.returncode
            return details

        cls._signal_process_group(process, signal.SIGTERM)
        details["term_sent"] = True
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            process.poll()
            if process.poll() is not None and not cls._process_group_exists(
                process.pid
            ):
                details["wait_complete"] = True
                details["returncode"] = process.returncode
                return details
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))

        if process.poll() is None or cls._process_group_exists(process.pid):
            cls._signal_process_group(process, signal.SIGKILL)
            details["kill_sent"] = True
        try:
            process.wait(timeout=max(1.0, grace_seconds))
        except subprocess.TimeoutExpired as exc:
            raise SupervisorError("child did not exit after SIGKILL") from exc
        kill_deadline = time.monotonic() + max(1.0, grace_seconds)
        while (
            cls._process_group_exists(process.pid) and time.monotonic() < kill_deadline
        ):
            time.sleep(0.01)
        if cls._process_group_exists(process.pid):
            raise SupervisorError("process group still exists after SIGKILL")
        details["wait_complete"] = True
        details["returncode"] = process.returncode
        return details

    @staticmethod
    def _signal_process_group(process: subprocess.Popen[bytes], signum: int) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signum)
            elif signum == signal.SIGTERM:  # pragma: no cover - Windows fallback
                process.terminate()
            else:  # pragma: no cover - Windows fallback
                process.kill()
        except ProcessLookupError:
            return

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        if os.name != "posix":  # pragma: no cover - Windows fallback
            return False
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SupervisorError(f"refusing to overwrite terminal record: {path}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(_json_safe(payload), handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "DEFAULT_MAX_COST_USD",
    "DEFAULT_MAX_TOTAL_TOKENS",
    "EVIDENCE_SNAPSHOT_SCHEMA",
    "PROVIDER_NETWORK_INTEGRATION_STATUS",
    "PROVIDER_NETWORK_LAUNCH_SCHEMA",
    "TERMINAL_CHAIN_EVENTS",
    "AttemptJournal",
    "FaultClassifier",
    "PortLease",
    "PortLeaseBusy",
    "PortLeaseError",
    "PortUnavailable",
    "PreCleanupObserver",
    "PrepareCallback",
    "ProcessSupervisor",
    "ProviderNetworkController",
    "ProviderNetworkLaunchPlan",
    "ProviderNetworkPrepareError",
    "RunSpec",
    "RuntimePrepareError",
    "SupervisionResult",
    "SupervisorError",
    "TerminalClass",
    "TraceBudgetMonitor",
    "build_provider_network_launch_plan",
    "build_sanitized_environment",
    "canonical_argv_sha256",
    "validate_terminal_chain",
    "write_recovered_terminal_chain",
]
