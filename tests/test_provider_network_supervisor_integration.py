from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.config import get_settings
from fort_gym.bench.run import process_supervisor as supervisor_module
from fort_gym.bench.run import supervised_manager as manager_module
from fort_gym.bench.run.process_supervisor import (
    ProcessSupervisor,
    RunSpec,
    TerminalClass,
    build_provider_network_launch_plan,
)
from fort_gym.bench.run.provider_network_isolation import (
    CAPABILITY_SCHEMA,
    CLEANUP_SCHEMA,
    INSPECT_SCHEMA,
    PREPARE_SCHEMA,
    REQUIRED_HOOKS,
    CommandResult,
    ProviderNetworkIsolationController,
)
from fort_gym.bench.run.storage import RunRegistry
from fort_gym.bench.run.supervised_manager import SupervisedRunManager

_RUN_ID = "provider-network-run"
_CONTRACT_SHA256 = "c" * 64
_NONCE = "d" * 32
_PORT = 24_455


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Do not leak a monkeypatched ARTIFACTS_DIR past a provider-network test."""

    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _process_group_still_present(pid: int) -> bool:
    try:
        os.getpgid(pid)
    except ProcessLookupError:
        return False
    return True


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain_json(item) for item in value]
    return value


def _helper(tmp_path: Path, *, execute_inner: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    helper = tmp_path / "fortgym-provider-network-helper"
    # Kernel shebang parsing cannot execute an interpreter path containing spaces.
    # The helper uses only the standard library, then execs the exact inner argv.
    body = [f"#!{Path(sys.executable).resolve()}", "import os", "import sys"]
    if execute_inner:
        body.extend(
            (
                "delimiter = sys.argv.index('--')",
                "inner = sys.argv[delimiter + 1:]",
                "os.execv(inner[0], inner)",
            )
        )
    helper.write_text("\n".join(body) + "\n", encoding="utf-8")
    helper.chmod(0o700)
    return helper.resolve()


def _report(identity_sha256: str) -> dict[str, Any]:
    return {
        "schema": "fortgym.provider-network-report/v1",
        "ok": True,
        "classification": "isolated_x86_linux_provider_network_control",
        "identity_sha256": identity_sha256,
        "dns_connections": 0,
        "port_443_connections": 0,
        "poison_sink_connections": 0,
        "only_assigned_dfhack_connection": True,
        "assigned_dfhack_connections": 1,
        "denied_attempts": 6,
        "denied_dns_attempts": 3,
        "denied_443_attempts": 1,
        "denied_poison_attempts": 1,
        "negative_canary_attested": True,
        "denied_hooks": ["connect4", "connect6", "sendmsg4", "sendmsg6"],
        "lost_events": 0,
        "python_guard_attested": True,
        "kernel_enforcement_attested": True,
        "provider_calls": 0,
        "provider_cost_usd": 0.0,
        "provider_events": 0,
        "provider_tokens": 0,
    }


class FakeProviderNetworkController:
    def __init__(
        self,
        tmp_path: Path,
        *,
        lifecycle: list[str] | None = None,
        execute_inner: bool = True,
        terminal_path: Path | None = None,
        validation_error: bool = False,
        validation_overrides: Mapping[str, Any] | None = None,
        member_pids: Sequence[int] = (),
    ) -> None:
        self.run_id = _RUN_ID
        self.contract_sha256 = _CONTRACT_SHA256
        self.assigned_host = "127.0.0.1"
        self.assigned_port = _PORT
        self.identity_sha256 = "e" * 64
        self.helper_path = _helper(tmp_path, execute_inner=execute_inner)
        self.helper_sha256 = _sha256_file(self.helper_path)
        self.cgroup_path = (tmp_path / "cgroup" / self.identity_sha256).resolve()
        self.guard_attestation_path = (
            tmp_path / "control" / "python-guard-attestation.json"
        ).resolve()
        self.denials_path = (
            tmp_path / "control" / "python-network-denials.jsonl"
        ).resolve()
        self.lifecycle = lifecycle if lifecycle is not None else []
        self.terminal_path = terminal_path
        self.validation_error = validation_error
        self.validation_overrides = dict(validation_overrides or {})
        self.prepare_calls = 0
        self.cleanup_calls = 0
        self.abort_calls = 0
        self.reconcile_calls = 0
        self.validation_calls = 0
        self.residue_calls = 0
        self.member_pids = list(member_pids)

    def public_identity(self) -> Mapping[str, Any]:
        return {
            "schema": "fortgym.provider-network-manifest/v1",
            "classification": "isolated_x86_linux_provider_network_control",
            "integration_status": "process-supervisor-atomic-wrapper-v1",
            "run_id": self.run_id,
            "contract_sha256": self.contract_sha256,
            "identity_sha256": self.identity_sha256,
            "assigned_host": self.assigned_host,
            "assigned_port": self.assigned_port,
            "poison_sink_host": "203.0.113.254",
            "poison_sink_port": 44_443,
            "nonce_matched": True,
        }

    def python_guard_environment(self) -> Mapping[str, str]:
        return {
            "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
            "FORT_GYM_NETWORK_ALLOWED_HOST": self.assigned_host,
            "FORT_GYM_NETWORK_ALLOWED_PORT": str(self.assigned_port),
            "FORT_GYM_NETWORK_EVIDENCE_PATH": str(self.denials_path),
            "FORT_GYM_RUN_ID": self.run_id,
            "FORT_GYM_RUN_CONTRACT_SHA256": self.contract_sha256,
            "FORT_GYM_RUN_NONCE": _NONCE,
        }

    def enter_argv(self, child_argv: Sequence[str]) -> Sequence[str]:
        return (
            str(self.helper_path),
            "enter",
            "--cgroup",
            str(self.cgroup_path),
            "--identity-sha256",
            self.identity_sha256,
            "--require-python-policy",
            "loopback-port-only",
            "--guard-attestation",
            str(self.guard_attestation_path),
            "--",
            *child_argv,
        )

    def prepare(self) -> Mapping[str, Any]:
        self.prepare_calls += 1
        self.lifecycle.append("network_prepare")
        return {"ok": True}

    def cleanup(self) -> Mapping[str, Any]:
        self.cleanup_calls += 1
        self.lifecycle.append("network_cleanup")
        return {"ok": True, "foreign_canary_untouched": True}

    def abort(self, *, recovered: bool = False) -> Mapping[str, Any]:
        self.abort_calls += 1
        self.lifecycle.append("network_abort_recovered" if recovered else "network_abort")
        return {"ok": True, "foreign_canary_untouched": True}

    def reconcile(self) -> Mapping[str, Any]:
        self.reconcile_calls += 1
        self.lifecycle.append("network_reconcile")
        return {"ok": True, "foreign_canary_untouched": True}

    def residue(self) -> Mapping[str, Any]:
        self.residue_calls += 1
        self.lifecycle.append("network_residue")
        return {
            "schema": "fortgym.provider-network-inspect/v1",
            "ok": False,
            "identity": self.public_identity(),
            "residue": {
                "cgroup_exists": True,
                "pins_exist": True,
                "member_pids": list(self.member_pids),
            },
            "foreign_canary_untouched": True,
            "foreign_canary": {
                "pid": 999_999,
                "alive": True,
                "identity_sha256": "a" * 64,
                "cgroup": "/foreign",
            },
        }

    def validate_evidence(
        self, provider_budget: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.validation_calls += 1
        self.lifecycle.append("network_validate")
        assert provider_budget == {
            "provider_enabled": False,
            "events_seen": 0,
            "calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "max_total_tokens": 128_000,
            "max_cost_usd": 25.0,
            "requested_models": [],
            "resolved_models": [],
            "providers": [],
        }
        if self.terminal_path is not None:
            assert not self.terminal_path.exists()
        if self.validation_error:
            raise RuntimeError("poison-secret-must-not-persist")
        report = _report(self.identity_sha256)
        report.update(self.validation_overrides)
        return report


class _ActualControllerRunner:
    """Stateful privileged-helper boundary with no subprocess or network use."""

    def __init__(self, *, helper_sha256: str, object_sha256: str) -> None:
        self.helper_sha256 = helper_sha256
        self.object_sha256 = object_sha256
        self.controller: ProviderNetworkIsolationController | None = None
        self.cgroup_exists = False
        self.pins_exist = False
        self.member_pids: list[int] = []
        self.operations: list[str] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> CommandResult:
        del timeout_seconds
        command = tuple(str(item) for item in argv)
        operation = command[1]
        self.operations.append(operation)
        controller = self.controller
        assert controller is not None
        if operation == "probe":
            payload: Mapping[str, Any] = {
                "schema": CAPABILITY_SCHEMA,
                "ok": True,
                "os": "linux",
                "architecture": "x86_64",
                "cgroup_version": 2,
                "bpffs": True,
                "cgroup_bpf": True,
                "default_deny": True,
                "structured_capture": True,
                "join_before_exec": True,
                "hooks": list(REQUIRED_HOOKS),
                "helper_sha256": self.helper_sha256,
                "bpf_object_sha256": self.object_sha256,
            }
        elif operation == "prepare":
            self.cgroup_exists = True
            self.pins_exist = True
            payload = {
                "schema": PREPARE_SCHEMA,
                "ok": True,
                "identity_sha256": controller.identity_sha256,
                "cgroup_path": str(controller.cgroup_path),
                "pin_root": str(controller.pin_root),
                "policy": controller.kernel_policy,
                "hooks": list(REQUIRED_HOOKS),
                "evidence_external": True,
            }
        elif operation == "inspect":
            payload = {
                "schema": INSPECT_SCHEMA,
                "ok": True,
                "identity_sha256": controller.identity_sha256,
                "cgroup_exists": self.cgroup_exists,
                "pins_exist": self.pins_exist,
                "member_pids": list(self.member_pids),
            }
        elif operation == "cleanup":
            self.cgroup_exists = False
            self.pins_exist = False
            payload = {
                "schema": CLEANUP_SCHEMA,
                "ok": True,
                "identity_sha256": controller.identity_sha256,
                "cgroup_absent": True,
                "pins_absent": True,
            }
        else:
            raise AssertionError(
                f"wrapper-pre-exec recovery must not call helper {operation}"
            )
        return CommandResult(
            argv=command,
            returncode=0,
            stdout=json.dumps(payload, sort_keys=True),
            stderr="",
        )


class _NoSocketLease:
    def __init__(self, lifecycle: list[str]) -> None:
        self.lifecycle = lifecycle

    def acquire(self) -> _NoSocketLease:
        self.lifecycle.append("lease")
        return self

    def release(self) -> None:
        self.lifecycle.append("lease_release")


def _disable_socket_lease(
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: list[str],
) -> None:
    monkeypatch.setattr(
        supervisor_module,
        "PortLease",
        lambda _port, _lock_dir: _NoSocketLease(lifecycle),
    )


def _identity() -> dict[str, Any]:
    return {
        "schema": "fortgym.m1b-runtime-contract/v1",
        "run_id": _RUN_ID,
        "contract_sha256": _CONTRACT_SHA256,
        "rpc": {"host": "127.0.0.1", "port": _PORT, "nonce": _NONCE},
    }


def _spec(
    tmp_path: Path,
    argv: Sequence[str],
    *,
    artifact_dir: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> RunSpec:
    environment = {
        "FORT_GYM_RUN_ID": _RUN_ID,
        "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
        "FORT_GYM_RUN_NONCE": _NONCE,
        "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
        "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
        "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
        "FORT_GYM_NETWORK_EVIDENCE_PATH": str(tmp_path / "legacy-denials.jsonl"),
        **dict(extra_env or {}),
    }
    return RunSpec(
        run_id=_RUN_ID,
        argv=tuple(argv),
        artifact_dir=artifact_dir or tmp_path / "attempt",
        env=environment,
        env_allowlist=tuple(environment),
        scripted=True,
        provider_enabled=False,
        timeout_seconds=2.0,
        term_grace_seconds=0.1,
        poll_interval_seconds=0.01,
        trace_path=tmp_path / "trace.jsonl",
        port=_PORT,
        port_lock_dir=tmp_path / "leases",
        environment_identity=_identity(),
        runtime_cleanup_required=artifact_dir is not None,
    )


def _journal(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_supervisor_uses_exact_wrapper_guard_and_preterminal_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    _disable_socket_lease(monkeypatch, lifecycle)
    dump_path = tmp_path / "child-environment.json"
    code = (
        "import json,os;"
        "names=[name for name in os.environ if name.startswith('FORT_GYM_')];"
        "open(os.environ['CHILD_DUMP'],'w',encoding='utf-8').write("
        "json.dumps({name:os.environ[name] for name in names},sort_keys=True))"
    )
    spec = _spec(
        tmp_path,
        (sys.executable, "-c", code),
        extra_env={"CHILD_DUMP": str(dump_path)},
    )
    controller = FakeProviderNetworkController(
        tmp_path,
        lifecycle=lifecycle,
        terminal_path=spec.artifact_dir / "terminal.json",
    )

    result = ProcessSupervisor().run(
        spec,
        prepare=lambda: lifecycle.append("runtime_prepare") or {"ok": True},
        cleanup=lambda: lifecycle.append("runtime_cleanup") or {"ok": True},
        provider_network=controller,
    )

    assert result.terminal_class is TerminalClass.COMPLETED
    assert lifecycle == [
        "lease",
        "network_prepare",
        "runtime_prepare",
        "network_cleanup",
        "network_validate",
        "runtime_cleanup",
        "lease_release",
    ]
    child_environment = json.loads(dump_path.read_text(encoding="utf-8"))
    assert child_environment["FORT_GYM_NETWORK_EVIDENCE_PATH"] == str(
        controller.denials_path
    )
    assert child_environment["FORT_GYM_DISABLE_DOTENV"] == "1"
    assert result.payload["provider_network"]["validation"]["provider_calls"] == 0
    rows = _journal(result.journal_path)
    launch = next(
        row["launch"]
        for row in rows
        if row["event"] == "provider_network_prepare_started"
    )
    child = next(row for row in rows if row["event"] == "child_started")
    assert launch["inner_argv"] == list(spec.argv)
    assert launch["wrapper_argv"][0] == str(controller.helper_path)
    assert child["launch_argv_sha256"] == launch["wrapper_argv_sha256"]
    assert _NONCE not in json.dumps(launch, sort_keys=True)
    events = [row["event"] for row in rows]
    assert events.index("port_leased") < events.index(
        "provider_network_prepare_started"
    )
    assert events.index("provider_network_validated") < events.index(
        "terminal_pending"
    )


def test_runtime_prepare_failure_aborts_network_without_launch_or_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    _disable_socket_lease(monkeypatch, lifecycle)
    child_marker = tmp_path / "child-started"
    spec = _spec(
        tmp_path,
        (
            sys.executable,
            "-c",
            f"from pathlib import Path;Path({str(child_marker)!r}).touch()",
        ),
    )
    controller = FakeProviderNetworkController(tmp_path, lifecycle=lifecycle)

    def fail_prepare() -> None:
        lifecycle.append("runtime_prepare")
        raise RuntimeError("synthetic runtime prepare failure")

    result = ProcessSupervisor().run(
        spec,
        prepare=fail_prepare,
        cleanup=lambda: lifecycle.append("runtime_cleanup") or {"ok": True},
        provider_network=controller,
    )

    assert result.terminal_class is TerminalClass.PREPARE_FAILURE
    assert result.payload["reason"]["code"] == "runtime_prepare_failed"
    assert result.payload["cleanup"]["ok"] is True
    assert not child_marker.exists()
    assert controller.abort_calls == 1
    assert controller.cleanup_calls == controller.validation_calls == 0
    assert lifecycle == [
        "lease",
        "network_prepare",
        "runtime_prepare",
        "network_abort",
        "runtime_cleanup",
        "lease_release",
    ]


def test_validation_failure_is_redacted_and_precedes_terminal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    _disable_socket_lease(monkeypatch, lifecycle)
    spec = _spec(tmp_path, (sys.executable, "-c", "pass"))
    controller = FakeProviderNetworkController(
        tmp_path,
        lifecycle=lifecycle,
        terminal_path=spec.artifact_dir / "terminal.json",
        validation_error=True,
    )

    result = ProcessSupervisor().run(
        spec,
        cleanup=lambda: lifecycle.append("runtime_cleanup") or {"ok": True},
        provider_network=controller,
    )

    assert result.terminal_class is TerminalClass.CLEANUP_FAILURE
    assert result.payload["cleanup"]["ok"] is False
    assert "poison-secret-must-not-persist" not in result.terminal_path.read_text(
        encoding="utf-8"
    )
    assert lifecycle.index("network_cleanup") < lifecycle.index("network_validate")
    assert lifecycle.index("network_validate") < lifecycle.index("runtime_cleanup")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dns_connections", False, "zero external activity"),
        ("provider_calls", False, "zero external activity"),
        ("provider_cost_usd", False, "zero provider cost"),
        ("provider_cost_usd", float("nan"), "zero provider cost"),
        ("assigned_dfhack_connections", True, "counters are invalid"),
        ("assigned_dfhack_connections", 0, "lacks the assigned"),
        ("denied_attempts", False, "counters are invalid"),
        ("denied_dns_attempts", 0, "negative canary denials"),
        ("negative_canary_attested", False, "report is contradictory"),
    ],
)
def test_terminal_report_rejects_bool_nan_and_zero_count_contradictions(
    field: str,
    value: Any,
    message: str,
) -> None:
    report = _report("e" * 64)
    report[field] = value

    with pytest.raises(
        supervisor_module.ProviderNetworkPrepareError,
        match=message,
    ):
        supervisor_module._validated_provider_network_report(
            report,
            identity_sha256="e" * 64,
        )


class FakeRuntimeController:
    def __init__(self, lifecycle: list[str]) -> None:
        self.lifecycle = lifecycle
        self.reconcile_calls = 0

    def prepare(self) -> Mapping[str, Any]:
        return {"ok": True}

    def cleanup(self) -> Mapping[str, Any]:
        return {"ok": True}

    def reconcile(self) -> Mapping[str, Any]:
        self.reconcile_calls += 1
        self.lifecycle.append("runtime_reconcile")
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


def _worker_argv(tmp_path: Path) -> tuple[str, ...]:
    config_path = (tmp_path / "experiment.json").resolve()
    config_path.write_text("{}\n", encoding="utf-8")
    return (
        str(Path(sys.executable).resolve()),
        "-m",
        "fort_gym.bench.cli",
        "experiment",
        str(config_path),
        "--external-run-id",
        _RUN_ID,
    )


def _recovery_rows(
    *,
    plan: Any,
    owner_pid: int,
    child_pid: int,
) -> list[dict[str, Any]]:
    common = {
        "schema": "fortgym.process-supervisor-attempt/v1",
        "run_id": _RUN_ID,
        "supervisor_pid": owner_pid,
    }
    return [
        {"event": "attempt_started", "environment_identity": _identity(), **common},
        {
            "event": "provider_network_prepare_started",
            "launch": _plain_json(plan.evidence),
            **common,
        },
        {
            "event": "provider_network_prepared",
            "launch_argv_sha256": plan.evidence["wrapper_argv_sha256"],
            "inner_argv_sha256": plan.evidence["inner_argv_sha256"],
            "provider_network_identity_sha256": plan.evidence[
                "provider_network_identity"
            ]["identity_sha256"],
            **common,
        },
        {
            "event": "provider_network_launch_intent",
            "launch_argv_sha256": plan.evidence["wrapper_argv_sha256"],
            "inner_argv_sha256": plan.evidence["inner_argv_sha256"],
            "provider_network_identity_sha256": plan.evidence[
                "provider_network_identity"
            ]["identity_sha256"],
            "contract_sha256": _CONTRACT_SHA256,
            "nonce_sha256": hashlib.sha256(_NONCE.encode()).hexdigest(),
            **common,
        },
        {
            "event": "child_started",
            "child_pid": child_pid,
            "launch_mode": "cgroup-bpf-join-before-exec",
            "launch_argv_sha256": plan.evidence["wrapper_argv_sha256"],
            "inner_argv_sha256": plan.evidence["inner_argv_sha256"],
            "provider_network_identity_sha256": plan.evidence[
                "provider_network_identity"
            ]["identity_sha256"],
            **common,
        },
    ]


def _write_recovery_control(
    control_root: Path,
    *,
    owner_pid: int,
    rows: Sequence[Mapping[str, Any]],
) -> Path:
    run_dir = control_root / _RUN_ID
    attempt_dir = run_dir / "attempts" / "attempt-0001"
    attempt_dir.mkdir(parents=True)
    environment_identity = _identity()
    environment_identity_sha256 = hashlib.sha256(
        json.dumps(
            _plain_json(environment_identity),
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    (run_dir / "owner.json").write_text(
        json.dumps(
            {
                "schema": "fortgym.supervised-manager-owner/v1",
                "run_id": _RUN_ID,
                "state": "active",
                "manager_pid": owner_pid,
                "manager_start_ticks": 1,
                "identity_bound": True,
                "contract_sha256": _CONTRACT_SHA256,
                "nonce_sha256": hashlib.sha256(_NONCE.encode("ascii")).hexdigest(),
                "environment_identity_sha256": environment_identity_sha256,
                "observed_registry_status": "running",
                "attempt_dir": str(attempt_dir.resolve()),
                "updated_at": "2026-08-16T20:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "attempt-journal.jsonl").write_text(
        "".join(json.dumps(dict(row), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return attempt_dir


def test_dead_owner_reconciles_exact_network_after_reap_before_runtime_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts_root))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 0, tzinfo=UTC),
    )

    control_root = tmp_path / "control-root"
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = _spec(
        tmp_path,
        _worker_argv(tmp_path),
        artifact_dir=attempt_dir,
    )
    network = FakeProviderNetworkController(
        tmp_path / "network-controller",
        lifecycle=lifecycle,
        execute_inner=False,
    )
    plan = build_provider_network_launch_plan(spec, network)
    owner_pid = 999_991
    rows = _recovery_rows(plan=plan, owner_pid=owner_pid, child_pid=999_992)
    _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
    runtime = FakeRuntimeController(lifecycle)

    def reap(expected: Any, *, identity_probe: Any) -> Mapping[str, Any]:
        del identity_probe
        assert _plain_json(expected.provider_network_launch) == _plain_json(
            plan.evidence
        )
        lifecycle.append("harness_reap")
        return {
            "ok": True,
            "child_pid": expected.child_pid,
            "absent": True,
            "foreign_canary_untouched": True,
        }

    monkeypatch.setattr(manager_module, "_reap_process_group", reap)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=lambda _record, _attempt, _controller: spec,
        provider_network_controller_factory=(
            lambda _record, _run_dir, _runtime, _spec: network
        ),
        ownership_probe=lambda _owner: False,
    )

    first = manager.reconcile(record.run_id)
    second = manager.reconcile(record.run_id)

    assert first.finalized is True
    assert first.status == "failed"
    assert second.action == "already_terminal"
    assert lifecycle == [
        "harness_reap",
        "network_reconcile",
        "network_validate",
        "runtime_reconcile",
    ]
    assert network.reconcile_calls == network.validation_calls == 1
    assert runtime.reconcile_calls == 1
    provider_recovery = first.reason["reconciliation"]["provider_network"]
    assert provider_recovery == {
        "ok": True,
        "mode": "launched_reconcile",
        "identity_sha256": network.identity_sha256,
        "foreign_canary_untouched": True,
        "validated": True,
    }
    stages = first.reason["reconciliation"]
    assert stages["harness_process_group"]["ok"] is True
    loaded = registry.get(_RUN_ID)
    assert loaded is not None and loaded.status == "failed"


def test_dead_owner_prelaunch_crash_retains_network_journal_and_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 1, tzinfo=UTC),
    )

    control_root = tmp_path / "control-root"
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = _spec(tmp_path, _worker_argv(tmp_path), artifact_dir=attempt_dir)
    network = FakeProviderNetworkController(
        tmp_path / "network-controller",
        lifecycle=lifecycle,
        execute_inner=False,
    )
    plan = build_provider_network_launch_plan(spec, network)
    owner_pid = 999_981
    # The durable launch identity exists, but the owner died after helper mutation
    # and before provider_network_prepared/child_started could be appended.
    rows = _recovery_rows(plan=plan, owner_pid=owner_pid, child_pid=999_982)[:2]
    _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
    runtime = FakeRuntimeController(lifecycle)

    def reap(expected: Any, *, identity_probe: Any) -> Mapping[str, Any]:
        del identity_probe
        assert expected is None
        lifecycle.append("harness_reap")
        return {"ok": True, "skipped": True, "reason": "child_not_started"}

    monkeypatch.setattr(manager_module, "_reap_process_group", reap)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=lambda _record, _attempt, _controller: spec,
        provider_network_controller_factory=(
            lambda _record, _run_dir, _runtime, _spec: network
        ),
        ownership_probe=lambda _owner: False,
    )

    result = manager.reconcile(record.run_id)

    assert result.finalized is True
    assert lifecycle == [
        "harness_reap",
        "network_abort_recovered",
        "runtime_reconcile",
    ]
    assert network.abort_calls == 1
    assert network.reconcile_calls == network.validation_calls == 0
    assert result.reason["reconciliation"]["provider_network"] == {
        "ok": True,
        "mode": "prelaunch_abort",
        "identity_sha256": network.identity_sha256,
        "foreign_canary_untouched": True,
    }


def test_dead_owner_reaps_joined_launch_intent_before_network_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 1, tzinfo=UTC),
    )
    control_root = tmp_path / "control-root"
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = _spec(tmp_path, _worker_argv(tmp_path), artifact_dir=attempt_dir)
    owned_pid = 999_961
    foreign_pid = 999_962
    same_group_outside_pid = 999_963
    network = FakeProviderNetworkController(
        tmp_path / "network-controller",
        lifecycle=lifecycle,
        execute_inner=False,
        member_pids=(owned_pid,),
    )
    plan = build_provider_network_launch_plan(spec, network)
    owner_pid = 999_960
    rows = _recovery_rows(
        plan=plan,
        owner_pid=owner_pid,
        child_pid=owned_pid,
    )[:-1]
    _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
    runtime = FakeRuntimeController(lifecycle)
    owned_identity = {
        "cmdline": tuple(plan.argv),
        "environment": {
            "FORT_GYM_RUN_ID": _RUN_ID,
            "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
            "FORT_GYM_RUN_NONCE": _NONCE,
            "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
            "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
            "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
            "FORT_GYM_NETWORK_EVIDENCE_PATH": str(network.denials_path),
        },
        "executable_path": str(network.helper_path),
        "executable_sha256": network.helper_sha256,
    }
    foreign_identity = {
        "cmdline": ("/usr/bin/foreign-canary",),
        "environment": {"FORT_GYM_RUN_ID": "foreign-run"},
        "executable_path": "/usr/bin/foreign-canary",
        "executable_sha256": "b" * 64,
    }
    same_group_outside_identity = {
        "cmdline": (sys.executable, "-c", "same-group-outside-cgroup"),
        "environment": dict(owned_identity["environment"]),
    }
    probes: list[int] = []

    def identity_probe(pid: int) -> Mapping[str, Any]:
        probes.append(pid)
        if pid == owned_pid:
            return owned_identity
        if pid == foreign_pid:
            return foreign_identity
        if pid == same_group_outside_pid:
            return same_group_outside_identity
        raise ProcessLookupError(pid)

    def reap(expected: Any, *, identity_probe: Any) -> Mapping[str, Any]:
        if expected is None:
            return {"ok": True, "skipped": True, "reason": "child_not_started"}
        assert expected.child_pid == owned_pid
        assert identity_probe(owned_pid) == owned_identity
        lifecycle.append("intent_reap")
        network.member_pids.clear()
        return {
            "ok": True,
            "child_pid": owned_pid,
            "absent": True,
            "foreign_canary_untouched": True,
        }

    monkeypatch.setattr(manager_module, "_reap_process_group", reap)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=lambda _record, _attempt, _controller: spec,
        provider_network_controller_factory=(
            lambda _record, _run_dir, _runtime, _spec: network
        ),
        ownership_probe=lambda _owner: False,
        process_identity_probe=identity_probe,
        process_ids_probe=lambda: (
            owned_pid,
            foreign_pid,
            same_group_outside_pid,
        ),
        process_group_probe=lambda pid: (
            owned_pid if pid == same_group_outside_pid else pid
        ),
    )

    first = manager.reconcile(record.run_id)
    second = manager.reconcile(record.run_id)

    assert first.status == "failed"
    assert second.action == "already_terminal"
    assert lifecycle == [
        "network_residue",
        "intent_reap",
        "network_residue",
        "network_abort_recovered",
        "runtime_reconcile",
    ]
    assert set(probes) == {owned_pid, foreign_pid, same_group_outside_pid}
    provider = first.reason["reconciliation"]["provider_network"]
    assert provider["mode"] == "launch_intent_wrapper_reaped_abort"
    assert provider["launch_intent"]["intent_process_reaped"] is True
    assert provider["launch_intent"]["child_pid"] == owned_pid
    assert provider["launch_intent"]["same_group_outside_cgroup_pids"] == [
        same_group_outside_pid
    ]
    assert provider["launch_intent"]["command_mode"] == (
        "provider_network_wrapper_pre_exec"
    )
    assert network.abort_calls == 1
    assert network.reconcile_calls == network.validation_calls == 0


def test_dead_owner_inner_exec_before_child_journal_reaps_group_and_validates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 1, tzinfo=UTC),
    )
    control_root = tmp_path / "control-root"
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = _spec(tmp_path, _worker_argv(tmp_path), artifact_dir=attempt_dir)
    leader_pid = 999_941
    descendant_pid = 999_942
    foreign_pid = 999_943
    network = FakeProviderNetworkController(
        tmp_path / "network-controller",
        lifecycle=lifecycle,
        member_pids=(leader_pid, descendant_pid),
    )
    plan = build_provider_network_launch_plan(spec, network)
    owner_pid = 999_940
    rows = _recovery_rows(
        plan=plan,
        owner_pid=owner_pid,
        child_pid=leader_pid,
    )[:-1]
    _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
    runtime = FakeRuntimeController(lifecycle)
    run_environment = {
        "FORT_GYM_RUN_ID": _RUN_ID,
        "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
        "FORT_GYM_RUN_NONCE": _NONCE,
        "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
        "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
        "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
        "FORT_GYM_NETWORK_EVIDENCE_PATH": str(network.denials_path),
    }
    identities = {
        leader_pid: {
            "cmdline": tuple(plan.evidence["inner_argv"]),
            "environment": run_environment,
        },
        descendant_pid: {
            "cmdline": (sys.executable, "-c", "same-run-descendant"),
            "environment": run_environment,
        },
        foreign_pid: {
            "cmdline": ("/usr/bin/foreign-canary",),
            "environment": {"FORT_GYM_RUN_ID": "foreign-run"},
        },
    }
    reaped: list[int] = []

    def identity_probe(pid: int) -> Mapping[str, Any]:
        return identities[pid]

    def reap(expected: Any, *, identity_probe: Any) -> Mapping[str, Any]:
        assert expected is not None
        assert expected.child_pid == leader_pid
        assert identity_probe(leader_pid) == identities[leader_pid]
        reaped.append(expected.child_pid)
        lifecycle.append("intent_reap")
        network.member_pids.clear()
        return {
            "ok": True,
            "child_pid": leader_pid,
            "absent": True,
            "foreign_canary_untouched": True,
        }

    monkeypatch.setattr(manager_module, "_reap_process_group", reap)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=lambda _record, _attempt, _controller: spec,
        provider_network_controller_factory=(
            lambda _record, _run_dir, _runtime, _spec: network
        ),
        ownership_probe=lambda _owner: False,
        process_identity_probe=identity_probe,
        process_ids_probe=lambda: (leader_pid, descendant_pid, foreign_pid),
        process_group_probe=lambda pid: (
            leader_pid if pid in {leader_pid, descendant_pid} else pid
        ),
    )

    first = manager.reconcile(record.run_id)
    second = manager.reconcile(record.run_id)

    assert first.finalized is True
    assert first.reason["code"] == "supervisor_lost"
    assert second.action == "already_terminal"
    assert reaped == [leader_pid]
    assert foreign_pid not in reaped
    assert lifecycle == [
        "network_residue",
        "intent_reap",
        "network_residue",
        "network_reconcile",
        "network_validate",
        "runtime_reconcile",
    ]
    provider = first.reason["reconciliation"]["provider_network"]
    assert provider["ok"] is True
    assert provider["mode"] == "launch_intent_inner_reaped_reconcile"
    assert provider["validated"] is True
    assert provider["foreign_canary_untouched"] is True
    assert provider["launch_intent"]["command_mode"] == (
        "provider_network_inner_exec"
    )
    assert provider["launch_intent"]["cgroup_member_pids"] == [
        leader_pid,
        descendant_pid,
    ]
    assert provider["launch_intent"]["additional_group_member_pids"] == [
        descendant_pid
    ]
    assert network.abort_calls == 0
    assert network.reconcile_calls == network.validation_calls == 1


def test_dead_owner_wrapper_pre_exec_uses_actual_controller_abort_without_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 1, tzinfo=UTC),
    )
    control_root = (tmp_path / "control-root").resolve()
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = _spec(tmp_path, _worker_argv(tmp_path), artifact_dir=attempt_dir)
    helper = _helper(tmp_path / "actual-helper", execute_inner=False)
    bpf_object = (tmp_path / "provider-network.bpf.o").resolve()
    bpf_object.write_bytes(b"static fake BPF object\n")
    helper_sha256 = _sha256_file(helper)
    object_sha256 = _sha256_file(bpf_object)
    runner = _ActualControllerRunner(
        helper_sha256=helper_sha256,
        object_sha256=object_sha256,
    )
    canary = {
        "pid": 999_949,
        "alive": True,
        "identity_sha256": "a" * 64,
        "cgroup": "/foreign.slice/canary.scope",
    }
    network = ProviderNetworkIsolationController(
        run_id=_RUN_ID,
        contract_sha256=_CONTRACT_SHA256,
        nonce=_NONCE,
        assigned_port=_PORT,
        control_root=control_root,
        gameplay_workspace=(tmp_path / "artifacts" / _RUN_ID).resolve(),
        helper_path=helper,
        helper_sha256=helper_sha256,
        bpf_object_path=bpf_object,
        bpf_object_sha256=object_sha256,
        cgroup_root=(tmp_path / "cgroup-root").resolve(),
        bpffs_root=(tmp_path / "bpffs-root").resolve(),
        foreign_canary_pid=canary["pid"],
        foreign_canary_probe=lambda _pid: dict(canary),
        runner=runner,
    )
    runner.controller = network
    network.prepare()
    owned_pid = 999_948
    runner.member_pids = [owned_pid]
    plan = build_provider_network_launch_plan(spec, network)
    owner_pid = 999_947
    rows = _recovery_rows(
        plan=plan,
        owner_pid=owner_pid,
        child_pid=owned_pid,
    )[:-1]
    _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
    runtime = FakeRuntimeController([])
    observed_identity = {
        "cmdline": tuple(plan.argv),
        "environment": {
            "FORT_GYM_RUN_ID": _RUN_ID,
            "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
            "FORT_GYM_RUN_NONCE": _NONCE,
            "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
            "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
            "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
            "FORT_GYM_NETWORK_EVIDENCE_PATH": str(network.python_denials_path),
        },
        "executable_path": str(helper),
        "executable_sha256": helper_sha256,
    }

    def reap(expected: Any, *, identity_probe: Any) -> Mapping[str, Any]:
        if expected is None:
            return {"ok": True, "skipped": True, "reason": "child_not_started"}
        assert expected.child_pid == owned_pid
        assert identity_probe(owned_pid) == observed_identity
        runner.member_pids.clear()
        return {
            "ok": True,
            "child_pid": owned_pid,
            "absent": True,
            "foreign_canary_untouched": True,
        }

    monkeypatch.setattr(manager_module, "_reap_process_group", reap)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=lambda _record, _attempt, _controller: spec,
        provider_network_controller_factory=(
            lambda _record, _run_dir, _runtime, _spec: network
        ),
        ownership_probe=lambda _owner: False,
        process_identity_probe=lambda pid: (
            observed_identity if pid == owned_pid else (_ for _ in ()).throw(
                ProcessLookupError(pid)
            )
        ),
        process_ids_probe=lambda: (owned_pid,),
        process_group_probe=lambda pid: pid,
    )

    result = manager.reconcile(_RUN_ID)

    assert result.finalized is True
    assert result.reason["reconciliation"]["provider_network"]["mode"] == (
        "launch_intent_wrapper_reaped_abort"
    )
    assert "snapshot" not in runner.operations
    assert runner.operations == [
        "probe",
        "prepare",
        "inspect",
        "inspect",
        "inspect",
        "cleanup",
        "inspect",
    ]
    assert not runner.cgroup_exists
    assert not runner.pins_exist
    assert json.loads(network.manifest_path.read_text())["state"] == "cleaned"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_dead_owner_launch_intent_reaps_real_resistant_process_group_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 1, tzinfo=UTC),
    )
    descendant_path = tmp_path / "descendant.pid"
    descendant_program = (
        "import signal,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "time.sleep(60)"
    )
    leader_program = (
        "import os,signal,subprocess,sys,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]]);"
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);"
        "os.write(fd,str(child.pid).encode());os.fsync(fd);os.close(fd);"
        "parent=os.open(os.path.dirname(sys.argv[1]),os.O_RDONLY);"
        "os.fsync(parent);os.close(parent);"
        "time.sleep(60)"
    )
    target = subprocess.Popen(
        [
            sys.executable,
            "-c",
            leader_program,
            str(descendant_path),
            descendant_program,
        ],
        start_new_session=True,
    )
    foreign_canary = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    descendant_pid: int | None = None
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not descendant_path.exists():
            time.sleep(0.01)
        assert descendant_path.exists()
        descendant_pid = int(descendant_path.read_text(encoding="utf-8"))
        assert os.getpgid(target.pid) == target.pid
        assert os.getpgid(descendant_pid) == target.pid

        control_root = tmp_path / "control-root"
        attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
        spec = _spec(tmp_path, _worker_argv(tmp_path), artifact_dir=attempt_dir)

        class ProcessAwareNetwork(FakeProviderNetworkController):
            def residue(self) -> Mapping[str, Any]:
                self.member_pids = [
                    pid
                    for pid in self.member_pids
                    if _process_group_still_present(pid)
                ]
                return super().residue()

        network = ProcessAwareNetwork(
            tmp_path / "network-controller",
            lifecycle=lifecycle,
            execute_inner=False,
            member_pids=(target.pid, descendant_pid),
        )
        plan = build_provider_network_launch_plan(spec, network)
        owner_pid = 999_946
        rows = _recovery_rows(
            plan=plan,
            owner_pid=owner_pid,
            child_pid=target.pid,
        )[:-1]
        _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
        runtime = FakeRuntimeController(lifecycle)
        owned_identity = {
            "cmdline": tuple(plan.argv),
            "environment": {
                "FORT_GYM_RUN_ID": _RUN_ID,
                "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
                "FORT_GYM_RUN_NONCE": _NONCE,
                "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
                "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
                "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
                "FORT_GYM_NETWORK_EVIDENCE_PATH": str(network.denials_path),
            },
            "executable_path": str(network.helper_path),
            "executable_sha256": network.helper_sha256,
        }

        def identity_probe(pid: int) -> Mapping[str, Any]:
            if pid == target.pid:
                return owned_identity
            if pid == descendant_pid:
                return {
                    "cmdline": (sys.executable, "-c", "resistant-descendant"),
                    "environment": dict(owned_identity["environment"]),
                }
            if pid == foreign_canary.pid:
                return {
                    "cmdline": (sys.executable, "-c", "foreign-canary"),
                    "environment": {"FORT_GYM_RUN_ID": "foreign-run"},
                }
            raise ProcessLookupError(pid)

        original_terminalize = registry.record_terminal_failure

        def record_terminal_failure(*args: Any, **kwargs: Any) -> Any:
            assert "network_abort_recovered" in lifecycle
            assert "runtime_reconcile" in lifecycle
            lifecycle.append("registry_terminal")
            return original_terminalize(*args, **kwargs)

        monkeypatch.setattr(
            registry, "record_terminal_failure", record_terminal_failure
        )
        manager = SupervisedRunManager(
            registry=registry,
            control_root=control_root,
            runtime_controller_factory=lambda _record, _run_dir: runtime,
            contract_factory=lambda _record, _attempt, _controller: spec,
            provider_network_controller_factory=(
                lambda _record, _run_dir, _runtime, _spec: network
            ),
            ownership_probe=lambda _owner: False,
            process_identity_probe=identity_probe,
            process_ids_probe=lambda: (
                target.pid,
                descendant_pid,
                foreign_canary.pid,
            ),
        )

        first = manager.reconcile(_RUN_ID)
        second = manager.reconcile(_RUN_ID)

        launch_reap = first.reason["reconciliation"]["provider_network"][
            "launch_intent"
        ]["reap"]
        assert first.finalized is True
        assert second.action == "already_terminal"
        assert launch_reap["term_sent"] is True
        assert launch_reap["kill_sent"] is True
        assert launch_reap["absent"] is True
        launch_intent = first.reason["reconciliation"]["provider_network"][
            "launch_intent"
        ]
        assert launch_intent["additional_group_member_pids"] == [descendant_pid]
        assert network.member_pids == []
        assert network.abort_calls == 1
        assert network.reconcile_calls == network.validation_calls == 0
        assert lifecycle.index("network_abort_recovered") < lifecycle.index(
            "registry_terminal"
        )
        assert lifecycle.index("runtime_reconcile") < lifecycle.index(
            "registry_terminal"
        )
        assert foreign_canary.poll() is None
        with pytest.raises(ProcessLookupError):
            os.kill(descendant_pid, 0)
    finally:
        for process in (target, foreign_canary):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except (ChildProcessError, subprocess.TimeoutExpired):
                pass
        if descendant_pid is not None:
            try:
                os.kill(descendant_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("member_kind", ["foreign", "different_process_group"])
def test_dead_owner_launch_intent_refuses_unowned_cgroup_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_kind: str,
) -> None:
    lifecycle: list[str] = []
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 1, tzinfo=UTC),
    )
    control_root = tmp_path / "control-root"
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = _spec(tmp_path, _worker_argv(tmp_path), artifact_dir=attempt_dir)
    leader_pid = 999_951
    other_pid = 999_952
    network = FakeProviderNetworkController(
        tmp_path / "network-controller",
        lifecycle=lifecycle,
        execute_inner=False,
        member_pids=(leader_pid, other_pid),
    )
    plan = build_provider_network_launch_plan(spec, network)
    owner_pid = 999_950
    rows = _recovery_rows(
        plan=plan,
        owner_pid=owner_pid,
        child_pid=leader_pid,
    )[:-1]
    _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
    runtime = FakeRuntimeController(lifecycle)
    reaped: list[int] = []

    def reap(expected: Any, *, identity_probe: Any) -> Mapping[str, Any]:
        del identity_probe
        if expected is None:
            return {"ok": True, "skipped": True, "reason": "child_not_started"}
        reaped.append(expected.child_pid)
        return {"ok": True}

    monkeypatch.setattr(manager_module, "_reap_process_group", reap)
    leader_identity = {
        "cmdline": tuple(plan.argv),
        "environment": {
            "FORT_GYM_RUN_ID": _RUN_ID,
            "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
            "FORT_GYM_RUN_NONCE": _NONCE,
            "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
            "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
            "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
            "FORT_GYM_NETWORK_EVIDENCE_PATH": str(network.denials_path),
        },
        "executable_path": str(network.helper_path),
        "executable_sha256": network.helper_sha256,
    }
    other_identity = (
        {
            "cmdline": ("/usr/bin/foreign-canary",),
            "environment": {"FORT_GYM_RUN_ID": "foreign-run"},
        }
        if member_kind == "foreign"
        else {
            "cmdline": (sys.executable, "-c", "same-run-different-group"),
            "environment": dict(leader_identity["environment"]),
        }
    )

    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=lambda _record, _attempt, _controller: spec,
        provider_network_controller_factory=(
            lambda _record, _run_dir, _runtime, _spec: network
        ),
        ownership_probe=lambda _owner: False,
        process_identity_probe=lambda pid: (
            leader_identity if pid == leader_pid else other_identity
        ),
        process_ids_probe=lambda: (leader_pid, other_pid),
        process_group_probe=lambda pid: pid,
    )

    result = manager.reconcile(record.run_id)

    assert result.status == "failed"
    assert reaped == []
    assert network.abort_calls == network.reconcile_calls == 0
    prior = result.reason["prior_terminal_reason"]
    provider = prior["reconciliation"]["provider_network"]
    assert provider["ok"] is False
    assert result.reason["code"] == "parent_cleanup_failed"
    assert lifecycle == ["network_residue", "runtime_reconcile"]


def test_dead_owner_recovery_rejects_forbidden_network_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()  # type: ignore[attr-defined]
    registry = RunRegistry(db_path=tmp_path / "runs.sqlite3")
    record = registry.create(
        run_id=_RUN_ID,
        backend="mock",
        model="fake",
        max_steps=1,
        ticks_per_step=1,
    )
    assert registry.claim_pending_run(
        _RUN_ID,
        started_at=datetime(2026, 8, 16, 20, 2, tzinfo=UTC),
    )

    control_root = tmp_path / "control-root"
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = _spec(tmp_path, _worker_argv(tmp_path), artifact_dir=attempt_dir)
    network = FakeProviderNetworkController(
        tmp_path / "network-controller",
        lifecycle=lifecycle,
        execute_inner=False,
        validation_overrides={"dns_connections": 1},
    )
    plan = build_provider_network_launch_plan(spec, network)
    owner_pid = 999_971
    rows = _recovery_rows(plan=plan, owner_pid=owner_pid, child_pid=999_972)
    _write_recovery_control(control_root, owner_pid=owner_pid, rows=rows)
    runtime = FakeRuntimeController(lifecycle)

    def reap(expected: Any, *, identity_probe: Any) -> Mapping[str, Any]:
        del identity_probe
        assert expected is not None
        lifecycle.append("harness_reap")
        return {"ok": True, "child_pid": expected.child_pid, "absent": True}

    monkeypatch.setattr(manager_module, "_reap_process_group", reap)
    manager = SupervisedRunManager(
        registry=registry,
        control_root=control_root,
        runtime_controller_factory=lambda _record, _run_dir: runtime,
        contract_factory=lambda _record, _attempt, _controller: spec,
        provider_network_controller_factory=(
            lambda _record, _run_dir, _runtime, _spec: network
        ),
        ownership_probe=lambda _owner: False,
    )

    result = manager.reconcile(record.run_id)

    assert result.finalized is True
    assert lifecycle == [
        "harness_reap",
        "network_reconcile",
        "network_validate",
        "runtime_reconcile",
    ]
    assert result.reason["code"] == "parent_cleanup_failed"
    prior = result.reason["prior_terminal_reason"]
    assert prior["code"] == "supervisor_lost"
    provider_recovery = prior["reconciliation"]["provider_network"]
    assert provider_recovery["ok"] is False
    assert provider_recovery["error"]["type"] == "ProviderNetworkPrepareError"
    assert prior["reconciliation"]["ok"] is False


def test_durable_wrapper_identity_accepts_only_inner_or_pinned_wrapper(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, _worker_argv(tmp_path))
    network = FakeProviderNetworkController(
        tmp_path / "network",
        execute_inner=False,
    )
    plan = build_provider_network_launch_plan(spec, network)
    rows = _recovery_rows(plan=plan, owner_pid=555, child_pid=777)
    journal = manager_module._provider_network_launch_from_journal(
        rows,
        _RUN_ID,
        owner_manager_pid=555,
    )
    assert journal is not None
    expected = manager_module._child_identity_from_journal(
        rows,
        _RUN_ID,
        owner_manager_pid=555,
        provider_network=journal,
    )
    assert expected is not None
    live_environment = {
        "FORT_GYM_RUN_ID": _RUN_ID,
        "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
        "FORT_GYM_RUN_NONCE": _NONCE,
        "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
        "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
        "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
        "FORT_GYM_NETWORK_EVIDENCE_PATH": str(network.denials_path),
    }

    verified = manager_module._verify_live_process_identity(
        expected,
        identity_probe=lambda _pid: {
            "cmdline": tuple(spec.argv),
            "environment": live_environment,
        },
    )

    encoded = json.dumps(verified, sort_keys=True)
    assert verified["provider_network"]["guard_attested"] is True
    assert _NONCE not in encoded
    assert str(network.denials_path) not in encoded

    with pytest.raises(
        manager_module.ControlEvidenceError,
        match="wrapper executable is not pinned",
    ):
        manager_module._verify_live_process_identity(
            expected,
            identity_probe=lambda _pid: {
                "cmdline": tuple(plan.argv),
                "environment": live_environment,
                "executable_path": str(network.helper_path),
                "executable_sha256": "0" * 64,
            },
        )

    poisoned = json.loads(json.dumps(rows))
    poisoned[1]["launch"]["inner_argv_sha256"] = "0" * 64
    with pytest.raises(
        manager_module.ControlEvidenceError,
        match="canonical inner or wrapper argv",
    ):
        manager_module._provider_network_launch_from_journal(
            poisoned,
            _RUN_ID,
            owner_manager_pid=555,
        )
