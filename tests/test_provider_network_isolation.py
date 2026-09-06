from __future__ import annotations

import hashlib
import json
import os
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fort_gym.bench.run.provider_network_isolation import (
    CAPABILITY_SCHEMA,
    CLEANUP_SCHEMA,
    INSPECT_SCHEMA,
    INTEGRATION_STATUS,
    LINUX_CLASSIFICATION,
    PREPARE_SCHEMA,
    PYTHON_GUARD_ATTESTATION_SCHEMA,
    REQUIRED_HOOKS,
    SNAPSHOT_SCHEMA,
    CommandResult,
    ProviderNetworkCapabilityError,
    ProviderNetworkCleanupError,
    ProviderNetworkConfigurationError,
    ProviderNetworkEvidenceError,
    ProviderNetworkHostConfig,
    ProviderNetworkIsolationController,
    ProviderNetworkOwnershipError,
    validate_provider_network_capture,
)
from fort_gym.bench.run.runtime_contract import ProviderPolicy, RuntimeContract

_RUN_ID = "provider-net-preflight"
_CONTRACT_SHA256 = "a" * 64
_NONCE = "n" * 32
_RUNTIME_NONCE = "d" * 32
_PORT = 58_071
_POISON_HOST = "203.0.113.254"
_POISON_PORT = 44_443
_CANARY_PID = 91_001
_CANARY_IDENTITY = "f" * 64
_API_KEY_POISON = "sk-provider-net-must-not-leak"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeCanaryProbe:
    def __init__(self) -> None:
        self.identity_sha256 = _CANARY_IDENTITY
        self.cgroup = "/foreign.slice/provider-net-canary.scope"
        self.alive = True
        self.calls: list[int] = []

    def __call__(self, pid: int) -> dict[str, Any]:
        self.calls.append(pid)
        return {
            "pid": pid,
            "alive": self.alive,
            "identity_sha256": self.identity_sha256,
            "cgroup": self.cgroup,
            "ignored_command": f"--api-key={_API_KEY_POISON}",
        }


class FakeProviderNetworkHelper:
    """Stateful helper model; no subprocess, socket, BPF, or network calls."""

    def __init__(self, *, helper_sha256: str, bpf_object_sha256: str) -> None:
        self.helper_sha256 = helper_sha256
        self.bpf_object_sha256 = bpf_object_sha256
        self.controller: ProviderNetworkIsolationController | None = None
        self.calls: list[tuple[str, ...]] = []
        self.cgroup_exists = False
        self.pins_exist = False
        self.member_pids: list[int] = []
        self.capability_overrides: dict[str, Any] = {}
        self.capture_override: dict[str, Any] | None = None
        self.failures: dict[str, CommandResult] = {}

    def run(self, argv: Any, *, timeout_seconds: float) -> CommandResult:
        del timeout_seconds
        command = tuple(str(item) for item in argv)
        self.calls.append(command)
        operation = command[1]
        if operation in self.failures:
            failure = self.failures[operation]
            return CommandResult(
                argv=command,
                returncode=failure.returncode,
                stdout=failure.stdout,
                stderr=failure.stderr,
            )
        assert self.controller is not None
        controller = self.controller
        if operation == "probe":
            payload: dict[str, Any] = {
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
                "bpf_object_sha256": self.bpf_object_sha256,
            }
            payload.update(self.capability_overrides)
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
        elif operation == "snapshot":
            payload = self.capture_override or _valid_capture(controller)
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
        else:  # pragma: no cover - test helper refuses invented operations
            raise AssertionError(f"unexpected fake helper operation: {operation}")
        return CommandResult(
            argv=command,
            returncode=0,
            stdout=json.dumps(payload, sort_keys=True),
            stderr="",
        )


