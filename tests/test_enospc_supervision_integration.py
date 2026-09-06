from __future__ import annotations

import hashlib
import json
import sys
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fort_gym.bench.config import get_settings
from fort_gym.bench.run.fault_driver import (
    FaultAuthorizationError,
    FaultGate,
    OwnedRunEvidenceLoader,
)
from fort_gym.bench.run.process_supervisor import SupervisionResult, TerminalClass
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import ManagedRunResult, SupervisedRunManager
from fort_gym.bench.run.supervision_service import (
    LaunchEvidenceError,
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionConfigurationError,
    SupervisionService,
    SupervisionServiceError,
)


class FakeEnospcControls:
    def __init__(self, config: ServiceConfig, timeline: list[str]) -> None:
        self.config = config
        self.timeline = timeline
        self.prepare_calls = 0
        self.cleanup_calls = 0
        self.reconcile_calls = 0
        self.fail_cleanup = False
        self.malformed_receipt = False
        self.prepared_authorization: Any | None = None

    def _target(self, run_id: str, *, cleanup_mode: str | None = None):
        launch = json.loads(
            (self.config.control_root / run_id / "launch.json").read_text()
        )
        contract = launch["contract"]
        peer_run_id = contract["cotenancy"]["peer_run_ids"][0]
        values: dict[str, Any] = {
            "run_id": run_id,
            "contract_sha256": contract["contract_sha256"],
            "nonce": contract["rpc"]["nonce"],
            "cohort_sha256": contract["cotenancy"]["cohort_sha256"],
            "peer_run_id": peer_run_id,
            "db_path": self.config.db_path,
            "workspace": self.config.artifacts_root / run_id,
            "control_root": self.config.control_root,
        }
        if cleanup_mode is not None:
            values.update(
                cleanup_mode=cleanup_mode,
                harness_process_group_id=None,
            )
        return SimpleNamespace(**values)

    def load_prelaunch_enospc_target(self, run_id: str):
        self.timeline.append("load_prelaunch")
        target = self._target(run_id)
        assert not (self.config.control_root / run_id / "owner.json").exists()
        assert not (self.config.control_root / run_id / "attempts").exists()
        assert not target.workspace.exists()
        return target

    def load_enospc_cleanup_target(self, run_id: str, *, peer_run_id: str):
        self.timeline.append("load_cleanup")
        target = self._target(run_id, cleanup_mode="pre_child_abort")
        journal = (
            self.config.control_root
            / run_id
            / "attempts"
            / "attempt-0001"
            / "attempt-journal.jsonl"
        )
        if journal.exists():
            child_rows = [
                row
                for row in (
                    json.loads(line) for line in journal.read_text().splitlines()
                )
                if row.get("event") == "child_started"
            ]
            if len(child_rows) == 1:
                target.cleanup_mode = "post_child_cleanup"
                target.harness_process_group_id = child_rows[0]["child_pid"]
        assert target.peer_run_id == peer_run_id
        assert (
            self.config.control_root / run_id / "prelaunch-enospc-workspace.json"
        ).exists()
        if not target.workspace.exists():
            rows = [json.loads(line) for line in journal.read_text().splitlines()]
            completed = [
                row for row in rows if row.get("event") == "post_cleanup_completed"
            ]
            assert len(completed) == 1
            details = completed[0]["details"]
            assert completed[0]["ok"] is True
            assert details["schema"] == "fortgym.m1b-private-tmpfs/v1"
            assert details["operation"] == "unmounted"
            assert details["run_id"] == run_id
            assert details["residue_absent"] is True
        return target

    def prepare_workspace(self, *, authorization: Any, target: Any) -> Mapping[str, Any]:
        self.prepare_calls += 1
        self.timeline.append("mount")
        assert "capability=<redacted>" in repr(authorization)
        authorization._authorize_tmpfs_setup(target)
        self.prepared_authorization = authorization
        target.workspace.mkdir(parents=False, exist_ok=False)
        source = f"fortgym-m1b-enospc-{target.run_id}"
        receipt = {
            "schema": "fortgym.m1b-prelaunch-enospc-workspace/v1",
            "ok": True,
            "run_id": target.run_id,
            "contract_sha256": target.contract_sha256,
            "nonce_sha256": hashlib.sha256(target.nonce.encode()).hexdigest(),
            "cohort_sha256": target.cohort_sha256,
            "peer_run_id": target.peer_run_id,
            "workspace": str(target.workspace),
            "filesystem": "tmpfs",
            "size_bytes": 16 * 1024 * 1024,
            "source": source,
            "marker_sha256": "f" * 64,
            "mount_argv": [
                "/bin/mount",
                "-t",
                "tmpfs",
                "-o",
                "size=16777216,nosuid,nodev,noexec,mode=0700",
                source,
                str(target.workspace),
            ],
            "shell": False,
            "prepared_before_manager": True,
        }
        if self.malformed_receipt:
            receipt["prepared_before_manager"] = False
        (target.control_root / target.run_id / "prelaunch-enospc-workspace.json").write_text(
            json.dumps(receipt),
            encoding="utf-8",
        )
        return receipt

    def cleanup_workspace(self, *, target: Any) -> Mapping[str, Any]:
        self.cleanup_calls += 1
        self.timeline.append("unmount")
        if self.fail_cleanup:
            raise RuntimeError("synthetic ENOSPC unmount failure")
        artifact = target.workspace / "artifact-opened"
        if artifact.exists():
            artifact.unlink()
        target.workspace.rmdir()
        return {
            "schema": "fortgym.m1b-private-tmpfs/v1",
            "operation": "unmounted",
            "run_id": target.run_id,
            "argv": ["/bin/umount", "--", str(target.workspace)],
            "shell": False,
            "cleanup_mode": getattr(target, "cleanup_mode", "pre_child_abort"),
            "child_process_group_id": getattr(
                target, "harness_process_group_id", None
            ),
            "child_process_group_absent": True,
            "residue_absent": True,
        }

    def reconcile_workspace(self, *, target: Any) -> Mapping[str, Any]:
        self.reconcile_calls += 1
        self.timeline.append("reconcile_unmount")
        existed = target.workspace.exists()
        if existed:
            target.workspace.rmdir()
        return {
            "schema": "fortgym.m1b-private-tmpfs/v1",
            "operation": "reconciled" if existed else "already_absent",
            "run_id": target.run_id,
            "argv": ["/bin/umount", "--", str(target.workspace)],
            "shell": False,
            "cleanup_mode": getattr(target, "cleanup_mode", "pre_child_abort"),
            "child_process_group_id": getattr(
                target, "harness_process_group_id", None
            ),
            "child_process_group_absent": True,
            "residue_absent": True,
        }


