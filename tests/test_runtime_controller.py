from __future__ import annotations

import hashlib
import io
import json
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import fort_gym.bench.run.runtime_controller as runtime_controller_module
from fort_gym.bench.run import fault_driver
from fort_gym.bench.run.runtime_contract import ProviderPolicy, RuntimeContract
from fort_gym.bench.run.runtime_controller import (
    CONTRACT_LABEL,
    ENTRYPOINT_LABEL,
    FAULT_PROFILE_LABEL,
    MANAGED_LABEL,
    CommandResult,
    DockerRuntimeController,
    RuntimeAttestationError,
    RuntimeCleanupError,
    RuntimeContainerCreateFailure,
    RuntimeFaultProfile,
    RuntimeMapReadinessTimeout,
    RuntimeOomHoldFailure,
    RuntimeOomPreReadiness,
    RuntimeOwnershipError,
    RuntimeReadinessTimeout,
    RuntimeStartError,
    RuntimeTestFault,
    ZstdTarArchiveReader,
)

HASHES = {
    "image_manifest_sha256": "1" * 64,
    "image_config_sha256": "2" * 64,
    "image_archive_sha256": "3" * 64,
    "seed_tree_sha256": "4" * 64,
    "seed_world_sha256": "5" * 64,
    "code_sha256": "6" * 64,
}
CONTAINER_ID = "a" * 64
FOREIGN_ID = "f" * 64
ENTRYPOINT = Path(__file__).parents[1] / "infra" / "m1b" / "runtime_entrypoint.sh"


def _contract(
    tmp_path: Path,
    *,
    scripted: bool = True,
    provider: ProviderPolicy | None = None,
    hashes: Mapping[str, str] | None = None,
) -> RuntimeContract:
    return RuntimeContract(
        run_id="m1b-runtime-01",
        backend="dfhack",
        model="dfhack-governed-scripted" if scripted else "provider-test",
        port=58_001,
        nonce="a" * 32,
        db_path=tmp_path / "registry.sqlite3",
        artifacts_root=tmp_path / "artifacts",
        control_root=tmp_path / "control",
        dfroot=tmp_path / "df",
        seed_save="region3-seed",
        runtime_save="runtime-m1b-runtime-01",
        cohort_run_ids=("m1b-runtime-01", "m1b-runtime-02"),
        provider=provider or ProviderPolicy(),
        scripted=scripted,
        **dict(hashes or HASHES),
    )


