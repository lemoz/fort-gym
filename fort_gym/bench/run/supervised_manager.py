"""Parent-owned orchestration for one externally assigned worker process.

This layer deliberately keeps API routing and runtime implementation details
out of the manager. Callers inject a runtime-controller factory and a worker
contract factory; the manager owns supervision evidence and the sole final
registry transition after parent cleanup.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

try:  # pragma: no cover - POSIX path is exercised in tests
    import fcntl
except ImportError:  # pragma: no cover - Windows is not an M1b target
    fcntl = None  # type: ignore[assignment]

from .fault_classification import (
    FAULT_CLASSIFICATION_RECORD_SCHEMA,
    FAULT_CLASSIFIER_RESULT_SCHEMA,
    FAULT_OBSERVATION_SCHEMA,
    RUNTIME_FAULT_CLASSIFICATION_FAILURE,
    RUNTIME_FAULT_TERMINAL_CLASSES,
    FaultClassificationError,
    validate_fault_classifier_result,
)
from .fault_session import FaultSessionEvidenceError
from .process_supervisor import (
    FaultClassifier,
    PreCleanupObserver,
    ProcessSupervisor,
    ProviderNetworkController,
    ProviderNetworkLaunchPlan,
    RunSpec,
    SupervisionResult,
    SupervisorError,
    TraceBudgetMonitor,
    _validated_provider_network_report,
    build_provider_network_launch_plan,
    canonical_argv_sha256,
    validate_terminal_chain,
    write_recovered_terminal_chain,
)
from .storage import RunInfo, RunRegistry

EXTERNAL_WORKER_COMPLETED = 0
EXTERNAL_WORKER_FAILED = 20
EXTERNAL_WORKER_STOPPED = 21
EXTERNAL_WORKER_EXCEPTION = 22
TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped"})
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_NONCE_RE = re.compile(r"^[a-f0-9]{32,64}$")


class SupervisedManagerError(RuntimeError):
    """Base error for invalid manager contracts or control evidence."""


class ActiveRunOwnershipError(SupervisedManagerError):
    """Another manager still owns the run control lock."""


class ControlEvidenceError(SupervisedManagerError):
    """Persisted control evidence is malformed or contradictory."""


class RuntimeController(Protocol):
    """Injected runtime lifecycle seam used by ``ProcessSupervisor``.

    Implementations may additionally expose ``classify_runtime_fault``.  The
    manager passes that optional callable to the supervisor only after the
    required prepare/cleanup interface has been validated.
    """

    def prepare(self) -> Mapping[str, Any] | None: ...

    def cleanup(self) -> Mapping[str, Any] | None: ...


class SupervisorLike(Protocol):
    def run(
        self,
        spec: RunSpec,
        *,
        prepare: Callable[[], Mapping[str, Any] | None] | None = None,
        cleanup: Callable[[], Mapping[str, Any] | None] | None = None,
        post_cleanup: Callable[[], Mapping[str, Any] | None] | None = None,
        fault_classifier: FaultClassifier | None = None,
        pre_cleanup_observer: PreCleanupObserver | None = None,
        provider_network: ProviderNetworkController | None = None,
    ) -> SupervisionResult: ...


RuntimeControllerFactory = Callable[[RunInfo, Path], RuntimeController]
WorkerContractFactory = Callable[[RunInfo, Path, RuntimeController], RunSpec]
SupervisorFactory = Callable[[], SupervisorLike]
ProviderNetworkControllerFactory = Callable[
    [RunInfo, Path, RuntimeController, RunSpec], ProviderNetworkController
]
PreCleanupObserverFactory = Callable[
    [RunInfo, Path, RuntimeController, RunSpec], PreCleanupObserver | None
]


class PostCleanupController(Protocol):
    def cleanup(self) -> Mapping[str, Any] | None: ...

    def reconcile(self) -> Mapping[str, Any] | None: ...


PostCleanupControllerFactory = Callable[[RunInfo, Path], PostCleanupController | None]
OwnershipProbe = Callable[[Mapping[str, Any]], bool]
ProcessIdentityProbe = Callable[[int], Mapping[str, Any]]
ProcessIdsProbe = Callable[[], Sequence[int]]
ProcessGroupProbe = Callable[[int], int]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class ManagedRunResult:
    run_id: str
    status: str
    finalized: bool
    recovered: bool
    action: str
    returncode: int | None
    control_dir: Path
    reason: Mapping[str, Any]


@dataclass(frozen=True)
class _ControlPaths:
    run_dir: Path
    attempt_dir: Path
    owner: Path
    journal: Path
    manager_terminal: Path
    supervision_observed: Path
    lock: Path


@dataclass(frozen=True)
class _ExpectedChildIdentity:
    child_pid: int
    run_id: str
    contract_sha256: str
    nonce: str = field(repr=False)
    provider_network_launch: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class _ProviderNetworkJournalEvidence:
    launch: Mapping[str, Any]
    prepared: bool
    launch_intended: bool


class SupervisedRunManager:
    """Launch and finalize exactly one externally assigned worker."""

    def __init__(
        self,
        *,
        registry: RunRegistry,
        control_root: Path,
        runtime_controller_factory: RuntimeControllerFactory,
        contract_factory: WorkerContractFactory,
        supervisor_factory: SupervisorFactory = ProcessSupervisor,
        provider_network_controller_factory: (
            ProviderNetworkControllerFactory | None
        ) = None,
        pre_cleanup_observer_factory: PreCleanupObserverFactory | None = None,
        post_cleanup_controller_factory: PostCleanupControllerFactory | None = None,
        ownership_probe: OwnershipProbe | None = None,
        process_identity_probe: ProcessIdentityProbe | None = None,
        process_ids_probe: ProcessIdsProbe | None = None,
        process_group_probe: ProcessGroupProbe = os.getpgid,
        clock: Clock | None = None,
    ) -> None:
        self._registry = registry
        self._control_root = Path(control_root).resolve()
        self._runtime_controller_factory = runtime_controller_factory
        self._contract_factory = contract_factory
        self._supervisor_factory = supervisor_factory
        self._provider_network_controller_factory = provider_network_controller_factory
        if pre_cleanup_observer_factory is not None and not callable(
            pre_cleanup_observer_factory
        ):
            raise TypeError("pre_cleanup_observer_factory must be callable or None")
        self._pre_cleanup_observer_factory = pre_cleanup_observer_factory
        self._post_cleanup_controller_factory = post_cleanup_controller_factory
        self._ownership_probe = ownership_probe or _owner_pid_is_live
        self._process_identity_probe = (
            process_identity_probe or _linux_process_identity_probe
        )
        self._process_ids_probe = process_ids_probe or _linux_process_ids
        if not callable(process_group_probe):
            raise TypeError("process_group_probe must be callable")
        self._process_group_probe = process_group_probe
        self._clock = clock or (lambda: datetime.now(UTC))
        self._manager_start_ticks = _current_process_start_ticks()

    def run(self, run_id: str) -> ManagedRunResult:
        """Launch at most one child and publish one parent-owned terminal state."""

        record = self._require_record(run_id)
        paths = self._paths(record)
        with _exclusive_lock(paths.lock):
            record = self._require_record(run_id)
            settled = self._already_terminal_result(record, paths, recovered=False)
            if settled is not None:
                return settled

            if self._has_prior_attempt(paths):
                return self._reconcile_locked(record, paths)

            paths.attempt_dir.mkdir(parents=True, exist_ok=False)
            owner = self._owner_payload(record, paths, state="active")
            _atomic_replace_json(paths.owner, owner)
            _append_journal(paths.journal, "ownership_acquired", owner=owner)

            controller: RuntimeController | None = None
            post_cleanup_controller: PostCleanupController | None = None
            owner_environment_identity: Mapping[str, Any] | None = None
            try:
                if self._post_cleanup_controller_factory is not None:
                    post_cleanup_controller = self._post_cleanup_controller_factory(
                        record,
                        paths.run_dir,
                    )
                    if post_cleanup_controller is not None:
                        self._validate_post_cleanup_controller(post_cleanup_controller)
                controller = self._runtime_controller_factory(record, paths.run_dir)
                self._validate_controller(controller)
                spec = self._contract_factory(record, paths.attempt_dir, controller)
                self._validate_spec(spec, record, paths)
                owner_environment_identity = spec.environment_identity
                owner = self._owner_payload(
                    record,
                    paths,
                    state="active",
                    environment_identity=owner_environment_identity,
                )
                _atomic_replace_json(paths.owner, owner)
                _append_journal(paths.journal, "ownership_identity_bound", owner=owner)
                pre_cleanup_observer: PreCleanupObserver | None = None
                if self._pre_cleanup_observer_factory is not None:
                    pre_cleanup_observer = self._pre_cleanup_observer_factory(
                        record,
                        paths.run_dir,
                        controller,
                        spec,
                    )
                    if pre_cleanup_observer is not None and not callable(
                        pre_cleanup_observer
                    ):
                        raise TypeError(
                            "pre-cleanup observer factory returned a non-callable"
                        )
                provider_network: ProviderNetworkController | None = None
                provider_network_plan: ProviderNetworkLaunchPlan | None = None
                if self._provider_network_controller_factory is not None:
                    provider_network = self._provider_network_controller_factory(
                        record,
                        paths.run_dir,
                        controller,
                        spec,
                    )
                    if provider_network is None:
                        raise TypeError(
                            "provider-network controller factory returned None"
                        )
                    provider_network_plan = build_provider_network_launch_plan(
                        spec, provider_network
                    )
                _append_journal(
                    paths.journal,
                    "supervision_started",
                    argv=list(spec.argv),
                    attempt_dir=str(paths.attempt_dir),
                    provider_network_requested=provider_network is not None,
                )
                supervisor = self._supervisor_factory()
                classifier = getattr(controller, "classify_runtime_fault", None)
                supervisor_kwargs: dict[str, Any] = {
                    "prepare": controller.prepare,
                    "cleanup": controller.cleanup,
                }
                if callable(classifier):
                    supervisor_kwargs["fault_classifier"] = classifier
                if pre_cleanup_observer is not None:
                    supervisor_kwargs["pre_cleanup_observer"] = pre_cleanup_observer
                if provider_network is not None:
                    supervisor_kwargs["provider_network"] = provider_network
                if post_cleanup_controller is not None:
                    supervisor_kwargs["post_cleanup"] = post_cleanup_controller.cleanup
                supervision = supervisor.run(spec, **supervisor_kwargs)
                payload = _json_mapping(supervision.payload)
                self._validate_supervision_payload(payload, run_id)
                if provider_network_plan is not None:
                    self._validate_provider_network_supervision(
                        payload,
                        provider_network_plan,
                    )
            except Exception as exc:  # noqa: BLE001 - parent terminal boundary
                payload = self._manager_exception_payload(
                    run_id=run_id,
                    controller=controller,
                    post_cleanup_controller=post_cleanup_controller,
                    exc=exc,
                )

            self._validate_supervision_payload(payload, run_id)
            _atomic_replace_json(paths.supervision_observed, payload)
            _append_journal(
                paths.journal,
                "supervision_finished",
                returncode=payload.get("returncode"),
                terminal_class=payload.get("terminal_class"),
                cleanup=payload.get("cleanup"),
            )
            _atomic_replace_json(
                paths.owner,
                self._owner_payload(
                    self._require_record(run_id),
                    paths,
                    state="supervision_finished",
                    environment_identity=owner_environment_identity,
                ),
            )
            return self._finalize_locked(
                self._require_record(run_id),
                paths,
                payload,
                recovered=False,
            )

    def reconcile(self, run_id: str) -> ManagedRunResult:
        """Recover only from durable parent/supervisor evidence.

        A live owner or an unfinished journal without a terminal record remains
        non-terminal. This method never infers failure from an unfinished
        SQLite row alone.
        """

        record = self._require_record(run_id)
        paths = self._paths(record)
        with _exclusive_lock(paths.lock):
            return self._reconcile_locked(self._require_record(run_id), paths)

    def _reconcile_locked(
        self,
        record: RunInfo,
        paths: _ControlPaths,
    ) -> ManagedRunResult:
        settled = self._already_terminal_result(record, paths, recovered=True)
        if settled is not None:
            return settled

        owner = _read_optional_mapping(paths.owner)
        if owner is not None:
            self._validate_owner(owner, record.run_id)
        owner_identity_matches_attempt = bool(
            owner is not None
            and self._owner_identity_matches_attempt(owner, paths)
        )
        if (
            owner is not None
            and owner.get("state") in {"active", "supervision_finished"}
            and owner_identity_matches_attempt
            and self._ownership_probe(owner)
        ):
            _append_journal(paths.journal, "reconcile_live_owner")
            return self._nonterminal_result(
                record,
                paths,
                action="live_owner",
                reason={"code": "live_parent_owner"},
                recovered=True,
            )

        manager_terminal = _read_optional_mapping(paths.manager_terminal)
        if manager_terminal is not None:
            self._validate_manager_terminal(manager_terminal, record.run_id)
            supervision = manager_terminal.get("supervision")
            if not isinstance(supervision, Mapping):
                raise ControlEvidenceError(
                    "manager terminal evidence is missing supervision payload"
                )
            return self._finalize_locked(
                record,
                paths,
                _json_mapping(supervision),
                recovered=True,
            )

        supervision = self._recover_supervision_payload(record.run_id, paths, owner)
        if supervision is not None:
            _append_journal(paths.journal, "reconcile_terminal_evidence")
            return self._finalize_locked(
                record,
                paths,
                supervision,
                recovered=True,
            )

        if owner is not None and owner.get("state") in {
            "active",
            "supervision_finished",
        }:
            supervision = self._dead_owner_supervision_payload(
                record,
                paths,
                owner=owner,
                supervisor_journal=self._supervisor_journal_path(paths, owner),
            )
            reason = _mapping_or_none(supervision.get("reason")) or {}
            events = reason.get("supervisor_events")
            _atomic_replace_json(paths.supervision_observed, supervision)
            _append_journal(
                paths.journal,
                "reconcile_dead_owner_cleanup_attempted",
                cleanup=supervision.get("cleanup"),
                supervisor_events=events,
            )
            return self._finalize_locked(
                record,
                paths,
                supervision,
                recovered=True,
            )

        events = _read_journal_events(self._supervisor_journal_path(paths, owner))
        _append_journal(
            paths.journal,
            "reconcile_unresolved",
            supervisor_events=events,
        )
        return self._nonterminal_result(
            record,
            paths,
            action="unresolved",
            reason={
                "code": "supervisor_terminal_evidence_missing",
                "supervisor_events": events,
            },
            recovered=True,
        )

    def _finalize_locked(
        self,
        record: RunInfo,
        paths: _ControlPaths,
        supervision: Mapping[str, Any],
        *,
        recovered: bool,
    ) -> ManagedRunResult:
        self._validate_supervision_payload(supervision, record.run_id)
        environment_identity = supervision.get("environment_identity")
        contract_bound = isinstance(environment_identity, Mapping) and isinstance(
            environment_identity.get("contract_sha256"), str
        )
        if contract_bound:
            try:
                validate_terminal_chain(
                    paths.attempt_dir,
                    supervision,
                    run_id=record.run_id,
                )
            except (OSError, SupervisorError) as exc:
                raise ControlEvidenceError(
                    "supervisor terminal chain is incomplete or contradictory"
                ) from exc
        current = self._require_record(record.run_id)
        settled = self._already_terminal_result(current, paths, recovered=recovered)
        if settled is not None:
            return settled

        cleanup = supervision.get("cleanup")
        cleanup_ok = isinstance(cleanup, Mapping) and cleanup.get("ok") is True
        returncode = _optional_int(supervision.get("returncode"))
        terminal_class = str(supervision.get("terminal_class") or "unknown")
        staged_reason = _staged_reason(current)
        supervisor_reason = _mapping_or_none(supervision.get("reason"))
        stop_requested_observed = self._registry.stop_requested(record.run_id)

        if not cleanup_ok:
            decision = "failed"
            reason = {
                "code": "parent_cleanup_failed",
                "cleanup": _json_safe(cleanup),
                "prior_terminal_reason": staged_reason or supervisor_reason,
            }
        elif terminal_class in RUNTIME_FAULT_TERMINAL_CLASSES or terminal_class == (
            RUNTIME_FAULT_CLASSIFICATION_FAILURE
        ):
            decision = "failed"
            reason = supervisor_reason or {
                "code": terminal_class,
                "returncode": returncode,
            }
        elif returncode == EXTERNAL_WORKER_FAILED:
            decision = "failed"
            reason = staged_reason or {
                "code": "external_worker_failed",
                "returncode": returncode,
            }
        elif returncode == EXTERNAL_WORKER_EXCEPTION:
            decision = "failed"
            reason = (
                staged_reason
                or supervisor_reason
                or {
                    "code": "external_worker_exception",
                    "returncode": returncode,
                }
            )
        elif returncode == EXTERNAL_WORKER_STOPPED:
            decision = "stopped"
            reason = {"code": "external_worker_stopped", "returncode": returncode}
        elif returncode == EXTERNAL_WORKER_COMPLETED and terminal_class == "completed":
            decision = "success"
            reason = {"code": "external_worker_completed", "returncode": returncode}
        else:
            decision = "failed"
            reason = supervisor_reason or {
                "code": "supervisor_terminal_failure",
                "terminal_class": terminal_class,
                "returncode": returncode,
            }

        if decision == "failed":
            reason = {
                **reason,
                "stop_requested_observed": stop_requested_observed,
            }

        finalized_at = self._clock()
        if cleanup_ok:
            self._registry.record_cleanup_completed(
                record.run_id,
                completed_at=finalized_at,
            )
            _append_journal(paths.journal, "cleanup_completion_recorded")
        else:
            _append_journal(paths.journal, "cleanup_failed", cleanup=cleanup)

        current = self._require_record(record.run_id)
        if decision in {"success", "stopped"}:
            if decision == "stopped" and not self._registry.stop_requested(
                record.run_id
            ):
                self._registry.request_stop(record.run_id)
            try:
                final_status = self._registry.finalize_success_after_cleanup(
                    record.run_id,
                    step=current.step,
                    ended_at=finalized_at,
                )
                reason = {
                    **reason,
                    "late_stop_observed": final_status == "stopped"
                    and returncode == EXTERNAL_WORKER_COMPLETED,
                }
            except Exception as exc:  # noqa: BLE001 - fail closed on finalization gaps
                reason = {
                    "code": "parent_success_finalization_failed",
                    "error": _safe_error(exc),
                    "prior_terminal_reason": reason,
                }
                self._registry.record_terminal_failure(
                    record.run_id,
                    terminal_reason=reason,
                    step=current.step,
                    ended_at=finalized_at,
                )
                self._registry.clear_stop(record.run_id)
                final_status = "failed"
        else:
            self._registry.record_terminal_failure(
                record.run_id,
                terminal_reason=dict(reason),
                step=current.step,
                ended_at=finalized_at,
            )
            self._registry.clear_stop(record.run_id)
            final_status = "failed"

        final_record = self._require_record(record.run_id)
        if (
            final_record.status not in TERMINAL_STATUSES
            or final_record.ended_at is None
        ):
            raise SupervisedManagerError(
                f"Run '{record.run_id}' did not reach one durable terminal state"
            )
        final_status = final_record.status
        terminal_payload = {
            "schema": "fortgym.supervised-manager-terminal/v1",
            "run_id": record.run_id,
            "status": final_status,
            "ended_at": final_record.ended_at.isoformat(),
            "finalized_at": _iso(finalized_at),
            "recovered": recovered,
            "returncode": returncode,
            "reason": reason,
            "supervision": _json_safe(supervision),
        }
        _write_once_or_verify(paths.manager_terminal, terminal_payload, record.run_id)
        _atomic_replace_json(
            paths.owner,
            self._owner_payload(final_record, paths, state="finalized"),
        )
        _append_journal(
            paths.journal,
            "registry_terminal_recorded",
            status=final_status,
            ended_at=final_record.ended_at.isoformat(),
        )
        return ManagedRunResult(
            run_id=record.run_id,
            status=final_status,
            finalized=True,
            recovered=recovered,
            action="finalized",
            returncode=returncode,
            control_dir=paths.run_dir,
            reason=dict(reason),
        )

    def _already_terminal_result(
        self,
        record: RunInfo,
        paths: _ControlPaths,
        *,
        recovered: bool,
    ) -> ManagedRunResult | None:
        if record.status not in TERMINAL_STATUSES:
            return None
        evidence = _read_optional_mapping(paths.manager_terminal)
        if evidence is not None:
            self._validate_manager_terminal(evidence, record.run_id)
            evidence_status = evidence.get("status")
            if evidence_status != record.status:
                raise ControlEvidenceError(
                    "manager terminal status contradicts registry terminal status"
                )
        reason = (
            (_mapping_or_none(evidence.get("reason")) if evidence is not None else None)
            or _staged_reason(record)
            or {"code": "registry_already_terminal"}
        )
        return ManagedRunResult(
            run_id=record.run_id,
            status=record.status,
            finalized=True,
            recovered=recovered,
            action="already_terminal",
            returncode=(
                _optional_int(evidence.get("returncode"))
                if evidence is not None
                else None
            ),
            control_dir=paths.run_dir,
            reason=reason,
        )

    def _nonterminal_result(
        self,
        record: RunInfo,
        paths: _ControlPaths,
        *,
        action: str,
        reason: Mapping[str, Any],
        recovered: bool,
    ) -> ManagedRunResult:
        return ManagedRunResult(
            run_id=record.run_id,
            status=record.status,
            finalized=False,
            recovered=recovered,
            action=action,
            returncode=None,
            control_dir=paths.run_dir,
            reason=dict(reason),
        )

    def _manager_exception_payload(
        self,
        *,
        run_id: str,
        controller: RuntimeController | None,
        post_cleanup_controller: PostCleanupController | None,
        exc: Exception,
    ) -> dict[str, Any]:
        cleanup: dict[str, Any]
        if controller is None:
            cleanup = {
                "ok": False,
                "stages": [
                    {
                        "stage": "runtime",
                        "ok": False,
                        "error": {
                            "type": "RuntimeControllerUnavailable",
                            "message": "runtime controller construction did not complete",
                        },
                    }
                ],
            }
        else:
            try:
                details = controller.cleanup()
                if details is not None and not isinstance(details, Mapping):
                    raise TypeError("runtime cleanup() must return a mapping or None")
                normalized_details = _json_safe(details or {})
                reported_failure = (
                    isinstance(details, Mapping)
                    and "ok" in details
                    and details.get("ok") is not True
                )
                if reported_failure:
                    cleanup = {
                        "ok": False,
                        "stages": [
                            {
                                "stage": "runtime",
                                "ok": False,
                                "details": normalized_details,
                                "error": {
                                    "type": "RuntimeCleanupReportedFailure",
                                    "message": (
                                        "runtime cleanup returned an explicit "
                                        "non-success status"
                                    ),
                                },
                            }
                        ],
                    }
                else:
                    cleanup = {
                        "ok": True,
                        "stages": [
                            {
                                "stage": "runtime",
                                "ok": True,
                                "details": normalized_details,
                            }
                        ],
                    }
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve both failures
                cleanup = {
                    "ok": False,
                    "stages": [
                        {
                            "stage": "runtime",
                            "ok": False,
                            "error": _safe_error(cleanup_exc),
                        }
                    ],
                }
        if post_cleanup_controller is not None:
            try:
                details = post_cleanup_controller.cleanup()
                if details is not None and not isinstance(details, Mapping):
                    raise TypeError("post cleanup() must return a mapping or None")
                normalized_details = _json_safe(details or {})
                reported_failure = (
                    isinstance(details, Mapping)
                    and "ok" in details
                    and details.get("ok") is not True
                )
                stage: dict[str, Any] = {
                    "stage": "post_callback",
                    "ok": not reported_failure,
                    "details": normalized_details,
                }
                if reported_failure:
                    stage["error"] = {
                        "type": "PostCleanupReportedFailure",
                        "message": (
                            "post cleanup returned an explicit non-success status"
                        ),
                    }
                cleanup["stages"].append(stage)
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve both failures
                cleanup["stages"].append(
                    {
                        "stage": "post_callback",
                        "ok": False,
                        "error": _safe_error(cleanup_exc),
                    }
                )
            cleanup["ok"] = all(stage.get("ok") is True for stage in cleanup["stages"])
        return {
            "schema": "fortgym.process-supervisor-terminal/v1",
            "run_id": run_id,
            "terminal_class": (
                "child_exit" if cleanup.get("ok") else "cleanup_failure"
            ),
            "primary_terminal_class": "child_exit",
            "returncode": EXTERNAL_WORKER_EXCEPTION,
            "reason": {"code": "manager_or_supervisor_exception", **_safe_error(exc)},
            "cleanup": cleanup,
        }

    def _dead_owner_supervision_payload(
        self,
        record: RunInfo,
        paths: _ControlPaths,
        *,
        owner: Mapping[str, Any],
        supervisor_journal: Path,
    ) -> dict[str, Any]:
        supervisor_events: list[str] = []
        journal_records: list[dict[str, Any]] = []
        provider_network_journal: _ProviderNetworkJournalEvidence | None = None
        expected_identity: _ExpectedChildIdentity | None = None
        try:
            journal_records = _read_journal_records(supervisor_journal)
            supervisor_events = [str(row["event"]) for row in journal_records]
            provider_network_journal = _provider_network_launch_from_journal(
                journal_records,
                record.run_id,
                owner_manager_pid=_required_positive_int(
                    owner.get("manager_pid"), "manager owner PID"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - preserve failed journal evidence
            harness_reconciliation = {
                "ok": False,
                "error": _safe_error(exc),
            }
        else:
            try:
                expected_identity = _child_identity_from_journal(
                    journal_records,
                    record.run_id,
                    owner_manager_pid=_required_positive_int(
                        owner.get("manager_pid"), "manager owner PID"
                    ),
                    provider_network=provider_network_journal,
                )
                harness_reconciliation = _reap_process_group(
                    expected_identity,
                    identity_probe=self._process_identity_probe,
                )
            except Exception as exc:  # noqa: BLE001 - preserve failed reap evidence
                harness_reconciliation = {
                    "ok": False,
                    "error": _safe_error(exc),
                }

        recovery_controller: RuntimeController | None = None
        recovery_spec: RunSpec | None = None
        post_cleanup_controller: PostCleanupController | None = None
        post_cleanup_construction_error: Exception | None = None
        if self._post_cleanup_controller_factory is not None:
            try:
                post_cleanup_controller = self._post_cleanup_controller_factory(
                    record,
                    paths.run_dir,
                )
                if post_cleanup_controller is not None:
                    self._validate_post_cleanup_controller(post_cleanup_controller)
            except Exception as exc:  # noqa: BLE001 - preserve reconstruction failure
                post_cleanup_construction_error = exc
        try:
            recovery_controller = self._runtime_controller_factory(
                record, paths.run_dir
            )
            self._validate_controller(recovery_controller)
            recovery_spec = self._contract_factory(
                record, paths.attempt_dir, recovery_controller
            )
            self._validate_spec(recovery_spec, record, paths)
        except Exception:  # noqa: BLE001 - each cleanup path records its own failure
            recovery_controller = None
            recovery_spec = None

        provider_network_reconciliation: dict[str, Any] = {
            "ok": True,
            "skipped": True,
            "reason": "provider_network_not_requested",
        }
        if provider_network_journal is not None:
            try:
                if self._provider_network_controller_factory is None:
                    raise ControlEvidenceError(
                        "provider-network controller factory is unavailable"
                    )
                if recovery_controller is None or recovery_spec is None:
                    raise ControlEvidenceError(
                        "provider-network recovery contract is unavailable"
                    )
                network_controller = self._provider_network_controller_factory(
                    record,
                    paths.run_dir,
                    recovery_controller,
                    recovery_spec,
                )
                if network_controller is None:
                    raise TypeError("provider-network controller factory returned None")
                recovered_plan = build_provider_network_launch_plan(
                    recovery_spec,
                    network_controller,
                )
                if _json_mapping(recovered_plan.evidence) != _json_mapping(
                    provider_network_journal.launch
                ):
                    raise ControlEvidenceError(
                        "reconstructed provider-network launch identity differs"
                    )
                intent_reconciliation: dict[str, Any] | None = None
                if (
                    expected_identity is None
                    and provider_network_journal.launch_intended
                ):
                    try:
                        intent_reconciliation = _reap_provider_network_launch_intent(
                            records=journal_records,
                            run_id=record.run_id,
                            provider_network=provider_network_journal,
                            controller=network_controller,
                            process_ids_probe=self._process_ids_probe,
                            identity_probe=self._process_identity_probe,
                            process_group_probe=self._process_group_probe,
                        )
                        harness_reconciliation = intent_reconciliation
                    except Exception as exc:
                        harness_reconciliation = {
                            "ok": False,
                            "error": _safe_error(exc),
                        }
                        raise
                if harness_reconciliation.get("ok") is not True:
                    raise ControlEvidenceError(
                        "provider-network reconciliation requires exact harness reap"
                    )
                intent_process_reaped = bool(
                    intent_reconciliation
                    and intent_reconciliation.get("intent_process_reaped") is True
                )
                intent_command_mode = (
                    intent_reconciliation.get("command_mode")
                    if intent_process_reaped and intent_reconciliation is not None
                    else None
                )
                if intent_process_reaped and intent_command_mode not in {
                    "provider_network_wrapper_pre_exec",
                    "provider_network_inner_exec",
                }:
                    raise ControlEvidenceError(
                        "provider-network launch-intent command mode is invalid"
                    )
                if expected_identity is None and (
                    not intent_process_reaped
                    or intent_command_mode == "provider_network_wrapper_pre_exec"
                ):
                    raw_network_reconciliation = network_controller.abort(
                        recovered=True
                    )
                    network_mode = (
                        "launch_intent_wrapper_reaped_abort"
                        if intent_process_reaped
                        else "prelaunch_abort"
                    )
                else:
                    raw_network_reconciliation = network_controller.reconcile()
                    network_mode = (
                        "launch_intent_inner_reaped_reconcile"
                        if intent_command_mode == "provider_network_inner_exec"
                        else "launched_reconcile"
                    )
                if (
                    not isinstance(raw_network_reconciliation, Mapping)
                    or raw_network_reconciliation.get("ok") is not True
                    or raw_network_reconciliation.get("foreign_canary_untouched")
                    is not True
                ):
                    raise ControlEvidenceError(
                        "provider-network reconciliation did not report success"
                    )
                provider_network_reconciliation = {
                    "ok": True,
                    "mode": network_mode,
                    "identity_sha256": network_controller.identity_sha256,
                    "foreign_canary_untouched": True,
                }
                if intent_reconciliation is not None:
                    provider_network_reconciliation["launch_intent"] = (
                        intent_reconciliation
                    )
                if expected_identity is not None or (
                    intent_process_reaped
                    and intent_command_mode == "provider_network_inner_exec"
                ):
                    budget_monitor = TraceBudgetMonitor(
                        recovery_spec.trace_path
                        or recovery_spec.artifact_dir / "trace.jsonl",
                        recovery_spec,
                    )
                    violation = budget_monitor.finalize()
                    if violation is not None:
                        raise ControlEvidenceError(
                            "provider-network recovery observed provider trace activity"
                        )
                    raw_validation = network_controller.validate_evidence(
                        budget_monitor.snapshot()
                    )
                    if not isinstance(raw_validation, Mapping):
                        raise ControlEvidenceError(
                            "provider-network recovery evidence is invalid"
                        )
                    _validated_provider_network_report(
                        raw_validation,
                        identity_sha256=network_controller.identity_sha256,
                    )
                    provider_network_reconciliation["validated"] = True
            except Exception as exc:  # noqa: BLE001 - persist failed recovery evidence
                provider_network_reconciliation = {
                    "ok": False,
                    "error": _safe_error(exc),
                }

        runtime_reconciliation: dict[str, Any]
        try:
            if recovery_controller is None:
                recovery_controller = self._runtime_controller_factory(
                    record, paths.run_dir
                )
                self._validate_controller(recovery_controller)
            reconcile = getattr(recovery_controller, "reconcile", None)
            if not callable(reconcile):
                raise TypeError(
                    "runtime controller cannot reconstruct dead-owner cleanup"
                )
            raw_reconciliation = reconcile()
            if not isinstance(raw_reconciliation, Mapping):
                raise TypeError("runtime controller reconcile() must return a mapping")
            runtime_reconciliation = _json_mapping(raw_reconciliation)
            _validate_runtime_reconciliation_evidence(runtime_reconciliation)
        except Exception as exc:  # noqa: BLE001 - persist failed recovery evidence
            runtime_reconciliation = {
                "ok": False,
                "error": _safe_error(exc),
            }

        post_cleanup_reconciliation: dict[str, Any] = {
            "ok": True,
            "skipped": True,
            "reason": "post_cleanup_not_requested",
        }
        if post_cleanup_construction_error is not None:
            post_cleanup_reconciliation = {
                "ok": False,
                "error": _safe_error(post_cleanup_construction_error),
            }
        elif post_cleanup_controller is not None:
            try:
                raw_post_cleanup = post_cleanup_controller.reconcile()
                if not isinstance(raw_post_cleanup, Mapping):
                    raise TypeError("post cleanup reconcile() must return a mapping")
                details = _json_mapping(raw_post_cleanup)
                if "ok" in raw_post_cleanup and raw_post_cleanup.get("ok") is not True:
                    raise ControlEvidenceError(
                        "post cleanup reconcile() did not report exact success"
                    )
                post_cleanup_reconciliation = {
                    "ok": True,
                    "details": details,
                }
            except Exception as exc:  # noqa: BLE001 - persist failed recovery evidence
                post_cleanup_reconciliation = {
                    "ok": False,
                    "error": _safe_error(exc),
                }
        cleanup_ok = (
            harness_reconciliation.get("ok") is True
            and provider_network_reconciliation.get("ok") is True
            and runtime_reconciliation.get("ok") is True
            and post_cleanup_reconciliation.get("ok") is True
        )
        reconciliation = {
            **runtime_reconciliation,
            "ok": cleanup_ok,
            "harness_process_group": harness_reconciliation,
        }
        if provider_network_journal is not None:
            reconciliation["provider_network"] = provider_network_reconciliation
        if self._post_cleanup_controller_factory is not None:
            reconciliation["post_cleanup"] = post_cleanup_reconciliation
        cleanup_stages = [
            {
                "stage": "orphan_harness_process_group",
                "ok": harness_reconciliation.get("ok") is True,
                "details": harness_reconciliation,
            },
        ]
        if provider_network_journal is not None:
            cleanup_stages.append(
                {
                    "stage": "provider_network_reconcile",
                    "ok": provider_network_reconciliation.get("ok") is True,
                    "details": provider_network_reconciliation,
                }
            )
        cleanup_stages.append(
            {
                "stage": "runtime_reconcile",
                "ok": runtime_reconciliation.get("ok") is True,
                "details": runtime_reconciliation,
            }
        )
        if self._post_cleanup_controller_factory is not None:
            cleanup_stages.append(
                {
                    "stage": "post_cleanup_reconcile",
                    "ok": post_cleanup_reconciliation.get("ok") is True,
                    "details": post_cleanup_reconciliation,
                }
            )
        cleanup = {
            "ok": cleanup_ok,
            "stages": cleanup_stages,
        }
        attempt_starts = [
            row for row in journal_records if row.get("event") == "attempt_started"
        ]
        child_starts = [
            row for row in journal_records if row.get("event") == "child_started"
        ]
        environment_identity = (
            attempt_starts[0].get("environment_identity")
            if len(attempt_starts) == 1
            and isinstance(attempt_starts[0].get("environment_identity"), Mapping)
            else {}
        )
        child_pid = child_starts[0].get("child_pid") if len(child_starts) == 1 else None
        primary_reason = {
            "code": "supervisor_lost",
            "supervisor_events": supervisor_events,
        }
        payload = {
            "schema": "fortgym.process-supervisor-terminal/v1",
            "run_id": record.run_id,
            "terminal_class": ("child_exit" if cleanup["ok"] else "cleanup_failure"),
            "primary_terminal_class": "child_exit",
            "primary_reason": primary_reason,
            "returncode": EXTERNAL_WORKER_EXCEPTION,
            "child_pid": child_pid,
            "child_signal": None,
            "port": (
                attempt_starts[0].get("port") if len(attempt_starts) == 1 else None
            ),
            "environment_identity": _json_mapping(environment_identity),
            "runtime_cleanup_required": True,
            "prepare": {},
            "termination": {},
            "reason": {
                "code": "supervisor_lost",
                "supervisor_events": supervisor_events,
                "reconciliation": reconciliation,
            },
            "cleanup": cleanup,
        }
        if isinstance(environment_identity.get("contract_sha256"), str):
            terminal_path = write_recovered_terminal_chain(
                paths.attempt_dir,
                payload,
                run_id=record.run_id,
            )
            recovered_terminal = _read_optional_mapping(terminal_path)
            if recovered_terminal is None:
                raise ControlEvidenceError(
                    "recovered supervisor terminal evidence is unavailable"
                )
            payload = dict(recovered_terminal)
        return payload

    def _recover_supervision_payload(
        self,
        run_id: str,
        paths: _ControlPaths,
        owner: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        observed = _read_optional_mapping(paths.supervision_observed)
        if observed is not None:
            self._validate_supervision_payload(observed, run_id)
            return dict(observed)
        terminal_path = self._supervisor_terminal_path(paths, owner)
        terminal = _read_optional_mapping(terminal_path)
        if terminal is None:
            return None
        self._validate_supervision_payload(terminal, run_id)
        return dict(terminal)

    def _supervisor_terminal_path(
        self,
        paths: _ControlPaths,
        owner: Mapping[str, Any] | None,
    ) -> Path:
        attempt_dir = _owner_attempt_dir(owner, paths)
        return attempt_dir / "terminal.json"

    def _supervisor_journal_path(
        self,
        paths: _ControlPaths,
        owner: Mapping[str, Any] | None,
    ) -> Path:
        attempt_dir = _owner_attempt_dir(owner, paths)
        return attempt_dir / "attempt-journal.jsonl"

    def _owner_payload(
        self,
        record: RunInfo,
        paths: _ControlPaths,
        *,
        state: str,
        environment_identity: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        identity = (
            _owner_environment_binding(environment_identity, run_id=record.run_id)
            if environment_identity is not None
            else {
                "identity_bound": False,
                "contract_sha256": None,
                "nonce_sha256": None,
                "environment_identity_sha256": None,
            }
        )
        return {
            "schema": "fortgym.supervised-manager-owner/v1",
            "run_id": record.run_id,
            "state": state,
            "manager_pid": os.getpid(),
            "manager_start_ticks": self._manager_start_ticks,
            **identity,
            "observed_registry_status": record.status,
            "attempt_dir": str(paths.attempt_dir),
            "updated_at": _iso(self._clock()),
        }

    @staticmethod
    def _owner_identity_matches_attempt(
        owner: Mapping[str, Any],
        paths: _ControlPaths,
    ) -> bool:
        if owner.get("identity_bound") is not True:
            return False
        try:
            records = _read_journal_records(paths.attempt_dir / "attempt-journal.jsonl")
        except (OSError, ControlEvidenceError):
            return False
        starts = [row for row in records if row.get("event") == "attempt_started"]
        if len(starts) != 1:
            return False
        environment = starts[0].get("environment_identity")
        if not isinstance(environment, Mapping):
            return False
        try:
            binding = _owner_environment_binding(
                environment,
                run_id=str(owner.get("run_id")),
            )
        except ControlEvidenceError:
            return False
        return all(owner.get(name) == value for name, value in binding.items())

    def _paths(self, record: RunInfo) -> _ControlPaths:
        if not _RUN_ID_RE.fullmatch(record.run_id):
            raise SupervisedManagerError("run_id is not filesystem safe")
        run_dir = (self._control_root / record.run_id).resolve()
        if record.artifacts_dir:
            artifact_dir = Path(record.artifacts_dir).resolve()
            artifact_root = artifact_dir.parent
            if _paths_overlap(run_dir, artifact_root):
                raise SupervisedManagerError(
                    "parent control evidence must remain outside run artifacts"
                )
        return _ControlPaths(
            run_dir=run_dir,
            attempt_dir=run_dir / "attempts" / "attempt-0001",
            owner=run_dir / "owner.json",
            journal=run_dir / "manager-journal.jsonl",
            manager_terminal=run_dir / "manager-terminal.json",
            supervision_observed=run_dir / "supervision-observed.json",
            lock=run_dir / "manager.lock",
        )

    def _require_record(self, run_id: str) -> RunInfo:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise SupervisedManagerError("run_id is not filesystem safe")
        record = self._registry.get(run_id)
        if record is None:
            raise KeyError(run_id)
        return record

    @staticmethod
    def _validate_controller(controller: RuntimeController) -> None:
        if not callable(getattr(controller, "prepare", None)):
            raise TypeError("runtime controller must define prepare()")
        if not callable(getattr(controller, "cleanup", None)):
            raise TypeError("runtime controller must define cleanup()")
        classifier = getattr(controller, "classify_runtime_fault", None)
        if classifier is not None and not callable(classifier):
            raise TypeError(
                "runtime controller classify_runtime_fault must be callable"
            )

    @staticmethod
    def _validate_post_cleanup_controller(
        controller: PostCleanupController,
    ) -> None:
        if not callable(getattr(controller, "cleanup", None)):
            raise TypeError("post cleanup controller must define cleanup()")
        if not callable(getattr(controller, "reconcile", None)):
            raise TypeError("post cleanup controller must define reconcile()")

    @staticmethod
    def _validate_spec(
        spec: RunSpec,
        record: RunInfo,
        paths: _ControlPaths,
    ) -> None:
        if not isinstance(spec, RunSpec):
            raise TypeError("worker contract factory must return RunSpec")
        if spec.run_id != record.run_id:
            raise SupervisedManagerError("worker RunSpec run_id mismatch")
        if spec.artifact_dir.resolve() != paths.attempt_dir.resolve():
            raise SupervisedManagerError(
                "ProcessSupervisor evidence must use the parent control attempt dir"
            )
        if spec.runtime_cleanup_required is not True:
            raise SupervisedManagerError(
                "managed runtime RunSpec must require runtime cleanup proof"
            )
        try:
            _owner_environment_binding(
                spec.environment_identity,
                run_id=record.run_id,
            )
        except ControlEvidenceError as exc:
            raise SupervisedManagerError(
                "managed runtime RunSpec lacks canonical contract identity"
            ) from exc
        argv = list(spec.argv)
        if (
            len(argv) != 7
            or not Path(argv[0]).is_absolute()
            or argv[1:4] != ["-m", "fort_gym.bench.cli", "experiment"]
            or not Path(argv[4]).is_absolute()
        ):
            raise SupervisedManagerError(
                "worker command must use the exact recoverable Fort Gym module form"
            )
        if argv[5:] != ["--external-run-id", record.run_id]:
            raise SupervisedManagerError("worker command external run ID mismatch")

    @staticmethod
    def _validate_supervision_payload(
        payload: Mapping[str, Any],
        run_id: str,
    ) -> None:
        if payload.get("schema") != "fortgym.process-supervisor-terminal/v1":
            raise ControlEvidenceError("invalid supervisor terminal schema")
        if payload.get("run_id") != run_id:
            raise ControlEvidenceError("supervisor terminal run ID mismatch")
        cleanup = payload.get("cleanup")
        if not isinstance(cleanup, Mapping) or not isinstance(cleanup.get("ok"), bool):
            raise ControlEvidenceError(
                "supervisor terminal cleanup evidence is missing"
            )
        terminal_class = payload.get("terminal_class")
        if terminal_class in RUNTIME_FAULT_TERMINAL_CLASSES:
            reason = payload.get("reason")
            if not isinstance(reason, Mapping) or reason.get("code") != terminal_class:
                raise ControlEvidenceError(
                    "typed runtime fault reason must match its terminal class"
                )
            record = payload.get("fault_classification")
            if (
                not isinstance(record, Mapping)
                or record.get("schema") != FAULT_CLASSIFICATION_RECORD_SCHEMA
                or record.get("attempted") is not True
                or record.get("ok") is not True
                or record.get("classified") is not True
                or record.get("terminal_class") != terminal_class
                or not isinstance(record.get("evidence"), Mapping)
            ):
                raise ControlEvidenceError(
                    "typed runtime fault lacks validated classification evidence"
                )
            observation = {
                "schema": FAULT_OBSERVATION_SCHEMA,
                "run_id": run_id,
                "primary_terminal_class": payload.get("primary_terminal_class"),
                "primary_reason": payload.get("primary_reason"),
                "child_pid": payload.get("child_pid"),
                "returncode": payload.get("returncode"),
                "child_signal": payload.get("child_signal"),
                "environment_identity": payload.get("environment_identity") or {},
                "prepare": payload.get("prepare") or {},
                "termination": payload.get("termination") or {},
                "cleanup": cleanup,
            }
            classifier_result = {
                "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
                "terminal_class": terminal_class,
                "evidence": record["evidence"],
            }
            enospc_snapshot = None
            primary_reason = payload.get("primary_reason")
            if (
                terminal_class == "workspace_enospc"
                and payload.get("primary_terminal_class") == "cap_trip"
                and isinstance(primary_reason, Mapping)
                and primary_reason.get("code") == "trace_accounting_invalid"
            ):
                pre_cleanup = payload.get("pre_cleanup_evidence")
                identity = payload.get("environment_identity")
                provider = identity.get("provider") if isinstance(identity, Mapping) else None
                if (
                    not isinstance(pre_cleanup, Mapping)
                    or pre_cleanup.get("eligible") is not True
                    or pre_cleanup.get("error") is not None
                    or not isinstance(pre_cleanup.get("snapshot"), Mapping)
                    or not isinstance(identity, Mapping)
                    or identity.get("scripted") is not True
                    or not isinstance(provider, Mapping)
                    or provider.get("enabled") is not False
                ):
                    raise ControlEvidenceError("ENOSPC trace fault lacks bound scripted snapshot")
                enospc_snapshot = pre_cleanup["snapshot"]
                observation.update(scripted=True, provider_enabled=False)
            try:
                validate_fault_classifier_result(
                    classifier_result, observation, enospc_snapshot=enospc_snapshot,
                )
            except (FaultClassificationError, FaultSessionEvidenceError) as exc:
                raise ControlEvidenceError(
                    "typed runtime fault evidence is contradictory"
                ) from exc
        elif terminal_class == RUNTIME_FAULT_CLASSIFICATION_FAILURE:
            reason = payload.get("reason")
            record = payload.get("fault_classification")
            if not isinstance(reason, Mapping) or reason.get("code") != (
                RUNTIME_FAULT_CLASSIFICATION_FAILURE
            ):
                raise ControlEvidenceError(
                    "runtime fault classification failure reason is invalid"
                )
            if (
                not isinstance(record, Mapping)
                or record.get("schema") != FAULT_CLASSIFICATION_RECORD_SCHEMA
                or record.get("attempted") is not True
                or record.get("ok") is not False
                or record.get("classified") is not False
                or not isinstance(record.get("error"), Mapping)
            ):
                raise ControlEvidenceError(
                    "runtime fault classification failure evidence is invalid"
                )

    @staticmethod
    def _validate_provider_network_supervision(
        payload: Mapping[str, Any],
        expected: ProviderNetworkLaunchPlan,
    ) -> None:
        record = payload.get("provider_network")
        if not isinstance(record, Mapping) or record.get("enabled") is not True:
            raise ControlEvidenceError(
                "explicit provider-network run lacks terminal evidence"
            )
        launch = record.get("launch")
        if not isinstance(launch, Mapping) or _json_mapping(launch) != _json_mapping(
            expected.evidence
        ):
            raise ControlEvidenceError(
                "provider-network terminal launch identity differs"
            )
        prepare = record.get("prepare")
        child_pid = _optional_int(payload.get("child_pid"))
        if child_pid is not None:
            validation = record.get("validation")
            if (
                not isinstance(prepare, Mapping)
                or prepare.get("ok") is not True
                or record.get("prepare_completed") is not True
                or not isinstance(validation, Mapping)
                or validation.get("ok") is not True
                or validation.get("identity_sha256")
                != launch.get("provider_network_identity", {}).get("identity_sha256")
            ):
                raise ControlEvidenceError(
                    "launched provider-network run lacks final validation"
                )

    @staticmethod
    def _validate_manager_terminal(
        payload: Mapping[str, Any],
        run_id: str,
    ) -> None:
        if payload.get("schema") != "fortgym.supervised-manager-terminal/v1":
            raise ControlEvidenceError("invalid manager terminal schema")
        if payload.get("run_id") != run_id:
            raise ControlEvidenceError("manager terminal run ID mismatch")

    @staticmethod
    def _validate_owner(payload: Mapping[str, Any], run_id: str) -> None:
        if set(payload) != {
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
        }:
            raise ControlEvidenceError("manager owner keyset differs")
        if payload.get("schema") != "fortgym.supervised-manager-owner/v1":
            raise ControlEvidenceError("invalid manager owner schema")
        if payload.get("run_id") != run_id:
            raise ControlEvidenceError("manager owner run ID mismatch")
        manager_pid = _optional_int(payload.get("manager_pid"))
        if manager_pid is None or manager_pid <= 0:
            raise ControlEvidenceError("manager owner PID is invalid")
        manager_start_ticks = _optional_int(payload.get("manager_start_ticks"))
        if manager_start_ticks is None or manager_start_ticks <= 0:
            raise ControlEvidenceError("manager owner start time is invalid")
        if payload.get("state") not in {"active", "supervision_finished"}:
            raise ControlEvidenceError("manager owner state is invalid")
        if not isinstance(payload.get("observed_registry_status"), str):
            raise ControlEvidenceError("manager owner registry status is invalid")
        if not isinstance(payload.get("attempt_dir"), str) or not isinstance(
            payload.get("updated_at"), str
        ):
            raise ControlEvidenceError("manager owner path or timestamp is invalid")
        identity_bound = payload.get("identity_bound")
        if not isinstance(identity_bound, bool):
            raise ControlEvidenceError("manager owner identity state is invalid")
        identity_values = (
            payload.get("contract_sha256"),
            payload.get("nonce_sha256"),
            payload.get("environment_identity_sha256"),
        )
        if identity_bound:
            if any(
                not isinstance(value, str) or not _SHA256_RE.fullmatch(value)
                for value in identity_values
            ):
                raise ControlEvidenceError("manager owner identity binding is invalid")
        elif any(value is not None for value in identity_values):
            raise ControlEvidenceError("unbound manager owner carries identity")

    @staticmethod
    def _has_prior_attempt(paths: _ControlPaths) -> bool:
        return any(
            path.exists()
            for path in (
                paths.owner,
                paths.manager_terminal,
                paths.supervision_observed,
                paths.attempt_dir,
            )
        )


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if fcntl is None:
            raise ActiveRunOwnershipError("POSIX file locks are required")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ActiveRunOwnershipError(
                f"another manager owns control lock: {path}"
            ) from exc
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


def _owner_environment_binding(
    environment: Mapping[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    if environment.get("run_id") != run_id:
        raise ControlEvidenceError("manager owner environment run ID differs")
    contract_sha256 = environment.get("contract_sha256")
    rpc = environment.get("rpc")
    nonce = rpc.get("nonce") if isinstance(rpc, Mapping) else None
    if (
        not isinstance(contract_sha256, str)
        or not _SHA256_RE.fullmatch(contract_sha256)
        or not isinstance(nonce, str)
        or not _NONCE_RE.fullmatch(nonce)
    ):
        raise ControlEvidenceError("manager owner contract identity is invalid")
    return {
        "identity_bound": True,
        "contract_sha256": contract_sha256,
        "nonce_sha256": hashlib.sha256(nonce.encode("ascii")).hexdigest(),
        "environment_identity_sha256": _canonical_payload_sha256(environment),
    }


def _canonical_payload_sha256(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _linux_process_start_ticks(pid: int) -> int:
    if not sys.platform.startswith("linux"):
        raise OSError("Linux procfs is required for process start-time identity")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise OSError("process identity PID is invalid")
    descriptor = os.open(
        Path("/proc") / str(pid) / "stat",
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        raw = os.read(descriptor, 16 * 1024)
        if not raw or len(raw) >= 16 * 1024:
            raise OSError("process stat evidence is empty or oversized")
    finally:
        os.close(descriptor)
    try:
        text = raw.decode("ascii")
        close = text.rindex(")")
        fields = text[close + 2 :].split()
        start_ticks = int(fields[19])
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise OSError("process stat evidence is malformed") from exc
    if start_ticks <= 0:
        raise OSError("process start time is invalid")
    return start_ticks


def _current_process_start_ticks() -> int:
    if sys.platform.startswith("linux"):
        return _linux_process_start_ticks(os.getpid())
    # This evidence is never used as a security decision off Linux. Keeping a
    # stable positive process-lifetime token preserves portable unit tests.
    return time.monotonic_ns()


def _owner_pid_is_live(owner: Mapping[str, Any]) -> bool:
    pid = _optional_int(owner.get("manager_pid"))
    start_ticks = _optional_int(owner.get("manager_start_ticks"))
    if (
        pid is None
        or pid <= 0
        or start_ticks is None
        or start_ticks <= 0
        or owner.get("identity_bound") is not True
    ):
        return False
    if not sys.platform.startswith("linux"):
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        return True
    try:
        if _linux_process_start_ticks(pid) != start_ticks:
            return False
        os.kill(pid, 0)
        if _linux_process_start_ticks(pid) != start_ticks:
            return False
    except (OSError, ProcessLookupError, PermissionError):
        return False
    return True


def _owner_attempt_dir(
    owner: Mapping[str, Any] | None,
    paths: _ControlPaths,
) -> Path:
    if owner is None or not isinstance(owner.get("attempt_dir"), str):
        return paths.attempt_dir
    candidate = Path(str(owner["attempt_dir"])).resolve()
    if candidate != paths.attempt_dir.resolve():
        raise ControlEvidenceError("owner attempt path does not match canonical path")
    return candidate


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _staged_reason(record: RunInfo) -> dict[str, Any] | None:
    value = record.metadata.get("terminal_reason")
    return dict(value) if isinstance(value, Mapping) else None


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _required_positive_int(value: Any, label: str) -> int:
    resolved = _optional_int(value)
    if resolved is None or resolved <= 0:
        raise ControlEvidenceError(f"{label} is invalid")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_error(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": " ".join(str(exc).split())[:400],
    }


def _iso(value: datetime) -> str:
    resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return _json_safe(value.value)
    return repr(value)


def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    safe = _json_safe(value)
    if not isinstance(safe, dict):  # pragma: no cover - Mapping always converts
        raise TypeError("expected JSON mapping")
    return safe


def _validate_runtime_reconciliation_evidence(
    evidence: Mapping[str, Any],
) -> None:
    """Reject incomplete cleanup claims before they enter a recovered terminal."""

    expected_keys = {
        "schema",
        "ok",
        "managed_candidates",
        "removed_container_ids",
        "skipped_foreign_container_ids",
        "listener_absent",
        "noop",
        "errors",
    }
    if set(evidence) != expected_keys:
        raise ControlEvidenceError("runtime reconciliation keyset is noncanonical")
    candidates = evidence.get("managed_candidates")
    removed = evidence.get("removed_container_ids")
    skipped = evidence.get("skipped_foreign_container_ids")
    errors = evidence.get("errors")
    identifier_re = re.compile(r"^[a-f0-9]{12,64}$")
    if (
        evidence.get("schema") != "fortgym.m1b-runtime-reconcile/v1"
        or not isinstance(evidence.get("ok"), bool)
        or isinstance(candidates, bool)
        or not isinstance(candidates, int)
        or candidates < 0
        or not isinstance(removed, list)
        or not isinstance(skipped, list)
        or not isinstance(errors, list)
        or not isinstance(evidence.get("listener_absent"), bool)
        or not isinstance(evidence.get("noop"), bool)
        or any(
            not isinstance(identifier, str)
            or not identifier_re.fullmatch(identifier)
            for identifier in (*removed, *skipped)
        )
        or len({*removed, *skipped}) != len(removed) + len(skipped)
        or candidates != len(removed) + len(skipped)
        or evidence.get("noop") is not (not removed)
    ):
        raise ControlEvidenceError("runtime reconciliation evidence is malformed")
    if evidence.get("ok") is True and (
        errors != [] or evidence.get("listener_absent") is not True
    ):
        raise ControlEvidenceError("runtime reconciliation success is contradictory")


def _atomic_replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(
                _json_safe(payload), handle, sort_keys=True, separators=(",", ":")
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _write_once_or_verify(
    path: Path,
    payload: Mapping[str, Any],
    run_id: str,
) -> None:
    existing = _read_optional_mapping(path)
    if existing is not None:
        if existing.get("run_id") != run_id:
            raise ControlEvidenceError("manager terminal belongs to another run")
        if existing.get("status") != payload.get("status"):
            raise ControlEvidenceError("manager terminal status is contradictory")
        if existing.get("returncode") != payload.get("returncode"):
            raise ControlEvidenceError("manager terminal return code is contradictory")
        return
    _atomic_replace_json(path, payload)


def _append_journal(path: Path, event: str, **fields: Any) -> None:
    payload = {
        "schema": "fortgym.supervised-manager-journal/v1",
        "at": _iso(datetime.now(UTC)),
        "manager_pid": os.getpid(),
        "event": event,
        **fields,
    }
    encoded = (
        json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("short manager journal append")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_optional_mapping(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ControlEvidenceError(f"invalid JSON control evidence: {path}") from exc
    if not isinstance(value, dict):
        raise ControlEvidenceError(f"control evidence must be an object: {path}")
    return value


def _read_journal_records(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ControlEvidenceError(f"invalid supervisor journal: {path}") from exc
        if not isinstance(value, Mapping) or not isinstance(value.get("event"), str):
            raise ControlEvidenceError(f"invalid supervisor journal row: {path}")
        records.append(dict(value))
    return records


def _read_journal_events(path: Path) -> list[str]:
    return [str(record["event"]) for record in _read_journal_records(path)]


def _validated_provider_network_launch(
    value: Any,
    *,
    run_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ControlEvidenceError("provider-network launch evidence is missing")
    launch = dict(value)
    expected_keys = {
        "schema",
        "mode",
        "run_id",
        "provider_network_identity",
        "helper",
        "inner_argv",
        "inner_argv_sha256",
        "wrapper_argv",
        "wrapper_argv_sha256",
        "python_guard",
    }
    if (
        set(launch) != expected_keys
        or launch.get("schema") != "fortgym.provider-network-launch/v1"
        or launch.get("mode") != "cgroup-bpf-join-before-exec"
        or launch.get("run_id") != run_id
    ):
        raise ControlEvidenceError("provider-network launch evidence is noncanonical")

    inner_raw = launch.get("inner_argv")
    wrapper_raw = launch.get("wrapper_argv")
    if (
        not isinstance(inner_raw, Sequence)
        or isinstance(inner_raw, (str, bytes))
        or not all(isinstance(item, str) and "\0" not in item for item in inner_raw)
        or not isinstance(wrapper_raw, Sequence)
        or isinstance(wrapper_raw, (str, bytes))
        or not all(isinstance(item, str) and "\0" not in item for item in wrapper_raw)
    ):
        raise ControlEvidenceError("provider-network launch argv is invalid")
    inner = tuple(inner_raw)
    wrapper = tuple(wrapper_raw)
    if (
        len(inner) != 7
        or not Path(inner[0]).is_absolute()
        or inner[1:4] != ("-m", "fort_gym.bench.cli", "experiment")
        or not Path(inner[4]).is_absolute()
        or inner[5:] != ("--external-run-id", run_id)
        or launch.get("inner_argv_sha256") != canonical_argv_sha256(inner)
        or launch.get("wrapper_argv_sha256") != canonical_argv_sha256(wrapper)
    ):
        raise ControlEvidenceError(
            "provider-network canonical inner or wrapper argv is contradictory"
        )

    helper = launch.get("helper")
    identity = launch.get("provider_network_identity")
    guard = launch.get("python_guard")
    if not isinstance(helper, Mapping) or set(helper) != {"path", "sha256"}:
        raise ControlEvidenceError("provider-network helper identity is invalid")
    helper_path = helper.get("path")
    helper_sha256 = helper.get("sha256")
    if (
        not isinstance(helper_path, str)
        or not Path(helper_path).is_absolute()
        or not isinstance(helper_sha256, str)
        or not _SHA256_RE.fullmatch(helper_sha256)
    ):
        raise ControlEvidenceError("provider-network helper pin is invalid")
    if not isinstance(identity, Mapping):
        raise ControlEvidenceError("provider-network public identity is invalid")
    identity_sha256 = identity.get("identity_sha256")
    if (
        identity.get("schema") != "fortgym.provider-network-manifest/v1"
        or identity.get("integration_status") != "process-supervisor-atomic-wrapper-v1"
        or identity.get("run_id") != run_id
        or not isinstance(identity_sha256, str)
        or not _SHA256_RE.fullmatch(identity_sha256)
        or identity.get("assigned_host") != "127.0.0.1"
        or not isinstance(identity.get("assigned_port"), int)
        or identity.get("nonce_matched") is not True
        or "nonce" in identity
    ):
        raise ControlEvidenceError("provider-network public identity is contradictory")
    if not isinstance(guard, Mapping) or set(guard) != {
        "policy",
        "allowed_host",
        "allowed_port",
        "evidence_path_sha256",
        "run_id",
        "contract_sha256",
        "nonce_matched",
    }:
        raise ControlEvidenceError("provider-network guard identity is invalid")
    if (
        guard.get("policy") != "loopback-port-only"
        or guard.get("allowed_host") != "127.0.0.1"
        or guard.get("allowed_port") != identity.get("assigned_port")
        or guard.get("run_id") != run_id
        or guard.get("contract_sha256") != identity.get("contract_sha256")
        or guard.get("nonce_matched") is not True
        or not isinstance(guard.get("evidence_path_sha256"), str)
        or not _SHA256_RE.fullmatch(str(guard["evidence_path_sha256"]))
    ):
        raise ControlEvidenceError("provider-network guard identity is contradictory")

    delimiter_indexes = [index for index, item in enumerate(wrapper) if item == "--"]
    if len(delimiter_indexes) != 1:
        raise ControlEvidenceError("provider-network wrapper delimiter is invalid")
    delimiter = delimiter_indexes[0]
    expected_prefix = (
        helper_path,
        "enter",
        "--cgroup",
    )
    if (
        wrapper[:3] != expected_prefix
        or delimiter != 10
        or len(wrapper) <= delimiter + 1
        or not Path(wrapper[3]).is_absolute()
        or wrapper[4:6] != ("--identity-sha256", identity_sha256)
        or wrapper[6:8] != ("--require-python-policy", "loopback-port-only")
        or wrapper[8] != "--guard-attestation"
        or not Path(wrapper[9]).is_absolute()
        or wrapper[delimiter + 1 :] != inner
    ):
        raise ControlEvidenceError("provider-network wrapper command is contradictory")
    return launch


def _provider_network_launch_from_journal(
    records: list[dict[str, Any]],
    run_id: str,
    *,
    owner_manager_pid: int,
) -> _ProviderNetworkJournalEvidence | None:
    started = [
        row for row in records if row.get("event") == "provider_network_prepare_started"
    ]
    prepared = [
        row for row in records if row.get("event") == "provider_network_prepared"
    ]
    intended = [
        row for row in records if row.get("event") == "provider_network_launch_intent"
    ]
    if not started:
        if prepared or intended:
            raise ControlEvidenceError(
                "provider-network launch row lacks a prepare-started identity"
            )
        return None
    if len(started) != 1 or len(prepared) > 1 or len(intended) > 1:
        raise ControlEvidenceError("provider-network launch journal is ambiguous")
    start = started[0]
    if (
        start.get("schema") != "fortgym.process-supervisor-attempt/v1"
        or start.get("run_id") != run_id
        or _required_positive_int(start.get("supervisor_pid"), "supervisor PID")
        != owner_manager_pid
    ):
        raise ControlEvidenceError("provider-network prepare journal identity mismatch")
    launch = _validated_provider_network_launch(start.get("launch"), run_id=run_id)
    if prepared:
        row = prepared[0]
        identity = launch["provider_network_identity"]
        if not isinstance(identity, Mapping):
            raise ControlEvidenceError(
                "provider-network prepared identity is unavailable"
            )
        if (
            row.get("schema") != "fortgym.process-supervisor-attempt/v1"
            or row.get("run_id") != run_id
            or _required_positive_int(row.get("supervisor_pid"), "supervisor PID")
            != owner_manager_pid
            or row.get("launch_argv_sha256") != launch["wrapper_argv_sha256"]
            or row.get("inner_argv_sha256") != launch["inner_argv_sha256"]
            or row.get("provider_network_identity_sha256")
            != identity["identity_sha256"]
        ):
            raise ControlEvidenceError(
                "provider-network prepared journal identity mismatch"
            )
    if intended:
        if not prepared:
            raise ControlEvidenceError(
                "provider-network launch intent lacks completed prepare evidence"
            )
        row = intended[0]
        identity = launch["provider_network_identity"]
        if not isinstance(identity, Mapping):
            raise ControlEvidenceError(
                "provider-network launch-intent identity is unavailable"
            )
        attempt_rows = [
            item for item in records if item.get("event") == "attempt_started"
        ]
        if len(attempt_rows) != 1:
            raise ControlEvidenceError(
                "provider-network launch intent lacks one attempt identity"
            )
        environment_identity = attempt_rows[0].get("environment_identity")
        rpc = (
            environment_identity.get("rpc")
            if isinstance(environment_identity, Mapping)
            else None
        )
        nonce = rpc.get("nonce") if isinstance(rpc, Mapping) else None
        if (
            row.get("schema") != "fortgym.process-supervisor-attempt/v1"
            or row.get("run_id") != run_id
            or _required_positive_int(row.get("supervisor_pid"), "supervisor PID")
            != owner_manager_pid
            or row.get("launch_argv_sha256") != launch["wrapper_argv_sha256"]
            or row.get("inner_argv_sha256") != launch["inner_argv_sha256"]
            or row.get("provider_network_identity_sha256")
            != identity["identity_sha256"]
            or row.get("contract_sha256") != identity["contract_sha256"]
            or not isinstance(nonce, str)
            or row.get("nonce_sha256")
            != hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        ):
            raise ControlEvidenceError(
                "provider-network launch intent identity mismatch"
            )
    return _ProviderNetworkJournalEvidence(
        launch=launch,
        prepared=bool(prepared),
        launch_intended=bool(intended),
    )


def _child_identity_from_journal(
    records: list[dict[str, Any]],
    run_id: str,
    *,
    owner_manager_pid: int,
    provider_network: _ProviderNetworkJournalEvidence | None = None,
) -> _ExpectedChildIdentity | None:
    child_rows = [
        record for record in records if record.get("event") == "child_started"
    ]
    if not child_rows:
        return None
    if len(child_rows) != 1:
        raise ControlEvidenceError("supervisor journal has multiple child_started rows")
    attempt_rows = [
        record for record in records if record.get("event") == "attempt_started"
    ]
    if len(attempt_rows) != 1:
        raise ControlEvidenceError(
            "supervisor journal must have exactly one attempt_started row"
        )

    attempt = attempt_rows[0]
    child = child_rows[0]
    for row, label in ((attempt, "attempt_started"), (child, "child_started")):
        if row.get("schema") != "fortgym.process-supervisor-attempt/v1":
            raise ControlEvidenceError(f"{label} journal schema is invalid")
        if row.get("run_id") != run_id:
            raise ControlEvidenceError(f"{label} journal run ID mismatch")
        if (
            _required_positive_int(row.get("supervisor_pid"), "supervisor PID")
            != owner_manager_pid
        ):
            raise ControlEvidenceError(
                f"{label} supervisor PID does not match manager owner"
            )

    environment_identity = attempt.get("environment_identity")
    if not isinstance(environment_identity, Mapping):
        raise ControlEvidenceError(
            "attempt_started is missing durable environment identity"
        )
    if environment_identity.get("run_id") != run_id:
        raise ControlEvidenceError("durable environment run ID mismatch")
    contract_sha256 = environment_identity.get("contract_sha256")
    if not isinstance(contract_sha256, str) or not _SHA256_RE.fullmatch(
        contract_sha256
    ):
        raise ControlEvidenceError("durable contract SHA-256 is invalid")
    rpc = environment_identity.get("rpc")
    if not isinstance(rpc, Mapping):
        raise ControlEvidenceError("durable environment RPC identity is missing")
    nonce = rpc.get("nonce")
    if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
        raise ControlEvidenceError("durable runtime nonce is invalid")

    provider_network_launch: Mapping[str, Any] | None = None
    provider_child_fields = {
        "launch_mode",
        "launch_argv_sha256",
        "inner_argv_sha256",
        "provider_network_identity_sha256",
    }
    if provider_network is not None:
        if not provider_network.prepared or not provider_network.launch_intended:
            raise ControlEvidenceError(
                "provider-network child started without prepared launch intent"
            )
        provider_network_launch = provider_network.launch
        identity = provider_network_launch["provider_network_identity"]
        guard = provider_network_launch["python_guard"]
        if not isinstance(identity, Mapping) or not isinstance(guard, Mapping):
            raise ControlEvidenceError(
                "provider-network child identity or guard is unavailable"
            )
        if (
            identity.get("contract_sha256") != contract_sha256
            or identity.get("assigned_port") != rpc.get("port")
            or guard.get("contract_sha256") != contract_sha256
            or child.get("launch_mode") != "cgroup-bpf-join-before-exec"
            or child.get("launch_argv_sha256")
            != provider_network_launch["wrapper_argv_sha256"]
            or child.get("inner_argv_sha256")
            != provider_network_launch["inner_argv_sha256"]
            or child.get("provider_network_identity_sha256")
            != identity.get("identity_sha256")
        ):
            raise ControlEvidenceError(
                "provider-network child journal identity is contradictory"
            )
    elif any(name in child for name in provider_child_fields):
        raise ControlEvidenceError(
            "direct child journal contains partial provider-network identity"
        )

    child_pid = _required_positive_int(child.get("child_pid"), "child_started PID")
    if child_pid <= 1:
        raise ControlEvidenceError("child_started journal PID is invalid")
    return _ExpectedChildIdentity(
        child_pid=child_pid,
        run_id=run_id,
        contract_sha256=contract_sha256,
        nonce=nonce,
        provider_network_launch=provider_network_launch,
    )


def _reap_process_group(
    expected: _ExpectedChildIdentity | None,
    *,
    identity_probe: ProcessIdentityProbe,
) -> dict[str, Any]:
    if expected is None:
        return {
            "ok": True,
            "skipped": True,
            "reason": "child_not_started",
        }
    child_pid = expected.child_pid
    try:
        process_group_id = os.getpgid(child_pid)
    except ProcessLookupError:
        return {
            "ok": True,
            "child_pid": child_pid,
            "already_absent": True,
            "term_sent": False,
            "kill_sent": False,
            "reaped": False,
        }
    if process_group_id != child_pid:
        raise ControlEvidenceError(
            "journal child PID is not the leader of its process group"
        )

    verified_identity = _verify_live_process_identity(
        expected,
        identity_probe=identity_probe,
    )
    try:
        confirmed_process_group_id = os.getpgid(child_pid)
    except ProcessLookupError:
        return {
            "ok": True,
            "child_pid": child_pid,
            "already_absent": True,
            "identity": verified_identity,
            "term_sent": False,
            "kill_sent": False,
            "reaped": False,
        }
    if confirmed_process_group_id != process_group_id:
        raise ControlEvidenceError(
            "child process-group identity changed after live identity verification"
        )

    result: dict[str, Any] = {
        "ok": False,
        "child_pid": child_pid,
        "process_group_id": process_group_id,
        "identity": verified_identity,
        "term_sent": False,
        "kill_sent": False,
        "reaped": False,
    }
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        result.update({"ok": True, "absent": True})
        return result
    result["term_sent"] = True
    if _wait_for_process_group_exit(
        process_group_id, child_pid, timeout=0.5, result=result
    ):
        result["ok"] = True
        return result

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        result.update({"ok": True, "absent": True})
        return result
    result["kill_sent"] = True
    if _wait_for_process_group_exit(
        process_group_id, child_pid, timeout=1.0, result=result
    ):
        result["ok"] = True
        return result
    result["error"] = {
        "type": "ProcessGroupStillAlive",
        "message": "orphan harness process group survived SIGKILL",
    }
    return result


def _reap_provider_network_launch_intent(
    *,
    records: Sequence[Mapping[str, Any]],
    run_id: str,
    provider_network: _ProviderNetworkJournalEvidence,
    controller: ProviderNetworkController,
    process_ids_probe: ProcessIdsProbe,
    identity_probe: ProcessIdentityProbe,
    process_group_probe: ProcessGroupProbe,
) -> dict[str, Any]:
    """Reap one exact wrapper/inner process when Popen outran child journaling."""

    if not provider_network.launch_intended:
        raise ControlEvidenceError("provider-network launch intent is absent")
    attempt_rows = [row for row in records if row.get("event") == "attempt_started"]
    if len(attempt_rows) != 1:
        raise ControlEvidenceError("launch-intent recovery lacks one attempt identity")
    environment_identity = attempt_rows[0].get("environment_identity")
    rpc = (
        environment_identity.get("rpc")
        if isinstance(environment_identity, Mapping)
        else None
    )
    contract_sha256 = (
        environment_identity.get("contract_sha256")
        if isinstance(environment_identity, Mapping)
        else None
    )
    nonce = rpc.get("nonce") if isinstance(rpc, Mapping) else None
    launch_identity = provider_network.launch.get("provider_network_identity")
    if (
        not isinstance(launch_identity, Mapping)
        or launch_identity.get("run_id") != run_id
        or contract_sha256 != launch_identity.get("contract_sha256")
        or not isinstance(contract_sha256, str)
        or not _SHA256_RE.fullmatch(contract_sha256)
        or not isinstance(nonce, str)
        or not _NONCE_RE.fullmatch(nonce)
    ):
        raise ControlEvidenceError("launch-intent private identity is invalid")

    raw_residue = controller.residue()
    if not isinstance(raw_residue, Mapping):
        raise ControlEvidenceError("provider-network residue report is unavailable")
    residue_identity = raw_residue.get("identity")
    residue = raw_residue.get("residue")
    member_pids = residue.get("member_pids") if isinstance(residue, Mapping) else None
    if (
        raw_residue.get("schema") != "fortgym.provider-network-inspect/v1"
        or raw_residue.get("foreign_canary_untouched") is not True
        or not isinstance(residue_identity, Mapping)
        or dict(residue_identity) != dict(launch_identity)
        or not isinstance(residue, Mapping)
        or residue.get("cgroup_exists") is not True
        or residue.get("pins_exist") is not True
        or not isinstance(member_pids, list)
        or len(set(member_pids)) != len(member_pids)
        or any(
            isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1
            for pid in member_pids
        )
    ):
        raise ControlEvidenceError(
            "provider-network launch-intent residue identity is contradictory"
        )

    try:
        raw_process_ids = tuple(process_ids_probe())
    except Exception as exc:
        raise ControlEvidenceError(
            "provider-network launch-intent process enumeration failed"
        ) from exc
    if (
        len(raw_process_ids) > 1_000_000
        or len(set(raw_process_ids)) != len(raw_process_ids)
        or any(
            isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1
            for pid in raw_process_ids
        )
    ):
        raise ControlEvidenceError(
            "provider-network launch-intent process enumeration is invalid"
        )
    candidate_pids = set(raw_process_ids) | set(member_pids)
    observed_processes: dict[int, Mapping[str, Any]] = {}
    for pid in sorted(candidate_pids):
        try:
            observed = identity_probe(pid)
        except (FileNotFoundError, ProcessLookupError, KeyError):
            if pid in member_pids:
                raise ControlEvidenceError(
                    "provider-network cgroup member vanished before verification"
                ) from None
            continue
        except PermissionError:
            if pid in member_pids:
                raise ControlEvidenceError(
                    "provider-network cgroup member identity is unreadable"
                ) from None
            continue
        if not isinstance(observed, Mapping):
            if pid in member_pids:
                raise ControlEvidenceError(
                    "provider-network cgroup member identity is malformed"
                )
            continue
        observed_processes[pid] = observed

    def exact_run_environment(observed: Mapping[str, Any]) -> bool:
        environment = observed.get("environment")
        return bool(
            isinstance(environment, Mapping)
            and environment.get("FORT_GYM_RUN_ID") == run_id
            and environment.get("FORT_GYM_RUN_CONTRACT_SHA256") == contract_sha256
            and environment.get("FORT_GYM_RUN_NONCE") == nonce
        )

    if any(
        pid not in observed_processes
        or not exact_run_environment(observed_processes[pid])
        for pid in member_pids
    ):
        raise ControlEvidenceError(
            "provider-network cgroup contains a foreign or contradictory process"
        )

    canonical: dict[int, Mapping[str, Any]] = {}
    for pid in member_pids:
        observed = observed_processes[pid]
        expected = _ExpectedChildIdentity(
            child_pid=pid,
            run_id=run_id,
            contract_sha256=contract_sha256,
            nonce=nonce,
            provider_network_launch=provider_network.launch,
        )
        try:
            canonical[pid] = _verify_live_process_identity(
                expected,
                identity_probe=lambda _pid, value=observed: value,
            )
        except ControlEvidenceError:
            # A post-exec descendant may have any command, but it remains
            # bounded below by the exact private run identity and process group.
            continue

    exact_run_pids = {
        pid
        for pid, observed in observed_processes.items()
        if exact_run_environment(observed)
    }
    if not member_pids and not exact_run_pids:
        return {
            "ok": True,
            "skipped": True,
            "reason": "launch_intent_has_no_live_owned_process",
            "cgroup_member_pids": [],
            "intent_process_reaped": False,
        }
    if len(canonical) != 1:
        raise ControlEvidenceError(
            "provider-network launch intent requires one canonical cgroup leader"
        )
    child_pid = next(iter(canonical))
    try:
        leader_group = process_group_probe(child_pid)
    except (OSError, KeyError) as exc:
        raise ControlEvidenceError(
            "provider-network canonical leader process group is unavailable"
        ) from exc
    if leader_group != child_pid:
        raise ControlEvidenceError(
            "provider-network canonical process is not its process-group leader"
        )
    for pid in member_pids:
        try:
            observed_group = process_group_probe(pid)
        except (OSError, KeyError) as exc:
            raise ControlEvidenceError(
                "provider-network cgroup member process group is unavailable"
            ) from exc
        if observed_group != child_pid:
            raise ControlEvidenceError(
                "provider-network cgroup contains a different process group"
            )

    outside_cgroup = sorted(exact_run_pids - set(member_pids))
    for pid in outside_cgroup:
        expected = _ExpectedChildIdentity(
            child_pid=pid,
            run_id=run_id,
            contract_sha256=contract_sha256,
            nonce=nonce,
            provider_network_launch=provider_network.launch,
        )
        try:
            _verify_live_process_identity(
                expected,
                identity_probe=lambda _pid, value=observed_processes[pid]: value,
            )
        except ControlEvidenceError:
            pass
        else:
            raise ControlEvidenceError(
                "provider-network canonical wrapper exists outside its cgroup"
            )
        try:
            observed_group = process_group_probe(pid)
        except (OSError, KeyError) as exc:
            raise ControlEvidenceError(
                "run-owned process outside provider cgroup is unreadable"
            ) from exc
        if observed_group != child_pid:
            raise ControlEvidenceError(
                "run-owned process escaped the canonical process group"
            )
    reaped = _reap_process_group(
        _ExpectedChildIdentity(
            child_pid=child_pid,
            run_id=run_id,
            contract_sha256=contract_sha256,
            nonce=nonce,
            provider_network_launch=provider_network.launch,
        ),
        identity_probe=identity_probe,
    )
    if reaped.get("ok") is not True:
        raise ControlEvidenceError(
            "provider-network launch-intent process group was not reaped"
        )
    after = controller.residue()
    after_residue = after.get("residue") if isinstance(after, Mapping) else None
    if (
        not isinstance(after, Mapping)
        or after.get("foreign_canary_untouched") is not True
        or not isinstance(after_residue, Mapping)
        or after_residue.get("member_pids") != []
    ):
        raise ControlEvidenceError(
            "provider-network launch-intent cgroup remains occupied after reap"
        )
    return {
        "ok": True,
        "intent_process_reaped": True,
        "child_pid": child_pid,
        "command_mode": canonical[child_pid]["command"]["mode"],
        "cgroup_member_pids": list(member_pids),
        "additional_group_member_pids": sorted(set(member_pids) - {child_pid}),
        "same_group_outside_cgroup_pids": outside_cgroup,
        "identity": canonical[child_pid],
        "reap": reaped,
        "foreign_canary_untouched": True,
    }


def _verify_live_process_identity(
    expected: _ExpectedChildIdentity,
    *,
    identity_probe: ProcessIdentityProbe,
) -> dict[str, Any]:
    try:
        observed = identity_probe(expected.child_pid)
    except Exception as exc:
        raise ControlEvidenceError(
            f"live child identity probe unavailable ({type(exc).__name__})"
        ) from exc
    if not isinstance(observed, Mapping):
        raise ControlEvidenceError(
            "live child identity probe returned invalid evidence"
        )

    raw_cmdline = observed.get("cmdline")
    if (
        not isinstance(raw_cmdline, Sequence)
        or isinstance(raw_cmdline, (str, bytes))
        or not all(isinstance(item, str) for item in raw_cmdline)
    ):
        raise ControlEvidenceError("live child command identity is unavailable")
    cmdline = tuple(raw_cmdline)
    provider_network = expected.provider_network_launch
    command_mode = "direct"
    if provider_network is None:
        if (
            len(cmdline) != 7
            or not cmdline[0]
            or cmdline[1:4] != ("-m", "fort_gym.bench.cli", "experiment")
            or not cmdline[4]
            or cmdline[4].startswith("-")
        ):
            raise ControlEvidenceError(
                "live child command is not the Fort Gym experiment worker"
            )
        if cmdline[5:] != ("--external-run-id", expected.run_id):
            raise ControlEvidenceError("live child command external run ID mismatch")
    else:
        inner = tuple(str(item) for item in provider_network["inner_argv"])
        wrapper = tuple(str(item) for item in provider_network["wrapper_argv"])
        helper = provider_network["helper"]
        if not isinstance(helper, Mapping):
            raise ControlEvidenceError("provider-network helper identity is unavailable")
        helper_path = Path(str(helper["path"]))
        helper_sha256 = str(helper["sha256"])
        try:
            current_helper_sha256 = _sha256_file(helper_path)
        except OSError as exc:
            raise ControlEvidenceError(
                "pinned provider-network wrapper is unavailable"
            ) from exc
        if current_helper_sha256 != helper_sha256:
            raise ControlEvidenceError("pinned provider-network wrapper digest changed")
        if cmdline == inner:
            command_mode = "provider_network_inner_exec"
        elif cmdline == wrapper:
            command_mode = "provider_network_wrapper_pre_exec"
            observed_executable = observed.get("executable_path")
            observed_sha256 = observed.get("executable_sha256")
            if (
                not isinstance(observed_executable, str)
                or Path(observed_executable).resolve() != helper_path.resolve()
                or observed_sha256 != helper_sha256
            ):
                raise ControlEvidenceError(
                    "live provider-network wrapper executable is not pinned"
                )
        else:
            raise ControlEvidenceError(
                "live child command differs from wrapper and canonical inner argv"
            )

    environment = observed.get("environment")
    if not isinstance(environment, Mapping):
        raise ControlEvidenceError("live child environment identity is unavailable")
    expected_environment = {
        "FORT_GYM_RUN_ID": expected.run_id,
        "FORT_GYM_RUN_CONTRACT_SHA256": expected.contract_sha256,
        "FORT_GYM_RUN_NONCE": expected.nonce,
    }
    for name, value in expected_environment.items():
        if environment.get(name) != value:
            raise ControlEvidenceError(f"live child environment mismatch for {name}")

    provider_network_result: dict[str, Any] | None = None
    if provider_network is not None:
        guard = provider_network["python_guard"]
        identity = provider_network["provider_network_identity"]
        if not isinstance(guard, Mapping) or not isinstance(identity, Mapping):
            raise ControlEvidenceError(
                "provider-network live identity or guard is unavailable"
            )
        expected_network_environment = {
            "FORT_GYM_NETWORK_POLICY": guard["policy"],
            "FORT_GYM_NETWORK_ALLOWED_HOST": guard["allowed_host"],
            "FORT_GYM_NETWORK_ALLOWED_PORT": str(guard["allowed_port"]),
        }
        for name, value in expected_network_environment.items():
            if environment.get(name) != value:
                raise ControlEvidenceError(
                    f"live child provider-network environment mismatch for {name}"
                )
        evidence_path = environment.get("FORT_GYM_NETWORK_EVIDENCE_PATH")
        if (
            not isinstance(evidence_path, str)
            or hashlib.sha256(evidence_path.encode("utf-8")).hexdigest()
            != guard["evidence_path_sha256"]
        ):
            raise ControlEvidenceError(
                "live child provider-network evidence path mismatch"
            )
        provider_network_result = {
            "identity_sha256": identity["identity_sha256"],
            "helper_sha256": provider_network["helper"]["sha256"],
            "inner_argv_sha256": provider_network["inner_argv_sha256"],
            "wrapper_argv_sha256": provider_network["wrapper_argv_sha256"],
            "guard_attested": True,
        }

    result = {
        "verified": True,
        "command": {
            "module": "fort_gym.bench.cli",
            "subcommand": "experiment",
            "external_run_id": expected.run_id,
            "mode": command_mode,
        },
        "environment": {
            "run_id": expected.run_id,
            "contract_sha256": expected.contract_sha256,
            "nonce_matched": True,
        },
    }
    if provider_network_result is not None:
        result["provider_network"] = provider_network_result
    return result


def _linux_process_identity_probe(pid: int) -> dict[str, Any]:
    if not sys.platform.startswith("linux"):
        raise OSError("Linux procfs is required for live worker identity verification")
    proc_root = Path("/proc") / str(pid)
    cmdline_bytes = (proc_root / "cmdline").read_bytes()
    environment_bytes = (proc_root / "environ").read_bytes()
    executable_link = proc_root / "exe"
    executable_path = os.readlink(executable_link)
    executable_sha256 = _sha256_file(executable_link)
    cmdline = tuple(os.fsdecode(item) for item in cmdline_bytes.split(b"\0") if item)
    selected_environment: dict[str, str] = {}
    required_names = {
        b"FORT_GYM_RUN_ID",
        b"FORT_GYM_RUN_CONTRACT_SHA256",
        b"FORT_GYM_RUN_NONCE",
        b"FORT_GYM_NETWORK_POLICY",
        b"FORT_GYM_NETWORK_ALLOWED_HOST",
        b"FORT_GYM_NETWORK_ALLOWED_PORT",
        b"FORT_GYM_NETWORK_EVIDENCE_PATH",
    }
    for item in environment_bytes.split(b"\0"):
        name, separator, value = item.partition(b"=")
        if separator and name in required_names:
            selected_environment[os.fsdecode(name)] = os.fsdecode(value)
    return {
        "cmdline": cmdline,
        "environment": selected_environment,
        "executable_path": executable_path,
        "executable_sha256": executable_sha256,
    }


def _linux_process_ids() -> tuple[int, ...]:
    if not sys.platform.startswith("linux"):
        raise OSError("Linux procfs is required for process enumeration")
    try:
        entries = tuple(Path("/proc").iterdir())
    except OSError as exc:
        raise OSError("Linux procfs process enumeration failed") from exc
    return tuple(
        sorted(
            int(entry.name)
            for entry in entries
            if entry.name.isdigit() and int(entry.name) > 1
        )
    )


def _wait_for_process_group_exit(
    process_group_id: int,
    child_pid: int,
    *,
    timeout: float,
    result: dict[str, Any],
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            waited_pid, wait_status = os.waitpid(child_pid, os.WNOHANG)
        except ChildProcessError:
            waited_pid = 0
            wait_status = 0
        if waited_pid == child_pid:
            result["reaped"] = True
            result["wait_status"] = wait_status
        if not _process_group_exists(process_group_id):
            result["absent"] = True
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:  # pragma: no cover - unsupported filesystems
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - unsupported filesystems
        pass
    finally:
        os.close(descriptor)


__all__ = [
    "EXTERNAL_WORKER_COMPLETED",
    "EXTERNAL_WORKER_EXCEPTION",
    "EXTERNAL_WORKER_FAILED",
    "EXTERNAL_WORKER_STOPPED",
    "ActiveRunOwnershipError",
    "ControlEvidenceError",
    "ManagedRunResult",
    "PreCleanupObserverFactory",
    "ProcessIdentityProbe",
    "RuntimeController",
    "RuntimeControllerFactory",
    "SupervisedManagerError",
    "SupervisedRunManager",
    "WorkerContractFactory",
]