class FakeRuntime:
    def __init__(self, artifacts_root: Path, timeline: list[str]) -> None:
        self.artifacts_root = artifacts_root
        self.timeline = timeline

    def prepare(self) -> Mapping[str, Any]:
        self.timeline.append("runtime_prepare")
        workspace = self.artifacts_root / "target-run"
        assert workspace.is_dir()
        (workspace / "artifact-opened").write_text("inside mounted workspace")
        self.timeline.append("artifact_opened")
        return {"ok": True}

    def cleanup(self) -> Mapping[str, Any]:
        self.timeline.append("runtime_cleanup")
        return {"ok": True, "container_absent": True, "listener_absent": True}

    def reconcile(self) -> Mapping[str, Any]:
        self.timeline.append("runtime_reconcile")
        return {
            "schema": "fortgym.m1b-runtime-reconcile/v1",
            "ok": True,
            "managed_candidates": 0,
            "removed_container_ids": [],
            "skipped_foreign_container_ids": [],
            "listener_absent": True,
            "noop": True,
            "errors": [],
        }


class CallbackSupervisor:
    def __init__(self, timeline: list[str]) -> None:
        self.timeline = timeline
        self.registry: RunRegistry | None = None

    def run(
        self,
        spec,
        *,
        prepare=None,
        cleanup=None,
        post_cleanup=None,
        fault_classifier=None,
        provider_network=None,
    ) -> SupervisionResult:
        assert provider_network is None
        assert post_cleanup is not None
        assert self.registry is not None
        self.registry.set_status(spec.run_id, status="running")
        self.registry.set_summary(spec.run_id, {"total_score": 0})
        prepare_details = prepare()
        cleanup_stages: list[dict[str, Any]] = []
        cleanup_stages.append(
            {"stage": "callback", "ok": True, "details": cleanup()}
        )
        try:
            post_details = post_cleanup()
            cleanup_stages.append(
                {"stage": "post_callback", "ok": True, "details": post_details}
            )
            cleanup_ok = True
        except Exception as exc:  # noqa: BLE001 - deterministic fake boundary
            cleanup_stages.append(
                {
                    "stage": "post_callback",
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            cleanup_ok = False
        self.timeline.append("cleanup_recorded")
        cleanup_record = {"ok": cleanup_ok, "stages": cleanup_stages}
        payload = {
            "schema": "fortgym.process-supervisor-terminal/v1",
            "run_id": spec.run_id,
            "terminal_class": "completed" if cleanup_ok else "cleanup_failure",
            "primary_terminal_class": "completed",
            "primary_reason": {"code": "child_completed"},
            "returncode": 0,
            "reason": {"code": "child_completed"},
            "prepare": {"ok": True, "details": prepare_details},
            "cleanup": cleanup_record,
        }
        spec.artifact_dir.mkdir(parents=True, exist_ok=True)
        journal = spec.artifact_dir / "attempt-journal.jsonl"
        journal.write_text(
            "\n".join(
                json.dumps({"event": event})
                for event in ("attempt_started", "cleanup_recorded", "terminal_pending")
            )
            + "\n",
            encoding="utf-8",
        )
        terminal = spec.artifact_dir / "terminal.json"
        terminal.write_text(json.dumps(payload), encoding="utf-8")
        self.timeline.append("terminal_pending")
        return SupervisionResult(
            TerminalClass.COMPLETED if cleanup_ok else TerminalClass.CLEANUP_FAILURE,
            terminal,
            journal,
            payload,
        )


def _service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    manager_factory,
    controls: FakeEnospcControls | None = None,
) -> tuple[SupervisionService, RunRegistry, ServiceConfig, FakeEnospcControls]:
    artifacts = (tmp_path / "artifacts").resolve()
    artifacts.mkdir()
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    entrypoint = repo / "runtime_entrypoint.sh"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    entrypoint.chmod(0o700)
    dfroot = (tmp_path / "dfroot").resolve()
    dfroot.mkdir()
    config = ServiceConfig(
        db_path=(tmp_path / "runs.sqlite3").resolve(),
        artifacts_root=artifacts,
        control_root=(tmp_path / "control").resolve(),
        repo_root=repo,
        python_executable=Path(sys.executable).absolute(),
        entrypoint_path=entrypoint,
        dfroot=dfroot,
        code_sha256="a" * 64,
        allow_test_workspace_fault_profiles=True,
    )
    registry = RunRegistry(db_path=config.db_path, recover_interrupted=False)
    controls = controls or FakeEnospcControls(config, [])
    ids = iter(("target-run", "peer-run"))
    nonces = iter(("1" * 32, "2" * 32))
    service = SupervisionService(
        registry=registry,
        config=config,
        manager_factory=manager_factory,
        enospc_evidence_loader=controls,  # type: ignore[arg-type]
        enospc_workspace=controls,  # type: ignore[arg-type]
        id_factory=lambda: next(ids),
        nonce_factory=lambda: next(nonces),
    )
    return service, registry, config, controls


def _request() -> SupervisedRunRequest:
    return SupervisedRunRequest(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=2,
        ticks_per_step=1,
        cohort_size=2,
    )


def test_prepared_enospc_authorization_is_handed_off_and_consumed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
    )
    service.reserve_enospc_preflight_cohort(_request())
    contract = service._load_contract("target-run")

    service._prepare_enospc_workspace(contract)
    authorization = service._take_enospc_fault_authorization(
        target_run_id="target-run",
        peer_run_id="peer-run",
    )

    assert authorization is controls.prepared_authorization
    assert authorization._consume(
        target_run_id="target-run",
        peer_run_id="peer-run",
    ) is FaultGate.ENOSPC
    with pytest.raises(FaultAuthorizationError, match="single-use"):
        authorization._consume(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )
    with pytest.raises(SupervisionServiceError, match="already handed off"):
        service._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )
    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in config.control_root.rglob("*.json")
    )
    assert "capability" not in serialized


