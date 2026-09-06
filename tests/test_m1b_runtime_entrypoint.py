from __future__ import annotations

import os
import hashlib
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).parents[1] / "infra" / "m1b" / "runtime_entrypoint.sh"


@pytest.mark.parametrize("acknowledgement,expected", [("correct", 137), ("wrong", 66), ("missing", 70)])
@pytest.mark.parametrize("exit_path", ["readiness", "load_save", "final_wait"])
def test_oom_exit_requires_run_bound_host_capture_ack(
    tmp_path: Path, acknowledgement: str, expected: int, exit_path: str
) -> None:
    helper = ENTRYPOINT.read_text().split("exit_after_launcher_failure() {", 1)[1].split("\n}", 1)[0]
    helper = helper.replace("/artifacts/", f"{tmp_path}/")
    capture = ENTRYPOINT.read_text().split("capture_oom_counters_before_exit() {", 1)[1].split("\n}", 1)[0]
    capture = capture.replace("/artifacts/", f"{tmp_path}/")
    identity = ("fortgym.m1b-pre-readiness-oom-exit-ack/v1", "test-run", "b" * 64, "a" * 32)
    if acknowledgement != "missing":
        token = hashlib.sha256(b"\0".join(value.encode() for value in identity)).hexdigest()
        (tmp_path / "pre-readiness-oom-exit-ack").write_text(
            (token if acknowledgement == "correct" else "wrong") + "\n"
        )
    completed = subprocess.run(
        ["/bin/bash", "-c", "set -euo pipefail\n"
         "sha256sum() { shasum -a 256; }\nsleep() { :; }\n"
         "capture_oom_counters_before_exit() {" + capture + "\n}\n"
         "trap capture_oom_counters_before_exit EXIT\n"
         "exit_after_launcher_failure() {" + helper + "\n}\n"
         + {"readiness": "(exit 137) &\nlauncher_pid=$!\nexit_after_launcher_failure RPC\n",
            "load_save": "(exit 137)\n",
            "final_wait": "(exit 137) &\nlauncher_pid=$!\nwait \"$launcher_pid\"\n"}[exit_path]],
        capture_output=True, text=True, check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
             "FORTGYM_FAULT_PROFILE": "oom_256m", "FORTGYM_RUN_ID": identity[1],
             "FORTGYM_CONTRACT_SHA256": identity[2], "FORTGYM_RUN_NONCE": identity[3]},
    )
    assert completed.returncode == expected, completed.stderr


