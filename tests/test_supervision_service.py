from __future__ import annotations

import json
import stat
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest

from fort_gym.bench.config import get_settings
from fort_gym.bench.experiment.config import load_experiment_config
from fort_gym.bench.run.runtime_contract import ProviderPolicy
from fort_gym.bench.run.runtime_controller import RuntimeFaultProfile
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import ManagedRunResult
from fort_gym.bench.run.supervision_service import (
    SUPERVISION_MODE,
    LaunchEvidenceError,
    RunNotOwnedError,
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionConfigurationError,
    SupervisionRequestError,
    SupervisionService,
)


class FakeManager:
    def __init__(self) -> None:
        self.run_calls: list[str] = []
        self.reconcile_calls: list[str] = []
        self.factory_kwargs: list[dict[str, Any]] = []

    def factory(self, **kwargs: Any) -> FakeManager:
        self.factory_kwargs.append(kwargs)
        return self

    def run(self, run_id: str) -> ManagedRunResult:
        self.run_calls.append(run_id)
        return _managed_result(run_id, action="run")

    def reconcile(self, run_id: str) -> ManagedRunResult:
        self.reconcile_calls.append(run_id)
        return _managed_result(run_id, action="reconcile", recovered=True)


class ConcurrentFakeManager(FakeManager):
    def __init__(self) -> None:
        super().__init__()
        self.barrier = threading.Barrier(2)
        self.thread_ids: set[int] = set()

    def run(self, run_id: str) -> ManagedRunResult:
        self.run_calls.append(run_id)
        self.thread_ids.add(threading.get_ident())
        self.barrier.wait(timeout=2.0)
        return _managed_result(run_id, action="run")


class ImmediateThread:
    def __init__(self, *, target, args, name: str, daemon: bool) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        self.target(*self.args)


class DeferredThread(ImmediateThread):
    instances: ClassVar[list[DeferredThread]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.started = False
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True


class FakeScreenClient:
    def __init__(self, calls: dict[str, Any], **kwargs: Any) -> None:
        calls["kwargs"] = kwargs
        calls["client"] = self
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def get_screen(self) -> dict[str, Any]:
        assert self.connected
        return {"width": 2, "height": 1, "tiles": [[65, 7, 0], [66, 7, 0]]}

    def close(self) -> None:
        self.closed = True


class FakePreReadinessOomMonitor:
    def arm(self, _created) -> dict[str, Any]:
        return {
            "schema": "fortgym.m1b-pre-readiness-oom-monitor-arm/v1",
            "ok": True,
            "peer_readiness_sha256": "e" * 64,
        }

    def finalize(self, _stopped) -> dict[str, Any]:
        return {
            "schema": "fortgym.m1b-pre-readiness-oom-monitor-finalize/v1",
            "ok": True,
        }


class FakeOomMonitorFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def __call__(self, target, peer) -> FakePreReadinessOomMonitor:
        self.calls.append((target, peer))
        return FakePreReadinessOomMonitor()


def _managed_result(
    run_id: str,
    *,
    action: str,
    recovered: bool = False,
) -> ManagedRunResult:
    return ManagedRunResult(
        run_id=run_id,
        status="completed",
        finalized=True,
        recovered=recovered,
        action=action,
        returncode=0,
        control_dir=Path("/tmp") / run_id,
        reason={"code": f"fake_{action}"},
    )


def _ids(*values: str):
    iterator = iter(values)
    return lambda: next(iterator)


def _nonces(count: int):
    iterator = iter(f"{index + 1:032x}" for index in range(count))
    return lambda: next(iterator)


def _build_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ids: tuple[str, ...] = ("run-01",),
    openrouter_key: str | None = None,
    thread_factory=ImmediateThread,
    configured_artifacts: Path | None = None,
    settings_artifacts: Path | None = None,
    allow_test_runtime_fault_profiles: bool = False,
    pre_readiness_oom_monitor_factory=None,
    provider_network_controller_factory=None,
) -> tuple[SupervisionService, RunRegistry, ServiceConfig, FakeManager]:
    configured_artifacts = configured_artifacts or tmp_path / "artifacts"
    settings_artifacts = settings_artifacts or configured_artifacts
    monkeypatch.setenv("ARTIFACTS_DIR", str(settings_artifacts))
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    entrypoint = repo_root / "runtime_entrypoint.sh"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    entrypoint.chmod(0o700)
    dfroot = tmp_path / "dfroot"
    dfroot.mkdir(parents=True, exist_ok=True)
    config = ServiceConfig(
        db_path=(tmp_path / "runs.sqlite3").resolve(),
        artifacts_root=configured_artifacts.resolve(),
        control_root=(tmp_path / "control").resolve(),
        repo_root=repo_root.resolve(),
        python_executable=Path(sys.executable).resolve(),
        entrypoint_path=entrypoint.resolve(),
        dfroot=dfroot.resolve(),
        code_sha256="a" * 64,
        default_seed_save="seed_region3_fresh",
        runtime_save_prefix="m1b",
        base_port=58_000,
        max_cohort=8,
        openrouter_api_key=openrouter_key,
        allow_test_runtime_fault_profiles=allow_test_runtime_fault_profiles,
    )
    registry = RunRegistry(db_path=config.db_path, recover_interrupted=False)
    manager = FakeManager()
    service = SupervisionService(
        registry=registry,
        config=config,
        manager_factory=manager.factory,
        thread_factory=thread_factory,
        pre_readiness_oom_monitor_factory=pre_readiness_oom_monitor_factory,
        provider_network_controller_factory=provider_network_controller_factory,
        id_factory=_ids(*ids),
        nonce_factory=_nonces(len(ids)),
    )
    return service, registry, config, manager


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()  # type: ignore[attr-defined]
    DeferredThread.instances.clear()
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]
    DeferredThread.instances.clear()


