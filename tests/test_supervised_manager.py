from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import fort_gym.bench.run.supervised_manager as supervised_manager_module
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.process_supervisor import (
    RunSpec,
    SupervisionResult,
    TerminalClass,
)
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import (
    SupervisedManagerError,
    SupervisedRunManager,
)

FIXED_NOW = datetime(2026, 8, 16, 18, 0, tzinfo=UTC)
TEST_CONTRACT_SHA256 = "c" * 64
TEST_NONCE = "d" * 32
MANAGED_CONTAINER_ID = "a" * 64
FOREIGN_CONTAINER_ID = "f" * 64
TYPED_RUNTIME_FAULTS = frozenset(
    {
        "runtime_df_killed",
        "harness_killed",
        "runtime_oom",
        "workspace_enospc",
        "runtime_container_restarted",
        "docker_daemon_restarted",
    }
)


def _typed_fault_evidence(terminal_class: str) -> dict[str, Any]:
    runtime_identity = {"expected": "container-a", "observed": "container-a"}
    evidence = {
        "runtime_df_killed": {
            "runtime_identity": runtime_identity,
            "signal": 9,
            "oom_killed": False,
        },
        "harness_killed": {"child_pid": 4242, "signal": 9},
        "runtime_oom": {
            "runtime_identity": runtime_identity,
            "runtime_exit_code": 137,
            "cgroup_memory_events": {
                "before": {"oom": 0, "oom_kill": 0},
                "after": {"oom": 1, "oom_kill": 1},
            },
        },
        "workspace_enospc": {
            "errno": 28,
            "operation": "write private fault fixture",
            "workspace": {
                "run_id": "managed-run",
                "scope_root": "/tmp/fortgym-control/managed-run/workspace",
                "fault_path": (
                    "/tmp/fortgym-control/managed-run/workspace/tmp/fill.bin"
                ),
                "fault_bytes": 16_777_216,
                "maximum_fault_bytes": 16_777_216,
            },
        },
        "runtime_container_restarted": {
            "container_identity": {
                "expected": "container-a",
                "before": "container-a",
                "after": "container-a",
            },
            "restart_count": {"before": 0, "after": 1},
        },
        "docker_daemon_restarted": {
            "daemon_generation": {"before": "boot-a", "after": "boot-b"},
            "runtime_identity": runtime_identity,
        },
    }
    return evidence[terminal_class]


@dataclass
class FakeRuntimeController:
    cleanup_error: bool = False
    reconciliation: Mapping[str, Any] | None = None
    prepare_calls: int = 0
    cleanup_calls: int = 0
    reconcile_calls: int = 0
    lifecycle: list[str] | None = None

    def prepare(self) -> Mapping[str, Any]:
        self.prepare_calls += 1
        if self.lifecycle is not None:
            self.lifecycle.append("runtime_prepare")
        return {"prepared": True}

    def cleanup(self) -> Mapping[str, Any]:
        self.cleanup_calls += 1
        if self.lifecycle is not None:
            self.lifecycle.append("runtime_cleanup")
        if self.cleanup_error:
            raise RuntimeError("deterministic cleanup failure")
        return {"cleaned": True}

    def reconcile(self) -> Mapping[str, Any]:
        self.reconcile_calls += 1
        return self.reconciliation or {
            "schema": "fortgym.m1b-runtime-reconcile/v1",
            "ok": True,
            "managed_candidates": 0,
            "removed_container_ids": [],
            "skipped_foreign_container_ids": [],
            "listener_absent": True,
            "noop": True,
            "errors": [],
        }


