"""Fail-closed batch control for the frozen M1b live acceptance matrix.

This module is deliberately a constructor-only orchestration boundary.  It has
no CLI, API, environment-variable, Docker, network, or cloud integration.  A
host runner must explicitly inject an adapter and an opaque private-test
authorization.  The adapter receives only the frozen gate plan and single-use
attempt permits; it never receives provider credentials or ambient settings.

The controller owns the durable batch facts that are easy to get subtly wrong:

* the exact frozen 16-gate order and 26 real-runtime-attempt ceiling;
* the PORT-2 contender as a separately evidenced non-runtime conflict;
* append-only, fsynced, hash-chained batch and attempt ledgers;
* local-credit boundaries that cannot promote mock evidence into live credit;
* two cleanup passes after each substantive gate and after the batch;
* fail-closed resume validation; and
* deterministic, content-addressed result, decision, manifest, and seal files.

Concrete Linux host actions remain outside this file by design.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

import yaml

FROZEN_ACCEPTANCE_SCHEMA = "fortgym.environment-layer.m1b-acceptance/v1"
FROZEN_ACCEPTANCE_SHA256 = (
    "b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf"
)
MAX_REAL_RUNTIME_ATTEMPTS = 26
REQUIRED_CLEANUP_PASSES = 2

BATCH_LEDGER_SCHEMA = "fortgym.m1b-live-acceptance-batch-ledger/v1"
ATTEMPT_LEDGER_SCHEMA = "fortgym.m1b-live-acceptance-attempt-ledger/v1"
GATE_RESULTS_SCHEMA = "fortgym.m1b-live-acceptance-gate-results/v1"
DECISION_SCHEMA = "fortgym.m1b-live-acceptance-decision/v1"
EVIDENCE_MANIFEST_SCHEMA = "fortgym.m1b-live-acceptance-evidence-manifest/v1"
SEAL_SCHEMA = "fortgym.m1b-live-acceptance-seal/v1"
PLAN_SCHEMA = "fortgym.m1b-live-acceptance-plan/v1"

_MAX_CONTRACT_BYTES = 256 * 1024
_MAX_LEDGER_RECORD_BYTES = 128 * 1024
_MAX_LEDGER_RECORDS = 8_192
_MAX_EVIDENCE_FILES = 4_096
_MAX_EVIDENCE_FILE_BYTES = 1024 * 1024 * 1024
_ZERO_SHA256 = "0" * 64
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_PATH_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_AUTH_SENTINEL = object()
_PERMIT_SENTINEL = object()


class LiveAcceptanceError(RuntimeError):
    """Base error for M1b live-acceptance batch control."""


class LiveAcceptanceAuthorizationError(LiveAcceptanceError):
    """The private constructor authorization is absent or mismatched."""


class LiveAcceptanceContractError(LiveAcceptanceError):
    """The frozen acceptance file or in-code plan differs."""


class LiveAcceptanceEvidenceError(LiveAcceptanceError):
    """Durable evidence is missing, mutable, malformed, or contradictory."""


class LiveAcceptanceResumeError(LiveAcceptanceEvidenceError):
    """An interrupted batch is not at a safely resumable boundary."""


class LiveAcceptanceProtocolError(LiveAcceptanceError):
    """An injected adapter violated the narrow gate protocol."""


class AttemptKind(str, Enum):
    REAL_RUNTIME = "real_runtime"
    NON_RUNTIME_CONFLICT = "non_runtime_conflict"


class LocalCreditScope(str, Enum):
    COMPLETE_LOCAL_GATE = "complete_local_gate"
    LOCAL_SUBPROCEDURE = "local_subprocedure"


class GateStatus(str, Enum):
    PASS = "PASS"
    PASS_LOCAL = "PASS_LOCAL"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class BatchDecisionValue(str, Enum):
    GO = "GO"
    INCOMPLETE_NO_GO = "INCOMPLETE_NO_GO"


@dataclass(frozen=True)
class AttemptPlan:
    """One exact attempt slot assigned to a gate."""

    role: str
    kind: AttemptKind

    def __post_init__(self) -> None:
        if not _CODE_RE.fullmatch(self.role):
            raise ValueError("attempt role must be a bounded lowercase code")
        if not isinstance(self.kind, AttemptKind):
            raise TypeError("attempt kind must be an AttemptKind")

    def payload(self, *, gate_index: int, slot_index: int) -> dict[str, Any]:
        return {
            "attempt_id": f"g{gate_index:02d}-a{slot_index:02d}-{self.role}",
            "kind": self.kind.value,
            "role": self.role,
        }


@dataclass(frozen=True)
class GatePlan:
    """Frozen semantic and accounting metadata for one acceptance gate."""

    gate_id: str
    gate_class: str
    procedure: str
    pass_contract: tuple[tuple[str, Any], ...]
    attempts: tuple[AttemptPlan, ...] = ()
    local_credit_scope: LocalCreditScope | None = None
    derived: bool = False
    hard: bool = True

    @property
    def criteria(self) -> tuple[str, ...]:
        return tuple(name for name, _value in self.pass_contract)

    @property
    def real_runtime_attempts(self) -> int:
        return sum(
            attempt.kind is AttemptKind.REAL_RUNTIME for attempt in self.attempts
        )

    @property
    def non_runtime_attempts(self) -> int:
        return sum(
            attempt.kind is AttemptKind.NON_RUNTIME_CONFLICT
            for attempt in self.attempts
        )

    def acceptance_mapping(self) -> dict[str, Any]:
        return {
            "id": self.gate_id,
            "class": self.gate_class,
            "procedure": self.procedure,
            "pass": dict(self.pass_contract),
        }

    def payload(self, *, gate_index: int) -> dict[str, Any]:
        return {
            "index": gate_index,
            "id": self.gate_id,
            "class": self.gate_class,
            "procedure": self.procedure,
            "pass": dict(self.pass_contract),
            "attempts": [
                attempt.payload(gate_index=gate_index, slot_index=slot_index)
                for slot_index, attempt in enumerate(self.attempts, start=1)
            ],
            "local_credit_scope": (
                self.local_credit_scope.value
                if self.local_credit_scope is not None
                else None
            ),
            "derived": self.derived,
            "hard": self.hard,
        }


def _attempt(role: str, kind: AttemptKind = AttemptKind.REAL_RUNTIME) -> AttemptPlan:
    return AttemptPlan(role=role, kind=kind)


FROZEN_GATE_PLAN: tuple[GatePlan, ...] = (
    GatePlan(
        "PORT-1",
        "local",
        "race 32 supervisor requests against one port lease",
        (
            ("winners", 1),
            ("durable_port_lease_conflicts", 31),
            ("losers_start_runtime_or_harness", False),
        ),
        local_credit_scope=LocalCreditScope.COMPLETE_LOCAL_GATE,
    ),
    GatePlan(
        "PORT-2",
        "real_runtime",
        "request an already leased and listening port while peer A remains ready",
        (
            ("fail_closed_seconds_lte", 5),
            ("second_runtime_started", False),
            ("second_harness_started", False),
            ("peer_nonce_and_rpc_unchanged", True),
        ),
        attempts=(
            _attempt("peer_a"),
            _attempt("contender_b", AttemptKind.NON_RUNTIME_CONFLICT),
        ),
    ),
    GatePlan(
        "COLD-RETRY",
        "real_runtime",
        "suppress first RPC readiness in test mode, then retry exactly once",
        (
            ("first_terminal", "rpc_readiness_timeout"),
            ("first_cleanup_verified", True),
            ("second_uses_fresh_identity_and_resources", True),
            ("second_completes", True),
            ("production_mode_accepts_fault_knob", False),
        ),
        attempts=(_attempt("suppressed_first"), _attempt("replacement_second")),
    ),
    GatePlan(
        "CO-8",
        "isolated_x86_linux",
        "barrier-start eight fresh runtimes and eight harness processes",
        (
            ("logical_runs_completed", 8),
            ("seed_attestation_unique_count", 1),
            ("distinct_ports_nonces_containers_pids_homes_saves_artifacts", True),
            ("rpc_receipts_match_run_nonce", True),
            ("symmetric_cotenancy_graph", True),
            ("cross_run_artifact_references", 0),
        ),
        attempts=tuple(_attempt(f"run_{index:02d}") for index in range(1, 9)),
    ),
    GatePlan(
        "DF-KILL",
        "real_runtime",
        "SIGKILL target A Dwarf_Fortress after step 2 while peer B continues",
        (
            ("target_terminal", "runtime_df_killed"),
            ("target_oom_killed", False),
            ("detection_seconds_lte", 10),
            ("cleanup_seconds_lte", 30),
            ("peer_minimum_step", 5),
            ("peer_reconnected", False),
        ),
        attempts=(_attempt("target"), _attempt("peer")),
    ),
    GatePlan(
        "HARNESS-KILL",
        "real_runtime",
        "SIGKILL target A harness after step 2 while leaving descendants",
        (
            ("target_terminal", "harness_killed"),
            ("target_process_group_reaped", True),
            ("target_runtime_listener_and_lease_removed", True),
            ("peer_minimum_step", 5),
        ),
        attempts=(_attempt("target"), _attempt("peer")),
    ),
    GatePlan(
        "OOM",
        "isolated_x86_linux",
        "run target A at 256 MiB while peer B retains the normal cap",
        (
            ("target_terminal", "runtime_oom"),
            ("cgroup_memory_events_proves_oom", True),
            ("target_memory_events_local_oom_kill_delta_gte", 1),
            ("exit_137_alone_is_sufficient", False),
            ("peer_healthy", True),
            ("host_oom_counter_delta", 0),
            (
                "host_oom_counter_definition",
                (
                    "global_proc_vmstat_oom_kill_delta minus "
                    "target_memory_events_local_oom_kill_delta"
                ),
            ),
        ),
        attempts=(_attempt("target"), _attempt("peer")),
    ),
    GatePlan(
        "ENOSPC",
        "isolated_x86_linux",
        "fill only target A private 16 MiB workspace tmpfs at the step-2 barrier",
        (
            ("target_terminal", "workspace_enospc"),
            ("errno", 28),
            ("control_plane_journal_survives", True),
            ("peer_continues", True),
            ("maximum_fault_bytes", 16_777_216),
        ),
        attempts=(_attempt("target"), _attempt("peer")),
    ),
    GatePlan(
        "CONTAINER-RESTART",
        "real_runtime",
        "docker restart target A at step 2",
        (
            ("target_terminal", "runtime_container_restarted"),
            ("silent_reconnect", False),
            ("peer_continues", True),
        ),
        attempts=(_attempt("target"), _attempt("peer")),
    ),
    GatePlan(
        "DAEMON-RESTART",
        "isolated_x86_linux_host_controller",
        "restart Docker from outside Docker while two runs are active",
        (
            ("affected_terminal", "docker_daemon_restarted"),
            ("silent_continuation", False),
            ("reconciliation_seconds_lte", 120),
            ("supervisor_remains_operational", True),
        ),
        attempts=(_attempt("target"), _attempt("peer")),
    ),
    GatePlan(
        "ORPHAN-1",
        "local_and_real_runtime",
        "reconcile managed orphans beside an unlabeled foreign canary",
        (
            ("managed_orphans_removed", True),
            ("foreign_canary_untouched", True),
            ("second_reconciliation_noop", True),
        ),
        attempts=(_attempt("managed_orphan"),),
        local_credit_scope=LocalCreditScope.LOCAL_SUBPROCEDURE,
    ),
    GatePlan(
        "ORPHAN-2",
        "isolated_x86_linux",
        "SIGKILL supervisor during a run, then restart from durable journal",
        (
            ("run_resumed", False),
            ("target_terminal", "supervisor_lost"),
            ("all_managed_resources_reaped", True),
        ),
        attempts=(_attempt("target"),),
    ),
    GatePlan(
        "PROVIDER-ENV",
        "local",
        "launch from poisoned parent environment and poisoned temporary dotenv",
        (
            ("child_environment_equals_allowlist", True),
            ("poisoned_values_present", False),
            ("dotenv_disabled", True),
            ("agent", "dfhack-governed-scripted"),
        ),
        local_credit_scope=LocalCreditScope.COMPLETE_LOCAL_GATE,
    ),
    GatePlan(
        "PROVIDER-NET",
        "isolated_x86_linux",
        "constrain harness network to assigned loopback RPC and capture connects",
        (
            ("dns_connections", 0),
            ("port_443_connections", 0),
            ("poison_sink_connections", 0),
            ("only_assigned_dfhack_connection", True),
            ("provider_calls", 0),
            ("provider_cost_usd", 0),
        ),
        attempts=(_attempt("target"),),
    ),
    GatePlan(
        "CAP-FAKE",
        "local",
        "emit one synthetic provider usage event that exactly reaches a positive "
        "configured test cap, leaving zero remaining budget before a second dispatch",
        (
            ("terminal", "budget_cap_exceeded"),
            ("second_fake_call", False),
            ("missing_cap_or_pin_rejected", True),
            ("real_provider_or_network_used", False),
        ),
        local_credit_scope=LocalCreditScope.COMPLETE_LOCAL_GATE,
    ),
    GatePlan(
        "CLEANUP",
        "every_case",
        "run scoped cleanup twice after every gate and after the final batch",
        (
            ("exact_batch_containers_processes_listeners_leases_mounts_tempdirs", 0),
            ("retained_evidence_allowed", True),
            ("foreign_canary_untouched", True),
        ),
        derived=True,
    ),
)

_SUBSTANTIVE_GATES = tuple(gate for gate in FROZEN_GATE_PLAN if not gate.derived)
_GATE_BY_ID = MappingProxyType({gate.gate_id: gate for gate in FROZEN_GATE_PLAN})
_LOCAL_CREDIT_BOUNDARIES = MappingProxyType(
    {
        gate.gate_id: gate.local_credit_scope
        for gate in FROZEN_GATE_PLAN
        if gate.local_credit_scope is not None
    }
)


def _plan_payload() -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
        "max_real_runtime_attempts": MAX_REAL_RUNTIME_ATTEMPTS,
        "required_cleanup_passes": REQUIRED_CLEANUP_PASSES,
        "gates": [
            gate.payload(gate_index=index)
            for index, gate in enumerate(FROZEN_GATE_PLAN, start=1)
        ],
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


# The literal makes an accidental source edit fail at import rather than
# silently changing a live batch plan.
FROZEN_PLAN_SHA256 = "d37cad75e7e052ed4463353f0b3138f64143ca1e50337e6ad5eb29cbbca47194"
if _payload_sha256(_plan_payload()) != FROZEN_PLAN_SHA256:
    raise RuntimeError("frozen M1b live-acceptance plan digest differs")


def _assert_frozen_plan() -> None:
    if _payload_sha256(_plan_payload()) != FROZEN_PLAN_SHA256:
        raise LiveAcceptanceContractError("frozen plan digest differs")
    if len(FROZEN_GATE_PLAN) != 16:
        raise LiveAcceptanceContractError("frozen plan must contain exactly 16 gates")
    gate_ids = tuple(gate.gate_id for gate in FROZEN_GATE_PLAN)
    if len(set(gate_ids)) != len(gate_ids):
        raise LiveAcceptanceContractError("frozen plan contains duplicate gate IDs")
    runtime_attempts = sum(gate.real_runtime_attempts for gate in FROZEN_GATE_PLAN)
    if runtime_attempts != MAX_REAL_RUNTIME_ATTEMPTS:
        raise LiveAcceptanceContractError(
            "frozen plan does not contain exactly 26 real-runtime slots"
        )
    non_runtime = [
        (gate.gate_id, attempt.role)
        for gate in FROZEN_GATE_PLAN
        for attempt in gate.attempts
        if attempt.kind is AttemptKind.NON_RUNTIME_CONFLICT
    ]
    if non_runtime != [("PORT-2", "contender_b")]:
        raise LiveAcceptanceContractError(
            "PORT-2 contender must be the only non-runtime attempt"
        )


_assert_frozen_plan()


@dataclass(frozen=True)
class EvidenceReference:
    """Public content address for one immutable evidence file."""

    path: str
    sha256: str
    size_bytes: int

    def payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class SourceManifestLock:
    """Exact prebuilt source-manifest input for one batch."""

    path: Path
    sha256: str

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not path.is_absolute() or "\0" in str(path):
            raise ValueError("source manifest path must be absolute and NUL-free")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise ValueError("source manifest digest must be lowercase SHA-256")
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class LocalCreditImport:
    """Explicit prior evidence with a frozen, non-promotable credit scope."""

    gate_id: str
    scope: LocalCreditScope
    criteria_passed: tuple[str, ...]
    evidence_paths: tuple[Path, ...]

    def __post_init__(self) -> None:
        if self.gate_id not in _GATE_BY_ID:
            raise ValueError("local credit gate is not in the frozen plan")
        if not isinstance(self.scope, LocalCreditScope):
            raise TypeError("local credit scope must be a LocalCreditScope")
        criteria = tuple(self.criteria_passed)
        paths = tuple(Path(path) for path in self.evidence_paths)
        if not paths:
            raise ValueError("local credit requires at least one evidence path")
        object.__setattr__(self, "criteria_passed", criteria)
        object.__setattr__(self, "evidence_paths", paths)


@dataclass(frozen=True)
class GateExecutionResult:
    """Narrow, secret-free result returned by one injected gate adapter."""

    gate_id: str
    criteria_passed: tuple[str, ...]
    evidence_paths: tuple[Path, ...]
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.gate_id, str):
            raise TypeError("gate result ID must be a string")
        criteria = tuple(self.criteria_passed)
        paths = tuple(Path(path) for path in self.evidence_paths)
        if self.failure_code is not None and (
            not isinstance(self.failure_code, str)
            or not _CODE_RE.fullmatch(self.failure_code)
        ):
            raise ValueError("gate failure code must be a bounded lowercase code")
        object.__setattr__(self, "criteria_passed", criteria)
        object.__setattr__(self, "evidence_paths", paths)


@dataclass(frozen=True)
class CleanupPassResult:
    """One independently evidenced cleanup/audit pass."""

    scope: str
    gate_id: str | None
    pass_index: int
    criteria_passed: tuple[str, ...]
    evidence_paths: tuple[Path, ...]
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in {"gate", "batch"}:
            raise ValueError("cleanup scope must be gate or batch")
        if self.scope == "gate" and self.gate_id not in {
            gate.gate_id for gate in _SUBSTANTIVE_GATES
        }:
            raise ValueError("gate cleanup requires a substantive frozen gate")
        if self.scope == "batch" and self.gate_id is not None:
            raise ValueError("batch cleanup cannot name a gate")
        if self.pass_index not in {1, 2}:
            raise ValueError("cleanup pass index must be 1 or 2")
        criteria = tuple(self.criteria_passed)
        paths = tuple(Path(path) for path in self.evidence_paths)
        if self.failure_code is not None and (
            not isinstance(self.failure_code, str)
            or not _CODE_RE.fullmatch(self.failure_code)
        ):
            raise ValueError("cleanup failure code must be a bounded lowercase code")
        object.__setattr__(self, "criteria_passed", criteria)
        object.__setattr__(self, "evidence_paths", paths)


@dataclass(frozen=True)
class CleanupPassContext:
    """Exact cleanup invocation.  The controller calls pass 1 and pass 2."""

    batch_id: str
    scope: str
    gate_id: str | None
    pass_index: int
    evidence_root: Path
    acceptance_sha256: str
    plan_sha256: str


@dataclass(frozen=True)
class GateExecutionContext:
    """Frozen gate request exposed to the injected host adapter."""

    batch_id: str
    gate_id: str
    gate_class: str
    procedure: str
    required_criteria: tuple[str, ...]
    attempts: tuple[AttemptPermit, ...]
    local_credit: Mapping[str, Any] | None
    privileged_commands: PrivilegedCommandExecutor
    evidence_root: Path
    acceptance_sha256: str
    plan_sha256: str


class LiveAcceptanceAdapter(Protocol):
    """Host boundary injected explicitly by a private acceptance runner."""

    def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult: ...

    def cleanup_pass(self, context: CleanupPassContext) -> CleanupPassResult: ...


@dataclass(frozen=True)
class PrivilegedCommandResult:
    """Bounded result from one exact logical command executed by a host helper.

    ``logical_argv`` is the command requested by the nonroot acceptance adapter.
    The helper/sudo transport is intentionally not prescribed or serialized.
    Only hashes of captured output cross this boundary.
    """

    logical_argv: tuple[str, ...]
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    executor_identity_sha256: str
    shell: bool = False

    def __post_init__(self) -> None:
        argv = tuple(self.logical_argv)
        if not argv or any(
            not isinstance(item, str)
            or not item
            or "\0" in item
            or len(item.encode("utf-8")) > 4096
            for item in argv
        ):
            raise ValueError("logical privileged argv is invalid")
        if (
            isinstance(self.returncode, bool)
            or not isinstance(self.returncode, int)
            or not -(2**31) <= self.returncode < 2**31
        ):
            raise ValueError("privileged command return code is invalid")
        for name in (
            "stdout_sha256",
            "stderr_sha256",
            "executor_identity_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"{name} must be lowercase SHA-256")
        if self.shell is not False:
            raise ValueError("privileged command execution must never use a shell")
        object.__setattr__(self, "logical_argv", argv)


class PrivilegedCommandExecutor(Protocol):
    """Injected non-shell escalation seam for exact Linux host operations."""

    def execute(
        self,
        logical_argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> PrivilegedCommandResult: ...


class _BoundPrivilegedCommandExecutor:
    """Validate the injected privilege transport around every exact request."""

    def __init__(self, delegate: PrivilegedCommandExecutor) -> None:
        self._delegate = delegate

    def execute(
        self,
        logical_argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> PrivilegedCommandResult:
        argv = tuple(logical_argv)
        if not argv or any(
            not isinstance(item, str)
            or not item
            or "\0" in item
            or len(item.encode("utf-8")) > 4096
            for item in argv
        ):
            raise LiveAcceptanceProtocolError("logical privileged argv is invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 600
        ):
            raise LiveAcceptanceProtocolError(
                "privileged command timeout must be finite and bounded"
            )
        result = self._delegate.execute(argv, timeout_seconds=float(timeout_seconds))
        if not isinstance(result, PrivilegedCommandResult):
            raise LiveAcceptanceProtocolError(
                "privileged executor must return PrivilegedCommandResult"
            )
        if result.logical_argv != argv or result.shell is not False:
            raise LiveAcceptanceProtocolError(
                "privileged executor changed the logical command identity"
            )
        return result


@dataclass(frozen=True)
class LiveAcceptanceOutcome:
    batch_id: str
    decision: BatchDecisionValue
    real_runtime_attempts_started: int
    real_runtime_attempts_completed: int
    non_runtime_attempts_started: int
    non_runtime_attempts_completed: int
    gate_results_path: Path
    decision_path: Path
    evidence_manifest_path: Path
    seal_path: Path


class LiveAcceptanceAuthorization:
    """Opaque constructor capability; intentionally non-serializable."""

    __slots__ = (
        "_capability",
        "_consumed",
        "batch_id",
        "contract_path",
        "evidence_root",
    )

    def __init__(
        self,
        *,
        batch_id: str,
        evidence_root: Path,
        contract_path: Path,
        _sentinel: object,
    ) -> None:
        if _sentinel is not _AUTH_SENTINEL:
            raise LiveAcceptanceAuthorizationError(
                "live acceptance authorization requires the private factory"
            )
        self.batch_id = batch_id
        self.evidence_root = evidence_root
        self.contract_path = contract_path
        self._capability = secrets.token_bytes(32)
        self._consumed = False

    def __repr__(self) -> str:
        return (
            "LiveAcceptanceAuthorization(batch_id="
            f"{self.batch_id!r}, evidence_root={str(self.evidence_root)!r}, "
            "capability=<redacted>)"
        )

    def __reduce__(self) -> object:
        raise TypeError("live acceptance authorizations are non-serializable")

    def _consume(self) -> None:
        if self._consumed:
            raise LiveAcceptanceAuthorizationError(
                "live acceptance authorization is single-use"
            )
        if not isinstance(self._capability, bytes) or len(self._capability) != 32:
            raise LiveAcceptanceAuthorizationError(
                "live acceptance authorization is invalid"
            )
        self._consumed = True


def authorize_private_m1b_live_acceptance(
    *,
    test_mode: bool,
    batch_id: str,
    evidence_root: Path,
    contract_path: Path,
) -> LiveAcceptanceAuthorization:
    """Mint explicit constructor authority; ambient strings are never coerced."""

    if test_mode is not True:
        raise LiveAcceptanceAuthorizationError(
            "M1b live acceptance requires literal private test_mode=True"
        )
    if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
        raise LiveAcceptanceAuthorizationError("batch ID is invalid")
    root = Path(evidence_root)
    contract = Path(contract_path)
    if not root.is_absolute() or "\0" in str(root):
        raise LiveAcceptanceAuthorizationError(
            "evidence root must be absolute and NUL-free"
        )
    if not contract.is_absolute() or "\0" in str(contract):
        raise LiveAcceptanceAuthorizationError(
            "contract path must be absolute and NUL-free"
        )
    return LiveAcceptanceAuthorization(
        batch_id=batch_id,
        evidence_root=root,
        contract_path=contract,
        _sentinel=_AUTH_SENTINEL,
    )


class _AppendOnlyLedger:
    """Strict hash-chained JSONL ledger with file and directory fsync."""

    def __init__(self, path: Path, *, schema: str, batch_id: str) -> None:
        self.path = path
        self.schema = schema
        self.batch_id = batch_id
        self.lock_path = path.with_suffix(f"{path.suffix}.lock")

    def initialize_empty(self) -> None:
        """Durably materialize an empty ledger before another process reads it."""

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.path.lexists(self.path):
            if self.path.is_symlink() or not self.path.is_file():
                raise LiveAcceptanceEvidenceError(
                    "ledger must be a regular non-symlink"
                )
            self.records()
            return
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError:
            if self.path.is_symlink() or not self.path.is_file():
                raise LiveAcceptanceEvidenceError(
                    "ledger must be a regular non-symlink"
                )
            self.records()
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_directory(self.path.parent)

    def records(self) -> list[dict[str, Any]]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return []
        if self.path.is_symlink() or not self.path.is_file():
            raise LiveAcceptanceEvidenceError("ledger must be a regular non-symlink")
        lines = raw.splitlines()
        if len(lines) > _MAX_LEDGER_RECORDS:
            raise LiveAcceptanceEvidenceError("ledger exceeds its record cap")
        records: list[dict[str, Any]] = []
        previous = _ZERO_SHA256
        for sequence, line in enumerate(lines, start=1):
            if not line or len(line) > _MAX_LEDGER_RECORD_BYTES:
                raise LiveAcceptanceEvidenceError("ledger record size is invalid")
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LiveAcceptanceEvidenceError(
                    "ledger contains invalid JSON"
                ) from exc
            if not isinstance(record, dict):
                raise LiveAcceptanceEvidenceError("ledger record must be an object")
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
            if set(record) != expected_keys:
                raise LiveAcceptanceEvidenceError("ledger record fields differ")
            claimed = record.get("record_sha256")
            hash_input = dict(record)
            hash_input.pop("record_sha256", None)
            if (
                record.get("schema") != self.schema
                or record.get("batch_id") != self.batch_id
                or record.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
                or record.get("plan_sha256") != FROZEN_PLAN_SHA256
                or record.get("sequence") != sequence
                or record.get("previous_record_sha256") != previous
                or not isinstance(record.get("at"), str)
                or not _ID_RE.fullmatch(str(record.get("event")))
                or not isinstance(record.get("payload"), dict)
                or not isinstance(claimed, str)
                or not _SHA256_RE.fullmatch(claimed)
                or _payload_sha256(hash_input) != claimed
            ):
                raise LiveAcceptanceEvidenceError(
                    "ledger identity, sequence, plan, or hash chain differs"
                )
            records.append(record)
            previous = claimed
        return records

    def append(
        self,
        event: str,
        payload: Mapping[str, Any],
        *,
        at: str,
    ) -> dict[str, Any]:
        if not _ID_RE.fullmatch(event):
            raise ValueError("ledger event must be a bounded safe identifier")
        safe_payload = _json_safe(payload)
        if not isinstance(safe_payload, dict):
            raise TypeError("ledger payload must be a mapping")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            records = self.records()
            if len(records) >= _MAX_LEDGER_RECORDS:
                raise LiveAcceptanceEvidenceError("ledger reached its record cap")
            previous = str(records[-1]["record_sha256"]) if records else _ZERO_SHA256
            record = {
                "schema": self.schema,
                "batch_id": self.batch_id,
                "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
                "plan_sha256": FROZEN_PLAN_SHA256,
                "sequence": len(records) + 1,
                "previous_record_sha256": previous,
                "at": at,
                "event": event,
                "payload": safe_payload,
            }
            record["record_sha256"] = _payload_sha256(record)
            encoded = _canonical_bytes(record) + b"\n"
            if len(encoded) > _MAX_LEDGER_RECORD_BYTES:
                raise LiveAcceptanceEvidenceError("ledger record exceeds byte cap")
            fd = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short ledger append")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_directory(self.path.parent)
            return record
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


@dataclass
class _AttemptState:
    plan: dict[str, Any]
    identity_sha256: str | None = None
    authorization_identity_sha256: str | None = None
    outcome_code: str | None = None
    evidence: tuple[EvidenceReference, ...] = ()

    @property
    def started(self) -> bool:
        return self.identity_sha256 is not None

    @property
    def completed(self) -> bool:
        return self.outcome_code is not None


class AttemptPermit:
    """Single-use durable permit for one frozen attempt slot."""

    __slots__ = ("_controller", "_sentinel", "attempt_id", "gate_id", "kind", "role")

    def __init__(
        self,
        *,
        controller: LiveAcceptanceBatchController,
        gate_id: str,
        attempt_id: str,
        kind: AttemptKind,
        role: str,
        _sentinel: object,
    ) -> None:
        if _sentinel is not _PERMIT_SENTINEL:
            raise LiveAcceptanceAuthorizationError(
                "attempt permits can only be constructed by the batch controller"
            )
        self._controller = controller
        self._sentinel = _sentinel
        self.gate_id = gate_id
        self.attempt_id = attempt_id
        self.kind = kind
        self.role = role

    def __repr__(self) -> str:
        return (
            "AttemptPermit(gate_id="
            f"{self.gate_id!r}, attempt_id={self.attempt_id!r}, "
            f"kind={self.kind.value!r}, role={self.role!r})"
        )

    def __reduce__(self) -> object:
        raise TypeError("attempt permits are non-serializable")

    @property
    def started(self) -> bool:
        return self._controller._attempt_is_started(self.attempt_id)

    @property
    def completed(self) -> bool:
        return self._controller._attempt_is_completed(self.attempt_id)

    def start(self, *, identity_sha256: str) -> None:
        """Durably account the attempt immediately before its external action."""

        self._controller._start_attempt(self, identity_sha256=identity_sha256)

    def bind_private_authorization(self, *, authorization_identity_sha256: str) -> None:
        """Bind the ENOSPC target to the consumed in-memory service capability."""

        self._controller._bind_private_authorization(
            self,
            authorization_identity_sha256=authorization_identity_sha256,
        )

    def complete(
        self,
        *,
        outcome_code: str,
        evidence_paths: Sequence[Path],
    ) -> None:
        """Record one exact terminal/conflict outcome without interpreting it."""

        self._controller._complete_attempt(
            self,
            outcome_code=outcome_code,
            evidence_paths=tuple(Path(path) for path in evidence_paths),
        )


@dataclass
class _ReplayState:
    opened: bool
    finalized: bool
    final_payload: dict[str, Any] | None
    local_credits: dict[str, dict[str, Any]]
    gate_results: dict[str, dict[str, Any]]
    cleanup_started: set[tuple[str, str | None]]
    cleanup_passes: dict[tuple[str, str | None], dict[int, dict[str, Any]]]
    cleanup_completed: dict[tuple[str, str | None], dict[str, Any]]
    cleanup_gate_result: dict[str, Any] | None
    active_gate: str | None
    attempt_states: dict[str, _AttemptState]
    attempt_head_sha256: str


class LiveAcceptanceBatchController:
    """Run or validate one frozen M1b live-acceptance batch."""

    def __init__(
        self,
        *,
        authorization: LiveAcceptanceAuthorization,
        adapter: LiveAcceptanceAdapter,
        privileged_commands: PrivilegedCommandExecutor,
        source_manifest: SourceManifestLock,
        local_credits: Sequence[LocalCreditImport],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(authorization, LiveAcceptanceAuthorization):
            raise LiveAcceptanceAuthorizationError(
                "an opaque private live-acceptance authorization is required"
            )
        authorization._consume()
        if not callable(getattr(adapter, "execute_gate", None)) or not callable(
            getattr(adapter, "cleanup_pass", None)
        ):
            raise TypeError("adapter must define execute_gate() and cleanup_pass()")
        if not callable(getattr(privileged_commands, "execute", None)):
            raise TypeError("privileged_commands must define execute()")
        if not isinstance(source_manifest, SourceManifestLock):
            raise TypeError("source_manifest must be a SourceManifestLock")
        self.batch_id = authorization.batch_id
        if authorization.evidence_root.is_symlink():
            raise LiveAcceptanceEvidenceError("evidence root cannot be a symlink")
        if authorization.contract_path.is_symlink():
            raise LiveAcceptanceContractError("acceptance contract cannot be a symlink")
        self.evidence_root = authorization.evidence_root.resolve(strict=False)
        self.contract_path = authorization.contract_path.resolve(strict=False)
        self.adapter = adapter
        self.privileged_commands = _BoundPrivilegedCommandExecutor(privileged_commands)
        self.source_manifest = source_manifest
        self.local_credits = tuple(local_credits)
        self._now = now or (lambda: datetime.now(UTC))
        self._thread_lock = threading.RLock()
        # ``run()`` deliberately holds ``_thread_lock`` while one batch is
        # active. Real host adapters start supervised runs in worker threads,
        # and those workers must be able to durably start/complete their
        # attempt permits while the batch thread waits for them. Keep permit
        # state on a separate lock so cross-thread accounting cannot deadlock
        # behind the batch run lock.
        self._attempt_lock = threading.RLock()
        self._active_gate: str | None = None
        self._attempt_states: dict[str, _AttemptState] = {}

        self.control_root = self.evidence_root / "control"
        self.batch_ledger_path = self.control_root / "batch-ledger.jsonl"
        self.attempt_ledger_path = self.control_root / "attempt-ledger.jsonl"
        self.gate_results_path = self.control_root / "gate-results.json"
        self.decision_path = self.control_root / "decision.json"
        self.evidence_manifest_path = self.control_root / "evidence-manifest.json"
        self.seal_path = self.control_root / "seal.json"
        self._run_lock_path = self.control_root / "live-acceptance.lock"
        self._batch_ledger = _AppendOnlyLedger(
            self.batch_ledger_path,
            schema=BATCH_LEDGER_SCHEMA,
            batch_id=self.batch_id,
        )
        self._attempt_ledger = _AppendOnlyLedger(
            self.attempt_ledger_path,
            schema=ATTEMPT_LEDGER_SCHEMA,
            batch_id=self.batch_id,
        )

        _assert_frozen_plan()
        self._validate_root()
        self._validate_acceptance_contract()
        self._source_reference = self._reference_file(self.source_manifest.path)
        if self._source_reference.sha256 != self.source_manifest.sha256:
            raise LiveAcceptanceEvidenceError("source manifest digest differs")
        self._validated_local_credits = self._validate_local_credits()

    def run(self) -> LiveAcceptanceOutcome:
        """Execute remaining safe boundaries or validate an already sealed batch."""

        if os.path.lexists(self.control_root):
            if self.control_root.is_symlink() or not self.control_root.is_dir():
                raise LiveAcceptanceEvidenceError(
                    "control root must be a regular directory beneath the packet"
                )
        else:
            self.control_root.mkdir(parents=False, mode=0o700)
        if self.control_root.resolve(strict=True).parent != self.evidence_root:
            raise LiveAcceptanceEvidenceError("control root escaped the packet")
        _fsync_directory(self.evidence_root)
        lock_fd = os.open(self._run_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            with self._thread_lock:
                self._batch_ledger.initialize_empty()
                self._attempt_ledger.initialize_empty()
                state = self._replay()
                if state.finalized:
                    expected_gate_results = self._gate_results_payload(state)
                    expected_decision = self._decision_payload(
                        state, expected_gate_results
                    )
                    return self._write_and_validate_seal(
                        state,
                        gate_results_payload=expected_gate_results,
                        decision_payload=expected_decision,
                    )
                if not state.opened:
                    self._append_batch("batch_opened", self._batch_open_payload())
                    state = self._replay()
                self._ensure_local_credit_events(state)
                state = self._replay()

                stop_after_cleanup_failure = False
                for gate in _SUBSTANTIVE_GATES:
                    state = self._replay()
                    if gate.gate_id in state.gate_results:
                        cleanup = self._ensure_cleanup(
                            state,
                            scope="gate",
                            gate_id=gate.gate_id,
                        )
                        if cleanup["status"] != GateStatus.PASS.value:
                            stop_after_cleanup_failure = True
                            break
                        continue
                    if state.active_gate is not None:
                        raise LiveAcceptanceResumeError(
                            "interrupted gate execution cannot be inferred or replayed"
                        )
                    gate_result = self._execute_one_gate(gate)
                    self._append_batch("gate_completed", gate_result)
                    state = self._replay()
                    cleanup = self._ensure_cleanup(
                        state,
                        scope="gate",
                        gate_id=gate.gate_id,
                    )
                    if cleanup["status"] != GateStatus.PASS.value:
                        stop_after_cleanup_failure = True
                        break

                state = self._replay()
                final_cleanup = self._ensure_cleanup(
                    state,
                    scope="batch",
                    gate_id=None,
                )
                state = self._replay()
                if state.cleanup_gate_result is None:
                    cleanup_gate = self._derive_cleanup_gate_result(
                        state,
                        final_cleanup=final_cleanup,
                        stopped_early=stop_after_cleanup_failure,
                    )
                    self._append_batch("cleanup_gate_completed", cleanup_gate)
                state = self._replay()
                gate_results_payload = self._gate_results_payload(state)
                decision_payload = self._decision_payload(state, gate_results_payload)
                final_payload = {
                    "decision": decision_payload["decision"],
                    "gate_results_sha256": _payload_sha256(gate_results_payload),
                    "decision_sha256": _payload_sha256(decision_payload),
                    "real_runtime_attempts_started": decision_payload[
                        "real_runtime_attempts_started"
                    ],
                    "real_runtime_attempts_completed": decision_payload[
                        "real_runtime_attempts_completed"
                    ],
                    "non_runtime_attempts_started": decision_payload[
                        "non_runtime_attempts_started"
                    ],
                    "non_runtime_attempts_completed": decision_payload[
                        "non_runtime_attempts_completed"
                    ],
                }
                self._append_batch("batch_finalized", final_payload)
                state = self._replay()
                return self._write_and_validate_seal(
                    state,
                    gate_results_payload=gate_results_payload,
                    decision_payload=decision_payload,
                )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _execute_one_gate(self, gate: GatePlan) -> dict[str, Any]:
        gate_index = FROZEN_GATE_PLAN.index(gate) + 1
        attempts = tuple(
            AttemptPermit(
                controller=self,
                gate_id=gate.gate_id,
                attempt_id=attempt.payload(
                    gate_index=gate_index,
                    slot_index=slot_index,
                )["attempt_id"],
                kind=attempt.kind,
                role=attempt.role,
                _sentinel=_PERMIT_SENTINEL,
            )
            for slot_index, attempt in enumerate(gate.attempts, start=1)
        )
        local_credit = self._validated_local_credits.get(gate.gate_id)
        self._append_batch(
            "gate_started",
            {
                "gate": gate.payload(gate_index=gate_index),
                "attempt_ledger_head_sha256": self._ledger_head(self._attempt_ledger),
            },
        )
        self._active_gate = gate.gate_id
        try:
            if gate.local_credit_scope is LocalCreditScope.COMPLETE_LOCAL_GATE:
                if local_credit is None:
                    raise LiveAcceptanceEvidenceError(
                        "complete local gate lacks its exact imported credit"
                    )
                return self._canonical_gate_result(
                    gate,
                    status=GateStatus.PASS_LOCAL,
                    criteria_passed=gate.criteria,
                    evidence=tuple(local_credit["evidence"]),
                    failure_code=None,
                    local_credit=local_credit,
                )
            context = GateExecutionContext(
                batch_id=self.batch_id,
                gate_id=gate.gate_id,
                gate_class=gate.gate_class,
                procedure=gate.procedure,
                required_criteria=gate.criteria,
                attempts=attempts,
                local_credit=(
                    MappingProxyType(dict(local_credit))
                    if local_credit is not None
                    else None
                ),
                privileged_commands=self.privileged_commands,
                evidence_root=self.evidence_root,
                acceptance_sha256=FROZEN_ACCEPTANCE_SHA256,
                plan_sha256=FROZEN_PLAN_SHA256,
            )
            try:
                raw_result = self.adapter.execute_gate(context)
                result = self._validate_gate_adapter_result(gate, raw_result)
            except Exception as exc:  # noqa: BLE001 - record type only, never message
                result = {
                    "status": GateStatus.FAIL,
                    "criteria_passed": (),
                    "evidence": (),
                    "failure_code": _exception_code("adapter", exc),
                }

            attempt_summary = self._gate_attempt_summary(gate)
            all_attempts_complete = (
                attempt_summary["planned"]
                == attempt_summary["started"]
                == attempt_summary["completed"]
            )
            enospc_bound = True
            authorization_identity_sha256: str | None = None
            if gate.gate_id == "ENOSPC":
                target_id = next(
                    permit.attempt_id for permit in attempts if permit.role == "target"
                )
                target_state = self._attempt_states[target_id]
                authorization_identity_sha256 = (
                    target_state.authorization_identity_sha256
                )
                enospc_bound = authorization_identity_sha256 is not None
            criteria_exact = tuple(result["criteria_passed"]) == gate.criteria
            status = result["status"]
            failure_code = result["failure_code"]
            if status is GateStatus.PASS and (
                not all_attempts_complete or not enospc_bound or not criteria_exact
            ):
                status = GateStatus.FAIL
                failure_code = (
                    "enospc_authorization_unbound"
                    if not enospc_bound
                    else "attempt_protocol_incomplete"
                )
            if status is GateStatus.FAIL and failure_code is None:
                failure_code = "acceptance_criteria_not_met"
            return self._canonical_gate_result(
                gate,
                status=status,
                criteria_passed=tuple(result["criteria_passed"]),
                evidence=tuple(result["evidence"]),
                failure_code=failure_code,
                local_credit=local_credit,
                attempt_summary=attempt_summary,
                authorization_identity_sha256=authorization_identity_sha256,
            )
        finally:
            self._active_gate = None

    def _validate_gate_adapter_result(
        self,
        gate: GatePlan,
        result: GateExecutionResult,
    ) -> dict[str, Any]:
        if not isinstance(result, GateExecutionResult):
            raise LiveAcceptanceProtocolError(
                "gate adapter must return GateExecutionResult"
            )
        if result.gate_id != gate.gate_id:
            raise LiveAcceptanceProtocolError("gate adapter result identity differs")
        criteria = _validate_criteria_subset(
            result.criteria_passed,
            gate.criteria,
            label="gate adapter",
        )
        evidence = self._reference_files(result.evidence_paths)
        passed = criteria == gate.criteria and result.failure_code is None
        if passed and not evidence:
            raise LiveAcceptanceProtocolError("passing gate requires evidence")
        if not passed and result.failure_code is None:
            raise LiveAcceptanceProtocolError("failing gate requires a failure code")
        if passed and result.failure_code is not None:
            raise LiveAcceptanceProtocolError(
                "passing criteria cannot carry a failure code"
            )
        return {
            "status": GateStatus.PASS if passed else GateStatus.FAIL,
            "criteria_passed": criteria,
            "evidence": evidence,
            "failure_code": result.failure_code,
        }

    def _ensure_cleanup(
        self,
        state: _ReplayState,
        *,
        scope: str,
        gate_id: str | None,
    ) -> dict[str, Any]:
        key = (scope, gate_id)
        existing = state.cleanup_completed.get(key)
        if existing is not None:
            return existing
        if key not in state.cleanup_started:
            self._append_batch(
                "cleanup_started",
                {
                    "scope": scope,
                    "gate_id": gate_id,
                    "required_passes": REQUIRED_CLEANUP_PASSES,
                },
            )
            state = self._replay()
        completed = dict(state.cleanup_passes.get(key, {}))
        for pass_index in range(1, REQUIRED_CLEANUP_PASSES + 1):
            if pass_index in completed:
                continue
            context = CleanupPassContext(
                batch_id=self.batch_id,
                scope=scope,
                gate_id=gate_id,
                pass_index=pass_index,
                evidence_root=self.evidence_root,
                acceptance_sha256=FROZEN_ACCEPTANCE_SHA256,
                plan_sha256=FROZEN_PLAN_SHA256,
            )
            try:
                raw = self.adapter.cleanup_pass(context)
                payload = self._validate_cleanup_result(context, raw)
            except Exception as exc:  # noqa: BLE001 - never persist exception text
                payload = {
                    "scope": scope,
                    "gate_id": gate_id,
                    "pass_index": pass_index,
                    "status": GateStatus.FAIL.value,
                    "criteria_passed": [],
                    "failure_code": _exception_code("cleanup", exc),
                    "evidence": [],
                }
            self._append_batch("cleanup_pass_completed", payload)
            completed[pass_index] = payload
        ordered = [completed[index] for index in (1, 2)]
        passed = all(item["status"] == GateStatus.PASS.value for item in ordered)
        summary = {
            "scope": scope,
            "gate_id": gate_id,
            "status": GateStatus.PASS.value if passed else GateStatus.FAIL.value,
            "required_passes": REQUIRED_CLEANUP_PASSES,
            "passes": ordered,
        }
        self._append_batch("cleanup_completed", summary)
        return summary

    def _validate_cleanup_result(
        self,
        context: CleanupPassContext,
        result: CleanupPassResult,
    ) -> dict[str, Any]:
        if not isinstance(result, CleanupPassResult):
            raise LiveAcceptanceProtocolError(
                "cleanup adapter must return CleanupPassResult"
            )
        if (
            result.scope != context.scope
            or result.gate_id != context.gate_id
            or result.pass_index != context.pass_index
        ):
            raise LiveAcceptanceProtocolError("cleanup result identity differs")
        cleanup_gate = _GATE_BY_ID["CLEANUP"]
        criteria = _validate_criteria_subset(
            result.criteria_passed,
            cleanup_gate.criteria,
            label="cleanup adapter",
        )
        evidence = self._reference_files(result.evidence_paths)
        passed = criteria == cleanup_gate.criteria and result.failure_code is None
        if passed and not evidence:
            raise LiveAcceptanceProtocolError("passing cleanup requires evidence")
        if not passed and result.failure_code is None:
            raise LiveAcceptanceProtocolError("failing cleanup requires a failure code")
        if passed and result.failure_code is not None:
            raise LiveAcceptanceProtocolError(
                "passing cleanup cannot carry a failure code"
            )
        return {
            "scope": context.scope,
            "gate_id": context.gate_id,
            "pass_index": context.pass_index,
            "status": GateStatus.PASS.value if passed else GateStatus.FAIL.value,
            "criteria_passed": list(criteria),
            "failure_code": result.failure_code,
            "evidence": [reference.payload() for reference in evidence],
        }

    def _derive_cleanup_gate_result(
        self,
        state: _ReplayState,
        *,
        final_cleanup: Mapping[str, Any],
        stopped_early: bool,
    ) -> dict[str, Any]:
        expected_keys = {("gate", gate.gate_id) for gate in _SUBSTANTIVE_GATES}
        all_gate_cleanups = all(
            state.cleanup_completed.get(key, {}).get("status") == GateStatus.PASS.value
            for key in expected_keys
        )
        passed = (
            not stopped_early
            and all_gate_cleanups
            and final_cleanup.get("status") == GateStatus.PASS.value
        )
        cleanup_gate = _GATE_BY_ID["CLEANUP"]
        evidence: dict[tuple[str, str, int], dict[str, Any]] = {}
        for cleanup in (*state.cleanup_completed.values(), dict(final_cleanup)):
            for pass_record in cleanup.get("passes", []):
                for reference in pass_record.get("evidence", []):
                    key = (
                        str(reference["path"]),
                        str(reference["sha256"]),
                        int(reference["size_bytes"]),
                    )
                    evidence[key] = dict(reference)
        return self._canonical_gate_result(
            cleanup_gate,
            status=GateStatus.PASS if passed else GateStatus.FAIL,
            criteria_passed=cleanup_gate.criteria if passed else (),
            evidence=tuple(
                EvidenceReference(path=path, sha256=digest, size_bytes=size)
                for path, digest, size in sorted(evidence)
            ),
            failure_code=None if passed else "cleanup_matrix_incomplete",
            local_credit=None,
        )

    def _canonical_gate_result(
        self,
        gate: GatePlan,
        *,
        status: GateStatus,
        criteria_passed: Sequence[str],
        evidence: Sequence[EvidenceReference | Mapping[str, Any]],
        failure_code: str | None,
        local_credit: Mapping[str, Any] | None,
        attempt_summary: Mapping[str, Any] | None = None,
        authorization_identity_sha256: str | None = None,
    ) -> dict[str, Any]:
        gate_index = FROZEN_GATE_PLAN.index(gate) + 1
        evidence_payload = [
            item.payload() if isinstance(item, EvidenceReference) else dict(item)
            for item in evidence
        ]
        return {
            "gate": gate.payload(gate_index=gate_index),
            "status": status.value,
            "criteria_passed": list(criteria_passed),
            "failure_code": failure_code,
            "evidence": evidence_payload,
            "local_credit": dict(local_credit) if local_credit is not None else None,
            "attempts": dict(attempt_summary or self._empty_attempt_summary(gate)),
            "authorization_identity_sha256": authorization_identity_sha256,
            "attempt_ledger_head_sha256": self._ledger_head(self._attempt_ledger),
        }

    def _empty_attempt_summary(self, gate: GatePlan) -> dict[str, Any]:
        return {
            "planned": len(gate.attempts),
            "started": 0,
            "completed": 0,
            "real_runtime_started": 0,
            "real_runtime_completed": 0,
            "non_runtime_started": 0,
            "non_runtime_completed": 0,
        }

    def _gate_attempt_summary(self, gate: GatePlan) -> dict[str, Any]:
        gate_index = FROZEN_GATE_PLAN.index(gate) + 1
        states = []
        for slot_index, attempt in enumerate(gate.attempts, start=1):
            attempt_id = attempt.payload(
                gate_index=gate_index,
                slot_index=slot_index,
            )["attempt_id"]
            states.append(self._attempt_states[attempt_id])
        return {
            "planned": len(states),
            "started": sum(state.started for state in states),
            "completed": sum(state.completed for state in states),
            "real_runtime_started": sum(
                state.started and state.plan["kind"] == AttemptKind.REAL_RUNTIME.value
                for state in states
            ),
            "real_runtime_completed": sum(
                state.completed and state.plan["kind"] == AttemptKind.REAL_RUNTIME.value
                for state in states
            ),
            "non_runtime_started": sum(
                state.started
                and state.plan["kind"] == AttemptKind.NON_RUNTIME_CONFLICT.value
                for state in states
            ),
            "non_runtime_completed": sum(
                state.completed
                and state.plan["kind"] == AttemptKind.NON_RUNTIME_CONFLICT.value
                for state in states
            ),
        }

    def _start_attempt(
        self,
        permit: AttemptPermit,
        *,
        identity_sha256: str,
    ) -> None:
        with self._attempt_lock:
            self._validate_live_permit(permit)
            if not isinstance(identity_sha256, str) or not _SHA256_RE.fullmatch(
                identity_sha256
            ):
                raise LiveAcceptanceProtocolError(
                    "attempt identity must be lowercase SHA-256"
                )
            state = self._attempt_states[permit.attempt_id]
            if state.started:
                raise LiveAcceptanceProtocolError("attempt permit is single-use")
            gate = _GATE_BY_ID[permit.gate_id]
            gate_index = FROZEN_GATE_PLAN.index(gate) + 1
            ordered_ids = [
                attempt.payload(gate_index=gate_index, slot_index=index)["attempt_id"]
                for index, attempt in enumerate(gate.attempts, start=1)
            ]
            position = ordered_ids.index(permit.attempt_id)
            if any(
                not self._attempt_states[item].started
                for item in ordered_ids[:position]
            ):
                raise LiveAcceptanceProtocolError(
                    "attempt slots must start in frozen order"
                )
            if permit.kind is AttemptKind.REAL_RUNTIME:
                total = sum(
                    attempt_state.started
                    and attempt_state.plan["kind"] == AttemptKind.REAL_RUNTIME.value
                    for attempt_state in self._attempt_states.values()
                )
                if total >= MAX_REAL_RUNTIME_ATTEMPTS:
                    raise LiveAcceptanceProtocolError(
                        "real-runtime attempt ceiling is exhausted"
                    )
            payload = {
                "gate_id": permit.gate_id,
                "attempt_id": permit.attempt_id,
                "kind": permit.kind.value,
                "role": permit.role,
                "identity_sha256": identity_sha256,
                "batch_ledger_head_sha256": self._ledger_head(self._batch_ledger),
            }
            self._append_attempt("attempt_started", payload)
            state.identity_sha256 = identity_sha256

    def _bind_private_authorization(
        self,
        permit: AttemptPermit,
        *,
        authorization_identity_sha256: str,
    ) -> None:
        with self._attempt_lock:
            self._validate_live_permit(permit)
            state = self._attempt_states[permit.attempt_id]
            if permit.gate_id != "ENOSPC" or permit.role != "target":
                raise LiveAcceptanceProtocolError(
                    "private authorization binding is ENOSPC-target-only"
                )
            if not state.started or state.completed:
                raise LiveAcceptanceProtocolError(
                    "ENOSPC authorization must bind a live incomplete attempt"
                )
            if state.authorization_identity_sha256 is not None:
                raise LiveAcceptanceProtocolError(
                    "ENOSPC authorization binding is single-use"
                )
            if not isinstance(
                authorization_identity_sha256, str
            ) or not _SHA256_RE.fullmatch(authorization_identity_sha256):
                raise LiveAcceptanceProtocolError(
                    "authorization identity must be lowercase SHA-256"
                )
            self._append_attempt(
                "private_authorization_bound",
                {
                    "gate_id": permit.gate_id,
                    "attempt_id": permit.attempt_id,
                    "authorization_identity_sha256": authorization_identity_sha256,
                },
            )
            state.authorization_identity_sha256 = authorization_identity_sha256

    def _complete_attempt(
        self,
        permit: AttemptPermit,
        *,
        outcome_code: str,
        evidence_paths: tuple[Path, ...],
    ) -> None:
        with self._attempt_lock:
            self._validate_live_permit(permit)
            state = self._attempt_states[permit.attempt_id]
            if not state.started:
                raise LiveAcceptanceProtocolError(
                    "attempt completion requires a durable start"
                )
            if state.completed:
                raise LiveAcceptanceProtocolError("attempt completion is single-use")
            if not isinstance(outcome_code, str) or not _CODE_RE.fullmatch(
                outcome_code
            ):
                raise LiveAcceptanceProtocolError(
                    "attempt outcome must be a bounded lowercase code"
                )
            if (
                permit.gate_id == "ENOSPC"
                and permit.role == "target"
                and state.authorization_identity_sha256 is None
            ):
                raise LiveAcceptanceProtocolError(
                    "ENOSPC target completion requires authorization binding"
                )
            evidence = self._reference_files(evidence_paths)
            if not evidence:
                raise LiveAcceptanceProtocolError(
                    "attempt completion requires immutable evidence"
                )
            self._append_attempt(
                "attempt_completed",
                {
                    "gate_id": permit.gate_id,
                    "attempt_id": permit.attempt_id,
                    "outcome_code": outcome_code,
                    "evidence": [reference.payload() for reference in evidence],
                },
            )
            state.outcome_code = outcome_code
            state.evidence = evidence

    def _validate_live_permit(self, permit: AttemptPermit) -> None:
        if (
            not isinstance(permit, AttemptPermit)
            or permit._sentinel is not _PERMIT_SENTINEL
            or permit._controller is not self
            or permit.gate_id != self._active_gate
            or permit.attempt_id not in self._attempt_states
        ):
            raise LiveAcceptanceAuthorizationError(
                "attempt permit is not active for this controller and gate"
            )

    def _attempt_is_started(self, attempt_id: str) -> bool:
        with self._attempt_lock:
            state = self._attempt_states.get(attempt_id)
            return bool(state is not None and state.started)

    def _attempt_is_completed(self, attempt_id: str) -> bool:
        with self._attempt_lock:
            state = self._attempt_states.get(attempt_id)
            return bool(state is not None and state.completed)

    def _validate_root(self) -> None:
        if not self.evidence_root.is_absolute():
            raise LiveAcceptanceEvidenceError("evidence root must be absolute")
        if not self.evidence_root.exists() or not self.evidence_root.is_dir():
            raise LiveAcceptanceEvidenceError(
                "evidence root must be a pre-created directory"
            )
        if self.evidence_root.is_symlink():
            raise LiveAcceptanceEvidenceError("evidence root cannot be a symlink")
        if self.evidence_root == Path(self.evidence_root.anchor):
            raise LiveAcceptanceEvidenceError(
                "evidence root cannot be a filesystem root"
            )

    def _validate_acceptance_contract(self) -> None:
        if (
            not self.contract_path.is_absolute()
            or not self.contract_path.is_file()
            or self.contract_path.is_symlink()
        ):
            raise LiveAcceptanceContractError(
                "acceptance contract must be an absolute regular non-symlink"
            )
        raw = self.contract_path.read_bytes()
        if not raw or len(raw) > _MAX_CONTRACT_BYTES:
            raise LiveAcceptanceContractError("acceptance contract size is invalid")
        if hashlib.sha256(raw).hexdigest() != FROZEN_ACCEPTANCE_SHA256:
            raise LiveAcceptanceContractError("frozen acceptance contract hash differs")
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise LiveAcceptanceContractError("acceptance YAML is invalid") from exc
        if not isinstance(parsed, dict):
            raise LiveAcceptanceContractError("acceptance contract must be an object")
        if parsed.get("schema") != FROZEN_ACCEPTANCE_SCHEMA:
            raise LiveAcceptanceContractError("acceptance schema differs")
        bounds = parsed.get("run_bounds")
        expected_bounds = {
            "agent": "dfhack-governed-scripted",
            "memory_enabled": False,
            "max_steps": 20,
            "max_ticks_per_step": 200,
            "max_real_runtime_attempts": MAX_REAL_RUNTIME_ATTEMPTS,
            "provider_calls": 0,
            "provider_cost_usd": 0,
        }
        if bounds != expected_bounds:
            raise LiveAcceptanceContractError("acceptance run bounds differ")
        expected_gates = [gate.acceptance_mapping() for gate in FROZEN_GATE_PLAN]
        if parsed.get("gates") != expected_gates:
            raise LiveAcceptanceContractError(
                "acceptance gate order or metadata differs from the frozen plan"
            )
        if parsed.get("decision_rule") != {
            "go": "every hard gate passes on the real runtime with complete evidence",
            "incomplete_no_go": (
                "local or mock success without CO-8, daemon restart, OOM, ENOSPC, "
                "provider network exclusion, and orphan recovery on isolated x86-64 Linux"
            ),
        }:
            raise LiveAcceptanceContractError("acceptance decision rule differs")

    def _validate_local_credits(self) -> dict[str, dict[str, Any]]:
        expected_order = [
            gate.gate_id
            for gate in FROZEN_GATE_PLAN
            if gate.local_credit_scope is not None
        ]
        if [credit.gate_id for credit in self.local_credits] != expected_order:
            raise LiveAcceptanceEvidenceError(
                "local credits must exactly match the frozen boundary and order"
            )
        validated: dict[str, dict[str, Any]] = {}
        for credit in self.local_credits:
            gate = _GATE_BY_ID[credit.gate_id]
            if credit.scope is not _LOCAL_CREDIT_BOUNDARIES[credit.gate_id]:
                raise LiveAcceptanceEvidenceError("local credit scope differs")
            criteria = _validate_criteria_subset(
                credit.criteria_passed,
                gate.criteria,
                label="local credit",
            )
            if criteria != gate.criteria:
                raise LiveAcceptanceEvidenceError(
                    "local credit must prove its complete local procedure"
                )
            evidence = self._reference_files(credit.evidence_paths)
            if not evidence:
                raise LiveAcceptanceEvidenceError("local credit evidence is empty")
            validated[credit.gate_id] = {
                "gate_id": credit.gate_id,
                "scope": credit.scope.value,
                "criteria_passed": list(criteria),
                "evidence": [reference.payload() for reference in evidence],
            }
        return validated

    def _batch_open_payload(self) -> dict[str, Any]:
        return {
            "plan": _plan_payload(),
            "plan_sha256": FROZEN_PLAN_SHA256,
            "source_manifest": self._source_reference.payload(),
            "local_credit_boundaries": {
                gate_id: scope.value
                for gate_id, scope in _LOCAL_CREDIT_BOUNDARIES.items()
            },
        }

    def _ensure_local_credit_events(self, state: _ReplayState) -> None:
        expected_ids = [
            gate.gate_id
            for gate in FROZEN_GATE_PLAN
            if gate.local_credit_scope is not None
        ]
        present = list(state.local_credits)
        if present != expected_ids[: len(present)]:
            raise LiveAcceptanceEvidenceError("local credit ledger order differs")
        for gate_id in expected_ids[len(present) :]:
            self._append_batch(
                "local_credit_imported",
                self._validated_local_credits[gate_id],
            )

    def _replay(self) -> _ReplayState:
        batch_records = self._batch_ledger.records()
        attempt_records = self._attempt_ledger.records()
        attempt_states, attempt_head = self._replay_attempts(attempt_records)
        opened = False
        finalized = False
        final_payload: dict[str, Any] | None = None
        local_credits: dict[str, dict[str, Any]] = {}
        gate_results: dict[str, dict[str, Any]] = {}
        cleanup_started: set[tuple[str, str | None]] = set()
        cleanup_passes: dict[tuple[str, str | None], dict[int, dict[str, Any]]] = {}
        cleanup_completed: dict[tuple[str, str | None], dict[str, Any]] = {}
        cleanup_gate_result: dict[str, Any] | None = None
        active_gate: str | None = None
        substantive_ids = [gate.gate_id for gate in _SUBSTANTIVE_GATES]
        attempt_first_previous: dict[str, str] = {}
        attempt_last_head: dict[str, str] = {}
        for attempt_record in attempt_records:
            attempt_payload = attempt_record["payload"]
            gate_id = str(attempt_payload["gate_id"])
            attempt_first_previous.setdefault(
                gate_id, str(attempt_record["previous_record_sha256"])
            )
            attempt_last_head[gate_id] = str(attempt_record["record_sha256"])
        expected_attempt_head = _ZERO_SHA256

        for record in batch_records:
            event = str(record["event"])
            payload = dict(record["payload"])
            if event == "batch_opened":
                if opened or payload != self._batch_open_payload():
                    raise LiveAcceptanceEvidenceError("batch-open identity differs")
                opened = True
                continue
            if not opened:
                raise LiveAcceptanceEvidenceError("batch event precedes batch_opened")
            if finalized:
                raise LiveAcceptanceEvidenceError(
                    "batch ledger continues after finalization"
                )
            if event == "local_credit_imported":
                gate_id = payload.get("gate_id")
                if active_gate is not None or gate_results:
                    raise LiveAcceptanceEvidenceError(
                        "local credit was imported after gate execution"
                    )
                if gate_id not in self._validated_local_credits:
                    raise LiveAcceptanceEvidenceError("unknown local credit in ledger")
                if gate_id in local_credits:
                    raise LiveAcceptanceEvidenceError(
                        "duplicate local credit in ledger"
                    )
                if payload != self._validated_local_credits[gate_id]:
                    raise LiveAcceptanceEvidenceError("local credit evidence drifted")
                local_credits[str(gate_id)] = payload
            elif event == "gate_started":
                if active_gate is not None:
                    raise LiveAcceptanceEvidenceError(
                        "nested gate execution is invalid"
                    )
                gate_payload = payload.get("gate")
                if not isinstance(gate_payload, dict):
                    raise LiveAcceptanceEvidenceError("gate-start payload is invalid")
                gate_id = gate_payload.get("id")
                expected_position = len(gate_results)
                if (
                    expected_position >= len(substantive_ids)
                    or gate_id != substantive_ids[expected_position]
                    or gate_payload
                    != _GATE_BY_ID[str(gate_id)].payload(
                        gate_index=FROZEN_GATE_PLAN.index(_GATE_BY_ID[str(gate_id)]) + 1
                    )
                    or set(payload) != {"gate", "attempt_ledger_head_sha256"}
                    or not _SHA256_RE.fullmatch(
                        str(payload.get("attempt_ledger_head_sha256"))
                    )
                    or payload.get("attempt_ledger_head_sha256")
                    != expected_attempt_head
                    or (
                        gate_id in attempt_first_previous
                        and attempt_first_previous[gate_id] != expected_attempt_head
                    )
                ):
                    raise LiveAcceptanceEvidenceError(
                        "gate-start order, metadata, or attempt head differs"
                    )
                active_gate = str(gate_id)
            elif event == "gate_completed":
                gate_id = _gate_result_id(payload)
                if active_gate != gate_id or gate_id in gate_results:
                    raise LiveAcceptanceEvidenceError(
                        "gate completion does not match the active gate"
                    )
                self._validate_recorded_gate_result(payload)
                expected_gate_head = attempt_last_head.get(
                    gate_id, expected_attempt_head
                )
                if payload.get("attempt_ledger_head_sha256") != expected_gate_head:
                    raise LiveAcceptanceEvidenceError(
                        "gate completion attempt-ledger checkpoint differs"
                    )
                expected_attempt_head = expected_gate_head
                gate_results[gate_id] = payload
                active_gate = None
            elif event == "cleanup_started":
                key = _cleanup_key(payload)
                self._validate_cleanup_position(
                    key,
                    gate_results=gate_results,
                    cleanup_completed=cleanup_completed,
                )
                if (
                    key in cleanup_started
                    or set(payload)
                    != {
                        "scope",
                        "gate_id",
                        "required_passes",
                    }
                    or payload.get("required_passes") != REQUIRED_CLEANUP_PASSES
                ):
                    raise LiveAcceptanceEvidenceError("cleanup-start record differs")
                cleanup_started.add(key)
                cleanup_passes[key] = {}
            elif event == "cleanup_pass_completed":
                key = _cleanup_key(payload)
                if key not in cleanup_started or key in cleanup_completed:
                    raise LiveAcceptanceEvidenceError(
                        "cleanup pass is outside an active cleanup scope"
                    )
                pass_index = payload.get("pass_index")
                if pass_index not in {1, 2} or pass_index in cleanup_passes[key]:
                    raise LiveAcceptanceEvidenceError(
                        "cleanup pass index is invalid or duplicated"
                    )
                if pass_index != len(cleanup_passes[key]) + 1:
                    raise LiveAcceptanceEvidenceError(
                        "cleanup passes are not in exact order"
                    )
                self._validate_recorded_cleanup_pass(payload)
                cleanup_passes[key][int(pass_index)] = payload
            elif event == "cleanup_completed":
                key = _cleanup_key(payload)
                if (
                    key not in cleanup_started
                    or key in cleanup_completed
                    or set(cleanup_passes[key]) != {1, 2}
                ):
                    raise LiveAcceptanceEvidenceError(
                        "cleanup completion lacks exactly two passes"
                    )
                expected_passes = [cleanup_passes[key][1], cleanup_passes[key][2]]
                expected_status = (
                    GateStatus.PASS.value
                    if all(
                        item["status"] == GateStatus.PASS.value
                        for item in expected_passes
                    )
                    else GateStatus.FAIL.value
                )
                if payload != {
                    "scope": key[0],
                    "gate_id": key[1],
                    "status": expected_status,
                    "required_passes": REQUIRED_CLEANUP_PASSES,
                    "passes": expected_passes,
                }:
                    raise LiveAcceptanceEvidenceError("cleanup summary differs")
                cleanup_completed[key] = payload
            elif event == "cleanup_gate_completed":
                if cleanup_gate_result is not None or active_gate is not None:
                    raise LiveAcceptanceEvidenceError("cleanup gate is duplicated")
                if ("batch", None) not in cleanup_completed:
                    raise LiveAcceptanceEvidenceError(
                        "cleanup gate precedes final batch cleanup"
                    )
                if _gate_result_id(payload) != "CLEANUP":
                    raise LiveAcceptanceEvidenceError("cleanup gate identity differs")
                self._validate_recorded_gate_result(payload)
                cleanup_gate_result = payload
            elif event == "batch_finalized":
                if cleanup_gate_result is None or active_gate is not None:
                    raise LiveAcceptanceEvidenceError(
                        "batch finalization precedes cleanup gate"
                    )
                if set(payload) != {
                    "decision",
                    "gate_results_sha256",
                    "decision_sha256",
                    "real_runtime_attempts_started",
                    "real_runtime_attempts_completed",
                    "non_runtime_attempts_started",
                    "non_runtime_attempts_completed",
                }:
                    raise LiveAcceptanceEvidenceError(
                        "batch finalization fields differ"
                    )
                finalized = True
                final_payload = payload
            else:
                raise LiveAcceptanceEvidenceError(f"unknown batch event: {event}")

        if batch_records and not opened:
            raise LiveAcceptanceEvidenceError("batch ledger lacks opening record")
        self._validate_attempt_batch_crosslinks(
            attempt_states,
            gate_results=gate_results,
            active_gate=active_gate,
        )
        self._verify_all_recorded_artifacts(
            batch_records=batch_records,
            attempt_records=attempt_records,
        )
        self._attempt_states = attempt_states
        return _ReplayState(
            opened=opened,
            finalized=finalized,
            final_payload=final_payload,
            local_credits=local_credits,
            gate_results=gate_results,
            cleanup_started=cleanup_started,
            cleanup_passes=cleanup_passes,
            cleanup_completed=cleanup_completed,
            cleanup_gate_result=cleanup_gate_result,
            active_gate=active_gate,
            attempt_states=attempt_states,
            attempt_head_sha256=attempt_head,
        )

    def _replay_attempts(
        self, records: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, _AttemptState], str]:
        planned: dict[str, _AttemptState] = {}
        ordered_attempt_ids: list[str] = []
        for gate_index, gate in enumerate(FROZEN_GATE_PLAN, start=1):
            for slot_index, attempt in enumerate(gate.attempts, start=1):
                payload = attempt.payload(
                    gate_index=gate_index,
                    slot_index=slot_index,
                )
                attempt_id = str(payload["attempt_id"])
                planned[attempt_id] = _AttemptState(
                    plan={"gate_id": gate.gate_id, **payload}
                )
                ordered_attempt_ids.append(attempt_id)
        last_started_position = -1
        for record in records:
            event = record["event"]
            payload = dict(record["payload"])
            attempt_id = payload.get("attempt_id")
            if attempt_id not in planned:
                raise LiveAcceptanceEvidenceError(
                    "attempt ledger names an unknown slot"
                )
            state = planned[str(attempt_id)]
            if payload.get("gate_id") != state.plan["gate_id"]:
                raise LiveAcceptanceEvidenceError("attempt gate identity differs")
            if event == "attempt_started":
                if state.started or set(payload) != {
                    "gate_id",
                    "attempt_id",
                    "kind",
                    "role",
                    "identity_sha256",
                    "batch_ledger_head_sha256",
                }:
                    raise LiveAcceptanceEvidenceError("attempt-start fields differ")
                position = ordered_attempt_ids.index(str(attempt_id))
                if position <= last_started_position:
                    raise LiveAcceptanceEvidenceError(
                        "attempt starts do not follow frozen order"
                    )
                if (
                    payload.get("kind") != state.plan["kind"]
                    or payload.get("role") != state.plan["role"]
                    or not _SHA256_RE.fullmatch(str(payload.get("identity_sha256")))
                    or not _SHA256_RE.fullmatch(
                        str(payload.get("batch_ledger_head_sha256"))
                    )
                ):
                    raise LiveAcceptanceEvidenceError("attempt-start identity differs")
                state.identity_sha256 = str(payload["identity_sha256"])
                last_started_position = position
            elif event == "private_authorization_bound":
                if (
                    set(payload)
                    != {
                        "gate_id",
                        "attempt_id",
                        "authorization_identity_sha256",
                    }
                    or state.plan["gate_id"] != "ENOSPC"
                    or state.plan["role"] != "target"
                    or not state.started
                    or state.completed
                    or state.authorization_identity_sha256 is not None
                    or not _SHA256_RE.fullmatch(
                        str(payload.get("authorization_identity_sha256"))
                    )
                ):
                    raise LiveAcceptanceEvidenceError(
                        "private authorization binding is invalid"
                    )
                state.authorization_identity_sha256 = str(
                    payload["authorization_identity_sha256"]
                )
            elif event == "attempt_completed":
                if (
                    set(payload)
                    != {
                        "gate_id",
                        "attempt_id",
                        "outcome_code",
                        "evidence",
                    }
                    or not state.started
                    or state.completed
                    or not _CODE_RE.fullmatch(str(payload.get("outcome_code")))
                ):
                    raise LiveAcceptanceEvidenceError(
                        "attempt completion fields or order differ"
                    )
                if (
                    state.plan["gate_id"] == "ENOSPC"
                    and state.plan["role"] == "target"
                    and state.authorization_identity_sha256 is None
                ):
                    raise LiveAcceptanceEvidenceError(
                        "ENOSPC target completed without authorization binding"
                    )
                evidence = _references_from_payload(payload.get("evidence"))
                if not evidence:
                    raise LiveAcceptanceEvidenceError(
                        "attempt completion evidence is empty"
                    )
                state.outcome_code = str(payload["outcome_code"])
                state.evidence = evidence
            else:
                raise LiveAcceptanceEvidenceError(f"unknown attempt event: {event}")
        runtime_started = sum(
            state.started and state.plan["kind"] == AttemptKind.REAL_RUNTIME.value
            for state in planned.values()
        )
        if runtime_started > MAX_REAL_RUNTIME_ATTEMPTS:
            raise LiveAcceptanceEvidenceError("real-runtime attempt ceiling exceeded")
        head = str(records[-1]["record_sha256"]) if records else _ZERO_SHA256
        return planned, head

    def _validate_attempt_batch_crosslinks(
        self,
        attempts: Mapping[str, _AttemptState],
        *,
        gate_results: Mapping[str, Mapping[str, Any]],
        active_gate: str | None,
    ) -> None:
        allowed = set(gate_results)
        if active_gate is not None:
            allowed.add(active_gate)
        for state in attempts.values():
            if state.started and state.plan["gate_id"] not in allowed:
                raise LiveAcceptanceEvidenceError(
                    "attempt exists before its batch gate start"
                )
        for gate_id, result in gate_results.items():
            expected = self._summary_from_states(_GATE_BY_ID[gate_id], attempts)
            if result.get("attempts") != expected:
                raise LiveAcceptanceEvidenceError(
                    "gate result attempt accounting differs from attempt ledger"
                )

    def _summary_from_states(
        self,
        gate: GatePlan,
        attempts: Mapping[str, _AttemptState],
    ) -> dict[str, Any]:
        gate_index = FROZEN_GATE_PLAN.index(gate) + 1
        states = [
            attempts[
                attempt.payload(gate_index=gate_index, slot_index=slot_index)[
                    "attempt_id"
                ]
            ]
            for slot_index, attempt in enumerate(gate.attempts, start=1)
        ]
        return {
            "planned": len(states),
            "started": sum(state.started for state in states),
            "completed": sum(state.completed for state in states),
            "real_runtime_started": sum(
                state.started and state.plan["kind"] == "real_runtime"
                for state in states
            ),
            "real_runtime_completed": sum(
                state.completed and state.plan["kind"] == "real_runtime"
                for state in states
            ),
            "non_runtime_started": sum(
                state.started and state.plan["kind"] == "non_runtime_conflict"
                for state in states
            ),
            "non_runtime_completed": sum(
                state.completed and state.plan["kind"] == "non_runtime_conflict"
                for state in states
            ),
        }

    def _validate_recorded_gate_result(self, payload: Mapping[str, Any]) -> None:
        expected_keys = {
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
        if set(payload) != expected_keys:
            raise LiveAcceptanceEvidenceError("recorded gate-result fields differ")
        gate_id = _gate_result_id(payload)
        gate = _GATE_BY_ID[gate_id]
        gate_index = FROZEN_GATE_PLAN.index(gate) + 1
        if payload.get("gate") != gate.payload(gate_index=gate_index):
            raise LiveAcceptanceEvidenceError("recorded gate metadata differs")
        status = payload.get("status")
        allowed_statuses = {
            GateStatus.PASS.value,
            GateStatus.PASS_LOCAL.value,
            GateStatus.FAIL.value,
        }
        if status not in allowed_statuses:
            raise LiveAcceptanceEvidenceError("recorded gate status is invalid")
        criteria = _validate_criteria_subset(
            payload.get("criteria_passed"),
            gate.criteria,
            label="recorded gate",
        )
        if status in {GateStatus.PASS.value, GateStatus.PASS_LOCAL.value} and (
            criteria != gate.criteria or payload.get("failure_code") is not None
        ):
            raise LiveAcceptanceEvidenceError("passing gate result is contradictory")
        if status == GateStatus.FAIL.value and not _CODE_RE.fullmatch(
            str(payload.get("failure_code"))
        ):
            raise LiveAcceptanceEvidenceError("failed gate lacks a safe failure code")
        evidence = _references_from_payload(payload.get("evidence"))
        if status != GateStatus.FAIL.value and not evidence:
            raise LiveAcceptanceEvidenceError("passing gate evidence is empty")
        if not _SHA256_RE.fullmatch(str(payload.get("attempt_ledger_head_sha256"))):
            raise LiveAcceptanceEvidenceError("gate attempt-ledger head is invalid")
        local_credit = payload.get("local_credit")
        expected_credit = self._validated_local_credits.get(gate_id)
        if local_credit != expected_credit:
            raise LiveAcceptanceEvidenceError("gate local-credit binding differs")
        authorization = payload.get("authorization_identity_sha256")
        if gate_id == "ENOSPC":
            if authorization is not None and not _SHA256_RE.fullmatch(
                str(authorization)
            ):
                raise LiveAcceptanceEvidenceError(
                    "ENOSPC authorization identity is invalid"
                )
        elif authorization is not None:
            raise LiveAcceptanceEvidenceError(
                "non-ENOSPC gate carries a private authorization identity"
            )

    def _validate_recorded_cleanup_pass(self, payload: Mapping[str, Any]) -> None:
        if set(payload) != {
            "scope",
            "gate_id",
            "pass_index",
            "status",
            "criteria_passed",
            "failure_code",
            "evidence",
        }:
            raise LiveAcceptanceEvidenceError("cleanup-pass fields differ")
        criteria = _validate_criteria_subset(
            payload.get("criteria_passed"),
            _GATE_BY_ID["CLEANUP"].criteria,
            label="recorded cleanup",
        )
        status = payload.get("status")
        evidence = _references_from_payload(payload.get("evidence"))
        if status == GateStatus.PASS.value:
            if (
                criteria != _GATE_BY_ID["CLEANUP"].criteria
                or payload.get("failure_code") is not None
                or not evidence
            ):
                raise LiveAcceptanceEvidenceError(
                    "passing cleanup record is contradictory"
                )
        elif status == GateStatus.FAIL.value:
            if not _CODE_RE.fullmatch(str(payload.get("failure_code"))):
                raise LiveAcceptanceEvidenceError(
                    "failed cleanup lacks a safe failure code"
                )
        else:
            raise LiveAcceptanceEvidenceError("cleanup status is invalid")

    def _validate_cleanup_position(
        self,
        key: tuple[str, str | None],
        *,
        gate_results: Mapping[str, Mapping[str, Any]],
        cleanup_completed: Mapping[tuple[str, str | None], Mapping[str, Any]],
    ) -> None:
        scope, gate_id = key
        if scope == "gate":
            if gate_id not in gate_results or key in cleanup_completed:
                raise LiveAcceptanceEvidenceError(
                    "gate cleanup is missing its completed gate or is duplicated"
                )
            return
        if scope != "batch" or gate_id is not None or key in cleanup_completed:
            raise LiveAcceptanceEvidenceError("batch cleanup identity differs")

    def _gate_results_payload(self, state: _ReplayState) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for gate in FROZEN_GATE_PLAN:
            if gate.gate_id == "CLEANUP":
                result = state.cleanup_gate_result
            else:
                result = state.gate_results.get(gate.gate_id)
            if result is None:
                gate_index = FROZEN_GATE_PLAN.index(gate) + 1
                result = {
                    "gate": gate.payload(gate_index=gate_index),
                    "status": GateStatus.NOT_RUN.value,
                    "criteria_passed": [],
                    "failure_code": "not_run",
                    "evidence": [],
                    "local_credit": self._validated_local_credits.get(gate.gate_id),
                    "attempts": self._summary_from_states(
                        gate,
                        state.attempt_states,
                    ),
                    "authorization_identity_sha256": None,
                    "attempt_ledger_head_sha256": state.attempt_head_sha256,
                }
            rows.append(dict(result))
        return {
            "schema": GATE_RESULTS_SCHEMA,
            "batch_id": self.batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "gates": rows,
        }

    def _decision_payload(
        self,
        state: _ReplayState,
        gate_results_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        rows = list(gate_results_payload["gates"])
        expected_pass = {
            gate.gate_id: (
                GateStatus.PASS_LOCAL.value
                if gate.local_credit_scope is LocalCreditScope.COMPLETE_LOCAL_GATE
                else GateStatus.PASS.value
            )
            for gate in FROZEN_GATE_PLAN
        }
        failed_gates = [
            row["gate"]["id"]
            for row in rows
            if row["status"] != expected_pass[row["gate"]["id"]]
        ]
        attempt_counts = self._attempt_counts(state.attempt_states)
        incomplete_attempts = sorted(
            attempt_id
            for attempt_id, attempt in state.attempt_states.items()
            if attempt.started and not attempt.completed
        )
        missing_attempts = sorted(
            attempt_id
            for attempt_id, attempt in state.attempt_states.items()
            if not attempt.started
        )
        reasons = [f"gate_not_passed:{gate_id}" for gate_id in failed_gates]
        if attempt_counts["real_runtime_attempts_started"] != MAX_REAL_RUNTIME_ATTEMPTS:
            reasons.append("real_runtime_attempt_count_not_26")
        if (
            attempt_counts["real_runtime_attempts_completed"]
            != MAX_REAL_RUNTIME_ATTEMPTS
        ):
            reasons.append("real_runtime_terminal_count_not_26")
        if attempt_counts["non_runtime_attempts_started"] != 1:
            reasons.append("port2_non_runtime_conflict_start_missing")
        if attempt_counts["non_runtime_attempts_completed"] != 1:
            reasons.append("port2_non_runtime_conflict_terminal_missing")
        if incomplete_attempts:
            reasons.append("attempt_terminal_evidence_incomplete")
        if missing_attempts:
            reasons.append("planned_attempts_not_run")
        decision = (
            BatchDecisionValue.GO
            if not reasons
            else BatchDecisionValue.INCOMPLETE_NO_GO
        )
        return {
            "schema": DECISION_SCHEMA,
            "batch_id": self.batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "decision": decision.value,
            "hard_gate_count": len(FROZEN_GATE_PLAN),
            "hard_gates_passed": len(FROZEN_GATE_PLAN) - len(failed_gates),
            "failed_or_incomplete_gates": failed_gates,
            "real_runtime_attempt_limit": MAX_REAL_RUNTIME_ATTEMPTS,
            **attempt_counts,
            "incomplete_attempt_ids": incomplete_attempts,
            "missing_attempt_ids": missing_attempts,
            "reasons": reasons,
            "provider_calls": 0,
            "provider_cost_usd": 0,
        }

    def _attempt_counts(self, attempts: Mapping[str, _AttemptState]) -> dict[str, int]:
        return {
            "real_runtime_attempts_started": sum(
                state.started and state.plan["kind"] == "real_runtime"
                for state in attempts.values()
            ),
            "real_runtime_attempts_completed": sum(
                state.completed and state.plan["kind"] == "real_runtime"
                for state in attempts.values()
            ),
            "non_runtime_attempts_started": sum(
                state.started and state.plan["kind"] == "non_runtime_conflict"
                for state in attempts.values()
            ),
            "non_runtime_attempts_completed": sum(
                state.completed and state.plan["kind"] == "non_runtime_conflict"
                for state in attempts.values()
            ),
        }

    def _write_and_validate_seal(
        self,
        state: _ReplayState,
        *,
        gate_results_payload: Mapping[str, Any],
        decision_payload: Mapping[str, Any],
    ) -> LiveAcceptanceOutcome:
        if not state.finalized or state.final_payload is None:
            raise LiveAcceptanceEvidenceError(
                "cannot seal a batch before durable finalization"
            )
        if state.final_payload.get("gate_results_sha256") != _payload_sha256(
            gate_results_payload
        ) or state.final_payload.get("decision_sha256") != _payload_sha256(
            decision_payload
        ):
            raise LiveAcceptanceEvidenceError("finalized payload hash differs")
        _write_once_json(self.gate_results_path, gate_results_payload)
        _write_once_json(self.decision_path, decision_payload)
        manifest_payload = self._build_manifest()
        _write_once_json(self.evidence_manifest_path, manifest_payload)
        seal_payload = {
            "schema": SEAL_SCHEMA,
            "batch_id": self.batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "decision": decision_payload["decision"],
            "gate_results_sha256": _sha256_file(self.gate_results_path),
            "decision_sha256": _sha256_file(self.decision_path),
            "evidence_manifest_sha256": _sha256_file(self.evidence_manifest_path),
        }
        _write_once_json(self.seal_path, seal_payload)
        return self._validate_sealed(self._replay())

    def _build_manifest(self) -> dict[str, Any]:
        artifacts: dict[str, EvidenceReference] = {}

        def add(reference: EvidenceReference) -> None:
            prior = artifacts.get(reference.path)
            if prior is not None and prior != reference:
                raise LiveAcceptanceEvidenceError(
                    "one evidence path has contradictory content addresses"
                )
            artifacts[reference.path] = reference

        add(
            EvidenceReference(
                path="contract/infra/m1b/acceptance.yaml",
                sha256=_sha256_file(self.contract_path),
                size_bytes=self.contract_path.stat().st_size,
            )
        )
        add(self._source_reference)
        batch_records = self._batch_ledger.records()
        attempt_records = self._attempt_ledger.records()
        for record in (*batch_records, *attempt_records):
            for reference in _walk_references(record["payload"]):
                add(reference)
        for path in (
            self.batch_ledger_path,
            self.attempt_ledger_path,
            self.gate_results_path,
            self.decision_path,
        ):
            add(self._reference_file(path))
        return {
            "schema": EVIDENCE_MANIFEST_SCHEMA,
            "batch_id": self.batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "artifacts": [artifacts[path].payload() for path in sorted(artifacts)],
        }

    def _validate_sealed(self, state: _ReplayState) -> LiveAcceptanceOutcome:
        if not state.finalized or state.final_payload is None:
            raise LiveAcceptanceEvidenceError("batch is not finalized")
        for path in (
            self.gate_results_path,
            self.decision_path,
            self.evidence_manifest_path,
            self.seal_path,
        ):
            if not path.is_file() or path.is_symlink():
                raise LiveAcceptanceEvidenceError("sealed output is missing or unsafe")
        gate_results = _read_exact_json(self.gate_results_path)
        decision = _read_exact_json(self.decision_path)
        expected_gate_results = self._gate_results_payload(state)
        expected_decision = self._decision_payload(state, expected_gate_results)
        if gate_results != expected_gate_results or decision != expected_decision:
            raise LiveAcceptanceEvidenceError("sealed result or decision drifted")
        expected_final = {
            "decision": expected_decision["decision"],
            "gate_results_sha256": _payload_sha256(expected_gate_results),
            "decision_sha256": _payload_sha256(expected_decision),
            "real_runtime_attempts_started": expected_decision[
                "real_runtime_attempts_started"
            ],
            "real_runtime_attempts_completed": expected_decision[
                "real_runtime_attempts_completed"
            ],
            "non_runtime_attempts_started": expected_decision[
                "non_runtime_attempts_started"
            ],
            "non_runtime_attempts_completed": expected_decision[
                "non_runtime_attempts_completed"
            ],
        }
        if state.final_payload != expected_final:
            raise LiveAcceptanceEvidenceError("batch-finalized checkpoint differs")
        manifest = _read_exact_json(self.evidence_manifest_path)
        if manifest != self._build_manifest_without_manifest_outputs():
            raise LiveAcceptanceEvidenceError("evidence manifest drifted")
        seal = _read_exact_json(self.seal_path)
        expected_seal = {
            "schema": SEAL_SCHEMA,
            "batch_id": self.batch_id,
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "decision": decision["decision"],
            "gate_results_sha256": _sha256_file(self.gate_results_path),
            "decision_sha256": _sha256_file(self.decision_path),
            "evidence_manifest_sha256": _sha256_file(self.evidence_manifest_path),
        }
        if seal != expected_seal:
            raise LiveAcceptanceEvidenceError("evidence seal differs")
        self._verify_manifest_files(manifest)
        counts = self._attempt_counts(state.attempt_states)
        return LiveAcceptanceOutcome(
            batch_id=self.batch_id,
            decision=BatchDecisionValue(str(decision["decision"])),
            real_runtime_attempts_started=counts["real_runtime_attempts_started"],
            real_runtime_attempts_completed=counts["real_runtime_attempts_completed"],
            non_runtime_attempts_started=counts["non_runtime_attempts_started"],
            non_runtime_attempts_completed=counts["non_runtime_attempts_completed"],
            gate_results_path=self.gate_results_path,
            decision_path=self.decision_path,
            evidence_manifest_path=self.evidence_manifest_path,
            seal_path=self.seal_path,
        )

    def _build_manifest_without_manifest_outputs(self) -> dict[str, Any]:
        # The manifest intentionally excludes itself and the seal, avoiding a
        # recursive digest while still sealing both through seal.json.
        return self._build_manifest()

    def _verify_manifest_files(self, manifest: Mapping[str, Any]) -> None:
        if set(manifest) != {
            "schema",
            "batch_id",
            "acceptance_sha256",
            "plan_sha256",
            "artifacts",
        } or (
            manifest.get("schema") != EVIDENCE_MANIFEST_SCHEMA
            or manifest.get("batch_id") != self.batch_id
            or manifest.get("acceptance_sha256") != FROZEN_ACCEPTANCE_SHA256
            or manifest.get("plan_sha256") != FROZEN_PLAN_SHA256
        ):
            raise LiveAcceptanceEvidenceError("evidence manifest identity differs")
        references = _references_from_payload(manifest.get("artifacts"))
        paths = [reference.path for reference in references]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise LiveAcceptanceEvidenceError(
                "evidence manifest paths are not sorted and unique"
            )
        for reference in references:
            if reference.path == "contract/infra/m1b/acceptance.yaml":
                observed = EvidenceReference(
                    path=reference.path,
                    sha256=_sha256_file(self.contract_path),
                    size_bytes=self.contract_path.stat().st_size,
                )
            else:
                path = self.evidence_root / reference.path
                observed = self._reference_file(path)
            if observed != reference:
                raise LiveAcceptanceEvidenceError("manifest artifact hash drifted")

    def _verify_all_recorded_artifacts(
        self,
        *,
        batch_records: Sequence[Mapping[str, Any]],
        attempt_records: Sequence[Mapping[str, Any]],
    ) -> None:
        references: dict[str, EvidenceReference] = {}
        for record in (*batch_records, *attempt_records):
            for reference in _walk_references(record["payload"]):
                prior = references.get(reference.path)
                if prior is not None and prior != reference:
                    raise LiveAcceptanceEvidenceError(
                        "recorded evidence path changed between ledger events"
                    )
                references[reference.path] = reference
        for reference in references.values():
            observed = self._reference_file(self.evidence_root / reference.path)
            if observed != reference:
                raise LiveAcceptanceEvidenceError("recorded evidence hash drifted")

    def _reference_files(self, paths: Sequence[Path]) -> tuple[EvidenceReference, ...]:
        if len(paths) > _MAX_EVIDENCE_FILES:
            raise LiveAcceptanceEvidenceError("too many evidence files")
        references = tuple(self._reference_file(Path(path)) for path in paths)
        relative_paths = [reference.path for reference in references]
        if len(relative_paths) != len(set(relative_paths)):
            raise LiveAcceptanceEvidenceError("evidence paths must be unique")
        return references

    def _reference_file(self, path: Path) -> EvidenceReference:
        raw_path = Path(path)
        if not raw_path.is_absolute() or "\0" in str(raw_path):
            raise LiveAcceptanceEvidenceError(
                "evidence file path must be absolute and NUL-free"
            )
        try:
            lexical_relative = raw_path.relative_to(self.evidence_root)
        except ValueError as exc:
            raise LiveAcceptanceEvidenceError(
                "evidence file must be lexically beneath the batch evidence root"
            ) from exc
        cursor = self.evidence_root
        for part in lexical_relative.parts:
            if part in {"", ".", ".."}:
                raise LiveAcceptanceEvidenceError(
                    "evidence path contains an unsafe traversal component"
                )
            cursor = cursor / part
            if cursor.is_symlink():
                raise LiveAcceptanceEvidenceError(
                    "evidence path cannot contain a symlink"
                )
        try:
            resolved = raw_path.resolve(strict=True)
            relative = resolved.relative_to(self.evidence_root)
        except (FileNotFoundError, ValueError) as exc:
            raise LiveAcceptanceEvidenceError(
                "evidence file must exist beneath the batch evidence root"
            ) from exc
        if not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
            raise LiveAcceptanceEvidenceError("evidence path must be a regular file")
        if (
            any(not _SAFE_PATH_PART_RE.fullmatch(part) for part in relative.parts)
            or len(relative.as_posix()) > 512
        ):
            raise LiveAcceptanceEvidenceError("evidence relative path is unsafe")
        if resolved in {
            self.evidence_manifest_path,
            self.seal_path,
        }:
            raise LiveAcceptanceEvidenceError(
                "recursive manifest or seal references are forbidden"
            )
        size = resolved.stat().st_size
        if size < 0 or size > _MAX_EVIDENCE_FILE_BYTES:
            raise LiveAcceptanceEvidenceError("evidence file size is out of bounds")
        return EvidenceReference(
            path=relative.as_posix(),
            sha256=_sha256_file(resolved),
            size_bytes=size,
        )

    def _append_batch(self, event: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._batch_ledger.append(event, payload, at=self._timestamp())

    def _append_attempt(self, event: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._attempt_ledger.append(event, payload, at=self._timestamp())

    def _timestamp(self) -> str:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise LiveAcceptanceEvidenceError("clock must return an aware datetime")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _ledger_head(ledger: _AppendOnlyLedger) -> str:
        records = ledger.records()
        return str(records[-1]["record_sha256"]) if records else _ZERO_SHA256


def _gate_result_id(payload: Mapping[str, Any]) -> str:
    gate = payload.get("gate")
    if not isinstance(gate, Mapping):
        raise LiveAcceptanceEvidenceError("gate result lacks gate metadata")
    gate_id = gate.get("id")
    if gate_id not in _GATE_BY_ID:
        raise LiveAcceptanceEvidenceError("gate result names an unknown gate")
    return str(gate_id)


def _cleanup_key(payload: Mapping[str, Any]) -> tuple[str, str | None]:
    scope = payload.get("scope")
    gate_id = payload.get("gate_id")
    if scope == "gate" and gate_id in {gate.gate_id for gate in _SUBSTANTIVE_GATES}:
        return "gate", str(gate_id)
    if scope == "batch" and gate_id is None:
        return "batch", None
    raise LiveAcceptanceEvidenceError("cleanup scope or gate identity differs")


def _validate_criteria_subset(
    actual: Any,
    expected: Sequence[str],
    *,
    label: str,
) -> tuple[str, ...]:
    if not isinstance(actual, (list, tuple)) or any(
        not isinstance(item, str) for item in actual
    ):
        raise LiveAcceptanceProtocolError(f"{label} criteria must be a sequence")
    selected = tuple(actual)
    if len(selected) != len(set(selected)):
        raise LiveAcceptanceProtocolError(f"{label} criteria contain duplicates")
    expected_tuple = tuple(expected)
    if selected != tuple(item for item in expected_tuple if item in selected):
        raise LiveAcceptanceProtocolError(
            f"{label} criteria must be an ordered subset of the frozen criteria"
        )
    return selected


def _references_from_payload(value: Any) -> tuple[EvidenceReference, ...]:
    if not isinstance(value, list) or len(value) > _MAX_EVIDENCE_FILES:
        raise LiveAcceptanceEvidenceError("evidence references must be a bounded list")
    references: list[EvidenceReference] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise LiveAcceptanceEvidenceError("evidence reference fields differ")
        path = item.get("path")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\0" in path
            or any(not _SAFE_PATH_PART_RE.fullmatch(part) for part in Path(path).parts)
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > _MAX_EVIDENCE_FILE_BYTES
        ):
            raise LiveAcceptanceEvidenceError("evidence reference is invalid")
        references.append(EvidenceReference(path=path, sha256=digest, size_bytes=size))
    if len({reference.path for reference in references}) != len(references):
        raise LiveAcceptanceEvidenceError("evidence reference paths are duplicated")
    return tuple(references)


def _walk_references(value: Any) -> tuple[EvidenceReference, ...]:
    found: list[EvidenceReference] = []
    if isinstance(value, Mapping):
        if set(value) == {"path", "sha256", "size_bytes"}:
            found.extend(_references_from_payload([dict(value)]))
        else:
            for item in value.values():
                found.extend(_walk_references(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_references(item))
    return tuple(found)


def _exception_code(prefix: str, exc: BaseException) -> str:
    type_name = re.sub(r"[^a-z0-9]+", "_", type(exc).__name__.lower()).strip("_")
    candidate = f"{prefix}_{type_name or 'exception'}"
    return candidate[:128]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("non-finite float is not JSON-safe")
        return value
    raise TypeError(
        f"live acceptance evidence is not JSON-safe: {type(value).__name__}"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_exact_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveAcceptanceEvidenceError("sealed JSON is unreadable") from exc
    if not isinstance(value, dict):
        raise LiveAcceptanceEvidenceError("sealed JSON must be an object")
    return value


def _write_once_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = _canonical_bytes(_json_safe(payload)) + b"\n"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        existing = _read_exact_json(path)
        if existing != _json_safe(payload):
            raise LiveAcceptanceEvidenceError("write-once output already differs")
        return
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write-once evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "ATTEMPT_LEDGER_SCHEMA",
    "BATCH_LEDGER_SCHEMA",
    "DECISION_SCHEMA",
    "EVIDENCE_MANIFEST_SCHEMA",
    "FROZEN_ACCEPTANCE_SHA256",
    "FROZEN_GATE_PLAN",
    "FROZEN_PLAN_SHA256",
    "GATE_RESULTS_SCHEMA",
    "MAX_REAL_RUNTIME_ATTEMPTS",
    "PLAN_SCHEMA",
    "REQUIRED_CLEANUP_PASSES",
    "SEAL_SCHEMA",
    "AttemptKind",
    "AttemptPermit",
    "BatchDecisionValue",
    "CleanupPassContext",
    "CleanupPassResult",
    "EvidenceReference",
    "GateExecutionContext",
    "GateExecutionResult",
    "GatePlan",
    "GateStatus",
    "LiveAcceptanceAdapter",
    "LiveAcceptanceAuthorization",
    "LiveAcceptanceAuthorizationError",
    "LiveAcceptanceBatchController",
    "LiveAcceptanceContractError",
    "LiveAcceptanceError",
    "LiveAcceptanceEvidenceError",
    "LiveAcceptanceOutcome",
    "LiveAcceptanceProtocolError",
    "LiveAcceptanceResumeError",
    "LocalCreditImport",
    "LocalCreditScope",
    "PrivilegedCommandExecutor",
    "PrivilegedCommandResult",
    "SourceManifestLock",
    "authorize_private_m1b_live_acceptance",
]