def test_reserve_persists_complete_symmetric_secret_free_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-key-must-not-leak")
    service, registry, config, _manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("run-z", "run-a", "run-m"),
    )
    request = SupervisedRunRequest(
        backend="mock",
        model="random",
        max_steps=3,
        ticks_per_step=7,
        cohort_size=3,
        seed_save="seed-explicit",
        runtime_save_prefix="cohort",
    )

    launch = service.reserve(request)

    assert launch.run_ids == ("run-z", "run-a", "run-m")
    assert tuple(record.run_id for record in launch.records) == launch.run_ids
    sorted_ids = tuple(sorted(launch.run_ids))
    runtime_saves: set[str] = set()
    for run_id in launch.run_ids:
        record = registry.get(run_id)
        assert record is not None
        assert record.supervision_mode == SUPERVISION_MODE
        assert record.status == "pending"
        assert record.seed_save == "seed-explicit"
        assert record.runtime_save == f"cohort-{run_id}"
        runtime_saves.add(str(record.runtime_save))

        run_dir = config.control_root / run_id
        launch_path = run_dir / "launch.json"
        config_path = run_dir / "experiment.json"
        assert stat.S_IMODE(launch_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
        launch_payload = json.loads(launch_path.read_text(encoding="utf-8"))
        serialized = json.dumps(launch_payload, sort_keys=True)
        assert "ambient-key-must-not-leak" not in serialized
        identity = launch_payload["contract"]
        slot = sorted_ids.index(run_id)
        assert identity["rpc"]["port"] == 58_000 + slot
        assert identity["cotenancy"]["slot"] == slot
        assert identity["cotenancy"]["cohort_size"] == 3
        assert set(identity["cotenancy"]["peer_run_ids"]) == set(sorted_ids) - {run_id}

        experiment = load_experiment_config(config_path)
        assert experiment.runs_per_variant == 1
        assert len(experiment.variants) == 1
        assert experiment.base_config.backend == "mock"
        assert experiment.base_config.model == "random"
        assert experiment.base_config.seed_save == "seed-explicit"
        assert experiment.base_config.runtime_save == f"cohort-{run_id}"
    assert len(runtime_saves) == 3
    assert not config.artifacts_root.exists()


def test_oom_preflight_reservation_is_programmatic_only_and_reconstructs_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SupervisedRunRequest(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=5,
        ticks_per_step=10,
        cohort_size=2,
    )
    disabled, disabled_registry, disabled_config, _manager = _build_service(
        tmp_path / "disabled",
        monkeypatch,
        ids=("disabled-target", "disabled-peer"),
    )
    monkeypatch.setenv("FORT_GYM_M1B_ALLOW_TEST_RUNTIME_FAULT_PROFILES", "1")
    with pytest.raises(
        SupervisionConfigurationError,
        match="programmatic authorization",
    ):
        disabled.reserve_oom_preflight_cohort(request)
    assert disabled_registry.list() == []
    assert not disabled_config.control_root.exists()

    unmonitored, unmonitored_registry, unmonitored_config, _manager = _build_service(
        tmp_path / "unmonitored",
        monkeypatch,
        ids=("unmonitored-target", "unmonitored-peer"),
        allow_test_runtime_fault_profiles=True,
    )
    with pytest.raises(SupervisionConfigurationError, match="host monitor factory"):
        unmonitored.reserve_oom_preflight_cohort(request)
    assert unmonitored_registry.list() == []
    assert not unmonitored_config.control_root.exists()

    monitor_factory = FakeOomMonitorFactory()
    service, registry, config, manager = _build_service(
        tmp_path / "enabled",
        monkeypatch,
        ids=("oom-target", "oom-peer"),
        allow_test_runtime_fault_profiles=True,
        pre_readiness_oom_monitor_factory=monitor_factory,
    )
    launch = service.reserve_oom_preflight_cohort(request)

    assert launch.run_ids == ("oom-target", "oom-peer")
    expected_profiles = {
        "oom-target": {
            "schema": "fortgym.m1b-runtime-fault-profile/v1",
            "cohort_kind": "oom_256m_target_peer",
            "role": "target",
            "name": "oom_256m",
            "memory_bytes": 256 * 1024 * 1024,
            "memory_swap_bytes": 256 * 1024 * 1024,
            "test_only": True,
        },
        "oom-peer": {
            "schema": "fortgym.m1b-runtime-fault-profile/v1",
            "cohort_kind": "oom_256m_target_peer",
            "role": "peer",
            "name": "normal_4g",
            "memory_bytes": 4 * 1024 * 1024 * 1024,
            "memory_swap_bytes": 4 * 1024 * 1024 * 1024,
            "test_only": True,
        },
    }
    for run_id, expected in expected_profiles.items():
        launch_payload = json.loads(
            (config.control_root / run_id / "launch.json").read_text()
        )
        assert launch_payload["runtime_fault_profile"] == expected

    target_record = registry.get("oom-target")
    peer_record = registry.get("oom-peer")
    assert target_record is not None
    assert peer_record is not None
    target_controller = service._runtime_controller(
        target_record,
        config.control_root / "oom-target",
    )
    peer_controller = service._runtime_controller(
        peer_record,
        config.control_root / "oom-peer",
    )
    assert target_controller.fault_profile is RuntimeFaultProfile.OOM_256M
    assert target_controller.pre_readiness_oom_monitor is not None
    assert target_controller.memory_bytes == 256 * 1024 * 1024
    assert peer_controller.fault_profile is None
    assert peer_controller.memory_bytes == 4 * 1024 * 1024 * 1024
    assert len(monitor_factory.calls) == 1
    assert monitor_factory.calls[0][0].run_id == "oom-target"
    assert monitor_factory.calls[0][1].run_id == "oom-peer"
    assert manager.run_calls == []

    disabled_recovery = SupervisionService(
        registry=registry,
        config=replace(config, allow_test_runtime_fault_profiles=False),
        manager_factory=manager.factory,
    )
    with pytest.raises(LaunchEvidenceError, match="forbidden by service config"):
        disabled_recovery.run_reserved("oom-target")


def test_public_reservation_never_persists_runtime_fault_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, config, _manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("normal-a", "normal-b"),
        allow_test_runtime_fault_profiles=True,
    )
    launch = service.reserve(
        SupervisedRunRequest(
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=1,
            ticks_per_step=1,
            cohort_size=2,
        )
    )

    for run_id in launch.run_ids:
        payload = json.loads((config.control_root / run_id / "launch.json").read_text())
        assert "runtime_fault_profile" not in payload