@pytest.mark.parametrize("child_status,expected", [(137, 137), (1, 1), (143, 143), (0, 70)])
@pytest.mark.parametrize("phase", ["RPC", "map"])
def test_early_launcher_exit_preserves_failure_status(
    child_status: int, expected: int, phase: str
) -> None:
    script = ENTRYPOINT.read_text()
    helper = script.split("exit_after_launcher_failure() {", 1)[1].split("\n}", 1)[0]
    completed = subprocess.run(
        [
            "/bin/bash",
            "-c",
            "set -euo pipefail\nexit_after_launcher_failure() {"
            + helper
            + "\n}\n"
            + f"(exit {child_status}) &\nlauncher_pid=$!\nexit_after_launcher_failure {phase}\n",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert completed.returncode == expected
    assert f"DFHack exited before {phase} readiness" in completed.stderr
    assert f"exit_after_launcher_failure {phase}" in script


def test_m1b_runtime_entrypoint_has_valid_bash_syntax() -> None:
    completed = subprocess.run(
        ("/bin/bash", "-n", str(ENTRYPOINT)),
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert completed.returncode == 0, completed.stderr


def test_m1b_runtime_entrypoint_requires_exact_seed_identity_before_filesystem_work() -> (
    None
):
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "DFHACK_PORT": "58001",
        "FORTGYM_RUN_ID": "entrypoint-static-test",
        "FORTGYM_RUN_NONCE": "a" * 32,
        "FORTGYM_CONTRACT_SHA256": "b" * 64,
        "FORTGYM_RUNTIME_PREPARED": "1",
        "FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256": "1" * 64,
        "FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256": "2" * 64,
        "FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256": "3" * 64,
        "FORTGYM_EXPECTED_SEED_TREE_SHA256": "not-a-digest",
        "FORTGYM_EXPECTED_SEED_WORLD_SHA256": "c" * 64,
    }
    completed = subprocess.run(
        ("/bin/bash", str(ENTRYPOINT)),
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == os.EX_USAGE
    assert "invalid FORTGYM_EXPECTED_SEED_TREE_SHA256" in completed.stderr


def test_m1b_runtime_entrypoint_attests_nonce_contract_seed_and_map() -> None:
    script = ENTRYPOINT.read_text()
    required = (
        "FORTGYM_RUN_NONCE",
        "FORTGYM_CONTRACT_SHA256",
        "FORTGYM_RUNTIME_PREPARED",
        "FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256",
        "FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256",
        "FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256",
        "FORTGYM_EXPECTED_SEED_TREE_SHA256",
        "FORTGYM_EXPECTED_SEED_WORLD_SHA256",
        "seed_tree_sha256",
        "seed_world_sha256",
        "seed_copy_equal",
        "rpc_ready",
        "map_ready",
        "write_startup_terminal rpc_readiness_timeout true",
        "write_startup_terminal rpc_readiness_timeout false",
        "write_startup_terminal map_readiness_timeout false",
        "FORTGYM_ALLOW_TEST_FAULT_PROFILE",
        "FORTGYM_FAULT_PROFILE",
        "FORTGYM_COHORT_SHA256",
        "fortgym.m1b-pre-readiness-oom-hold-ready/v1",
        "pre-readiness-oom-release-token/v1",
        "/run/fortgym/run-identity.tsv",
    )
    for marker in required:
        assert marker in script
    assert (
        'if [[ "$seed_tree_sha256" != "$FORTGYM_EXPECTED_SEED_TREE_SHA256" ]]' in script
    )
    assert (
        'if [[ "$seed_world_sha256" != "$FORTGYM_EXPECTED_SEED_WORLD_SHA256" ]]'
        in script
    )


def test_secret_free_startup_receipts_are_host_readable() -> None:
    script = ENTRYPOINT.read_text()
    assert script.count('chmod 644 "$temporary_path"') == 1
    assert script.count('chmod 644 "$hold_temporary"') == 1
    assert 'chmod 600 "$temporary_path"' not in script
    assert 'chmod 600 "$hold_temporary"' not in script


def test_production_entrypoint_rejects_rpc_suppression_before_filesystem_work() -> None:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "DFHACK_PORT": "58001",
        "FORTGYM_RUN_ID": "entrypoint-fault-rejection",
        "FORTGYM_RUN_NONCE": "a" * 32,
        "FORTGYM_CONTRACT_SHA256": "b" * 64,
        "FORTGYM_RUNTIME_PREPARED": "1",
        "FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256": "1" * 64,
        "FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256": "2" * 64,
        "FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256": "3" * 64,
        "FORTGYM_EXPECTED_SEED_TREE_SHA256": "4" * 64,
        "FORTGYM_EXPECTED_SEED_WORLD_SHA256": "5" * 64,
        "FORTGYM_TEST_SUPPRESS_RPC_READY": "1",
    }

    completed = subprocess.run(
        ("/bin/bash", str(ENTRYPOINT)),
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == os.EX_USAGE
    assert "test fault knob rejected outside explicit fault mode" in completed.stderr


def test_production_entrypoint_rejects_oom_profile_before_filesystem_work() -> None:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "DFHACK_PORT": "58001",
        "FORTGYM_RUN_ID": "entrypoint-profile-rejection",
        "FORTGYM_RUN_NONCE": "a" * 32,
        "FORTGYM_CONTRACT_SHA256": "b" * 64,
        "FORTGYM_RUNTIME_PREPARED": "1",
        "FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256": "1" * 64,
        "FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256": "2" * 64,
        "FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256": "3" * 64,
        "FORTGYM_EXPECTED_SEED_TREE_SHA256": "4" * 64,
        "FORTGYM_EXPECTED_SEED_WORLD_SHA256": "5" * 64,
        "FORTGYM_FAULT_PROFILE": "oom_256m",
        "FORTGYM_COHORT_SHA256": "6" * 64,
    }

    completed = subprocess.run(
        ("/bin/bash", str(ENTRYPOINT)),
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == os.EX_USAGE
    assert (
        "runtime fault profile rejected outside explicit fault mode" in completed.stderr
    )