class FakeDockerRunner:
    """Small Docker/ss state model; no subprocess, socket, or network calls."""

    def __init__(
        self,
        *,
        image_manifest_sha256: str = HASHES["image_manifest_sha256"],
        image_config_sha256: str = HASHES["image_config_sha256"],
        archive_members: Mapping[str, str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.archive_calls: list[tuple[Path, frozenset[str], float]] = []
        self.containers: dict[str, dict[str, Any]] = {}
        self.names: dict[str, str] = {}
        self.listener_output = ""
        self.attestation_output = ""
        self.logs_stdout = "dfhack runtime log\n"
        self.logs_returncode = 0
        self.manifest_available = True
        self.image_manifest_sha256 = image_manifest_sha256
        self.image_config_sha256 = image_config_sha256
        self.image_id = f"sha256:{image_manifest_sha256}"
        self.config_image_id = f"sha256:{image_config_sha256}"
        self.runtime_image = f"sha256:{image_config_sha256}"
        self.archive_members = dict(archive_members or {})
        self.docker_run_returncode = 0
        self.docker_launch_exception: BaseException | None = None
        self.docker_start_returncode = 0
        self.docker_start_exception: BaseException | None = None
        self.docker_start_output: str | None = None
        self.write_oom_hold_ready = True
        self.exit_after_run = False
        self.oom_killed_after_run = False
        self.exit_code_after_run = 70
        self.startup_terminal_payload: dict[str, Any] | None = None

    def run(self, argv: Sequence[str], *, timeout_seconds: float) -> CommandResult:
        del timeout_seconds
        command = tuple(str(item) for item in argv)
        self.calls.append(command)
        if command[:3] == ("docker", "image", "inspect"):
            reference = command[-1]
            if reference == f"sha256:{self.image_manifest_sha256}":
                if not self.manifest_available:
                    return self._result(
                        command,
                        returncode=1,
                        stderr=f"No such image: {reference}",
                    )
                image_id = self.image_id
            elif reference == f"sha256:{self.image_config_sha256}":
                image_id = self.config_image_id
            else:
                return self._result(
                    command,
                    returncode=1,
                    stderr=f"No such image: {reference}",
                )
            return self._result(command, stdout=json.dumps([{"Id": image_id}]))
        if command[:2] == ("docker", "run"):
            return self._docker_launch(command, start_immediately=True)
        if command[:2] == ("docker", "create"):
            return self._docker_launch(command, start_immediately=False)
        if command[:2] == ("docker", "start"):
            return self._docker_start(command, command[2])
        if command[:4] == ("docker", "inspect", "--type", "container"):
            return self._inspect(command, command[4])
        if command[:2] == ("docker", "exec"):
            return self._result(command, stdout=self.attestation_output)
        if command[:2] == ("docker", "logs"):
            return self._result(
                command,
                returncode=self.logs_returncode,
                stdout=self.logs_stdout,
                stderr="synthetic log error" if self.logs_returncode else "",
            )
        if command[:3] == ("docker", "rm", "--force"):
            return self._remove(command, command[3])
        if command[:2] == ("docker", "ps"):
            rows = [
                json.dumps({"ID": identifier, "Names": item["Name"].lstrip("/")})
                for identifier, item in self.containers.items()
            ]
            return self._result(
                command, stdout="\n".join(rows) + ("\n" if rows else "")
            )
        if command[0] == "ss":
            return self._result(command, stdout=self.listener_output)
        raise AssertionError(f"unexpected fake command: {command!r}")

    def read_archive_members(
        self,
        archive_path: Path,
        members: frozenset[str],
        *,
        timeout_seconds: float,
    ) -> Mapping[str, bytes]:
        self.archive_calls.append((archive_path, members, timeout_seconds))
        missing = members.difference(self.archive_members)
        if missing:
            raise RuntimeStartError("synthetic archive lacks required member")
        return {member: self.archive_members[member].encode() for member in members}

    @staticmethod
    def _result(
        command: tuple[str, ...],
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> CommandResult:
        return CommandResult(command, returncode, stdout, stderr)

    def _docker_launch(
        self, command: tuple[str, ...], *, start_immediately: bool
    ) -> CommandResult:
        if self.docker_launch_exception is not None:
            raise self.docker_launch_exception
        if self.docker_run_returncode:
            return self._result(
                command,
                returncode=self.docker_run_returncode,
                stderr="synthetic Docker create failure",
            )
        name = command[command.index("--name") + 1]
        labels = self._pairs(command, "--label")
        environment = self._pairs(command, "--env")
        volumes = [
            command[index + 1]
            for index, item in enumerate(command)
            if item == "--volume"
        ]
        image = command[-2]
        cpuset = (
            command[command.index("--cpuset-cpus") + 1]
            if "--cpuset-cpus" in command
            else ""
        )
        memory_limit = command[command.index("--memory") + 1]
        memory_bytes = {
            "4g": 4 * 1024 * 1024 * 1024,
            "256m": 256 * 1024 * 1024,
        }[memory_limit]
        mounts = []
        for volume in volumes:
            source, destination, *options = volume.split(":")
            mounts.append(
                {
                    "Source": source,
                    "Destination": destination,
                    "RW": options != ["ro"],
                }
            )
        inspection = {
            "Id": CONTAINER_ID,
            "Name": f"/{name}",
            "Image": self.runtime_image,
            "Config": {
                "Image": image,
                "Labels": labels,
                "Env": [f"{name}={value}" for name, value in environment.items()],
                "Entrypoint": ["/bin/bash"],
                "Cmd": ["/opt/fortgym-m1b/runtime_entrypoint.sh"],
            },
            "HostConfig": {
                "NetworkMode": "host",
                "Memory": memory_bytes,
                "MemorySwap": memory_bytes,
                "PidsLimit": 256,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges", "seccomp=unconfined"],
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                "CpusetCpus": cpuset,
            },
            "State": {
                "Running": start_immediately and not self.exit_after_run,
                "OOMKilled": start_immediately and self.oom_killed_after_run,
                "ExitCode": (
                    self.exit_code_after_run
                    if start_immediately and self.exit_after_run
                    else 0
                ),
            },
            "Mounts": mounts,
        }
        self.containers[CONTAINER_ID] = inspection
        self.names[name] = CONTAINER_ID
        if self.startup_terminal_payload is not None:
            evidence_mount = next(
                mount for mount in mounts if mount["Destination"] == "/artifacts"
            )
            evidence_dir = Path(str(evidence_mount["Source"]))
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "startup-terminal.json").write_text(
                json.dumps(self.startup_terminal_payload),
                encoding="utf-8",
            )
        if start_immediately and not self.listener_output and not self.exit_after_run:
            port = environment["DFHACK_PORT"]
            self.listener_output = f"LISTEN 0 128 127.0.0.1:{port} 0.0.0.0:*\n"
        return self._result(command, stdout=f"{CONTAINER_ID}\n")

    def _docker_start(self, command: tuple[str, ...], identifier: str) -> CommandResult:
        if self.docker_start_exception is not None:
            raise self.docker_start_exception
        if self.docker_start_returncode:
            return self._result(
                command,
                returncode=self.docker_start_returncode,
                stderr="synthetic Docker start failure",
            )
        resolved = self.names.get(identifier, identifier)
        inspection = self.containers.get(resolved)
        if inspection is None:
            return self._result(command, returncode=1, stderr="No such container")
        inspection["State"] = {"Running": True, "OOMKilled": False, "ExitCode": 0}
        environment = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in inspection["Config"]["Env"]
        }
        if (
            environment.get("FORTGYM_FAULT_PROFILE") == "oom_256m"
            and self.write_oom_hold_ready
        ):
            evidence_mount = next(
                mount
                for mount in inspection["Mounts"]
                if mount["Destination"] == "/artifacts"
            )
            evidence_dir = Path(str(evidence_mount["Source"]))
            hold_ready = {
                "schema": "fortgym.m1b-pre-readiness-oom-hold-ready/v1",
                "run_id": environment["FORTGYM_RUN_ID"],
                "contract_sha256": environment["FORTGYM_CONTRACT_SHA256"],
                "nonce_sha256": hashlib.sha256(
                    environment["FORTGYM_RUN_NONCE"].encode()
                ).hexdigest(),
                "cohort_sha256": environment["FORTGYM_COHORT_SHA256"],
                "fault_profile": "oom_256m",
                "memory_bytes": 256 * 1024 * 1024,
                "memory_swap_bytes": 256 * 1024 * 1024,
            }
            (evidence_dir / "pre-readiness-oom-hold-ready.json").write_text(
                json.dumps(hold_ready),
                encoding="utf-8",
            )
        output = self.docker_start_output or resolved
        return self._result(command, stdout=f"{output}\n")

    @staticmethod
    def _pairs(command: tuple[str, ...], option: str) -> dict[str, str]:
        pairs: dict[str, str] = {}
        for index, item in enumerate(command):
            if item != option:
                continue
            name, value = command[index + 1].split("=", 1)
            pairs[name] = value
        return pairs

    def _inspect(self, command: tuple[str, ...], identifier: str) -> CommandResult:
        resolved = self.names.get(identifier, identifier)
        inspection = self.containers.get(resolved)
        if inspection is None:
            return self._result(
                command, returncode=1, stderr=f"No such object: {identifier}"
            )
        environment = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in inspection["Config"]["Env"]
        }
        if environment.get("FORTGYM_FAULT_PROFILE") == "oom_256m":
            evidence_mount = next(
                mount
                for mount in inspection["Mounts"]
                if mount["Destination"] == "/artifacts"
            )
            evidence_dir = Path(str(evidence_mount["Source"]))
            if (evidence_dir / "pre-readiness-oom-release").exists():
                if self.exit_after_run:
                    inspection["State"] = {
                        "Running": False,
                        "OOMKilled": self.oom_killed_after_run,
                        "ExitCode": self.exit_code_after_run,
                    }
                elif not self.listener_output:
                    port = environment["DFHACK_PORT"]
                    self.listener_output = f"LISTEN 0 128 127.0.0.1:{port} 0.0.0.0:*\n"
        return self._result(command, stdout=json.dumps([inspection]))

    def _remove(self, command: tuple[str, ...], identifier: str) -> CommandResult:
        resolved = self.names.get(identifier, identifier)
        inspection = self.containers.pop(resolved, None)
        if inspection is None:
            return self._result(command, returncode=1, stderr="No such container")
        self.names.pop(str(inspection["Name"]).lstrip("/"), None)
        if inspection["Config"]["Labels"].get(MANAGED_LABEL) == "true":
            self.listener_output = ""
        return self._result(command, stdout=f"{resolved}\n")


class FakeOomMonitor:
    def __init__(
        self,
        evidence_dir: Path | None = None,
        contract: RuntimeContract | None = None,
    ) -> None:
        self.evidence_dir = evidence_dir
        self.contract = contract
        self.arm_calls: list[Mapping[str, Any]] = []
        self.finalize_calls: list[Mapping[str, Any]] = []
        self.arm_result: dict[str, Any] | None = None
        self.hold_present_at_arm: bool | None = None
        self.release_present_at_arm: bool | None = None

    def arm(self, container_created: Mapping[str, Any]) -> Mapping[str, Any]:
        self.arm_calls.append(dict(container_created))
        if self.evidence_dir is not None:
            self.hold_present_at_arm = (
                self.evidence_dir / "pre-readiness-oom-hold-ready.json"
            ).exists()
            self.release_present_at_arm = (
                self.evidence_dir / "pre-readiness-oom-release"
            ).exists()
        assert self.evidence_dir is not None
        assert self.contract is not None
        peer_run_id = next(
            run_id
            for run_id in self.contract.cohort_run_ids
            if run_id != self.contract.run_id
        )
        result = {
            "schema": "fortgym.m1b-pre-readiness-oom-monitor-arm/v1",
            "ok": True,
            "run_id": container_created["run_id"],
            "contract_sha256": container_created["contract_sha256"],
            "nonce_sha256": container_created["nonce_sha256"],
            "cohort_sha256": container_created["cohort_sha256"],
            "container_id": container_created["container_id"],
            "container_init_host_pid": 4242,
            "container_cgroup_path": "/system.slice/docker-target.scope",
            "peer_run_id": peer_run_id,
            "peer_container_id": FOREIGN_ID,
            "peer_readiness_sha256": "e" * 64,
            "journal_path": str(
                self.contract.control_root
                / self.contract.run_id
                / "fault-driver-observations.jsonl"
            ),
        }
        self.arm_result = result
        return result

    def finalize(self, pre_readiness_oom: Mapping[str, Any]) -> Mapping[str, Any]:
        self.finalize_calls.append(dict(pre_readiness_oom))
        assert self.arm_result is not None
        return {
            "schema": "fortgym.m1b-pre-readiness-oom-monitor-finalize/v1",
            "ok": True,
            "run_id": self.arm_result["run_id"],
            "contract_sha256": self.arm_result["contract_sha256"],
            "nonce_sha256": self.arm_result["nonce_sha256"],
            "cohort_sha256": self.arm_result["cohort_sha256"],
            "container_id": self.arm_result["container_id"],
            "journal_path": self.arm_result["journal_path"],
            "completed_record_sha256": "7" * 64,
            "classifier_evidence_sha256": "8" * 64,
        }