def test_oom_preflight_enters_both_reserved_managers_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_factory = FakeOomMonitorFactory()
    service, _registry, _config, _manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("concurrent-target", "concurrent-peer"),
        allow_test_runtime_fault_profiles=True,
        pre_readiness_oom_monitor_factory=monitor_factory,
    )
    manager = ConcurrentFakeManager()
    service._manager_factory = manager.factory
    request = SupervisedRunRequest(
        backend="dfhack",
        model="dfhack-governed-scripted",
        max_steps=5,
        ticks_per_step=10,
        cohort_size=2,
    )

    results = service.run_oom_preflight_cohort(request)

    assert tuple(results) == ("concurrent-target", "concurrent-peer")
    assert set(manager.run_calls) == set(results)
    assert len(manager.thread_ids) == 2
    assert all(result.status == "completed" for result in results.values())


@pytest.mark.parametrize(
    "run_request",
    [
        SupervisedRunRequest("mock", "random", 1, 1, safe=False),
        SupervisedRunRequest("mock", "unknown", 1, 1),
        SupervisedRunRequest("dfhack", "random", 1, 1),
        SupervisedRunRequest("unknown", "random", 1, 1),
        SupervisedRunRequest("mock", "random", 1, 1, memory_window=1),
        SupervisedRunRequest("mock", "random", 1, 1, cohort_size=9),
        SupervisedRunRequest("dfhack", "dfhack-governed-llm", 1, 1),
    ],
)
def test_unsafe_or_unsupported_request_is_rejected_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_request: SupervisedRunRequest,
) -> None:
    service, registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("never-written",)
    )

    with pytest.raises((SupervisionRequestError, SupervisionConfigurationError)):
        service.reserve(run_request)

    assert registry.list() == []
    assert not config.control_root.exists()