def test_concurrent_enospc_handoff_has_exactly_one_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, _config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
    )
    service.reserve_enospc_preflight_cohort(_request())
    service._prepare_enospc_workspace(service._load_contract("target-run"))
    barrier = threading.Barrier(3)

    def take() -> Any:
        barrier.wait()
        try:
            return service._take_enospc_fault_authorization(
                target_run_id="target-run",
                peer_run_id="peer-run",
            )
        except BaseException as exc:  # noqa: BLE001 - retain competing outcome
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(take), executor.submit(take))
        barrier.wait()
        outcomes = [future.result() for future in futures]

    winners = [value for value in outcomes if value is controls.prepared_authorization]
    losers = [value for value in outcomes if isinstance(value, BaseException)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], SupervisionServiceError)
    assert "already handed off" in str(losers[0])


def test_concurrent_enospc_preparation_cannot_replace_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, _config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
    )
    service.reserve_enospc_preflight_cohort(_request())
    contract = service._load_contract("target-run")
    prepare_entered = threading.Event()
    release_prepare = threading.Event()
    original_prepare = controls.prepare_workspace

    def blocking_prepare(*, authorization: Any, target: Any) -> Mapping[str, Any]:
        prepare_entered.set()
        assert release_prepare.wait(timeout=5)
        return original_prepare(authorization=authorization, target=target)

    controls.prepare_workspace = blocking_prepare  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(service._prepare_enospc_workspace, contract)
        assert prepare_entered.wait(timeout=5)
        try:
            with pytest.raises(
                SupervisionServiceError,
                match="already prepared or preparing",
            ):
                service._prepare_enospc_workspace(contract)
        finally:
            release_prepare.set()
        first.result()

    authorization = service._take_enospc_fault_authorization(
        target_run_id="target-run",
        peer_run_id="peer-run",
    )
    assert authorization is controls.prepared_authorization
    assert controls.prepare_calls == 1