def _attestation(contract: RuntimeContract, *, map_state: str = "MAP_LOADED") -> str:
    return (
        f"FORTGYM_ATTEST\t{contract.run_id}\t{contract.nonce}\t"
        f"{contract.contract_sha256}\t{contract.seed_tree_sha256}\t"
        f"{contract.seed_world_sha256}\t{contract.image_manifest_sha256}\t"
        f"{contract.image_config_sha256}\t{contract.image_archive_sha256}\t"
        f"{map_state}\n"
    )


def _controller(
    contract: RuntimeContract,
    runner: FakeDockerRunner,
    *,
    cpuset_cpus: str | None = "3",
    allow_test_faults: bool = False,
    test_fault: RuntimeTestFault | None = None,
    image_archive_path: Path | None = None,
    allow_test_fault_profile: bool = False,
    fault_profile: RuntimeFaultProfile | None = None,
    pre_readiness_oom_monitor: Any = None,
) -> DockerRuntimeController:
    runner.attestation_output = _attestation(contract)
    return DockerRuntimeController(
        contract,
        entrypoint_path=ENTRYPOINT,
        cpuset_cpus=cpuset_cpus,
        runner=runner,
        image_archive_path=image_archive_path,
        archive_member_reader=runner.read_archive_members,
        readiness_attempts=2,
        readiness_interval_seconds=0,
        allow_test_faults=allow_test_faults,
        test_fault=test_fault,
        allow_test_fault_profile=allow_test_fault_profile,
        fault_profile=fault_profile,
        pre_readiness_oom_monitor=pre_readiness_oom_monitor,
        sleep=lambda _seconds: None,
    )


