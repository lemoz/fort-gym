from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import infra.m1b.run_live_acceptance as host_runner_module
from fort_gym.bench.run.live_acceptance import (
    FROZEN_ACCEPTANCE_SHA256,
    FROZEN_GATE_PLAN,
    FROZEN_PLAN_SHA256,
    BatchDecisionValue,
    CleanupPassContext,
    CleanupPassResult,
    GateExecutionContext,
    GateExecutionResult,
    LocalCreditImport,
    SourceManifestLock,
)
from fort_gym.bench.run.runtime_controller import DockerRuntimeController
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervision_service import (
    ServiceConfig,
    SupervisedRunRequest,
    SupervisionService,
)
from infra.m1b.root_broker import (
    AUTHORITY_EXPIRES_AT,
    BrokerError,
    BrokerLayout,
    RootBroker,
    broker_policy_sha256,
)
from infra.m1b.root_broker import (
    FROZEN_PLAN_SHA256 as BROKER_PLAN_SHA256,
)
from infra.m1b.root_broker import (
    _canonical_bytes as broker_canonical_bytes,
)
from infra.m1b.run_live_acceptance import (
    BrokerClientError,
    BrokeredRuntimeCommandRunner,
    BrokeredSupervisionService,
    BrokerReceipt,
    GateExecutionError,
    HostPaths,
    LinuxGateBackend,
    LinuxM1BHostAdapter,
    PublicRunBinding,
    RootBrokerClient,
    _bounded_cross_run_artifact_scan,
    _canary_inspect_state_sha256,
    _canonical_bytes,
    _FaultSessionFailureGuard,
    _OrphanChildUnwindGuard,
    _PausedHarnessUnwindGuard,
    _port2_conflict_terminal_proof,
    _rehydrate_container_inspect_projection,
    _rehydrate_runtime_attestation_projection,
    _validate_canary_absence_receipt,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
CANARY_IMAGE = "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"


def test_nonroot_process_preflight_scopes_uid_and_fails_on_unknown_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [
        SimpleNamespace(name="12", stat=lambda: SimpleNamespace(st_uid=1000)),
        SimpleNamespace(name="1", stat=lambda: SimpleNamespace(st_uid=0)),
        SimpleNamespace(name="self"),
        SimpleNamespace(name="13", stat=lambda: (_ for _ in ()).throw(FileNotFoundError())),
    ]
    monkeypatch.setattr(host_runner_module, "Path", lambda _root: SimpleNamespace(iterdir=lambda: entries))
    monkeypatch.setattr(host_runner_module.os, "geteuid", lambda: 1000)
    assert host_runner_module._caller_owned_process_ids() == (12,)
    entries.append(SimpleNamespace(name="14", stat=lambda: (_ for _ in ()).throw(PermissionError())))
    with pytest.raises(PermissionError):
        host_runner_module._caller_owned_process_ids()


def test_fault_barrier_rejects_already_terminal_participant() -> None:
    future = Future()
    future.set_result(SimpleNamespace(status="failed"))
    store = SimpleNamespace(ready=lambda run_id: {"stale": "receipt"})
    with pytest.raises(host_runner_module.GateExecutionError, match="terminated"):
        host_runner_module._fault_ready_while_running(store, "target", {"peer": future})


def test_fault_barrier_propagates_worker_failure() -> None:
    future = Future()
    future.set_exception(RuntimeError("worker failed"))
    with pytest.raises(RuntimeError, match="worker failed"):
        host_runner_module._fault_ready_while_running(None, "target", {"target": future})


def test_fault_barrier_keeps_waiting_for_live_participants() -> None:
    future = Future()
    store = SimpleNamespace(ready=lambda run_id: None)
    assert (
        host_runner_module._fault_ready_while_running(store, "target", {"target": future})
        is None
    )
    receipt = {"run_id": "target"}
    store.ready = lambda run_id: receipt
    assert (
        host_runner_module._fault_ready_while_running(store, "target", {"target": future})
        == receipt
    )


def _root_client_paths(tmp_path: Path) -> tuple[HostPaths, str]:
    repo = (tmp_path / "repo").resolve()
    broker_source = repo / "infra/m1b/root_broker.py"
    broker_source.parent.mkdir(parents=True)
    broker_source.write_text("# pinned broker source\n", encoding="utf-8")
    source_sha256 = hashlib.sha256(broker_source.read_bytes()).hexdigest()
    packet = (tmp_path / "packet").resolve()
    packet.mkdir()
    (packet / "source-manifest.json").write_text(
        json.dumps(
            {
                "schema": "fortgym.m1b-live-source-manifest/v1",
                "files": [
                    {
                        "path": "infra/m1b/root_broker.py",
                        "sha256": source_sha256,
                        "size_bytes": broker_source.stat().st_size,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state = (tmp_path / "state").resolve()
    (state / "broker/requests").mkdir(parents=True)
    return (
        HostPaths(
            batch_id="batch-client",
            packet_root=packet,
            state_root=state,
            repo_root=repo,
            dfroot=(tmp_path / "dfroot").resolve(),
            runtime_archive_path=(tmp_path / "runtime.tar.zst").resolve(),
            broker_executable=(tmp_path / "broker").resolve(),
            sudo_executable=(tmp_path / "sudo").resolve(),
            require_canonical_host=False,
        ),
        source_sha256,
    )


def test_host_and_broker_registry_use_the_service_owned_control_root(
    tmp_path: Path,
) -> None:
    paths, _ = _root_client_paths(tmp_path)
    layout = BrokerLayout(
        repo_root=paths.repo_root,
        state_root=paths.state_root,
        venv_python=(tmp_path / "venv/bin/python").resolve(),
        image_archive=paths.runtime_archive_path,
        root_evidence_root=(tmp_path / "root-evidence").resolve(),
        packet_root=paths.packet_root,
    )

    expected = paths.state_root / "control" / "registry.sqlite3"
    assert paths.db_path == expected
    assert layout.db_path == expected
    assert paths.db_path.parent == paths.service_control_root

    paths.service_control_root.mkdir(mode=0o700)
    paths.artifacts_root.mkdir(mode=0o700)
    paths.state_root.chmod(0o555)
    try:
        registry = RunRegistry(
            db_path=paths.db_path,
            artifacts_root=paths.artifacts_root,
        )
        registry._ensure_conn()
        assert paths.db_path.is_file()
        assert not (paths.state_root / "registry.sqlite3").exists()
    finally:
        paths.state_root.chmod(0o700)


class _ClientReceiptTransport:
    def __init__(
        self,
        *,
        paths: HostPaths,
        source_sha256: str,
        binding: PublicRunBinding | None,
        mutate: Any = None,
    ) -> None:
        self.paths = paths
        self.source_sha256 = source_sha256
        self.binding = binding
        self.mutate = mutate

    def __call__(
        self,
        argv: Any,
        _timeout_seconds: float,
        _environment: Any,
    ) -> Any:
        request_path = Path(argv[-1])
        raw = request_path.read_bytes()
        request = json.loads(raw)
        binding = None
        if self.binding is not None:
            binding = {
                "run_id": self.binding.run_id,
                "contract_sha256": self.binding.contract_sha256,
                "nonce_sha256": self.binding.nonce_sha256,
                "cohort_sha256": self.binding.cohort_sha256,
                "container_name": (
                    f"fortgym-m1b-{self.binding.run_id}-"
                    f"{self.binding.contract_sha256[:12]}"
                ),
                "container_id": None,
                "port": self.binding.port,
            }
        command_stdout = ""
        receipt = {
            "schema": "fortgym.m1b-root-broker-receipt/v1",
            "ok": True,
            "request_id": request["request_id"],
            "request_sha256": hashlib.sha256(raw).hexdigest(),
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "policy_sha256": broker_policy_sha256(
                repo_root=self.paths.repo_root,
                state_root=self.paths.state_root,
            ),
            "broker_source_sha256": self.source_sha256,
            "batch_id": request["batch_id"],
            "gate_id": request["gate_id"],
            "grant_kind": request["grant_kind"],
            "attempt_id": request["attempt_id"],
            "attempt_identity_sha256": request["attempt_identity_sha256"],
            "action": request["action"],
            "binding": binding,
            "logical_argv_sha256": request["logical_argv_sha256"],
            "returncode": 0,
            "stdout": command_stdout,
            "stderr": "",
            "stdout_sha256": hashlib.sha256(command_stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "result": None,
            "shell": False,
            "action_grant_sha256": SHA_A,
        }
        if self.mutate is not None:
            self.mutate(receipt)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(receipt),
            stderr="",
        )


def test_root_broker_client_reports_secret_safe_failure_fingerprint(
    tmp_path: Path,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    reason_sha256 = hashlib.sha256(b"root-only semantic reason").hexdigest()

    def reject(argv: Any, _timeout_seconds: float, _environment: Any) -> Any:
        return subprocess.CompletedProcess(
            argv,
            64,
            stdout=json.dumps(
                {
                    "schema": "fortgym.m1b-root-broker-error/v1",
                    "ok": False,
                    "error_code": "broker_brokererror",
                    "reason_sha256": reason_sha256,
                }
            ),
            stderr="",
        )

    client = RootBrokerClient(
        paths=paths,
        gate_id="BATCH-CANARY",
        transport=reject,
    )
    with pytest.raises(BrokerClientError, match=reason_sha256):
        client.execute(
            ("docker", "inspect", "--type", "container", "canary"),
            binding=None,
            timeout_seconds=30.0,
            action="canary_inspect",
            parameters={"canary_name": "canary"},
        )
    errors = list(
        (paths.evidence_root / "broker-errors" / "BATCH-CANARY").glob("*.json")
    )
    assert len(errors) == 1
    error = json.loads(errors[0].read_text())
    assert error["schema"] == "fortgym.m1b-root-broker-client-error/v1"
    assert error["error_code"] == "broker_brokererror"
    assert error["reason_sha256"] == reason_sha256
    assert error["returncode"] == 64
    assert "root-only semantic reason" not in errors[0].read_text()


def test_root_broker_client_normalizes_only_docker_semantic_executable() -> None:
    identifier = "d" * 64
    logical = ("docker", "inspect", "--type", "container", identifier)
    assert (
        RootBrokerClient._semantic_logical_argv(
            ("/usr/bin/docker", *logical[1:]), action="docker_container_inspect"
        )
        == logical
    )
    assert (
        RootBrokerClient._semantic_logical_argv(
            logical, action="docker_container_inspect"
        )
        == logical
    )
    kill = ("/bin/kill", "-KILL", "--", "123")
    assert (
        RootBrokerClient._semantic_logical_argv(kill, action="signal_runtime") == kill
    )


def _client_attempt_binding() -> PublicRunBinding:
    return PublicRunBinding(
        attempt_id="g02-a01-peer_a",
        attempt_identity_sha256=SHA_A,
        run_id="m1b-port2-peer",
        contract_sha256=SHA_B,
        nonce_sha256=SHA_C,
        cohort_sha256="d" * 64,
        port=58_002,
    )


def test_fault_peer_inspection_uses_peer_binding_with_unchanged_root_policy(tmp_path: Path) -> None:
    target = replace(_client_attempt_binding(), run_id="fault-target", peer_run_id="fault-peer")
    peer = replace(target, run_id="fault-peer", peer_run_id="fault-target", port=58003)
    target_id, peer_id = "1" * 64, "2" * 64
    root = RootBroker(layout=BrokerLayout(state_root=tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid())
    observed = []

    class Broker:
        def execute(self, argv, *, binding, timeout_seconds):
            observed.append(binding)
            root._derive_command(
                {"action": "docker_container_inspect", "parameters": {"identifier": argv[-1]}},
                SimpleNamespace(
                    runtime_controller=None,
                    container_name=binding.run_id,
                    container_id=peer_id if binding.run_id == peer.run_id else target_id,
                ),
            )
            return SimpleNamespace(returncode=1, action="docker_container_inspect", stdout="", stderr="")

    runner = host_runner_module.BrokeredFaultCommandRunner(
        broker=Broker(), binding=target, inspection_binding_resolver=lambda argv: peer
    )
    runner.run(("docker", "inspect", "--type", "container", peer_id), timeout_seconds=1)
    assert observed == [peer]


@pytest.mark.parametrize("run_id,cohort", [("foreign", "d" * 64), ("fault-peer", "e" * 64)])
def test_fault_inspection_refuses_other_run_or_cohort(run_id: str, cohort: str) -> None:
    target = replace(_client_attempt_binding(), run_id="fault-target", peer_run_id="fault-peer")
    foreign = replace(target, run_id=run_id, peer_run_id="fault-target", cohort_sha256=cohort)
    runner = host_runner_module.BrokeredFaultCommandRunner(
        broker=None, binding=target, inspection_binding_resolver=lambda argv: foreign
    )
    with pytest.raises(BrokerClientError, match="target/peer cohort"):
        runner.run(("docker", "inspect", "--type", "container", "2" * 64), timeout_seconds=1)


def test_fault_mutation_does_not_rebind_to_peer() -> None:
    target = replace(_client_attempt_binding(), run_id="fault-target", peer_run_id="fault-peer")
    observed = []

    def execute(argv, *, binding, timeout_seconds):
        observed.append(binding)
        return SimpleNamespace(returncode=1, action="docker_restart", stdout="", stderr="")

    def forbidden_resolver(argv):
        raise AssertionError("mutation must never resolve a peer binding")

    runner = host_runner_module.BrokeredFaultCommandRunner(
        broker=SimpleNamespace(execute=execute), binding=target,
        inspection_binding_resolver=forbidden_resolver,
    )
    runner.run(("docker", "restart", "2" * 64), timeout_seconds=1)
    assert observed == [target]


def test_brokered_service_binds_runtime_runner_before_returning_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    broker = RootBrokerClient(paths=paths, gate_id="PORT-2")
    binding = _client_attempt_binding()
    controller = object.__new__(DockerRuntimeController)
    observed: list[tuple[str, DockerRuntimeController]] = []
    service = object.__new__(BrokeredSupervisionService)
    service._host_gate_id = "PORT-2"
    service._host_binding_factory = lambda _contract: binding
    service._host_broker_factory = lambda _gate_id: broker
    service._host_runtime_controller_observer = lambda run_id, value: observed.append(
        (run_id, value)
    )
    service._host_nonruntime_port_conflict_run_ids = frozenset()
    service._load_contract = lambda _run_id: SimpleNamespace()
    monkeypatch.setattr(
        SupervisionService,
        "_runtime_controller",
        lambda _self, _record, _run_dir: controller,
    )
    run_dir = tmp_path / "control" / binding.run_id

    returned = BrokeredSupervisionService._runtime_controller(
        service,
        SimpleNamespace(run_id=binding.run_id),
        run_dir,
    )

    assert returned is controller
    assert isinstance(controller.runner, BrokeredRuntimeCommandRunner)
    assert controller.runner.broker is broker
    assert controller.runner.binding == binding
    assert observed == [(binding.run_id, controller)]
    receipt = json.loads((run_dir / "brokered-runtime-runner.json").read_text())
    assert receipt == {
        "schema": "fortgym.m1b-brokered-runtime-runner/v1",
        "run_id": binding.run_id,
        "gate_id": "PORT-2",
        "attempt_id": binding.attempt_id,
        "attempt_identity_sha256": binding.attempt_identity_sha256,
        "contract_sha256": binding.contract_sha256,
        "nonce_sha256": binding.nonce_sha256,
        "cohort_sha256": binding.cohort_sha256,
        "broker_policy_sha256": broker._expected_policy_sha256,
        "broker_source_sha256": broker._expected_broker_source_sha256,
        "runner_type": "BrokeredRuntimeCommandRunner",
    }


def test_brokered_service_configures_only_exact_nonruntime_port_contender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    broker = RootBrokerClient(paths=paths, gate_id="PORT-2")
    binding = _client_attempt_binding()
    controller = object.__new__(DockerRuntimeController)
    configured: list[str] = []
    controller.configure_nonruntime_port_conflict_cleanup = lambda: configured.append(
        binding.run_id
    )
    service = object.__new__(BrokeredSupervisionService)
    service._host_gate_id = "PORT-2"
    service._host_binding_factory = lambda _contract: binding
    service._host_broker_factory = lambda _gate_id: broker
    service._host_runtime_controller_observer = lambda _run_id, _value: None
    service._host_nonruntime_port_conflict_run_ids = frozenset({binding.run_id})
    service._load_contract = lambda _run_id: SimpleNamespace()
    monkeypatch.setattr(
        SupervisionService,
        "_runtime_controller",
        lambda _self, _record, _run_dir: controller,
    )

    BrokeredSupervisionService._runtime_controller(
        service,
        SimpleNamespace(run_id=binding.run_id),
        tmp_path / "control" / binding.run_id,
    )

    assert configured == [binding.run_id]


def test_brokered_service_real_dfhack_controller_never_uses_default_runner(
    tmp_path: Path,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    paths.artifacts_root.mkdir(parents=True)
    paths.service_control_root.mkdir(parents=True)
    paths.dfroot.mkdir(parents=True)
    paths.runtime_archive_path.write_bytes(b"pinned archive placeholder")
    entrypoint = paths.repo_root / "infra" / "m1b" / "runtime_entrypoint.sh"
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    entrypoint.chmod(0o700)
    config = ServiceConfig(
        db_path=paths.db_path,
        artifacts_root=paths.artifacts_root,
        control_root=paths.service_control_root,
        repo_root=paths.repo_root,
        python_executable=Path(os.sys.executable).absolute(),
        entrypoint_path=entrypoint,
        dfroot=paths.dfroot,
        code_sha256=SHA_A,
        image_archive_path=paths.runtime_archive_path,
    )
    registry = RunRegistry(
        db_path=config.db_path,
        artifacts_root=config.artifacts_root,
        recover_interrupted=False,
    )
    broker = RootBrokerClient(paths=paths, gate_id="PORT-2")
    observed: list[tuple[str, DockerRuntimeController]] = []

    def binding_factory(contract: Any) -> PublicRunBinding:
        return PublicRunBinding(
            attempt_id="g02-a01-peer_a",
            attempt_identity_sha256=SHA_A,
            run_id=contract.run_id,
            contract_sha256=contract.contract_sha256,
            nonce_sha256=hashlib.sha256(contract.nonce.encode()).hexdigest(),
            cohort_sha256=contract.cohort_digest,
            port=contract.port,
        )

    service = BrokeredSupervisionService(
        registry=registry,
        config=config,
        id_factory=lambda: "m1b-port2-peer",
        nonce_factory=lambda: "1" * 32,
        broker_factory=lambda _gate_id: broker,
        gate_id="PORT-2",
        attempt_hook=lambda _run_id: None,
        binding_factory=binding_factory,
        runtime_controller_observer=(
            lambda run_id, value: observed.append((run_id, value))
        ),
        fault_session=host_runner_module.FaultSessionBinding(),
    )
    launch = service.reserve(
        SupervisedRunRequest(
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=2,
            ticks_per_step=4,
        )
    )
    record = launch.records[0]
    run_dir = paths.service_control_root / record.run_id

    controller = service._runtime_controller(record, run_dir)

    assert isinstance(controller, DockerRuntimeController)
    assert isinstance(controller.runner, BrokeredRuntimeCommandRunner)
    assert controller.runner.broker is broker
    assert controller.runner.binding.run_id == record.run_id
    assert observed == [(record.run_id, controller)]
    assert (run_dir / "brokered-runtime-runner.json").is_file()


def test_port2_nonruntime_conflict_requires_exact_terminal_chain_and_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(status="failed")
    proof = {
        "run_id": "m1b-port2-contender",
        "status": "failed",
        "reason_code": "port_lease_busy",
        "terminal_chain": {"events": ["immutable_terminal_classification"]},
    }
    monkeypatch.setattr(host_runner_module, "_terminal_proof", lambda value: proof)
    assert _port2_conflict_terminal_proof(result) == proof

    monkeypatch.setattr(
        host_runner_module,
        "_terminal_proof",
        lambda value: {**proof, "reason_code": "port_policy_failure"},
    )
    with pytest.raises(GateExecutionError, match="contender terminal proof"):
        _port2_conflict_terminal_proof(result)

    def missing_chain(_value: Any) -> dict[str, Any]:
        raise GateExecutionError("managed result terminal chain is incomplete")

    monkeypatch.setattr(host_runner_module, "_terminal_proof", missing_chain)
    with pytest.raises(GateExecutionError, match="terminal chain is incomplete"):
        _port2_conflict_terminal_proof(result)


def test_nonruntime_port2_residue_uses_exact_authenticated_absence_probe(
    tmp_path: Path,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    paths.evidence_root.mkdir(parents=True, mode=0o700)
    run_id = "m1b-port2-contender"
    binding = PublicRunBinding(
        attempt_id="g02-a02-contender_b",
        attempt_identity_sha256=SHA_A,
        run_id=run_id,
        contract_sha256=SHA_B,
        nonce_sha256=SHA_C,
        cohort_sha256=SHA_A,
        port=58_000,
    )
    evidence = paths.evidence_root / "contender-absence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    class MissingContainerBroker:
        def execute(self, argv: Any, **kwargs: Any) -> BrokerReceipt:
            logical = tuple(argv)
            calls.append((logical, kwargs))
            empty_sha = hashlib.sha256(b"").hexdigest()
            return BrokerReceipt(
                action="docker_container_inspect",
                ok=False,
                logical_argv=logical,
                returncode=1,
                stdout="",
                stderr="Error: no such object",
                stdout_sha256=empty_sha,
                stderr_sha256=hashlib.sha256(b"Error: no such object").hexdigest(),
                policy_sha256=SHA_A,
                broker_source_sha256=SHA_B,
                result=None,
                request_id="contender-absence",
                evidence_path=evidence,
            )

    backend = object.__new__(LinuxGateBackend)
    backend.paths = paths
    backend._bindings = {run_id: binding}
    backend._permit_by_run = {
        run_id: SimpleNamespace(kind=SimpleNamespace(value="non_runtime_conflict"))
    }
    broker = MissingContainerBroker()
    backend.broker = lambda gate_id: broker  # type: ignore[method-assign]

    probe = backend._residue_command_probe("PORT-2")
    result = probe(
        (
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            "label=fortgym.m1b.managed=true",
            "--filter",
            f"label=fortgym.m1b.run_id={run_id}",
        )
    )

    assert result == (0, "", "")
    expected_name = f"fortgym-m1b-{run_id}-{SHA_B[:12]}"
    assert calls == [
        (
            ("docker", "inspect", "--type", "container", expected_name),
            {
                "binding": binding,
                "timeout_seconds": 30.0,
                "action": "docker_container_inspect",
                "parameters": {"identifier": expected_name},
            },
        )
    ]


def test_gate_failure_receipt_records_exact_safe_execution_stage(
    tmp_path: Path,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    paths.evidence_root.mkdir(parents=True, mode=0o700)
    backend = LinuxGateBackend(paths=paths)

    def fail_at_terminal(_context: Any) -> None:
        backend._failure_stage = "validate_peer_terminal_chain"
        raise GateExecutionError("PORT-2 peer durable-stop terminal differs")

    backend._gate_port_2 = fail_at_terminal  # type: ignore[method-assign]
    result = backend.execute(SimpleNamespace(gate_id="PORT-2"))

    assert result.failure_code == "host_gateexecutionerror"
    failure = json.loads(result.evidence_paths[0].read_text(encoding="utf-8"))
    assert failure == {
        "schema": "fortgym.m1b-host-gate-failure/v1",
        "gate_id": "PORT-2",
        "error_type": "GateExecutionError",
        "stage": "validate_peer_terminal_chain",
    }
    assert backend._active_gate is None
    assert backend._failure_stage is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "foreign-run"),
        ("contract_sha256", SHA_C),
        ("nonce_sha256", SHA_A),
        ("cohort_sha256", SHA_A),
        ("container_name", "fortgym-m1b-foreign"),
        ("container_id", "e" * 64),
        ("port", 58_003),
    ],
)
def test_root_broker_client_rejects_every_tampered_public_binding_field(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    binding = _client_attempt_binding()

    def tamper(receipt: dict[str, Any]) -> None:
        receipt["binding"][field] = value

    client = RootBrokerClient(
        paths=paths,
        gate_id="PORT-2",
        transport=_ClientReceiptTransport(
            paths=paths,
            source_sha256=source_sha256,
            binding=binding,
            mutate=tamper,
        ),
    )
    with pytest.raises(BrokerClientError, match="identity"):
        client.execute(
            (
                "docker",
                "image",
                "inspect",
                CANARY_IMAGE,
            ),
            binding=binding,
            timeout_seconds=30.0,
        )


@pytest.mark.parametrize("returncode", [1, 125])
def test_root_broker_client_accepts_authenticated_initial_container_absence(
    tmp_path: Path,
    returncode: int,
) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    binding = _client_attempt_binding()
    stderr = "Error: no such object\n"

    def absent(receipt: dict[str, Any]) -> None:
        receipt["binding"]["container_id"] = None
        receipt["ok"] = False
        receipt["returncode"] = returncode
        receipt["stdout"] = ""
        receipt["stderr"] = stderr
        receipt["stdout_sha256"] = hashlib.sha256(b"").hexdigest()
        receipt["stderr_sha256"] = hashlib.sha256(stderr.encode()).hexdigest()

    client = RootBrokerClient(
        paths=paths,
        gate_id="PORT-2",
        transport=_ClientReceiptTransport(
            paths=paths,
            source_sha256=source_sha256,
            binding=binding,
            mutate=absent,
        ),
    )
    receipt = client.execute(
        (
            "docker",
            "inspect",
            "--type",
            "container",
            f"fortgym-m1b-{binding.run_id}-{binding.contract_sha256[:12]}",
        ),
        binding=binding,
        timeout_seconds=30.0,
    )

    assert receipt.ok is False
    assert receipt.returncode == returncode
    assert receipt.stdout == ""
    assert receipt.stderr == stderr
    public = json.loads(receipt.evidence_path.read_text())
    assert public["binding"]["container_id"] is None
    assert public["returncode"] == returncode
    assert public["ok"] is False


def test_root_broker_client_rejects_null_container_id_on_success(
    tmp_path: Path,
) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    binding = _client_attempt_binding()
    client = RootBrokerClient(
        paths=paths,
        gate_id="PORT-2",
        transport=_ClientReceiptTransport(
            paths=paths,
            source_sha256=source_sha256,
            binding=binding,
        ),
    )

    with pytest.raises(BrokerClientError, match="identity"):
        client.execute(
            (
                "docker",
                "inspect",
                "--type",
                "container",
                f"fortgym-m1b-{binding.run_id}-{binding.contract_sha256[:12]}",
            ),
            binding=binding,
            timeout_seconds=30.0,
        )


def test_root_broker_client_accepts_empty_managed_inventory_after_removal(
    tmp_path: Path,
) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    binding = _client_attempt_binding()
    client = RootBrokerClient(
        paths=paths,
        gate_id="PORT-2",
        transport=_ClientReceiptTransport(
            paths=paths,
            source_sha256=source_sha256,
            binding=binding,
        ),
    )

    receipt = client.execute(
        (
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
        ),
        binding=binding,
        timeout_seconds=30.0,
    )

    assert receipt.ok is True
    assert receipt.returncode == 0
    assert receipt.stdout == ""


@pytest.mark.parametrize("mutation", [None, "stdout", "returncode", "run_id", "contract_sha256"])
def test_root_broker_client_unmount_receipt_after_container_removal(
    tmp_path: Path, mutation: str | None,
) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    binding = _client_attempt_binding()

    def mutate(receipt: dict[str, Any]) -> None:
        if mutation == "stdout":
            receipt["stdout"] = "unexpected"
            receipt["stdout_sha256"] = hashlib.sha256(b"unexpected").hexdigest()
        elif mutation == "returncode":
            receipt["returncode"] = 1
            receipt["ok"] = False
        elif mutation in {"run_id", "contract_sha256"}:
            receipt["binding"][mutation] = "foreign"

    client = RootBrokerClient(
        paths=paths, gate_id="ENOSPC",
        transport=_ClientReceiptTransport(
            paths=paths, source_sha256=source_sha256,
            binding=binding, mutate=mutate,
        ),
    )
    argv = ("/bin/umount", "--", str(paths.artifacts_root / binding.run_id))
    if mutation is not None:
        with pytest.raises(BrokerClientError, match="identity"):
            client.execute(argv, binding=binding, timeout_seconds=30.0)
    else:
        receipt = client.execute(argv, binding=binding, timeout_seconds=30.0)
        assert receipt.ok is True
        assert receipt.stdout == ""


def test_root_broker_client_rejects_nonempty_managed_inventory_without_id(
    tmp_path: Path,
) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    binding = _client_attempt_binding()

    def nonempty(receipt: dict[str, Any]) -> None:
        receipt["stdout"] = "{}\n"
        receipt["stdout_sha256"] = hashlib.sha256(b"{}\n").hexdigest()

    client = RootBrokerClient(
        paths=paths,
        gate_id="PORT-2",
        transport=_ClientReceiptTransport(
            paths=paths,
            source_sha256=source_sha256,
            binding=binding,
            mutate=nonempty,
        ),
    )

    with pytest.raises(BrokerClientError, match="identity"):
        client.execute(
            (
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
            ),
            binding=binding,
            timeout_seconds=30.0,
        )


@pytest.mark.parametrize("field", ["policy_sha256", "broker_source_sha256"])
def test_root_broker_client_rejects_tampered_policy_or_source_digest(
    tmp_path: Path,
    field: str,
) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    binding = _client_attempt_binding()

    def tamper(receipt: dict[str, Any]) -> None:
        receipt[field] = "e" * 64

    client = RootBrokerClient(
        paths=paths,
        gate_id="PORT-2",
        transport=_ClientReceiptTransport(
            paths=paths,
            source_sha256=source_sha256,
            binding=binding,
            mutate=tamper,
        ),
    )
    with pytest.raises(BrokerClientError, match="identity"):
        client.execute(
            (
                "docker",
                "image",
                "inspect",
                CANARY_IMAGE,
            ),
            binding=binding,
            timeout_seconds=30.0,
        )


def test_root_broker_client_requires_exact_null_batch_binding(tmp_path: Path) -> None:
    paths, source_sha256 = _root_client_paths(tmp_path)
    valid = RootBrokerClient(
        paths=paths,
        gate_id="BATCH-CANARY",
        transport=_ClientReceiptTransport(
            paths=paths,
            source_sha256=source_sha256,
            binding=None,
        ),
    )
    logical = (
        "docker",
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        "name=^/fortgym-m1b-foreign-test$",
        "--format",
        "{{.ID}}",
    )
    assert (
        valid.execute(
            logical,
            binding=None,
            timeout_seconds=30.0,
            action="canary_absence",
            parameters={"canary_name": "fortgym-m1b-foreign-test"},
        ).ok
        is True
    )

    def tamper(receipt: dict[str, Any]) -> None:
        receipt["binding"] = {}

    rejected = RootBrokerClient(
        paths=replace(paths, batch_id="batch-client-tamper"),
        gate_id="BATCH-CANARY",
        transport=_ClientReceiptTransport(
            paths=replace(paths, batch_id="batch-client-tamper"),
            source_sha256=source_sha256,
            binding=None,
            mutate=tamper,
        ),
    )
    with pytest.raises(BrokerClientError, match="identity"):
        rejected.execute(
            logical,
            binding=None,
            timeout_seconds=30.0,
            action="canary_absence",
            parameters={"canary_name": "fortgym-m1b-foreign-test"},
        )


def _layout(tmp_path: Path) -> BrokerLayout:
    return BrokerLayout(
        repo_root=(tmp_path / "repo").resolve(),
        state_root=(tmp_path / "state").resolve(),
        venv_python=(tmp_path / "venv/bin/python").resolve(),
        image_archive=(tmp_path / "runtime.tar.zst").resolve(),
        root_evidence_root=(tmp_path / "root-evidence").resolve(),
    )


def _make_broker_dirs(layout: BrokerLayout) -> None:
    layout.request_root.mkdir(parents=True, mode=0o700)
    layout.incoming_root.mkdir(parents=True, mode=0o700)
    layout.grant_root.mkdir(mode=0o700)
    layout.receipt_root.mkdir(mode=0o700)


def _ledger_record(
    *,
    schema: str,
    batch_id: str,
    sequence: int,
    previous: str,
    event: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "schema": schema,
        "batch_id": batch_id,
        "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
        "plan_sha256": FROZEN_PLAN_SHA256,
        "sequence": sequence,
        "previous_record_sha256": previous,
        "at": "2026-08-22T12:00:00+00:00",
        "event": event,
        "payload": payload,
    }
    record["record_sha256"] = hashlib.sha256(broker_canonical_bytes(record)).hexdigest()
    return record


def _write_ledger(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"".join(broker_canonical_bytes(record) + b"\n" for record in records)
    )
    path.chmod(0o600)


def _canary_inspect(*, container_id: str = "d" * 64) -> str:
    return json.dumps(
        [
            {
                "Id": container_id,
                "Name": "/fortgym-m1b-foreign-deadbeefdeadbeef",
                "Image": CANARY_IMAGE,
                "RestartCount": 0,
                "State": {
                    "Status": "created",
                    "Running": False,
                    "Dead": False,
                    "Restarting": False,
                },
                "Config": {
                    "Image": CANARY_IMAGE,
                    "Entrypoint": ["/bin/sleep"],
                    "Cmd": ["28800"],
                },
                "HostConfig": {
                    "NetworkMode": "none",
                    "Memory": 134_217_728,
                    "MemorySwap": 134_217_728,
                    "PidsLimit": 16,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges"],
                    "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                },
            }
        ]
    )


def _fake_runtime_controller(tmp_path: Path) -> SimpleNamespace:
    environment = {
        "DFHACK_PORT": "58000",
        "FORTGYM_CONTRACT_SHA256": SHA_A,
        "FORTGYM_RUN_ID": "m1b-runtime-one",
        "FORTGYM_RUN_NONCE": "12" * 16,
    }
    contract = SimpleNamespace(
        run_id="m1b-runtime-one",
        nonce="12" * 16,
        contract_sha256=SHA_A,
        seed_tree_sha256=SHA_B,
        seed_world_sha256=SHA_C,
        image_manifest_sha256=(
            "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
        ),
        image_config_sha256=(
            "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
        ),
        image_archive_sha256=(
            "87d66d26553cb271af1b784405d63ea6b95f3bbe20e9429f05e6412133d1f43a"
        ),
    )
    manifest = f"sha256:{contract.image_manifest_sha256}"
    config = f"sha256:{contract.image_config_sha256}"
    return SimpleNamespace(
        contract=contract,
        container_name="fortgym-m1b-m1b-runtime-one-aaaaaaaaaaaa",
        expected_labels={
            "fortgym.m1b.managed": "true",
            "fortgym.m1b.run_id": contract.run_id,
        },
        image_reference=manifest,
        image_config_reference=config,
        resolved_image_reference=manifest,
        memory_bytes=4 * 1024 * 1024 * 1024,
        cpuset_cpus=None,
        entrypoint_path=(tmp_path / "runtime_entrypoint.sh").resolve(),
        evidence_dir=(tmp_path / "control/runtime").resolve(),
        container_environment=lambda: dict(environment),
    )


def _container_projection(controller: SimpleNamespace) -> dict[str, Any]:
    environment = controller.container_environment()
    mounts = [
        {
            "destination": "/artifacts",
            "source_sha256": hashlib.sha256(
                str(controller.evidence_dir).encode()
            ).hexdigest(),
            "rw": True,
            "type": "bind",
        },
        {
            "destination": "/opt/fortgym-m1b/runtime_entrypoint.sh",
            "source_sha256": hashlib.sha256(
                str(controller.entrypoint_path).encode()
            ).hexdigest(),
            "rw": False,
            "type": "bind",
        },
    ]
    mounts.sort(key=lambda item: item["destination"])
    return {
        "FortGymProjectionSchema": "fortgym.m1b-container-inspect-projection/v1",
        "Id": "d" * 64,
        "Name": f"/{controller.container_name}",
        "Image": controller.image_reference,
        "RestartCount": 0,
        "State": {
            "Status": "running",
            "Running": True,
            "Dead": False,
            "Restarting": False,
            "OOMKilled": False,
            "ExitCode": 0,
            "Pid": 1001,
        },
        "Config": {
            "Image": controller.resolved_image_reference,
            "Labels": controller.expected_labels,
            "Entrypoint": ["/bin/bash"],
            "Cmd": ["/opt/fortgym-m1b/runtime_entrypoint.sh"],
        },
        "HostConfig": {
            "NetworkMode": "host",
            "Memory": controller.memory_bytes,
            "MemorySwap": controller.memory_bytes,
            "PidsLimit": 256,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true", "seccomp=unconfined"],
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "CpusetCpus": "",
        },
        "EnvAttestations": [
            {
                "name": name,
                "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
            }
            for name, value in sorted(environment.items())
        ],
        "MountAttestations": mounts,
    }


def test_adapter_dispatches_injected_gate_without_host_actions(tmp_path: Path) -> None:
    evidence = (tmp_path / "gate.json").resolve()
    evidence.write_text("{}\n", encoding="utf-8")

    class Backend:
        observed: str | None = None

        def execute(self, context: GateExecutionContext) -> GateExecutionResult:
            self.observed = context.gate_id
            return GateExecutionResult(
                gate_id=context.gate_id,
                criteria_passed=context.required_criteria,
                evidence_paths=(evidence,),
            )

    backend = Backend()
    adapter = LinuxM1BHostAdapter(backend)  # type: ignore[arg-type]
    context = GateExecutionContext(
        batch_id="batch-one",
        gate_id="PORT-1",
        gate_class="local",
        procedure="race",
        required_criteria=("winners",),
        attempts=(),
        local_credit=None,
        privileged_commands=SimpleNamespace(),
        evidence_root=tmp_path.resolve(),
        acceptance_sha256=FROZEN_ACCEPTANCE_SHA256,
        plan_sha256=FROZEN_PLAN_SHA256,
    )
    result = adapter.execute_gate(context)
    assert backend.observed == "PORT-1"
    assert result.criteria_passed == ("winners",)


@pytest.mark.parametrize(
    "gate",
    [gate for gate in FROZEN_GATE_PLAN if gate.gate_id != "CLEANUP"],
    ids=lambda gate: gate.gate_id,
)
def test_each_gate_criteria_evaluator_withholds_every_unproved_fact(gate: Any) -> None:
    complete = dict(gate.pass_contract)
    assert (
        LinuxGateBackend._verified_gate_criteria(gate.gate_id, complete)
        == gate.criteria
    )
    for name, expected in gate.pass_contract:
        missing = dict(complete)
        missing.pop(name)
        assert name not in LinuxGateBackend._verified_gate_criteria(
            gate.gate_id, missing
        )
        contradicted = dict(complete)
        if isinstance(expected, bool):
            contradicted[name] = not expected
        elif isinstance(expected, str):
            contradicted[name] = f"wrong-{expected}"
        elif name.endswith("_seconds_lte"):
            contradicted[name] = expected + 1
        elif name.endswith("_delta_gte") or name == "peer_minimum_step":
            contradicted[name] = expected - 1
        elif name == "maximum_fault_bytes":
            contradicted[name] = expected + 1
        else:
            contradicted[name] = expected + 1
        assert name not in LinuxGateBackend._verified_gate_criteria(
            gate.gate_id, contradicted
        )


def test_gate_inequality_fields_use_their_literal_direction() -> None:
    df_facts = dict(
        next(
            gate for gate in FROZEN_GATE_PLAN if gate.gate_id == "DF-KILL"
        ).pass_contract
    )
    df_facts["peer_minimum_step"] = 9
    assert "peer_minimum_step" in LinuxGateBackend._verified_gate_criteria(
        "DF-KILL", df_facts
    )
    enospc_facts = dict(
        next(
            gate for gate in FROZEN_GATE_PLAN if gate.gate_id == "ENOSPC"
        ).pass_contract
    )
    enospc_facts["maximum_fault_bytes"] = 8 * 1024 * 1024
    assert "maximum_fault_bytes" in LinuxGateBackend._verified_gate_criteria(
        "ENOSPC", enospc_facts
    )


def test_inert_canary_command_and_state_are_exact(tmp_path: Path) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path),
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    batch_id = "batch-one"
    name = "fortgym-m1b-foreign-" + hashlib.sha256(batch_id.encode()).hexdigest()[:16]
    request = {"batch_id": batch_id}
    logical, actual, timeout = broker._derive_canary(
        "canary_create", request, {"canary_name": name}
    )
    assert logical[:2] == ("docker", "create")
    assert logical[logical.index("--entrypoint") + 1] == "/bin/sleep"
    assert logical[-2:] == (CANARY_IMAGE, "28800")
    assert "--detach" not in logical
    assert actual[0] == "/usr/bin/docker"
    assert timeout == 60.0
    inspect_logical, inspect_actual, inspect_timeout = broker._derive_canary(
        "canary_inspect", request, {"canary_name": name}
    )
    assert inspect_logical == ("docker", "inspect", "--type", "container", name)
    assert inspect_actual == ("/usr/bin/docker", *inspect_logical[1:])
    assert inspect_timeout == 30.0
    remove_logical, remove_actual, remove_timeout = broker._derive_canary(
        "canary_remove", request, {"canary_name": name}
    )
    assert remove_logical == ("docker", "rm", "--force", name)
    assert remove_actual == ("/usr/bin/docker", *remove_logical[1:])
    assert remove_timeout == 60.0

    inspect_name = "fortgym-m1b-foreign-deadbeefdeadbeef"
    first = _canary_inspect()
    digest = _canary_inspect_state_sha256(
        first, name=inspect_name, container_id="d" * 64
    )
    assert len(digest) == 64
    changed = json.loads(first)
    changed[0]["State"]["Running"] = True
    with pytest.raises(GateExecutionError, match="semantic state"):
        _canary_inspect_state_sha256(
            json.dumps(changed), name=inspect_name, container_id="d" * 64
        )
    normalized = json.loads(first)
    normalized[0]["HostConfig"]["SecurityOpt"] = ["no-new-privileges:true"]
    assert (
        len(
            _canary_inspect_state_sha256(
                json.dumps(normalized), name=inspect_name, container_id="d" * 64
            )
        )
        == 64
    )


def test_container_projection_rehydrates_only_locally_held_values(
    tmp_path: Path,
) -> None:
    controller = _fake_runtime_controller(tmp_path)
    projection = _container_projection(controller)
    wire = json.dumps([projection]) + "\n"
    assert controller.contract.nonce not in wire
    assert "FORTGYM_RUN_NONCE=" not in wire
    assert str(controller.entrypoint_path) not in wire
    assert str(controller.evidence_dir) not in wire

    restored = json.loads(
        _rehydrate_container_inspect_projection(wire, controller=controller)
    )[0]
    assert f"FORTGYM_RUN_NONCE={controller.contract.nonce}" in restored["Config"]["Env"]
    assert {mount["Source"] for mount in restored["Mounts"]} == {
        str(controller.entrypoint_path),
        str(controller.evidence_dir),
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "fields differ"),
        (
            lambda value: value["EnvAttestations"].append(
                {"name": "OPENAI_API_KEY", "value_sha256": SHA_A}
            ),
            "environment attestations differ",
        ),
        (
            lambda value: value["MountAttestations"][0].update(
                {"source_sha256": SHA_A}
            ),
            "mount attestations differ",
        ),
        (
            lambda value: value["State"].update({"Pid": True}),
            "State projection differs",
        ),
    ],
)
def test_container_projection_rejects_extra_poison_and_hash_drift(
    tmp_path: Path,
    mutation: Any,
    message: str,
) -> None:
    controller = _fake_runtime_controller(tmp_path)
    projection = _container_projection(controller)
    mutation(projection)
    with pytest.raises(BrokerClientError, match=message):
        _rehydrate_container_inspect_projection(
            json.dumps([projection]), controller=controller
        )


def test_runtime_attestation_projection_rehydrates_nonce_after_hash_match(
    tmp_path: Path,
) -> None:
    controller = _fake_runtime_controller(tmp_path)
    contract = controller.contract
    projection = {
        "schema": "fortgym.m1b-runtime-attestation-projection/v1",
        "run_id": contract.run_id,
        "nonce_sha256": hashlib.sha256(contract.nonce.encode()).hexdigest(),
        "contract_sha256": contract.contract_sha256,
        "seed_tree_sha256": contract.seed_tree_sha256,
        "seed_world_sha256": contract.seed_world_sha256,
        "image_manifest_sha256": contract.image_manifest_sha256,
        "image_config_sha256": contract.image_config_sha256,
        "image_archive_sha256": contract.image_archive_sha256,
        "map_state": "MAP_LOADED",
    }
    wire = json.dumps(projection) + "\n"
    assert contract.nonce not in wire
    restored = _rehydrate_runtime_attestation_projection(wire, controller=controller)
    assert restored.split("\t") == [
        "FORTGYM_ATTEST",
        contract.run_id,
        contract.nonce,
        contract.contract_sha256,
        contract.seed_tree_sha256,
        contract.seed_world_sha256,
        contract.image_manifest_sha256,
        contract.image_config_sha256,
        contract.image_archive_sha256,
        "MAP_LOADED\n",
    ]
    projection["nonce_sha256"] = SHA_B
    with pytest.raises(BrokerClientError, match="identity differs"):
        _rehydrate_runtime_attestation_projection(
            json.dumps(projection), controller=controller
        )


def test_canary_absence_requires_authenticated_zero_empty_listing(
    tmp_path: Path,
) -> None:
    name = "fortgym-m1b-foreign-deadbeefdeadbeef"
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
    evidence = tmp_path / "absence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    empty_sha = hashlib.sha256(b"").hexdigest()
    receipt = BrokerReceipt(
        action="canary_absence",
        ok=True,
        logical_argv=logical,
        returncode=0,
        stdout="",
        stderr="",
        stdout_sha256=empty_sha,
        stderr_sha256=empty_sha,
        policy_sha256=SHA_A,
        broker_source_sha256=SHA_B,
        result=None,
        request_id="request-one",
        evidence_path=evidence,
    )
    _validate_canary_absence_receipt(receipt, name=name)
    contradictions = (
        replace(receipt, ok=False, returncode=1),
        replace(
            receipt,
            stdout="\n",
            stdout_sha256=hashlib.sha256(b"\n").hexdigest(),
        ),
        replace(
            receipt,
            stderr="normalized error",
            stderr_sha256=hashlib.sha256(b"normalized error").hexdigest(),
        ),
        replace(receipt, logical_argv=(*logical[:-1], "{{.Names}}")),
    )
    for contradiction in contradictions:
        with pytest.raises(GateExecutionError, match="exact absence listing"):
            _validate_canary_absence_receipt(contradiction, name=name)


def test_co8_gameplay_artifact_scan_detects_foreign_run_identity(
    tmp_path: Path,
) -> None:
    run_ids = ("m1b-co8-run01", "m1b-co8-run02")
    roots = {run_id: tmp_path / run_id for run_id in run_ids}
    for run_id, root in roots.items():
        root.mkdir()
        (root / "trace.jsonl").write_text(
            json.dumps({"run_id": run_id}) + "\n", encoding="utf-8"
        )
    count, evidence = _bounded_cross_run_artifact_scan(roots)
    assert count == 0
    assert evidence["files_scanned"] == 2
    (roots[run_ids[0]] / "child.stdout.log").write_text(
        f"foreign={run_ids[1]}\n", encoding="utf-8"
    )
    count, evidence = _bounded_cross_run_artifact_scan(roots)
    assert count == 1
    assert evidence["references"] == [
        {
            "owner_run_id": run_ids[0],
            "foreign_run_id": run_ids[1],
            "path": f"{run_ids[0]}/child.stdout.log",
        }
    ]


def test_broker_atomically_claims_request_and_replay_has_no_name(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    _make_broker_dirs(layout)
    broker = RootBroker(
        layout=layout,
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    request_id = "a" * 64
    request_path = layout.request_root / f"{request_id}.json"
    raw = b'{"one":1}\n'
    request_path.write_bytes(raw)
    request_path.chmod(0o600)

    claimed, observed = broker._claim_request(request_path, caller_uid=os.getuid())
    assert claimed == request_path
    assert observed == raw
    assert not request_path.exists()
    assert (layout.incoming_root / f"{request_id}.json").read_bytes() == raw
    with pytest.raises(FileNotFoundError):
        broker._claim_request(request_path, caller_uid=os.getuid())

    symlink_id = "b" * 64
    target = tmp_path / "symlink-target.json"
    target.write_text("{}\n", encoding="utf-8")
    (layout.request_root / f"{symlink_id}.json").symlink_to(target)
    with pytest.raises(OSError):
        broker._claim_request(
            layout.request_root / f"{symlink_id}.json", caller_uid=os.getuid()
        )

    hardlink_id = "c" * 64
    hardlink_source = tmp_path / "hardlink-source.json"
    hardlink_source.write_text("{}\n", encoding="utf-8")
    hardlink_source.chmod(0o600)
    os.link(hardlink_source, layout.request_root / f"{hardlink_id}.json")
    with pytest.raises(BrokerError, match="ownership or mode"):
        broker._claim_request(
            layout.request_root / f"{hardlink_id}.json", caller_uid=os.getuid()
        )


def test_broker_expiry_precedes_request_or_runtime_access(tmp_path: Path) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path),
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
        now=lambda: AUTHORITY_EXPIRES_AT + timedelta(seconds=1),
    )
    with pytest.raises(BrokerError, match="expired"):
        broker.handle((tmp_path / "does-not-exist.json").resolve())


def test_fault_session_failure_guard_aborts_only_unreleased_holds(
    tmp_path: Path,
) -> None:
    class Store:
        def __init__(self) -> None:
            self.aborted: list[tuple[str, str]] = []
            self.completion_aborts: list[str] = []

        def abort(self, run_id: str, *, reason_code: str) -> None:
            self.aborted.append((run_id, reason_code))

        def abort_completion(self, *, reason_code: str) -> None:
            self.completion_aborts.append(reason_code)

    class Service:
        def __init__(self) -> None:
            self.discarded: list[str] = []

        def _discard_enospc_fault_authorization(self, run_id: str) -> None:
            self.discarded.append(run_id)

    store = Store()
    service = Service()
    receipt = tmp_path / "fault-session-unwind.json"
    guard = _FaultSessionFailureGuard(
        store=store,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        run_ids=("target", "peer"),
        evidence_path=receipt,
        enospc_target_run_id="target",
    )
    with pytest.raises(RuntimeError, match="driver failed"), guard:
        guard.note_release("target")
        raise RuntimeError("driver failed")

    assert store.aborted == [("peer", "host_gate_failed")]
    assert store.completion_aborts == ["host_gate_failed"]
    assert service.discarded == ["target"]
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["error_type"] == "RuntimeError"
    assert payload["actions"]["participant_decisions"] == {
        "peer": "abort_requested",
        "target": "release_already_requested",
    }
    assert payload["actions"]["completion"] == "abort_requested"


def test_fault_session_failure_guard_does_nothing_after_success(tmp_path: Path) -> None:
    store = SimpleNamespace(
        abort=lambda *_args, **_kwargs: pytest.fail("unexpected participant abort"),
        abort_completion=lambda **_kwargs: pytest.fail("unexpected completion abort"),
    )
    service = SimpleNamespace(
        _discard_enospc_fault_authorization=lambda *_args: pytest.fail(
            "unexpected authorization discard"
        )
    )
    receipt = tmp_path / "fault-session-unwind.json"
    with _FaultSessionFailureGuard(
        store=store,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        run_ids=("target", "peer"),
        evidence_path=receipt,
        enospc_target_run_id="target",
    ) as guard:
        guard.note_release("target")
        guard.note_release("peer")
        guard.note_completion()
    assert not receipt.exists()


def _pause_binding() -> PublicRunBinding:
    return PublicRunBinding(
        attempt_id="g02-a01-peer_a",
        attempt_identity_sha256=SHA_A,
        run_id="m1b-port2-peer",
        contract_sha256=SHA_B,
        nonce_sha256=SHA_C,
        cohort_sha256="d" * 64,
        port=58_002,
    )


class _PauseBroker:
    def __init__(
        self, tmp_path: Path, resume_results: list[int | BaseException]
    ) -> None:
        self.tmp_path = tmp_path
        self.resume_results = list(resume_results)
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(
        self,
        argv: Any,
        *,
        binding: Any,
        timeout_seconds: float,
        action: str,
        parameters: Any,
    ) -> BrokerReceipt:
        del binding, timeout_seconds, parameters
        normalized = tuple(argv)
        self.calls.append((action, normalized))
        if action.startswith("resume_"):
            result = self.resume_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            returncode = result
        elif action == "abort_paused_harness":
            returncode = 0
        else:
            raise AssertionError(f"unexpected action {action}")
        evidence = self.tmp_path / f"broker-{len(self.calls)}.json"
        evidence.write_text("{}\n", encoding="utf-8")
        return BrokerReceipt(
            action=action,
            ok=returncode == 0,
            logical_argv=normalized,
            returncode=returncode,
            stdout="",
            stderr="" if returncode == 0 else "failed",
            stdout_sha256=hashlib.sha256(b"").hexdigest(),
            stderr_sha256=hashlib.sha256(
                ("" if returncode == 0 else "failed").encode()
            ).hexdigest(),
            policy_sha256=SHA_A,
            broker_source_sha256=SHA_B,
            result=None,
            request_id=f"request-{len(self.calls)}",
            evidence_path=evidence,
        )


class _PauseRegistry:
    def __init__(self) -> None:
        self.stops: list[str] = []

    def request_stop(self, run_id: str) -> bool:
        self.stops.append(run_id)
        return True


class _NeverCompletes:
    def done(self) -> bool:
        return False

    def result(self, *, timeout: float) -> None:
        assert timeout > 0
        raise TimeoutError("still running")


class _CompletesAfterStop:
    def done(self) -> bool:
        return False

    def result(self, *, timeout: float) -> None:
        assert timeout == 0.25


def test_early_cohort_failure_stops_every_submitted_run_before_return(
    tmp_path: Path,
) -> None:
    registry = _PauseRegistry()
    evidence = tmp_path / "early-unwind.json"
    futures = {
        "m1b-co8-run01": _CompletesAfterStop(),
        "m1b-co8-run02": _CompletesAfterStop(),
    }
    guard = _PausedHarnessUnwindGuard(
        broker=_PauseBroker(tmp_path, []),  # type: ignore[arg-type]
        registry=registry,
        gate_id="CO-8",
        evidence_path=evidence,
        futures=futures,
        join_timeout_seconds=0.25,
    )

    with pytest.raises(RuntimeError, match="early cohort failure"), guard:
        raise RuntimeError("early cohort failure")

    assert registry.stops == list(futures)
    payload = json.loads(evidence.read_text())
    assert payload["ok"] is True
    assert payload["actions"] == {
        run_id: {"registry_stop": "requested", "join": "completed"}
        for run_id in futures
    }


def test_paused_harness_resume_retries_before_success(tmp_path: Path) -> None:
    broker = _PauseBroker(tmp_path, [1, RuntimeError("retry"), 0])
    registry = _PauseRegistry()
    guard = _PausedHarnessUnwindGuard(
        broker=broker,  # type: ignore[arg-type]
        registry=registry,
        gate_id="PORT-2",
        evidence_path=tmp_path / "unwind.json",
        futures={},
    )
    with guard:
        guard.note_pause(
            run_id="m1b-port2-peer",
            harness_pid=1234,
            binding=_pause_binding(),
            resume_action="resume_peer_harness",
        )
        receipt = guard.resume("m1b-port2-peer")
        assert receipt.returncode == 0
    assert [action for action, _argv in broker.calls] == [
        "resume_peer_harness",
        "resume_peer_harness",
        "resume_peer_harness",
    ]
    assert registry.stops == []


def test_paused_harness_failed_resume_forces_authenticated_abort(
    tmp_path: Path,
) -> None:
    broker = _PauseBroker(tmp_path, [1, 1, 1])
    registry = _PauseRegistry()
    evidence = tmp_path / "unwind.json"
    guard = _PausedHarnessUnwindGuard(
        broker=broker,  # type: ignore[arg-type]
        registry=registry,
        gate_id="PORT-2",
        evidence_path=evidence,
        futures={},
    )
    with pytest.raises(RuntimeError, match="gate failed"), guard:
        guard.note_pause(
            run_id="m1b-port2-peer",
            harness_pid=1234,
            binding=_pause_binding(),
            resume_action="resume_peer_harness",
        )
        raise RuntimeError("gate failed")
    assert broker.calls[-1] == (
        "abort_paused_harness",
        ("/bin/kill", "-KILL", "--", "1234"),
    )
    assert registry.stops == ["m1b-port2-peer"]
    assert json.loads(evidence.read_text())["remaining_paused_run_ids"] == []


def test_resumed_harness_bounded_join_failure_still_forces_abort(
    tmp_path: Path,
) -> None:
    broker = _PauseBroker(tmp_path, [0])
    registry = _PauseRegistry()
    guard = _PausedHarnessUnwindGuard(
        broker=broker,  # type: ignore[arg-type]
        registry=registry,
        gate_id="CO-8",
        evidence_path=tmp_path / "unwind.json",
        futures={"m1b-port2-peer": _NeverCompletes()},
        join_timeout_seconds=0.01,
    )
    with pytest.raises(RuntimeError, match="post-resume failure"), guard:
        guard.note_pause(
            run_id="m1b-port2-peer",
            harness_pid=1234,
            binding=_pause_binding(),
            resume_action="resume_cohort_harness",
        )
        guard.resume("m1b-port2-peer")
        raise RuntimeError("post-resume failure")
    assert any(action == "abort_paused_harness" for action, _argv in broker.calls)
    assert registry.stops == ["m1b-port2-peer"]


def test_normal_exit_with_paused_harness_unwinds_then_fails_gate(
    tmp_path: Path,
) -> None:
    broker = _PauseBroker(tmp_path, [0])
    registry = _PauseRegistry()
    guard = _PausedHarnessUnwindGuard(
        broker=broker,  # type: ignore[arg-type]
        registry=registry,
        gate_id="PORT-2",
        evidence_path=tmp_path / "unwind.json",
        futures={},
    )
    with pytest.raises(GateExecutionError, match="completed with a paused"), guard:
        guard.note_pause(
            run_id="m1b-port2-peer",
            harness_pid=1234,
            binding=_pause_binding(),
            resume_action="resume_peer_harness",
        )
    assert guard.paused == {}
    assert registry.stops == ["m1b-port2-peer"]


class _OrphanBroker:
    def __init__(
        self,
        tmp_path: Path,
        *,
        returncode: int = 0,
        error: BaseException | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.returncode = returncode
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def execute(self, argv: Any, **kwargs: Any) -> BrokerReceipt:
        normalized = tuple(argv)
        self.calls.append({"argv": normalized, **kwargs})
        if self.error is not None:
            raise self.error
        evidence = self.tmp_path / f"orphan-broker-{len(self.calls)}.json"
        evidence.write_text("{}\n", encoding="utf-8")
        return BrokerReceipt(
            action="signal_supervisor",
            ok=self.returncode == 0,
            logical_argv=normalized,
            returncode=self.returncode,
            stdout="",
            stderr="",
            stdout_sha256=hashlib.sha256(b"").hexdigest(),
            stderr_sha256=hashlib.sha256(b"").hexdigest(),
            policy_sha256=SHA_A,
            broker_source_sha256=SHA_B,
            result=None,
            request_id="orphan-request",
            evidence_path=evidence,
        )


class _OrphanService:
    def __init__(
        self,
        run_id: str,
        *,
        reconciliation_error: BaseException | None = None,
    ) -> None:
        self.run_id = run_id
        self.reconciliation_error = reconciliation_error
        self.registry = _PauseRegistry()
        self.reconcile_calls = 0

    def reconcile_all(self) -> dict[str, Any]:
        self.reconcile_calls += 1
        if self.reconciliation_error is not None:
            raise self.reconciliation_error
        return {self.run_id: SimpleNamespace(run_id=self.run_id)}


def _orphan_guard(
    tmp_path: Path,
    *,
    broker: _OrphanBroker,
    service: _OrphanService,
    waitpid: Any,
    start_ticks_probe: Any,
    monotonic: Any = lambda: 0.0,
    sleep: Any = lambda _seconds: None,
    timeout: float = 1.0,
) -> _OrphanChildUnwindGuard:
    return _OrphanChildUnwindGuard(
        broker=broker,  # type: ignore[arg-type]
        binding=replace(_pause_binding(), run_id=service.run_id),
        service=service,  # type: ignore[arg-type]
        run_id=service.run_id,
        gate_id="ORPHAN-1",
        evidence_path=tmp_path / "orphan-child-unwind.json",
        wait_timeout_seconds=timeout,
        waitpid=waitpid,
        monotonic=monotonic,
        sleep=sleep,
        start_ticks_probe=start_ticks_probe,
    )


def test_orphan_child_unwind_binds_kills_reaps_and_reconciles_exactly(
    tmp_path: Path,
) -> None:
    pid = 4321
    waits = iter(((0, 0), (pid, signal.SIGKILL)))
    options: list[int] = []

    def waitpid(observed_pid: int, option: int) -> tuple[int, int]:
        assert observed_pid == pid
        options.append(option)
        return next(waits)

    broker = _OrphanBroker(tmp_path)
    service = _OrphanService("m1b-orphan-one")
    guard = _orphan_guard(
        tmp_path,
        broker=broker,
        service=service,
        waitpid=waitpid,
        start_ticks_probe=lambda observed_pid: 991 if observed_pid == pid else 0,
    )
    with guard:
        guard.note_child(pid)
        guard.bind_owned(SimpleNamespace(run_id=service.run_id, supervisor_pid=pid))
    assert options == [os.WNOHANG, os.WNOHANG]
    assert broker.calls == [
        {
            "argv": ("/bin/kill", "-KILL", "--", str(pid)),
            "binding": guard.binding,
            "timeout_seconds": 10.0,
            "action": "signal_supervisor",
            "parameters": {"supervisor_start_ticks": 991},
        }
    ]
    assert service.reconcile_calls == 1
    payload = json.loads(guard.evidence_path.read_text())
    assert payload["ok"] is True
    assert payload["child"] == {
        "identity_bound": True,
        "identity_current": True,
        "owned_supervisor_pid": pid,
        "pid": pid,
        "start_ticks": 991,
    }
    assert payload["wait"]["outcome"] == "signaled"
    assert payload["wait"]["signal"] == signal.SIGKILL


@pytest.mark.parametrize("mode", ["pid_mismatch", "starttime_drift"])
def test_orphan_child_identity_contradiction_prevents_broker_signal(
    tmp_path: Path,
    mode: str,
) -> None:
    pid = 4321
    ticks = iter((991, 992)) if mode == "starttime_drift" else None
    broker = _OrphanBroker(tmp_path)
    service = _OrphanService("m1b-orphan-one")
    guard = _orphan_guard(
        tmp_path,
        broker=broker,
        service=service,
        waitpid=lambda _pid, _option: (pid, 0),
        start_ticks_probe=(
            (lambda _pid: next(ticks)) if ticks is not None else (lambda _pid: 991)
        ),
    )
    with pytest.raises(GateExecutionError, match="ownership"), guard:
        guard.note_child(pid)
        guard.bind_owned(
            SimpleNamespace(
                run_id=service.run_id,
                supervisor_pid=pid + 1 if mode == "pid_mismatch" else pid,
            )
        )
    assert broker.calls == []
    assert service.reconcile_calls == 1
    assert json.loads(guard.evidence_path.read_text())["ok"] is False


def test_orphan_broker_failure_still_bounds_wait_and_reconciles(
    tmp_path: Path,
) -> None:
    pid = 4321
    broker = _OrphanBroker(tmp_path, error=RuntimeError("broker failed"))
    service = _OrphanService("m1b-orphan-one")
    guard = _orphan_guard(
        tmp_path,
        broker=broker,
        service=service,
        waitpid=lambda _pid, option: (pid, 0) if option == os.WNOHANG else (-1, 0),
        start_ticks_probe=lambda _pid: 991,
    )
    with pytest.raises(GateExecutionError, match="did not complete"), guard:
        guard.note_child(pid)
        guard.bind_owned(SimpleNamespace(run_id=service.run_id, supervisor_pid=pid))
    payload = json.loads(guard.evidence_path.read_text())
    assert payload["broker_kill"]["error_type"] == "RuntimeError"
    assert payload["wait"]["wnohang_only"] is True
    assert service.registry.stops == [service.run_id]
    assert service.reconcile_calls == 1


def test_orphan_wait_timeout_is_bounded_and_reconciliation_still_runs(
    tmp_path: Path,
) -> None:
    pid = 4321

    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    clock = Clock()
    calls: list[int] = []
    broker = _OrphanBroker(tmp_path)
    service = _OrphanService("m1b-orphan-one")
    guard = _orphan_guard(
        tmp_path,
        broker=broker,
        service=service,
        waitpid=lambda _pid, option: calls.append(option) or (0, 0),
        start_ticks_probe=lambda _pid: 991,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        timeout=0.11,
    )
    with pytest.raises(GateExecutionError, match="did not complete"), guard:
        guard.note_child(pid)
        guard.bind_owned(SimpleNamespace(run_id=service.run_id, supervisor_pid=pid))
    payload = json.loads(guard.evidence_path.read_text())
    assert payload["wait"]["outcome"] == "timeout"
    assert 2 <= len(calls) <= 5
    assert set(calls) == {os.WNOHANG}
    assert service.reconcile_calls == 1


@pytest.mark.parametrize(
    ("wait_status", "reconcile_error", "error_type"),
    [
        (signal.SIGKILL, RuntimeError("reconcile failed"), "RuntimeError"),
        (0, None, None),
    ],
)
def test_orphan_reconcile_failure_or_normal_exit_cannot_prove_unwind(
    tmp_path: Path,
    wait_status: int,
    reconcile_error: BaseException | None,
    error_type: str | None,
) -> None:
    pid = 4321
    broker = _OrphanBroker(tmp_path)
    service = _OrphanService("m1b-orphan-one", reconciliation_error=reconcile_error)
    guard = _orphan_guard(
        tmp_path,
        broker=broker,
        service=service,
        waitpid=lambda _pid, _option: (pid, wait_status),
        start_ticks_probe=lambda _pid: 991,
    )
    with pytest.raises(GateExecutionError, match="did not complete"), guard:
        guard.note_child(pid)
        guard.bind_owned(SimpleNamespace(run_id=service.run_id, supervisor_pid=pid))
    payload = json.loads(guard.evidence_path.read_text())
    assert payload["reconciliation"]["error_type"] == error_type
    if wait_status == 0:
        assert payload["wait"]["outcome"] == "exited"
        assert payload["wait"]["exit_code"] == 0


def test_attempt_grant_is_bound_to_active_gate_role_and_started_identity(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    _make_broker_dirs(layout)
    batch_id = "batch-one"
    opened = _ledger_record(
        schema="fortgym.m1b-live-acceptance-batch-ledger/v1",
        batch_id=batch_id,
        sequence=1,
        previous="0" * 64,
        event="batch_opened",
        payload={},
    )
    gate = _ledger_record(
        schema="fortgym.m1b-live-acceptance-batch-ledger/v1",
        batch_id=batch_id,
        sequence=2,
        previous=opened["record_sha256"],
        event="gate_started",
        payload={"gate": {"id": "PORT-2"}},
    )
    started = _ledger_record(
        schema="fortgym.m1b-live-acceptance-attempt-ledger/v1",
        batch_id=batch_id,
        sequence=1,
        previous="0" * 64,
        event="attempt_started",
        payload={
            "attempt_id": "g02-a01-peer_a",
            "gate_id": "PORT-2",
            "role": "peer_a",
            "kind": "real_runtime",
            "identity_sha256": SHA_A,
            "batch_ledger_head_sha256": gate["record_sha256"],
        },
    )
    control = layout.batch_evidence_root(batch_id) / "control"
    _write_ledger(control / "batch-ledger.jsonl", [opened, gate])
    _write_ledger(control / "attempt-ledger.jsonl", [started])
    broker = RootBroker(
        layout=layout,
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    request = {
        "batch_id": batch_id,
        "gate_id": "PORT-2",
        "grant_kind": "attempt",
        "attempt_id": "g02-a01-peer_a",
        "attempt_identity_sha256": SHA_A,
        "action": "pause_peer_harness",
    }
    phase = broker._validate_grant(request, caller_uid=os.getuid())
    assert phase is not None and phase.active_gate == "PORT-2"
    with pytest.raises(BrokerError, match="role"):
        broker._validate_grant(
            {**request, "action": "signal_runtime"}, caller_uid=os.getuid()
        )
    with pytest.raises(BrokerError, match="identity"):
        broker._validate_grant(
            {**request, "attempt_identity_sha256": SHA_B},
            caller_uid=os.getuid(),
        )

    completed = _ledger_record(
        schema="fortgym.m1b-live-acceptance-attempt-ledger/v1",
        batch_id=batch_id,
        sequence=2,
        previous=started["record_sha256"],
        event="attempt_completed",
        payload={"attempt_id": "g02-a01-peer_a"},
    )
    gate_completed = _ledger_record(
        schema="fortgym.m1b-live-acceptance-batch-ledger/v1",
        batch_id=batch_id,
        sequence=3,
        previous=gate["record_sha256"],
        event="gate_completed",
        payload={"gate": {"id": "PORT-2"}},
    )
    cleanup_started = _ledger_record(
        schema="fortgym.m1b-live-acceptance-batch-ledger/v1",
        batch_id=batch_id,
        sequence=4,
        previous=gate_completed["record_sha256"],
        event="cleanup_started",
        payload={"scope": "gate", "gate_id": "PORT-2"},
    )
    _write_ledger(
        control / "batch-ledger.jsonl", [opened, gate, gate_completed, cleanup_started]
    )
    _write_ledger(control / "attempt-ledger.jsonl", [started, completed])
    with pytest.raises(BrokerError, match="cleanup"):
        broker._validate_grant(request, caller_uid=os.getuid())
    cleanup_phase = broker._validate_grant(
        {**request, "action": "docker_managed_list"},
        caller_uid=os.getuid(),
    )
    assert cleanup_phase is not None and cleanup_phase.cleanup_scope == "gate"


class _Permit:
    gate_id = "ENOSPC"
    role = "target"
    attempt_id = "g08-a01-target"

    def __init__(self) -> None:
        self.started = False
        self.completed = False
        self.starts: list[str] = []

    def start(self, *, identity_sha256: str) -> None:
        self.started = True
        self.starts.append(identity_sha256)


def test_record_contracts_starts_cohort_permits_in_frozen_order(
    tmp_path: Path,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    backend = object.__new__(LinuxGateBackend)
    backend.paths = paths
    backend.resources = {"CO-8": host_runner_module.GateResources()}
    backend._permit_lock = threading.Lock()
    backend._permit_by_run = {}
    backend._attempt_identity_by_run = {}
    backend._bindings = {}
    observed: list[str] = []
    waited: list[int] = []
    backend._wait_for_reusable_port = waited.append

    class OrderedPermit:
        gate_id = "CO-8"
        kind = SimpleNamespace(value="real_runtime")

        def __init__(self, role: str, attempt_id: str) -> None:
            self.role = role
            self.attempt_id = attempt_id
            self.started = False

        def start(self, *, identity_sha256: str) -> None:
            assert len(identity_sha256) == 64
            self.started = True
            observed.append(self.attempt_id)

    contracts: dict[str, Any] = {}
    run_ids: list[str] = []
    for index in range(3):
        run_id = f"m1b-co8-run-{index + 1:02d}"
        run_ids.append(run_id)
        launch = paths.service_control_root / run_id / "launch.json"
        launch.parent.mkdir(parents=True, exist_ok=True)
        launch.write_bytes(_canonical_bytes({"run_id": run_id}) + b"\n")
        contracts[run_id] = SimpleNamespace(
            run_id=run_id,
            contract_sha256=hashlib.sha256(run_id.encode()).hexdigest(),
            nonce=f"{index + 1:032x}",
            cohort_digest=SHA_C,
            port=58_100 + index,
        )
        backend._permit_by_run[run_id] = OrderedPermit(
            role=f"run_{index + 1:02d}",
            attempt_id=f"g04-a{index + 1:02d}-run_{index + 1:02d}",
        )
    service = SimpleNamespace(
        _load_contract=lambda run_id: contracts[run_id],
    )

    recorded = backend._record_contracts("CO-8", service, tuple(run_ids))

    assert [contract.run_id for contract in recorded] == run_ids
    assert observed == [
        "g04-a01-run_01",
        "g04-a02-run_02",
        "g04-a03-run_03",
    ]
    assert waited == [58_100, 58_101, 58_102]
    assert set(backend._bindings) == set(run_ids)
    for run_id in run_ids:
        permit = backend._permit_by_run[run_id]
        backend._start_run_attempt(run_id)
        assert permit.started is True
    assert len(observed) == 3


def test_reused_gate_port_waits_through_transient_bind_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    backend = object.__new__(LinuxGateBackend)
    backend.paths = paths
    attempts = 0
    releases = 0

    class TransientLease:
        def __init__(self, port: int, lock_dir: Path) -> None:
            assert port == 58_000
            assert lock_dir == paths.service_control_root / "port-leases"

        def acquire(self) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise host_runner_module.PortLeaseError("transient bind refusal")

        def release(self) -> None:
            nonlocal releases
            releases += 1

    monkeypatch.setattr(host_runner_module, "PortLease", TransientLease)
    monkeypatch.setattr(host_runner_module.time, "sleep", lambda _seconds: None)

    backend._wait_for_reusable_port(58_000, timeout_seconds=1.0)

    assert attempts == 3
    assert releases == 1


def test_unreusable_gate_port_fails_before_attempt_permit_starts(
    tmp_path: Path,
) -> None:
    paths, _source_sha256 = _root_client_paths(tmp_path)
    backend = object.__new__(LinuxGateBackend)
    backend.paths = paths
    backend.resources = {"COLD-RETRY": host_runner_module.GateResources()}
    backend._permit_lock = threading.Lock()
    backend._attempt_identity_by_run = {}
    backend._bindings = {}
    run_id = "m1b-coldretry-suppressedfirst-timeout"
    launch = paths.service_control_root / run_id / "launch.json"
    launch.parent.mkdir(parents=True, exist_ok=True)
    launch.write_bytes(_canonical_bytes({"run_id": run_id}) + b"\n")

    class UnstartedPermit:
        gate_id = "COLD-RETRY"
        attempt_id = "g03-a01-suppressed_first"
        role = "suppressed_first"
        started = False

        def start(self, *, identity_sha256: str) -> None:
            raise AssertionError(f"attempt started unexpectedly: {identity_sha256}")

    permit = UnstartedPermit()
    backend._permit_by_run = {run_id: permit}
    backend._wait_for_reusable_port = lambda _port: (_ for _ in ()).throw(
        GateExecutionError("loopback port 58000 did not become reusable")
    )
    contract = SimpleNamespace(run_id=run_id, port=58_000)
    service = SimpleNamespace(_load_contract=lambda _run_id: contract)

    with pytest.raises(GateExecutionError, match="did not become reusable"):
        backend._record_contracts("COLD-RETRY", service, (run_id,))

    assert permit.started is False
    assert backend._attempt_identity_by_run == {}
    assert backend._bindings == {}


@pytest.mark.parametrize("use_loader", [True, False])
def test_enospc_mount_inspection_precedes_binding_without_privilege(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_loader: bool
) -> None:
    paths, _ = _root_client_paths(tmp_path)
    backend = object.__new__(LinuxGateBackend)
    backend.paths = paths
    backend._bindings = {}
    backend._prelaunch_enospc_binding = lambda *_: pytest.fail("inspection bound a slot")
    backend.broker = lambda *_: pytest.fail("inspection requested root")
    target, peer = backend._planned_ids("ENOSPC", ("target", "peer"))
    calls = []

    def inspect(_self: Any, argv: Any, *, timeout_seconds: float) -> Any:
        calls.append((tuple(argv), timeout_seconds))
        return host_runner_module.FaultCommandResult(
            argv=tuple(argv), returncode=1, stdout="", stderr=""
        )

    monkeypatch.setattr(host_runner_module.SubprocessFaultCommandRunner, "run", inspect)
    runner = (
        backend._evidence_loader("ENOSPC")._runner
        if use_loader else backend._fault_runner_for_unbound("ENOSPC")
    )
    for run_id in (target, peer):
        argv = ("/usr/bin/findmnt", "--json", "--bytes", "--target",
                str(paths.artifacts_root / run_id), "--output",
                "TARGET,FSTYPE,SIZE,OPTIONS,SOURCE")
        assert runner.run(argv, timeout_seconds=10).returncode == 1
    assert len(calls) == 2
    assert backend._bindings == {}


@pytest.mark.parametrize("violation", ["gate", "path", "options", "timeout", "symlink"])
def test_enospc_mount_inspection_rejects_scope_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, violation: str
) -> None:
    paths, _ = _root_client_paths(tmp_path)
    backend = object.__new__(LinuxGateBackend)
    backend.paths = paths
    target, _ = backend._planned_ids("ENOSPC", ("target", "peer"))
    workspace = paths.artifacts_root / target
    argv = ["/usr/bin/findmnt", "--json", "--bytes", "--target", str(workspace),
            "--output", "TARGET,FSTYPE,SIZE,OPTIONS,SOURCE"]
    if violation == "path":
        argv[4] = str(paths.artifacts_root / "foreign")
    elif violation == "options":
        argv[3] = "--mountpoint"
    elif violation == "symlink":
        workspace.parent.mkdir(parents=True, exist_ok=True)
        workspace.symlink_to(tmp_path)
    monkeypatch.setattr(
        host_runner_module.SubprocessFaultCommandRunner, "run",
        lambda *_args, **_kwargs: pytest.fail("unsafe probe executed"),
    )
    with pytest.raises(GateExecutionError, match="mount inspection escaped"):
        backend._read_enospc_mount(
            "OOM" if violation == "gate" else "ENOSPC", argv,
            timeout_seconds=11 if violation == "timeout" else 10,
        )


def test_enospc_prelaunch_starts_exactly_one_attempt_before_binding(
    tmp_path: Path,
) -> None:
    state = (tmp_path / "state").resolve()
    paths = HostPaths(
        batch_id="batch-one",
        packet_root=(tmp_path / "packet").resolve(),
        state_root=state,
        repo_root=(tmp_path / "repo").resolve(),
        dfroot=(tmp_path / "df").resolve(),
        runtime_archive_path=(tmp_path / "runtime.tar.zst").resolve(),
        broker_executable=(tmp_path / "broker").resolve(),
        sudo_executable=(tmp_path / "sudo").resolve(),
        require_canonical_host=False,
    )
    backend = object.__new__(LinuxGateBackend)
    backend.paths = paths
    backend._permit_by_run = {}
    backend._attempt_identity_by_run = {}
    backend._bindings = {}
    backend._run_sessions = {}
    target_id, peer_id = backend._planned_ids("ENOSPC", ("target", "peer"))
    permit = _Permit()
    backend._permit_by_run[target_id] = permit
    cohort = SHA_C
    for run_id, role in ((target_id, "target"), (peer_id, "peer")):
        launch = {
            "workspace_fault_profile": {"role": role},
            "contract": {
                "run_id": run_id,
                "contract_sha256": SHA_A if role == "target" else SHA_B,
                "rpc": {
                    "nonce": "12" * 16,
                    "port": 58_010 if role == "target" else 58_011,
                },
                "cotenancy": {"cohort_sha256": cohort},
            },
        }
        path = paths.service_control_root / run_id / "launch.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_canonical_bytes(launch) + b"\n")
    binding = backend._prelaunch_enospc_binding("ENOSPC")
    assert binding.run_id == target_id
    assert binding.peer_run_id == peer_id
    assert permit.starts == [binding.attempt_identity_sha256]
    assert backend._prelaunch_enospc_binding("ENOSPC") == binding
    assert len(permit.starts) == 1
    from dataclasses import replace

    # Real execution first registers an identity-only binding in
    # _record_contracts, before the peer/session association is available.
    backend._bindings[target_id] = replace(binding, peer_run_id=None)
    backend._run_sessions[target_id] = SHA_C
    enriched = backend._prelaunch_enospc_binding("ENOSPC")
    assert enriched.peer_run_id == peer_id
    assert enriched.session_sha256 == SHA_C
    assert len(permit.starts) == 1
    for changed in (
        replace(enriched, peer_run_id="foreign-peer"),
        replace(enriched, session_sha256=SHA_A),
        replace(enriched, contract_sha256=SHA_B),
    ):
        backend._bindings[target_id] = changed
        with pytest.raises(GateExecutionError, match="prelaunch binding changed"):
            backend._prelaunch_enospc_binding("ENOSPC")


@pytest.mark.parametrize("damage", [None, "image", "contract", "registry", "wrong_gate"])
def test_orphan_inspection_reconstructs_only_bound_parent_context(tmp_path, damage):
    backend = object.__new__(LinuxGateBackend)
    backend._permit_lock = threading.Lock()
    backend._runtime_controllers = {}
    backend.paths = SimpleNamespace(service_control_root=tmp_path)
    backend._permit_by_run = {
        "target": SimpleNamespace(gate_id="DF-KILL" if damage == "wrong_gate" else "ORPHAN-1")
    }
    backend._run_id_from_docker_argv = lambda _argv: "target"
    contract = SimpleNamespace(image_manifest_sha256=SHA_A, image_config_sha256=SHA_B,
                               image_archive_sha256=SHA_C)
    bound = []
    backend._binding_for_contract = lambda c: bound.append(c)
    record = SimpleNamespace(run_id="target")
    backend.registry = SimpleNamespace(get=lambda _: None if damage == "registry" else record)
    calls = []
    controller = SimpleNamespace(_resolved_image_reference=None)
    def construct(r, directory):
        assert r is record
        assert directory == tmp_path / "target"
        calls.append("construct_only")
        return controller
    service = SimpleNamespace(_load_contract=lambda _: contract, _runtime_controller=construct)
    backend._service = lambda **_kw: service
    resolution = {
        "schema": "fortgym.m1b-image-resolution/v1",
        "image_manifest_sha256": SHA_A,
        "image_config_sha256": SHA_B,
        "image_archive_sha256": SHA_C,
        "resolved_reference": f"sha256:{SHA_B}",
    }
    if damage == "image":
        resolution["resolved_reference"] = "untrusted:image"
    if damage == "contract":
        resolution["image_archive_sha256"] = SHA_A
    directory = tmp_path / "target/attempts/attempt-0001/runtime"
    directory.mkdir(parents=True)
    (directory / "image-resolution.json").write_text(json.dumps(resolution))
    argv = ("docker", "inspect", "--type", "container", "d" * 64)
    if damage is None:
        assert backend._runtime_controller_for_docker_argv(argv) is controller
        assert controller._resolved_image_reference == f"sha256:{SHA_B}"
        assert calls == ["construct_only"]
        assert bound == [contract]
    else:
        with pytest.raises(GateExecutionError):
            backend._runtime_controller_for_docker_argv(argv)
        assert calls == []


class _HostIntegrationAdapter:
    def __init__(self, root: Path, *, fail_after_start: bool) -> None:
        self.root = root
        self.fail_after_start = fail_after_start
        self.failure_injected = False
        self.unwind_reconciled = False
        self.cleanup_calls: list[tuple[str, str | None, int]] = []

    def _evidence(self, relative: str, payload: Mapping[str, Any]) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_canonical_bytes(payload) + b"\n")
        return path

    def execute_gate(self, context: GateExecutionContext) -> GateExecutionResult:
        if (
            self.fail_after_start
            and not self.failure_injected
            and context.gate_id == "DF-KILL"
        ):
            for index, permit in enumerate(context.attempts):
                permit.start(
                    identity_sha256=hashlib.sha256(
                        permit.attempt_id.encode("ascii")
                    ).hexdigest()
                )
                if index + 1 != len(context.attempts):
                    completed_evidence = self._evidence(
                        f"gates/DF-KILL/attempts/{permit.attempt_id}.json",
                        {
                            "schema": "fortgym.m1b-injected-attempt/v1",
                            "attempt_id": permit.attempt_id,
                            "role": permit.role,
                            "kind": permit.kind.value,
                        },
                    )
                    permit.complete(
                        outcome_code="terminal_recorded",
                        evidence_paths=(completed_evidence,),
                    )
            self.failure_injected = True
            self.unwind_reconciled = True
            self._evidence(
                "gates/DF-KILL/injected-unwind.json",
                {
                    "schema": "fortgym.m1b-injected-unwind/v1",
                    "attempt_id": context.attempts[-1].attempt_id,
                    "unwind_completed": True,
                    "reconciliation_completed": True,
                },
            )
            raise GateExecutionError("synthetic adapter failure after durable start")

        for permit in context.attempts:
            permit.start(
                identity_sha256=hashlib.sha256(
                    permit.attempt_id.encode("ascii")
                ).hexdigest()
            )
            if context.gate_id == "ENOSPC" and permit.role == "target":
                permit.bind_private_authorization(
                    authorization_identity_sha256="e" * 64
                )
            attempt_evidence = self._evidence(
                f"gates/{context.gate_id}/attempts/{permit.attempt_id}.json",
                {
                    "schema": "fortgym.m1b-injected-attempt/v1",
                    "attempt_id": permit.attempt_id,
                    "role": permit.role,
                    "kind": permit.kind.value,
                },
            )
            permit.complete(
                outcome_code=(
                    "port_lease_conflict"
                    if permit.kind.value == "non_runtime_conflict"
                    else "terminal_recorded"
                ),
                evidence_paths=(attempt_evidence,),
            )
        gate_evidence = self._evidence(
            f"gates/{context.gate_id}/gate-result.json",
            {
                "schema": "fortgym.m1b-injected-gate/v1",
                "gate_id": context.gate_id,
                "criteria": list(context.required_criteria),
            },
        )
        return GateExecutionResult(
            gate_id=context.gate_id,
            criteria_passed=context.required_criteria,
            evidence_paths=(gate_evidence,),
        )

    def cleanup_pass(self, context: CleanupPassContext) -> CleanupPassResult:
        self.cleanup_calls.append((context.scope, context.gate_id, context.pass_index))
        evidence = self._evidence(
            "cleanup/"
            f"{context.scope}-{context.gate_id or 'batch'}-{context.pass_index}.json",
            {
                "schema": "fortgym.m1b-injected-cleanup/v1",
                "scope": context.scope,
                "gate_id": context.gate_id,
                "pass_index": context.pass_index,
            },
        )
        cleanup_gate = next(
            gate for gate in FROZEN_GATE_PLAN if gate.gate_id == "CLEANUP"
        )
        return CleanupPassResult(
            scope=context.scope,
            gate_id=context.gate_id,
            pass_index=context.pass_index,
            criteria_passed=cleanup_gate.criteria,
            evidence_paths=(evidence,),
        )


class _HostIntegrationBroker:
    def __init__(self, paths: HostPaths) -> None:
        self.paths = paths
        self.calls: list[dict[str, Any]] = []
        self.observed_attempt_counts: dict[str, int] | None = None

    def execute(self, argv: Any, **kwargs: Any) -> BrokerReceipt:
        normalized = tuple(argv)
        self.calls.append({"argv": normalized, **kwargs})
        assert kwargs["action"] == "attest_broker_evidence"
        assert kwargs["binding"] is None
        attempt_ledger = self.paths.evidence_root / "control" / "attempt-ledger.jsonl"
        rows = [json.loads(line) for line in attempt_ledger.read_text().splitlines()]
        self.observed_attempt_counts = {
            "started": sum(row["event"] == "attempt_started" for row in rows),
            "completed": sum(row["event"] == "attempt_completed" for row in rows),
        }
        result = {
            "schema": "fortgym.m1b-root-broker-attestation-result/v1",
            "ok": True,
            "batch_id": self.paths.batch_id,
            "path": str(
                host_runner_module._ROOT_EVIDENCE_ROOT
                / "batches"
                / self.paths.batch_id
                / "broker-attestation.json"
            ),
            "sha256": "9" * 64,
        }
        evidence = (
            self.paths.evidence_root
            / "broker-client"
            / "CLEANUP"
            / "final-attestation.json"
        )
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_bytes(_canonical_bytes(result) + b"\n")
        stdout = json.dumps(result, sort_keys=True, separators=(",", ":"))
        empty_sha = hashlib.sha256(b"").hexdigest()
        return BrokerReceipt(
            action="attest_broker_evidence",
            ok=True,
            logical_argv=normalized,
            returncode=0,
            stdout=stdout,
            stderr="",
            stdout_sha256=hashlib.sha256(stdout.encode()).hexdigest(),
            stderr_sha256=empty_sha,
            policy_sha256=SHA_A,
            broker_source_sha256=SHA_B,
            result=result,
            request_id="final-attestation-request",
            evidence_path=evidence,
        )


class _HostIntegrationBackend:
    def __init__(self, paths: HostPaths) -> None:
        self.paths = paths
        self.final_broker = _HostIntegrationBroker(paths)
        self.canary_created = False
        self.canary_destroyed = False
        self._active_gate = None
        self._bindings: dict[str, Any] = {}
        self.resources: dict[str, Any] = {}

    def _ensure_canary(self, gate_id: str) -> None:
        assert gate_id == "BATCH-CANARY"
        self.canary_created = True
        receipt = self.paths.evidence_root / "batch-canary-created.json"
        receipt.write_bytes(
            _canonical_bytes(
                {
                    "schema": "fortgym.m1b-batch-canary-created/v1",
                    "batch_id": self.paths.batch_id,
                    "synthetic": True,
                }
            )
            + b"\n"
        )

    def broker(self, gate_id: str) -> _HostIntegrationBroker:
        assert gate_id == "CLEANUP"
        return self.final_broker

    def destroy_canary(self) -> Mapping[str, Any]:
        self.canary_destroyed = True
        return {
            "present": True,
            "removed": True,
            "name": "fortgym-m1b-foreign-synthetic",
            "container_id": "d" * 64,
            "container_absent": True,
            "container_absence_returncode": 0,
            "process_id": 4242,
            "process_start_ticks": 99,
            "process_absent": True,
            "workspace": str(self.paths.state_root / "canary" / self.paths.batch_id),
            "workspace_absent": True,
            "initial_container_state_sha256": "8" * 64,
            "pre_removal_container_state_sha256": "8" * 64,
            "pre_removal_broker_evidence_sha256": "1" * 64,
            "creation_broker_evidence_sha256": "2" * 64,
            "removal_broker_evidence_sha256": "3" * 64,
            "absence_broker_evidence_sha256": "4" * 64,
        }


def _host_integration_inputs(paths: HostPaths) -> SimpleNamespace:
    inputs = paths.evidence_root / "inputs"
    inputs.mkdir(parents=True, mode=0o700)
    contract = inputs / "acceptance.yaml"
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "infra/m1b/acceptance.yaml",
        contract,
    )
    assert hashlib.sha256(contract.read_bytes()).hexdigest() == FROZEN_ACCEPTANCE_SHA256
    source = inputs / "source-manifest.json"
    source.write_text('{"source":"synthetic-current"}\n', encoding="utf-8")
    credits: list[LocalCreditImport] = []
    for gate in FROZEN_GATE_PLAN:
        if gate.local_credit_scope is None:
            continue
        evidence = inputs / "local" / f"{gate.gate_id}.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_bytes(
            _canonical_bytes(
                {
                    "gate_id": gate.gate_id,
                    "criteria": list(gate.criteria),
                }
            )
            + b"\n"
        )
        credits.append(
            LocalCreditImport(
                gate_id=gate.gate_id,
                scope=gate.local_credit_scope,
                criteria_passed=gate.criteria,
                evidence_paths=(evidence,),
            )
        )
    return SimpleNamespace(
        contract_path=contract,
        source_manifest=SourceManifestLock(
            path=source,
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        ),
        local_credits=tuple(credits),
    )


@pytest.mark.parametrize(
    (
        "fail_after_start",
        "expected_decision",
        "expected_started",
        "expected_completed",
    ),
    [
        (False, BatchDecisionValue.GO, 26, 26),
        (True, BatchDecisionValue.INCOMPLETE_NO_GO, 26, 25),
    ],
)
def test_full_host_runner_reaches_root_attestation_for_go_and_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail_after_start: bool,
    expected_decision: BatchDecisionValue,
    expected_started: int,
    expected_completed: int,
) -> None:
    batch_id = "batch-go" if not fail_after_start else "batch-incomplete"
    paths = HostPaths(
        batch_id=batch_id,
        packet_root=(tmp_path / "packet").resolve(),
        state_root=(tmp_path / "state").resolve(),
        repo_root=Path(__file__).resolve().parents[1],
        dfroot=(tmp_path / "dfroot").resolve(),
        runtime_archive_path=(tmp_path / "runtime.tar.zst").resolve(),
        broker_executable=(tmp_path / "broker").resolve(),
        sudo_executable=(tmp_path / "sudo").resolve(),
        require_canonical_host=False,
    )
    paths.packet_root.mkdir()
    paths.evidence_root.mkdir(parents=True, mode=0o700)
    inputs = _host_integration_inputs(paths)
    adapter = _HostIntegrationAdapter(
        paths.evidence_root,
        fail_after_start=fail_after_start,
    )
    backend = _HostIntegrationBackend(paths)
    monkeypatch.setattr(host_runner_module, "validate_host_policy", lambda _paths: None)
    monkeypatch.setattr(host_runner_module, "prepare_inputs", lambda _paths: inputs)
    monkeypatch.setattr(
        host_runner_module, "LinuxGateBackend", lambda **_kwargs: backend
    )
    monkeypatch.setattr(
        host_runner_module,
        "LinuxM1BHostAdapter",
        lambda _backend, *, two_fort_diagnostic=False: adapter,
    )

    outcome = host_runner_module.run_live_acceptance(paths)

    assert outcome.decision is expected_decision
    assert outcome.real_runtime_attempts_started == expected_started
    assert outcome.real_runtime_attempts_completed == expected_completed
    assert outcome.non_runtime_attempts_started == 1
    assert outcome.non_runtime_attempts_completed == 1
    assert backend.canary_created is True
    assert backend.canary_destroyed is True
    assert len(adapter.cleanup_calls) == 32
    assert adapter.cleanup_calls[-2:] == [("batch", None, 1), ("batch", None, 2)]
    assert backend.final_broker.observed_attempt_counts == {
        "started": expected_started + 1,
        "completed": expected_completed + 1,
    }
    if fail_after_start:
        assert adapter.failure_injected is True
        assert adapter.unwind_reconciled is True
    cleanup = json.loads(outcome.post_seal_cleanup_path.read_text())
    assert cleanup["cleanup"]["container_absence_returncode"] == 0
    assert cleanup["cleanup"]["removed"] is True
    reference = json.loads(outcome.broker_attestation_reference_path.read_text())
    assert reference["root_attestation_sha256"] == outcome.broker_attestation_sha256
    assert backend.final_broker.calls[0]["parameters"] == {
        "controller_seal_sha256": hashlib.sha256(
            outcome.seal_path.read_bytes()
        ).hexdigest(),
        "post_seal_cleanup_sha256": outcome.post_seal_cleanup_sha256,
    }

    monkeypatch.setattr(
        host_runner_module,
        "run_live_acceptance",
        lambda _paths: outcome,
    )
    monkeypatch.setattr(host_runner_module, "HostPaths", lambda **_kwargs: paths)
    assert (
        host_runner_module.main(
            [
                "--private-test-mode",
                "--batch-id",
                batch_id,
                "--packet-root",
                str(paths.packet_root),
                "--state-root",
                str(paths.state_root),
            ]
        )
        == 0
    )
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["schema"] == "fortgym.m1b-host-runner-outcome/v1"
    assert stdout["decision"] == expected_decision.value
    assert stdout["broker_attestation_sha256"] == "9" * 64
    assert stdout["post_seal_cleanup_sha256"] == outcome.post_seal_cleanup_sha256


def test_protocol_constants_remain_cross_module_exact() -> None:
    assert BROKER_PLAN_SHA256 == FROZEN_PLAN_SHA256
    assert datetime.now(UTC).tzinfo is UTC