def test_pinned_governed_alias_mismatch_is_rejected_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "dedicated-test-key"
    service, registry, config, _manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("never-written",),
        openrouter_key=key,
    )
    provider = ProviderPolicy.openrouter(
        model="different/provider-model",
        provider_name="provider-a",
        api_key=key,
        max_total_tokens=100,
        max_cost_usd=1.0,
    )
    request = SupervisedRunRequest(
        "dfhack",
        "dfhack-governed-llm-gpt55",
        1,
        1,
        provider_policy=provider,
    )

    with pytest.raises(SupervisionRequestError, match="requires provider model"):
        service.reserve(request)

    assert registry.list() == []
    assert not config.control_root.exists()


def test_dedicated_provider_key_is_required_and_never_loaded_from_ambient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-provider-key")
    service, registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("never-written",), openrouter_key=None
    )
    provider = ProviderPolicy.openrouter(
        model="openai/gpt-5.5",
        provider_name="provider-a",
        api_key="ambient-provider-key",
        max_total_tokens=100,
        max_cost_usd=1.0,
    )

    with pytest.raises(SupervisionConfigurationError, match="dedicated"):
        service.reserve(
            SupervisedRunRequest(
                "dfhack",
                "dfhack-governed-llm-gpt55",
                1,
                1,
                provider_policy=provider,
            )
        )

    assert registry.list() == []
    assert not config.control_root.exists()


def test_provider_enabled_launch_files_redact_dedicated_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "dedicated-provider-key-that-must-not-be-persisted"
    service, _registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("provider-run",), openrouter_key=key
    )
    provider = ProviderPolicy.openrouter(
        model="custom/provider-model",
        provider_name="provider-a",
        api_key=key,
        max_total_tokens=100,
        max_cost_usd=1.0,
    )

    service.reserve(
        SupervisedRunRequest(
            "dfhack",
            "dfhack-governed-llm",
            1,
            1,
            provider_policy=provider,
        )
    )

    for path in (config.control_root / "provider-run").iterdir():
        if path.is_file():
            assert key not in path.read_text(encoding="utf-8")


def test_run_reserved_builds_exact_mock_worker_contract_without_gameplay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORT_GYM_M1B_PROVIDER_NETWORK_ENABLED", "1")
    service, registry, config, manager = _build_service(
        tmp_path, monkeypatch, ids=("mock-run",)
    )
    service.reserve(SupervisedRunRequest("mock", "fake", 2, 4))

    result = service.run_reserved("mock-run")

    assert result.action == "run"
    assert manager.run_calls == ["mock-run"]
    assert len(manager.factory_kwargs) == 1
    seams = manager.factory_kwargs[0]
    assert "provider_network_controller_factory" not in seams
    record = registry.get("mock-run")
    assert record is not None
    run_dir = config.control_root / "mock-run"
    controller = seams["runtime_controller_factory"](record, run_dir)
    assert controller.prepare()["runtime"] == "none"
    assert controller.cleanup()["ok"] is True
    assert controller.reconcile()["noop"] is True

    attempt_dir = run_dir / "attempts" / "attempt-0001"
    spec = seams["contract_factory"](record, attempt_dir, controller)
    assert spec.run_id == "mock-run"
    assert spec.artifact_dir == attempt_dir
    assert spec.argv == (
        str(config.python_executable),
        "-m",
        "fort_gym.bench.cli",
        "experiment",
        str(run_dir / "experiment.json"),
        "--external-run-id",
        "mock-run",
    )
    assert spec.env["FORT_GYM_RUN_ID"] == "mock-run"
    assert spec.env["FORT_GYM_NETWORK_POLICY"] == "deny-inet"
    assert "OPENROUTER_API_KEY" not in spec.env