def test_mismatched_enospc_handoff_invalidates_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, _config, _controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
    )
    service.reserve_enospc_preflight_cohort(_request())
    service._prepare_enospc_workspace(service._load_contract("target-run"))

    with pytest.raises(LaunchEvidenceError, match="binding differs"):
        service._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="wrong-peer",
        )
    with pytest.raises(SupervisionServiceError, match="already handed off"):
        service._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )


def test_invalid_enospc_prepare_receipt_retains_no_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, _config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
    )
    service.reserve_enospc_preflight_cohort(_request())
    controls.malformed_receipt = True

    with pytest.raises(LaunchEvidenceError, match="receipt is noncanonical"):
        service._prepare_enospc_workspace(service._load_contract("target-run"))
    with pytest.raises(SupervisionServiceError, match="already handed off"):
        service._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )


def test_enospc_handoff_remains_default_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _service_owner, registry, config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
    )
    disabled = SupervisionService(
        registry=registry,
        config=replace(config, allow_test_workspace_fault_profiles=False),
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
        enospc_evidence_loader=controls,  # type: ignore[arg-type]
        enospc_workspace=controls,  # type: ignore[arg-type]
    )

    with pytest.raises(SupervisionConfigurationError, match="programmatic"):
        disabled.reserve_enospc_preflight_cohort(_request())
    with pytest.raises(SupervisionConfigurationError, match="programmatically"):
        disabled._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )
    assert not config.control_root.exists()


def test_enospc_post_cleanup_boundary_discards_unclaimed_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry, config, _controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("manager is unused"),
    )
    service.reserve_enospc_preflight_cohort(_request())
    service._prepare_enospc_workspace(service._load_contract("target-run"))
    record = registry.get("target-run")
    assert record is not None
    controller = service._enospc_post_cleanup_controller(
        record,
        config.control_root / "target-run",
    )
    assert controller is not None

    result = controller.cleanup()

    assert result["residue_absent"] is True
    with pytest.raises(SupervisionServiceError, match="already handed off"):
        service._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )


