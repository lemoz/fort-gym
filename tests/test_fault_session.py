from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fort_gym.bench.agent.base import RandomAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.experiment.config import (
    BaseRunConfig,
    ExperimentConfig,
    VariantConfig,
)
from fort_gym.bench.run import fault_driver
from fort_gym.bench.run.fault_session import (
    FAULT_SESSION_MANIFEST_ENV,
    PRE_CLEANUP_OBSERVATION_SCHEMA,
    FaultSessionAborted,
    FaultSessionEvidenceError,
    FaultSessionIdentity,
    FaultSessionParticipant,
    FaultSessionStore,
    FaultSessionTimeout,
    StepCommit,
    step_observer_from_environment,
)
from fort_gym.bench.run.process_supervisor import (
    ProcessSupervisor,
    RunSpec,
    SupervisionResult,
    TerminalClass,
)
from fort_gym.bench.run.runner import RunExecutionOutcome, run_once
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import SupervisedRunManager

TARGET_RUN_ID = "fault-target"
PEER_RUN_ID = "fault-peer"
TARGET_CONTRACT = "a" * 64
PEER_CONTRACT = "b" * 64
TARGET_NONCE = "11" * 16
PEER_NONCE = "22" * 16
COHORT_SHA256 = "c" * 64
TARGET_CONTAINER = "d" * 64
PEER_CONTAINER = "e" * 64


