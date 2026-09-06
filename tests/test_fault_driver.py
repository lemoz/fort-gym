from __future__ import annotations

import hashlib
import inspect
import json
import os
import pickle
import sqlite3
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml


@pytest.mark.parametrize("damage", [None, "missing", "false", "digest", "extra"])
def test_daemon_callback_preserves_strict_outer_guard_extension(damage):
    from fort_gym.bench.run.fault_driver import _validate_daemon_callback_fields
    value = {
        "schema": DAEMON_RESTART_CALLBACK_SCHEMA,
        "host_controller": True,
        "inside_container": False,
        "invoked": True,
        "outer_guard_verified": True,
        "outer_guard_stdout_sha256": "a" * 64,
        "outer_guard_broker_evidence_sha256": "b" * 64,
    }
    if damage == "missing":
        del value["outer_guard_stdout_sha256"]
    elif damage == "false":
        value["outer_guard_verified"] = False
    elif damage == "digest":
        value["outer_guard_stdout_sha256"] = "not-a-digest"
    elif damage == "extra":
        value["unexpected"] = True
    if damage is None:
        _validate_daemon_callback_fields(value)
    else:
        with pytest.raises(FaultEvidenceError):
            _validate_daemon_callback_fields(value)

from fort_gym.bench.run.fault_classification import (
    FAULT_CLASSIFIER_RESULT_SCHEMA,
    FAULT_OBSERVATION_SCHEMA,
    validate_fault_classifier_result,
)
from fort_gym.bench.run.fault_driver import (
    CANARY_OBSERVATION_SCHEMA,
    COHORT_START_SCHEMA,
    DAEMON_RESTART_CALLBACK_SCHEMA,
    FAULT_STATE_SCHEMA,
    RUN_OWNERSHIP_SCHEMA,
    STEP2_BARRIER_SCHEMA,
    EnospcWorkspaceCleanupTarget,
    FaultActionError,
    FaultAuthorizationError,
    FaultCommandResult,
    FaultEvidenceError,
    FaultEvidenceTimeout,
    FaultGate,
    LinuxHostFaultProbe,
    M1BFaultDriver,
    OwnedRun,
    OwnedRunEvidenceLoader,
    OwnedRunEvidencePending,
    PrelaunchEnospcTarget,
    PrelaunchEnospcWorkspace,
    PreReadinessOomMonitor,
    PreReadinessOomTarget,
    ProtectedCanary,
    authorize_private_m1b_fault,
    fault_observation_journal_path,
    load_completed_fault_observation,
)
from fort_gym.bench.run.runtime_contract import RuntimeContract
from fort_gym.bench.run.runtime_controller import DockerRuntimeController

MIB_16 = 16_777_216
MIB_256 = 256 * 1024 * 1024
GIB_4 = 4 * 1024 * 1024 * 1024
POST_READINESS_GATES = tuple(gate for gate in FaultGate if gate is not FaultGate.OOM)