class FakeSupervisor:
    def __init__(
        self,
        returncode: int,
        *,
        terminal_class: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        self.returncode = returncode
        self.terminal_class = terminal_class
        self.reason_code = reason_code
        self.calls = 0
        self.specs: list[RunSpec] = []
        self.fault_classifiers: list[Any] = []

    def run(self, spec, *, prepare=None, cleanup=None, fault_classifier=None):
        self.calls += 1
        self.specs.append(spec)
        self.fault_classifiers.append(fault_classifier)
        if prepare is not None:
            prepare()

        cleanup_payload: dict[str, Any]
        try:
            details = cleanup() if cleanup is not None else {}
            cleanup_payload = {
                "ok": True,
                "stages": [{"stage": "callback", "ok": True, "details": details}],
            }
        except Exception as exc:  # noqa: BLE001 - fake supervisor cleanup boundary
            cleanup_payload = {
                "ok": False,
                "stages": [
                    {
                        "stage": "callback",
                        "ok": False,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }
                ],
            }

        terminal_class = self.terminal_class or (
            "completed" if self.returncode == 0 else "child_exit"
        )
        if not cleanup_payload["ok"]:
            terminal_class = "cleanup_failure"
        primary_terminal_class = (
            "completed"
            if self.returncode == 0
            else "external_signal"
            if self.returncode < 0
            else "child_exit"
        )
        payload: dict[str, Any] = {
            "schema": "fortgym.process-supervisor-terminal/v1",
            "run_id": spec.run_id,
            "terminal_class": terminal_class,
            "primary_terminal_class": primary_terminal_class,
            "primary_reason": {
                "code": "child_signaled"
                if self.returncode < 0
                else "child_completed"
                if self.returncode == 0
                else "child_nonzero_exit"
            },
            "child_pid": 4242,
            "returncode": self.returncode,
            "child_signal": -self.returncode if self.returncode < 0 else None,
            "reason": {
                "code": self.reason_code
                or ("child_completed" if self.returncode == 0 else "child_nonzero_exit")
            },
            "cleanup": cleanup_payload,
        }
        if terminal_class in TYPED_RUNTIME_FAULTS:
            payload["fault_classification"] = {
                "schema": "fortgym.runtime-fault-classification/v1",
                "attempted": True,
                "ok": True,
                "classified": True,
                "terminal_class": terminal_class,
                "evidence": _typed_fault_evidence(terminal_class),
            }
        elif terminal_class == "runtime_fault_classification_failure":
            payload["fault_classification"] = {
                "schema": "fortgym.runtime-fault-classification/v1",
                "attempted": True,
                "ok": False,
                "classified": False,
                "error": {"type": "RuntimeError", "message": "synthetic"},
            }
        spec.artifact_dir.mkdir(parents=True, exist_ok=True)
        terminal_path = spec.artifact_dir / "terminal.json"
        terminal_path.write_text(json.dumps(payload), encoding="utf-8")
        journal_path = spec.artifact_dir / "attempt-journal.jsonl"
        journal_path.write_text(
            json.dumps({"event": "attempt_started"})
            + "\n"
            + json.dumps({"event": "cleanup_recorded"})
            + "\n"
            + json.dumps({"event": "terminal_pending"})
            + "\n",
            encoding="utf-8",
        )
        terminal_enum = TerminalClass(terminal_class)
        return SupervisionResult(
            terminal_enum,
            terminal_path,
            journal_path,
            payload,
        )


def _registry(tmp_path, monkeypatch) -> tuple[RunRegistry, str, Path]:
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id="managed-run",
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    registry.set_summary(record.run_id, {"total_score": 0, "steps": 1})
    return registry, record.run_id, artifacts_root


def _contract(record, attempt_dir, controller) -> RunSpec:
    return RunSpec(
        run_id=record.run_id,
        argv=(
            sys.executable,
            "-m",
            "fort_gym.bench.cli",
            "experiment",
            "/tmp/config.yaml",
            "--external-run-id",
            record.run_id,
        ),
        artifact_dir=attempt_dir,
        trace_path=Path(str(record.trace_path)),
        scripted=True,
        environment_identity={
            "run_id": record.run_id,
            "contract_sha256": TEST_CONTRACT_SHA256,
            "rpc": {"nonce": TEST_NONCE},
        },
        runtime_cleanup_required=True,
    )


def _manager(
    *,
    registry: RunRegistry,
    control_root: Path,
    controller: FakeRuntimeController,
    supervisor: FakeSupervisor,
    ownership_probe=lambda _owner: False,
    process_identity_probe=None,
) -> SupervisedRunManager:
    return SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _control_dir: controller,
        contract_factory=_contract,
        supervisor_factory=lambda: supervisor,
        ownership_probe=ownership_probe,
        process_identity_probe=process_identity_probe,
        clock=lambda: FIXED_NOW,
    )