def test_service_manager_supervisor_mounts_before_artifacts_and_unmounts_before_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[str] = []
    supervisor = CallbackSupervisor(timeline)

    def manager_factory(**kwargs: Any) -> SupervisedRunManager:
        supervisor.registry = kwargs["registry"]
        runtime = FakeRuntime(kwargs["registry"].artifacts_root, timeline)
        return SupervisedRunManager(
            registry=kwargs["registry"],
            control_root=kwargs["control_root"],
            runtime_controller_factory=lambda _record, _run_dir: runtime,
            contract_factory=kwargs["contract_factory"],
            supervisor_factory=lambda: supervisor,
            post_cleanup_controller_factory=kwargs[
                "post_cleanup_controller_factory"
            ],
        )

    service, registry, config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=manager_factory,
    )
    controls.timeline = timeline
    launch = service.reserve_enospc_preflight_cohort(_request())

    result = service.run_reserved(launch.run_ids[0])

    assert result.status == "completed", (result.reason, timeline)
    assert registry.get("target-run").status == "completed"  # type: ignore[union-attr]
    assert not (config.artifacts_root / "target-run").exists()
    assert timeline == [
        "load_prelaunch",
        "mount",
        "runtime_prepare",
        "artifact_opened",
        "runtime_cleanup",
        "load_cleanup",
        "unmount",
        "cleanup_recorded",
        "terminal_pending",
    ]
    launch_payloads = [
        json.loads((config.control_root / run_id / "launch.json").read_text())
        for run_id in launch.run_ids
    ]
    assert [row["workspace_fault_profile"]["role"] for row in launch_payloads] == [
        "target",
        "peer",
    ]
    with pytest.raises(SupervisionServiceError, match="already handed off"):
        service._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )


def test_delayed_enospc_mount_finishes_before_either_cohort_manager_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[str] = []
    mount_entered = threading.Event()
    release_mount = threading.Event()
    reconcile_calls: list[str] = []

    class RecordingManager:
        def run(self, run_id: str) -> ManagedRunResult:
            timeline.append(f"manager:{run_id}")
            return ManagedRunResult(
                run_id=run_id,
                status="completed",
                finalized=True,
                recovered=False,
                action="run",
                returncode=0,
                control_dir=config.control_root / run_id,
                reason={"code": "completed"},
            )

        def reconcile(self, run_id: str) -> ManagedRunResult:
            reconcile_calls.append(run_id)
            raise AssertionError("a same-process prepared target must not reconcile")

    service, _registry, config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: RecordingManager(),
    )
    controls.timeline = timeline
    original_prepare = controls.prepare_workspace

    def delayed_prepare(*, authorization: Any, target: Any) -> Mapping[str, Any]:
        timeline.append("mount_entered")
        mount_entered.set()
        assert release_mount.wait(timeout=5)
        return original_prepare(authorization=authorization, target=target)

    controls.prepare_workspace = delayed_prepare  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.run_enospc_preflight_cohort, _request())
        assert mount_entered.wait(timeout=5)
        try:
            assert not any(item.startswith("manager:") for item in timeline)
        finally:
            release_mount.set()
        results = future.result(timeout=5)

    assert set(results) == {"target-run", "peer-run"}
    assert controls.prepare_calls == 1
    assert reconcile_calls == []
    mount_index = timeline.index("mount")
    assert mount_index < timeline.index("manager:target-run")
    assert mount_index < timeline.index("manager:peer-run")


def test_enospc_post_cleanup_failure_has_parent_cleanup_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[str] = []
    supervisor = CallbackSupervisor(timeline)

    def manager_factory(**kwargs: Any) -> SupervisedRunManager:
        supervisor.registry = kwargs["registry"]
        return SupervisedRunManager(
            registry=kwargs["registry"],
            control_root=kwargs["control_root"],
            runtime_controller_factory=lambda _record, _run_dir: FakeRuntime(
                kwargs["registry"].artifacts_root,
                timeline,
            ),
            contract_factory=kwargs["contract_factory"],
            supervisor_factory=lambda: supervisor,
            post_cleanup_controller_factory=kwargs[
                "post_cleanup_controller_factory"
            ],
        )

    service, registry, _config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=manager_factory,
    )
    controls.timeline = timeline
    controls.fail_cleanup = True
    launch = service.reserve_enospc_preflight_cohort(_request())

    result = service.run_reserved(launch.run_ids[0])

    assert result.status == "failed"
    assert result.reason["code"] == "parent_cleanup_failed"
    record = registry.get("target-run")
    assert record is not None
    assert record.status == "failed"
    assert "cleanup_completed_at" not in record.metadata
    assert timeline.index("runtime_cleanup") < timeline.index("unmount")
    assert timeline.index("unmount") < timeline.index("cleanup_recorded")


