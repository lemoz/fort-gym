from __future__ import annotations

import json
import os
import platform
import queue
import signal
import socket
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.run import process_supervisor as process_supervisor_module
from fort_gym.bench.run.fault_classification import FAULT_CLASSIFIER_RESULT_SCHEMA
from fort_gym.bench.run.process_supervisor import (
    TERMINAL_CHAIN_EVENTS,
    PortLease,
    PortLeaseBusy,
    PortUnavailable,
    ProcessSupervisor,
    RunSpec,
    SupervisorError,
    TerminalClass,
    TraceBudgetMonitor,
    build_sanitized_environment,
    validate_terminal_chain,
)


def _run_spec(tmp_path: Path, run_id: str, code: str, **changes: Any) -> RunSpec:
    values: dict[str, Any] = {
        "run_id": run_id,
        "argv": (sys.executable, "-c", code),
        "artifact_dir": tmp_path / run_id,
        "timeout_seconds": 1.0,
        "term_grace_seconds": 0.08,
        "poll_interval_seconds": 0.01,
    }
    values.update(changes)
    return RunSpec(**values)


def _journal(result: Any) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in result.journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _guard_reap_after_terminal_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    journal_path: Path,
) -> list[tuple[str, ...]]:
    original = ProcessSupervisor._terminate_process_group
    observed: list[tuple[str, ...]] = []

    def guarded(cls, process, grace_seconds):
        del cls
        events = tuple(
            json.loads(line)["event"]
            for line in journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        assert events.count("terminal_pending_cleanup") == 1
        assert events.count("evidence_snapshot_completed") == 1
        assert "harness_process_group_reaped" not in events
        observed.append(events)
        return original(process, grace_seconds)

    monkeypatch.setattr(
        ProcessSupervisor,
        "_terminate_process_group",
        classmethod(guarded),
    )
    return observed


def _openrouter_event(
    *,
    model: str = "openai/test-model",
    resolved_model: str | None = None,
    provider: str = "OpenAI",
    tokens: int = 11,
    cost: float = 0.01,
) -> dict[str, Any]:
    return {
        "step": 0,
        "events": [
            {
                "type": "tool_call",
                "data": {
                    "tool": "openrouter.chat.completions.create",
                    "input": {"model": model},
                    "output": {
                        "generation_id": "gen-test",
                        "resolved_model": resolved_model or model,
                        "total_tokens": tokens,
                        "cost": cost,
                        "generation": {
                            "id": "gen-test",
                            "provider_name": provider,
                            "total_cost": cost,
                        },
                    },
                },
            }
        ],
    }


def _trace_writer_code(record: dict[str, Any]) -> str:
    encoded = json.dumps(record, sort_keys=True)
    return (
        "import os,time\n"
        "path=os.environ['TRACE_PATH']\n"
        f"payload={encoded!r}+'\\n'\n"
        "with open(path,'w',encoding='utf-8') as handle:\n"
        " handle.write(payload); handle.flush(); os.fsync(handle.fileno())\n"
        "time.sleep(10)\n"
    )


def _trace_writer_exit_code(payload: str) -> str:
    return (
        "import os\n"
        "path=os.environ['TRACE_PATH']\n"
        f"payload={payload!r}\n"
        "with open(path,'w',encoding='utf-8') as handle:\n"
        " handle.write(payload); handle.flush(); os.fsync(handle.fileno())\n"
    )


def test_sanitized_environment_is_allowlist_only_and_disables_dotenv() -> None:
    environment = build_sanitized_environment(
        allowlist=("SAFE_VALUE", "OPENROUTER_API_KEY"),
        overrides={"SAFE_VALUE": "kept"},
        scripted=True,
        source={
            "PATH": "/bin",
            "SAFE_VALUE": "ambient",
            "OPENROUTER_API_KEY": "must-not-leak",
            "UNLISTED": "must-not-leak",
        },
    )

    assert environment == {
        "FORT_GYM_DISABLE_DOTENV": "1",
        "PATH": "/bin",
        "SAFE_VALUE": "kept",
    }
    with pytest.raises(ValueError, match="scripted mode rejects"):
        build_sanitized_environment(
            allowlist=("OPENROUTER_API_KEY",),
            overrides={"OPENROUTER_API_KEY": "rejected"},
            scripted=True,
            source={},
        )


def test_provider_enabled_spec_requires_positive_default_on_caps(
    tmp_path: Path,
) -> None:
    spec = _run_spec(
        tmp_path,
        "positive-caps",
        "pass",
        scripted=False,
        provider_enabled=True,
        provider_route="openrouter",
        provider_model="openai/test-model",
        provider_name="OpenAI",
    )
    assert spec.max_total_tokens > 0
    assert spec.max_cost_usd > 0

    with pytest.raises(ValueError, match="positive token cap"):
        _run_spec(
            tmp_path,
            "zero-token-cap",
            "pass",
            scripted=False,
            provider_enabled=True,
            provider_route="openrouter",
            provider_model="openai/test-model",
            provider_name="OpenAI",
            max_total_tokens=0,
        )

    with pytest.raises(ValueError, match="pin a provider name"):
        _run_spec(
            tmp_path,
            "missing-provider-pin",
            "pass",
            scripted=False,
            provider_enabled=True,
            provider_route="openrouter",
            provider_model="openai/test-model",
            provider_name="",
        )


def test_identity_and_cotenancy_are_immutable_bounded_and_durable(
    tmp_path: Path,
) -> None:
    environment_identity = {
        "image": {"manifest_digest": "sha256:test"},
        "seed_attestation": "seed-test",
    }
    cotenancy = {"slot": 2, "peer_run_ids": ["peer-a", "peer-b"]}
    spec = _run_spec(
        tmp_path,
        "identity-evidence",
        "pass",
        environment_identity=environment_identity,
        cotenancy=cotenancy,
    )
    environment_identity["image"]["manifest_digest"] = "mutated-by-caller"
    cotenancy["peer_run_ids"].append("peer-c")

    with pytest.raises(TypeError):
        spec.environment_identity["new"] = "rejected"  # type: ignore[index]
    assert spec.environment_identity["image"]["manifest_digest"] == "sha256:test"
    assert spec.cotenancy["peer_run_ids"] == ("peer-a", "peer-b")

    result = ProcessSupervisor().run(spec)
    attempt_started = _journal(result)[0]
    for evidence in (attempt_started, result.payload):
        assert evidence["environment_identity"]["seed_attestation"] == "seed-test"
        assert evidence["cotenancy"]["slot"] == 2
        assert (
            evidence["supervisor_runtime"]["python_version"]
            == platform.python_version()
        )
        assert evidence["supervisor_runtime"]["platform"]

    with pytest.raises(TypeError, match="non-JSON-safe"):
        _run_spec(
            tmp_path,
            "invalid-identity",
            "pass",
            environment_identity={"bad": object()},
        )
    with pytest.raises(ValueError, match="encoded bytes"):
        _run_spec(
            tmp_path,
            "oversized-cotenancy",
            "pass",
            cotenancy={"blob": "x" * 20_000},
        )


def test_port_lease_is_exclusive_and_checks_loopback_bind(tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as finder:
        finder.bind(("127.0.0.1", 0))
        leased_port = int(finder.getsockname()[1])
    first = PortLease(leased_port, tmp_path / "locks").acquire()
    try:
        with pytest.raises(PortLeaseBusy):
            PortLease(leased_port, tmp_path / "locks").acquire()
    finally:
        first.release()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied_port = int(occupied.getsockname()[1])
        with pytest.raises(PortUnavailable):
            PortLease(occupied_port, tmp_path / "locks").acquire()


def test_port_lease_lock_probe_is_independent_of_socket_bindability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_dir = tmp_path / "locks"
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("lock-only probe must not create a socket")
        ),
    )

    assert PortLease.lock_available(58_000, lock_dir) is True

    path = lock_dir / "tcp-127.0.0.1-58000.lock"
    fd = os.open(path, os.O_RDWR)
    try:
        PortLease._lock(fd)
        assert PortLease.lock_available(58_000, lock_dir) is False
    finally:
        PortLease._unlock(fd)
        os.close(fd)