@pytest.mark.parametrize(
    ("returncode", "expected_status"),
    [(0, "completed"), (20, "failed"), (21, "stopped"), (22, "failed")],
)
def test_manager_interprets_every_external_worker_exit(
    tmp_path,
    monkeypatch,
    returncode: int,
    expected_status: str,
) -> None:
    registry, run_id, artifacts_root = _registry(tmp_path, monkeypatch)
    controller = FakeRuntimeController()
    supervisor = FakeSupervisor(returncode)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "parent-control",
        controller=controller,
        supervisor=supervisor,
    )

    result = manager.run(run_id)

    assert result.status == expected_status
    assert result.returncode == returncode
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == expected_status
    assert loaded.ended_at == FIXED_NOW
    assert "cleanup_completed_at" in loaded.metadata
    assert controller.prepare_calls == 1
    assert controller.cleanup_calls == 1
    assert supervisor.calls == 1
    assert supervisor.specs[0].argv.count("--external-run-id") == 1
    assert supervisor.specs[0].argv[-1] == run_id
    assert not result.control_dir.is_relative_to(Path(loaded.artifacts_dir).resolve())
    assert (result.control_dir / "manager-terminal.json").is_file()
    assert not (artifacts_root / run_id / "manager-terminal.json").exists()


@pytest.mark.parametrize("returncode", [20, 22])
def test_failure_and_exception_exit_take_precedence_over_stop(
    tmp_path,
    monkeypatch,
    returncode: int,
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.request_stop(run_id)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(),
        supervisor=FakeSupervisor(returncode),
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    loaded = registry.get(run_id)
    assert loaded is not None and loaded.status == "failed"


def test_cleanup_failure_takes_precedence_over_stop_and_is_not_attested_complete(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.request_stop(run_id)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(cleanup_error=True),
        supervisor=FakeSupervisor(21),
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == "parent_cleanup_failed"
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.ended_at == FIXED_NOW
    assert "cleanup_completed_at" not in loaded.metadata


def test_manager_wires_optional_controller_fault_classifier_only_when_present(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    controller = FakeRuntimeController()
    classifier_calls: list[Mapping[str, Any]] = []

    def classify(observation: Mapping[str, Any]) -> Mapping[str, Any]:
        classifier_calls.append(observation)
        return {
            "schema": "fortgym.runtime-fault-classifier-result/v1",
            "terminal_class": None,
            "evidence": {},
        }

    controller.classify_runtime_fault = classify  # type: ignore[attr-defined]
    supervisor = FakeSupervisor(0)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=controller,
        supervisor=supervisor,
    )

    result = manager.run(run_id)

    assert result.status == "completed"
    assert supervisor.fault_classifiers == [classify]
    assert classifier_calls == []  # The injected fake records the seam only.

    registry_two, run_id_two, _ = _registry(tmp_path / "without", monkeypatch)
    supervisor_two = FakeSupervisor(0)
    manager_two = _manager(
        registry=registry_two,
        control_root=tmp_path / "without" / "control",
        controller=FakeRuntimeController(),
        supervisor=supervisor_two,
    )
    assert manager_two.run(run_id_two).status == "completed"
    assert supervisor_two.fault_classifiers == [None]


def test_non_callable_controller_fault_classifier_fails_before_supervision(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    controller = FakeRuntimeController()
    controller.classify_runtime_fault = "runtime_oom"  # type: ignore[attr-defined]
    supervisor = FakeSupervisor(0)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=controller,
        supervisor=supervisor,
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == "manager_or_supervisor_exception"
    assert result.reason["type"] == "TypeError"
    assert supervisor.calls == 0
    assert controller.cleanup_calls == 1


@pytest.mark.parametrize(
    ("terminal_class", "returncode"),
    [
        ("runtime_df_killed", 20),
        ("harness_killed", -9),
        ("runtime_oom", 20),
        ("workspace_enospc", 20),
        ("runtime_container_restarted", 20),
        ("docker_daemon_restarted", 20),
    ],
)
def test_typed_runtime_fault_reason_precedes_worker_exit_stage_and_stop(
    tmp_path, monkeypatch, terminal_class: str, returncode: int
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    registry.record_pending_terminal_failure(
        run_id,
        terminal_reason={"code": "staged_worker_failure"},
        step=0,
    )
    assert registry.request_stop(run_id)
    supervisor = FakeSupervisor(
        returncode,
        terminal_class=terminal_class,
        reason_code=terminal_class,
    )
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(),
        supervisor=supervisor,
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == terminal_class
    assert result.reason["stop_requested_observed"] is True
    loaded = registry.get(run_id)
    assert loaded is not None and loaded.status == "failed"
    assert "cleanup_completed_at" in loaded.metadata


def test_classifier_failure_terminal_cannot_be_misclassified_completed(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(),
        supervisor=FakeSupervisor(
            0,
            terminal_class="runtime_fault_classification_failure",
            reason_code="runtime_fault_classification_failure",
        ),
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == "runtime_fault_classification_failure"


@pytest.mark.parametrize(
    ("staged", "expected_code"),
    [
        ({"code": "staged_agent_failure", "detail": "kept"}, "staged_agent_failure"),
        (None, "external_worker_failed"),
    ],
)
def test_failed_exit_uses_staged_reason_or_deterministic_fallback(
    tmp_path,
    monkeypatch,
    staged: dict[str, Any] | None,
    expected_code: str,
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    if staged is not None:
        registry.record_pending_terminal_failure(
            run_id,
            terminal_reason=staged,
            step=0,
        )
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(),
        supervisor=FakeSupervisor(20),
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == expected_code
    if staged is not None:
        assert result.reason["detail"] == "kept"


@pytest.mark.parametrize("initial_status", ["pending", "running"])
def test_pre_main_exception_finalizes_pending_or_running_row(
    tmp_path,
    monkeypatch,
    initial_status: str,
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    if initial_status == "running":
        assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(),
        supervisor=FakeSupervisor(22),
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.ended_at == FIXED_NOW


@pytest.mark.parametrize("initial_status", ["pending", "running"])
def test_contract_factory_exception_cleans_then_finalizes_pending_or_running_row(
    tmp_path,
    monkeypatch,
    initial_status: str,
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    if initial_status == "running":
        assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    controller = FakeRuntimeController()
    supervisor = FakeSupervisor(0)

    def broken_contract(_record, _attempt_dir, _controller):
        raise RuntimeError("synthetic pre-main contract failure")

    manager = SupervisedRunManager(
        registry=registry,
        control_root=tmp_path / "control",
        runtime_controller_factory=lambda _record, _control_dir: controller,
        contract_factory=broken_contract,
        supervisor_factory=lambda: supervisor,
        ownership_probe=lambda _owner: False,
        clock=lambda: FIXED_NOW,
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == "manager_or_supervisor_exception"
    assert controller.cleanup_calls == 1
    assert supervisor.calls == 0
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.ended_at == FIXED_NOW
    assert "cleanup_completed_at" in loaded.metadata


@pytest.mark.parametrize(
    ("cleanup_result", "expected_error_type"),
    [
        (
            {"ok": False, "residue": ["managed-container"]},
            "RuntimeCleanupReportedFailure",
        ),
        ("not-a-mapping", "TypeError"),
    ],
)
def test_pre_main_exception_fails_closed_on_non_success_cleanup_result(
    tmp_path,
    monkeypatch,
    cleanup_result: Any,
    expected_error_type: str,
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    controller = FakeRuntimeController()
    supervisor = FakeSupervisor(0)

    def reported_cleanup():
        controller.cleanup_calls += 1
        return cleanup_result

    def broken_contract(_record, _attempt_dir, _controller):
        raise RuntimeError("synthetic pre-main contract failure")

    monkeypatch.setattr(controller, "cleanup", reported_cleanup)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=tmp_path / "control",
        runtime_controller_factory=lambda _record, _control_dir: controller,
        contract_factory=broken_contract,
        supervisor_factory=lambda: supervisor,
        ownership_probe=lambda _owner: False,
        clock=lambda: FIXED_NOW,
    )

    result = manager.run(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == "parent_cleanup_failed"
    cleanup = result.reason["cleanup"]
    assert cleanup["ok"] is False
    stage = cleanup["stages"][0]
    assert stage["error"]["type"] == expected_error_type
    if isinstance(cleanup_result, Mapping):
        assert stage["details"] == cleanup_result
    assert controller.cleanup_calls == 1
    assert supervisor.calls == 0
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert "cleanup_completed_at" not in loaded.metadata


def test_successful_zero_plus_late_stop_finalizes_stopped(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.request_stop(run_id)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(),
        supervisor=FakeSupervisor(0),
    )

    result = manager.run(run_id)

    assert result.status == "stopped"
    assert result.reason["late_stop_observed"] is True


def test_cleanup_precedes_one_terminal_write_and_duplicate_run_is_idempotent(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    lifecycle: list[str] = []
    controller = FakeRuntimeController(lifecycle=lifecycle)
    supervisor = FakeSupervisor(0)
    original_cleanup = registry.record_cleanup_completed
    original_finalize = registry.finalize_success_after_cleanup

    def tracked_cleanup(*args, **kwargs):
        lifecycle.append("registry_cleanup_complete")
        return original_cleanup(*args, **kwargs)

    def tracked_finalize(*args, **kwargs):
        lifecycle.append("registry_terminal")
        return original_finalize(*args, **kwargs)

    monkeypatch.setattr(registry, "record_cleanup_completed", tracked_cleanup)
    monkeypatch.setattr(registry, "finalize_success_after_cleanup", tracked_finalize)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=controller,
        supervisor=supervisor,
    )

    first = manager.run(run_id)
    first_ended = registry.get(run_id).ended_at  # type: ignore[union-attr]
    second = manager.run(run_id)

    assert first.status == second.status == "completed"
    assert second.action == "already_terminal"
    assert registry.get(run_id).ended_at == first_ended  # type: ignore[union-attr]
    assert supervisor.calls == 1
    assert lifecycle.count("registry_cleanup_complete") == 1
    assert lifecycle.count("registry_terminal") == 1
    assert (
        lifecycle.index("runtime_cleanup")
        < lifecycle.index("registry_cleanup_complete")
        < lifecycle.index("registry_terminal")
    )


def test_manager_rejects_control_evidence_inside_artifact_root(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, artifacts_root = _registry(tmp_path, monkeypatch)
    supervisor = FakeSupervisor(0)
    manager = _manager(
        registry=registry,
        control_root=artifacts_root / "parent-control",
        controller=FakeRuntimeController(),
        supervisor=supervisor,
    )

    with pytest.raises(SupervisedManagerError, match="outside run artifacts"):
        manager.run(run_id)

    assert supervisor.calls == 0
    loaded = registry.get(run_id)
    assert loaded is not None and loaded.status == "pending"


def _write_recovery_evidence(
    *,
    control_root: Path,
    run_id: str,
    payload: Mapping[str, Any] | None,
    owner_pid: int = 999_999,
    child_pid: int = 999_998,
) -> None:
    run_dir = control_root / run_id
    attempt_dir = run_dir / "attempts" / "attempt-0001"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    environment_identity = {
        "run_id": run_id,
        "contract_sha256": TEST_CONTRACT_SHA256,
        "rpc": {"nonce": TEST_NONCE},
    }
    (run_dir / "owner.json").write_text(
        json.dumps(
            {
                "schema": "fortgym.supervised-manager-owner/v1",
                "run_id": run_id,
                "state": "active",
                "manager_pid": owner_pid,
                "manager_start_ticks": 123_456,
                "identity_bound": True,
                "contract_sha256": TEST_CONTRACT_SHA256,
                "nonce_sha256": hashlib.sha256(
                    TEST_NONCE.encode("ascii")
                ).hexdigest(),
                "environment_identity_sha256": hashlib.sha256(
                    json.dumps(
                        environment_identity,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "observed_registry_status": "running",
                "attempt_dir": str(attempt_dir.resolve()),
                "updated_at": "2026-08-16T18:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "attempt-journal.jsonl").write_text(
        json.dumps(
            {
                "schema": "fortgym.process-supervisor-attempt/v1",
                "event": "attempt_started",
                "run_id": run_id,
                "supervisor_pid": owner_pid,
                "environment_identity": environment_identity,
            }
        )
        + "\n"
        + json.dumps(
            {
                "schema": "fortgym.process-supervisor-attempt/v1",
                "event": "child_started",
                "run_id": run_id,
                "supervisor_pid": owner_pid,
                "child_pid": child_pid,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if payload is not None:
        (attempt_dir / "terminal.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )


def _recovery_payload(run_id: str, returncode: int = 0) -> dict[str, Any]:
    return {
        "schema": "fortgym.process-supervisor-terminal/v1",
        "run_id": run_id,
        "terminal_class": "completed" if returncode == 0 else "child_exit",
        "primary_terminal_class": "completed" if returncode == 0 else "child_exit",
        "returncode": returncode,
        "reason": {"code": "recovered_child"},
        "cleanup": {"ok": True, "stages": []},
    }


def _matching_process_identity(run_id: str) -> dict[str, Any]:
    return {
        "cmdline": (
            sys.executable,
            "-m",
            "fort_gym.bench.cli",
            "experiment",
            "/tmp/config.yaml",
            "--external-run-id",
            run_id,
        ),
        "environment": {
            "FORT_GYM_RUN_ID": run_id,
            "FORT_GYM_RUN_CONTRACT_SHA256": TEST_CONTRACT_SHA256,
            "FORT_GYM_RUN_NONCE": TEST_NONCE,
        },
    }


def test_reconcile_dead_owner_from_terminal_evidence_is_deterministic_and_idempotent(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    control_root = tmp_path / "control"
    _write_recovery_evidence(
        control_root=control_root,
        run_id=run_id,
        payload=_recovery_payload(run_id),
    )
    supervisor = FakeSupervisor(0)
    manager = _manager(
        registry=registry,
        control_root=control_root,
        controller=FakeRuntimeController(),
        supervisor=supervisor,
        ownership_probe=lambda _owner: False,
    )

    first = manager.reconcile(run_id)
    second = manager.reconcile(run_id)

    assert first.status == second.status == "completed"
    assert first.recovered is True
    assert second.action == "already_terminal"
    assert supervisor.calls == 0


def test_reconcile_live_owner_does_not_relabel_running_worker(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    control_root = tmp_path / "control"
    _write_recovery_evidence(
        control_root=control_root,
        run_id=run_id,
        payload=_recovery_payload(run_id, returncode=22),
        owner_pid=123,
    )
    manager = _manager(
        registry=registry,
        control_root=control_root,
        controller=FakeRuntimeController(),
        supervisor=FakeSupervisor(22),
        ownership_probe=lambda _owner: True,
    )

    result = manager.reconcile(run_id)

    assert result.finalized is False
    assert result.action == "live_owner"
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.ended_at is None


def test_linux_owner_liveness_binds_start_ticks_before_and_after_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = {
        "manager_pid": 321,
        "manager_start_ticks": 987_654,
        "identity_bound": True,
    }
    observed: list[int] = []
    start_ticks = iter((987_654, 987_654))
    monkeypatch.setattr(supervised_manager_module.sys, "platform", "linux")
    monkeypatch.setattr(
        supervised_manager_module,
        "_linux_process_start_ticks",
        lambda pid: next(start_ticks),
    )
    monkeypatch.setattr(
        supervised_manager_module.os,
        "kill",
        lambda pid, sig: observed.append(pid) if sig == 0 else None,
    )

    assert supervised_manager_module._owner_pid_is_live(owner) is True
    assert observed == [321]


@pytest.mark.parametrize("phase", ["before_probe", "after_probe"])
def test_linux_owner_liveness_rejects_pid_reuse(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    owner = {
        "manager_pid": 321,
        "manager_start_ticks": 987_654,
        "identity_bound": True,
    }
    start_ticks = (
        iter((987_655,))
        if phase == "before_probe"
        else iter((987_654, 987_655))
    )
    monkeypatch.setattr(supervised_manager_module.sys, "platform", "linux")
    monkeypatch.setattr(
        supervised_manager_module,
        "_linux_process_start_ticks",
        lambda pid: next(start_ticks),
    )
    monkeypatch.setattr(supervised_manager_module.os, "kill", lambda _pid, _sig: None)

    assert supervised_manager_module._owner_pid_is_live(owner) is False


def test_reconcile_dead_owner_without_terminal_cleans_managed_resources_then_fails(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    control_root = tmp_path / "control"
    _write_recovery_evidence(
        control_root=control_root,
        run_id=run_id,
        payload=None,
    )
    controller = FakeRuntimeController(
        reconciliation={
            "schema": "fortgym.m1b-runtime-reconcile/v1",
            "ok": True,
            "managed_candidates": 1,
            "removed_container_ids": [MANAGED_CONTAINER_ID],
            "skipped_foreign_container_ids": [],
            "listener_absent": True,
            "noop": False,
            "errors": [],
        }
    )
    manager = _manager(
        registry=registry,
        control_root=control_root,
        controller=controller,
        supervisor=FakeSupervisor(22),
        ownership_probe=lambda _owner: False,
    )

    first = manager.reconcile(run_id)
    second = manager.reconcile(run_id)

    assert first.finalized is True
    assert first.status == "failed"
    assert first.reason["code"] == "supervisor_lost"
    assert first.reason["supervisor_events"] == ["attempt_started", "child_started"]
    assert first.reason["reconciliation"]["removed_container_ids"] == [
        MANAGED_CONTAINER_ID
    ]
    assert second.action == "already_terminal"
    assert controller.reconcile_calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.ended_at == FIXED_NOW
    assert "cleanup_completed_at" in loaded.metadata


def test_reconcile_reaps_exact_orphan_process_group_and_leaves_foreign_canary(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    target = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    foreign_canary = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        control_root = tmp_path / "control"
        _write_recovery_evidence(
            control_root=control_root,
            run_id=run_id,
            payload=None,
            child_pid=target.pid,
        )
        controller = FakeRuntimeController(
            reconciliation={
                "schema": "fortgym.m1b-runtime-reconcile/v1",
                "ok": True,
                "managed_candidates": 1,
                "removed_container_ids": [],
                "skipped_foreign_container_ids": [FOREIGN_CONTAINER_ID],
                "listener_absent": True,
                "noop": True,
                "errors": [],
            }
        )
        manager = _manager(
            registry=registry,
            control_root=control_root,
            controller=controller,
            supervisor=FakeSupervisor(22),
            ownership_probe=lambda _owner: False,
            process_identity_probe=lambda pid: (
                _matching_process_identity(run_id)
                if pid == target.pid
                else pytest.fail("identity probe targeted a foreign process")
            ),
        )

        result = manager.reconcile(run_id)

        assert result.status == "failed"
        harness = result.reason["reconciliation"]["harness_process_group"]
        assert harness["child_pid"] == target.pid
        assert harness["term_sent"] is True
        assert harness["absent"] is True
        assert harness["identity"]["environment"] == {
            "run_id": run_id,
            "contract_sha256": TEST_CONTRACT_SHA256,
            "nonce_matched": True,
        }
        assert TEST_NONCE not in json.dumps(harness, sort_keys=True)
        with pytest.raises(ProcessLookupError):
            os.killpg(target.pid, 0)
        assert foreign_canary.poll() is None
    finally:
        for process in (target, foreign_canary):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=2)
            except ChildProcessError:
                pass


@pytest.mark.parametrize(
    "identity_failure", ["durable_missing", "probe_missing", "mismatch", "unavailable"]
)
def test_reconcile_identity_failure_leaves_foreign_process_untouched(
    tmp_path, monkeypatch, identity_failure: str
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    foreign_canary = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        control_root = tmp_path / "control"
        _write_recovery_evidence(
            control_root=control_root,
            run_id=run_id,
            payload=None,
            child_pid=foreign_canary.pid,
        )
        if identity_failure == "durable_missing":
            journal_path = (
                control_root
                / run_id
                / "attempts"
                / "attempt-0001"
                / "attempt-journal.jsonl"
            )
            records = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
            ]
            records[0].pop("environment_identity")
            journal_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

        def identity_probe(pid: int) -> Mapping[str, Any]:
            assert pid == foreign_canary.pid
            if identity_failure == "unavailable":
                raise PermissionError("synthetic procfs denial")
            observed = _matching_process_identity(run_id)
            environment = dict(observed["environment"])
            if identity_failure == "probe_missing":
                environment.pop("FORT_GYM_RUN_NONCE")
            elif identity_failure == "mismatch":
                environment["FORT_GYM_RUN_ID"] = "different-run"
            return {**observed, "environment": environment}

        manager = _manager(
            registry=registry,
            control_root=control_root,
            controller=FakeRuntimeController(),
            supervisor=FakeSupervisor(22),
            ownership_probe=lambda _owner: False,
            process_identity_probe=identity_probe,
        )

        result = manager.reconcile(run_id)

        assert result.status == "failed"
        assert result.reason["code"] == "parent_cleanup_failed"
        harness = result.reason["prior_terminal_reason"]["reconciliation"][
            "harness_process_group"
        ]
        assert harness["ok"] is False
        assert harness["error"]["type"] == "ControlEvidenceError"
        assert foreign_canary.poll() is None
    finally:
        if foreign_canary.poll() is None:
            try:
                os.killpg(foreign_canary.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        foreign_canary.wait(timeout=2)


def test_reconcile_dead_owner_cleanup_failure_is_failed_without_cleanup_attestation(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    control_root = tmp_path / "control"
    _write_recovery_evidence(
        control_root=control_root,
        run_id=run_id,
        payload=None,
    )
    controller = FakeRuntimeController(
        reconciliation={
            "schema": "fortgym.m1b-runtime-reconcile/v1",
            "ok": False,
            "managed_candidates": 1,
            "removed_container_ids": [],
            "skipped_foreign_container_ids": [FOREIGN_CONTAINER_ID],
            "listener_absent": False,
            "noop": True,
            "errors": ["assigned listener remains"],
        }
    )
    manager = _manager(
        registry=registry,
        control_root=control_root,
        controller=controller,
        supervisor=FakeSupervisor(22),
        ownership_probe=lambda _owner: False,
    )

    result = manager.reconcile(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == "parent_cleanup_failed"
    assert result.reason["prior_terminal_reason"]["code"] == "supervisor_lost"
    assert controller.reconcile_calls == 1
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert "cleanup_completed_at" not in loaded.metadata


def test_reconcile_delegates_foreign_canary_and_preserves_evidence(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    control_root = tmp_path / "control"
    _write_recovery_evidence(
        control_root=control_root,
        run_id=run_id,
        payload=None,
    )
    controller = FakeRuntimeController(
        reconciliation={
            "schema": "fortgym.m1b-runtime-reconcile/v1",
            "ok": True,
            "managed_candidates": 1,
            "removed_container_ids": [],
            "skipped_foreign_container_ids": [FOREIGN_CONTAINER_ID],
            "listener_absent": True,
            "noop": True,
            "errors": [],
        }
    )
    manager = _manager(
        registry=registry,
        control_root=control_root,
        controller=controller,
        supervisor=FakeSupervisor(22),
        ownership_probe=lambda _owner: False,
    )

    result = manager.reconcile(run_id)

    assert result.status == "failed"
    assert result.reason["reconciliation"]["skipped_foreign_container_ids"] == [
        FOREIGN_CONTAINER_ID
    ]
    manager_terminal = json.loads(
        (result.control_dir / "manager-terminal.json").read_text(encoding="utf-8")
    )
    stages = manager_terminal["supervision"]["cleanup"]["stages"]
    details = next(
        stage["details"] for stage in stages if stage["stage"] == "runtime_reconcile"
    )
    assert details["skipped_foreign_container_ids"] == [FOREIGN_CONTAINER_ID]


def test_reconcile_without_reconstructable_controller_fails_closed_with_evidence(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    control_root = tmp_path / "control"
    _write_recovery_evidence(
        control_root=control_root,
        run_id=run_id,
        payload=None,
    )

    def unavailable_controller(_record, _control_dir):
        raise RuntimeError("durable runtime contract unavailable")

    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=unavailable_controller,
        contract_factory=_contract,
        supervisor_factory=lambda: FakeSupervisor(22),
        ownership_probe=lambda _owner: False,
        clock=lambda: FIXED_NOW,
    )

    result = manager.reconcile(run_id)

    assert result.status == "failed"
    assert result.reason["code"] == "parent_cleanup_failed"
    prior = result.reason["prior_terminal_reason"]
    assert prior["code"] == "supervisor_lost"
    assert prior["reconciliation"]["ok"] is False
    assert (
        "durable runtime contract unavailable"
        in prior["reconciliation"]["error"]["message"]
    )
    loaded = registry.get(run_id)
    assert loaded is not None
    assert "cleanup_completed_at" not in loaded.metadata


def test_reconcile_without_owner_or_terminal_remains_unresolved(
    tmp_path, monkeypatch
) -> None:
    registry, run_id, _ = _registry(tmp_path, monkeypatch)
    assert registry.claim_pending_run(run_id, started_at=FIXED_NOW)
    manager = _manager(
        registry=registry,
        control_root=tmp_path / "control",
        controller=FakeRuntimeController(),
        supervisor=FakeSupervisor(22),
        ownership_probe=lambda _owner: False,
    )

    result = manager.reconcile(run_id)

    assert result.finalized is False
    assert result.action == "unresolved"
    loaded = registry.get(run_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.ended_at is None
