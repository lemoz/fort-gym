from __future__ import annotations

import json
import os
import queue
import signal
import socket
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.run.process_supervisor import (
    PortLease,
    ProcessSupervisor,
    RunSpec,
    SupervisionResult,
    TerminalClass,
)
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import SupervisedRunManager
from infra.m1b.run_live_acceptance import _port2_conflict_terminal_proof

_HOST = "127.0.0.1"
_PEER_RUN_ID = "port2-local-peer-a"
_PEER_NONCE = "a" * 32
_CONTENDER_RUN_ID = "port2-local-contender-b"
_CONTENDER_NONCE = "b" * 32
_MANAGED_CONTENDER_RUN_ID = "port2-local-managed-contender-b"
_MANAGED_CONTENDER_NONCE = "e" * 32
_MANAGED_CONTENDER_CONTRACT_SHA256 = "f" * 64
_REACQUIRE_RUN_ID = "port2-local-reacquire-c"
_REACQUIRE_NONCE = "c" * 32
_CLASSIFICATION = "local_engineering_preflight_not_real_df_port2_gate"
_IDENTITY_SCHEMA = "fortgym.port2-local-preflight/v1"
_MARKER_SCHEMA = "fortgym.port2-local-peer/v1"

_LIVE_PEER_CODE = r"""
import json
import os
import socket

host = os.environ["PORT2_PEER_HOST"]
port = int(os.environ["PORT2_PEER_PORT"])
marker_path = os.environ["PORT2_PEER_MARKER"]
payload = {
    "classification": os.environ["PORT2_CLASSIFICATION"],
    "host": host,
    "nonce": os.environ["PORT2_PEER_NONCE"],
    "port": port,
    "run_id": os.environ["PORT2_PEER_RUN_ID"],
    "schema": "fortgym.port2-local-peer/v1",
}
encoded = (
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
).encode("utf-8")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(8)
    descriptor = os.open(
        marker_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("short peer identity write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    while True:
        connection, _address = listener.accept()
        with connection:
            request = b""
            while not request.endswith(b"\n"):
                chunk = connection.recv(64)
                if not chunk:
                    break
                request += chunk
            if request != b"ping\n":
                raise RuntimeError("unexpected local peer request")
            connection.sendall(b"pong\n")
            while connection.recv(64):
                pass
""".lstrip()

_REACQUIRE_CODE = r"""
import json
import os
import socket

host = os.environ["PORT2_PEER_HOST"]
port = int(os.environ["PORT2_PEER_PORT"])
marker_path = os.environ["PORT2_PEER_MARKER"]
payload = {
    "classification": os.environ["PORT2_CLASSIFICATION"],
    "host": host,
    "nonce": os.environ["PORT2_PEER_NONCE"],
    "port": port,
    "run_id": os.environ["PORT2_PEER_RUN_ID"],
    "schema": "fortgym.port2-local-peer/v1",
}
encoded = (
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
).encode("utf-8")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(1)
    descriptor = os.open(
        marker_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("short reacquisition identity write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
""".lstrip()


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as finder:
        finder.bind((_HOST, 0))
        return int(finder.getsockname()[1])


def _identity(*, run_id: str, nonce: str, port: int) -> dict[str, Any]:
    return {
        "schema": _IDENTITY_SCHEMA,
        "classification": _CLASSIFICATION,
        "real_df_port2_gate": False,
        "host": _HOST,
        "port": port,
        "run_id": run_id,
        "nonce": nonce,
    }