def test_interrupted_pre_manager_mount_reconciles_without_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[str] = []

    class CrashingManager:
        def run(self, _run_id: str) -> ManagedRunResult:
            timeline.append("manager_crash")
            raise RuntimeError("synthetic service-to-manager crash")

        def reconcile(self, _run_id: str) -> ManagedRunResult:
            raise AssertionError("first service must not reconcile")

    def crashing_factory(**_kwargs: Any) -> CrashingManager:
        return CrashingManager()

    service, registry, config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=crashing_factory,
    )
    controls.timeline = timeline
    service.reserve_enospc_preflight_cohort(_request())
    with pytest.raises(RuntimeError, match="service-to-manager crash"):
        service.run_reserved("target-run")
    assert (config.artifacts_root / "target-run").exists()
    assert registry.get("target-run").status == "pending"  # type: ignore[union-attr]
    with pytest.raises(SupervisionServiceError, match="already handed off"):
        service._take_enospc_fault_authorization(
            target_run_id="target-run",
            peer_run_id="peer-run",
        )

    class RecoveryManager:
        def run(self, _run_id: str) -> ManagedRunResult:
            raise AssertionError("recovery must not resume the target")

        def reconcile(self, run_id: str) -> ManagedRunResult:
            record = registry.get(run_id)
            assert record is not None
            return ManagedRunResult(
                run_id=run_id,
                status=record.status,
                finalized=True,
                recovered=True,
                action="already_terminal",
                returncode=None,
                control_dir=config.control_root / run_id,
                reason=record.metadata.get("terminal_reason") or {},
            )

    recovered = SupervisionService(
        registry=registry,
        config=config,
        manager_factory=lambda **_kwargs: RecoveryManager(),
        enospc_evidence_loader=controls,  # type: ignore[arg-type]
        enospc_workspace=controls,  # type: ignore[arg-type]
    )
    results = recovered.reconcile_all()

    result = results["target-run"]
    assert isinstance(result, ManagedRunResult)
    assert result.status == "failed"
    record = registry.get("target-run")
    assert record is not None
    assert record.metadata["terminal_reason"]["code"] == (
        "enospc_prelaunch_owner_lost"
    )
    assert "cleanup_completed_at" in record.metadata
    assert controls.prepare_calls == 1
    assert controls.reconcile_calls == 1
    assert timeline[-2:] == ["load_cleanup", "reconcile_unmount"]
    assert not (config.artifacts_root / "target-run").exists()


