from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fort_gym.bench.run import network_guard


def test_address_policy_allows_only_exact_rpc_endpoint_or_unix() -> None:
    allowed = {
        "policy": "loopback-port-only",
        "allowed_host": "127.0.0.1",
        "allowed_port": 58_001,
    }

    assert network_guard._address_allowed(
        network_guard.socket.AF_UNIX,
        "/tmp/local.sock",
        **allowed,
    )
    assert network_guard._address_allowed(
        network_guard.socket.AF_INET,
        ("127.0.0.1", 58_001),
        **allowed,
    )
    assert not network_guard._address_allowed(
        network_guard.socket.AF_INET,
        ("127.0.0.1", 58_002),
        **allowed,
    )
    assert not network_guard._address_allowed(
        network_guard.socket.AF_INET,
        ("1.1.1.1", 443),
        **allowed,
    )


def _guarded_subprocess(
    tmp_path: Path,
    code: str,
    *,
    policy: str = "loopback-port-only",
    environment_overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    evidence = tmp_path / "network-denials.jsonl"
    runtime_directory = Path(network_guard.__file__).resolve().parent
    package_root = Path(network_guard.__file__).resolve().parents[3]
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.pathsep.join(
            (str(runtime_directory), str(package_root))
        ),
        "FORT_GYM_NETWORK_POLICY": policy,
        "FORT_GYM_NETWORK_EVIDENCE_PATH": str(evidence),
        "FORT_GYM_RUN_ID": "network-guard-test",
        "FORT_GYM_RUN_CONTRACT_SHA256": "a" * 64,
    }
    if policy == "loopback-port-only":
        environment.update(
            {
                "FORT_GYM_NETWORK_ALLOWED_HOST": "127.0.0.1",
                "FORT_GYM_NETWORK_ALLOWED_PORT": "58001",
            }
        )
    for name, value in (environment_overrides or {}).items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    return subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        cwd=tmp_path,
        timeout=10,
    )


def test_sitecustomize_blocks_provider_dns_before_network_and_records_evidence(
    tmp_path: Path,
) -> None:
    result = _guarded_subprocess(
        tmp_path,
        "import socket; socket.getaddrinfo('provider.invalid', 443)",
    )

    assert result.returncode != 0
    assert "supervised network policy denied getaddrinfo" in result.stderr
    [event] = [
        json.loads(line)
        for line in (tmp_path / "network-denials.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert event["run_id"] == "network-guard-test"
    assert event["contract_sha256"] == "a" * 64
    assert event["operation"] == "getaddrinfo"
    assert "provider.invalid" in event["address"]


@pytest.mark.parametrize(
    "environment_overrides",
    [
        {"FORT_GYM_RUN_ID": None},
        {"FORT_GYM_NETWORK_POLICY": "unknown"},
    ],
)
def test_invalid_guard_configuration_exits_before_application_import(
    tmp_path: Path,
    environment_overrides: dict[str, str | None],
) -> None:
    result = _guarded_subprocess(
        tmp_path,
        "raise SystemExit('APPLICATION_IMPORTED')",
        environment_overrides=environment_overrides,
    )

    assert result.returncode == 78
    assert "network guard failed before worker import" in result.stderr
    assert "APPLICATION_IMPORTED" not in result.stderr