def test_provider_network_service_factory_is_programmatic_strict_and_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory_calls: list[tuple[Any, ...]] = []
    sentinel = object()

    def provider_network_factory(*args: Any) -> Any:
        factory_calls.append(args)
        return sentinel

    service, registry, config, manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("provider-network-run",),
        provider_network_controller_factory=provider_network_factory,
    )
    launch = service.reserve(
        SupervisedRunRequest(
            "dfhack",
            "dfhack-governed-scripted",
            1,
            1,
        )
    )
    assert launch.run_ids == ("provider-network-run",)

    service._manager()
    seams = manager.factory_kwargs[-1]
    callback = seams["provider_network_controller_factory"]
    record = registry.get("provider-network-run")
    assert record is not None
    run_dir = config.control_root / record.run_id
    runtime_controller = object()
    spec = seams["contract_factory"](
        record,
        run_dir / "attempts" / "attempt-0001",
        runtime_controller,
    )

    assert callback(record, run_dir, runtime_controller, spec) is sentinel
    assert len(factory_calls) == 1
    contract, observed_dir, observed_runtime, observed_spec = factory_calls[0]
    assert contract.run_id == record.run_id
    assert contract.nonce
    assert observed_dir == run_dir
    assert observed_runtime is runtime_controller
    assert observed_spec is spec
    public_identity = service.environment_identity(record.run_id)
    assert "nonce" not in public_identity["rpc"]
    assert public_identity["rpc"]["nonce_attested"] is True

    rejected, rejected_registry, rejected_config, _ = _build_service(
        tmp_path / "rejected",
        monkeypatch,
        ids=("provider-network-rejected",),
        provider_network_controller_factory=provider_network_factory,
    )
    with pytest.raises(SupervisionRequestError, match="provider-free scripted DFHack"):
        rejected.reserve(SupervisedRunRequest("mock", "fake", 1, 1))
    assert rejected_registry.list() == []
    assert not rejected_config.control_root.exists()


def test_launch_async_starts_exactly_one_manager_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, registry, _config, manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("async-a",),
        thread_factory=ImmediateThread,
    )

    launch = service.launch_async(SupervisedRunRequest("mock", "random", 1, 1))

    assert launch.run_ids == ("async-a",)
    assert manager.run_calls == ["async-a"]
    assert {record.run_id for record in registry.list()} == {"async-a"}


def test_launch_async_terminalizes_manager_factory_failure_before_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, registry, _config, manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("async-preclaim-failure",),
        thread_factory=ImmediateThread,
    )

    def fail_manager_factory(**_kwargs: Any) -> Any:
        raise RuntimeError("synthetic manager factory failure")

    monkeypatch.setattr(service, "_manager_factory", fail_manager_factory)

    launch = service.launch_async(SupervisedRunRequest("mock", "random", 1, 1))

    assert launch.run_ids == ("async-preclaim-failure",)
    assert manager.run_calls == []
    record = registry.get("async-preclaim-failure")
    assert record is not None
    assert record.status == "failed"
    assert record.ended_at is not None
    assert record.metadata["terminal_reason"]["code"] == (
        "manager_async_preclaim_failed"
    )
    assert record.metadata["terminal_reason"]["error"] == {
        "type": "RuntimeError",
        "message": "synthetic manager factory failure",
    }
    assert "cleanup_completed_at" in record.metadata


def test_convenience_launchers_reject_cohorts_before_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, registry, config, _manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("never-a", "never-b"),
    )
    request = SupervisedRunRequest("mock", "random", 1, 1, cohort_size=2)

    with pytest.raises(SupervisionRequestError, match="single-run only"):
        service.launch_async(request)
    with pytest.raises(SupervisionRequestError, match="single-run only"):
        service.run_blocking(request)

    assert registry.list() == []
    assert not config.control_root.exists()