class RecordingRunner:
    def __init__(self, *, returncode: int = 0, enospc_bytes: int = 15_728_640) -> None:
        self.calls: list[tuple[tuple[str, ...], float]] = []
        self.returncode = returncode
        self.enospc_bytes = enospc_bytes

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> FaultCommandResult:
        normalized = tuple(argv)
        self.calls.append((normalized, timeout_seconds))
        stdout = ""
        if "fortgym-m1b-enospc.fill" in " ".join(normalized):
            stdout = json.dumps(
                {
                    "errno": 28,
                    "fault_bytes": self.enospc_bytes,
                    "maximum_fault_bytes": MIB_16,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        return FaultCommandResult(
            normalized,
            self.returncode,
            stdout=stdout,
            stderr="",
        )


class TmpfsRunner:
    def __init__(self, mounts: dict[str, dict[str, Any]]) -> None:
        self.mounts = mounts
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> FaultCommandResult:
        del timeout_seconds
        normalized = tuple(argv)
        self.calls.append(normalized)
        if normalized[0] == "/bin/mount":
            path = normalized[-1]
            source = normalized[-2]
            self.mounts[path] = {
                "target": path,
                "filesystem": "tmpfs",
                "size_bytes": MIB_16,
                "options": "rw,nosuid,nodev,noexec",
                "source": source,
            }
        elif normalized[0] == "/bin/umount":
            path = normalized[-1]
            self.mounts.pop(path, None)
            marker = Path(path) / ".fortgym-m1b-workspace-owner.json"
            marker.unlink(missing_ok=True)
        return FaultCommandResult(normalized, 0)


class InspectRunner:
    def __init__(self, inspections: dict[str, dict[str, Any]]) -> None:
        self.inspections = inspections
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> FaultCommandResult:
        del timeout_seconds
        normalized = tuple(argv)
        self.calls.append(normalized)
        container_id = normalized[-1]
        inspection = self.inspections.get(container_id)
        if (
            normalized[:4]
            != (
                "/usr/bin/docker",
                "inspect",
                "--type",
                "container",
            )
            or inspection is None
        ):
            return FaultCommandResult(normalized, 1, stderr="not found")
        return FaultCommandResult(normalized, 0, stdout=json.dumps([inspection]))


def _run(tmp_path: Path, name: str, *, slot: int) -> OwnedRun:
    container_id = format(slot + 10, "x") * 64
    container_id = container_id[:64]
    return OwnedRun(
        run_id=name,
        contract_sha256=format(slot + 1, "x") * 64,
        nonce=format(slot + 2, "x") * 32,
        cohort_sha256="f" * 64,
        container_id=container_id,
        runtime_host_pid=10_000 + slot,
        runtime_container_pid=100 + slot,
        runtime_cgroup_path=f"/system.slice/docker-{container_id}.scope",
        harness_pid=20_000 + slot,
        harness_process_group_id=20_000 + slot,
        supervisor_pid=30_000,
        db_path=(tmp_path / "runs.sqlite").resolve(),
        workspace=(tmp_path / "workspaces" / name).resolve(),
        control_root=(tmp_path / "control").resolve(),
    )


@pytest.mark.parametrize(
    ("status", "step", "present", "accepted"),
    [("running", 2, True, False), ("completed", 5, True, False),
     ("running", 5, False, False), ("running", 5, True, True)],
)
def test_peer_health_diagnostics_preserve_exact_rejection_predicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    status: str, step: int, present: bool, accepted: bool,
) -> None:
    peer = _run(tmp_path, "peer", slot=1)
    probe = LinuxHostFaultProbe(target_run_id="target", path_exists=lambda _path: present)
    monkeypatch.setattr(probe, "_run_status", lambda _run: (status, step))
    monkeypatch.setattr(probe, "_rpc_generation", lambda _run: "generation")
    probe._barrier_rpc_generations[peer.run_id] = "generation"
    assert probe.peer_health_diagnostics() == {"sample_count": 0, "first": None, "last": None}
    for _ in range(200):
        observed = probe.state_probe(FaultGate.DF_KILL, peer, "peer_after")
        assert (observed is not None) is accepted
    diagnostic = probe.peer_health_diagnostics()
    assert diagnostic["sample_count"] == 200
    assert set(diagnostic) == {"sample_count", "first", "last"}
    for sample in (diagnostic["first"], diagnostic["last"]):
        assert sample["run_id"] == peer.run_id
        assert sample["status"] == status
        assert sample["step"] == step
        assert sample["harness_pid"] == peer.harness_pid
        assert sample["harness_present"] is present
    assert diagnostic["last"]["monotonic_seconds"] >= diagnostic["first"]["monotonic_seconds"]
    diagnostic["last"]["step"] = 999
    assert probe.peer_health_diagnostics()["last"]["step"] == step


def test_peer_timeout_retains_probe_samples_without_granting_acceptance(tmp_path: Path) -> None:
    peer = _run(tmp_path, "peer", slot=1)
    diagnostic = {"sample_count": 2, "first": {"step": 2}, "last": {"step": 4}}
    driver = M1BFaultDriver(
        barrier_probe=lambda _run: None,
        ownership_probe=lambda _run: {},
        state_probe=lambda _gate, _run, _phase: None,
        canary_probe=lambda _canary: {},
        state_diagnostic_probe=lambda: diagnostic,
        state_poll_attempts=2, sleep=lambda _seconds: None,
    )
    with pytest.raises(FaultEvidenceTimeout, match="peer health diagnostics=") as caught:
        driver._wait_for_state(FaultGate.DF_KILL, peer, "peer_after")
    assert json.loads(str(caught.value).split("peer health diagnostics=", 1)[1]) == diagnostic


def test_peer_progress_wait_is_separate_from_target_detection_polling(tmp_path: Path) -> None:
    peer = _run(tmp_path, "peer", slot=1)
    target = _run(tmp_path, "target", slot=0)
    elapsed = 0.0

    def sleep(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    def observe(gate: FaultGate, run: OwnedRun, phase: str) -> Mapping[str, Any] | None:
        if elapsed < 31.0:
            return None
        return _state(gate, run, phase, target=target)

    driver = M1BFaultDriver(
        barrier_probe=lambda _run: None, ownership_probe=lambda _run: {},
        state_probe=observe, canary_probe=lambda _canary: {},
        peer_state_poll_attempts=480, sleep=sleep,
    )
    # Reproduce the old ~30-second cutoff for target-state polling.
    with pytest.raises(FaultEvidenceTimeout):
        driver._wait_for_state(FaultGate.DF_KILL, target, "after")
    assert elapsed == 29.75
    elapsed = 0.0
    result = driver._wait_for_state(FaultGate.DF_KILL, peer, "peer_after")
    assert result["facts"]["step"] == 5
    assert elapsed == 31.0
    # Peer waiting remains bounded, including a peer that never advances.
    driver._state_probe = lambda _gate, _run, _phase: None
    elapsed = 0.0
    with pytest.raises(FaultEvidenceTimeout):
        driver._wait_for_state(FaultGate.DF_KILL, peer, "peer_after")
    assert elapsed == 119.75


def test_peer_probe_observes_committed_wal_progress_and_real_process_exit(tmp_path: Path) -> None:
    """Exercise real SQLite readers and process liveness without Docker or DF.

    macOS has no /proc, so only that filesystem lookup is translated to the
    portable process-existence syscall. All registry and lifecycle reads are real.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
        stdin=subprocess.PIPE,
    )
    try:
        peer = replace(_run(tmp_path, "peer", slot=1), harness_pid=child.pid)
        lifecycle = peer.control_root / peer.run_id / "attempts/attempt-0001/runtime/lifecycle.jsonl"
        lifecycle.parent.mkdir(parents=True)
        lifecycle.write_text(json.dumps({
            "schema": "fortgym.m1b-runtime-prepare/v1", "ok": True,
            "run_id": peer.run_id,
        }) + "\n")
        with sqlite3.connect(peer.db_path) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE runs (run_id TEXT, status TEXT, step INTEGER)")
            writer.execute("INSERT INTO runs VALUES (?, 'running', 2)", (peer.run_id,))
            writer.commit()

            def exists(path: Path) -> bool:
                if path == Path(f"/proc/{child.pid}"):
                    try:
                        os.kill(child.pid, 0)
                    except ProcessLookupError:
                        return False
                    return True
                return path.exists()

            probe = LinuxHostFaultProbe(target_run_id="target", path_exists=exists)
            probe._barrier_rpc_generations[peer.run_id] = probe._rpc_generation(peer)
            assert probe.state_probe(FaultGate.DF_KILL, peer, "peer_after") is None
            writer.execute("UPDATE runs SET step = 5 WHERE run_id = ?", (peer.run_id,))
            # An uncommitted update must never grant progress evidence.
            assert probe.state_probe(FaultGate.DF_KILL, peer, "peer_after") is None
            assert probe.peer_health_diagnostics()["last"]["step"] == 2
            writer.commit()
            observed = probe.state_probe(FaultGate.DF_KILL, peer, "peer_after")
            assert observed is not None
            assert observed["facts"]["healthy"] is True
            assert observed["facts"]["step"] == 5
            assert observed["facts"]["reconnected"] is False
            child.communicate(timeout=5)
            assert child.returncode == 0
            # A stale running row cannot make an exited process healthy.
            assert probe.state_probe(FaultGate.DF_KILL, peer, "peer_after") is None
            assert probe.peer_health_diagnostics()["last"]["harness_present"] is False
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def _prelaunch_enospc_target(target: OwnedRun, peer: OwnedRun) -> PrelaunchEnospcTarget:
    # Service reservation creates the control run directory before the
    # prelaunch workspace hook is allowed to run.
    (target.control_root / target.run_id).mkdir(parents=True, exist_ok=True)
    return PrelaunchEnospcTarget(
        run_id=target.run_id,
        contract_sha256=target.contract_sha256,
        nonce=target.nonce,
        cohort_sha256=target.cohort_sha256,
        peer_run_id=peer.run_id,
        db_path=target.db_path,
        workspace=target.workspace,
        control_root=target.control_root,
    )


def _enospc_cleanup_target(
    prelaunch: PrelaunchEnospcTarget, *, process_group_id: int
) -> EnospcWorkspaceCleanupTarget:
    return EnospcWorkspaceCleanupTarget(
        run_id=prelaunch.run_id,
        contract_sha256=prelaunch.contract_sha256,
        nonce=prelaunch.nonce,
        cohort_sha256=prelaunch.cohort_sha256,
        peer_run_id=prelaunch.peer_run_id,
        db_path=prelaunch.db_path,
        workspace=prelaunch.workspace,
        control_root=prelaunch.control_root,
        cleanup_mode="post_child_cleanup",
        harness_process_group_id=process_group_id,
    )


def _container_inspection(
    *,
    run_id: str,
    contract_sha256: str,
    nonce: str,
    cohort_sha256: str,
    container_id: str,
    container_name: str,
    init_pid: int,
    memory_bytes: int,
    fault_profile: str | None,
    image_manifest_sha256: str = "4" * 64,
    image_config_sha256: str = "5" * 64,
    running: bool = True,
    oom_killed: bool = False,
    exit_code: int = 0,
) -> dict[str, Any]:
    labels = {
        "fortgym.m1b.managed": "true",
        "fortgym.m1b.run_id": run_id,
        "fortgym.m1b.contract_sha256": contract_sha256,
        "fortgym.m1b.cohort_sha256": cohort_sha256,
    }
    if fault_profile is not None:
        labels["fortgym.m1b.fault_profile"] = fault_profile
    image = f"sha256:{image_manifest_sha256}"
    return {
        "Id": container_id,
        "Name": f"/{container_name}",
        "Image": image,
        "Config": {
            "Image": image,
            "Labels": labels,
            "Env": [
                f"FORTGYM_RUN_ID={run_id}",
                f"FORTGYM_CONTRACT_SHA256={contract_sha256}",
                f"FORTGYM_RUN_NONCE={nonce}",
            ],
        },
        "HostConfig": {
            "Memory": memory_bytes,
            "MemorySwap": memory_bytes,
        },
        "State": {
            "Pid": init_pid if running else 0,
            "Running": running,
            "OOMKilled": oom_killed,
            "ExitCode": exit_code,
        },
        "image_config_sha256": image_config_sha256,
    }


def _barrier(run: OwnedRun) -> dict[str, Any]:
    return {
        "schema": STEP2_BARRIER_SCHEMA,
        "run_id": run.run_id,
        "contract_sha256": run.contract_sha256,
        "nonce": run.nonce,
        "cohort_sha256": run.cohort_sha256,
        "container_id": run.container_id,
        "runtime_host_pid": run.runtime_host_pid,
        "runtime_container_pid": run.runtime_container_pid,
        "harness_pid": run.harness_pid,
        "workspace": str(run.workspace),
        "step": 2,
        "state": "reached",
        "durable": True,
        "journal_record_sha256": "a" * 64,
    }


def _cohort_start(run: OwnedRun, *, target_run_id: str) -> dict[str, Any]:
    target = run.run_id == target_run_id
    return {
        "schema": COHORT_START_SCHEMA,
        "run_id": run.run_id,
        "contract_sha256": run.contract_sha256,
        "nonce": run.nonce,
        "cohort_sha256": run.cohort_sha256,
        "container_id": run.container_id,
        "role": "target" if target else "peer",
        "memory_bytes": MIB_256 if target else GIB_4,
        "memory_swap_bytes": MIB_256 if target else GIB_4,
        "fault_profile": "oom_256m" if target else None,
        "provider_free": True,
        "state": "container_created",
        "durable": True,
        "journal_record_sha256": "b" * 64,
    }


def _ownership(
    run: OwnedRun,
    *,
    gate: FaultGate,
    target_run_id: str,
) -> dict[str, Any]:
    target_oom = gate is FaultGate.OOM and run.run_id == target_run_id
    enospc_target = gate is FaultGate.ENOSPC and run.run_id == target_run_id
    return {
        "schema": RUN_OWNERSHIP_SCHEMA,
        "run_id": run.run_id,
        "contract_sha256": run.contract_sha256,
        "nonce": run.nonce,
        "cohort_sha256": run.cohort_sha256,
        "container": {
            "id": run.container_id,
            "labels": {
                "managed": "true",
                "run_id": run.run_id,
                "contract_sha256": run.contract_sha256,
            },
            "environment": {
                "run_id": run.run_id,
                "contract_sha256": run.contract_sha256,
                "nonce": run.nonce,
            },
            "host_config": {
                "memory_bytes": MIB_256 if target_oom else GIB_4,
                "memory_swap_bytes": MIB_256 if target_oom else GIB_4,
                "fault_profile": "oom_256m" if target_oom else None,
            },
        },
        "runtime_process": {
            "host_pid": run.runtime_host_pid,
            "container_pid": run.runtime_container_pid,
            "run_id": run.run_id,
            "container_id": run.container_id,
            "executable_basename": "Dwarf_Fortress",
            "cgroup_path": run.runtime_cgroup_path,
        },
        "harness_process": {
            "pid": run.harness_pid,
            "run_id": run.run_id,
            "process_group_id": run.harness_process_group_id,
        },
        "supervisor_process": {"pid": run.supervisor_pid, "operational": True},
        "workspace_owner": {
            "path": str(run.workspace),
            "run_id": run.run_id,
            "private": True,
            "filesystem": "tmpfs" if enospc_target else "host-directory",
            "size_bytes": MIB_16 if enospc_target else GIB_4,
        },
    }


def _state(
    gate: FaultGate,
    run: OwnedRun,
    phase: str,
    *,
    target: OwnedRun,
    enospc_bytes: int = 15_728_640,
) -> dict[str, Any]:
    if phase == "peer_before_release":
        facts = {
            "target_run_id": target.run_id,
            "cohort_sha256": run.cohort_sha256,
            "status": "running",
            "step": 2,
            "runtime_ready": True,
            "healthy": True,
            "reconnected": False,
            "continued_before_fault": True,
            "connection_generation": "8" * 64,
            "durable": True,
            "readiness_receipt_sha256": "9" * 64,
        }
    elif phase == "peer_after":
        daemon = gate is FaultGate.DAEMON_RESTART
        facts: dict[str, Any] = {
            "step": 2
            if daemon
            else (5 if gate in {FaultGate.DF_KILL, FaultGate.HARNESS_KILL} else 3),
            "healthy": not daemon,
            "reconnected": False,
            "continued_after_fault": not daemon,
            "target_run_id": target.run_id,
        }
        if gate is FaultGate.OOM:
            facts.update(
                {
                    "runtime_ready": True,
                    "cohort_sha256": run.cohort_sha256,
                    "connection_generation": "8" * 64,
                }
            )
    elif gate is FaultGate.DF_KILL:
        facts = (
            {
                "runtime_identity": run.container_id,
                "runtime_state": "running",
                "oom_killed": False,
            }
            if phase == "before"
            else {
                "runtime_identity": run.container_id,
                "runtime_state": "exited",
                "runtime_exit_code": 137,
                "signal": 9,
                "oom_killed": False,
            }
        )
    elif gate is FaultGate.HARNESS_KILL:
        facts = (
            {
                "child_pid": run.harness_pid,
                "child_state": "running",
                "process_group_members": [run.harness_pid, run.harness_pid + 1],
            }
            if phase == "before"
            else {
                "child_pid": run.harness_pid,
                "child_state": "signaled",
                "signal": 9,
                "process_group_members": [run.harness_pid + 1],
            }
        )
    elif gate is FaultGate.OOM:
        facts = {
            "runtime_identity": run.container_id,
            "runtime_exit_code": None if phase == "before" else 137,
            "cgroup_memory_events": (
                {"oom": 3, "oom_kill": 1}
                if phase == "before"
                else {"oom": 4, "oom_kill": 2}
            ),
            "host_oom_counter": 7,
        }
    elif gate is FaultGate.ENOSPC:
        facts = {
            "operation": "fill-private-workspace",
            "workspace": {
                "run_id": run.run_id,
                "scope_root": str(run.workspace),
                "fault_path": str(run.workspace / ".fortgym-m1b-enospc.fill"),
                "fault_bytes": 0 if phase == "before" else enospc_bytes,
                "maximum_fault_bytes": MIB_16,
                "filesystem": "tmpfs",
                "private": True,
                "size_bytes": MIB_16,
            },
        }
    elif gate is FaultGate.CONTAINER_RESTART:
        facts = {
            "container_identity": run.container_id,
            "restart_count": 2 if phase == "before" else 3,
            "running": True,
            "rpc_connection_generation": "rpc-generation-1",
            "reconnected": False,
            "terminal_observed": phase == "after",
        }
    elif gate is FaultGate.DAEMON_RESTART:
        facts = {
            "daemon_generation": "daemon-1" if phase == "before" else "daemon-2",
            "runtime_identity": run.container_id,
            "inside_container": False,
            "supervisor_operational": True,
            "rpc_connection_generation": "rpc-generation-1",
            "reconnected": False,
            "terminal_observed": phase == "after",
            "silent_continuation": False,
        }
    else:  # pragma: no cover - exhaustive enum guard
        raise AssertionError(gate)
    return {
        "schema": FAULT_STATE_SCHEMA,
        "gate": gate.value,
        "phase": phase,
        "run_id": run.run_id,
        "contract_sha256": run.contract_sha256,
        "nonce": run.nonce,
        "container_id": run.container_id,
        "runtime_host_pid": run.runtime_host_pid,
        "runtime_container_pid": run.runtime_container_pid,
        "harness_pid": run.harness_pid,
        "workspace": str(run.workspace),
        "facts": facts,
    }


def _canary(tmp_path: Path) -> ProtectedCanary:
    return ProtectedCanary(
        name="foreign-canary",
        container_id="e" * 64,
        process_ids=(40_001, 40_002),
        workspace=(tmp_path / "foreign" / "canary").resolve(),
    )


def _runtime_fault_profile(role: str) -> dict[str, Any]:
    target = role == "target"
    return {
        "schema": "fortgym.m1b-runtime-fault-profile/v1",
        "cohort_kind": "oom_256m_target_peer",
        "role": role,
        "name": "oom_256m" if target else "normal_4g",
        "memory_bytes": MIB_256 if target else GIB_4,
        "memory_swap_bytes": MIB_256 if target else GIB_4,
        "test_only": True,
    }


def _workspace_fault_profile(role: str) -> dict[str, Any]:
    target = role == "target"
    return {
        "schema": "fortgym.m1b-workspace-fault-profile/v1",
        "cohort_kind": "enospc_16m_target_peer",
        "role": role,
        "name": "enospc_16m" if target else "normal_workspace",
        "filesystem": "tmpfs" if target else "host",
        "size_bytes": MIB_16 if target else None,
        "test_only": True,
    }


def _loader_fixture(
    tmp_path: Path, *, oom_profiles: bool = False, workspace_profiles: bool = False
) -> tuple[
    OwnedRunEvidenceLoader,
    RuntimeContract,
    RuntimeContract,
    dict[str, dict[str, Any]],
    dict[Path, bytes],
    dict[Path, str],
    dict[str, Any],
]:
    assert not (oom_profiles and workspace_profiles)
    control_root = (tmp_path / "control").resolve()
    artifacts_root = (tmp_path / "artifacts").resolve()
    db_path = (tmp_path / "runs.sqlite").resolve()
    cohort = ("oom-target", "normal-peer")

    def contract(run_id: str, port: int, nonce_digit: str) -> RuntimeContract:
        return RuntimeContract(
            run_id=run_id,
            backend="dfhack",
            model="dfhack-governed-scripted",
            port=port,
            nonce=nonce_digit * 32,
            image_manifest_sha256="4" * 64,
            image_config_sha256="5" * 64,
            image_archive_sha256="6" * 64,
            seed_tree_sha256="7" * 64,
            seed_world_sha256="8" * 64,
            code_sha256="9" * 64,
            db_path=db_path,
            artifacts_root=artifacts_root,
            control_root=control_root,
            dfroot=(tmp_path / "dfroot").resolve(),
            seed_save="seed-save",
            runtime_save=f"runtime-{run_id}",
            cohort_run_ids=cohort,
        )

    target_contract = contract("oom-target", 58_000, "a")
    peer_contract = contract("normal-peer", 58_001, "b")
    profiles = {
        target_contract.run_id: _runtime_fault_profile("target"),
        peer_contract.run_id: _runtime_fault_profile("peer"),
    }
    workspace_fault_profiles = {
        target_contract.run_id: _workspace_fault_profile("target"),
        peer_contract.run_id: _workspace_fault_profile("peer"),
    }
    request = {
        "max_steps": 20,
        "ticks_per_step": 200,
        "evaluation_protocol": None,
        "preserve_save": False,
        "memory_window": 0,
        "safe": True,
    }
    for runtime_contract in (target_contract, peer_contract):
        run_dir = control_root / runtime_contract.run_id
        run_dir.mkdir(parents=True)
        launch = {
            "schema": "fortgym.m1b-service-launch/v1",
            "run_id": runtime_contract.run_id,
            "created_at": "2026-08-16T00:00:00Z",
            "contract": runtime_contract.environment_identity(),
            "request": request,
        }
        if oom_profiles:
            launch["runtime_fault_profile"] = profiles[runtime_contract.run_id]
        if workspace_profiles:
            launch["workspace_fault_profile"] = workspace_fault_profiles[
                runtime_contract.run_id
            ]
        (run_dir / "launch.json").write_text(json.dumps(launch), encoding="utf-8")

    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, backend TEXT, model TEXT, "
        "max_steps INTEGER, ticks_per_step INTEGER, status TEXT, step INTEGER, "
        "seed_save TEXT, runtime_save TEXT, preserve_save INTEGER, "
        "evaluation_protocol TEXT, supervision_mode TEXT, artifacts_dir TEXT, "
        "trace_path TEXT)"
    )
    for runtime_contract in (target_contract, peer_contract):
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                runtime_contract.run_id,
                runtime_contract.backend,
                runtime_contract.model,
                20,
                200,
                "pending" if workspace_profiles else "running",
                0 if workspace_profiles else 3,
                runtime_contract.seed_save,
                runtime_contract.runtime_save,
                0,
                None,
                "m1b-process",
                str(artifacts_root / runtime_contract.run_id),
                str(artifacts_root / runtime_contract.run_id / "trace.jsonl"),
            ),
        )
    connection.commit()
    connection.close()

    inspections: dict[str, dict[str, Any]] = {}
    binary_reads: dict[Path, bytes] = {}
    text_reads: dict[Path, str] = {}
    live_proc: set[Path] = set()
    process_ids: list[int] = []
    pgids: dict[int, int] = {}
    mounts: dict[str, dict[str, Any]] = {}

    def read_bytes(path: Path) -> bytes:
        return binary_reads[path] if path in binary_reads else path.read_bytes()

    def read_text(path: Path) -> str:
        return text_reads[path] if path in text_reads else path.read_text()

    tmpfs_runner = TmpfsRunner(mounts)
    loader = OwnedRunEvidenceLoader(
        control_root=control_root,
        db_path=db_path,
        artifacts_root=artifacts_root,
        command_runner=InspectRunner(inspections),
        read_bytes=read_bytes,
        read_text=read_text,
        path_exists=lambda path: path in live_proc or path.exists(),
        getpgid=lambda pid: pgids[pid],
        process_ids=lambda: tuple(process_ids),
        mount_probe=lambda path: mounts.get(str(path)),
    )
    context: dict[str, Any] = {"mounts": mounts}
    if workspace_profiles:
        artifacts_root.mkdir(parents=True)
        prelaunch = loader.load_prelaunch_enospc_target(target_contract.run_id)
        authorization = authorize_private_m1b_fault(
            test_mode=True,
            gate=FaultGate.ENOSPC,
            target_run_id=target_contract.run_id,
            peer_run_id=peer_contract.run_id,
        )
        lifecycle = PrelaunchEnospcWorkspace(
            command_runner=tmpfs_runner,
            mount_probe=lambda path: mounts.get(str(path)),
        )
        receipt = lifecycle.prepare_workspace(
            authorization=authorization, target=prelaunch
        )
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE runs SET status = 'running', step = 3")
        connection.commit()
        connection.close()
        context.update(
            {
                "authorization": authorization,
                "lifecycle": lifecycle,
                "prelaunch": prelaunch,
                "receipt": receipt,
                "tmpfs_runner": tmpfs_runner,
                "order": ["workspace_prepared"],
            }
        )
    for slot, runtime_contract in enumerate((target_contract, peer_contract), start=1):
        run_id = runtime_contract.run_id
        contract_sha256 = runtime_contract.contract_sha256
        container_id = format(slot + 11, "x") * 64
        container_id = container_id[:64]
        container_name = f"fortgym-m1b-{run_id}-{contract_sha256[:12]}"
        supervisor_pid = 30_000
        manager_start_ticks = 40_000
        child_pid = 20_000 + slot
        init_pid = 10_000 + slot
        dwarf_pid = 11_000 + slot
        container_pid = 100 + slot
        attempt_dir = control_root / run_id / "attempts" / "attempt-0001"
        runtime_dir = attempt_dir / "runtime"
        runtime_dir.mkdir(parents=True)
        (artifacts_root / run_id).mkdir(parents=True, exist_ok=True)
        owner = {
            "schema": "fortgym.supervised-manager-owner/v1",
            "run_id": run_id,
            "state": "active",
            "manager_pid": supervisor_pid,
            "manager_start_ticks": manager_start_ticks,
            "identity_bound": True,
            "contract_sha256": contract_sha256,
            "nonce_sha256": hashlib.sha256(
                runtime_contract.nonce.encode("ascii")
            ).hexdigest(),
            "environment_identity_sha256": hashlib.sha256(
                json.dumps(
                    runtime_contract.environment_identity(),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "observed_registry_status": "pending",
            "attempt_dir": str(attempt_dir),
            "updated_at": "2026-08-16T00:00:01Z",
        }
        (control_root / run_id / "owner.json").write_text(
            json.dumps(owner), encoding="utf-8"
        )
        attempt = {
            "schema": "fortgym.process-supervisor-attempt/v1",
            "at": "2026-08-16T00:00:02Z",
            "monotonic_ns": 1,
            "supervisor_pid": supervisor_pid,
            "event": "attempt_started",
            "run_id": run_id,
            "scripted": True,
            "provider_enabled": False,
            "argv0": "/usr/bin/python3",
            "port": runtime_contract.port,
            "environment_identity": runtime_contract.environment_identity(),
            "cotenancy": runtime_contract.cotenancy(),
            "supervisor_runtime": {},
        }
        child = {
            "schema": "fortgym.process-supervisor-attempt/v1",
            "at": "2026-08-16T00:00:03Z",
            "monotonic_ns": 2,
            "supervisor_pid": supervisor_pid,
            "event": "child_started",
            "run_id": run_id,
            "child_pid": child_pid,
        }
        (attempt_dir / "attempt-journal.jsonl").write_text(
            json.dumps(attempt) + "\n" + json.dumps(child) + "\n",
            encoding="utf-8",
        )
        receipt = {
            "schema": "fortgym.m1b-container-created/v1",
            "ok": True,
            "run_id": run_id,
            "contract_sha256": contract_sha256,
            "nonce_sha256": __import__("hashlib")
            .sha256(runtime_contract.nonce.encode())
            .hexdigest(),
            "cohort_sha256": runtime_contract.cohort_digest,
            "container_name": container_name,
            "container_id": container_id,
            "image_reference": f"sha256:{runtime_contract.image_manifest_sha256}",
            "fault_profile": None,
            "memory_bytes": GIB_4,
            "memory_swap_bytes": GIB_4,
        }
        (runtime_dir / "container-created.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        inspections[container_id] = _container_inspection(
            run_id=run_id,
            contract_sha256=contract_sha256,
            nonce=runtime_contract.nonce,
            cohort_sha256=runtime_contract.cohort_digest,
            container_id=container_id,
            container_name=container_name,
            init_pid=init_pid,
            memory_bytes=GIB_4,
            fault_profile=None,
        )
        cgroup_path = f"/system.slice/docker-{container_id}.scope"
        for pid in (supervisor_pid, child_pid, init_pid, dwarf_pid):
            live_proc.add(Path(f"/proc/{pid}"))
        text_reads[Path(f"/proc/{supervisor_pid}/stat")] = (
            f"{supervisor_pid} (fortgym-manager) "
            + " ".join(["S", *(["0"] * 18), str(manager_start_ticks), "0"])
            + "\n"
        )
        binary_reads[Path(f"/proc/{child_pid}/environ")] = (
            f"FORT_GYM_RUN_ID={run_id}\0"
            f"FORT_GYM_RUN_CONTRACT_SHA256={contract_sha256}\0"
            f"FORT_GYM_RUN_NONCE={runtime_contract.nonce}\0"
            f"FORT_GYM_CONTROL_DIR={attempt_dir}\0"
        ).encode()
        binary_reads[Path(f"/proc/{child_pid}/cmdline")] = (
            f"/usr/bin/python3\0-m\0fort_gym.bench.cli\0experiment\0"
            f"/tmp/config.yaml\0--external-run-id\0{run_id}\0"
        ).encode()
        text_reads[Path(f"/proc/{init_pid}/cgroup")] = f"0::{cgroup_path}\n"
        text_reads[Path(f"/proc/{dwarf_pid}/comm")] = "Dwarf_Fortress\n"
        text_reads[Path(f"/proc/{dwarf_pid}/status")] = (
            f"Name:\tDwarf_Fortress\nNSpid:\t{dwarf_pid}\t{container_pid}\n"
        )
        text_reads[Path(f"/proc/{dwarf_pid}/cgroup")] = f"0::{cgroup_path}\n"
        process_ids.append(dwarf_pid)
        pgids[child_pid] = child_pid

    if workspace_profiles:
        context["order"].append("manager_and_artifacts_started")

    return (
        loader,
        target_contract,
        peer_contract,
        inspections,
        binary_reads,
        text_reads,
        context,
    )


def _assert_no_raw_nonce(value: Any, nonce: str) -> None:
    if isinstance(value, Mapping):
        assert "nonce" not in value
        for nested in value.values():
            _assert_no_raw_nonce(nested, nonce)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_raw_nonce(nested, nonce)
    elif isinstance(value, str):
        assert value != nonce


def _enospc_terminal_chain_rows(
    *,
    contract: RuntimeContract,
    unmounted: Mapping[str, Any],
    crash_phase: str,
) -> list[dict[str, Any]]:
    """Build the exact progressive post-child terminal chain for ENOSPC tests."""

    child_pid = 20_001
    attempt_dir = (
        contract.control_root / contract.run_id / "attempts" / "attempt-0001"
    )
    identity = {
        "run_id": contract.run_id,
        "contract_sha256": contract.contract_sha256,
        "nonce_sha256": hashlib.sha256(contract.nonce.encode("ascii")).hexdigest(),
        "environment_identity_sha256": hashlib.sha256(
            json.dumps(
                contract.environment_identity(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "child_pid": child_pid,
        "port": contract.port,
    }
    snapshot_path = attempt_dir / "evidence-snapshot.json"
    snapshot_payload = {
        "schema": "fortgym.process-supervisor-evidence-snapshot/v1",
        "identity": identity,
        "primary_terminal_class": "completed",
        "primary_reason": {"code": "child_completed"},
    }
    snapshot_path.write_text(
        json.dumps(snapshot_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    common = {
        "schema": "fortgym.process-supervisor-attempt/v1",
        "at": "2026-08-16T00:00:04Z",
        "supervisor_pid": 30_000,
        "run_id": contract.run_id,
    }
    rows: list[dict[str, Any]] = [
        {
            "event": "terminal_pending_cleanup",
            "monotonic_ns": 3,
            "identity": identity,
            "primary_terminal_class": "completed",
            "primary_reason_sha256": "1" * 64,
            **common,
        },
        {
            "event": "evidence_snapshot_completed",
            "monotonic_ns": 4,
            "identity": identity,
            "ok": True,
            "snapshot_path": str(snapshot_path),
            "snapshot_sha256": snapshot_sha256,
            "fault_snapshot_attached": True,
            "error": None,
            **common,
        },
        {
            "event": "harness_process_group_reaped",
            "monotonic_ns": 5,
            "identity": identity,
            "ok": True,
            "skipped": False,
            "child_pid": child_pid,
            "group_exists": False,
            **common,
        },
        {"event": "post_cleanup_started", "monotonic_ns": 6, **common},
        {
            "event": "post_cleanup_completed",
            "monotonic_ns": 7,
            "ok": True,
            "details": dict(unmounted),
            **common,
        },
    ]
    cleanup = {
        "ok": True,
        "stages": [
            {"stage": "process_group", "ok": True, "details": {"absent": True}},
            {"stage": "post_callback", "ok": True, "details": dict(unmounted)},
        ],
    }
    cleanup_sha256 = hashlib.sha256(
        json.dumps(cleanup, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    terminal_draft_path = attempt_dir / "terminal-draft.json"
    terminal_draft_path.write_text(
        json.dumps(
            {
                "schema": "fortgym.process-supervisor-terminal/v1",
                "run_id": contract.run_id,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    terminal_draft_sha256 = hashlib.sha256(
        terminal_draft_path.read_bytes()
    ).hexdigest()
    suffix = [
        {
            "event": "runtime_container_removed",
            "monotonic_ns": 8,
            "identity": identity,
            "ok": True,
            "skipped": False,
            "container_absent": True,
            "listener_absent": True,
            **common,
        },
        {
            "event": "cleanup_recorded",
            "monotonic_ns": 9,
            "cleanup": cleanup,
            **common,
        },
        {
            "event": "runtime_fault_classification_recorded",
            "monotonic_ns": 10,
            "fault_classification": {
                "schema": "fortgym.runtime-fault-classification/v1",
                "attempted": False,
                "ok": True,
                "classified": False,
                "skipped": "classifier_not_configured",
            },
            "terminal_draft_path": str(terminal_draft_path),
            "terminal_draft_sha256": terminal_draft_sha256,
            **common,
        },
        {
            "event": "cleanup_verified",
            "monotonic_ns": 11,
            "identity": identity,
            "ok": True,
            "cleanup_sha256": cleanup_sha256,
            **common,
        },
        {
            "event": "cleanup_completed",
            "monotonic_ns": 12,
            "identity": identity,
            "ok": True,
            "cleanup_sha256": cleanup_sha256,
            **common,
        },
        {
            "event": "immutable_terminal_classification",
            "monotonic_ns": 13,
            "identity": identity,
            "terminal_class": "completed",
            "reason_sha256": "2" * 64,
            "cleanup_sha256": cleanup_sha256,
            "evidence_snapshot_sha256": snapshot_sha256,
            **common,
        },
        {
            "event": "terminal_pending",
            "monotonic_ns": 14,
            "terminal_class": "completed",
            "cleanup_ok": True,
            **common,
        },
    ]
    phase_lengths = {
        "post_cleanup": 0,
        "runtime_removed": 1,
        "cleanup_recorded": 2,
        "classified": 3,
        "cleanup_verified": 4,
        "cleanup_completed": 5,
        "immutable": 6,
        "terminal_pending": 7,
    }
    return [*rows, *suffix[: phase_lengths[crash_phase]]]


def _execute(
    tmp_path: Path,
    gate: FaultGate,
    *,
    runner: RecordingRunner | None = None,
    monotonic_values: Sequence[float] = (100.0, 101.0, 102.0),
    mutate_ownership: Any = None,
    mutate_state: Any = None,
) -> tuple[Any, RecordingRunner, OwnedRun, OwnedRun, Any, Any]:
    target = _run(tmp_path, "target-run", slot=1)
    peer = _run(tmp_path, "peer-run", slot=2)
    canary = _canary(tmp_path)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=gate,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    tmpfs = None
    if gate is FaultGate.ENOSPC:
        mounts: dict[str, dict[str, Any]] = {}
        tmpfs_runner = TmpfsRunner(mounts)
        tmpfs = PrelaunchEnospcWorkspace(
            command_runner=tmpfs_runner,
            mount_probe=lambda path: mounts.get(str(path)),
        )
        target.workspace.parent.mkdir(parents=True, exist_ok=True)
        tmpfs.prepare_workspace(
            authorization=authorization,
            target=_prelaunch_enospc_target(target, peer),
        )
    command_runner = runner or RecordingRunner()
    times = iter(monotonic_values)

    def ownership_probe(run: OwnedRun) -> Mapping[str, Any]:
        record = _ownership(run, gate=gate, target_run_id=target.run_id)
        return mutate_ownership(record, run) if mutate_ownership else record

    def state_probe(
        selected_gate: FaultGate, run: OwnedRun, phase: str
    ) -> Mapping[str, Any] | None:
        record = _state(
            selected_gate,
            run,
            phase,
            target=target,
            enospc_bytes=command_runner.enospc_bytes,
        )
        return mutate_state(record, run, phase) if mutate_state else record

    driver = M1BFaultDriver(
        barrier_probe=lambda run: _barrier(run),
        cohort_start_probe=lambda run: _cohort_start(run, target_run_id=target.run_id),
        ownership_probe=ownership_probe,
        state_probe=state_probe,
        canary_probe=lambda value: {
            "schema": CANARY_OBSERVATION_SCHEMA,
            "name": value.name,
            "identity_sha256": value.identity_sha256,
            "present": True,
        },
        command_runner=command_runner,
        daemon_restart_callback=lambda: {
            "schema": DAEMON_RESTART_CALLBACK_SCHEMA,
            "host_controller": True,
            "inside_container": False,
            "invoked": True,
        },
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
        monotonic=lambda: next(times),
    )
    result = driver.inject(
        authorization=authorization,
        target=target,
        peer=peer,
        protected_canaries=(canary,),
    )
    return result, command_runner, target, peer, authorization, tmpfs


def _oom_monitor_fixture(
    tmp_path: Path,
) -> tuple[
    PreReadinessOomMonitor,
    PreReadinessOomTarget,
    OwnedRun,
    InspectRunner,
    dict[str, int],
    dict[str, Any],
]:
    peer = _run(tmp_path, "normal-peer", slot=2)
    target = PreReadinessOomTarget(
        run_id="oom-target",
        contract_sha256="2" * 64,
        nonce="3" * 32,
        cohort_sha256=peer.cohort_sha256,
        container_name=f"fortgym-m1b-oom-target-{'2' * 12}",
        db_path=peer.db_path,
        workspace=(tmp_path / "workspaces" / "oom-target").resolve(),
        control_root=peer.control_root,
    )
    container_id = "d" * 64
    init_pid = 9_001
    cgroup_path = f"/system.slice/docker-{container_id}.scope"
    created = {
        "schema": "fortgym.m1b-container-created/v1",
        "ok": True,
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce_sha256": hashlib.sha256(target.nonce.encode()).hexdigest(),
        "cohort_sha256": target.cohort_sha256,
        "container_name": target.container_name,
        "container_id": container_id,
        "image_reference": "sha256:" + "4" * 64,
        "fault_profile": "oom_256m",
        "memory_bytes": MIB_256,
        "memory_swap_bytes": MIB_256,
    }
    hold_ready = {
        "schema": "fortgym.m1b-pre-readiness-oom-hold-ready/v1",
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce_sha256": hashlib.sha256(target.nonce.encode()).hexdigest(),
        "cohort_sha256": target.cohort_sha256,
        "fault_profile": "oom_256m",
        "memory_bytes": MIB_256,
        "memory_swap_bytes": MIB_256,
    }
    runtime_dir = (
        target.control_root / target.run_id / "attempts" / "attempt-0001" / "runtime"
    )
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "container-created.json").write_text(
        json.dumps(created), encoding="utf-8"
    )
    (runtime_dir / "pre-readiness-oom-hold-ready.json").write_text(
        json.dumps(hold_ready), encoding="utf-8"
    )
    inspection = _container_inspection(
        run_id=target.run_id,
        contract_sha256=target.contract_sha256,
        nonce=target.nonce,
        cohort_sha256=target.cohort_sha256,
        container_id=container_id,
        container_name=target.container_name,
        init_pid=init_pid,
        memory_bytes=MIB_256,
        fault_profile="oom_256m",
    )
    runner = InspectRunner({container_id: inspection})
    counters = {"oom": 1, "oom_kill": 0, "host": 9}

    def read_text(path: Path) -> str:
        if path == Path(f"/proc/{init_pid}/cgroup"):
            return f"0::{cgroup_path}\n"
        if (
            path
            == Path("/sys/fs/cgroup") / cgroup_path.lstrip("/") / "memory.events.local"
        ):
            return f"oom {counters['oom']}\noom_kill {counters['oom_kill']}\n"
        if path == Path("/proc/vmstat"):
            return f"oom_kill {counters['host']}\n"
        return path.read_text()

    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.OOM,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    times = iter((10.0, 11.0, 12.0))
    monitor = PreReadinessOomMonitor(
        authorization=authorization,
        target=target,
        peer_run_id=peer.run_id,
        peer_loader=lambda: peer,
        peer_cohort_start_probe=lambda run: _cohort_start(
            run, target_run_id=target.run_id
        ),
        peer_ownership_probe=lambda run: _ownership(
            run, gate=FaultGate.OOM, target_run_id=target.run_id
        ),
        peer_state_probe=lambda gate, run, phase: _state(
            gate,
            run,
            phase,
            target=SimpleNamespace(run_id=target.run_id),  # type: ignore[arg-type]
        ),
        canary_probe=lambda _canary: {},
        command_runner=runner,
        read_text=read_text,
        path_exists=lambda path: path == Path(f"/proc/{init_pid}") or path.exists(),
        peer_poll_attempts=2,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
        monotonic=lambda: next(times),
    )
    return monitor, target, peer, runner, counters, created


def _write_stopped_oom_receipt(
    target: PreReadinessOomTarget,
    runner: InspectRunner,
    counters: dict[str, int],
    *,
    global_oom_kill_delta: int = 1,
) -> dict[str, Any]:
    counters["oom"] = 2
    counters["oom_kill"] = 1
    counters["host"] += global_oom_kill_delta
    runner.inspections["d" * 64]["State"] = {
        "Pid": 0,
        "Running": False,
        "OOMKilled": True,
        "ExitCode": 137,
    }
    stopped = {
        "schema": "fortgym.m1b-pre-readiness-oom-observation/v1",
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce_sha256": hashlib.sha256(target.nonce.encode()).hexdigest(),
        "container_name": target.container_name,
        "container_id": "d" * 64,
        "fault_profile": "oom_256m",
        "memory_bytes": MIB_256,
        "memory_swap_bytes": MIB_256,
        "state": {"running": False, "oom_killed": True, "exit_code": 137},
    }
    runtime_dir = (
        target.control_root / target.run_id / "attempts" / "attempt-0001" / "runtime"
    )
    (runtime_dir / "pre-readiness-oom.json").write_text(
        json.dumps(stopped), encoding="utf-8"
    )
    return stopped


def test_frozen_acceptance_contract_matches_fault_driver_bounds() -> None:
    acceptance = yaml.safe_load(Path("infra/m1b/acceptance.yaml").read_text())
    gates = {gate["id"]: gate for gate in acceptance["gates"]}
    assert set(FaultGate) == {
        FaultGate(gate_id)
        for gate_id in (
            "DF-KILL",
            "HARNESS-KILL",
            "OOM",
            "ENOSPC",
            "CONTAINER-RESTART",
            "DAEMON-RESTART",
        )
    }
    assert gates["OOM"]["procedure"] == (
        "run target A at 256 MiB while peer B retains the normal cap"
    )
    assert gates["ENOSPC"]["pass"]["maximum_fault_bytes"] == MIB_16
    assert gates["DF-KILL"]["pass"]["detection_seconds_lte"] == 10
    assert gates["DAEMON-RESTART"]["pass"]["reconciliation_seconds_lte"] == 120


@pytest.mark.parametrize("test_mode", [False, "true", 1, None])
def test_ordinary_mode_cannot_mint_fault_capability(test_mode: object) -> None:
    with pytest.raises(FaultAuthorizationError, match="test_mode=True"):
        authorize_private_m1b_fault(
            test_mode=test_mode,  # type: ignore[arg-type]
            gate=FaultGate.DF_KILL,
            target_run_id="target",
            peer_run_id="peer",
        )


def test_inject_rejects_serialized_or_missing_fault_knobs_before_any_probe(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    driver = M1BFaultDriver(
        barrier_probe=lambda _run: calls.append("barrier"),  # type: ignore[arg-type,return-value]
        ownership_probe=lambda _run: calls.append("ownership"),  # type: ignore[arg-type,return-value]
        state_probe=lambda _gate, _run, _phase: calls.append("state"),  # type: ignore[arg-type,return-value]
        canary_probe=lambda _canary: calls.append("canary"),  # type: ignore[arg-type,return-value]
    )
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    with pytest.raises(FaultAuthorizationError, match="ordinary mode"):
        driver.inject(authorization={"gate": "DF-KILL"}, target=target, peer=peer)  # type: ignore[arg-type]
    assert calls == []
    assert not fault_observation_journal_path(
        target.control_root, target.run_id
    ).exists()


def test_private_fault_capability_is_nonserializable() -> None:
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.DF_KILL,
        target_run_id="target",
        peer_run_id="peer",
    )
    with pytest.raises(TypeError, match="non-serializable"):
        pickle.dumps(authorization)


@pytest.mark.parametrize("gate", POST_READINESS_GATES)
def test_every_gate_records_exact_shell_free_action_and_no_terminal(
    tmp_path: Path, gate: FaultGate
) -> None:
    result, runner, target, _peer, _authorization, _tmpfs = _execute(tmp_path, gate)
    payload = result.observation["payload"]
    rows = [json.loads(line) for line in result.journal_path.read_text().splitlines()]
    for row in rows:
        _assert_no_raw_nonce(row, target.nonce)
    serialized = result.journal_path.read_text(encoding="utf-8")
    assert "terminal_class" not in serialized
    assert payload["classifier_evidence_schema"].endswith("/v1")
    assert "cleanup_double_audit" in payload["pending_external_checks"]
    if gate is FaultGate.DF_KILL:
        assert runner.calls[0][0] == (
            "/bin/kill",
            "-KILL",
            "--",
            str(target.runtime_host_pid),
        )
        assert str(target.runtime_container_pid) not in runner.calls[0][0]
    elif gate is FaultGate.HARNESS_KILL:
        assert runner.calls[0][0] == (
            "/bin/kill",
            "-KILL",
            "--",
            str(target.harness_pid),
        )
    elif gate is FaultGate.ENOSPC:
        argv = runner.calls[0][0]
        assert argv[1:3] == ("-I", "-c")
        assert argv[-1] == str(MIB_16)
        assert argv[-2] == str(target.workspace / ".fortgym-m1b-enospc.fill")
        assert payload["action"]["enospc"]["errno"] == 28
    elif gate is FaultGate.CONTAINER_RESTART:
        assert runner.calls[0][0] == (
            "/usr/bin/docker",
            "restart",
            "--time",
            "0",
            target.container_id,
        )
    else:
        assert runner.calls == []
        assert payload["action"]["kind"] == "external_host_callback"
    for call, _timeout in runner.calls:
        assert all(";" not in token and "&&" not in token for token in call)


@pytest.mark.parametrize(
    ("gate", "terminal_class"),
    [
        (FaultGate.DF_KILL, "runtime_df_killed"),
        (FaultGate.HARNESS_KILL, "harness_killed"),
        (FaultGate.ENOSPC, "workspace_enospc"),
        (FaultGate.CONTAINER_RESTART, "runtime_container_restarted"),
        (FaultGate.DAEMON_RESTART, "docker_daemon_restarted"),
    ],
)
def test_completed_evidence_is_accepted_only_by_the_separate_classifier(
    tmp_path: Path, gate: FaultGate, terminal_class: str
) -> None:
    result, _runner, target, _peer, _authorization, _tmpfs = _execute(tmp_path, gate)
    primary_reason = (
        {"code": "child_signaled"}
        if gate is FaultGate.HARNESS_KILL
        else {"code": "child_exited"}
    )
    observation = {
        "schema": FAULT_OBSERVATION_SCHEMA,
        "run_id": target.run_id,
        "primary_terminal_class": "external_signal"
        if gate is FaultGate.HARNESS_KILL
        else "child_exit",
        "primary_reason": primary_reason,
        "child_pid": target.harness_pid,
        "returncode": -9 if gate is FaultGate.HARNESS_KILL else 1,
        "child_signal": 9 if gate is FaultGate.HARNESS_KILL else None,
        "environment_identity": {},
        "prepare": {},
        "termination": {},
        "cleanup": {"ok": True},
    }
    classified = validate_fault_classifier_result(
        {
            "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
            "terminal_class": terminal_class,
            "evidence": dict(result.classifier_evidence),
        },
        observation,
    )
    assert classified.terminal_class == terminal_class


def test_barrier_waits_for_both_exact_durable_receipts(tmp_path: Path) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.DF_KILL,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    counts = {target.run_id: 0, peer.run_id: 0}
    runner = RecordingRunner()

    def barrier(run: OwnedRun) -> Mapping[str, Any] | None:
        counts[run.run_id] += 1
        return None if counts[run.run_id] == 1 else _barrier(run)

    driver = M1BFaultDriver(
        barrier_probe=barrier,
        ownership_probe=lambda run: _ownership(
            run, gate=FaultGate.DF_KILL, target_run_id=target.run_id
        ),
        state_probe=lambda gate, run, phase: _state(gate, run, phase, target=target),
        canary_probe=lambda _canary: {},
        command_runner=runner,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
        monotonic=iter((1.0, 2.0, 3.0)).__next__,
    )
    driver.inject(authorization=authorization, target=target, peer=peer)
    assert counts == {target.run_id: 2, peer.run_id: 2}
    assert len(runner.calls) == 1


def test_missing_barrier_times_out_without_fault_action(tmp_path: Path) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.DF_KILL,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    runner = RecordingRunner()
    driver = M1BFaultDriver(
        barrier_probe=lambda _run: None,
        ownership_probe=lambda _run: pytest.fail("ownership must not run"),
        state_probe=lambda _gate, _run, _phase: pytest.fail("state must not run"),
        canary_probe=lambda _canary: pytest.fail("canary must not run"),
        command_runner=runner,
        barrier_poll_attempts=2,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(FaultEvidenceTimeout, match="step-2"):
        driver.inject(authorization=authorization, target=target, peer=peer)
    assert runner.calls == []
    assert (
        load_completed_fault_observation(
            control_root=target.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce=target.nonce,
            expected_gate=FaultGate.DF_KILL,
        )
        is None
    )


def test_pid_namespace_mismatch_fails_before_host_kill(tmp_path: Path) -> None:
    def mutate(record: dict[str, Any], run: OwnedRun) -> dict[str, Any]:
        if run.run_id == "target-run":
            record["runtime_process"]["container_pid"] = run.runtime_host_pid
        return record

    runner = RecordingRunner()
    with pytest.raises(FaultEvidenceError, match="process ownership"):
        _execute(tmp_path, FaultGate.DF_KILL, runner=runner, mutate_ownership=mutate)
    assert runner.calls == []


def test_post_readiness_driver_rejects_oom_owned_run_shape(tmp_path: Path) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.OOM,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    with pytest.raises(FaultAuthorizationError, match="PreReadinessOomMonitor"):
        M1BFaultDriver(
            barrier_probe=lambda _run: pytest.fail("must fail before probes"),
            ownership_probe=lambda _run: pytest.fail("must fail before probes"),
            state_probe=lambda _gate, _run, _phase: pytest.fail(
                "must fail before probes"
            ),
            canary_probe=lambda _canary: pytest.fail("must fail before probes"),
        ).inject(authorization=authorization, target=target, peer=peer)


def test_live_oom_capture_survives_removed_cgroup_without_fabricating_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor, target, _peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    monitor.arm(created)
    inspection = runner.inspections["d" * 64]
    assert monitor.capture_live_oom(inspection) is False
    counters["oom"] = 2
    counters["oom_kill"] = 1
    assert monitor.capture_live_oom(inspection) is True
    stopped = _write_stopped_oom_receipt(target, runner, counters)

    def missing(_path):
        raise FileNotFoundError("cgroup was removed after exit")

    monkeypatch.setattr(monitor, "_memory_events", missing)
    assert monitor.finalize(stopped)["ok"] is True
    completed = load_completed_fault_observation(
        control_root=target.control_root, run_id=target.run_id,
        contract_sha256=target.contract_sha256, nonce=target.nonce, expected_gate=FaultGate.OOM,
    )
    assert completed["payload"]["classifier_evidence"]["cgroup_memory_events"]["after"]["oom_kill"] == 1


def test_live_oom_capture_rejects_changed_init_identity(tmp_path: Path) -> None:
    monitor, _target, _peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    monitor.arm(created)
    counters["oom_kill"] = 1
    runner.inspections["d" * 64]["State"]["Pid"] += 1
    with pytest.raises(FaultEvidenceError, match="init changed"):
        monitor.capture_live_oom(runner.inspections["d" * 64])
    assert monitor._live_oom_events is None


def test_background_oom_capture_survives_exit_between_docker_polls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, target, _peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    monitor.arm(created)
    monitor.start_counter_capture()
    counters["oom"] = 2
    counters["oom_kill"] = 1
    monitor._counter_sampler.join(timeout=2.0)
    assert not monitor._counter_sampler.is_alive()
    assert monitor._sampled_oom[0]["oom_kill"] == 1
    stopped = _write_stopped_oom_receipt(target, runner, counters)

    def removed(_path):
        raise FileNotFoundError("container cgroup removed before next Docker poll")

    monkeypatch.setattr(monitor, "_memory_events", removed)
    assert monitor.finalize(stopped)["ok"] is True
    completed = load_completed_fault_observation(
        control_root=target.control_root, run_id=target.run_id,
        contract_sha256=target.contract_sha256, nonce=target.nonce,
        expected_gate=FaultGate.OOM,
    )
    assert completed["payload"]["classifier_evidence"]["cgroup_memory_events"]["after"]["oom_kill"] == 1


def test_background_oom_capture_stops_without_fabricating_a_sample(tmp_path: Path) -> None:
    monitor, _target, _peer, _runner, _counters, created = _oom_monitor_fixture(tmp_path)
    with pytest.raises(FaultAuthorizationError, match="armed"):
        monitor.start_counter_capture()
    monitor.arm(created)
    monitor.start_counter_capture()
    with pytest.raises(FaultAuthorizationError, match="already started"):
        monitor.start_counter_capture()
    monitor.stop_counter_capture()
    assert not monitor._counter_sampler.is_alive()
    assert monitor._sampled_oom is None
    assert monitor._live_oom_events is None


def test_pre_readiness_oom_monitor_requires_hold_and_peer_before_release_then_finalizes(
    tmp_path: Path,
) -> None:
    monitor, target, peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    arm = monitor.arm(created)
    assert arm["ok"] is True
    assert arm["container_init_host_pid"] == 9_001
    assert arm["peer_run_id"] == peer.run_id
    assert len(arm["peer_readiness_sha256"]) == 64
    assert "runtime_host_pid" not in arm
    assert runner.calls == [
        ("/usr/bin/docker", "inspect", "--type", "container", "d" * 64)
    ]

    stopped = _write_stopped_oom_receipt(target, runner, counters)
    finalized = monitor.finalize(stopped)
    assert finalized["ok"] is True
    completed = load_completed_fault_observation(
        control_root=target.control_root,
        run_id=target.run_id,
        contract_sha256=target.contract_sha256,
        nonce=target.nonce,
        expected_gate=FaultGate.OOM,
    )
    assert completed is not None
    payload = completed["payload"]
    assert payload["target"]["identity_kind"] == "pre_readiness_oom"
    assert payload["barrier"]["peer"]["run_id"] == peer.run_id
    assert payload["peer_before_release"]["phase"] == "peer_before_release"
    assert payload["peer_before_release"]["facts"]["runtime_ready"] is True
    assert payload["classifier_evidence"]["runtime_exit_code"] == 137
    assert payload["pending_external_checks"] == [
        "target_cleanup_verified",
        "cleanup_double_audit",
    ]


def test_pre_readiness_oom_monitor_rejects_missing_hold_without_inspect(
    tmp_path: Path,
) -> None:
    monitor, target, _peer, runner, _counters, created = _oom_monitor_fixture(tmp_path)
    (
        target.control_root
        / target.run_id
        / "attempts"
        / "attempt-0001"
        / "runtime"
        / "pre-readiness-oom-hold-ready.json"
    ).unlink()
    with pytest.raises(FaultEvidenceError, match="hold-ready.*absent"):
        monitor.arm(created)
    assert runner.calls == []


def test_owned_run_evidence_loader_builds_full_host_and_namespace_identity(
    tmp_path: Path,
) -> None:
    loader, target_contract, _peer_contract, _inspections, _bytes, _text, _context = (
        _loader_fixture(tmp_path)
    )
    loaded = loader.load(target_contract.run_id)
    assert loaded.run_id == target_contract.run_id
    assert loaded.contract_sha256 == target_contract.contract_sha256
    assert loaded.runtime_host_pid == 11_001
    assert loaded.runtime_container_pid == 101
    assert loaded.runtime_host_pid != loaded.runtime_container_pid
    assert loaded.harness_pid == 20_001
    assert loaded.harness_process_group_id == loaded.harness_pid


def test_owned_run_loader_rejects_manager_pid_reuse_during_evidence_read(
    tmp_path: Path,
) -> None:
    loader, target_contract, _peer_contract, _inspections, _bytes, text, _context = (
        _loader_fixture(tmp_path)
    )
    manager_stat = Path("/proc/30000/stat")
    stable = text[manager_stat]
    changed = stable.replace("40000", "40001")
    reads = iter((stable, changed))
    original_read_text = loader._read_text  # type: ignore[attr-defined]

    def read_text(path: Path) -> str:
        if path == manager_stat:
            return next(reads)
        return original_read_text(path)

    loader._read_text = read_text  # type: ignore[attr-defined]

    with pytest.raises(FaultEvidenceError, match="changed during evidence loading"):
        loader.load(target_contract.run_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_sha256", "f" * 64),
        ("nonce_sha256", "e" * 64),
        ("environment_identity_sha256", "d" * 64),
    ],
)
def test_owned_run_loader_rejects_manager_owner_contract_binding_drift(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    loader, target_contract, _peer_contract, _inspections, _bytes, _text, _context = (
        _loader_fixture(tmp_path)
    )
    owner_path = target_contract.control_root / target_contract.run_id / "owner.json"
    owner = json.loads(owner_path.read_text())
    owner[field] = value
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    with pytest.raises(FaultEvidenceError, match="ownership evidence differs"):
        loader.load(target_contract.run_id)


def test_owned_run_loader_waits_for_manager_prebinding_window(tmp_path: Path) -> None:
    loader, contract, _peer, _inspections, _bytes, _text, _context = _loader_fixture(tmp_path)
    run_dir = contract.control_root / contract.run_id
    owner_path = run_dir / "owner.json"
    original = owner_path.read_text()
    owner = json.loads(original)
    owner.update(
        identity_bound=False, contract_sha256=None, nonce_sha256=None,
        environment_identity_sha256=None,
    )
    journal = run_dir / "attempts/attempt-0001/attempt-journal.jsonl"
    saved_journal = journal.read_bytes()
    journal.unlink()
    container_receipt = run_dir / "attempts/attempt-0001/runtime/container-created.json"
    saved_container = container_receipt.read_bytes()
    container_receipt.unlink()
    owner_path.write_text(json.dumps(owner))
    assert loader.try_load(contract.run_id) is None
    # Once the manager binds the identity, the same run becomes loadable.
    owner_path.write_text(original)
    journal.write_bytes(saved_journal)
    container_receipt.write_bytes(saved_container)
    assert loader.try_load(contract.run_id).run_id == contract.run_id


def test_owned_run_loader_rejects_unbound_owner_after_supervision_started(tmp_path: Path) -> None:
    loader, contract, _peer, _inspections, _bytes, _text, _context = _loader_fixture(tmp_path)
    owner_path = contract.control_root / contract.run_id / "owner.json"
    owner = json.loads(owner_path.read_text())
    owner.update(
        identity_bound=False, contract_sha256=None, nonce_sha256=None,
        environment_identity_sha256=None,
    )
    owner_path.write_text(json.dumps(owner))
    with pytest.raises(FaultEvidenceError):
        loader.try_load(contract.run_id)


@pytest.mark.parametrize(
    "event",
    [
        "terminal_pending_cleanup",
        "evidence_snapshot_completed",
        "harness_process_group_reaped",
        "runtime_container_removed",
        "cleanup_verified",
        "cleanup_completed",
        "immutable_terminal_classification",
    ],
)
def test_owned_run_loader_rejects_every_terminal_chain_event(
    tmp_path: Path,
    event: str,
) -> None:
    loader, target_contract, _peer_contract, _inspections, _bytes, _text, _context = (
        _loader_fixture(tmp_path)
    )
    journal = (
        target_contract.control_root
        / target_contract.run_id
        / "attempts"
        / "attempt-0001"
        / "attempt-journal.jsonl"
    )
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event}) + "\n")

    with pytest.raises(FaultEvidenceError, match="terminal or cleanup sequencing"):
        loader.load(target_contract.run_id)


def test_owned_run_loader_profiles_are_role_aware_and_fail_closed(
    tmp_path: Path,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, _context = (
        _loader_fixture(tmp_path, oom_profiles=True)
    )
    target = loader.load_pre_readiness_oom_target(target_contract.run_id)
    peer = loader.load_oom_peer(
        peer_contract.run_id, target_run_id=target_contract.run_id
    )
    assert target.cohort_sha256 == peer.cohort_sha256
    with pytest.raises(FaultEvidenceError, match="service launch fields"):
        loader.load(target_contract.run_id)

    peer_launch_path = peer.control_root / peer.run_id / "launch.json"
    peer_launch = json.loads(peer_launch_path.read_text())
    peer_launch["runtime_fault_profile"]["memory_bytes"] = MIB_256
    peer_launch_path.write_text(json.dumps(peer_launch), encoding="utf-8")
    with pytest.raises(FaultEvidenceError, match="counterpart profile"):
        loader.load_pre_readiness_oom_target(target_contract.run_id)


def test_owned_run_loader_rejects_dwarf_namespace_mismatch(
    tmp_path: Path,
) -> None:
    loader, target_contract, _peer_contract, _inspections, _bytes, text, _context = (
        _loader_fixture(tmp_path)
    )
    status_path = Path("/proc/11001/status")
    text[status_path] = "Name:\tDwarf_Fortress\nNSpid:\t999\t101\n"
    with pytest.raises(FaultEvidenceError, match="Dwarf_Fortress process"):
        loader.load(target_contract.run_id)


def test_enospc_prelaunch_mount_then_manager_then_step2_then_cleanup_order(
    tmp_path: Path,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    assert context["order"] == [
        "workspace_prepared",
        "manager_and_artifacts_started",
    ]
    receipt = context["receipt"]
    assert receipt["prepared_before_manager"] is True
    assert receipt["shell"] is False
    target = loader.load_enospc_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    peer = loader.load_enospc_peer(
        peer_contract.run_id, target_run_id=target_contract.run_id
    )
    with pytest.raises(FaultEvidenceError, match="service launch fields"):
        loader.load(target.run_id)

    command_runner = RecordingRunner()
    result = M1BFaultDriver(
        barrier_probe=_barrier,
        ownership_probe=lambda run: _ownership(
            run, gate=FaultGate.ENOSPC, target_run_id=target.run_id
        ),
        state_probe=lambda gate, run, phase: _state(
            gate,
            run,
            phase,
            target=target,
            enospc_bytes=command_runner.enospc_bytes,
        ),
        canary_probe=lambda _canary: {},
        command_runner=command_runner,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
        monotonic=iter((1.0, 2.0, 3.0)).__next__,
    ).inject(
        authorization=context["authorization"],
        target=target,
        peer=peer,
    )
    context["order"].append("step2_fill_observed")

    # Simulate ProcessSupervisor's cleanup callback boundary: the child group
    # has been reaped, while cleanup_recorded/classification/terminal are absent.
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target.run_id, peer_run_id=peer.run_id
    )
    context["lifecycle"]._process_group_members = lambda _pgid: ()
    cleaned = context["lifecycle"].cleanup_workspace(target=cleanup_target)
    context["order"].append("workspace_unmounted")
    context["order"].append("terminal_allowed")
    assert cleaned["child_process_group_absent"] is True
    assert cleaned["residue_absent"] is True
    assert context["order"] == [
        "workspace_prepared",
        "manager_and_artifacts_started",
        "step2_fill_observed",
        "workspace_unmounted",
        "terminal_allowed",
    ]
    assert result.journal_path.exists()
    assert not result.journal_path.is_relative_to(target.workspace)


def test_enospc_cleanup_failure_prevents_terminal_boundary(tmp_path: Path) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    context["lifecycle"]._process_group_members = lambda _pgid: (20_001,)
    terminal_calls: list[str] = []
    with pytest.raises(FaultEvidenceError, match="process-group absence"):
        context["lifecycle"].cleanup_workspace(target=cleanup_target)
    if not context["mounts"]:
        terminal_calls.append("terminal")
    assert terminal_calls == []
    assert context["mounts"]


def test_oom_default_peer_wait_covers_readiness_bound_and_timeout_is_durable(
    tmp_path: Path,
) -> None:
    parameters = inspect.signature(PreReadinessOomMonitor).parameters
    attempts = parameters["peer_poll_attempts"].default
    interval = parameters["poll_interval_seconds"].default
    assert (attempts - 1) * interval >= 330

    monitor, target, _peer, runner, _counters, created = _oom_monitor_fixture(tmp_path)
    sleeps: list[float] = []
    monitor._peer_loader = lambda: None
    monitor._sleep = sleeps.append
    with pytest.raises(FaultEvidenceTimeout, match="within the 0s bound"):
        monitor.arm(created)
    assert sleeps == [0.0]
    assert runner.calls == [
        ("/usr/bin/docker", "inspect", "--type", "container", "d" * 64)
    ]
    rows = [
        json.loads(line)
        for line in fault_observation_journal_path(target.control_root, target.run_id)
        .read_text()
        .splitlines()
    ]
    assert rows[-1]["phase"] == "failed"
    assert "0s bound" in rows[-1]["payload"]["error"]


def test_oom_arm_does_not_release_for_owned_but_unready_peer(
    tmp_path: Path,
) -> None:
    monitor, target, _peer, runner, _counters, created = _oom_monitor_fixture(tmp_path)
    readiness_calls: list[str] = []

    def never_ready(_gate: FaultGate, _run: OwnedRun, phase: str) -> None:
        readiness_calls.append(phase)

    monitor._peer_state_probe = never_ready
    with pytest.raises(FaultEvidenceTimeout, match="durable health readiness"):
        monitor.arm(created)
    assert readiness_calls == ["peer_before_release", "peer_before_release"]
    assert runner.calls == [
        ("/usr/bin/docker", "inspect", "--type", "container", "d" * 64)
    ]
    rows = [
        json.loads(line)
        for line in fault_observation_journal_path(target.control_root, target.run_id)
        .read_text()
        .splitlines()
    ]
    assert rows[-1]["phase"] == "failed"
    assert not any(row["phase"] == "action_attempted" for row in rows)


def test_oom_finalize_rejects_peer_readiness_connection_change(
    tmp_path: Path,
) -> None:
    monitor, target, peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    readiness_count = 0

    def state_probe(gate: FaultGate, run: OwnedRun, phase: str) -> Mapping[str, Any]:
        nonlocal readiness_count
        record = _state(
            gate,
            run,
            phase,
            target=SimpleNamespace(run_id=target.run_id),  # type: ignore[arg-type]
        )
        if phase == "peer_before_release":
            readiness_count += 1
            if readiness_count > 1:
                record["facts"]["connection_generation"] = "7" * 64
        return record

    monitor._peer_state_probe = state_probe
    monitor.arm(created)
    stopped = _write_stopped_oom_receipt(target, runner, counters)
    with pytest.raises(FaultEvidenceError, match="silently reconnected"):
        monitor.finalize(stopped)
    assert peer.run_id == monitor.peer_run_id
    assert readiness_count == 2
    assert (
        load_completed_fault_observation(
            control_root=target.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce=target.nonce,
            expected_gate=FaultGate.OOM,
        )
        is None
    )


@pytest.mark.parametrize("interval", [True, float("nan"), float("inf"), "0"])
def test_oom_monitor_rejects_nonfinite_or_nonnumeric_poll_interval(
    tmp_path: Path, interval: object
) -> None:
    _monitor, target, peer, runner, _counters, _created = _oom_monitor_fixture(tmp_path)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.OOM,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    with pytest.raises(ValueError, match="finite non-negative"):
        PreReadinessOomMonitor(
            authorization=authorization,
            target=target,
            peer_run_id=peer.run_id,
            peer_loader=lambda: peer,
            peer_cohort_start_probe=lambda run: _cohort_start(
                run, target_run_id=target.run_id
            ),
            peer_ownership_probe=lambda run: _ownership(
                run, gate=FaultGate.OOM, target_run_id=target.run_id
            ),
            peer_state_probe=lambda gate, run, phase: _state(
                gate,
                run,
                phase,
                target=SimpleNamespace(run_id=target.run_id),  # type: ignore[arg-type]
            ),
            canary_probe=lambda _canary: {},
            command_runner=runner,
            poll_interval_seconds=interval,  # type: ignore[arg-type]
        )


def test_oom_monitor_rejects_boolean_monotonic_sample(tmp_path: Path) -> None:
    monitor, _target, _peer, _runner, _counters, created = _oom_monitor_fixture(
        tmp_path
    )
    monitor._monotonic = lambda: True
    with pytest.raises(ValueError, match="monotonic sample"):
        monitor.arm(created)


def test_oom_scope_subtracts_target_local_kill_from_global_counter(
    tmp_path: Path,
) -> None:
    monitor, target, _peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    monitor.arm(created)
    stopped = _write_stopped_oom_receipt(
        target,
        runner,
        counters,
        global_oom_kill_delta=2,
    )
    with pytest.raises(FaultEvidenceError, match="unattributed host OOM"):
        monitor.finalize(stopped)
    assert (
        load_completed_fault_observation(
            control_root=target.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce=target.nonce,
            expected_gate=FaultGate.OOM,
        )
        is None
    )


def test_cleanup_process_scope_does_not_hide_root_owned_runtime_discovery(tmp_path: Path) -> None:
    loader, contract, _peer, *_ = _loader_fixture(tmp_path)
    full_inventory = loader._process_ids()
    assert full_inventory
    loader._run_process_ids = lambda: ()
    target = loader.load(contract.run_id)
    assert target.runtime_host_pid in full_inventory
    assert loader._process_ids() == full_inventory
    assert loader._live_processes_with_run_id(contract.run_id) == ()


@pytest.mark.parametrize("variant", ["valid", "foreign_peer", "changed_contract", "missing_launch"])
def test_linux_workspace_marker_uses_canonical_launch_peer(
    tmp_path: Path, variant: str
) -> None:
    loader, contract, peer, *_ = _loader_fixture(tmp_path, workspace_profiles=True)
    target = loader.load_enospc_target(contract.run_id, peer_run_id=peer.run_id)
    marker_path = target.workspace / ".fortgym-m1b-workspace-owner.json"
    launch_path = target.control_root / target.run_id / "launch.json"
    if variant == "foreign_peer":
        marker = json.loads(marker_path.read_text())
        marker["peer_run_id"] = "foreign-peer"
        marker_path.write_text(json.dumps(marker))
    elif variant == "changed_contract":
        launch = json.loads(launch_path.read_text())
        launch["contract"]["cotenancy"]["peer_run_ids"] = ["foreign-peer"]
        launch_path.write_text(json.dumps(launch))
    elif variant == "missing_launch":
        launch_path.unlink()
    probe = LinuxHostFaultProbe(target_run_id=target.run_id)
    if variant != "valid":
        with pytest.raises(FaultEvidenceError):
            probe._workspace_owner(target)
        return
    observed = probe._workspace_owner(target)
    assert observed["run_id"] == target.run_id
    assert observed["private"] is True
    assert observed["filesystem"] == "tmpfs"
    assert observed["size_bytes"] == MIB_16


def test_enospc_requires_authorized_private_tmpfs_setup(tmp_path: Path) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.ENOSPC,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    with pytest.raises(FaultAuthorizationError, match="tmpfs setup"):
        M1BFaultDriver(
            barrier_probe=lambda run: _barrier(run),
            ownership_probe=lambda run: _ownership(
                run, gate=FaultGate.ENOSPC, target_run_id=target.run_id
            ),
            state_probe=lambda gate, run, phase: _state(
                gate, run, phase, target=target
            ),
            canary_probe=lambda _canary: {},
        ).inject(authorization=authorization, target=target, peer=peer)


@pytest.mark.parametrize("target", ["/workspace/target", "/", None])
def test_exact_mount_probe_distinguishes_enclosing_filesystem(target: str | None) -> None:
    from fort_gym.bench.run.fault_driver import _find_exact_mount_with_runner

    def run(argv, *, timeout_seconds):
        return FaultCommandResult(
            argv=tuple(argv), returncode=0,
            stdout=json.dumps({"filesystems": [{
                "target": target, "fstype": "tmpfs", "size": 16777216,
                "options": "rw", "source": "owned",
            }]}), stderr="",
        )

    runner = SimpleNamespace(run=run)
    if target is None:
        with pytest.raises(FaultEvidenceError, match="exact target"):
            _find_exact_mount_with_runner(runner, Path("/workspace/target"))
    else:
        observed = _find_exact_mount_with_runner(runner, Path("/workspace/target"))
        assert (observed is not None) == (target == "/workspace/target")


@pytest.mark.parametrize("variant", ["empty", "absent", "public", "nonempty", "mounted"])
def test_enospc_pre_mount_loader_validates_created_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    control = tmp_path / "control"
    artifacts = tmp_path / "artifacts"
    run_dir = control / "target"
    run_dir.mkdir(parents=True)
    (run_dir / "launch.json").write_text("{}")
    workspace = artifacts / "target"
    if variant != "absent":
        workspace.mkdir(mode=0o700, parents=True)
    if variant == "public":
        workspace.chmod(0o755)
    if variant == "nonempty":
        (workspace / "foreign").write_text("retained")
    loader = OwnedRunEvidenceLoader(
        control_root=control, db_path=control / "registry.sqlite3", artifacts_root=artifacts,
        mount_probe=lambda path: {"mounted": True} if variant == "mounted" else None,
    )
    contract = {
        "contract_sha256": "a" * 64, "rpc": {"nonce": "b" * 32},
        "cotenancy": {"peer_run_ids": ["peer"], "cohort_sha256": "c" * 64},
    }
    monkeypatch.setattr(loader, "_load_launch_and_registry", lambda *args, **kwargs: (
        contract, {"status": "pending", "step": 0}
    ))
    if variant == "empty":
        observed = loader.load_prelaunch_enospc_target("target", mountpoint_created=True)
        assert observed.workspace == workspace
        assert observed.peer_run_id == "peer"
        with pytest.raises(FaultEvidenceError, match="window is already closed"):
            loader.load_prelaunch_enospc_target("target")
    else:
        with pytest.raises(FaultEvidenceError):
            loader.load_prelaunch_enospc_target("target", mountpoint_created=True)


def test_private_tmpfs_lifecycle_has_exact_mount_and_safe_cleanup(
    tmp_path: Path,
) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.ENOSPC,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    mounts: dict[str, dict[str, Any]] = {}
    runner = TmpfsRunner(mounts)
    lifecycle = PrelaunchEnospcWorkspace(
        command_runner=runner,
        mount_probe=lambda path: mounts.get(str(path)),
        process_group_members=lambda _pgid: (),
    )
    target.workspace.parent.mkdir(parents=True)
    prelaunch = _prelaunch_enospc_target(target, peer)
    prepared = lifecycle.prepare_workspace(
        authorization=authorization,
        target=prelaunch,
    )
    assert prepared["shell"] is False
    assert target.workspace.stat().st_mode & 0o777 == 0o700
    assert f"size={MIB_16}" in prepared["mount_argv"][4]
    assert Path(prepared["mount_argv"][-1]) == target.workspace
    # Simulate the authorized injection attempt before post-cleanup unmount.
    authorization._consume(target_run_id=target.run_id, peer_run_id=peer.run_id)
    cleaned = lifecycle.cleanup_workspace(
        target=_enospc_cleanup_target(
            prelaunch, process_group_id=target.harness_process_group_id
        )
    )
    assert cleaned["residue_absent"] is True
    assert runner.calls[-1] == ("/bin/umount", "--", str(target.workspace))


def test_private_tmpfs_reconcile_uses_durable_owner_without_consumed_token(
    tmp_path: Path,
) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    setup_authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.ENOSPC,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    mounts: dict[str, dict[str, Any]] = {}
    runner = TmpfsRunner(mounts)
    lifecycle = PrelaunchEnospcWorkspace(
        command_runner=runner,
        mount_probe=lambda path: mounts.get(str(path)),
        process_group_members=lambda _pgid: (),
    )
    target.workspace.parent.mkdir(parents=True)
    prelaunch = _prelaunch_enospc_target(target, peer)
    lifecycle.prepare_workspace(authorization=setup_authorization, target=prelaunch)

    reconciled = lifecycle.reconcile_workspace(
        target=_enospc_cleanup_target(
            prelaunch, process_group_id=target.harness_process_group_id
        )
    )
    assert reconciled["operation"] == "reconciled"
    assert reconciled["shell"] is False
    assert reconciled["residue_absent"] is True
    assert runner.calls[-1] == ("/bin/umount", "--", str(target.workspace))


def test_private_tmpfs_reconcile_refuses_mount_without_owner_marker(
    tmp_path: Path,
) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    mounts: dict[str, dict[str, Any]] = {}
    runner = TmpfsRunner(mounts)
    lifecycle = PrelaunchEnospcWorkspace(
        command_runner=runner,
        mount_probe=lambda path: mounts.get(str(path)),
        process_group_members=lambda _pgid: (),
    )
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.ENOSPC,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )

    target.workspace.parent.mkdir(parents=True)
    prelaunch = _prelaunch_enospc_target(target, peer)
    lifecycle.prepare_workspace(authorization=authorization, target=prelaunch)
    (target.workspace / ".fortgym-m1b-workspace-owner.json").unlink()
    calls_before = list(runner.calls)
    with pytest.raises(FaultEvidenceError, match="marker is absent"):
        lifecycle.reconcile_workspace(
            target=_enospc_cleanup_target(
                prelaunch, process_group_id=target.harness_process_group_id
            )
        )
    assert runner.calls == calls_before
    assert mounts[str(target.workspace)]["source"] == (
        f"fortgym-m1b-enospc-{target.run_id}"
    )


def test_private_tmpfs_failed_mount_removes_empty_mountpoint(tmp_path: Path) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.ENOSPC,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    target.workspace.parent.mkdir(parents=True)
    lifecycle = PrelaunchEnospcWorkspace(
        command_runner=RecordingRunner(returncode=1),
        mount_probe=lambda _path: None,
    )

    with pytest.raises(FaultActionError, match="mount failed"):
        lifecycle.prepare_workspace(
            authorization=authorization,
            target=_prelaunch_enospc_target(target, peer),
        )
    assert not target.workspace.exists()


def test_enospc_prepare_requires_reserved_control_parent_before_mount(
    tmp_path: Path,
) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.ENOSPC,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    target.workspace.parent.mkdir(parents=True)
    runner = RecordingRunner()
    lifecycle = PrelaunchEnospcWorkspace(
        command_runner=runner,
        mount_probe=lambda _path: None,
    )
    prelaunch = PrelaunchEnospcTarget(
        run_id=target.run_id,
        contract_sha256=target.contract_sha256,
        nonce=target.nonce,
        cohort_sha256=target.cohort_sha256,
        peer_run_id=peer.run_id,
        db_path=target.db_path,
        workspace=target.workspace,
        control_root=target.control_root,
    )
    with pytest.raises(FaultActionError, match="reserved control parent"):
        lifecycle.prepare_workspace(authorization=authorization, target=prelaunch)
    assert runner.calls == []
    assert not target.workspace.exists()


def test_enospc_receipt_is_write_once_mode_600_and_fsynced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    loader, target_contract, _peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    prelaunch = context["prelaunch"]
    receipt_path = (
        prelaunch.control_root
        / target_contract.run_id
        / "prelaunch-enospc-workspace.json"
    )
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert receipt_path.read_bytes().endswith(b"\n")
    assert not receipt_path.is_relative_to(prelaunch.workspace)
    assert len(fsync_calls) >= 3  # marker, receipt, and receipt parent directory
    with pytest.raises(FaultEvidenceError, match="service launch fields"):
        loader.load(target_contract.run_id)


def test_enospc_cleanup_recovery_is_idempotent_after_exact_unmount(
    tmp_path: Path,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    context["lifecycle"]._process_group_members = lambda _pgid: ()
    first = context["lifecycle"].cleanup_workspace(target=cleanup_target)
    second = context["lifecycle"].reconcile_workspace(target=cleanup_target)
    assert first["operation"] == "unmounted"
    assert first["residue_absent"] is True
    assert second == {
        "schema": "fortgym.m1b-private-tmpfs/v1",
        "operation": "already_absent",
        "run_id": target_contract.run_id,
        "argv": None,
        "shell": False,
        "residue_absent": True,
    }


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
def test_enospc_loader_reconstructs_attested_post_unmount_crash_window(
    tmp_path: Path,
    crash_phase: str,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    context["lifecycle"]._process_group_members = lambda _pgid: ()
    unmounted = context["lifecycle"].cleanup_workspace(target=cleanup_target)
    journal = (
        target_contract.control_root
        / target_contract.run_id
        / "attempts"
        / "attempt-0001"
        / "attempt-journal.jsonl"
    )
    rows = _enospc_terminal_chain_rows(
        contract=target_contract,
        unmounted=unmounted,
        crash_phase=crash_phase,
    )
    with journal.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    recovered_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    recovered = context["lifecycle"].reconcile_workspace(
        target=recovered_target
    )

    assert recovered_target.cleanup_mode == "post_child_cleanup"
    assert recovered_target.harness_process_group_id == 20_001
    assert recovered["operation"] == "already_absent"
    assert recovered["residue_absent"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "interleaved",
        "missing_classification",
        "cleanup_not_ok",
        "unknown_terminal_class",
        "wrong_classification_binding",
        "wrong_supervisor",
        "terminal_present",
    ],
)
def test_enospc_loader_rejects_contradictory_terminal_pending_attestation(
    tmp_path: Path,
    mutation: str,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    context["lifecycle"]._process_group_members = lambda _pgid: ()
    unmounted = context["lifecycle"].cleanup_workspace(target=cleanup_target)
    journal = (
        target_contract.control_root
        / target_contract.run_id
        / "attempts"
        / "attempt-0001"
        / "attempt-journal.jsonl"
    )
    rows = _enospc_terminal_chain_rows(
        contract=target_contract,
        unmounted=unmounted,
        crash_phase="terminal_pending",
    )
    common = {
        "schema": "fortgym.process-supervisor-attempt/v1",
        "at": "2026-08-16T00:00:04Z",
        "supervisor_pid": 30_000,
        "run_id": target_contract.run_id,
    }
    if mutation == "duplicate":
        rows.append({**rows[-1], "monotonic_ns": 15})
    elif mutation == "interleaved":
        rows.insert(
            -1,
            {
                "event": "unexpected_before_terminal",
                "monotonic_ns": 14,
                **common,
            },
        )
    elif mutation == "missing_classification":
        rows = [
            row
            for row in rows
            if row["event"] != "runtime_fault_classification_recorded"
        ]
    elif mutation == "cleanup_not_ok":
        rows[-1]["cleanup_ok"] = False
    elif mutation == "unknown_terminal_class":
        rows[-1]["terminal_class"] = "poison_terminal"
    elif mutation == "wrong_classification_binding":
        classification = next(
            row
            for row in rows
            if row["event"] == "runtime_fault_classification_recorded"
        )
        classification["fault_classification"] = {
            "schema": "fortgym.runtime-fault-classification/v1",
            "attempted": True,
            "ok": True,
            "classified": True,
            "terminal_class": "workspace_enospc",
            "evidence": {"validated": True},
        }
    elif mutation == "wrong_supervisor":
        rows[-1]["supervisor_pid"] = 30_001
    elif mutation == "terminal_present":
        terminal_path = journal.parent / "terminal.json"
        terminal_path.write_text(
            json.dumps(
                {
                    "schema": "fortgym.process-supervisor-terminal/v1",
                    "run_id": target_contract.run_id,
                }
            ),
            encoding="utf-8",
        )
    with journal.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    with pytest.raises(FaultEvidenceError, match="terminal|trailing"):
        loader.load_enospc_cleanup_target(
            target_contract.run_id, peer_run_id=peer_contract.run_id
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_prefix",
        "reordered_prefix",
        "malformed_identity",
        "missing_snapshot",
        "runtime_removal_not_ok",
        "reordered_cleanup_boundaries",
    ],
)
def test_enospc_loader_rejects_malformed_seven_event_chain(
    tmp_path: Path,
    mutation: str,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    context["lifecycle"]._process_group_members = lambda _pgid: ()
    unmounted = context["lifecycle"].cleanup_workspace(target=cleanup_target)
    journal = (
        target_contract.control_root
        / target_contract.run_id
        / "attempts"
        / "attempt-0001"
        / "attempt-journal.jsonl"
    )
    rows = _enospc_terminal_chain_rows(
        contract=target_contract,
        unmounted=unmounted,
        crash_phase="terminal_pending",
    )
    if mutation == "duplicate_prefix":
        row = next(row for row in rows if row["event"] == "terminal_pending_cleanup")
        rows.insert(1, {**row, "monotonic_ns": 4})
    elif mutation == "reordered_prefix":
        snapshot_index = next(
            index
            for index, row in enumerate(rows)
            if row["event"] == "evidence_snapshot_completed"
        )
        reap_index = next(
            index
            for index, row in enumerate(rows)
            if row["event"] == "harness_process_group_reaped"
        )
        rows[snapshot_index], rows[reap_index] = rows[reap_index], rows[snapshot_index]
    elif mutation == "malformed_identity":
        row = next(
            row for row in rows if row["event"] == "harness_process_group_reaped"
        )
        row["identity"] = {**row["identity"], "run_id": "foreign-run"}
    elif mutation == "missing_snapshot":
        (journal.parent / "evidence-snapshot.json").unlink()
    elif mutation == "runtime_removal_not_ok":
        row = next(
            row for row in rows if row["event"] == "runtime_container_removed"
        )
        row["ok"] = False
    elif mutation == "reordered_cleanup_boundaries":
        verified_index = next(
            index for index, row in enumerate(rows) if row["event"] == "cleanup_verified"
        )
        completed_index = next(
            index
            for index, row in enumerate(rows)
            if row["event"] == "cleanup_completed"
        )
        rows[verified_index], rows[completed_index] = (
            rows[completed_index],
            rows[verified_index],
        )
    with journal.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    with pytest.raises(FaultEvidenceError, match="ENOSPC"):
        loader.load_enospc_cleanup_target(
            target_contract.run_id, peer_run_id=peer_contract.run_id
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "interleaved",
        "not_ok",
        "wrong_schema",
        "wrong_argv",
        "wrong_process_group",
    ],
)
def test_enospc_loader_rejects_contradictory_post_unmount_attestation(
    tmp_path: Path,
    mutation: str,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    context["lifecycle"]._process_group_members = lambda _pgid: ()
    unmounted = dict(
        context["lifecycle"].cleanup_workspace(target=cleanup_target)
    )
    if mutation == "wrong_schema":
        unmounted["schema"] = "fortgym.poison/v1"
    elif mutation == "wrong_argv":
        unmounted["argv"] = ["/bin/umount", "--", "/foreign/workspace"]
    elif mutation == "wrong_process_group":
        unmounted["child_process_group_id"] = 99_999
    completion = {
        "schema": "fortgym.process-supervisor-attempt/v1",
        "at": "2026-08-16T00:00:04Z",
        "monotonic_ns": 4,
        "supervisor_pid": 30_000,
        "event": "post_cleanup_completed",
        "run_id": target_contract.run_id,
        "ok": mutation != "not_ok",
        "details": unmounted,
    }
    journal = (
        target_contract.control_root
        / target_contract.run_id
        / "attempts"
        / "attempt-0001"
        / "attempt-journal.jsonl"
    )
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema": completion["schema"],
                    "at": completion["at"],
                    "supervisor_pid": completion["supervisor_pid"],
                    "event": "post_cleanup_started",
                    "run_id": completion["run_id"],
                    "monotonic_ns": 3,
                }
            )
            + "\n"
        )
        if mutation == "interleaved":
            handle.write(
                json.dumps(
                    {
                        "schema": completion["schema"],
                        "at": completion["at"],
                        "supervisor_pid": completion["supervisor_pid"],
                        "event": "unexpected_between_cleanup_events",
                        "run_id": completion["run_id"],
                        "monotonic_ns": 3,
                    }
                )
                + "\n"
            )
        handle.write(json.dumps(completion) + "\n")
        if mutation == "duplicate":
            handle.write(json.dumps({**completion, "monotonic_ns": 5}) + "\n")

    with pytest.raises(
        (FaultEvidenceError, OwnedRunEvidencePending),
        match="post-cleanup|completion",
    ):
        loader.load_enospc_cleanup_target(
            target_contract.run_id, peer_run_id=peer_contract.run_id
        )


def test_enospc_cleanup_rejects_foreign_mount_before_unmount(tmp_path: Path) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    workspace = str(context["prelaunch"].workspace)
    context["mounts"][workspace]["source"] = "foreign-tmpfs"
    loader._process_ids = lambda: (11_001, 11_002)  # type: ignore[attr-defined]
    calls_before = list(context["tmpfs_runner"].calls)
    with pytest.raises(FaultEvidenceError, match="mount identity"):
        loader.load_enospc_cleanup_target(
            target_contract.run_id, peer_run_id=peer_contract.run_id
        )
    assert context["tmpfs_runner"].calls == calls_before
    assert context["mounts"][workspace]["source"] == "foreign-tmpfs"


def test_enospc_pre_child_abort_reconstructs_without_retained_token(
    tmp_path: Path,
) -> None:
    loader, target_contract, peer_contract, _inspections, _bytes, _text, context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    run_dir = target_contract.control_root / target_contract.run_id
    attempt_dir = run_dir / "attempts" / "attempt-0001"
    (run_dir / "owner.json").unlink()
    (attempt_dir / "runtime" / "container-created.json").unlink()
    (attempt_dir / "runtime").rmdir()
    (attempt_dir / "attempt-journal.jsonl").unlink()
    attempt_dir.rmdir()
    (run_dir / "attempts").rmdir()
    loader._process_ids = lambda: ()  # type: ignore[attr-defined]
    cleanup_target = loader.load_enospc_cleanup_target(
        target_contract.run_id, peer_run_id=peer_contract.run_id
    )
    assert cleanup_target.cleanup_mode == "pre_child_abort"
    assert cleanup_target.harness_process_group_id is None
    context["lifecycle"]._process_group_members = lambda _pgid: pytest.fail(
        "pre-child abort must not invent a process group"
    )
    cleaned = context["lifecycle"].cleanup_workspace(target=cleanup_target)
    assert cleaned["cleanup_mode"] == "pre_child_abort"
    assert cleaned["child_process_group_id"] is None
    assert cleaned["residue_absent"] is True


def test_enospc_cleanup_reconstruction_rejects_hidden_run_process(
    tmp_path: Path,
) -> None:
    loader, target_contract, peer_contract, _inspections, binary, _text, _context = (
        _loader_fixture(tmp_path, workspace_profiles=True)
    )
    hidden_pid = 49_999
    binary[Path(f"/proc/{hidden_pid}/environ")] = (
        f"FORT_GYM_RUN_ID={target_contract.run_id}\0"
    ).encode()
    loader._process_ids = lambda: (hidden_pid,)  # type: ignore[attr-defined]
    with pytest.raises(OwnedRunEvidencePending, match="run-owned processes remain"):
        loader.load_enospc_cleanup_target(
            target_contract.run_id, peer_run_id=peer_contract.run_id
        )


@pytest.mark.parametrize("damage", [None, "same_generation", "reconnect"])
def test_manual_container_restart_uses_process_generation_not_automatic_counter(tmp_path, damage):
    def mutate(record, run, phase):
        if run.run_id == "target-run":
            facts = record["facts"]
            facts["restart_count"] = 0
            facts["runtime_generation"] = "a" * 64 if phase == "before" else "b" * 64
            if damage == "same_generation":
                facts["runtime_generation"] = "a" * 64
            if damage == "reconnect" and phase == "after":
                facts["reconnected"] = True
        return record
    if damage is None:
        result, *_ = _execute(tmp_path, FaultGate.CONTAINER_RESTART, mutate_state=mutate)
        assert result is not None
    else:
        with pytest.raises(FaultEvidenceError):
            _execute(tmp_path, FaultGate.CONTAINER_RESTART, mutate_state=mutate)


def test_container_process_generation_detects_pid_reuse():
    probe = object.__new__(LinuxHostFaultProbe)
    ticks = [123]
    def read_stat(path):
        assert path == Path("/proc/456/stat")
        fields = ["S"] + ["0"] * 18 + [str(ticks[0])]
        return "456 (name with spaces) " + " ".join(fields)
    probe._read_text = read_stat
    before = probe._container_process_generation(456)
    assert probe._container_process_generation(456) == before
    ticks[0] += 1
    assert probe._container_process_generation(456) != before
    with pytest.raises(FaultEvidenceError):
        probe._container_process_generation(True)


def test_container_restart_rejects_silent_target_reconnect(tmp_path: Path) -> None:
    def mutate(record: dict[str, Any], run: OwnedRun, phase: str) -> dict[str, Any]:
        if run.run_id == "target-run" and phase == "after":
            record["facts"]["reconnected"] = True
            record["facts"]["rpc_connection_generation"] = "rpc-generation-2"
        return record

    with pytest.raises(FaultEvidenceError, match="anti-reconnect"):
        _execute(tmp_path, FaultGate.CONTAINER_RESTART, mutate_state=mutate)


def test_daemon_restart_reconciliation_over_120_seconds_fails(tmp_path: Path) -> None:
    with pytest.raises(FaultEvidenceError, match="120 second"):
        _execute(
            tmp_path,
            FaultGate.DAEMON_RESTART,
            monotonic_values=(10.0, 20.0, 130.01),
        )


def test_df_detection_over_10_seconds_fails_and_cleanup_remains_external(
    tmp_path: Path,
) -> None:
    with pytest.raises(FaultEvidenceError, match="10 second"):
        _execute(
            tmp_path,
            FaultGate.DF_KILL,
            monotonic_values=(10.0, 20.01, 21.0),
        )
    result, _runner, _target, _peer, _auth, _tmpfs = _execute(
        tmp_path / "ok",
        FaultGate.DF_KILL,
        monotonic_values=(10.0, 20.0, 21.0),
    )
    assert result.observation["payload"]["pending_external_checks"] == [
        "cleanup_seconds_lte_30",
        "cleanup_double_audit",
    ]


def test_command_failure_is_durable_but_never_completed(tmp_path: Path) -> None:
    runner = RecordingRunner(returncode=9)
    with pytest.raises(FaultActionError, match="return code 9"):
        _execute(tmp_path, FaultGate.DF_KILL, runner=runner)
    target = _run(tmp_path, "target-run", slot=1)
    rows = [
        json.loads(line)
        for line in fault_observation_journal_path(target.control_root, target.run_id)
        .read_text()
        .splitlines()
    ]
    assert rows[-1]["phase"] == "failed"
    assert all(row["phase"] != "completed" for row in rows)


def test_completed_loader_is_strictly_bound_and_absence_is_none(tmp_path: Path) -> None:
    result, _runner, target, _peer, _authorization, _tmpfs = _execute(
        tmp_path, FaultGate.DF_KILL
    )
    loaded = load_completed_fault_observation(
        control_root=target.control_root,
        run_id=target.run_id,
        contract_sha256=target.contract_sha256,
        nonce=target.nonce,
        expected_gate=FaultGate.DF_KILL,
    )
    assert loaded == result.observation
    with pytest.raises(FaultEvidenceError, match="binding"):
        load_completed_fault_observation(
            control_root=target.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce="0" * 32,
            expected_gate=FaultGate.DF_KILL,
        )
    assert (
        load_completed_fault_observation(
            control_root=tmp_path / "absent-control",
            run_id="absent",
            contract_sha256="a" * 64,
            nonce="b" * 32,
        )
        is None
    )


def test_real_runtime_controller_consumes_exact_completed_driver_record(
    tmp_path: Path,
) -> None:
    result, _runner, target, _peer, _authorization, _tmpfs = _execute(
        tmp_path, FaultGate.DF_KILL
    )
    controller = SimpleNamespace(
        contract=SimpleNamespace(
            run_id=target.run_id,
            control_root=target.control_root,
            contract_sha256=target.contract_sha256,
            nonce=target.nonce,
        )
    )
    classified = DockerRuntimeController.classify_runtime_fault(
        controller,  # type: ignore[arg-type]
        {"run_id": target.run_id, "cleanup": {"ok": True}},
    )
    assert classified == {
        "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
        "terminal_class": "runtime_df_killed",
        "evidence": dict(result.classifier_evidence),
    }


def test_loader_rejects_tampered_fault_action(tmp_path: Path) -> None:
    result, _runner, target, _peer, _authorization, _tmpfs = _execute(
        tmp_path, FaultGate.DF_KILL
    )
    rows = [json.loads(line) for line in result.journal_path.read_text().splitlines()]
    rows[-1]["payload"]["action"]["argv"][-1] = str(target.runtime_container_pid)
    result.journal_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    with pytest.raises(FaultEvidenceError, match="DF-KILL action"):
        load_completed_fault_observation(
            control_root=target.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce=target.nonce,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("action.shell", True, "OOM action"),
        ("after.unattributed_host_oom_delta", 1, "unattributed host OOM"),
    ],
)
def test_completed_oom_loader_rejects_contradictory_durable_evidence(
    tmp_path: Path, field: str, value: Any, message: str
) -> None:
    monitor, target, _peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    monitor.arm(created)
    stopped = _write_stopped_oom_receipt(target, runner, counters)
    monitor.finalize(stopped)
    journal_path = fault_observation_journal_path(target.control_root, target.run_id)
    rows = [json.loads(line) for line in journal_path.read_text().splitlines()]
    if field == "action.shell":
        rows[-1]["payload"]["action"]["shell"] = value
    else:
        rows[-1]["payload"]["after"]["facts"]["unattributed_host_oom_delta"] = value
    journal_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    with pytest.raises(FaultEvidenceError, match=message):
        load_completed_fault_observation(
            control_root=target.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce=target.nonce,
            expected_gate=FaultGate.OOM,
        )


def test_completed_oom_loader_rejects_tampered_pre_release_peer_binding(
    tmp_path: Path,
) -> None:
    monitor, target, _peer, runner, counters, created = _oom_monitor_fixture(tmp_path)
    monitor.arm(created)
    stopped = _write_stopped_oom_receipt(target, runner, counters)
    monitor.finalize(stopped)
    journal_path = fault_observation_journal_path(target.control_root, target.run_id)
    rows = [json.loads(line) for line in journal_path.read_text().splitlines()]
    rows[-1]["payload"]["peer_before_release"]["facts"]["cohort_sha256"] = "0" * 64
    journal_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    with pytest.raises(FaultEvidenceError, match="pre-release baseline"):
        load_completed_fault_observation(
            control_root=target.control_root,
            run_id=target.run_id,
            contract_sha256=target.contract_sha256,
            nonce=target.nonce,
            expected_gate=FaultGate.OOM,
        )


def test_control_journal_is_mode_600_outside_workspaces_and_fsyncs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def fsync(descriptor: int) -> None:
        calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    result, _runner, target, peer, _authorization, _tmpfs = _execute(
        tmp_path, FaultGate.DF_KILL
    )
    assert calls
    assert result.journal_path.stat().st_mode & 0o777 == 0o600
    assert not result.journal_path.is_relative_to(target.workspace)
    assert not result.journal_path.is_relative_to(peer.workspace)
    rows = [json.loads(line) for line in result.journal_path.read_text().splitlines()]
    assert [row["event_index"] for row in rows] == list(range(1, len(rows) + 1))


def test_canary_collision_is_rejected_before_fault_action(tmp_path: Path) -> None:
    target = _run(tmp_path, "target", slot=1)
    peer = _run(tmp_path, "peer", slot=2)
    canary = ProtectedCanary(
        name="colliding-canary",
        container_id=target.container_id,
        process_ids=(50_001,),
        workspace=(tmp_path / "canary").resolve(),
    )
    authorization = authorize_private_m1b_fault(
        test_mode=True,
        gate=FaultGate.DF_KILL,
        target_run_id=target.run_id,
        peer_run_id=peer.run_id,
    )
    runner = RecordingRunner()
    with pytest.raises(FaultEvidenceError, match="protected canary"):
        M1BFaultDriver(
            barrier_probe=lambda run: _barrier(run),
            ownership_probe=lambda run: _ownership(
                run, gate=FaultGate.DF_KILL, target_run_id=target.run_id
            ),
            state_probe=lambda gate, run, phase: _state(
                gate, run, phase, target=target
            ),
            canary_probe=lambda _canary: {},
            command_runner=runner,
        ).inject(
            authorization=authorization,
            target=target,
            peer=peer,
            protected_canaries=(canary,),
        )
    assert runner.calls == []


def _docker_inspection(run: OwnedRun, *, oom: bool = False) -> dict[str, Any]:
    return {
        "Id": run.container_id,
        "Config": {
            "Labels": {
                "fortgym.m1b.managed": "true",
                "fortgym.m1b.run_id": run.run_id,
                "fortgym.m1b.contract_sha256": run.contract_sha256,
                **({"fortgym.m1b.fault_profile": "oom_256m"} if oom else {}),
            },
            "Env": [
                f"FORTGYM_RUN_ID={run.run_id}",
                f"FORTGYM_CONTRACT_SHA256={run.contract_sha256}",
                f"FORTGYM_RUN_NONCE={run.nonce}",
            ],
        },
        "HostConfig": {
            "Memory": MIB_256 if oom else GIB_4,
            "MemorySwap": MIB_256 if oom else GIB_4,
        },
        "State": {"Running": True, "OOMKilled": False, "ExitCode": 0},
        "RestartCount": 0,
    }


def test_concrete_linux_probe_reads_committed_barrier_and_proves_pid_namespace(
    tmp_path: Path,
) -> None:
    target = _run(tmp_path, "target", slot=1)
    target.db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target.db_path)
    connection.execute(
        "CREATE TABLE runs (run_id TEXT, status TEXT, step INTEGER, supervision_mode TEXT, trace_path TEXT)"
    )
    connection.execute(
        "INSERT INTO runs VALUES (?, 'running', 2, 'm1b-process', ?)",
        (target.run_id, str(target.workspace / "trace.jsonl")),
    )
    connection.commit()
    connection.close()
    lifecycle = (
        target.control_root
        / target.run_id
        / "attempts"
        / "attempt-0001"
        / "runtime"
        / "lifecycle.jsonl"
    )
    lifecycle.parent.mkdir(parents=True)
    lifecycle.write_text(
        json.dumps(
            {
                "schema": "fortgym.m1b-runtime-prepare/v1",
                "ok": True,
                "run_id": target.run_id,
            }
        )
        + "\n"
    )
    target.workspace.mkdir(parents=True)
    text_files = {
        f"/proc/{target.runtime_host_pid}/comm": "Dwarf_Fortress\n",
        f"/proc/{target.runtime_host_pid}/status": (
            f"Name:\tDwarf_Fortress\nNSpid:\t{target.runtime_host_pid}\t"
            f"{target.runtime_container_pid}\n"
        ),
        f"/proc/{target.runtime_host_pid}/cgroup": (
            f"0::{target.runtime_cgroup_path}\n"
        ),
    }
    byte_files = {
        f"/proc/{target.harness_pid}/environ": (
            f"FORT_GYM_RUN_ID={target.run_id}\0"
            f"FORT_GYM_RUN_CONTRACT_SHA256={target.contract_sha256}\0"
            f"FORT_GYM_RUN_NONCE={target.nonce}\0"
        ).encode()
    }
    existing = {
        target.db_path,
        lifecycle,
        target.workspace,
        Path(f"/proc/{target.runtime_host_pid}"),
        Path(f"/proc/{target.harness_pid}"),
        Path(f"/proc/{target.supervisor_pid}"),
    }
    runner = InspectRunner({target.container_id: _docker_inspection(target)})
    statvfs = os.statvfs_result(
        (4096, 4096, 1_000_000, 900_000, 900_000, 0, 0, 0, 0, 255)
    )
    probe = LinuxHostFaultProbe(
        target_run_id=target.run_id,
        command_runner=runner,
        read_text=lambda path: text_files[str(path)],
        read_bytes=lambda path: (
            byte_files[str(path)] if str(path) in byte_files else path.read_bytes()
        ),
        path_exists=lambda path: path in existing,
        statvfs=lambda _path: statvfs,
        getpgid=lambda pid: (
            target.harness_process_group_id if pid == target.harness_pid else pid
        ),
        process_ids=lambda: (target.runtime_host_pid, target.harness_pid),
    )
    barrier = probe.barrier_probe(target)
    assert barrier is not None and barrier["step"] == 2
    ownership = probe.ownership_probe(target)
    runtime = ownership["runtime_process"]
    assert runtime["host_pid"] == target.runtime_host_pid
    assert runtime["container_pid"] == target.runtime_container_pid
    assert runtime["host_pid"] != runtime["container_pid"]
    assert runner.calls == [
        ("/usr/bin/docker", "inspect", "--type", "container", target.container_id)
    ]


def test_concrete_linux_probe_rejects_host_container_pid_assumption(
    tmp_path: Path,
) -> None:
    target = _run(tmp_path, "target", slot=1)
    target.workspace.mkdir(parents=True)
    runner = InspectRunner({target.container_id: _docker_inspection(target)})
    text_files = {
        f"/proc/{target.runtime_host_pid}/comm": "Dwarf_Fortress\n",
        f"/proc/{target.runtime_host_pid}/status": (
            f"NSpid:\t{target.runtime_host_pid}\t{target.runtime_host_pid}\n"
        ),
        f"/proc/{target.runtime_host_pid}/cgroup": f"0::{target.runtime_cgroup_path}\n",
    }
    byte_files = {
        f"/proc/{target.harness_pid}/environ": (
            f"FORT_GYM_RUN_ID={target.run_id}\0"
            f"FORT_GYM_RUN_CONTRACT_SHA256={target.contract_sha256}\0"
            f"FORT_GYM_RUN_NONCE={target.nonce}\0"
        ).encode()
    }
    existing = {
        target.workspace,
        Path(f"/proc/{target.runtime_host_pid}"),
        Path(f"/proc/{target.harness_pid}"),
        Path(f"/proc/{target.supervisor_pid}"),
    }
    statvfs = os.statvfs_result((4096, 4096, 100, 90, 90, 0, 0, 0, 0, 255))
    probe = LinuxHostFaultProbe(
        target_run_id=target.run_id,
        command_runner=runner,
        read_text=lambda path: text_files[str(path)],
        read_bytes=lambda path: byte_files[str(path)],
        path_exists=lambda path: path in existing,
        statvfs=lambda _path: statvfs,
        getpgid=lambda _pid: target.harness_process_group_id,
        process_ids=lambda: (),
    )
    with pytest.raises(FaultEvidenceError, match="PID namespace"):
        probe.ownership_probe(target)