def _marker_bytes(*, run_id: str, nonce: str, port: int) -> bytes:
    payload = {
        "schema": _MARKER_SCHEMA,
        "classification": _CLASSIFICATION,
        "host": _HOST,
        "port": port,
        "run_id": run_id,
        "nonce": nonce,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _peer_environment(
    *, run_id: str, nonce: str, port: int, marker: Path
) -> dict[str, str]:
    return {
        "PORT2_CLASSIFICATION": _CLASSIFICATION,
        "PORT2_PEER_HOST": _HOST,
        "PORT2_PEER_MARKER": str(marker),
        "PORT2_PEER_NONCE": nonce,
        "PORT2_PEER_PORT": str(port),
        "PORT2_PEER_RUN_ID": run_id,
    }


def _run_spec(
    tmp_path: Path,
    *,
    run_id: str,
    nonce: str,
    port: int,
    code: str,
    environment: Mapping[str, str],
    timeout_seconds: float = 20.0,
) -> RunSpec:
    return RunSpec(
        run_id=run_id,
        argv=(sys.executable, "-c", code),
        artifact_dir=tmp_path / run_id,
        env=dict(environment),
        env_allowlist=tuple(sorted(environment)),
        scripted=True,
        provider_enabled=False,
        timeout_seconds=timeout_seconds,
        term_grace_seconds=0.2,
        poll_interval_seconds=0.01,
        port=port,
        port_lock_dir=tmp_path / "port-leases",
        environment_identity=_identity(run_id=run_id, nonce=nonce, port=port),
    )


def _journal(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def _receive_line(connection: socket.socket) -> bytes:
    response = b""
    while not response.endswith(b"\n"):
        chunk = connection.recv(64)
        if not chunk:
            break
        response += chunk
    return response


def _round_trip(port: int) -> bytes:
    with socket.create_connection((_HOST, port), timeout=0.5) as connection:
        connection.settimeout(0.5)
        connection.sendall(b"ping\n")
        response = _receive_line(connection)
        connection.shutdown(socket.SHUT_WR)
        while connection.recv(64):
            pass
        return response


def _wait_for_live_peer(
    *,
    port: int,
    marker: Path,
    journal_path: Path,
    supervisor_thread: threading.Thread,
    timeout: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        rows = _journal(journal_path)
        events = [str(row.get("event")) for row in rows]
        if marker.is_file() and {"port_leased", "child_started"}.issubset(events):
            try:
                if _round_trip(port) == b"pong\n":
                    return
            except OSError as exc:
                last_error = exc
        if not supervisor_thread.is_alive():
            raise AssertionError("peer supervisor exited before readiness")
        time.sleep(0.01)
    raise AssertionError(f"local peer did not become ready: {last_error!r}")


def _run_in_thread(
    supervisor: ProcessSupervisor,
    spec: RunSpec,
    outcomes: queue.Queue[SupervisionResult | BaseException],
) -> None:
    try:
        outcomes.put(supervisor.run(spec))
    except BaseException as exc:  # noqa: BLE001 - preserve thread failures for pytest
        outcomes.put(exc)


def _require_result(
    outcomes: queue.Queue[SupervisionResult | BaseException],
) -> SupervisionResult:
    outcome = outcomes.get(timeout=1)
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome


def _assert_zero_spend(result: SupervisionResult) -> None:
    assert result.payload["budget"] == {
        "calls": 0,
        "events_seen": 0,
        "max_cost_usd": 25.0,
        "max_total_tokens": 128_000,
        "provider_enabled": False,
        "providers": [],
        "requested_models": [],
        "resolved_models": [],
        "total_cost_usd": 0.0,
        "total_tokens": 0,
    }


@pytest.mark.skipif(os.name != "posix", reason="preflight requires POSIX groups")
def test_port2_live_peer_duplicate_port_fails_closed_without_disturbing_owner(
    tmp_path: Path,
) -> None:
    """Local engineering preflight only; this is not the real DF PORT-2 gate."""

    port = _unused_loopback_port()
    lock_dir = tmp_path / "port-leases"
    peer_marker = tmp_path / "peer-a-ready.json"
    peer_environment = _peer_environment(
        run_id=_PEER_RUN_ID,
        nonce=_PEER_NONCE,
        port=port,
        marker=peer_marker,
    )
    peer_spec = _run_spec(
        tmp_path,
        run_id=_PEER_RUN_ID,
        nonce=_PEER_NONCE,
        port=port,
        code=_LIVE_PEER_CODE,
        environment=peer_environment,
    )
    peer_supervisor = ProcessSupervisor()
    peer_outcomes: queue.Queue[SupervisionResult | BaseException] = queue.Queue()
    peer_thread = threading.Thread(
        target=_run_in_thread,
        args=(peer_supervisor, peer_spec, peer_outcomes),
        name="port2-local-peer-supervisor",
    )
    peer_thread.start()

    try:
        _wait_for_live_peer(
            port=port,
            marker=peer_marker,
            journal_path=peer_spec.artifact_dir / "attempt-journal.jsonl",
            supervisor_thread=peer_thread,
        )
        expected_peer_marker = _marker_bytes(
            run_id=_PEER_RUN_ID,
            nonce=_PEER_NONCE,
            port=port,
        )
        peer_marker_before_race = peer_marker.read_bytes()
        assert peer_marker_before_race == expected_peer_marker
        peer_events = [
            row["event"]
            for row in _journal(peer_spec.artifact_dir / "attempt-journal.jsonl")
        ]
        assert peer_events.index("port_leased") < peer_events.index("child_started")
        assert (lock_dir / f"tcp-127.0.0.1-{port}.lock").is_file()
        assert _round_trip(port) == b"pong\n"

        contender_runtime_marker = tmp_path / "contender-runtime-prepared"
        contender_child_marker = tmp_path / "contender-child-started"
        contender_environment = {
            "PORT2_CONTENDER_CHILD_MARKER": str(contender_child_marker),
        }
        contender_code = (
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['PORT2_CONTENDER_CHILD_MARKER']).write_bytes(b'started')\n"
        )
        contender_spec = _run_spec(
            tmp_path,
            run_id=_CONTENDER_RUN_ID,
            nonce=_CONTENDER_NONCE,
            port=port,
            code=contender_code,
            environment=contender_environment,
            timeout_seconds=5.0,
        )

        def prepare_contender_runtime() -> Mapping[str, Any]:
            contender_runtime_marker.write_bytes(b"prepared")
            return {"ok": True, "marker": str(contender_runtime_marker)}

        race_started = time.monotonic()
        contender_result = ProcessSupervisor().run(
            contender_spec,
            prepare=prepare_contender_runtime,
        )
        race_elapsed = time.monotonic() - race_started

        assert race_elapsed <= 5.0
        assert contender_result.terminal_class is TerminalClass.PORT_POLICY_FAILURE
        assert contender_result.payload["child_pid"] is None
        assert contender_result.payload["reason"] == {
            "code": "port_lease_busy",
            "port": port,
            "type": "PortLeaseBusy",
            "message": f"port {port} already has a host lease",
        }
        assert contender_result.payload["environment_identity"] == _identity(
            run_id=_CONTENDER_RUN_ID,
            nonce=_CONTENDER_NONCE,
            port=port,
        )
        assert (
            json.loads(contender_result.terminal_path.read_text(encoding="utf-8"))
            == contender_result.payload
        )
        contender_events = [
            row["event"] for row in _journal(contender_result.journal_path)
        ]
        assert contender_events[0] == "attempt_started"
        assert "port_policy_rejected" in contender_events
        assert "runtime_prepare_started" not in contender_events
        assert "runtime_prepare_completed" not in contender_events
        assert "child_started" not in contender_events
        assert contender_events.index("cleanup_recorded") < contender_events.index(
            "terminal_pending"
        )
        assert not contender_runtime_marker.exists()
        assert not contender_child_marker.exists()
        _assert_zero_spend(contender_result)

        registry = RunRegistry(
            db_path=tmp_path / "managed-contender.sqlite3",
            artifacts_root=tmp_path / "managed-artifacts",
        )
        managed_record = registry.create(
            run_id=_MANAGED_CONTENDER_RUN_ID,
            backend="dfhack",
            model="dfhack-governed-scripted",
            max_steps=1,
            ticks_per_step=1,
            supervision_mode="m1b-process",
        )
        registry.set_summary(managed_record.run_id, {"total_score": 0, "steps": 0})
        managed_child_marker = tmp_path / "managed-contender-child-started"

        class ManagedRuntimeController:
            prepare_calls = 0
            cleanup_calls = 0

            def prepare(self) -> Mapping[str, Any]:
                self.prepare_calls += 1
                raise AssertionError("port-conflict runtime prepare must not run")

            def cleanup(self) -> Mapping[str, Any]:
                self.cleanup_calls += 1
                return {
                    "ok": True,
                    "container_absent": True,
                    "listener_absent": False,
                    "shared_listener_preserved": True,
                }

        managed_controller = ManagedRuntimeController()

        def managed_contract(record, attempt_dir, _controller) -> RunSpec:
            environment = {
                "PORT2_CONTENDER_CHILD_MARKER": str(managed_child_marker),
            }
            return RunSpec(
                run_id=record.run_id,
                argv=(
                    sys.executable,
                    "-m",
                    "fort_gym.bench.cli",
                    "experiment",
                    "/tmp/never-started.yaml",
                    "--external-run-id",
                    record.run_id,
                ),
                artifact_dir=attempt_dir,
                trace_path=Path(str(record.trace_path)),
                env=environment,
                env_allowlist=tuple(sorted(environment)),
                scripted=True,
                provider_enabled=False,
                timeout_seconds=5.0,
                term_grace_seconds=0.2,
                poll_interval_seconds=0.01,
                port=port,
                port_lock_dir=lock_dir,
                environment_identity={
                    "run_id": record.run_id,
                    "contract_sha256": _MANAGED_CONTENDER_CONTRACT_SHA256,
                    "rpc": {"nonce": _MANAGED_CONTENDER_NONCE},
                },
                runtime_cleanup_required=True,
            )

        managed_result = SupervisedRunManager(
            registry=registry,
            control_root=tmp_path / "managed-control",
            runtime_controller_factory=lambda _record, _run_dir: managed_controller,
            contract_factory=managed_contract,
        ).run(_MANAGED_CONTENDER_RUN_ID)
        managed_proof = _port2_conflict_terminal_proof(managed_result)

        assert managed_result.status == "failed"
        assert managed_result.reason["code"] == "port_lease_busy"
        assert managed_proof["reason_code"] == "port_lease_busy"
        assert managed_proof["terminal_chain"]["events"][-1] == (
            "immutable_terminal_classification"
        )
        assert managed_controller.prepare_calls == 0
        assert managed_controller.cleanup_calls == 1
        assert not managed_child_marker.exists()

        assert peer_thread.is_alive()
        assert _round_trip(port) == b"pong\n"
        assert peer_marker.read_bytes() == peer_marker_before_race

        peer_supervisor.request_stop(signal.SIGTERM)
        peer_thread.join(timeout=5)
        assert not peer_thread.is_alive()
        peer_result = _require_result(peer_outcomes)
        assert peer_result.terminal_class is TerminalClass.EXTERNAL_SIGNAL
        assert peer_result.payload["reason"] == {
            "code": "supervisor_stop_requested",
            "signal": signal.SIGTERM,
        }
        assert peer_result.payload["environment_identity"] == _identity(
            run_id=_PEER_RUN_ID,
            nonce=_PEER_NONCE,
            port=port,
        )
        peer_lease_cleanup = next(
            stage
            for stage in peer_result.payload["cleanup"]["stages"]
            if stage["stage"] == "port_lease"
        )
        assert peer_lease_cleanup == {
            "stage": "port_lease",
            "ok": True,
            "port": port,
        }
        assert peer_marker.read_bytes() == expected_peer_marker
        _assert_zero_spend(peer_result)

        reacquire_marker = tmp_path / "peer-c-reacquired.json"
        reacquire_environment = _peer_environment(
            run_id=_REACQUIRE_RUN_ID,
            nonce=_REACQUIRE_NONCE,
            port=port,
            marker=reacquire_marker,
        )
        reacquire_spec = _run_spec(
            tmp_path,
            run_id=_REACQUIRE_RUN_ID,
            nonce=_REACQUIRE_NONCE,
            port=port,
            code=_REACQUIRE_CODE,
            environment=reacquire_environment,
            timeout_seconds=5.0,
        )
        reacquire_result = ProcessSupervisor().run(reacquire_spec)

        assert reacquire_result.terminal_class is TerminalClass.COMPLETED
        assert reacquire_result.payload["reason"] == {"code": "child_completed"}
        assert reacquire_result.payload["environment_identity"] == _identity(
            run_id=_REACQUIRE_RUN_ID,
            nonce=_REACQUIRE_NONCE,
            port=port,
        )
        assert reacquire_marker.read_bytes() == _marker_bytes(
            run_id=_REACQUIRE_RUN_ID,
            nonce=_REACQUIRE_NONCE,
            port=port,
        )
        reacquire_events = [
            row["event"] for row in _journal(reacquire_result.journal_path)
        ]
        assert reacquire_events.index("port_leased") < reacquire_events.index(
            "child_started"
        )
        _assert_zero_spend(reacquire_result)

        final_lease = PortLease(port, lock_dir).acquire()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as final_listener:
                final_listener.bind((_HOST, port))
                final_listener.listen(1)
        finally:
            final_lease.release()
    finally:
        if peer_thread.is_alive():
            peer_supervisor.request_stop(signal.SIGTERM)
            peer_thread.join(timeout=5)
        if peer_thread.is_alive():
            rows = _journal(peer_spec.artifact_dir / "attempt-journal.jsonl")
            child_rows = [row for row in rows if row.get("event") == "child_started"]
            if child_rows:
                try:
                    os.killpg(int(child_rows[-1]["child_pid"]), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            peer_thread.join(timeout=5)