def test_reconcile_all_touches_only_owned_nonterminal_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, registry, config, manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("pending-owned", "running-owned", "terminal-owned"),
        thread_factory=ImmediateThread,
    )
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1, cohort_size=3))
    assert registry.claim_pending_run("running-owned", started_at=_fixed_datetime())
    (config.control_root / "running-owned" / "attempts" / "attempt-0001").mkdir(
        parents=True
    )
    terminal = registry.get("terminal-owned")
    assert terminal is not None
    registry.record_terminal_failure(
        terminal.run_id,
        terminal_reason={"code": "test_terminal"},
        step=0,
        ended_at=_fixed_datetime(),
    )
    registry.create(
        run_id="unowned",
        backend="mock",
        model="random",
        max_steps=1,
        ticks_per_step=1,
    )

    results = service.reconcile_all()

    assert results["pending-owned"] == "pending_restarted"
    assert results["running-owned"].action == "reconcile"  # type: ignore[union-attr]
    assert "terminal-owned" not in results
    assert "unowned" not in results
    assert manager.run_calls == ["pending-owned"]
    assert manager.reconcile_calls == ["running-owned"]


def test_pending_recovery_terminalizes_manager_factory_failure_before_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, registry, _config, manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=("recovery-preclaim-failure",),
        thread_factory=ImmediateThread,
    )
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1))

    def fail_manager_factory(**_kwargs: Any) -> Any:
        raise RuntimeError("synthetic recovery manager factory failure")

    monkeypatch.setattr(service, "_manager_factory", fail_manager_factory)

    results = service.reconcile_all()

    assert results == {"recovery-preclaim-failure": "pending_restarted"}
    assert manager.run_calls == []
    record = registry.get("recovery-preclaim-failure")
    assert record is not None
    assert record.status == "failed"
    assert record.ended_at is not None
    assert record.metadata["terminal_reason"]["code"] == (
        "manager_recovery_preclaim_failed"
    )
    assert record.metadata["terminal_reason"]["error"] == {
        "type": "RuntimeError",
        "message": "synthetic recovery manager factory failure",
    }
    assert "cleanup_completed_at" in record.metadata


@pytest.mark.parametrize("launch_path", ["async", "recovery"])
def test_thread_preclaim_failure_with_attempt_evidence_remains_nonterminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launch_path: str,
) -> None:
    run_id = f"{launch_path}-attempt-present"
    service, registry, config, manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=(run_id,),
        thread_factory=DeferredThread,
    )

    def fail_manager_factory(**_kwargs: Any) -> Any:
        raise RuntimeError("synthetic post-attempt manager factory failure")

    monkeypatch.setattr(service, "_manager_factory", fail_manager_factory)
    request = SupervisedRunRequest("mock", "random", 1, 1)
    if launch_path == "async":
        service.launch_async(request)
    else:
        service.reserve(request)
        assert service.reconcile_all() == {run_id: "pending_restarted"}

    assert len(DeferredThread.instances) == 1
    thread = DeferredThread.instances[0]
    assert thread.started is True
    (config.control_root / run_id / "attempts" / "attempt-0001").mkdir(parents=True)

    thread.target(*thread.args)

    assert manager.run_calls == []
    record = registry.get(run_id)
    assert record is not None
    assert record.status == "pending"
    assert record.ended_at is None
    assert "terminal_reason" not in record.metadata
    assert "cleanup_completed_at" not in record.metadata


@pytest.mark.parametrize("launch_path", ["async", "recovery"])
def test_thread_preflight_evidence_failure_with_attempt_remains_nonterminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launch_path: str,
) -> None:
    run_id = f"{launch_path}-attempt-preflight"
    service, registry, config, manager = _build_service(
        tmp_path,
        monkeypatch,
        ids=(run_id,),
        thread_factory=DeferredThread,
    )
    request = SupervisedRunRequest("mock", "random", 1, 1)
    if launch_path == "async":
        service.launch_async(request)
    else:
        service.reserve(request)
        assert service.reconcile_all() == {run_id: "pending_restarted"}

    assert len(DeferredThread.instances) == 1
    thread = DeferredThread.instances[0]
    assert thread.started is True
    (config.control_root / run_id / "attempts" / "attempt-0001").mkdir(parents=True)
    launch_file = config.control_root / run_id / "launch.json"
    payload = json.loads(launch_file.read_text(encoding="utf-8"))
    payload["contract"]["contract_sha256"] = "0" * 64
    launch_file.write_text(json.dumps(payload), encoding="utf-8")

    thread.target(*thread.args)

    assert manager.run_calls == []
    record = registry.get(run_id)
    assert record is not None
    assert record.status == "pending"
    assert record.ended_at is None
    assert "terminal_reason" not in record.metadata
    assert "cleanup_completed_at" not in record.metadata