def test_port_lease_32_way_race_has_one_winner_and_31_conflicts(tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as finder:
        finder.bind(("127.0.0.1", 0))
        leased_port = int(finder.getsockname()[1])

    contender_count = 32
    start = threading.Barrier(contender_count)
    release_path = tmp_path / "release-port-race-winner"
    lock_dir = tmp_path / "race-locks"
    outcomes: queue.Queue[tuple[str, Any]] = queue.Queue()
    winner_code = (
        "import os,time\n"
        "path=os.environ['PORT_RACE_RELEASE']\n"
        "while not os.path.exists(path):\n"
        " time.sleep(0.005)\n"
    )

    def contend(index: int) -> None:
        try:
            start.wait(timeout=5)
            result = ProcessSupervisor().run(
                _run_spec(
                    tmp_path,
                    f"port-race-{index:02d}",
                    winner_code,
                    env={"PORT_RACE_RELEASE": str(release_path)},
                    env_allowlist=("PORT_RACE_RELEASE",),
                    timeout_seconds=5.0,
                    port=leased_port,
                    port_lock_dir=lock_dir,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - surface every contender failure
            outcomes.put(("error", repr(exc)))
            return
        outcomes.put(("result", result))

    threads = [
        threading.Thread(target=contend, args=(index,))
        for index in range(contender_count)
    ]
    for thread in threads:
        thread.start()
    try:
        observed = [outcomes.get(timeout=5) for _ in range(contender_count - 1)]
        release_path.touch()
        observed.append(outcomes.get(timeout=5))
    finally:
        release_path.touch(exist_ok=True)
        for thread in threads:
            thread.join(timeout=5)

    assert [detail for outcome, detail in observed if outcome == "error"] == []
    assert all(not thread.is_alive() for thread in threads)
    results = [detail for outcome, detail in observed if outcome == "result"]
    winners = [
        result for result in results if result.terminal_class is TerminalClass.COMPLETED
    ]
    conflicts = [
        result
        for result in results
        if result.payload["reason"]["code"] == "port_lease_busy"
    ]
    assert len(winners) == 1
    assert len(conflicts) == 31
    assert all(result.payload["child_pid"] is None for result in conflicts)
    assert all(result.terminal_path.exists() for result in results)
    assert all(
        any(row["event"] == "port_policy_rejected" for row in _journal(result))
        for result in conflicts
    )


def test_port_policy_failures_have_distinct_durable_reasons(tmp_path: Path) -> None:
    lock_dir = tmp_path / "policy-locks"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as finder:
        finder.bind(("127.0.0.1", 0))
        leased_port = int(finder.getsockname()[1])

    held = PortLease(leased_port, lock_dir).acquire()
    try:
        busy = ProcessSupervisor().run(
            _run_spec(
                tmp_path,
                "port-lease-busy",
                "pass",
                port=leased_port,
                port_lock_dir=lock_dir,
            )
        )
    finally:
        held.release()

    assert busy.terminal_class is TerminalClass.PORT_POLICY_FAILURE
    assert busy.payload["child_pid"] is None
    assert busy.payload["reason"]["code"] == "port_lease_busy"
    assert any(row["event"] == "port_policy_rejected" for row in _journal(busy))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied_port = int(occupied.getsockname()[1])
        unavailable = ProcessSupervisor().run(
            _run_spec(
                tmp_path,
                "port-unavailable",
                "pass",
                port=occupied_port,
                port_lock_dir=lock_dir,
            )
        )

    assert unavailable.terminal_class is TerminalClass.PORT_POLICY_FAILURE
    assert unavailable.payload["child_pid"] is None
    assert unavailable.payload["reason"]["code"] == "port_unavailable"
    assert any(row["event"] == "port_policy_rejected" for row in _journal(unavailable))


def test_completed_child_writes_terminal_only_after_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-secret")
    code = (
        "import os,sys\n"
        "ok=os.environ.get('FORT_GYM_DISABLE_DOTENV')=='1'\n"
        "ok=ok and 'OPENROUTER_API_KEY' not in os.environ\n"
        "sys.exit(0 if ok else 91)\n"
    )
    spec = _run_spec(tmp_path, "completed", code)
    terminal_path = spec.artifact_dir / "terminal.json"

    def cleanup() -> dict[str, int]:
        assert not terminal_path.exists()
        return {"residual_processes": 0}

    result = ProcessSupervisor().run(spec, cleanup=cleanup)

    assert result.terminal_class is TerminalClass.COMPLETED
    terminal = json.loads(result.terminal_path.read_text(encoding="utf-8"))
    assert terminal["cleanup"]["ok"] is True
    assert terminal["terminal_class"] == "completed"
    rows = _journal(result)
    events = [row["event"] for row in rows]
    assert events.index("cleanup_recorded") < events.index("terminal_pending")
    assert all(row["schema"] == "fortgym.process-supervisor-attempt/v1" for row in rows)


def test_terminal_chain_is_exact_identity_bound_and_precedes_pending(
    tmp_path: Path,
) -> None:
    spec = _run_spec(tmp_path, "terminal-chain", "raise SystemExit(0)")
    result = ProcessSupervisor().run(spec, cleanup=lambda: {"residual_processes": 0})
    terminal = json.loads(result.terminal_path.read_text(encoding="utf-8"))
    proof = validate_terminal_chain(
        spec.artifact_dir,
        terminal,
        run_id=spec.run_id,
        require_cleanup_success=True,
    )
    rows = _journal(result)
    chain = [row for row in rows if row["event"] in TERMINAL_CHAIN_EVENTS]
    assert tuple(row["event"] for row in chain) == TERMINAL_CHAIN_EVENTS
    assert rows[-2]["event"] == "immutable_terminal_classification"
    assert rows[-1]["event"] == "terminal_pending"
    assert proof["events"] == TERMINAL_CHAIN_EVENTS

    chain[3]["identity"]["run_id"] = "foreign-run"
    result.journal_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    with pytest.raises(SupervisorError, match="identities differ"):
        validate_terminal_chain(spec.artifact_dir, terminal, run_id=spec.run_id)


def test_snapshot_failure_cannot_validate_terminal_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = process_supervisor_module._atomic_write_json

    def fail_snapshot(path: Path, payload: Mapping[str, Any]) -> None:
        if Path(path).name == "evidence-snapshot.json":
            raise OSError("synthetic snapshot durability failure")
        original(path, payload)

    monkeypatch.setattr(process_supervisor_module, "_atomic_write_json", fail_snapshot)
    spec = _run_spec(tmp_path, "snapshot-failure", "raise SystemExit(0)")
    result = ProcessSupervisor().run(spec)
    terminal = json.loads(result.terminal_path.read_text(encoding="utf-8"))
    assert terminal["terminal_class"] == "cleanup_failure"
    assert terminal["cleanup"]["ok"] is False
    snapshot_rows = [
        row for row in _journal(result) if row["event"] == "evidence_snapshot_completed"
    ]
    assert len(snapshot_rows) == 1 and snapshot_rows[0]["ok"] is False
    with pytest.raises((OSError, SupervisorError)):
        validate_terminal_chain(spec.artifact_dir, terminal, run_id=spec.run_id)


def test_terminal_chain_rejects_an_earlier_duplicate_pending_record(
    tmp_path: Path,
) -> None:
    spec = _run_spec(tmp_path, "duplicate-terminal-pending", "raise SystemExit(0)")
    result = ProcessSupervisor().run(spec)
    terminal = json.loads(result.terminal_path.read_text(encoding="utf-8"))
    rows = _journal(result)
    duplicate = dict(rows[-1])
    duplicate["monotonic_ns"] = rows[-2]["monotonic_ns"]
    rows.insert(-2, duplicate)
    result.journal_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(SupervisorError, match="terminal-pending"):
        validate_terminal_chain(spec.artifact_dir, terminal, run_id=spec.run_id)


def test_prepare_runs_after_port_lease_before_child_and_cleanup(tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as finder:
        finder.bind(("127.0.0.1", 0))
        leased_port = int(finder.getsockname()[1])
    marker = tmp_path / "runtime-prepared"
    spec = _run_spec(
        tmp_path,
        "prepared-runtime",
        "import os,sys\nsys.exit(0 if os.path.exists(os.environ['PREPARED']) else 88)\n",
        env={"PREPARED": str(marker)},
        env_allowlist=("PREPARED",),
        port=leased_port,
        port_lock_dir=tmp_path / "prepare-locks",
    )
    observed: list[str] = []

    def prepare() -> dict[str, str]:
        with pytest.raises(PortLeaseBusy):
            PortLease(leased_port, spec.port_lock_dir).acquire()
        assert not (spec.artifact_dir / "terminal.json").exists()
        marker.touch()
        observed.append("prepare")
        return {"runtime": "synthetic"}

    def cleanup() -> dict[str, int]:
        assert marker.exists()
        assert not (spec.artifact_dir / "terminal.json").exists()
        observed.append("cleanup")
        return {"runtime_residue": 0}

    result = ProcessSupervisor().run(spec, prepare=prepare, cleanup=cleanup)

    assert result.terminal_class is TerminalClass.COMPLETED
    assert observed == ["prepare", "cleanup"]
    assert result.payload["prepare"] == {
        "ok": True,
        "skipped": False,
        "details": {"runtime": "synthetic"},
    }
    events = [row["event"] for row in _journal(result)]
    assert events.index("port_leased") < events.index("runtime_prepare_started")
    assert events.index("runtime_prepare_completed") < events.index("child_started")


def test_prepare_failure_never_starts_child_but_still_runs_cleanup(
    tmp_path: Path,
) -> None:
    child_marker = tmp_path / "child-started"
    cleanup_calls: list[str] = []
    spec = _run_spec(
        tmp_path,
        "prepare-failure",
        f"from pathlib import Path\nPath({str(child_marker)!r}).touch()\n",
    )

    def prepare() -> None:
        raise RuntimeError("synthetic prepare failure")

    def cleanup() -> dict[str, int]:
        cleanup_calls.append("cleanup")
        return {"runtime_residue": 0}

    result = ProcessSupervisor().run(spec, prepare=prepare, cleanup=cleanup)

    assert result.terminal_class is TerminalClass.PREPARE_FAILURE
    assert result.payload["reason"]["code"] == "runtime_prepare_failed"
    assert result.payload["child_pid"] is None
    assert not child_marker.exists()
    assert cleanup_calls == ["cleanup"]
    assert result.payload["prepare"]["ok"] is False
    assert result.payload["cleanup"]["ok"] is True


@pytest.mark.parametrize(
    ("reported_code", "expected_code"),
    [
        ("container_create_failure", "container_create_failure"),
        ("rpc_readiness_timeout", "rpc_readiness_timeout"),
        ("map_readiness_timeout", "map_readiness_timeout"),
        ("invented_runtime_result", "runtime_prepare_failed"),
        ("../unsafe", "runtime_prepare_failed"),
        (None, "runtime_prepare_failed"),
    ],
)
def test_prepare_exception_preserves_only_frozen_terminal_code(
    tmp_path: Path,
    reported_code: str | None,
    expected_code: str,
) -> None:
    class TypedPrepareFailure(RuntimeError):
        terminal_code = reported_code

    result = ProcessSupervisor().run(
        _run_spec(tmp_path, f"typed-prepare-{expected_code}", "pass"),
        prepare=lambda: (_ for _ in ()).throw(TypedPrepareFailure("not ready")),
        cleanup=lambda: {"ok": True, "runtime_residue": 0},
    )

    assert result.terminal_class is TerminalClass.PREPARE_FAILURE
    assert result.payload["reason"]["code"] == expected_code
    assert result.payload["child_pid"] is None
    assert result.payload["cleanup"]["ok"] is True
    events = _journal(result)
    assert all(row["event"] != "child_started" for row in events)
    failed = next(row for row in events if row["event"] == "runtime_prepare_failed")
    if expected_code in {
        "container_create_failure",
        "rpc_readiness_timeout",
        "map_readiness_timeout",
    }:
        assert failed["prepare"]["terminal_code"] == expected_code
    else:
        assert "terminal_code" not in failed["prepare"]


def test_authoritative_prepare_failure_skips_runtime_fault_classifier(
    tmp_path: Path,
) -> None:
    class RuntimeReadinessTimeout(RuntimeError):
        terminal_code = "rpc_readiness_timeout"

    classifier_calls = 0

    def classify(_observation: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal classifier_calls
        classifier_calls += 1
        raise AssertionError("prepare classification must retain precedence")

    def prepare() -> None:
        raise RuntimeReadinessTimeout("RPC did not become ready")

    result = ProcessSupervisor().run(
        _run_spec(tmp_path, "prepare-precedes-runtime-classifier", "pass"),
        prepare=prepare,
        cleanup=lambda: {"ok": True},
        fault_classifier=classify,
    )

    assert result.terminal_class is TerminalClass.PREPARE_FAILURE
    assert result.payload["reason"]["code"] == "rpc_readiness_timeout"
    assert result.payload["fault_classification"]["skipped"] == (
        "authoritative_primary_terminal_precedence"
    )
    assert classifier_calls == 0


@pytest.mark.parametrize("reported_ok", [False, 1, "true", None])
def test_prepare_callback_status_is_literal_and_fails_closed(
    tmp_path: Path, reported_ok: object
) -> None:
    child_marker = tmp_path / "prepare-status-child-started"
    spec = _run_spec(
        tmp_path,
        f"prepare-status-{reported_ok!s}",
        f"from pathlib import Path\nPath({str(child_marker)!r}).touch()\n",
    )
    details = {"ok": reported_ok, "runtime": "not-ready"}

    result = ProcessSupervisor().run(spec, prepare=lambda: details)

    assert result.terminal_class is TerminalClass.PREPARE_FAILURE
    assert result.payload["reason"]["code"] == "runtime_prepare_failed"
    assert result.payload["prepare"] == {
        "ok": False,
        "skipped": False,
        "details": details,
    }
    assert result.payload["child_pid"] is None
    assert not child_marker.exists()
    failed_row = next(
        row for row in _journal(result) if row["event"] == "runtime_prepare_failed"
    )
    assert failed_row["prepare"]["details"] == details


def test_prepare_callback_requires_mapping_but_preserves_none_and_legacy_mapping(
    tmp_path: Path,
) -> None:
    invalid = ProcessSupervisor().run(
        _run_spec(tmp_path, "prepare-invalid-result", "pass"),
        prepare=lambda: ["not", "a", "mapping"],  # type: ignore[arg-type,return-value]
    )

    assert invalid.terminal_class is TerminalClass.PREPARE_FAILURE
    assert invalid.payload["child_pid"] is None
    assert invalid.payload["prepare"]["error"] == {
        "type": "TypeError",
        "message": "prepare callback must return a mapping or None",
    }

    for suffix, prepare, expected_details in (
        ("none", lambda: None, {}),
        ("legacy", lambda: {"runtime": "ready"}, {"runtime": "ready"}),
        ("literal-true", lambda: {"ok": True}, {"ok": True}),
    ):
        result = ProcessSupervisor().run(
            _run_spec(tmp_path, f"prepare-valid-{suffix}", "pass"),
            prepare=prepare,
        )
        assert result.terminal_class is TerminalClass.COMPLETED
        assert result.payload["prepare"] == {
            "ok": True,
            "skipped": False,
            "details": expected_details,
        }


def test_nonzero_child_exit_is_classified(tmp_path: Path) -> None:
    result = ProcessSupervisor().run(
        _run_spec(tmp_path, "child-exit", "raise SystemExit(7)")
    )

    assert result.terminal_class is TerminalClass.CHILD_EXIT
    assert result.payload["returncode"] == 7
    assert result.payload["cleanup"]["ok"] is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal semantics")
def test_child_signal_is_classified_as_external(tmp_path: Path) -> None:
    code = "import os,signal\nos.kill(os.getpid(), signal.SIGTERM)\n"
    result = ProcessSupervisor().run(_run_spec(tmp_path, "external-signal", code))

    assert result.terminal_class is TerminalClass.EXTERNAL_SIGNAL
    assert result.payload["child_signal"] == signal.SIGTERM
    assert result.payload["cleanup"]["ok"] is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX TERM-to-KILL escalation")
def test_timeout_terms_then_kills_and_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = (
        "import signal,time\n"
        "signal.signal(signal.SIGTERM, lambda *_: None)\n"
        "time.sleep(10)\n"
    )
    spec = _run_spec(
        tmp_path,
        "timeout",
        code,
        timeout_seconds=0.2,
        term_grace_seconds=0.08,
    )
    guarded_reaps = _guard_reap_after_terminal_snapshot(
        monkeypatch, spec.artifact_dir / "attempt-journal.jsonl"
    )
    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.TIMEOUT
    assert result.payload["termination"]["term_sent"] is True
    assert result.payload["termination"]["kill_sent"] is True
    assert result.payload["termination"]["wait_complete"] is True
    assert result.payload["cleanup"]["ok"] is True
    assert len(guarded_reaps) == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group semantics")
def test_exited_child_leaving_ignoring_descendant_is_killed_and_reaped(
    tmp_path: Path,
) -> None:
    descendant_pid_path = tmp_path / "descendant.pid"
    descendant_code = (
        "import os,signal,time\n"
        "signal.signal(signal.SIGTERM, lambda *_: None)\n"
        "path=os.environ['DESCENDANT_PID_PATH']\n"
        "with open(path,'w',encoding='utf-8') as handle:\n"
        " handle.write(str(os.getpid())); handle.flush(); os.fsync(handle.fileno())\n"
        "time.sleep(10)\n"
    )
    parent_code = (
        "import os,subprocess,sys,time\n"
        f"code={descendant_code!r}\n"
        "child=subprocess.Popen([sys.executable,'-c',code])\n"
        "path=os.environ['DESCENDANT_PID_PATH']\n"
        "deadline=time.monotonic()+2\n"
        "while not os.path.exists(path) and time.monotonic()<deadline:\n"
        " time.sleep(0.005)\n"
        "raise SystemExit(0 if os.path.exists(path) else 92)\n"
    )
    spec = _run_spec(
        tmp_path,
        "orphan-descendant",
        parent_code,
        env={"DESCENDANT_PID_PATH": str(descendant_pid_path)},
        env_allowlist=("DESCENDANT_PID_PATH",),
    )

    result = ProcessSupervisor().run(spec)

    descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
    assert result.terminal_class is TerminalClass.COMPLETED
    assert result.payload["cleanup"]["ok"] is True
    process_stage = next(
        stage
        for stage in result.payload["cleanup"]["stages"]
        if stage["stage"] == "process_group"
    )
    assert process_stage["details"]["term_sent"] is True
    assert process_stage["details"]["kill_sent"] is True
    assert process_stage["details"]["wait_complete"] is True
    assert process_stage["group_exists"] is False
    with pytest.raises(ProcessLookupError):
        os.kill(descendant_pid, 0)


def test_live_trace_token_cap_terminates_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_dir = tmp_path / "cap-trip"
    trace_path = artifact_dir / "trace.jsonl"
    spec = _run_spec(
        tmp_path,
        "cap-trip",
        _trace_writer_code(_openrouter_event(tokens=11)),
        artifact_dir=artifact_dir,
        trace_path=trace_path,
        env={"TRACE_PATH": str(trace_path)},
        env_allowlist=("TRACE_PATH",),
        scripted=False,
        provider_enabled=True,
        provider_route="openrouter",
        provider_model="openai/test-model",
        provider_name="OpenAI",
        max_total_tokens=10,
        max_cost_usd=1.0,
    )
    guarded_reaps = _guard_reap_after_terminal_snapshot(
        monkeypatch, spec.artifact_dir / "attempt-journal.jsonl"
    )
    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.CAP_TRIP
    assert result.payload["reason"]["code"] == "token_cap_reached"
    assert result.payload["budget"]["total_tokens"] == 11
    assert result.payload["cleanup"]["ok"] is True
    assert len(guarded_reaps) == 1


def test_stop_request_defers_reap_until_terminal_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = ProcessSupervisor()
    spec = _run_spec(tmp_path, "stop-order", "import time; time.sleep(10)")
    guarded_reaps = _guard_reap_after_terminal_snapshot(
        monkeypatch, spec.artifact_dir / "attempt-journal.jsonl"
    )
    original_poll = TraceBudgetMonitor.poll
    triggered = False

    def trigger_stop(monitor):
        nonlocal triggered
        if not triggered:
            triggered = True
            supervisor.request_stop(signal.SIGTERM)
        return original_poll(monitor)

    monkeypatch.setattr(TraceBudgetMonitor, "poll", trigger_stop)
    result = supervisor.run(spec)

    assert result.payload["reason"]["code"] == "supervisor_stop_requested"
    assert len(guarded_reaps) == 1


def test_monitor_error_defers_reap_until_terminal_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _run_spec(tmp_path, "monitor-error-order", "import time; time.sleep(10)")
    guarded_reaps = _guard_reap_after_terminal_snapshot(
        monkeypatch, spec.artifact_dir / "attempt-journal.jsonl"
    )

    def fail_poll(_monitor):
        raise RuntimeError("synthetic monitor failure")

    monkeypatch.setattr(TraceBudgetMonitor, "poll", fail_poll)
    result = ProcessSupervisor().run(spec)

    assert result.payload["primary_reason"]["code"] == (
        "supervisor_start_or_monitor_error"
    )
    assert len(guarded_reaps) == 1


def test_child_exit_finalizes_valid_trace_without_trailing_newline(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "partial-cap-trip"
    trace_path = artifact_dir / "trace.jsonl"
    payload = json.dumps(_openrouter_event(tokens=11), sort_keys=True)
    spec = _run_spec(
        tmp_path,
        "partial-cap-trip",
        _trace_writer_exit_code(payload),
        artifact_dir=artifact_dir,
        trace_path=trace_path,
        env={"TRACE_PATH": str(trace_path)},
        env_allowlist=("TRACE_PATH",),
        scripted=False,
        provider_enabled=True,
        provider_route="openrouter",
        provider_model="openai/test-model",
        provider_name="OpenAI",
        max_total_tokens=10,
        max_cost_usd=1.0,
    )

    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.CAP_TRIP
    assert result.payload["reason"]["code"] == "token_cap_reached"
    assert result.payload["budget"]["total_tokens"] == 11


def test_child_exit_fails_closed_on_invalid_trailing_trace_fragment(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "invalid-partial-trace"
    trace_path = artifact_dir / "trace.jsonl"
    spec = _run_spec(
        tmp_path,
        "invalid-partial-trace",
        _trace_writer_exit_code('{"events":['),
        artifact_dir=artifact_dir,
        trace_path=trace_path,
        env={"TRACE_PATH": str(trace_path)},
        env_allowlist=("TRACE_PATH",),
    )

    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.CAP_TRIP
    assert result.payload["reason"]["code"] == "trace_accounting_invalid"


def test_live_trace_usd_cap_terminates_child(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "usd-cap-trip"
    trace_path = artifact_dir / "trace.jsonl"
    spec = _run_spec(
        tmp_path,
        "usd-cap-trip",
        _trace_writer_code(_openrouter_event(tokens=1, cost=0.01)),
        artifact_dir=artifact_dir,
        trace_path=trace_path,
        env={"TRACE_PATH": str(trace_path)},
        env_allowlist=("TRACE_PATH",),
        scripted=False,
        provider_enabled=True,
        provider_route="openrouter",
        provider_model="openai/test-model",
        provider_name="OpenAI",
        max_total_tokens=100,
        max_cost_usd=0.01,
    )
    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.CAP_TRIP
    assert result.payload["reason"]["code"] == "usd_cap_reached"
    assert result.payload["budget"]["total_cost_usd"] == 0.01
    assert result.payload["cleanup"]["ok"] is True


def test_live_trace_provider_model_pin_violation_terminates_child(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "pin-violation"
    trace_path = artifact_dir / "trace.jsonl"
    spec = _run_spec(
        tmp_path,
        "pin-violation",
        _trace_writer_code(_openrouter_event(model="openai/wrong-model")),
        artifact_dir=artifact_dir,
        trace_path=trace_path,
        env={"TRACE_PATH": str(trace_path)},
        env_allowlist=("TRACE_PATH",),
        scripted=False,
        provider_enabled=True,
        provider_route="openrouter",
        provider_model="openai/test-model",
        provider_name="OpenAI",
        max_total_tokens=100,
        max_cost_usd=1.0,
    )
    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.PROVIDER_PIN_VIOLATION
    assert result.payload["reason"]["code"] == "provider_pin_mismatch"
    assert result.payload["cleanup"]["ok"] is True


def test_billable_trace_missing_resolved_provider_fails_closed(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "missing-resolved-provider"
    trace_path = artifact_dir / "trace.jsonl"
    spec = _run_spec(
        tmp_path,
        "missing-resolved-provider",
        _trace_writer_code(_openrouter_event(provider="", tokens=1, cost=0.01)),
        artifact_dir=artifact_dir,
        trace_path=trace_path,
        env={"TRACE_PATH": str(trace_path)},
        env_allowlist=("TRACE_PATH",),
        scripted=False,
        provider_enabled=True,
        provider_route="openrouter",
        provider_model="openai/test-model",
        provider_name="OpenAI",
        max_total_tokens=100,
        max_cost_usd=1.0,
    )

    result = ProcessSupervisor().run(spec)

    assert result.terminal_class is TerminalClass.PROVIDER_PIN_VIOLATION
    assert result.payload["reason"]["code"] == "provider_pin_mismatch"
    assert result.payload["reason"]["provider"] == {
        "expected": "OpenAI",
        "observed": None,
    }


def test_cleanup_failure_overrides_primary_terminal_class(tmp_path: Path) -> None:
    spec = _run_spec(tmp_path, "cleanup-failure", "pass")

    def cleanup() -> None:
        assert not (spec.artifact_dir / "terminal.json").exists()
        raise RuntimeError("synthetic cleanup failure")

    result = ProcessSupervisor().run(spec, cleanup=cleanup)

    assert result.terminal_class is TerminalClass.CLEANUP_FAILURE
    assert result.payload["primary_terminal_class"] == "completed"
    assert result.payload["cleanup"]["ok"] is False
    callback = next(
        stage
        for stage in result.payload["cleanup"]["stages"]
        if stage["stage"] == "callback"
    )
    assert callback["error"]["type"] == "RuntimeError"
    cleanup_row = next(
        row for row in _journal(result) if row["event"] == "cleanup_recorded"
    )
    assert cleanup_row["cleanup"]["ok"] is False


@pytest.mark.parametrize("reported_ok", [False, 1, "true", None])
def test_cleanup_callback_status_is_literal_and_fails_terminal_cleanup(
    tmp_path: Path, reported_ok: object
) -> None:
    details = {"ok": reported_ok, "runtime_residue": 1}
    result = ProcessSupervisor().run(
        _run_spec(tmp_path, f"cleanup-status-{reported_ok!s}", "pass"),
        cleanup=lambda: details,
    )

    assert result.terminal_class is TerminalClass.CLEANUP_FAILURE
    assert result.payload["primary_terminal_class"] == "completed"
    assert result.payload["cleanup"]["ok"] is False
    callback = next(
        stage
        for stage in result.payload["cleanup"]["stages"]
        if stage["stage"] == "callback"
    )
    assert callback == {"stage": "callback", "ok": False, "details": details}


def test_cleanup_callback_requires_mapping_but_preserves_none_and_legacy_mapping(
    tmp_path: Path,
) -> None:
    invalid = ProcessSupervisor().run(
        _run_spec(tmp_path, "cleanup-invalid-result", "pass"),
        cleanup=lambda: "not a mapping",  # type: ignore[arg-type,return-value]
    )

    assert invalid.terminal_class is TerminalClass.CLEANUP_FAILURE
    invalid_callback = next(
        stage
        for stage in invalid.payload["cleanup"]["stages"]
        if stage["stage"] == "callback"
    )
    assert invalid_callback["error"] == {
        "type": "TypeError",
        "message": "cleanup callback must return a mapping or None",
    }

    for suffix, cleanup, expected_details in (
        ("none", lambda: None, {}),
        ("legacy", lambda: {"runtime_residue": 0}, {"runtime_residue": 0}),
        ("literal-true", lambda: {"ok": True}, {"ok": True}),
    ):
        result = ProcessSupervisor().run(
            _run_spec(tmp_path, f"cleanup-valid-{suffix}", "pass"),
            cleanup=cleanup,
        )
        assert result.terminal_class is TerminalClass.COMPLETED
        callback = next(
            stage
            for stage in result.payload["cleanup"]["stages"]
            if stage["stage"] == "callback"
        )
        assert callback == {
            "stage": "callback",
            "ok": True,
            "details": expected_details,
        }


def test_post_observation_classifier_emits_exact_typed_runtime_fault(
    tmp_path: Path,
) -> None:
    observations: list[Mapping[str, Any]] = []

    def classify(observation: Mapping[str, Any]) -> Mapping[str, Any]:
        observations.append(observation)
        return {
            "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
            "terminal_class": "runtime_df_killed",
            "evidence": {
                "runtime_identity": {
                    "expected": "container-a",
                    "observed": "container-a",
                },
                "signal": 9,
                "oom_killed": False,
            },
        }

    result = ProcessSupervisor().run(
        _run_spec(tmp_path, "typed-runtime-df-killed", "raise SystemExit(22)"),
        fault_classifier=classify,
    )

    assert result.terminal_class is TerminalClass.RUNTIME_DF_KILLED
    assert result.payload["primary_terminal_class"] == "child_exit"
    assert result.payload["reason"]["code"] == "runtime_df_killed"
    assert result.payload["fault_classification"] == {
        "schema": "fortgym.runtime-fault-classification/v1",
        "attempted": True,
        "ok": True,
        "classified": True,
        "terminal_class": "runtime_df_killed",
        "evidence": {
            "runtime_identity": {
                "expected": "container-a",
                "observed": "container-a",
            },
            "signal": 9,
            "oom_killed": False,
        },
    }
    assert len(observations) == 1
    assert observations[0]["cleanup"]["ok"] is True
    assert observations[0]["returncode"] == 22
    assert result.terminal_path.is_file()


def test_explicit_no_fault_classification_preserves_primary_outcome(
    tmp_path: Path,
) -> None:
    result = ProcessSupervisor().run(
        _run_spec(tmp_path, "explicit-no-runtime-fault", "pass"),
        fault_classifier=lambda _observation: {
            "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
            "terminal_class": None,
            "evidence": {},
        },
    )

    assert result.terminal_class is TerminalClass.COMPLETED
    assert result.payload["reason"] == {"code": "child_completed"}
    assert result.payload["fault_classification"]["ok"] is True
    assert result.payload["fault_classification"]["classified"] is False


@pytest.mark.parametrize("invalid_result", [None, "runtime_oom", ["runtime_oom"]])
def test_non_mapping_fault_classifier_result_fails_closed(
    tmp_path: Path, invalid_result: object
) -> None:
    result = ProcessSupervisor().run(
        _run_spec(
            tmp_path, f"classifier-non-mapping-{type(invalid_result).__name__}", "pass"
        ),
        fault_classifier=lambda _observation: invalid_result,  # type: ignore[arg-type,return-value]
    )

    assert result.terminal_class is TerminalClass.RUNTIME_FAULT_CLASSIFICATION_FAILURE
    assert result.payload["reason"]["code"] == "runtime_fault_classification_failure"
    assert result.payload["reason"]["prior_terminal_class"] == "completed"
    assert result.payload["fault_classification"]["ok"] is False
    assert result.payload["cleanup"]["ok"] is True


def test_fault_classifier_exception_fails_closed_before_terminal_write(
    tmp_path: Path,
) -> None:
    spec = _run_spec(tmp_path, "classifier-exception", "pass")

    def classify(_observation: Mapping[str, Any]) -> Mapping[str, Any]:
        assert not (spec.artifact_dir / "terminal.json").exists()
        raise RuntimeError("synthetic classifier failure")

    result = ProcessSupervisor().run(spec, fault_classifier=classify)

    assert result.terminal_class is TerminalClass.RUNTIME_FAULT_CLASSIFICATION_FAILURE
    assert result.payload["reason"]["classification_error"] == {
        "type": "RuntimeError",
        "message": "synthetic classifier failure",
    }
    assert result.terminal_path.is_file()


def test_fault_classifier_missing_required_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    result = ProcessSupervisor().run(
        _run_spec(tmp_path, "classifier-missing-oom-evidence", "raise SystemExit(137)"),
        fault_classifier=lambda _observation: {
            "schema": FAULT_CLASSIFIER_RESULT_SCHEMA,
            "terminal_class": "runtime_oom",
            "evidence": {
                "runtime_identity": {
                    "expected": "container-a",
                    "observed": "container-a",
                },
                "runtime_exit_code": 137,
            },
        },
    )

    assert result.terminal_class is TerminalClass.RUNTIME_FAULT_CLASSIFICATION_FAILURE
    assert result.payload["reason"]["classification_error"]["type"] == (
        "FaultClassificationError"
    )
    assert result.payload["reason"]["prior_terminal_class"] == "child_exit"
    assert result.payload["returncode"] == 137


def test_cleanup_failure_has_absolute_precedence_and_skips_classifier(
    tmp_path: Path,
) -> None:
    classifier_calls = 0

    def classify(_observation: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal classifier_calls
        classifier_calls += 1
        raise AssertionError("classifier must not run after cleanup failure")

    result = ProcessSupervisor().run(
        _run_spec(tmp_path, "cleanup-before-classifier", "pass"),
        cleanup=lambda: {"ok": False, "runtime_residue": 1},
        fault_classifier=classify,
    )

    assert result.terminal_class is TerminalClass.CLEANUP_FAILURE
    assert result.payload["primary_terminal_class"] == "completed"
    assert result.payload["fault_classification"] == {
        "schema": "fortgym.runtime-fault-classification/v1",
        "attempted": False,
        "ok": True,
        "classified": False,
        "skipped": "cleanup_failure_precedence",
    }
    assert classifier_calls == 0