def _nonce_sha256(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _session_store(
    tmp_path: Path,
    *,
    gate: str = "DAEMON-RESTART",
) -> FaultSessionStore:
    session = FaultSessionIdentity(
        packet_id="m1b-live-packet",
        authority_sha256="f" * 64,
        gate=gate,
        participants=(
            FaultSessionParticipant(
                run_id=TARGET_RUN_ID,
                role="target",
                contract_sha256=TARGET_CONTRACT,
                nonce_sha256=_nonce_sha256(TARGET_NONCE),
                cohort_sha256=COHORT_SHA256,
            ),
            FaultSessionParticipant(
                run_id=PEER_RUN_ID,
                role="peer",
                contract_sha256=PEER_CONTRACT,
                nonce_sha256=_nonce_sha256(PEER_NONCE),
                cohort_sha256=COHORT_SHA256,
            ),
        ),
        hold_timeout_seconds=1.0,
        cleanup_ack_timeout_seconds=1.0,
    )
    store = FaultSessionStore(
        control_root=(tmp_path / "control").resolve(),
        session=session,
        poll_interval_seconds=0.005,
    )
    store.initialize()
    return store


def _classifier_evidence(gate: str) -> dict[str, Any]:
    identity = {"expected": TARGET_CONTAINER, "observed": TARGET_CONTAINER}
    return {
        "DF-KILL": {
            "runtime_identity": identity,
            "signal": 9,
            "oom_killed": False,
        },
        "HARNESS-KILL": {"child_pid": 4242, "signal": 9},
        "ENOSPC": {
            "errno": 28,
            "operation": "bounded workspace write",
            "workspace": {
                "run_id": TARGET_RUN_ID,
                "scope_root": "/tmp/fortgym-fault-target",
                "fault_path": "/tmp/fortgym-fault-target/fill.bin",
                "fault_bytes": 1024,
                "maximum_fault_bytes": 16_777_216,
            },
        },
        "CONTAINER-RESTART": {
            "container_identity": {
                "expected": TARGET_CONTAINER,
                "before": TARGET_CONTAINER,
                "after": TARGET_CONTAINER,
            },
            "restart_count": {"before": 0, "after": 1},
        },
        "DAEMON-RESTART": {
            "daemon_generation": {"before": "boot-a", "after": "boot-b"},
            "runtime_identity": identity,
        },
    }[gate]


def _completed_observation(store: FaultSessionStore) -> dict[str, Any]:
    target = store.session.target
    peer = store.session.peer
    return {
        "schema": "fortgym.m1b-fault-driver-observation/v1",
        "event_index": 7,
        "recorded_at": "2026-08-17T12:00:00Z",
        "phase": "completed",
        "gate": store.session.gate,
        "run_id": target.run_id,
        "contract_sha256": target.contract_sha256,
        "nonce_sha256": target.nonce_sha256,
        "payload": {
            "target": {
                **target.payload(),
                "container_id": TARGET_CONTAINER,
            },
            "peer": {
                **peer.payload(),
                "container_id": PEER_CONTAINER,
            },
            "barrier": {},
            "ownership": {},
            "before": {},
            "action": {},
            "after": {},
            "peer_after": {},
            "canaries": {},
            "timing": {},
            "classifier_evidence_schema": (
                "fortgym.m1b-fault-driver-classifier-evidence/v1"
            ),
            "classifier_evidence": _classifier_evidence(store.session.gate),
            "pending_external_checks": [],
        },
    }


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_driver_journal(
    store: FaultSessionStore,
    completed: Mapping[str, Any],
) -> str:
    phases = (
        "authorized",
        "barrier_confirmed",
        "ownership_confirmed",
        "before_observed",
        "action_armed",
        "action_attempted",
    )
    rows: list[dict[str, Any]] = []
    for index, phase in enumerate(phases, start=1):
        rows.append(
            {
                "schema": "fortgym.m1b-fault-driver-observation/v1",
                "event_index": index,
                "recorded_at": "2026-08-17T12:00:00Z",
                "phase": phase,
                "gate": store.session.gate,
                "run_id": TARGET_RUN_ID,
                "contract_sha256": TARGET_CONTRACT,
                "nonce_sha256": _nonce_sha256(TARGET_NONCE),
                "payload": (
                    completed["payload"]["action"]
                    if phase == "action_attempted"
                    else {}
                ),
            }
        )
    rows.append(dict(completed))
    journal_path = (
        store.control_root / TARGET_RUN_ID / "fault-driver-observations.jsonl"
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return _payload_sha256(rows[-2])


def _ready_and_release_session(
    tmp_path: Path,
    store: FaultSessionStore,
    *,
    trigger_record_sha256: str,
) -> None:
    errors: list[BaseException] = []
    threads: list[threading.Thread] = []

    for participant in store.session.participants:
        trace_path = (tmp_path / f"{participant.run_id}-trace.jsonl").resolve()
        trace_path.write_text('{"step":2}\n', encoding="utf-8")
        observer = store.step_observer(participant.run_id)

        def observe(
            bound_observer: Callable[[StepCommit], None] = observer,
            bound_participant: FaultSessionParticipant = participant,
            bound_trace: Path = trace_path,
        ) -> None:
            try:
                bound_observer(StepCommit(bound_participant.run_id, 2, bound_trace))
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        threads.append(thread)

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if all(
            store.ready(item.run_id) is not None for item in store.session.participants
        ):
            break
        time.sleep(0.005)
    assert all(
        store.ready(item.run_id) is not None for item in store.session.participants
    )
    for participant in store.session.participants:
        store.release(
            participant.run_id,
            trigger_record_sha256=trigger_record_sha256,
        )
    for thread in threads:
        thread.join(timeout=1.0)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert all(
        store.released(participant.run_id) is not None
        for participant in store.session.participants
    )


def _persist_completed(
    monkeypatch: pytest.MonkeyPatch,
    store: FaultSessionStore,
) -> dict[str, Any]:
    completed = _completed_observation(store)
    action_record_sha256 = _write_driver_journal(store, completed)
    assert store.action_attempted_sha256() == action_record_sha256
    _ready_and_release_session(
        store.control_root.parent,
        store,
        trigger_record_sha256=action_record_sha256,
    )
    calls: list[dict[str, Any]] = []

    def load_completed(**kwargs: Any) -> Mapping[str, Any]:
        calls.append(kwargs)
        return completed

    monkeypatch.setattr(
        fault_driver,
        "load_completed_fault_observation",
        load_completed,
    )
    store.persist_completed_claims(completed, target_nonce=TARGET_NONCE)
    assert len(calls) == 1
    assert calls[0]["run_id"] == TARGET_RUN_ID
    assert calls[0]["contract_sha256"] == TARGET_CONTRACT
    assert calls[0]["nonce"] == TARGET_NONCE
    assert calls[0]["expected_gate"].value == store.session.gate
    return completed


def _pre_cleanup_observation(
    participant: FaultSessionParticipant,
    *,
    returncode: int | None = 7,
) -> dict[str, Any]:
    return {
        "schema": PRE_CLEANUP_OBSERVATION_SCHEMA,
        "run_id": participant.run_id,
        "primary_terminal_class": ("timeout" if returncode is None else "child_exit"),
        "primary_reason": (
            {"code": "wall_timeout", "seconds": 0.05}
            if returncode is None
            else {"code": "child_nonzero_exit", "returncode": returncode}
        ),
        "child_pid": 4242,
        "returncode": returncode,
        "child_signal": None,
        "environment_identity": {
            "run_id": participant.run_id,
            "contract_sha256": participant.contract_sha256,
            "rpc": {
                "nonce": (TARGET_NONCE if participant.role == "target" else PEER_NONCE)
            },
            "cotenancy": {"cohort_sha256": participant.cohort_sha256},
        },
        "prepare": {"ok": True},
        "termination": {},
    }


def _supervisor_spec(
    tmp_path: Path,
    participant: FaultSessionParticipant,
    *,
    code: str = "raise SystemExit(7)",
    timeout_seconds: float = 1.0,
) -> RunSpec:
    nonce = TARGET_NONCE if participant.role == "target" else PEER_NONCE
    return RunSpec(
        run_id=participant.run_id,
        argv=(sys.executable, "-c", code),
        artifact_dir=tmp_path / participant.run_id,
        timeout_seconds=timeout_seconds,
        term_grace_seconds=0.08,
        poll_interval_seconds=0.005,
        environment_identity={
            "run_id": participant.run_id,
            "contract_sha256": participant.contract_sha256,
            "scripted": True,
            "provider": {"enabled": False},
            "rpc": {"nonce": nonce},
            "cotenancy": {"cohort_sha256": participant.cohort_sha256},
        },
    )


def _journal(result: SupervisionResult) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in result.journal_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_step2_barrier_is_durable_bounded_and_single_decision(
    tmp_path: Path,
) -> None:
    store = _session_store(tmp_path)
    trace_path = (tmp_path / "trace.jsonl").resolve()
    trace_path.write_text('{"step":2}\n', encoding="utf-8")
    observer = store.step_observer(TARGET_RUN_ID)
    errors: list[BaseException] = []

    def observe() -> None:
        try:
            observer(StepCommit(TARGET_RUN_ID, 2, trace_path))
        except BaseException as exc:  # noqa: BLE001 - surfaced in the test thread
            errors.append(exc)

    thread = threading.Thread(target=observe, daemon=True)
    thread.start()
    deadline = time.monotonic() + 1.0
    ready = None
    while ready is None and time.monotonic() < deadline:
        ready = store.ready(TARGET_RUN_ID)
        time.sleep(0.005)

    assert ready is not None
    assert ready["step"] == 2
    assert ready["trace_size_bytes"] == trace_path.stat().st_size
    trigger_sha256 = "9" * 64
    store.release(TARGET_RUN_ID, trigger_record_sha256=trigger_sha256)
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert errors == []
    released = json.loads(
        (
            store.session_dir / "participants" / TARGET_RUN_ID / "step2-released.json"
        ).read_text(encoding="utf-8")
    )
    assert released["trigger_record_sha256"] == trigger_sha256
    assert store.released(TARGET_RUN_ID) == released
    with pytest.raises(FaultSessionEvidenceError, match="contradicts"):
        store.abort(TARGET_RUN_ID, reason_code="driver-failed")


def test_step_observer_environment_is_explicit_and_contract_bound(
    tmp_path: Path,
) -> None:
    store = _session_store(tmp_path)
    worker_environment = store.worker_environment(TARGET_RUN_ID)
    assert worker_environment == {
        "FORT_GYM_FAULT_SESSION_MANIFEST": str(store.manifest_path),
        "FORT_GYM_FAULT_SESSION_SHA256": store.session.session_sha256,
    }
    environment = {
        **worker_environment,
        "FORT_GYM_RUN_ID": TARGET_RUN_ID,
        "FORT_GYM_RUN_CONTRACT_SHA256": TARGET_CONTRACT,
        "FORT_GYM_RUN_NONCE": TARGET_NONCE,
    }

    assert callable(step_observer_from_environment(environment))
    assert step_observer_from_environment({}) is None
    with pytest.raises(FaultSessionEvidenceError, match="contract identity"):
        step_observer_from_environment(
            {**environment, "FORT_GYM_RUN_NONCE": PEER_NONCE}
        )
    with pytest.raises(FaultSessionEvidenceError, match="incomplete"):
        step_observer_from_environment(
            {FAULT_SESSION_MANIFEST_ENV: str(store.manifest_path)}
        )


def test_action_receipt_poll_is_prefix_aware_and_failed_closed(tmp_path: Path) -> None:
    store = _session_store(tmp_path / "prefix")
    journal_path = (
        store.control_root / TARGET_RUN_ID / "fault-driver-observations.jsonl"
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.touch()
    assert store.action_attempted_sha256() is None
    with pytest.raises(FaultSessionEvidenceError, match="file is invalid"):
        store._validated_driver_records(journal_path)
    journal_path.write_bytes(b"{")
    with pytest.raises(FaultSessionEvidenceError, match="partial"):
        store.action_attempted_sha256()
    authorized = {
        "schema": "fortgym.m1b-fault-driver-observation/v1",
        "event_index": 1,
        "recorded_at": "2026-08-17T12:00:00Z",
        "phase": "authorized",
        "gate": store.session.gate,
        "run_id": TARGET_RUN_ID,
        "contract_sha256": TARGET_CONTRACT,
        "nonce_sha256": _nonce_sha256(TARGET_NONCE),
        "payload": {},
    }
    journal_path.write_text(
        json.dumps(authorized, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    assert store.action_attempted_sha256() is None

    failed_store = _session_store(tmp_path / "failed")
    failed_path = (
        failed_store.control_root / TARGET_RUN_ID / "fault-driver-observations.jsonl"
    )
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    failed = {
        **authorized,
        "phase": "failed",
        "payload": {"error": {"type": "FaultEvidenceError", "message": "failed"}},
    }
    failed_path.write_text(
        json.dumps(failed, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(FaultSessionAborted, match="failed before release"):
        failed_store.action_attempted_sha256()


def test_action_poll_survives_real_writer_create_before_first_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _session_store(tmp_path, gate="DF-KILL")
    path = store.control_root / TARGET_RUN_ID / "fault-driver-observations.jsonl"
    journal = fault_driver._ObservationJournal(
        path,
        gate=fault_driver.FaultGate.DF_KILL,
        target=SimpleNamespace(
            run_id=TARGET_RUN_ID, contract_sha256=TARGET_CONTRACT, nonce=TARGET_NONCE
        ),
        now=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )
    created = threading.Event()
    resume = threading.Event()
    original_flock = fault_driver.fcntl.flock
    records: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def pause_first_append(descriptor: int, operation: int) -> None:
        if operation == fault_driver.fcntl.LOCK_EX and not created.is_set():
            created.set()
            assert resume.wait(5), "test did not release paused writer"
        original_flock(descriptor, operation)

    def write() -> None:
        try:
            for phase in (
                "authorized", "barrier_confirmed", "ownership_confirmed",
                "before_observed", "action_armed", "action_attempted",
            ):
                records.append(journal.append(phase, {}))
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(fault_driver.fcntl, "flock", pause_first_append)
    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    try:
        assert created.wait(5), "writer did not reach its first append lock"
        assert path.stat().st_size == 0
        assert writer.is_alive()
        assert store.action_attempted_sha256() is None
    finally:
        resume.set()
        writer.join(5)
    assert not writer.is_alive()
    assert not errors
    assert len(records) == 6
    assert store.action_attempted_sha256() == _payload_sha256(records[-1])


@pytest.mark.parametrize("outcome", ["completed", "aborted", "foreign", "timeout"])
def test_dfkill_peer_remains_observable_until_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    store = _session_store(tmp_path, gate="DF-KILL")
    completed = _completed_observation(store)
    action_digest = _write_driver_journal(store, completed)
    _ready_and_release_session(tmp_path, store, trigger_record_sha256=action_digest)
    trace = (tmp_path / "peer-progress.jsonl").resolve()
    trace.write_text('{"step":5}\n')
    errors = []
    observer = store.step_observer(PEER_RUN_ID)

    def progress():
        try:
            observer(StepCommit(PEER_RUN_ID, 5, trace))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=progress, daemon=True)
    thread.start()
    root = store.session_dir / "participants" / PEER_RUN_ID
    try:
        deadline = time.monotonic() + 0.5
        while not (root / "peer-progress-ready.json").exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert (root / "peer-progress-ready.json").exists()
        assert thread.is_alive()
        assert not (root / "peer-progress-released.json").exists()
        if outcome == "completed":
            monkeypatch.setattr(fault_driver, "load_completed_fault_observation", lambda **kw: completed)
            store.persist_completed_claims(completed, target_nonce=TARGET_NONCE)
        elif outcome == "aborted":
            store.abort_completion(reason_code="driver_failed")
        elif outcome == "foreign":
            store._completion_path().write_text(json.dumps({
                "schema": "fortgym.m1b-fault-session-completed/v1",
                "session_sha256": "0" * 64, "gate": "DF-KILL",
            }))
    finally:
        thread.join(2)
    assert not thread.is_alive()
    if outcome == "completed":
        assert errors == []
        receipt = json.loads((root / "peer-progress-released.json").read_text())
        assert receipt["step"] == 5
        assert receipt["trigger_record_sha256"] == action_digest
    else:
        assert len(errors) == 1
        expected = {
            "aborted": FaultSessionAborted,
            "foreign": FaultSessionEvidenceError,
            "timeout": FaultSessionTimeout,
        }[outcome]
        assert isinstance(errors[0], expected)
        assert not (root / "peer-progress-released.json").exists()


def test_completed_claims_require_canonical_driver_reload_and_raw_nonce_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _session_store(tmp_path)
    completed = _completed_observation(store)
    mismatched = {**completed, "event_index": 8}
    monkeypatch.setattr(
        fault_driver,
        "load_completed_fault_observation",
        lambda **_kwargs: mismatched,
    )

    with pytest.raises(FaultSessionEvidenceError, match="canonical durable"):
        store.persist_completed_claims(completed, target_nonce=TARGET_NONCE)
    with pytest.raises(FaultSessionEvidenceError, match="nonce identity"):
        store.persist_completed_claims(completed, target_nonce=PEER_NONCE)


def test_completed_claim_rejects_release_not_bound_to_action_attempted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _session_store(tmp_path)
    completed = _completed_observation(store)
    _write_driver_journal(store, completed)
    _ready_and_release_session(
        tmp_path,
        store,
        trigger_record_sha256="8" * 64,
    )
    monkeypatch.setattr(
        fault_driver,
        "load_completed_fault_observation",
        lambda **_kwargs: completed,
    )

    with pytest.raises(FaultSessionEvidenceError, match="action_attempted"):
        store.persist_completed_claims(completed, target_nonce=TARGET_NONCE)


def test_daemon_completed_receipt_binds_target_and_peer_terminal_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _session_store(tmp_path)
    _persist_completed(monkeypatch, store)

    target_snapshot = store.pre_cleanup_observer(TARGET_RUN_ID)(
        _pre_cleanup_observation(store.session.target)
    )
    peer_snapshot = store.pre_cleanup_observer(PEER_RUN_ID)(
        _pre_cleanup_observation(store.session.peer)
    )

    assert target_snapshot["classifier_result"]["terminal_class"] == (
        "docker_daemon_restarted"
    )
    assert peer_snapshot["classifier_result"]["terminal_class"] == (
        "docker_daemon_restarted"
    )
    assert (
        target_snapshot["participant_claim"]["source_completed_record_sha256"]
        == peer_snapshot["participant_claim"]["source_completed_record_sha256"]
    )
    assert peer_snapshot["classifier_result"]["evidence"]["runtime_identity"] == {
        "expected": PEER_CONTAINER,
        "observed": PEER_CONTAINER,
    }
    completed = target_snapshot["completed_receipt"]
    assert completed["classified_run_ids"] == sorted([TARGET_RUN_ID, PEER_RUN_ID])
    assert completed["source_contract_sha256"] == TARGET_CONTRACT


def test_non_daemon_peer_cannot_receive_target_fault_classification(
    tmp_path: Path,
) -> None:
    store = _session_store(tmp_path, gate="DF-KILL")

    with pytest.raises(FaultSessionEvidenceError, match="only DAEMON-RESTART"):
        store.pre_cleanup_observer(PEER_RUN_ID)


def test_completion_abort_unblocks_cleanup_without_terminal_claim(
    tmp_path: Path,
) -> None:
    store = _session_store(tmp_path)
    store.abort_completion(reason_code="driver-evidence-failed")

    with pytest.raises(FaultSessionAborted, match="driver-evidence-failed"):
        store.pre_cleanup_observer(TARGET_RUN_ID)(
            _pre_cleanup_observation(store.session.target)
        )


@pytest.mark.parametrize("run_id", [TARGET_RUN_ID, PEER_RUN_ID])
def test_daemon_snapshot_classifies_each_supervisor_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_id: str,
) -> None:
    store = _session_store(tmp_path)
    _persist_completed(monkeypatch, store)
    participant = store.session.participant(run_id)
    classifier_calls: list[Mapping[str, Any]] = []

    def forbidden_classifier(observation: Mapping[str, Any]) -> Mapping[str, Any]:
        classifier_calls.append(observation)
        raise AssertionError("session evidence must be the immutable classifier input")

    result = ProcessSupervisor().run(
        _supervisor_spec(tmp_path, participant),
        cleanup=lambda: {"ok": True, "container_absent": True},
        fault_classifier=forbidden_classifier,
        pre_cleanup_observer=store.pre_cleanup_observer(run_id),
    )

    assert result.terminal_class is TerminalClass.DOCKER_DAEMON_RESTARTED
    assert result.payload["cleanup"]["ok"] is True
    assert result.payload["reason"]["code"] == "docker_daemon_restarted"
    assert result.payload["pre_cleanup_evidence"]["snapshot"]["run_id"] == run_id
    assert classifier_calls == []
    event_names = [row["event"] for row in _journal(result)]
    ordered = [
        "cleanup_started",
        "evidence_snapshot_completed",
        "harness_process_group_reaped",
        "cleanup_recorded",
        "runtime_fault_classification_recorded",
        "terminal_pending",
    ]
    positions = [event_names.index(name) for name in ordered]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    ("gate", "expected_terminal"),
    [
        ("DF-KILL", TerminalClass.RUNTIME_DF_KILLED),
        ("ENOSPC", TerminalClass.WORKSPACE_ENOSPC),
        ("CONTAINER-RESTART", TerminalClass.RUNTIME_CONTAINER_RESTARTED),
    ],
)
def test_target_snapshot_classifies_each_non_harness_post_readiness_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate: str,
    expected_terminal: TerminalClass,
) -> None:
    store = _session_store(tmp_path, gate=gate)
    _persist_completed(monkeypatch, store)

    result = ProcessSupervisor().run(
        _supervisor_spec(tmp_path, store.session.target),
        cleanup=lambda: {"ok": True, "container_absent": True},
        pre_cleanup_observer=store.pre_cleanup_observer(TARGET_RUN_ID),
    )

    assert result.terminal_class is expected_terminal
    assert result.payload["reason"]["code"] == expected_terminal.value


@pytest.mark.parametrize("gate", ["ENOSPC", "DF-KILL"])
@pytest.mark.parametrize("with_claim", [False, True])
def test_truncated_trace_requires_completed_enospc_claim_to_override_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: str, with_claim: bool
) -> None:
    store = _session_store(tmp_path, gate=gate)
    _persist_completed(monkeypatch, store)
    trace_path = tmp_path / TARGET_RUN_ID / "trace.jsonl"
    code = f"from pathlib import Path; Path({str(trace_path)!r}).write_text('{{\\\"events\\\":['); raise SystemExit(22)"
    result = ProcessSupervisor().run(
        _supervisor_spec(tmp_path, store.session.target, code=code),
        cleanup=lambda: {"ok": True, "container_absent": True},
        pre_cleanup_observer=(store.pre_cleanup_observer(TARGET_RUN_ID) if with_claim else None),
    )
    expected = TerminalClass.WORKSPACE_ENOSPC if gate == "ENOSPC" and with_claim else TerminalClass.CAP_TRIP
    assert result.terminal_class is expected
    assert result.payload["primary_terminal_class"] == "cap_trip"
    assert result.payload["primary_reason"]["code"] == "trace_accounting_invalid"
    if expected is TerminalClass.WORKSPACE_ENOSPC:
        from fort_gym.bench.run.supervised_manager import ControlEvidenceError, SupervisedRunManager

        SupervisedRunManager._validate_supervision_payload(result.payload, TARGET_RUN_ID)
        for damage in ("snapshot", "scripted", "provider", "budget_reason", "foreign_snapshot"):
            altered = json.loads(json.dumps(result.payload, default=dict))
            if damage == "snapshot":
                altered.pop("pre_cleanup_evidence")
            elif damage == "scripted":
                altered["environment_identity"]["scripted"] = False
            elif damage == "provider":
                altered["environment_identity"]["provider"]["enabled"] = True
            elif damage == "budget_reason":
                altered["primary_reason"]["code"] = "token_cap_reached"
            else:
                altered["pre_cleanup_evidence"]["snapshot"]["run_id"] = "foreign"
            with pytest.raises(ControlEvidenceError):
                SupervisedRunManager._validate_supervision_payload(altered, TARGET_RUN_ID)


@pytest.mark.parametrize("reason_code", ["token_cap_reached", "cost_cap_reached"])
def test_real_budget_reason_retains_precedence_over_completed_enospc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason_code: str
) -> None:
    from fort_gym.bench.run.process_supervisor import MonitorViolation, TraceBudgetMonitor

    store = _session_store(tmp_path, gate="ENOSPC")
    _persist_completed(monkeypatch, store)
    monkeypatch.setattr(
        TraceBudgetMonitor, "_observe_raw_line",
        lambda *_args: MonitorViolation(TerminalClass.CAP_TRIP, reason_code, {}),
    )
    trace_path = tmp_path / TARGET_RUN_ID / "trace.jsonl"
    code = f"from pathlib import Path; Path({str(trace_path)!r}).write_text('{{}}\\n'); raise SystemExit(22)"
    result = ProcessSupervisor().run(
        _supervisor_spec(tmp_path, store.session.target, code=code),
        cleanup=lambda: {"ok": True, "container_absent": True},
        pre_cleanup_observer=store.pre_cleanup_observer(TARGET_RUN_ID),
    )
    assert result.terminal_class is TerminalClass.CAP_TRIP
    assert result.payload["reason"]["code"] == reason_code


def test_harness_kill_snapshot_binds_the_actual_signaled_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _session_store(tmp_path, gate="HARNESS-KILL")
    results: list[SupervisionResult] = []
    errors: list[BaseException] = []
    spec = _supervisor_spec(
        tmp_path,
        store.session.target,
        code="import time; time.sleep(10)",
        timeout_seconds=2.0,
    )

    def supervise() -> None:
        try:
            results.append(
                ProcessSupervisor().run(
                    spec,
                    cleanup=lambda: {"ok": True, "container_absent": True},
                    pre_cleanup_observer=store.pre_cleanup_observer(TARGET_RUN_ID),
                )
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    thread = threading.Thread(target=supervise, daemon=True)
    thread.start()
    child_pid = None
    deadline = time.monotonic() + 1.0
    journal_path = spec.artifact_dir / "attempt-journal.jsonl"
    while child_pid is None and time.monotonic() < deadline:
        if journal_path.exists():
            rows = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            children = [row for row in rows if row.get("event") == "child_started"]
            if children:
                child_pid = children[0]["child_pid"]
                break
        time.sleep(0.005)
    assert isinstance(child_pid, int) and child_pid > 1

    completed = _completed_observation(store)
    completed["payload"]["classifier_evidence"] = {
        "child_pid": child_pid,
        "signal": 9,
    }
    os.kill(child_pid, signal.SIGKILL)
    action_record_sha256 = _write_driver_journal(store, completed)
    _ready_and_release_session(
        tmp_path,
        store,
        trigger_record_sha256=action_record_sha256,
    )
    monkeypatch.setattr(
        fault_driver,
        "load_completed_fault_observation",
        lambda **_kwargs: completed,
    )
    store.persist_completed_claims(completed, target_nonce=TARGET_NONCE)
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert errors == []
    assert len(results) == 1
    assert results[0].terminal_class is TerminalClass.HARNESS_KILLED
    assert results[0].payload["child_pid"] == child_pid
    assert results[0].payload["child_signal"] == 9


def test_timeout_observes_completed_fault_before_terminating_live_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _session_store(tmp_path)
    _persist_completed(monkeypatch, store)
    observations: list[Mapping[str, Any]] = []
    bound_observer = store.pre_cleanup_observer(TARGET_RUN_ID)

    def observe(observation: Mapping[str, Any]) -> Mapping[str, Any]:
        observations.append(observation)
        assert observation["returncode"] is None
        return bound_observer(observation)

    result = ProcessSupervisor().run(
        _supervisor_spec(
            tmp_path,
            store.session.target,
            code="import time; time.sleep(10)",
            timeout_seconds=0.05,
        ),
        cleanup=lambda: {"ok": True, "container_absent": True},
        pre_cleanup_observer=observe,
    )

    assert len(observations) == 1
    assert result.terminal_class is TerminalClass.DOCKER_DAEMON_RESTARTED
    assert result.payload["primary_terminal_class"] == "timeout"
    process_stage = next(
        stage
        for stage in result.payload["cleanup"]["stages"]
        if stage["stage"] == "process_group"
    )
    assert process_stage["ok"] is True


def test_cleanup_failure_has_absolute_precedence_over_session_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _session_store(tmp_path)
    _persist_completed(monkeypatch, store)

    result = ProcessSupervisor().run(
        _supervisor_spec(tmp_path, store.session.target),
        cleanup=lambda: {"ok": False, "residue": "managed-container"},
        pre_cleanup_observer=store.pre_cleanup_observer(TARGET_RUN_ID),
    )

    assert result.terminal_class is TerminalClass.CLEANUP_FAILURE
    assert result.payload["reason"]["code"] == "child_nonzero_exit"
    assert result.payload["fault_classification"]["skipped"] == (
        "cleanup_failure_precedence"
    )


@pytest.mark.parametrize(
    "observer",
    [
        lambda _observation: "not-a-mapping",
        lambda _observation: (_ for _ in ()).throw(RuntimeError("snapshot failed")),
    ],
)
def test_pre_cleanup_observer_failure_cleans_then_fails_classification(
    tmp_path: Path,
    observer: Callable[[Mapping[str, Any]], Any],
) -> None:
    cleanup_calls: list[str] = []
    result = ProcessSupervisor().run(
        _supervisor_spec(tmp_path, _session_store(tmp_path).session.target),
        cleanup=lambda: cleanup_calls.append("cleanup") or {"ok": True},
        pre_cleanup_observer=observer,
    )

    assert cleanup_calls == ["cleanup"]
    assert result.terminal_class is TerminalClass.RUNTIME_FAULT_CLASSIFICATION_FAILURE
    assert result.payload["cleanup"]["ok"] is True
    assert result.payload["fault_classification"]["ok"] is False
    assert (result.terminal_path).is_file()


def test_prepare_failure_never_waits_for_fault_session_completion(
    tmp_path: Path,
) -> None:
    observer_calls: list[Mapping[str, Any]] = []

    def prepare() -> Mapping[str, Any]:
        raise RuntimeError("prepare failed before child launch")

    result = ProcessSupervisor().run(
        _supervisor_spec(tmp_path, _session_store(tmp_path).session.target),
        prepare=prepare,
        cleanup=lambda: {"ok": True},
        pre_cleanup_observer=lambda observation: (
            observer_calls.append(observation) or {}
        ),
    )

    assert result.terminal_class is TerminalClass.PREPARE_FAILURE
    assert observer_calls == []
    assert result.payload["cleanup"]["ok"] is True
    assert any(
        row["event"] == "pre_cleanup_evidence_skipped" for row in _journal(result)
    )


def test_ordinary_supervisor_path_has_no_fault_session_events(
    tmp_path: Path,
) -> None:
    result = ProcessSupervisor().run(
        RunSpec(
            run_id="ordinary-run",
            argv=(sys.executable, "-c", "pass"),
            artifact_dir=tmp_path / "ordinary-run",
            timeout_seconds=1.0,
            poll_interval_seconds=0.005,
        )
    )

    assert result.terminal_class is TerminalClass.COMPLETED
    assert "pre_cleanup_evidence" not in result.payload
    event_names = {row["event"] for row in _journal(result)}
    assert "evidence_snapshot_completed" in event_names
    assert not event_names.intersection(
        {"cleanup_started", "evidence_snapshot_failed"}
    )


def test_run_once_observer_sees_trace_and_registry_step_already_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id="step-observer-run",
        backend="mock",
        model="random",
        max_steps=3,
        ticks_per_step=1,
    )
    observed_steps: list[int] = []

    def observe(commit: StepCommit) -> None:
        loaded = registry.get(record.run_id)
        assert loaded is not None and loaded.step == commit.step
        raw = commit.trace_path.read_bytes()
        assert raw.endswith(b"\n")
        assert json.loads(raw.splitlines()[-1])["step"] == commit.step
        observed_steps.append(commit.step)

    outcome = run_once(
        RandomAgent(seed=0, safe=True),
        backend="mock",
        model="random",
        max_steps=3,
        ticks_per_step=1,
        run_id=record.run_id,
        registry=registry,
        supervisor_owns_terminal=True,
        step_commit_observer=observe,
    )

    assert isinstance(outcome, RunExecutionOutcome)
    assert outcome.outcome == "completed"
    assert observed_steps == [0, 1, 2]
    loaded = registry.get(record.run_id)
    assert loaded is not None and loaded.status == "running"
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_run_once_rejects_step_observer_without_parent_terminal_ownership() -> None:
    with pytest.raises(ValueError, match="supervisor-owned terminal"):
        run_once(
            RandomAgent(seed=0, safe=True),
            step_commit_observer=lambda _commit: None,
        )


def test_external_experiment_worker_loads_explicit_session_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fort_gym.bench.experiment import runner as experiment_runner

    db_path = tmp_path / "runs.sqlite3"
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("FORT_GYM_DB_PATH", str(db_path))
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=db_path)
    record = registry.create(
        run_id="external-session-worker",
        backend="mock",
        model="fake",
        max_steps=2,
        ticks_per_step=10,
    )
    sentinel = lambda _commit: None
    captured: dict[str, Any] = {}
    monkeypatch.setattr(experiment_runner, "_ensure_agent_factories", lambda: None)
    monkeypatch.setattr(experiment_runner, "_make_agent", lambda _name: object())
    monkeypatch.setattr(
        experiment_runner,
        "step_observer_from_environment",
        lambda environment: sentinel if environment is os.environ else None,
    )

    def fake_run_once(_agent: object, **kwargs: Any) -> RunExecutionOutcome:
        captured.update(kwargs)
        return RunExecutionOutcome(run_id=kwargs["run_id"], outcome="completed")

    monkeypatch.setattr(experiment_runner, "run_once", fake_run_once)
    config = ExperimentConfig(
        name="external-session",
        description=None,
        base_config=BaseRunConfig(
            backend="mock",
            model="fake",
            max_steps=2,
            ticks_per_step=10,
        ),
        variants=[VariantConfig(name="only", memory_window=0)],
        runs_per_variant=1,
    )

    experiment_runner.ExperimentRunner(artifacts_root=artifacts_root).run(
        config,
        external_run_id=record.run_id,
    )

    assert captured["step_commit_observer"] is sentinel
    assert captured["supervisor_owns_terminal"] is True
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_manager_injects_pre_cleanup_observer_only_when_factory_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id="manager-session-run",
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    registry.set_summary(record.run_id, {"total_score": 0, "steps": 1})
    sentinel = lambda _observation: {}
    captured: dict[str, Any] = {}

    class Controller:
        def prepare(self) -> Mapping[str, Any]:
            return {"ok": True}

        def cleanup(self) -> Mapping[str, Any]:
            return {
                "ok": True,
                "container_absent": True,
                "listener_absent": True,
            }

    class Supervisor:
        def run(self, spec: RunSpec, **kwargs: Any) -> SupervisionResult:
            captured.update(kwargs)
            delegated = dict(kwargs)
            delegated["pre_cleanup_observer"] = None
            return ProcessSupervisor().run(
                replace(spec, argv=(sys.executable, "-c", "pass")),
                **delegated,
            )

    def contract_factory(
        loaded: Any,
        attempt_dir: Path,
        _controller: Any,
    ) -> RunSpec:
        return RunSpec(
            run_id=loaded.run_id,
            argv=(
                sys.executable,
                "-m",
                "fort_gym.bench.cli",
                "experiment",
                "/tmp/config.json",
                "--external-run-id",
                loaded.run_id,
            ),
            artifact_dir=attempt_dir,
            environment_identity={
                "schema": "fortgym.m1b-runtime-contract/v1",
                "run_id": loaded.run_id,
                "contract_sha256": "c" * 64,
                "rpc": {
                    "host": "127.0.0.1",
                    "port": 24_455,
                    "nonce": "d" * 32,
                },
            },
            runtime_cleanup_required=True,
        )

    manager = SupervisedRunManager(
        registry=registry,
        control_root=tmp_path / "control",
        runtime_controller_factory=lambda _record, _run_dir: Controller(),
        contract_factory=contract_factory,
        supervisor_factory=Supervisor,
        pre_cleanup_observer_factory=(
            lambda _record, _run_dir, _controller, _spec: sentinel
        ),
    )

    result = manager.run(record.run_id)

    assert result.status == "completed"
    assert captured["pre_cleanup_observer"] is sentinel
    get_settings.cache_clear()  # type: ignore[attr-defined]