def test_environment_identity_is_verified_and_redacts_runtime_nonce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _registry, _config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("identity-run",)
    )
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1))

    identity = service.environment_identity("identity-run")

    assert identity["run_id"] == "identity-run"
    assert identity["rpc"]["nonce_attested"] is True
    assert "nonce" not in identity["rpc"]
    assert len(identity["contract_sha256"]) == 64


def test_capture_screen_passes_all_eight_exact_runtime_identity_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, registry, _config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("screen-run",)
    )
    calls: dict[str, Any] = {}
    service._client_factory = lambda **kwargs: FakeScreenClient(calls, **kwargs)
    service.reserve(SupervisedRunRequest("dfhack", "dfhack-governed-scripted", 1, 1))
    assert registry.claim_pending_run("screen-run", started_at=_fixed_datetime())
    contract = service._load_contract("screen-run")

    screen = service.capture_screen("screen-run")

    assert screen == {"width": 2, "height": 1, "tiles": [[65, 7, 0], [66, 7, 0]]}
    kwargs = calls["kwargs"]
    assert kwargs == {
        "host": "127.0.0.1",
        "port": contract.port,
        "retries": 1,
        "expected_run_id": contract.run_id,
        "expected_nonce": contract.nonce,
        "expected_contract_sha256": contract.contract_sha256,
        "expected_seed_tree_sha256": contract.seed_tree_sha256,
        "expected_seed_world_sha256": contract.seed_world_sha256,
        "expected_image_manifest_sha256": contract.image_manifest_sha256,
        "expected_image_config_sha256": contract.image_config_sha256,
        "expected_image_archive_sha256": contract.image_archive_sha256,
    }
    assert calls["client"].closed is True


def test_capture_screen_rejects_unowned_or_inactive_runs_without_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _registry, _config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("mock-run",)
    )
    calls: list[dict[str, Any]] = []
    service._client_factory = lambda **kwargs: calls.append(kwargs)
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1))

    with pytest.raises(SupervisionRequestError):
        service.capture_screen("mock-run")
    with pytest.raises(RunNotOwnedError):
        service.capture_screen("not-owned")
    assert calls == []


def test_invalid_evaluation_protocol_is_rejected_before_control_or_registry_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("invalid-protocol",)
    )

    with pytest.raises(SupervisionRequestError):
        service.reserve(
            SupervisedRunRequest(
                "mock", "random", 1, 1, evaluation_protocol="invalid protocol"
            )
        )

    assert registry.list() == []
    assert not config.control_root.exists()


def test_run_reserved_verifies_launch_digest_before_injected_manager_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _registry, config, manager = _build_service(
        tmp_path, monkeypatch, ids=("tampered-run",)
    )
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1))
    launch_path = config.control_root / "tampered-run" / "launch.json"
    payload = json.loads(launch_path.read_text(encoding="utf-8"))
    payload["contract"]["contract_sha256"] = "0" * 64
    launch_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LaunchEvidenceError, match="digest"):
        service.run_reserved("tampered-run")

    assert manager.run_calls == []


def test_reconstructed_contract_must_retain_service_pinned_image_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("repinned-run",)
    )
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1))
    contract = service._load_contract("repinned-run")
    changed = replace(contract, image_manifest_sha256="e" * 64)
    launch_path = config.control_root / "repinned-run" / "launch.json"
    payload = json.loads(launch_path.read_text(encoding="utf-8"))
    payload["contract"] = changed.environment_identity()
    launch_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LaunchEvidenceError, match="service config"):
        service.environment_identity("repinned-run")


def test_reconstructed_contract_run_id_must_match_outer_launch_and_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("bound-run",)
    )
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1))
    contract = service._load_contract("bound-run")
    changed = replace(
        contract,
        run_id="different-run",
        cohort_run_ids=("different-run",),
    )
    launch_path = config.control_root / "bound-run" / "launch.json"
    payload = json.loads(launch_path.read_text(encoding="utf-8"))
    payload["contract"] = changed.environment_identity()
    launch_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LaunchEvidenceError, match="run ID"):
        service.environment_identity("bound-run")


def test_launch_request_fields_must_match_reserved_registry_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("request-bound",)
    )
    service.reserve(SupervisedRunRequest("mock", "random", 3, 7))
    launch_path = config.control_root / "request-bound" / "launch.json"
    payload = json.loads(launch_path.read_text(encoding="utf-8"))
    payload["request"]["max_steps"] = 999
    launch_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LaunchEvidenceError, match="registry row"):
        service.environment_identity("request-bound")