def _oci_archive_case(
    tmp_path: Path,
    *,
    wrong_manifest_config: bool = False,
) -> tuple[RuntimeContract, FakeDockerRunner, Path]:
    config_bytes = b'{"architecture":"amd64","os":"linux"}'
    config_sha256 = hashlib.sha256(config_bytes).hexdigest()
    manifest_config = (
        "sha256:" + "e" * 64 if wrong_manifest_config else f"sha256:{config_sha256}"
    )
    manifest_bytes = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": manifest_config,
                "size": len(config_bytes),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": "sha256:" + "f" * 64,
                    "size": 1,
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    index_bytes = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": f"sha256:{manifest_sha256}",
                    "size": len(manifest_bytes),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    archive_path = tmp_path / "preserved-image.tar.zst"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"synthetic-compressed-oci-archive")
    hashes = {
        **HASHES,
        "image_manifest_sha256": manifest_sha256,
        "image_config_sha256": config_sha256,
        "image_archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    }
    contract = _contract(tmp_path, hashes=hashes)
    runner = FakeDockerRunner(
        image_manifest_sha256=manifest_sha256,
        image_config_sha256=config_sha256,
        archive_members={
            "index.json": index_bytes.decode(),
            f"blobs/sha256/{manifest_sha256}": manifest_bytes.decode(),
            f"blobs/sha256/{config_sha256}": config_bytes.decode(),
        },
    )
    runner.manifest_available = False
    return contract, runner, archive_path


def test_zstd_archive_reader_streams_exact_members_without_extraction(
    tmp_path: Path,
) -> None:
    zstd = shutil.which("zstd")
    if zstd is None:
        pytest.skip("zstd is unavailable")
    raw_tar = tmp_path / "oci.tar"
    compressed = tmp_path / "oci.tar.zst"
    expected = b'{"schemaVersion":2}'
    with tarfile.open(raw_tar, mode="w") as archive:
        selected = tarfile.TarInfo("index.json")
        selected.size = len(expected)
        archive.addfile(selected, io.BytesIO(expected))
        unrelated = tarfile.TarInfo("blobs/sha256/unrelated")
        unrelated.size = 4
        archive.addfile(unrelated, io.BytesIO(b"skip"))
    completed = subprocess.run(
        (zstd, "-q", "-f", str(raw_tar), "-o", str(compressed)),
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr

    observed = ZstdTarArchiveReader(zstd)(
        compressed,
        frozenset({"index.json"}),
        timeout_seconds=10.0,
    )

    assert observed == {"index.json": expected}
    assert not (tmp_path / "index.json").exists()


def test_docker_argv_is_checksum_pinned_scoped_hardened_and_provider_free(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)

    argv = controller.docker_run_argv()
    environment = controller.container_environment()

    assert argv[:2] == ("docker", "run")
    assert argv[-2:] == (
        f"sha256:{contract.image_manifest_sha256}",
        "/opt/fortgym-m1b/runtime_entrypoint.sh",
    )
    assert ("--network", "host") == argv[
        argv.index("--network") : argv.index("--network") + 2
    ]
    assert ("--cpuset-cpus", "3") == argv[
        argv.index("--cpuset-cpus") : argv.index("--cpuset-cpus") + 2
    ]
    assert ("--memory", "4g") == argv[
        argv.index("--memory") : argv.index("--memory") + 2
    ]
    assert ("--memory-swap", "4g") == argv[
        argv.index("--memory-swap") : argv.index("--memory-swap") + 2
    ]
    assert ("--pids-limit", "256") == argv[
        argv.index("--pids-limit") : argv.index("--pids-limit") + 2
    ]
    assert "ALL" in argv
    assert "no-new-privileges" in argv
    assert ("--restart", "no") == argv[
        argv.index("--restart") : argv.index("--restart") + 2
    ]
    assert f"{MANAGED_LABEL}=true" in argv
    assert f"{CONTRACT_LABEL}={contract.contract_sha256}" in argv
    assert environment == {
        "DFHACK_PORT": "58001",
        "FORTGYM_CONTRACT_SHA256": contract.contract_sha256,
        "FORTGYM_EXPECTED_IMAGE_ARCHIVE_SHA256": "3" * 64,
        "FORTGYM_EXPECTED_IMAGE_CONFIG_SHA256": "2" * 64,
        "FORTGYM_EXPECTED_IMAGE_MANIFEST_SHA256": "1" * 64,
        "FORTGYM_EXPECTED_SEED_TREE_SHA256": "4" * 64,
        "FORTGYM_EXPECTED_SEED_WORLD_SHA256": "5" * 64,
        "FORTGYM_RUN_ID": contract.run_id,
        "FORTGYM_RUN_NONCE": contract.nonce,
        "FORTGYM_RUNTIME_PREPARED": "1",
        "FORTGYM_RUNTIME_SAVE": contract.runtime_save,
    }
    assert not any(
        marker in item
        for item in argv
        for marker in ("OPENROUTER", "OPENAI", "ANTHROPIC", "API_KEY")
    )


def test_test_fault_requires_explicit_authorization_and_default_env_has_no_knob(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    default = _controller(contract, runner)

    environment = default.container_environment()
    assert "FORTGYM_ALLOW_TEST_FAULTS" not in environment
    assert "FORTGYM_TEST_SUPPRESS_RPC_READY" not in environment

    with pytest.raises(ValueError, match="explicit test-only authorization"):
        _controller(
            contract,
            runner,
            test_fault=RuntimeTestFault.SUPPRESS_RPC_READINESS,
        )
    assert runner.calls == []


def test_explicit_test_fault_adds_only_gated_rpc_suppression_identity(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    controller = _controller(
        contract,
        FakeDockerRunner(),
        allow_test_faults=True,
        test_fault=RuntimeTestFault.SUPPRESS_RPC_READINESS,
    )

    environment = controller.container_environment()
    assert environment["FORTGYM_ALLOW_TEST_FAULTS"] == "1"
    assert environment["FORTGYM_TEST_SUPPRESS_RPC_READY"] == "1"
    assert controller.expected_labels["fortgym.m1b.test_fault"] == (
        "suppress_rpc_readiness"
    )


def test_prepare_uses_exact_config_id_when_manifest_descriptor_is_unaddressable(
    tmp_path: Path,
) -> None:
    contract, runner, archive_path = _oci_archive_case(tmp_path)
    controller = _controller(
        contract,
        runner,
        image_archive_path=archive_path,
    )

    evidence = controller.prepare()

    assert evidence["image_reference"] == controller.image_config_reference
    assert evidence["image_resolution"]["mode"] == "config_id_fallback"
    image_inspections = [
        call for call in runner.calls if call[:3] == ("docker", "image", "inspect")
    ]
    assert image_inspections == [
        ("docker", "image", "inspect", controller.image_reference),
        ("docker", "image", "inspect", controller.image_config_reference),
    ]
    docker_run = next(call for call in runner.calls if call[:2] == ("docker", "run"))
    assert docker_run[-2] == controller.image_config_reference
    resolution = json.loads(
        (controller.evidence_dir / "image-resolution.json").read_text()
    )
    assert resolution["image_manifest_sha256"] == contract.image_manifest_sha256
    assert resolution["image_config_sha256"] == contract.image_config_sha256
    assert resolution["image_archive_sha256"] == contract.image_archive_sha256
    assert resolution["archive_verification"] == {
        "schema": "fortgym.m1b-oci-archive-verification/v1",
        "archive_path": str(archive_path),
        "compressed_sha256": contract.image_archive_sha256,
        "archive_size_bytes": archive_path.stat().st_size,
        "manifest_digest": controller.image_reference,
        "config_digest": controller.image_config_reference,
        "index_manifest_count": 1,
    }
    assert runner.archive_calls == [
        (archive_path, frozenset({"index.json"}), 120.0),
        (
            archive_path,
            frozenset({f"blobs/sha256/{contract.image_manifest_sha256}"}),
            120.0,
        ),
        (
            archive_path,
            frozenset({f"blobs/sha256/{contract.image_config_sha256}"}),
            120.0,
        ),
    ]


def test_config_id_fallback_fails_closed_without_preserved_archive(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.manifest_available = False

    with pytest.raises(RuntimeStartError, match="explicit preserved OCI archive"):
        _controller(contract, runner).prepare()

    assert not any(call[:2] == ("docker", "run") for call in runner.calls)


def test_config_id_fallback_rejects_archive_hash_or_manifest_chain_mismatch(
    tmp_path: Path,
) -> None:
    contract, runner, archive_path = _oci_archive_case(tmp_path / "hash")
    archive_path.write_bytes(b"changed-after-contract")
    with pytest.raises(RuntimeStartError, match="compressed SHA-256"):
        _controller(
            contract,
            runner,
            image_archive_path=archive_path,
        ).prepare()

    chain_contract, chain_runner, chain_archive = _oci_archive_case(
        tmp_path / "chain",
        wrong_manifest_config=True,
    )
    with pytest.raises(RuntimeStartError, match="pinned config digest"):
        _controller(
            chain_contract,
            chain_runner,
            image_archive_path=chain_archive,
        ).prepare()


@pytest.mark.parametrize("fallback", [False, True])
def test_prepare_rejects_unpinned_image_id_in_either_docker_store(
    tmp_path: Path,
    fallback: bool,
) -> None:
    archive_path: Path | None = None
    if fallback:
        contract, runner, archive_path = _oci_archive_case(tmp_path)
        runner.config_image_id = "sha256:" + "e" * 64
    else:
        contract = _contract(tmp_path)
        runner = FakeDockerRunner()
        runner.image_id = "sha256:" + "e" * 64
    controller = _controller(
        contract,
        runner,
        image_archive_path=archive_path,
    )

    with pytest.raises(RuntimeStartError, match="unpinned|pinned config"):
        controller.prepare()

    assert not any(call[:2] == ("docker", "run") for call in runner.calls)


def test_injected_rpc_timeout_is_typed_and_cleanup_remains_exact(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.exit_after_run = True
    runner.startup_terminal_payload = {
        "schema": "fortgym.m1b-startup-terminal/v1",
        "run_id": contract.run_id,
        "contract_sha256": contract.contract_sha256,
        "terminal_code": "rpc_readiness_timeout",
        "injected": True,
    }
    controller = _controller(
        contract,
        runner,
        allow_test_faults=True,
        test_fault=RuntimeTestFault.SUPPRESS_RPC_READINESS,
    )

    with pytest.raises(RuntimeReadinessTimeout) as exc_info:
        controller.prepare()

    assert exc_info.value.terminal_code == "rpc_readiness_timeout"
    assert exc_info.value.injected is True
    cleanup = controller.cleanup()
    assert cleanup["ok"] is True
    assert cleanup["container_absent"] is True
    assert cleanup["listener_absent"] is True


@pytest.mark.parametrize(
    ("terminal_code", "expected_type"),
    [
        ("rpc_readiness_timeout", RuntimeReadinessTimeout),
        ("map_readiness_timeout", RuntimeMapReadinessTimeout),
    ],
)
def test_natural_readiness_terminal_is_typed_and_contract_bound(
    tmp_path: Path,
    terminal_code: str,
    expected_type: type[RuntimeAttestationError],
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.exit_after_run = True
    runner.startup_terminal_payload = {
        "schema": "fortgym.m1b-startup-terminal/v1",
        "run_id": contract.run_id,
        "contract_sha256": contract.contract_sha256,
        "terminal_code": terminal_code,
        "injected": False,
    }
    controller = _controller(contract, runner)

    with pytest.raises(expected_type) as exc_info:
        controller.prepare()

    assert exc_info.value.terminal_code == terminal_code
    assert exc_info.value.evidence == runner.startup_terminal_payload


def test_container_create_failure_is_durably_typed_before_cleanup(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.docker_run_returncode = 125
    controller = _controller(contract, runner)

    with pytest.raises(RuntimeContainerCreateFailure) as exc_info:
        controller.prepare()

    expected = {
        "schema": "fortgym.m1b-startup-terminal/v1",
        "run_id": contract.run_id,
        "contract_sha256": contract.contract_sha256,
        "terminal_code": "container_create_failure",
        "injected": False,
    }
    assert exc_info.value.terminal_code == "container_create_failure"
    assert exc_info.value.evidence == expected
    assert (
        json.loads((controller.evidence_dir / "startup-terminal.json").read_text())
        == expected
    )
    assert controller.cleanup()["ok"] is True


def test_oom_fault_profile_is_explicit_create_time_and_exactly_owned(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    with pytest.raises(ValueError, match="explicit test-only authorization"):
        _controller(
            contract,
            runner,
            fault_profile=RuntimeFaultProfile.OOM_256M,
        )
    assert runner.calls == []

    unmonitored = _controller(
        contract,
        FakeDockerRunner(),
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
    )
    with pytest.raises(RuntimeStartError, match="explicit pre-readiness monitor"):
        unmonitored.prepare()

    controller = _controller(
        contract,
        runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
        pre_readiness_oom_monitor=FakeOomMonitor(
            contract.control_root / contract.run_id / "runtime",
            contract,
        ),
    )
    argv = controller.docker_run_argv()
    assert argv[argv.index("--memory") + 1] == "256m"
    assert argv[argv.index("--memory-swap") + 1] == "256m"
    assert controller.expected_labels[FAULT_PROFILE_LABEL] == "oom_256m"

    prepared = controller.prepare()
    assert prepared["fault_profile"] == "oom_256m"
    inspected = runner.containers[CONTAINER_ID]
    assert inspected["HostConfig"]["Memory"] == 256 * 1024 * 1024
    assert inspected["HostConfig"]["MemorySwap"] == 256 * 1024 * 1024
    created = json.loads(
        (controller.evidence_dir / "container-created.json").read_text()
    )
    assert created["schema"] == "fortgym.m1b-container-created/v1"
    assert created["run_id"] == contract.run_id
    assert created["contract_sha256"] == contract.contract_sha256
    assert created["container_id"] == CONTAINER_ID
    assert created["fault_profile"] == "oom_256m"
    assert created["memory_bytes"] == 256 * 1024 * 1024
    assert created["memory_swap_bytes"] == 256 * 1024 * 1024
    assert "nonce" not in created
    assert (
        created["nonce_sha256"] == hashlib.sha256(contract.nonce.encode()).hexdigest()
    )
    with pytest.raises(RuntimeOwnershipError, match="profile|ownership labels"):
        _controller(contract, runner).cleanup()
    assert CONTAINER_ID in runner.containers

    reconstructed = _controller(
        contract,
        runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
    )
    assert reconstructed.cleanup()["ok"] is True


@pytest.mark.parametrize("captured", [False, True])
def test_oom_exit_ack_written_only_after_host_counter_capture(
    tmp_path: Path, captured: bool
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    monitor = FakeOomMonitor(contract.control_root / contract.run_id / "runtime", contract)
    observations = []

    def capture(inspection: Mapping[str, Any]) -> bool:
        assert monitor.evidence_dir is not None
        assert (monitor.evidence_dir / "pre-readiness-oom-release").exists()
        observations.append(inspection)
        return captured

    monitor.capture_live_oom = capture
    controller = _controller(
        contract, runner, allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M, pre_readiness_oom_monitor=monitor,
    )
    controller.prepare()
    assert observations
    acknowledgement = controller.evidence_dir / "pre-readiness-oom-exit-ack"
    assert acknowledgement.exists() is captured
    if captured:
        values = ("fortgym.m1b-pre-readiness-oom-exit-ack/v1", contract.run_id,
                  contract.contract_sha256, contract.nonce)
        expected = hashlib.sha256(b"\0".join(value.encode() for value in values)).hexdigest()
        assert acknowledgement.read_text() == expected + "\n"
        assert acknowledgement.stat().st_mode & 0o777 == 0o644
    controller.cleanup()


def test_exact_oom_profile_exit_137_writes_routing_receipt_before_prepare_fails(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.exit_after_run = True
    runner.oom_killed_after_run = True
    runner.exit_code_after_run = 137
    monitor = FakeOomMonitor(
        contract.control_root / contract.run_id / "runtime",
        contract,
    )
    controller = _controller(
        contract,
        runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
        pre_readiness_oom_monitor=monitor,
    )

    with pytest.raises(RuntimeOomPreReadiness) as exc_info:
        controller.prepare()

    expected = {
        "schema": "fortgym.m1b-pre-readiness-oom-observation/v1",
        "run_id": contract.run_id,
        "contract_sha256": contract.contract_sha256,
        "nonce_sha256": hashlib.sha256(contract.nonce.encode()).hexdigest(),
        "container_name": controller.container_name,
        "container_id": CONTAINER_ID,
        "fault_profile": "oom_256m",
        "memory_bytes": 256 * 1024 * 1024,
        "memory_swap_bytes": 256 * 1024 * 1024,
        "state": {"running": False, "oom_killed": True, "exit_code": 137},
    }
    assert exc_info.value.terminal_code == "oom_256m_pre_readiness"
    assert exc_info.value.evidence == expected
    assert (
        json.loads((controller.evidence_dir / "pre-readiness-oom.json").read_text())
        == expected
    )
    assert not (controller.evidence_dir / "startup-terminal.json").exists()
    assert "nonce" not in expected
    assert (
        expected["nonce_sha256"] == hashlib.sha256(contract.nonce.encode()).hexdigest()
    )
    assert len(monitor.arm_calls) == 1
    assert monitor.arm_calls[0]["schema"] == "fortgym.m1b-container-created/v1"
    assert monitor.hold_present_at_arm is True
    assert monitor.release_present_at_arm is False
    assert monitor.finalize_calls == [expected]
    create_argv = next(
        call for call in runner.calls if call[:2] == ("docker", "create")
    )
    start_argv = next(call for call in runner.calls if call[:2] == ("docker", "start"))
    assert runner.calls.index(create_argv) < runner.calls.index(start_argv)

    def argv_sha256(argv: tuple[str, ...]) -> str:
        digest = hashlib.sha256()
        for value in argv:
            digest.update(value.encode())
            digest.update(b"\0")
        return digest.hexdigest()

    create_evidence = json.loads(
        (controller.evidence_dir / "container-create-command.json").read_text()
    )
    start_evidence = json.loads(
        (controller.evidence_dir / "container-start-command.json").read_text()
    )
    assert create_evidence["argv_sha256"] == argv_sha256(create_argv)
    assert start_evidence["argv_sha256"] == argv_sha256(start_argv)
    assert create_evidence["container_id"] == CONTAINER_ID
    assert start_evidence["container_id"] == CONTAINER_ID
    assert "FORTGYM_RUN_NONCE" not in json.dumps(create_evidence)
    assert (
        json.loads(
            (
                controller.evidence_dir / "pre-readiness-oom-monitor-finalize.json"
            ).read_text()
        )["ok"]
        is True
    )
    release_marker = controller.evidence_dir / "pre-readiness-oom-release"
    expected_release_token = hashlib.sha256(
        b"\0".join(
            value.encode()
            for value in (
                "fortgym.m1b-pre-readiness-oom-release-token/v1",
                contract.run_id,
                contract.contract_sha256,
                contract.nonce,
            )
        )
    ).hexdigest()
    assert release_marker.read_text() == f"{expected_release_token}\n"
    assert stat.S_IMODE(release_marker.stat().st_mode) == 0o644
    release_evidence = json.loads(
        (controller.evidence_dir / "pre-readiness-oom-release.json").read_text()
    )
    assert release_evidence["release_token_sha256"] == expected_release_token
    assert controller.cleanup()["ok"] is True
    create_count = sum(1 for call in runner.calls if call[:2] == ("docker", "create"))
    with pytest.raises(RuntimeStartError, match="hold evidence must be absent"):
        controller.prepare()
    assert (
        sum(1 for call in runner.calls if call[:2] == ("docker", "create"))
        == create_count
    )


@pytest.mark.parametrize(
    "failure_stage",
    [
        "create",
        "create_exception",
        "start",
        "start_exception",
        "start_identity",
    ],
)
def test_oom_create_and_start_failures_are_typed_before_monitor_arm(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    if failure_stage == "create":
        runner.docker_run_returncode = 125
    elif failure_stage == "create_exception":
        runner.docker_launch_exception = OSError("synthetic create exception")
    elif failure_stage == "start":
        runner.docker_start_returncode = 1
    elif failure_stage == "start_exception":
        runner.docker_start_exception = OSError("synthetic start exception")
    else:
        runner.docker_start_output = "not-the-owned-container"
    monitor = FakeOomMonitor()
    controller = _controller(
        contract,
        runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
        pre_readiness_oom_monitor=monitor,
    )

    with pytest.raises(RuntimeOomHoldFailure) as exc_info:
        controller.prepare()

    assert exc_info.value.terminal_code == "oom_256m_hold_failure"
    assert monitor.arm_calls == []
    assert monitor.finalize_calls == []
    stage = "create" if failure_stage.startswith("create") else "start"
    command_evidence = json.loads(
        (controller.evidence_dir / f"container-{stage}-command.json").read_text()
    )
    assert command_evidence["stage"] == stage
    assert command_evidence["ok"] is False
    failure = json.loads(
        (controller.evidence_dir / "oom-hold-failure.json").read_text()
    )
    assert failure["stage"] == stage
    assert failure["credit_eligible"] is False
    assert not (controller.evidence_dir / "startup-terminal.json").exists()
    cleanup = controller.cleanup()
    assert cleanup["ok"] is True
    if stage == "start":
        assert cleanup["container_id"] == CONTAINER_ID
        assert ("docker", "rm", "--force", CONTAINER_ID) in runner.calls


def test_oom_hold_timeout_and_release_write_failure_are_non_credit_and_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)

    hold_runner = FakeDockerRunner()
    hold_runner.write_oom_hold_ready = False
    hold_controller = _controller(
        contract,
        hold_runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
        pre_readiness_oom_monitor=FakeOomMonitor(
            contract.control_root / contract.run_id / "runtime",
            contract,
        ),
    )
    with pytest.raises(RuntimeOomHoldFailure, match="hold_ready"):
        hold_controller.prepare()
    hold_failure = json.loads(
        (hold_controller.evidence_dir / "oom-hold-failure.json").read_text()
    )
    assert hold_failure["stage"] == "hold_ready"
    assert hold_failure["credit_eligible"] is False
    assert not (hold_controller.evidence_dir / "pre-readiness-oom-release").exists()
    assert hold_controller.cleanup()["container_id"] == CONTAINER_ID
    assert ("docker", "rm", "--force", CONTAINER_ID) in hold_runner.calls

    release_contract = _contract(tmp_path / "release")
    release_runner = FakeDockerRunner()
    release_controller = _controller(
        release_contract,
        release_runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
        pre_readiness_oom_monitor=FakeOomMonitor(
            release_contract.control_root / release_contract.run_id / "runtime",
            release_contract,
        ),
    )
    real_atomic_write = runtime_controller_module._atomic_write
    marker_failure_injected = False

    def fail_release_marker_once(path: Path, data: bytes, **kwargs) -> None:
        nonlocal marker_failure_injected
        if path.name == "pre-readiness-oom-release" and not marker_failure_injected:
            marker_failure_injected = True
            raise OSError("synthetic release marker failure")
        real_atomic_write(path, data, **kwargs)

    monkeypatch.setattr(
        runtime_controller_module, "_atomic_write", fail_release_marker_once
    )
    with pytest.raises(RuntimeOomHoldFailure, match="release"):
        release_controller.prepare()
    release_failure = json.loads(
        (release_controller.evidence_dir / "oom-hold-failure.json").read_text()
    )
    assert release_failure["stage"] == "release"
    assert release_failure["monitor_armed"] is True
    assert release_failure["release_written"] is False
    assert release_failure["credit_eligible"] is False
    assert not (release_controller.evidence_dir / "pre-readiness-oom-release").exists()
    assert release_controller.cleanup()["container_id"] == CONTAINER_ID
    assert ("docker", "rm", "--force", CONTAINER_ID) in release_runner.calls
    with pytest.raises(RuntimeStartError, match="hold evidence must be absent"):
        release_controller.prepare()


def test_oom_monitor_is_profile_scoped_and_fails_closed_before_readiness(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    monitor = FakeOomMonitor()
    with pytest.raises(ValueError, match="authorized oom_256m profile"):
        _controller(contract, runner, pre_readiness_oom_monitor=monitor)
    assert runner.calls == []

    monitor.arm = lambda _created: {  # type: ignore[method-assign]
        "schema": "fortgym.m1b-pre-readiness-oom-monitor-arm/v1",
        "ok": False,
    }
    controller = _controller(
        contract,
        runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
        pre_readiness_oom_monitor=monitor,
    )
    with pytest.raises(RuntimeOomHoldFailure, match="monitor_arm"):
        controller.prepare()
    assert monitor.finalize_calls == []
    assert not (controller.evidence_dir / "prepare.json").exists()
    assert not (controller.evidence_dir / "pre-readiness-oom-release").exists()
    failure = json.loads(
        (controller.evidence_dir / "oom-hold-failure.json").read_text()
    )
    assert failure["monitor_armed"] is False
    assert failure["release_written"] is False
    assert failure["credit_eligible"] is False
    assert controller.cleanup()["ok"] is True


@pytest.mark.parametrize("bad_digest", [None, True, 0, "E" * 64, "e" * 63])
def test_oom_monitor_requires_exact_peer_readiness_digest_before_release(
    tmp_path: Path,
    bad_digest: object,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    monitor = FakeOomMonitor()
    original_arm = monitor.arm

    def invalid_arm(created: Mapping[str, Any]) -> Mapping[str, Any]:
        result = dict(original_arm(created))
        if bad_digest is None:
            result.pop("peer_readiness_sha256")
        else:
            result["peer_readiness_sha256"] = bad_digest
        return result

    monitor.arm = invalid_arm  # type: ignore[method-assign]
    controller = _controller(
        contract,
        runner,
        allow_test_fault_profile=True,
        fault_profile=RuntimeFaultProfile.OOM_256M,
        pre_readiness_oom_monitor=monitor,
    )

    with pytest.raises(RuntimeOomHoldFailure, match="monitor_arm"):
        controller.prepare()

    assert monitor.finalize_calls == []
    assert not (controller.evidence_dir / "pre-readiness-oom-release").exists()
    failure = json.loads(
        (controller.evidence_dir / "oom-hold-failure.json").read_text()
    )
    assert failure["monitor_armed"] is False
    assert failure["release_written"] is False
    assert failure["credit_eligible"] is False
    assert controller.cleanup()["ok"] is True


@pytest.mark.parametrize(
    ("fault_profile", "oom_killed", "exit_code"),
    [
        (None, True, 137),
        (RuntimeFaultProfile.OOM_256M, False, 137),
        (RuntimeFaultProfile.OOM_256M, True, 70),
    ],
)
def test_pre_readiness_exit_never_routes_oom_without_every_exact_bound(
    tmp_path: Path,
    fault_profile: RuntimeFaultProfile | None,
    oom_killed: bool,
    exit_code: int,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.exit_after_run = True
    runner.oom_killed_after_run = oom_killed
    runner.exit_code_after_run = exit_code
    controller = _controller(
        contract,
        runner,
        allow_test_fault_profile=fault_profile is not None,
        fault_profile=fault_profile,
        pre_readiness_oom_monitor=(
            FakeOomMonitor(
                contract.control_root / contract.run_id / "runtime",
                contract,
            )
            if fault_profile is RuntimeFaultProfile.OOM_256M
            else None
        ),
    )

    with pytest.raises(RuntimeAttestationError) as exc_info:
        controller.prepare()

    assert not isinstance(exc_info.value, RuntimeOomPreReadiness)
    assert not (controller.evidence_dir / "pre-readiness-oom.json").exists()


def test_unconfigured_cpuset_is_still_an_exact_owned_resource_profile(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner, cpuset_cpus=None)
    controller.prepare()

    runner.containers[CONTAINER_ID]["HostConfig"]["CpusetCpus"] = "7"
    with pytest.raises(RuntimeOwnershipError, match="CPU set"):
        controller.cleanup()

    assert CONTAINER_ID in runner.containers


def test_fault_classifier_returns_explicit_null_without_completed_driver_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(tmp_path)
    controller = _controller(contract, FakeDockerRunner())
    observed_kwargs: dict[str, Any] = {}

    def load(**kwargs: Any) -> None:
        observed_kwargs.update(kwargs)

    monkeypatch.setattr(fault_driver, "load_completed_fault_observation", load)
    result = controller.classify_runtime_fault(
        {"run_id": contract.run_id, "cleanup": {"ok": True}}
    )

    assert result == {
        "schema": "fortgym.runtime-fault-classifier-result/v1",
        "terminal_class": None,
        "evidence": {},
    }
    assert observed_kwargs == {
        "control_root": contract.control_root,
        "run_id": contract.run_id,
        "contract_sha256": contract.contract_sha256,
        "nonce": contract.nonce,
    }
    assert contract.nonce not in repr(result)


@pytest.mark.parametrize(
    ("gate", "terminal_class"),
    [
        (fault_driver.FaultGate.DF_KILL, "runtime_df_killed"),
        (fault_driver.FaultGate.HARNESS_KILL, "harness_killed"),
        (fault_driver.FaultGate.OOM, "runtime_oom"),
        (fault_driver.FaultGate.ENOSPC, "workspace_enospc"),
        (
            fault_driver.FaultGate.CONTAINER_RESTART,
            "runtime_container_restarted",
        ),
        (fault_driver.FaultGate.DAEMON_RESTART, "docker_daemon_restarted"),
    ],
)
def test_fault_classifier_maps_only_exact_completed_driver_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate: fault_driver.FaultGate,
    terminal_class: str,
) -> None:
    contract = _contract(tmp_path)
    controller = _controller(contract, FakeDockerRunner())
    evidence = {"driver_proved": gate.value}
    monkeypatch.setattr(
        fault_driver,
        "load_completed_fault_observation",
        lambda **_kwargs: {
            "gate": gate.value,
            "payload": {
                "classifier_evidence_schema": "fortgym.m1b-classifier-evidence/v1",
                "classifier_evidence": evidence,
            },
        },
    )

    result = controller.classify_runtime_fault(
        {"run_id": contract.run_id, "cleanup": {"ok": True}}
    )

    assert result == {
        "schema": "fortgym.runtime-fault-classifier-result/v1",
        "terminal_class": terminal_class,
        "evidence": evidence,
    }


def test_prepare_attests_container_listener_identity_seed_and_map(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)

    evidence = controller.prepare()

    assert evidence["ok"] is True
    assert evidence["container_id"] == CONTAINER_ID
    assert evidence["attestation"] == {
        "run_id": contract.run_id,
        "nonce": contract.nonce,
        "contract_sha256": contract.contract_sha256,
        "seed_tree_sha256": contract.seed_tree_sha256,
        "seed_world_sha256": contract.seed_world_sha256,
        "image_manifest_sha256": contract.image_manifest_sha256,
        "image_config_sha256": contract.image_config_sha256,
        "image_archive_sha256": contract.image_archive_sha256,
        "map_loaded": True,
    }
    exec_call = next(call for call in runner.calls if call[:2] == ("docker", "exec"))
    assert controller.container_name in exec_call
    assert f"DFHACK_PORT={contract.port}" in exec_call
    assert "/run/fortgym/run-identity.tsv" in exec_call[-1]
    assert (controller.evidence_dir / "image.inspect.json").is_file()


def test_prepare_rejects_non_loopback_listener_before_rpc_exec(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.listener_output = "LISTEN 0 128 0.0.0.0:58001 0.0.0.0:*\n"
    controller = _controller(contract, runner)

    with pytest.raises(RuntimeAttestationError, match="loopback"):
        controller.prepare()

    assert not any(call[:2] == ("docker", "exec") for call in runner.calls)


@pytest.mark.parametrize(
    "field",
    [
        "nonce",
        "seed_tree",
        "seed_world",
        "contract",
        "image_manifest",
        "image_config",
        "image_archive",
    ],
)
def test_prepare_rejects_identity_or_seed_mismatch(tmp_path: Path, field: str) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)
    fields = _attestation(contract).rstrip().split("\t")
    index = {
        "nonce": 2,
        "contract": 3,
        "seed_tree": 4,
        "seed_world": 5,
        "image_manifest": 6,
        "image_config": 7,
        "image_archive": 8,
    }[field]
    fields[index] = "e" * len(fields[index])
    runner.attestation_output = "\t".join(fields) + "\n"

    with pytest.raises(RuntimeAttestationError, match="identity or seed"):
        controller.prepare()


def test_cleanup_captures_then_removes_exact_owned_container_and_is_idempotent(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)
    controller.prepare()
    assert controller.evidence_dir.stat().st_mode & 0o7777 == 0o1777

    first = controller.cleanup()
    second = controller.cleanup()

    assert first["ok"] is True
    assert first["container_absent"] is True
    assert first["listener_absent"] is True
    assert second["ok"] is True
    assert second["already_absent"] is True
    assert controller.evidence_dir.stat().st_mode & 0o7777 == 0o700
    assert (controller.evidence_dir / "container.inspect.json").is_file()
    assert (
        controller.evidence_dir / "container.logs.stdout.txt"
    ).read_text() == runner.logs_stdout
    lifecycle = [
        json.loads(line)
        for line in (controller.evidence_dir / "lifecycle.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [item["schema"] for item in lifecycle] == [
        "fortgym.m1b-container-created/v1",
        "fortgym.m1b-runtime-prepare/v1",
        "fortgym.m1b-runtime-cleanup/v1",
        "fortgym.m1b-runtime-cleanup/v1",
    ]
    removals = [
        call for call in runner.calls if call[:3] == ("docker", "rm", "--force")
    ]
    assert removals == [("docker", "rm", "--force", CONTAINER_ID)]


def test_cleanup_refuses_name_collision_without_removing_foreign_container(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)
    controller.prepare()
    runner.containers[CONTAINER_ID]["Config"]["Labels"][CONTRACT_LABEL] = "0" * 64

    with pytest.raises(RuntimeOwnershipError, match="ownership labels"):
        controller.cleanup()

    assert CONTAINER_ID in runner.containers
    assert not any(call[:3] == ("docker", "rm", "--force") for call in runner.calls)


def test_reconcile_removes_only_exact_contract_owned_and_leaves_foreign_canary(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)
    controller.prepare()
    runner.containers[CONTAINER_ID]["Config"]["Labels"][ENTRYPOINT_LABEL] = "0" * 64
    foreign = deepcopy(runner.containers[CONTAINER_ID])
    foreign["Id"] = FOREIGN_ID
    foreign["Name"] = "/foreign-canary"
    foreign["Config"]["Labels"] = {MANAGED_LABEL: "false", CONTRACT_LABEL: "f" * 64}
    runner.containers[FOREIGN_ID] = foreign
    runner.names["foreign-canary"] = FOREIGN_ID

    first = controller.reconcile()
    second = controller.reconcile()

    assert first["ok"] is True
    assert first["removed_container_ids"] == [CONTAINER_ID]
    assert first["skipped_foreign_container_ids"] == [FOREIGN_ID]
    assert FOREIGN_ID in runner.containers
    assert second["ok"] is True
    assert second["noop"] is True
    assert second["removed_container_ids"] == []
    removals = [
        call[-1] for call in runner.calls if call[:3] == ("docker", "rm", "--force")
    ]
    assert removals == [CONTAINER_ID]
    assert FOREIGN_ID not in removals


def test_cleanup_rejects_provider_material_in_inspected_df_container(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)
    controller.prepare()
    runner.containers[CONTAINER_ID]["Config"]["Env"].append(
        "OPENROUTER_API_KEY=forbidden"
    )

    with pytest.raises(RuntimeOwnershipError, match="provider material"):
        controller.cleanup()

    assert CONTAINER_ID in runner.containers
    assert not any(call[:3] == ("docker", "rm", "--force") for call in runner.calls)


def test_provider_enabled_harness_contract_still_builds_provider_free_df_container(
    tmp_path: Path,
) -> None:
    provider = ProviderPolicy.openrouter(
        model="openai/test-model",
        provider_name="OpenAI",
        api_key="must-never-reach-docker",
        max_total_tokens=1,
        max_cost_usd=0.01,
    )
    contract = _contract(tmp_path, scripted=False, provider=provider)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)

    argv = controller.docker_run_argv()
    environment = controller.container_environment()

    assert runner.calls == []
    prepared = controller.prepare()
    cleaned = controller.cleanup()

    assert prepared["ok"] is True
    assert cleaned["ok"] is True
    assert "must-never-reach-docker" not in "\0".join(argv)
    assert not any(
        marker in item
        for item in argv
        for marker in ("OPENROUTER", "OPENAI", "ANTHROPIC", "API_KEY")
    )
    assert not any(
        marker in name
        for name in environment
        for marker in ("OPENROUTER", "OPENAI", "ANTHROPIC", "API_KEY")
    )
    assert "must-never-reach-docker" not in repr(runner.calls)


def test_invalid_cpuset_fails_before_command(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    with pytest.raises(ValueError, match="CPU set"):
        _controller(_contract(tmp_path), runner, cpuset_cpus="0;docker ps")
    assert runner.calls == []


def test_evidence_directory_must_be_scoped_under_run_control_root(
    tmp_path: Path,
) -> None:
    runner = FakeDockerRunner()
    with pytest.raises(ValueError, match="inside the run control root"):
        DockerRuntimeController(
            _contract(tmp_path),
            entrypoint_path=ENTRYPOINT,
            evidence_dir=tmp_path / "outside-control",
            runner=runner,
        )
    assert runner.calls == []


def test_cleanup_fails_if_listener_remains_after_exact_container_removal(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    controller = _controller(contract, runner)
    controller.prepare()

    original_remove = runner._remove

    def remove_but_retain_listener(
        command: tuple[str, ...], identifier: str
    ) -> CommandResult:
        result = original_remove(command, identifier)
        runner.listener_output = "LISTEN 0 128 127.0.0.1:58001 0.0.0.0:*\n"
        return result

    runner._remove = remove_but_retain_listener  # type: ignore[method-assign]
    with pytest.raises(RuntimeCleanupError, match="listener remains"):
        controller.cleanup()

    payload = json.loads((controller.evidence_dir / "cleanup.json").read_text())
    assert payload["ok"] is False
    assert payload["container_absent"] is True
    assert payload["listener_absent"] is False


def test_nonruntime_port_conflict_cleanup_preserves_exact_peer_listener(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.listener_output = "LISTEN 0 128 127.0.0.1:58001 0.0.0.0:*\n"
    controller = _controller(contract, runner)

    controller.configure_nonruntime_port_conflict_cleanup()
    cleanup = controller.cleanup()

    assert cleanup == {
        "schema": "fortgym.m1b-runtime-cleanup/v1",
        "ok": True,
        "already_absent": True,
        "container_name": controller.container_name,
        "container_absent": True,
        "listener_absent": False,
        "shared_listener_preserved": True,
        "port": contract.port,
    }
    assert not any(call[:2] == ("docker", "run") for call in runner.calls)
    assert not any(call[:3] == ("docker", "rm", "--force") for call in runner.calls)


def test_nonruntime_port_conflict_cleanup_rejects_unsafe_listener(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.listener_output = "LISTEN 0 128 0.0.0.0:58001 0.0.0.0:*\n"
    controller = _controller(contract, runner)
    controller.configure_nonruntime_port_conflict_cleanup()

    with pytest.raises(RuntimeCleanupError, match="listener remains"):
        controller.cleanup()

    cleanup = json.loads((controller.evidence_dir / "cleanup.json").read_text())
    assert cleanup["ok"] is False
    assert cleanup["listener_absent"] is False
    assert cleanup["shared_listener_preserved"] is False


def test_cleanup_still_removes_exact_container_when_log_capture_fails(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    runner = FakeDockerRunner()
    runner.logs_returncode = 1
    controller = _controller(contract, runner)
    controller.prepare()

    with pytest.raises(RuntimeCleanupError, match="log capture failed"):
        controller.cleanup()

    assert CONTAINER_ID not in runner.containers
    payload = json.loads((controller.evidence_dir / "cleanup.json").read_text())
    assert payload["ok"] is False
    assert payload["container_absent"] is True
    assert payload["listener_absent"] is True