@pytest.mark.parametrize(
    "crash_phase",
    [
        "post_cleanup",
        "runtime_removed",
        "cleanup_recorded",
        "classified",
        "cleanup_verified",
        "cleanup_completed",
        "immutable",
        "terminal_pending",
    ],
)
def test_dead_owner_after_attested_unmount_terminalizes_supervisor_lost_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_phase: str,
) -> None:
    timeline: list[str] = []
    service, registry, config, controls = _service(
        tmp_path,
        monkeypatch,
        manager_factory=lambda **_kwargs: pytest.fail("service manager is unused"),
    )
    controls.timeline = timeline
    service.reserve_enospc_preflight_cohort(_request())
    contract = service._load_contract("target-run")
    service._prepare_enospc_workspace(contract)
    assert registry.claim_pending_run(
        "target-run",
        started_at=datetime(2026, 8, 16, 21, 0, tzinfo=UTC),
    )
    run_dir = config.control_root / "target-run"
    attempt_dir = run_dir / "attempts" / "attempt-0001"
    attempt_dir.mkdir(parents=True)
    owner_pid = 999_901
    child_pid = 999_902
    environment = contract.environment_identity()

    def digest(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    (run_dir / "owner.json").write_text(
        json.dumps(
            {
                "schema": "fortgym.supervised-manager-owner/v1",
                "run_id": "target-run",
                "state": "active",
                "manager_pid": owner_pid,
                "manager_start_ticks": 123_456,
                "identity_bound": True,
                "contract_sha256": contract.contract_sha256,
                "nonce_sha256": hashlib.sha256(
                    contract.nonce.encode("ascii")
                ).hexdigest(),
                "environment_identity_sha256": digest(environment),
                "observed_registry_status": "running",
                "attempt_dir": str(attempt_dir.resolve()),
                "updated_at": "2026-08-16T21:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    sequence = iter(range(1, 100))

    def row(event: str, **fields: Any) -> dict[str, Any]:
        position = next(sequence)
        return {
            "schema": "fortgym.process-supervisor-attempt/v1",
            "at": f"2026-08-16T21:00:{position:02d}+00:00",
            "monotonic_ns": position,
            "run_id": "target-run",
            "supervisor_pid": owner_pid,
            "event": event,
            **fields,
        }

    chain_identity = {
        "run_id": "target-run",
        "contract_sha256": contract.contract_sha256,
        "nonce_sha256": hashlib.sha256(
            contract.nonce.encode("ascii")
        ).hexdigest(),
        "environment_identity_sha256": digest(environment),
        "child_pid": child_pid,
        "port": contract.port,
    }
    primary_reason = {"code": "child_nonzero_exit", "returncode": 1}
    rows = [
        row(
            "attempt_started",
            scripted=True,
            provider_enabled=False,
            argv0=sys.executable,
            port=contract.port,
            environment_identity=environment,
            cotenancy=contract.cotenancy(),
            supervisor_runtime={"pid": owner_pid},
        ),
        row("child_started", child_pid=child_pid),
        row(
            "terminal_pending_cleanup",
            identity=chain_identity,
            primary_terminal_class="child_exit",
            primary_reason_sha256=digest(primary_reason),
        ),
    ]
    snapshot = {
        "schema": "fortgym.process-supervisor-evidence-snapshot/v1",
        "identity": chain_identity,
        "primary_terminal_class": "child_exit",
        "primary_reason": primary_reason,
        "prepare": {},
        "termination": {},
        "files": {},
        "fault_snapshot": None,
        "fault_snapshot_error": None,
    }
    snapshot_path = attempt_dir / "evidence-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    rows.extend(
        [
            row(
                "evidence_snapshot_completed",
                identity=chain_identity,
                ok=True,
                snapshot_path=str(snapshot_path),
                snapshot_sha256=snapshot_sha256,
                fault_snapshot_attached=False,
                error=None,
            ),
            row(
                "harness_process_group_reaped",
                identity=chain_identity,
                ok=True,
                skipped=False,
                child_pid=child_pid,
                group_exists=False,
            ),
        ]
    )
    journal = attempt_dir / "attempt-journal.jsonl"
    journal.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in rows),
        encoding="utf-8",
    )
    cleanup_target = controls.load_enospc_cleanup_target(
        "target-run", peer_run_id="peer-run"
    )
    unmounted = controls.cleanup_workspace(target=cleanup_target)
    cleanup = {
        "ok": True,
        "stages": [
            {"stage": "post_callback", "ok": True, "details": unmounted},
        ],
    }
    terminal_draft = {
        "schema": "fortgym.process-supervisor-terminal/v1",
        "run_id": "target-run",
        "terminal_class": "child_exit",
        "primary_terminal_class": "child_exit",
        "primary_reason": primary_reason,
        "returncode": 1,
        "child_pid": child_pid,
        "child_signal": None,
        "port": contract.port,
        "environment_identity": environment,
        "runtime_cleanup_required": True,
        "prepare": {},
        "termination": {},
        "reason": primary_reason,
        "cleanup": cleanup,
        "fault_classification": {
            "schema": "fortgym.runtime-fault-classification/v1",
            "attempted": False,
            "ok": True,
            "classified": False,
            "skipped": "classifier_not_configured",
        },
    }
    phase_order = {
        "post_cleanup": 0,
        "runtime_removed": 1,
        "cleanup_recorded": 2,
        "classified": 3,
        "cleanup_verified": 4,
        "cleanup_completed": 5,
        "immutable": 6,
        "terminal_pending": 7,
    }
    durable = [
        row("post_cleanup_started"),
        row("post_cleanup_completed", ok=True, details=unmounted),
    ]
    phase = phase_order[crash_phase]
    if phase >= 1:
        durable.append(
            row(
                "runtime_container_removed",
                identity=chain_identity,
                ok=True,
                skipped=False,
                container_absent=True,
                listener_absent=True,
            )
        )
    if phase >= 2:
        durable.append(row("cleanup_recorded", cleanup=cleanup))
    if phase >= 3:
        draft_path = attempt_dir / "terminal-draft.json"
        draft_path.write_text(json.dumps(terminal_draft), encoding="utf-8")
        durable.append(
            row(
                "runtime_fault_classification_recorded",
                fault_classification=terminal_draft["fault_classification"],
                terminal_draft_path=str(draft_path),
                terminal_draft_sha256=hashlib.sha256(
                    draft_path.read_bytes()
                ).hexdigest(),
            )
        )
    cleanup_sha256 = digest(cleanup)
    if phase >= 4:
        durable.append(
            row(
                "cleanup_verified",
                identity=chain_identity,
                ok=True,
                cleanup_sha256=cleanup_sha256,
            )
        )
    if phase >= 5:
        durable.append(
            row(
                "cleanup_completed",
                identity=chain_identity,
                ok=True,
                cleanup_sha256=cleanup_sha256,
            )
        )
    if phase >= 6:
        durable.append(
            row(
                "immutable_terminal_classification",
                identity=chain_identity,
                terminal_class="child_exit",
                reason_sha256=digest(primary_reason),
                cleanup_sha256=cleanup_sha256,
                evidence_snapshot_sha256=snapshot_sha256,
            )
        )
    if phase >= 7:
        durable.append(
            row("terminal_pending", terminal_class="child_exit", cleanup_ok=True)
        )
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(
            "".join(json.dumps(value, sort_keys=True) + "\n" for value in durable)
        )

    # Use the real immutable-evidence loader for the recovery-side ENOSPC
    # authorization.  It accepts every exact progressive suffix above and no
    # malformed or reordered approximation.
    cleanup_loader = OwnedRunEvidenceLoader(
        control_root=config.control_root,
        db_path=config.db_path,
        artifacts_root=config.artifacts_root,
        process_ids=lambda: (),
        mount_probe=lambda _path: None,
    )
    cleanup_loader.load_enospc_cleanup_target(
        "target-run", peer_run_id="peer-run"
    )
    service._enospc_evidence_loader = cleanup_loader
    timeline.clear()
    runtime = FakeRuntime(config.artifacts_root, timeline)
    original_terminalize = registry.record_terminal_failure

    def terminalize(*args: Any, **kwargs: Any) -> Any:
        assert "reconcile_unmount" in timeline
        timeline.append("registry_terminal")
        return original_terminalize(*args, **kwargs)

    monkeypatch.setattr(registry, "record_terminal_failure", terminalize)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=config.control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=service._run_spec,
        post_cleanup_controller_factory=service._enospc_post_cleanup_controller,
        ownership_probe=lambda _owner: False,
    )

    first = manager.reconcile("target-run")
    journal_after_first = journal.read_bytes()
    second = manager.reconcile("target-run")

    assert first.finalized is True
    assert first.status == "failed"
    assert first.reason["code"] in {"supervisor_lost", "child_nonzero_exit"}
    assert second.action == "already_terminal"
    assert journal.read_bytes() == journal_after_first
    assert controls.reconcile_calls == 1
    assert timeline == [
        "runtime_reconcile",
        "reconcile_unmount",
        "registry_terminal",
    ]
    record = registry.get("target-run")
    assert record is not None and record.status == "failed"
    assert "cleanup_completed_at" in record.metadata
    events = [json.loads(line)["event"] for line in journal.read_text().splitlines()]
    exact_chain = [
        "terminal_pending_cleanup",
        "evidence_snapshot_completed",
        "harness_process_group_reaped",
        "runtime_container_removed",
        "cleanup_verified",
        "cleanup_completed",
        "immutable_terminal_classification",
    ]
    assert [event for event in events if event in exact_chain] == exact_chain
    assert events.count("terminal_pending") == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeout_seconds", True),
        ("term_grace_seconds", "1"),
        ("poll_interval_seconds", object()),
    ],
)
def test_service_config_rejects_coerced_timeout_values(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    entrypoint = repo / "entrypoint"
    entrypoint.write_text("#!/bin/sh\n")
    entrypoint.chmod(0o700)
    dfroot = tmp_path / "dfroot"
    dfroot.mkdir()
    kwargs: dict[str, Any] = {
        "db_path": (tmp_path / "db.sqlite3").resolve(),
        "artifacts_root": (tmp_path / "artifacts").resolve(),
        "control_root": (tmp_path / "control").resolve(),
        "repo_root": repo.resolve(),
        "python_executable": Path(sys.executable).absolute(),
        "entrypoint_path": entrypoint.resolve(),
        "dfroot": dfroot.resolve(),
        "code_sha256": "a" * 64,
        field: value,
    }
    with pytest.raises(Exception, match=field):
        ServiceConfig(**kwargs)