def test_reconstructed_cohort_must_remain_symmetric_and_service_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _registry, config, _manager = _build_service(
        tmp_path, monkeypatch, ids=("cohort-a", "cohort-b")
    )
    service.reserve(SupervisedRunRequest("mock", "random", 1, 1, cohort_size=2))
    contract = service._load_contract("cohort-a")
    changed = replace(
        contract,
        cohort_run_ids=("cohort-a", "foreign-run"),
    )
    launch_path = config.control_root / "cohort-a" / "launch.json"
    payload = json.loads(launch_path.read_text(encoding="utf-8"))
    payload["contract"] = changed.environment_identity()
    launch_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LaunchEvidenceError, match="cohort"):
        service.environment_identity("cohort-a")


def test_registry_artifact_root_must_match_immutable_service_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured-artifacts"
    ambient = tmp_path / "ambient-artifacts"
    with pytest.raises(SupervisionConfigurationError, match="artifact root"):
        _build_service(
            tmp_path,
            monkeypatch,
            ids=("mismatched-root",),
            configured_artifacts=configured,
            settings_artifacts=ambient,
        )


def test_service_config_rejects_missing_required_runtime_paths(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SupervisionConfigurationError, match="entrypoint_path"):
        ServiceConfig(
            db_path=(tmp_path / "runs.sqlite3").resolve(),
            artifacts_root=(tmp_path / "artifacts").resolve(),
            control_root=(tmp_path / "control").resolve(),
            repo_root=(tmp_path / "repo").resolve(),
            python_executable=Path(sys.executable).resolve(),
            entrypoint_path=(missing / "runtime_entrypoint.sh").resolve(),
            dfroot=(tmp_path / "dfroot").resolve(),
            code_sha256="a" * 64,
        )


def test_service_config_rejects_invalid_cpuset_before_runtime(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    entrypoint = repo / "entrypoint.sh"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")

    with pytest.raises(SupervisionConfigurationError, match="cpuset"):
        ServiceConfig(
            db_path=(tmp_path / "runs.sqlite3").resolve(),
            artifacts_root=(tmp_path / "artifacts").resolve(),
            control_root=(tmp_path / "control").resolve(),
            repo_root=repo.resolve(),
            python_executable=Path(sys.executable).resolve(),
            entrypoint_path=entrypoint.resolve(),
            dfroot=(tmp_path / "dfroot").resolve(),
            code_sha256="a" * 64,
            cpusets=("not-a-cpu-set",),
        )


def test_from_environment_ignores_ambient_provider_key_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    control = tmp_path / "control"
    image_archive = tmp_path / "image.tar.zst"
    image_archive.write_bytes(b"preserved-image")
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    monkeypatch.setenv("FORT_GYM_M1B_SUPERVISION_ENABLED", "1")
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("FORT_GYM_M1B_CONTROL_ROOT", str(control))
    monkeypatch.setenv("FORT_GYM_SEED_SAVE", "seed_region3_fresh")
    monkeypatch.setenv("FORT_GYM_M1B_IMAGE_ARCHIVE_PATH", str(image_archive))
    monkeypatch.setenv("FORT_GYM_M1B_ZSTD_EXECUTABLE", "/opt/tools/zstd")
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-only-key")
    monkeypatch.delenv("FORT_GYM_M1B_OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    config = ServiceConfig.from_environment()

    assert config.openrouter_api_key is None
    assert config.artifacts_root == artifacts.resolve()
    assert config.control_root == control.resolve()
    assert config.image_archive_path == image_archive.resolve()
    assert config.zstd_executable == "/opt/tools/zstd"
    assert not artifacts.exists()
    assert not control.exists()


def test_from_environment_wraps_invalid_numeric_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    monkeypatch.setenv("FORT_GYM_M1B_SUPERVISION_ENABLED", "1")
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FORT_GYM_SEED_SAVE", "seed_region3_fresh")
    monkeypatch.setenv("FORT_GYM_M1B_BASE_PORT", "not-an-integer")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    with pytest.raises(SupervisionConfigurationError, match="BASE_PORT"):
        ServiceConfig.from_environment()


def _fixed_datetime():
    from datetime import UTC, datetime

    return datetime(2026, 8, 16, 22, 0, tzinfo=UTC)