def _provider_budget() -> dict[str, Any]:
    return {
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


def _valid_capture(
    controller: ProviderNetworkIsolationController,
) -> dict[str, Any]:
    identity = controller.identity_sha256
    events = [
        {
            "sequence": 1,
            "identity_sha256": identity,
            "hook": "connect4",
            "operation": "connect",
            "family": "AF_INET",
            "protocol": "tcp",
            "destination_host": "127.0.0.1",
            "destination_port": controller.assigned_port,
            "decision": "allow",
            "errno": 0,
        },
        {
            "sequence": 2,
            "identity_sha256": identity,
            "hook": "connect4",
            "operation": "connect",
            "family": "AF_INET",
            "protocol": "tcp",
            "destination_host": "198.51.100.53",
            "destination_port": 53,
            "decision": "deny",
            "errno": "EPERM",
        },
        {
            "sequence": 3,
            "identity_sha256": identity,
            "hook": "connect4",
            "operation": "connect",
            "family": "AF_INET",
            "protocol": "tcp",
            "destination_host": "198.51.100.10",
            "destination_port": 443,
            "decision": "deny",
            "errno": "EPERM",
        },
        {
            "sequence": 4,
            "identity_sha256": identity,
            "hook": "connect4",
            "operation": "connect",
            "family": "AF_INET",
            "protocol": "tcp",
            "destination_host": controller.poison_sink_host,
            "destination_port": controller.poison_sink_port,
            "decision": "deny",
            "errno": "EACCES",
        },
        {
            "sequence": 5,
            "identity_sha256": identity,
            "hook": "connect6",
            "operation": "connect",
            "family": "AF_INET6",
            "protocol": "tcp",
            "destination_host": "::1",
            "destination_port": controller.assigned_port,
            "decision": "deny",
            "errno": "EPERM",
        },
        {
            "sequence": 6,
            "identity_sha256": identity,
            "hook": "sendmsg4",
            "operation": "sendmsg",
            "family": "AF_INET",
            "protocol": "udp",
            "destination_host": "198.51.100.53",
            "destination_port": 53,
            "decision": "deny",
            "errno": "EACCES",
        },
        {
            "sequence": 7,
            "identity_sha256": identity,
            "hook": "sendmsg6",
            "operation": "sendmsg",
            "family": "AF_INET6",
            "protocol": "udp",
            "destination_host": "::1",
            "destination_port": 53,
            "decision": "deny",
            "errno": "EACCES",
        },
    ]
    evidence_path_sha256 = _sha256(
        str(controller.python_denials_path).encode("utf-8")
    )
    return {
        "schema": SNAPSHOT_SCHEMA,
        "final": True,
        "identity_sha256": identity,
        "policy": controller.kernel_policy,
        "hooks": list(REQUIRED_HOOKS),
        "lost_events": 0,
        "event_count": len(events),
        "events": events,
        "python_guard": {
            "schema": PYTHON_GUARD_ATTESTATION_SCHEMA,
            "installed": True,
            "identity_sha256": identity,
            "policy": "loopback-port-only",
            "allowed_host": "127.0.0.1",
            "allowed_port": controller.assigned_port,
            "evidence_path_sha256": evidence_path_sha256,
        },
    }


def _controller(
    tmp_path: Path,
    *,
    canary: FakeCanaryProbe | None = None,
) -> tuple[
    ProviderNetworkIsolationController,
    FakeProviderNetworkHelper,
    FakeCanaryProbe,
]:
    helper_path = (tmp_path / "bin" / "fortgym-provider-net-helper").resolve()
    helper_path.parent.mkdir(parents=True)
    helper_path.write_bytes(b"provider-network-helper-test-binary\n")
    helper_path.chmod(0o700)
    bpf_object_path = (tmp_path / "bpf" / "provider-network.bpf.o").resolve()
    bpf_object_path.parent.mkdir(parents=True)
    bpf_object_path.write_bytes(b"provider-network-bpf-test-object\n")
    helper_sha256 = _sha256(helper_path.read_bytes())
    bpf_object_sha256 = _sha256(bpf_object_path.read_bytes())
    runner = FakeProviderNetworkHelper(
        helper_sha256=helper_sha256,
        bpf_object_sha256=bpf_object_sha256,
    )
    selected_canary = canary or FakeCanaryProbe()
    controller = ProviderNetworkIsolationController(
        run_id=_RUN_ID,
        contract_sha256=_CONTRACT_SHA256,
        nonce=_NONCE,
        assigned_port=_PORT,
        control_root=(tmp_path / "control").resolve(),
        gameplay_workspace=(tmp_path / "gameplay").resolve(),
        helper_path=helper_path,
        helper_sha256=helper_sha256,
        bpf_object_path=bpf_object_path,
        bpf_object_sha256=bpf_object_sha256,
        cgroup_root=(tmp_path / "fake-cgroup-v2").resolve(),
        bpffs_root=(tmp_path / "fake-bpffs").resolve(),
        foreign_canary_pid=_CANARY_PID,
        foreign_canary_probe=selected_canary,
        runner=runner,
        poison_sink_host=_POISON_HOST,
        poison_sink_port=_POISON_PORT,
    )
    runner.controller = controller
    return controller, runner, selected_canary


def _host_config(
    tmp_path: Path,
) -> tuple[ProviderNetworkHostConfig, FakeProviderNetworkHelper, FakeCanaryProbe]:
    controller, runner, canary = _controller(tmp_path)
    config = ProviderNetworkHostConfig(
        helper_path=controller.helper_path,
        helper_sha256=controller.helper_sha256,
        bpf_object_path=controller.bpf_object_path,
        bpf_object_sha256=controller.bpf_object_sha256,
        cgroup_root=Path("/sys/fs/cgroup/fortgym-provider-net"),
        bpffs_root=Path("/sys/fs/bpf/fortgym-provider-net"),
        foreign_canary_pid=_CANARY_PID,
        foreign_canary_probe=canary,
        runner=runner,
        poison_sink_host=_POISON_HOST,
        poison_sink_port=_POISON_PORT,
    )
    return config, runner, canary


def _service_contract_and_spec(
    tmp_path: Path,
) -> tuple[RuntimeContract, Any, Path]:
    control_root = (tmp_path / "service-control").resolve()
    artifacts_root = (tmp_path / "service-artifacts").resolve()
    config_path = (tmp_path / "experiment.json").resolve()
    contract = RuntimeContract(
        run_id=_RUN_ID,
        backend="dfhack",
        model="dfhack-governed-scripted",
        port=_PORT,
        nonce=_RUNTIME_NONCE,
        image_manifest_sha256="1" * 64,
        image_config_sha256="2" * 64,
        image_archive_sha256="3" * 64,
        seed_tree_sha256="4" * 64,
        seed_world_sha256="5" * 64,
        code_sha256="6" * 64,
        db_path=(tmp_path / "runs.sqlite3").resolve(),
        artifacts_root=artifacts_root,
        control_root=control_root,
        dfroot=(tmp_path / "dfroot").resolve(),
        seed_save="seed-region",
        runtime_save="runtime-region",
        cohort_run_ids=(_RUN_ID,),
        provider=ProviderPolicy(),
        scripted=True,
    )
    attempt_dir = control_root / _RUN_ID / "attempts" / "attempt-0001"
    spec = contract.to_run_spec(
        argv=RuntimeContract.worker_argv(
            python_executable=Path(sys.executable).absolute(),
            config_path=config_path,
            run_id=_RUN_ID,
        ),
        cwd=tmp_path.resolve(),
        attempt_dir=attempt_dir,
    )
    return contract, spec, control_root / _RUN_ID


def test_command_vectors_policy_guard_and_public_identity_are_exact_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", _API_KEY_POISON)
    controller, _runner, _canary = _controller(tmp_path)
    helper = str(controller.helper_path)

    assert controller.probe_argv() == (
        helper,
        "probe",
        "--bpf-object",
        str(controller.bpf_object_path),
        "--format",
        "json",
    )
    assert controller.prepare_argv() == (
        helper,
        "prepare",
        "--bpf-object",
        str(controller.bpf_object_path),
        "--expected-helper-sha256",
        controller.helper_sha256,
        "--expected-bpf-object-sha256",
        controller.bpf_object_sha256,
        "--cgroup",
        str(controller.cgroup_path),
        "--pin-root",
        str(controller.pin_root),
        "--identity-sha256",
        controller.identity_sha256,
        "--allow-connect4",
        f"127.0.0.1:{_PORT}",
        "--negative-canary-poison",
        f"{_POISON_HOST}:{_POISON_PORT}",
        "--deny-connect6",
        "--deny-sendmsg4",
        "--deny-sendmsg6",
        "--format",
        "json",
    )
    child_argv = ("/usr/bin/python3.11", "-m", "fort_gym.bench.cli", "experiment")
    assert controller.enter_argv(child_argv) == (
        helper,
        "enter",
        "--cgroup",
        str(controller.cgroup_path),
        "--identity-sha256",
        controller.identity_sha256,
        "--require-python-policy",
        "loopback-port-only",
        "--guard-attestation",
        str(controller.guard_attestation_path),
        "--",
        *child_argv,
    )
    assert controller.snapshot_argv() == (
        helper,
        "snapshot",
        "--cgroup",
        str(controller.cgroup_path),
        "--pin-root",
        str(controller.pin_root),
        "--identity-sha256",
        controller.identity_sha256,
        "--guard-attestation",
        str(controller.guard_attestation_path),
        "--format",
        "json",
    )
    assert controller.inspect_argv() == (
        helper,
        "inspect",
        "--cgroup",
        str(controller.cgroup_path),
        "--pin-root",
        str(controller.pin_root),
        "--identity-sha256",
        controller.identity_sha256,
        "--format",
        "json",
    )
    assert controller.cleanup_argv() == (
        helper,
        "cleanup",
        "--cgroup",
        str(controller.cgroup_path),
        "--pin-root",
        str(controller.pin_root),
        "--identity-sha256",
        controller.identity_sha256,
        "--format",
        "json",
    )
    assert controller.kernel_policy == {
        "mode": "cgroup_bpf_default_deny",
        "hooks": list(REQUIRED_HOOKS),
        "allow": {
            "hook": "connect4",
            "family": "AF_INET",
            "protocol": "tcp",
            "host": "127.0.0.1",
            "port": _PORT,
        },
        "deny": {
            "connect4_nonmatching": True,
            "connect6": True,
            "sendmsg4": True,
            "sendmsg6": True,
        },
    }
    assert controller.python_guard_environment() == {
        "FORT_GYM_NETWORK_POLICY": "loopback-port-only",
        "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
        "FORT_GYM_NETWORK_ALLOWED_PORT": str(_PORT),
        "FORT_GYM_NETWORK_EVIDENCE_PATH": str(controller.python_denials_path),
        "FORT_GYM_RUN_ID": _RUN_ID,
        "FORT_GYM_RUN_CONTRACT_SHA256": _CONTRACT_SHA256,
        "FORT_GYM_RUN_NONCE": _NONCE,
    }
    assert not controller.evidence_dir.is_relative_to(controller.gameplay_workspace)
    assert not controller.gameplay_workspace.is_relative_to(controller.evidence_dir)
    requirements = controller.integration_requirements()
    assert len(requirements) == 6
    assert any("enter_argv" in requirement for requirement in requirements)
    assert any("inner canonical worker argv" in requirement for requirement in requirements)

    public_serialized = json.dumps(
        {
            "identity": controller.public_identity(),
            "repr": repr(controller),
            "commands": (
                controller.probe_argv(),
                controller.prepare_argv(),
                controller.enter_argv(child_argv),
                controller.snapshot_argv(),
                controller.inspect_argv(),
                controller.cleanup_argv(),
            ),
        },
        sort_keys=True,
    )
    assert controller.public_identity()["integration_status"] == INTEGRATION_STATUS
    assert _NONCE not in public_serialized
    assert _API_KEY_POISON not in public_serialized
    assert "OPENROUTER_API_KEY" not in public_serialized


def test_host_config_builds_exact_reconstructable_service_controller_without_ambient_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", _API_KEY_POISON)
    monkeypatch.setenv("FORT_GYM_RUN_NONCE", "poison-parent-nonce")
    config, runner, _canary = _host_config(tmp_path / "host")
    contract, spec, run_dir = _service_contract_and_spec(tmp_path / "service")
    factory = config.service_factory()

    first = factory(contract, run_dir, object(), spec)
    second = factory(contract, run_dir, object(), spec)

    assert first.public_identity() == second.public_identity()
    assert first.identity_sha256 == second.identity_sha256
    assert first.evidence_dir == contract.control_root / _RUN_ID / "provider-network"
    assert first.gameplay_workspace == contract.artifacts_root / _RUN_ID
    assert first.cgroup_path.parent == Path("/sys/fs/cgroup/fortgym-provider-net")
    assert first.pin_root.parent == Path("/sys/fs/bpf/fortgym-provider-net")
    serialized = json.dumps(
        {
            "host": repr(config),
            "identity": first.public_identity(),
        },
        sort_keys=True,
    )
    assert _API_KEY_POISON not in serialized
    assert "poison-parent-nonce" not in serialized
    assert _RUNTIME_NONCE not in serialized
    assert os.environ["OPENROUTER_API_KEY"] == _API_KEY_POISON

    runner.controller = first
    prepared = first.prepare()
    assert prepared["identity"] == first.public_identity()
    assert [call[1] for call in runner.calls] == ["probe", "prepare"]


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("cgroup_root", Path("/tmp/not-the-pinned-cgroup-root"), "cgroup_root"),
        ("bpffs_root", Path("/tmp/not-the-pinned-bpffs-root"), "bpffs_root"),
        ("helper_sha256", "A" * 64, "helper_sha256"),
        ("bpf_object_sha256", "0", "bpf_object_sha256"),
        ("foreign_canary_pid", True, "foreign_canary_pid"),
        ("foreign_canary_pid", "91001", "foreign_canary_pid"),
        ("foreign_canary_probe", None, "foreign_canary_probe"),
        ("poison_sink_host", "127.0.0.1", "poison_sink_host"),
        ("poison_sink_port", True, "poison_sink_port"),
        ("poison_sink_port", "44443", "poison_sink_port"),
        ("runner", object(), "runner"),
    ],
)
def test_host_config_rejects_ambient_or_coerced_operational_inputs(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    controller, runner, canary = _controller(tmp_path)
    values: dict[str, Any] = {
        "helper_path": controller.helper_path,
        "helper_sha256": controller.helper_sha256,
        "bpf_object_path": controller.bpf_object_path,
        "bpf_object_sha256": controller.bpf_object_sha256,
        "cgroup_root": Path("/sys/fs/cgroup/fortgym-provider-net"),
        "bpffs_root": Path("/sys/fs/bpf/fortgym-provider-net"),
        "foreign_canary_pid": _CANARY_PID,
        "foreign_canary_probe": canary,
        "runner": runner,
        "poison_sink_host": _POISON_HOST,
        "poison_sink_port": _POISON_PORT,
    }
    values[field] = value

    with pytest.raises((ProviderNetworkConfigurationError, TypeError), match=match):
        ProviderNetworkHostConfig(**values)


@pytest.mark.parametrize(
    "mutation",
    ["run_dir", "attempt_dir", "environment", "runtime_controller"],
)
def test_host_config_factory_rejects_contradictory_service_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    config, _runner, _canary = _host_config(tmp_path / "host")
    contract, spec, run_dir = _service_contract_and_spec(tmp_path / "service")
    runtime_controller: object | None = object()
    if mutation == "run_dir":
        run_dir = run_dir.with_name("different-run")
    elif mutation == "attempt_dir":
        spec = replace(spec, artifact_dir=spec.artifact_dir.with_name("attempt-0002"))
    elif mutation == "environment":
        poisoned = dict(spec.env)
        poisoned["HOME"] = "/poisoned/home"
        spec = replace(
            spec,
            env=poisoned,
            env_allowlist=tuple(sorted(poisoned)),
        )
    elif mutation == "runtime_controller":
        runtime_controller = None

    with pytest.raises(
        ProviderNetworkConfigurationError,
        match="requires the bound runtime controller|identity is contradictory",
    ):
        config.service_factory()(contract, run_dir, runtime_controller, spec)


def test_prepare_fails_closed_when_any_linux_capability_is_absent(
    tmp_path: Path,
) -> None:
    controller, runner, _canary = _controller(tmp_path)
    runner.capability_overrides["hooks"] = ["connect4", "connect6", "sendmsg4"]

    with pytest.raises(
        ProviderNetworkCapabilityError,
        match="required isolated-x86 Linux network capabilities are absent",
    ):
        controller.prepare()

    assert runner.calls == [controller.probe_argv()]
    assert not controller.manifest_path.exists()
    assert not runner.cgroup_exists
    assert not runner.pins_exist


def test_helper_failure_redacts_stderr_nonce_and_provider_key(tmp_path: Path) -> None:
    controller, runner, _canary = _controller(tmp_path)
    runner.failures["probe"] = CommandResult(
        argv=(),
        returncode=127,
        stderr=f"OPENROUTER_API_KEY={_API_KEY_POISON} nonce={_NONCE}",
    )

    with pytest.raises(ProviderNetworkEvidenceError) as exc_info:
        controller.validate_evidence(_provider_budget())
    assert "absent" in str(exc_info.value)

    with pytest.raises(Exception) as prepare_exc_info:
        controller.prepare()
    message = str(prepare_exc_info.value)
    assert "failed closed" in message
    assert _API_KEY_POISON not in message
    assert _NONCE not in message


def test_capture_parser_accepts_exact_denials_and_rejects_contradictions(
    tmp_path: Path,
) -> None:
    controller, _runner, _canary = _controller(tmp_path)
    capture = _valid_capture(controller)
    report = validate_provider_network_capture(
        capture,
        identity_sha256=controller.identity_sha256,
        host="127.0.0.1",
        port=_PORT,
        poison_sink_host=_POISON_HOST,
        poison_sink_port=_POISON_PORT,
        evidence_path_sha256=_sha256(
            str(controller.python_denials_path).encode("utf-8")
        ),
        provider_budget=_provider_budget(),
    )

    assert report == {
        "schema": "fortgym.provider-network-report/v1",
        "ok": True,
        "classification": LINUX_CLASSIFICATION,
        "identity_sha256": controller.identity_sha256,
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
        "denied_hooks": list(REQUIRED_HOOKS),
        "lost_events": 0,
        "python_guard_attested": True,
        "kernel_enforcement_attested": True,
        "provider_calls": 0,
        "provider_cost_usd": 0.0,
        "provider_events": 0,
        "provider_tokens": 0,
    }

    identity_mismatch = deepcopy(capture)
    identity_mismatch["identity_sha256"] = "0" * 64
    with pytest.raises(ProviderNetworkEvidenceError, match="identity mismatch"):
        validate_provider_network_capture(
            identity_mismatch,
            identity_sha256=controller.identity_sha256,
            host="127.0.0.1",
            port=_PORT,
            poison_sink_host=_POISON_HOST,
            poison_sink_port=_POISON_PORT,
            evidence_path_sha256=_sha256(
                str(controller.python_denials_path).encode("utf-8")
            ),
        )

    allowed_443 = deepcopy(capture)
    allowed_443["events"][2]["decision"] = "allow"
    allowed_443["events"][2]["errno"] = 0
    with pytest.raises(ProviderNetworkEvidenceError, match="non-assigned"):
        validate_provider_network_capture(
            allowed_443,
            identity_sha256=controller.identity_sha256,
            host="127.0.0.1",
            port=_PORT,
            poison_sink_host=_POISON_HOST,
            poison_sink_port=_POISON_PORT,
            evidence_path_sha256=_sha256(
                str(controller.python_denials_path).encode("utf-8")
            ),
        )

    missing_hook = deepcopy(capture)
    missing_hook["hooks"] = list(REQUIRED_HOOKS[:-1])
    with pytest.raises(ProviderNetworkEvidenceError, match="hooks are incomplete"):
        validate_provider_network_capture(
            missing_hook,
            identity_sha256=controller.identity_sha256,
            host="127.0.0.1",
            port=_PORT,
            poison_sink_host=_POISON_HOST,
            poison_sink_port=_POISON_PORT,
            evidence_path_sha256=_sha256(
                str(controller.python_denials_path).encode("utf-8")
            ),
        )

    missing_negative_canary = deepcopy(capture)
    missing_negative_canary["events"][4]["destination_host"] = "::2"
    with pytest.raises(ProviderNetworkEvidenceError, match="negative canary"):
        validate_provider_network_capture(
            missing_negative_canary,
            identity_sha256=controller.identity_sha256,
            host="127.0.0.1",
            port=_PORT,
            poison_sink_host=_POISON_HOST,
            poison_sink_port=_POISON_PORT,
            evidence_path_sha256=_sha256(
                str(controller.python_denials_path).encode("utf-8")
            ),
        )

    leaked_key = deepcopy(capture)
    leaked_key["OPENROUTER_API_KEY"] = _API_KEY_POISON
    with pytest.raises(ProviderNetworkEvidenceError, match="sensitive field"):
        validate_provider_network_capture(
            leaked_key,
            identity_sha256=controller.identity_sha256,
            host="127.0.0.1",
            port=_PORT,
            poison_sink_host=_POISON_HOST,
            poison_sink_port=_POISON_PORT,
            evidence_path_sha256=_sha256(
                str(controller.python_denials_path).encode("utf-8")
            ),
        )


def test_prepare_rejects_bpf_object_swap_after_attested_probe(tmp_path: Path) -> None:
    controller, runner, _canary = _controller(tmp_path)
    original_run = runner.run

    def swapping_run(argv: Any, *, timeout_seconds: float) -> CommandResult:
        result = original_run(argv, timeout_seconds=timeout_seconds)
        if tuple(argv)[1] == "probe":
            controller.bpf_object_path.write_bytes(b"swapped-after-probe\n")
        return result

    runner.run = swapping_run  # type: ignore[method-assign]

    with pytest.raises(
        ProviderNetworkCapabilityError,
        match="changed after probe",
    ):
        controller.prepare()

    assert [call[1] for call in runner.calls] == ["probe"]


def test_prepare_cleanup_twice_reconcile_and_residue_preserve_foreign_canary(
    tmp_path: Path,
) -> None:
    controller, runner, canary = _controller(tmp_path)

    prepared = controller.prepare()
    first_cleanup = controller.cleanup()
    second_cleanup = controller.cleanup()
    residue = controller.residue()
    reconciled = controller.reconcile()
    report = controller.validate_evidence(_provider_budget())

    assert prepared["ok"] is True
    assert prepared["launch_integration"] == INTEGRATION_STATUS
    assert first_cleanup["ok"] is True
    assert first_cleanup["already_absent"] is False
    assert first_cleanup["capture"]["only_assigned_dfhack_connection"] is True
    assert first_cleanup["foreign_canary_untouched"] is True
    assert second_cleanup["ok"] is True
    assert second_cleanup["already_absent"] is True
    assert residue["ok"] is True
    assert residue["residue"] == {
        "cgroup_exists": False,
        "pins_exist": False,
        "member_pids": [],
    }
    assert reconciled["ok"] is True
    assert reconciled["already_absent"] is True
    assert reconciled["recovered"] is True
    assert report["provider_calls"] == 0
    assert report["provider_cost_usd"] == 0.0
    assert report["dns_connections"] == 0
    assert report["port_443_connections"] == 0
    assert report["poison_sink_connections"] == 0
    assert not runner.cgroup_exists
    assert not runner.pins_exist
    assert canary.calls == [_CANARY_PID] * 6
    assert [call[1] for call in runner.calls] == [
        "probe",
        "prepare",
        "inspect",
        "snapshot",
        "cleanup",
        "inspect",
        "inspect",
        "inspect",
        "inspect",
    ]

    persisted = b"".join(
        path.read_bytes()
        for path in sorted(controller.evidence_dir.iterdir())
        if path.is_file()
    )
    assert _NONCE.encode("utf-8") not in persisted
    assert _API_KEY_POISON.encode("utf-8") not in persisted
    manifest = json.loads(controller.manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "cleaned"
    assert manifest["foreign_canary"] == {
        "pid": _CANARY_PID,
        "alive": True,
        "identity_sha256": _CANARY_IDENTITY,
        "cgroup": "/foreign.slice/provider-net-canary.scope",
    }


def test_cleanup_refuses_live_members_and_changed_foreign_canary(
    tmp_path: Path,
) -> None:
    controller, runner, canary = _controller(tmp_path)
    controller.prepare()
    runner.member_pids = [92_001]

    with pytest.raises(ProviderNetworkCleanupError, match="still has members"):
        controller.cleanup()
    assert [call[1] for call in runner.calls].count("snapshot") == 0
    assert [call[1] for call in runner.calls].count("cleanup") == 0
    assert runner.cgroup_exists
    assert runner.pins_exist

    runner.member_pids = []
    canary.identity_sha256 = "e" * 64
    with pytest.raises(ProviderNetworkCleanupError, match="canary identity changed"):
        controller.cleanup()
    assert [call[1] for call in runner.calls].count("snapshot") == 0
    assert [call[1] for call in runner.calls].count("cleanup") == 0


def test_helper_capture_with_raw_nonce_fails_before_persistence_or_detach(
    tmp_path: Path,
) -> None:
    controller, runner, _canary = _controller(tmp_path)
    controller.prepare()
    leaky_capture = _valid_capture(controller)
    leaky_capture["opaque_value"] = _NONCE
    runner.capture_override = leaky_capture

    with pytest.raises(ProviderNetworkEvidenceError, match="forbidden secret material"):
        controller.cleanup()

    assert not controller.capture_path.exists()
    assert [call[1] for call in runner.calls].count("cleanup") == 0
    assert runner.cgroup_exists
    assert runner.pins_exist


def test_reconcile_never_infers_ownership_without_manifest(tmp_path: Path) -> None:
    controller, runner, _canary = _controller(tmp_path)
    runner.cgroup_exists = True
    runner.pins_exist = True

    with pytest.raises(
        ProviderNetworkOwnershipError,
        match="lack an ownership manifest",
    ):
        controller.reconcile()

    assert [call[1] for call in runner.calls] == ["inspect"]
    assert runner.cgroup_exists
    assert runner.pins_exist
