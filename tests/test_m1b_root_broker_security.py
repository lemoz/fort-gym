from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fort_gym.bench.run.live_acceptance import (
    FROZEN_GATE_PLAN,
    CleanupPassResult,
    LiveAcceptanceBatchController,
    LocalCreditImport,
    SourceManifestLock,
    authorize_private_m1b_live_acceptance,
)
from infra.m1b.root_broker import (
    _FROZEN_ATTEMPTS,
    _RUNTIME_IMAGE_ENVIRONMENT,
    _RUNTIME_IMAGE_LABELS,
    FROZEN_ACCEPTANCE_SHA256,
    FROZEN_PLAN_SHA256,
    BrokerError,
    BrokerLayout,
    CommandCapture,
    RootBroker,
    _AttemptMirror,
    _BatchPhase,
    _failure_payload,
    _LedgerSnapshot,
    _MountIdentity,
    _ProcessIdentity,
    _RecoveryDecision,
    _RunBinding,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
MANIFEST = "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
CONFIG = "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
ARCHIVE = "87d66d26553cb271af1b784405d63ea6b95f3bbe20e9429f05e6412133d1f43a"


@pytest.mark.parametrize("decision", ["GO", "INCOMPLETE_NO_GO"])
def test_recovery_attestation_rechecks_loaded_decision_after_initial_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    request = {"batch_id": "batch-one", "request_id": SHA_A}
    monkeypatch.setattr(broker, "_state_records", lambda: [
        {**request, "event": "recovery_boundary"}
    ])
    if decision == "GO":
        with pytest.raises(BrokerError, match="cannot export a GO"):
            broker._validate_recovery_attestation_decision(request, {"decision": decision})
    else:
        broker._validate_recovery_attestation_decision(request, {"decision": decision})


@pytest.mark.parametrize("variant", ["no_go", "go", "foreign", "missing"])
def test_ambiguous_action_attestation_cannot_claim_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    root = broker.layout.batch_evidence_root("batch-one")
    path = root / "control" / "seal.json"
    path.parent.mkdir(parents=True)
    seal = {
        "schema": "fortgym.m1b-live-acceptance-seal/v1",
        "batch_id": "foreign" if variant == "foreign" else "batch-one",
        "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
        "plan_sha256": FROZEN_PLAN_SHA256,
        "decision": "GO" if variant == "go" else "INCOMPLETE_NO_GO",
    }
    if variant != "missing":
        path.write_text(json.dumps(seal))
    monkeypatch.setattr(broker, "_required_evidence_owner_uid", lambda: os.getuid())
    if variant == "no_go":
        broker._require_failed_seal_for_recovery_attestation({"batch_id": "batch-one"})
    else:
        with pytest.raises(BrokerError):
            broker._require_failed_seal_for_recovery_attestation({"batch_id": "batch-one"})


def test_root_broker_failure_payload_exposes_only_a_reason_fingerprint() -> None:
    payload = _failure_payload(BrokerError("fixed semantic rejection"))
    assert payload == {
        "schema": "fortgym.m1b-root-broker-error/v1",
        "ok": False,
        "error_code": "broker_brokererror",
        "reason_sha256": hashlib.sha256(b"fixed semantic rejection").hexdigest(),
    }
    assert "fixed semantic rejection" not in json.dumps(payload)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _frozen_plan() -> dict[str, Any]:
    return {
        "schema": "fortgym.m1b-live-acceptance-plan/v1",
        "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
        "max_real_runtime_attempts": 26,
        "required_cleanup_passes": 2,
        "gates": [
            gate.payload(gate_index=index)
            for index, gate in enumerate(FROZEN_GATE_PLAN, start=1)
        ],
    }


def _strict_opening(
    broker: RootBroker,
    *,
    batch_id: str = "batch-one",
) -> dict[str, Any]:
    packet_source = broker.layout.source_manifest_path
    batch_source = (
        broker.layout.batch_evidence_root(batch_id) / "inputs" / "source-manifest.json"
    )
    packet_source.parent.mkdir(mode=0o755, parents=True)
    batch_source.parent.mkdir(mode=0o700, parents=True)
    encoded = b'{"schema":"source-test"}\n'
    packet_source.write_bytes(encoded)
    batch_source.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    broker._evidence_owner_uid = os.getuid()
    return {
        "sequence": 1,
        "batch_id": batch_id,
        "event": "batch_opened",
        "record_sha256": _digest("batch-opened"),
        "payload": {
            "plan": _frozen_plan(),
            "plan_sha256": FROZEN_PLAN_SHA256,
            "source_manifest": {
                "path": "inputs/source-manifest.json",
                "sha256": digest,
                "size_bytes": len(encoded),
            },
            "local_credit_boundaries": {
                "PORT-1": "complete_local_gate",
                "ORPHAN-1": "local_subprocedure",
                "PROVIDER-ENV": "complete_local_gate",
                "CAP-FAKE": "complete_local_gate",
            },
        },
    }


def _local_credit_record(gate_id: str, sequence: int) -> dict[str, Any]:
    gate = next(item for item in FROZEN_GATE_PLAN if item.gate_id == gate_id)
    return {
        "sequence": sequence,
        "batch_id": "batch-one",
        "event": "local_credit_imported",
        "record_sha256": _digest(f"local-{gate_id}"),
        "payload": {
            "gate_id": gate_id,
            "scope": (
                "local_subprocedure" if gate_id == "ORPHAN-1" else "complete_local_gate"
            ),
            "criteria_passed": list(gate.criteria),
            "evidence": [
                {"path": f"local/{gate_id}.json", "sha256": SHA_A, "size_bytes": 1}
            ],
        },
    }


def _layout(tmp_path: Path) -> BrokerLayout:
    return BrokerLayout(
        repo_root=(tmp_path / "repo").resolve(),
        state_root=(tmp_path / "state").resolve(),
        venv_python=(tmp_path / "venv/bin/python").resolve(),
        image_archive=(tmp_path / "runtime.tar.zst").resolve(),
        root_evidence_root=(tmp_path / "root-evidence").resolve(),
        packet_root=(tmp_path / "packet").resolve(),
    )


def _binding(tmp_path: Path) -> _RunBinding:
    secret_nonce = "12" * 16
    secret_path = str((tmp_path / "private/run/control").resolve())
    environment = {
        "DFHACK_PORT": "58000",
        "FORTGYM_CONTRACT_SHA256": SHA_A,
        "FORTGYM_RUN_ID": "m1b-runtime-one",
        "FORTGYM_RUN_NONCE": secret_nonce,
        "FORTGYM_EVIDENCE_DIR": secret_path,
    }
    contract = SimpleNamespace(
        run_id="m1b-runtime-one",
        nonce=secret_nonce,
        contract_sha256=SHA_A,
        seed_tree_sha256=SHA_B,
        seed_world_sha256=SHA_C,
        image_manifest_sha256=MANIFEST,
        image_config_sha256=CONFIG,
        image_archive_sha256=ARCHIVE,
    )
    controller = SimpleNamespace(
        contract=contract,
        container_name="fortgym-m1b-runtime-one-aaaaaaaaaaaa",
        expected_labels={
            "fortgym.m1b.managed": "true",
            "fortgym.m1b.run_id": contract.run_id,
            "fortgym.m1b.contract_sha256": SHA_A,
        },
        image_reference=f"sha256:{MANIFEST}",
        image_config_reference=f"sha256:{CONFIG}",
        resolved_image_reference=f"sha256:{MANIFEST}",
        memory_bytes=4 * 1024 * 1024 * 1024,
        cpuset_cpus=None,
        entrypoint_path=(tmp_path / "repo/infra/m1b/runtime_entrypoint.sh").resolve(),
        evidence_dir=(tmp_path / "private/run/control").resolve(),
        container_environment=lambda: dict(environment),
    )
    return _RunBinding(
        run_id=contract.run_id,
        contract_sha256=SHA_A,
        nonce_sha256=hashlib.sha256(secret_nonce.encode()).hexdigest(),
        cohort_sha256=SHA_B,
        container_name=controller.container_name,
        container_id="d" * 64,
        port=58_000,
        runtime_controller=controller,
        launch={},
        launch_sha256=SHA_C,
    )


def _inspection(binding: _RunBinding) -> dict[str, Any]:
    controller = binding.runtime_controller
    return {
        "Id": binding.container_id,
        "Name": f"/{binding.container_name}",
        "Image": f"sha256:{MANIFEST}",
        "RestartCount": 0,
        "State": {
            "Status": "running",
            "Running": True,
            "Dead": False,
            "Restarting": False,
            "OOMKilled": False,
            "ExitCode": 0,
            "Pid": 3001,
        },
        "Config": {
            "Image": f"sha256:{MANIFEST}",
            "Labels": {
                **_RUNTIME_IMAGE_LABELS,
                **controller.expected_labels,
            },
            "Env": [
                f"{name}={value}"
                for name, value in {
                    **_RUNTIME_IMAGE_ENVIRONMENT,
                    **controller.container_environment(),
                }.items()
            ],
            "Entrypoint": ["/bin/bash"],
            "Cmd": ["/opt/fortgym-m1b/runtime_entrypoint.sh"],
        },
        "HostConfig": {
            "NetworkMode": "host",
            "Memory": controller.memory_bytes,
            "MemorySwap": controller.memory_bytes,
            "PidsLimit": 256,
            "CpusetCpus": "",
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "SecurityOpt": ["no-new-privileges:true", "seccomp=unconfined"],
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "Privileged": False,
            "Devices": [],
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(controller.entrypoint_path),
                "Destination": "/opt/fortgym-m1b/runtime_entrypoint.sh",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(
                    Path(controller.entrypoint_path).parents[3]
                    / "root-evidence"
                    / "bind-sources"
                    / binding.run_id
                    / "artifacts"
                ),
                "Destination": "/artifacts",
                "RW": True,
            },
        ],
    }


def _pin_test_stage(
    broker: RootBroker,
    binding: _RunBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = broker._root_staged_evidence_path(binding.run_id)
    stage.mkdir(mode=0o700, parents=True)
    monkeypatch.setattr(
        broker,
        "_mount_record",
        lambda path: {"mountpoint": str(stage)} if Path(path) == stage else None,
    )


def test_container_projection_hashes_secrets_and_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    _pin_test_stage(broker, binding, monkeypatch)
    document = _inspection(binding)

    broker._validate_owned_container_document(binding, document)
    projected = broker._sanitize_container_inspection(binding, document)
    payload = json.loads(projected)[0]

    assert payload["FortGymProjectionSchema"] == (
        "fortgym.m1b-container-inspect-projection/v1"
    )
    assert set(payload) == {
        "FortGymProjectionSchema",
        "Id",
        "Name",
        "Image",
        "RestartCount",
        "State",
        "Config",
        "HostConfig",
        "EnvAttestations",
        "MountAttestations",
    }
    assert binding.runtime_controller.contract.nonce not in projected
    assert str(binding.runtime_controller.evidence_dir) not in projected
    assert str(binding.runtime_controller.entrypoint_path) not in projected
    assert "Env" not in payload["Config"]
    assert all(
        set(item) == {"name", "value_sha256"} for item in payload["EnvAttestations"]
    )
    assert all(
        set(item) == {"destination", "source_sha256", "rw", "type"}
        for item in payload["MountAttestations"]
    )


def test_container_labels_are_exact_pinned_image_and_run_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    _pin_test_stage(broker, binding, monkeypatch)
    document = _inspection(binding)
    expected = {
        **_RUNTIME_IMAGE_LABELS,
        **binding.runtime_controller.expected_labels,
    }
    assert document["Config"]["Labels"] == expected
    broker._validate_owned_container_document(binding, document)

    missing = _inspection(binding)
    missing["Config"]["Labels"].pop("org.opencontainers.image.revision")
    with pytest.raises(BrokerError, match="labels differ"):
        broker._validate_owned_container_document(binding, missing)

    changed = _inspection(binding)
    changed["Config"]["Labels"]["org.opencontainers.image.version"] = "poison"
    with pytest.raises(BrokerError, match="labels differ"):
        broker._validate_owned_container_document(binding, changed)

    extra = _inspection(binding)
    extra["Config"]["Labels"]["fortgym.untrusted"] = "true"
    with pytest.raises(BrokerError, match="labels differ"):
        broker._validate_owned_container_document(binding, extra)


def test_container_identity_includes_exact_pinned_image_environment_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    _pin_test_stage(broker, binding, monkeypatch)
    document = _inspection(binding)
    assert document["Image"] == f"sha256:{MANIFEST}"
    assert set(document["Config"]["Env"]) == {
        *(f"{name}={value}" for name, value in _RUNTIME_IMAGE_ENVIRONMENT.items()),
        *(
            f"{name}={value}"
            for name, value in binding.runtime_controller.container_environment().items()
        ),
    }
    broker._validate_owned_container_document(binding, document)

    config_identity = _inspection(binding)
    config_identity["Image"] = f"sha256:{CONFIG}"
    with pytest.raises(BrokerError, match="isolation profile differs"):
        broker._validate_owned_container_document(binding, config_identity)

    missing_image_environment = _inspection(binding)
    missing_image_environment["Config"]["Env"] = [
        item
        for item in missing_image_environment["Config"]["Env"]
        if not item.startswith("PATH=")
    ]
    with pytest.raises(BrokerError, match="environment escapes"):
        broker._validate_owned_container_document(binding, missing_image_environment)

    changed_image_environment = _inspection(binding)
    path_index = next(
        index
        for index, item in enumerate(changed_image_environment["Config"]["Env"])
        if item.startswith("PATH=")
    )
    changed_image_environment["Config"]["Env"][path_index] = "PATH=/poison"
    with pytest.raises(BrokerError, match="environment escapes"):
        broker._validate_owned_container_document(binding, changed_image_environment)


@pytest.mark.parametrize(
    "poison", ["OPENAI_API_KEY=sk-poison", "LD_PRELOAD=/tmp/evil.so"]
)
def test_container_validation_rejects_every_extra_environment(
    tmp_path: Path,
    poison: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    _pin_test_stage(broker, binding, monkeypatch)
    document = _inspection(binding)
    document["Config"]["Env"].append(poison)
    with pytest.raises(BrokerError):
        broker._validate_owned_container_document(binding, document)


def test_container_validation_rejects_duplicate_environment_and_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    _pin_test_stage(broker, binding, monkeypatch)
    document = _inspection(binding)
    document["Config"]["Env"].append(document["Config"]["Env"][0])
    with pytest.raises(BrokerError, match="not unique"):
        broker._validate_owned_container_document(binding, document)

    document = _inspection(binding)
    document["Mounts"] = [document["Mounts"][0], dict(document["Mounts"][0])]
    with pytest.raises(BrokerError, match="duplicated"):
        broker._validate_owned_container_document(binding, document)


def test_runtime_attestation_projection_never_returns_nonce(tmp_path: Path) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    contract = binding.runtime_controller.contract
    raw = (
        "\t".join(  # noqa: FLY002 - mirrors the tab protocol under test
            (
                "FORTGYM_ATTEST",
                binding.run_id,
                contract.nonce,
                binding.contract_sha256,
                contract.seed_tree_sha256,
                contract.seed_world_sha256,
                contract.image_manifest_sha256,
                contract.image_config_sha256,
                contract.image_archive_sha256,
                "MAP_LOADED",
            )
        )
        + "\n"
    )
    capture = broker._validate_command_result(
        {"action": "docker_exec_attest"},
        binding,
        CommandCapture(("docker",), 0, raw, ""),
    )
    assert contract.nonce not in capture.stdout
    assert json.loads(capture.stdout) == {
        "schema": "fortgym.m1b-runtime-attestation-projection/v1",
        "run_id": binding.run_id,
        "nonce_sha256": binding.nonce_sha256,
        "contract_sha256": binding.contract_sha256,
        "seed_tree_sha256": SHA_B,
        "seed_world_sha256": SHA_C,
        "image_manifest_sha256": MANIFEST,
        "image_config_sha256": CONFIG,
        "image_archive_sha256": ARCHIVE,
        "map_state": "MAP_LOADED",
    }

    noisy = broker._validate_command_result(
        {"action": "docker_exec_attest"},
        binding,
        CommandCapture(
            ("docker",),
            0,
            "DFHack command output\n\x1b[32m" + raw.rstrip() + "\x1b[0m\n",
            "",
        ),
    )
    assert noisy.stdout == capture.stdout

    with pytest.raises(BrokerError, match="marker cardinality differs"):
        broker._validate_command_result(
            {"action": "docker_exec_attest"},
            binding,
            CommandCapture(("docker",), 0, raw + raw, ""),
        )

    with pytest.raises(BrokerError, match="marker cardinality differs"):
        broker._validate_command_result(
            {"action": "docker_exec_attest"},
            binding,
            CommandCapture(("docker",), 0, "DFHack command output\n", ""),
        )


def test_read_only_inspect_reuses_only_exact_prior_removed_container_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    removed_id = "f" * 64
    monkeypatch.setattr(broker, "_root_container_id", lambda _run_id: None)
    monkeypatch.setattr(
        broker, "_prior_removed_container_id", lambda _run_id: removed_id
    )
    assert (
        broker._container_id_for_action("m1b-runtime-one", "docker_container_inspect")
        == removed_id
    )
    assert (
        broker._container_id_for_action("m1b-runtime-one", "docker_remove")
        == removed_id
    )
    assert broker._container_id_for_action("m1b-runtime-one", "docker_start") is None


def test_canary_absence_is_only_rc_zero_exact_empty(tmp_path: Path) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    request = {"action": "canary_absence"}
    accepted = broker._validate_command_result(
        request,
        None,
        CommandCapture(("docker",), 0, "", ""),
    )
    assert accepted.returncode == 0 and accepted.stdout == ""
    with pytest.raises(BrokerError, match="returned an object"):
        broker._validate_command_result(
            request,
            None,
            CommandCapture(("docker",), 0, "d" * 64 + "\n", ""),
        )
    failed = broker._validate_command_result(
        request,
        None,
        CommandCapture(("docker",), 1, "", "poison-secret"),
    )
    assert failed.returncode == 1
    assert "poison-secret" not in failed.stderr


def test_recovery_has_one_root_live_epoch_and_no_third_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    request = {
        "batch_id": "batch-one",
        "grant_kind": "batch_canary",
        "attempt_id": None,
        "gate_id": "CLEANUP",
        "action": "canary_remove",
    }
    record = {
        "batch_id": "batch-one",
        "event": "action_completed",
        "data": {"action": "canary_remove", "attempt_id": None},
    }
    monkeypatch.setattr(broker, "_state_records", lambda: [record])
    monkeypatch.setattr(broker, "_matching_action_grants", lambda _request: [{}])
    monkeypatch.setattr(
        broker,
        "_root_live_recovery_state",
        lambda _request, binding: (True, "canary_already_absent"),
    )
    assert broker._recovery_decision(request, binding=None) == _RecoveryDecision(
        epoch=1,
        noop=True,
        reason="canary_already_absent",
    )
    monkeypatch.setattr(broker, "_matching_action_grants", lambda _request: [{}, {}])
    with pytest.raises(BrokerError, match="exhausted"):
        broker._recovery_decision(request, binding=None)


def test_one_shot_recovery_scan_accepts_prior_reusable_inspection_grants(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    broker = RootBroker(
        layout=layout,
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    layout.grant_root.mkdir(parents=True, mode=0o700)
    request = {
        "batch_id": "batch-one",
        "grant_kind": "batch_canary",
        "attempt_id": None,
        "attempt_identity_sha256": None,
        "gate_id": "CLEANUP",
        "action": "canary_remove",
        "logical_argv_sha256": SHA_A,
    }

    def grant(*, action: str, request_id: str, one_shot: bool) -> dict[str, Any]:
        return {
            "schema": "fortgym.m1b-root-broker-action-grant/v1",
            "acceptance_sha256": FROZEN_ACCEPTANCE_SHA256,
            "plan_sha256": FROZEN_PLAN_SHA256,
            "batch_id": "batch-one",
            "grant_kind": "batch_canary",
            "attempt_id": None,
            "attempt_identity_sha256": None,
            "gate_id": "CLEANUP",
            "action": action,
            "logical_argv_sha256": SHA_A,
            "recovery_epoch": 0,
            "request_id": request_id,
            "batch_ledger_head_sha256": SHA_B,
            "one_shot": one_shot,
        }

    inspection = grant(
        action="canary_inspect",
        request_id=_digest("inspection"),
        one_shot=False,
    )
    removal = grant(
        action="canary_remove",
        request_id=_digest("removal"),
        one_shot=True,
    )
    (layout.grant_root / "inspection.json").write_text(
        json.dumps(inspection), encoding="utf-8"
    )
    (layout.grant_root / "removal.json").write_text(
        json.dumps(removal), encoding="utf-8"
    )

    assert broker._matching_action_grants(request) == [removal]

    inspection["one_shot"] = True
    (layout.grant_root / "inspection.json").write_text(
        json.dumps(inspection), encoding="utf-8"
    )
    with pytest.raises(BrokerError, match="grant schema"):
        broker._matching_action_grants(request)


def test_trusted_path_keyset_and_installed_source_tree_are_exact(
    tmp_path: Path,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    flags = {
        "source_root_owned_nonwritable",
        "venv_owned_nonwritable",
        "interpreter_owned_nonwritable",
        "site_packages_owned_nonwritable",
        "isolated_source_pth_exact",
        "broker_owned_nonwritable",
        "packet_metadata_root_owned_readable",
        "packet_archives_root_only",
        "broker_receipts_root_only",
        "docker_server_29_1_3_containerd_store",
        "runtime_archive_digest_exact",
        "provider_helper_bpf_attested",
    }
    digest_keys = {
        "docker_runtime_attestation_sha256",
        "runtime_archive_attestation_sha256",
        "provider_helper_bpf_attestation_sha256",
        "docker_image_descriptor_attestation_sha256",
    }
    trusted = {
        "schema": "fortgym.m1b-trusted-host-paths/v1",
        "ok": True,
        **{name: True for name in flags},
        **{name: SHA_A for name in digest_keys},
    }
    broker._validate_trusted_paths_document(trusted)
    with pytest.raises(BrokerError, match="trusted bootstrap"):
        broker._validate_trusted_paths_document({**trusted, "unexpected": True})
    with pytest.raises(BrokerError, match="trusted bootstrap"):
        broker._validate_trusted_paths_document(
            {**trusted, "isolated_source_pth_exact": False}
        )

    source_path = broker.layout.repo_root / "pkg" / "module.py"
    source_path.parent.mkdir(mode=0o755, parents=True)
    source_path.write_bytes(b"VALUE = 1\n")
    source_path.chmod(0o644)
    item = {
        "path": "pkg/module.py",
        "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "size_bytes": source_path.stat().st_size,
        "mode": "0644",
    }
    source = {
        "schema": "fortgym.m1b-live-source-manifest/v1",
        "base_head": "236d3187c548b9bc03c4c99829d479d381a008d5",
        "branch": "codex/test",
        "file_count": 1,
        "file_bytes": item["size_bytes"],
        "tree_sha256": hashlib.sha256(
            json.dumps(
                [item], ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "files": [item],
        "runtime_proto": {
            "canonical_runtime": {
                "runtime_binding_sha256": (
                    "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f"
                )
            },
            "wire_reference": {},
        },
    }
    broker._verify_installed_source_manifest(source)
    source_path.write_bytes(b"VALUE = 2\n")
    with pytest.raises(BrokerError, match="installed source file differs"):
        broker._verify_installed_source_manifest(source)


def test_process_pid_starttime_swap_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    owned = SimpleNamespace(
        container_id=binding.container_id,
        harness_pid=4242,
        harness_process_group_id=4242,
        runtime_host_pid=4343,
        supervisor_pid=4444,
    )
    monkeypatch.setattr(broker, "_load_owned_run", lambda _request: owned)
    monkeypatch.setattr(
        broker,
        "_inspect_container_live",
        lambda _binding, allow_absent: ({}, CommandCapture((), 0, "", "")),
    )
    snapshots = iter(
        (
            (10, 4242, 4000, "S", {}, b"python\0--external-run-id\0m1b-runtime-one\0"),
            (11, 4242, 4000, "S", {}, b"python\0--external-run-id\0m1b-runtime-one\0"),
        )
    )
    monkeypatch.setattr(broker, "_proc_snapshot", lambda _pid: next(snapshots))
    broker._derived_target_pid = 4242
    with pytest.raises(BrokerError, match="changed during revalidation"):
        broker._process_identity_for_action(
            {"action": "pause_peer_harness", "parameters": {}}, binding
        )


@pytest.mark.parametrize("target", ["harness", "supervisor", "supervisor_child"])
@pytest.mark.parametrize("states", [("R", "S"), ("S", "R"), ("S", "Z"), ("Z", "S")])
def test_process_scheduler_state_is_not_identity_but_dead_state_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
    states: tuple[str, str],
) -> None:
    broker = RootBroker(layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid())
    binding = _binding(tmp_path)
    owned = SimpleNamespace(container_id=binding.container_id, harness_pid=4242,
                            harness_process_group_id=4242, runtime_host_pid=4343,
                            supervisor_pid=4444)
    environment = {
        "FORT_GYM_RUN_ID": binding.run_id,
        "FORT_GYM_RUN_CONTRACT_SHA256": binding.contract_sha256,
        "FORT_GYM_RUN_NONCE": binding.runtime_controller.contract.nonce,
    }
    command = f"python\0--external-run-id\0{binding.run_id}\0".encode()
    pairs = {
        4242: iter(states if target != "supervisor" else ("S", "S")),
        4444: iter(states if target == "supervisor" else ("S", "S")),
    }

    def snapshot(pid):
        state = next(pairs[pid])
        if pid == 4242:
            return (10, 4242, 4444, state, environment, command)
        return (77, 4444, 1, state, {}, b"manager\0")

    monkeypatch.setattr(broker, "_load_owned_run", lambda _request: owned)
    monkeypatch.setattr(broker, "_inspect_container_live", lambda *args, **kwargs: ({}, CommandCapture((), 0, "", "")))
    monkeypatch.setattr(broker, "_proc_snapshot", snapshot)
    request = {"action": "pause_cohort_harness" if target == "harness" else "signal_supervisor",
               "parameters": {"supervisor_start_ticks": 77}}
    if "Z" in states:
        with pytest.raises(BrokerError, match="already terminal"):
            broker._process_identity_for_action(request, binding)
    else:
        identity, observed_state = broker._process_identity_for_action(request, binding)
        assert identity.pid == (4242 if target == "harness" else 4444)
        assert observed_state == ("S" if target == "supervisor_child" else states[1])


def test_pidfd_revalidation_never_signals_a_reused_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    environment = {"FORT_GYM_RUN_ID": "m1b-runtime-one"}
    broker._execution_process_identity = _ProcessIdentity(
        pid=4242,
        starttime=10,
        process_group_id=4242,
        parent_pid=4000,
        environment_sha256=hashlib.sha256(
            json.dumps(environment, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        command_sha256=hashlib.sha256(b"owned\0").hexdigest(),
        role="harness",
    )
    read_fd, write_fd = os.pipe()
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(os, "pidfd_open", lambda _pid, _flags: read_fd, raising=False)
    monkeypatch.setattr(broker, "_pidfd_target_pid", lambda _fd: 4242)
    monkeypatch.setattr(
        broker,
        "_proc_snapshot",
        lambda _pid: (11, 4242, 4000, "S", environment, b"foreign\0"),
    )
    monkeypatch.setattr(
        signal,
        "pidfd_send_signal",
        lambda *args: sent.append(tuple(args)),
        raising=False,
    )
    try:
        with pytest.raises(BrokerError, match="changed before delivery"):
            broker._execute_pidfd_signal(
                {"action": "pause_peer_harness"},
                actual_argv=("/bin/kill", "-STOP", "--", "4242"),
            )
    finally:
        os.close(write_fd)
    assert sent == []


def test_post_signal_state_waits_for_the_bound_task_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    broker = RootBroker(
        layout=_layout(tmp_path),
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
        sleep=sleeps.append,
    )
    broker._execution_process_identity = _ProcessIdentity(
        pid=4242,
        starttime=10,
        process_group_id=4242,
        parent_pid=4000,
        environment_sha256=SHA_A,
        command_sha256=SHA_B,
        role="harness",
    )
    observations = iter(
        (
            (10, 4242, 4000, "S", {}, b"owned\0"),
            (10, 4242, 4000, "S", {}, b"owned\0"),
            (10, 4242, 4000, "T", {}, b"owned\0"),
        )
    )
    monkeypatch.setattr(broker, "_proc_snapshot", lambda _pid: next(observations))

    broker._require_post_signal_state(stopped=True)

    assert sleeps == [0.025, 0.025]


def test_post_signal_state_rejects_identity_drift_during_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path),
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
        sleep=lambda _seconds: None,
    )
    broker._execution_process_identity = _ProcessIdentity(
        pid=4242,
        starttime=10,
        process_group_id=4242,
        parent_pid=4000,
        environment_sha256=SHA_A,
        command_sha256=SHA_B,
        role="harness",
    )
    observations = iter(
        (
            (10, 4242, 4000, "S", {}, b"owned\0"),
            (11, 4242, 4000, "T", {}, b"foreign\0"),
        )
    )
    monkeypatch.setattr(broker, "_proc_snapshot", lambda _pid: next(observations))

    with pytest.raises(BrokerError, match="identity changed"):
        broker._require_post_signal_state(stopped=True)


def test_forged_supervisor_owner_cannot_target_a_foreign_canary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    owned = SimpleNamespace(
        container_id=binding.container_id,
        harness_pid=4242,
        harness_process_group_id=4242,
        runtime_host_pid=4343,
        # A forged owner/journal names the unrelated live canary as manager.
        supervisor_pid=4444,
    )
    child_environment = {
        "FORT_GYM_RUN_ID": binding.run_id,
        "FORT_GYM_RUN_CONTRACT_SHA256": binding.contract_sha256,
        "FORT_GYM_RUN_NONCE": binding.runtime_controller.contract.nonce,
    }
    child_command = b"python\0--external-run-id\0m1b-runtime-one\0"

    def snapshot(pid: int) -> tuple[int, int, int, str, dict[str, str], bytes]:
        if pid == 4444:
            # The attacker supplies the canary's correct start ticks.
            return (77, 4444, 1111, "S", {}, b"foreign-canary\0")
        if pid == 4242:
            # The owned harness remains a child of its real manager, not the canary.
            return (10, 4242, 4555, "S", child_environment, child_command)
        raise AssertionError(f"unexpected PID {pid}")

    pidfd_opened: list[int] = []
    signals: list[tuple[Any, ...]] = []
    monkeypatch.setattr(broker, "_load_owned_run", lambda _request: owned)
    monkeypatch.setattr(
        broker,
        "_inspect_container_live",
        lambda _binding, allow_absent: ({}, CommandCapture((), 0, "", "")),
    )
    monkeypatch.setattr(broker, "_proc_snapshot", snapshot)
    monkeypatch.setattr(broker, "_append_state_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        os,
        "pidfd_open",
        lambda pid, _flags: pidfd_opened.append(pid),
        raising=False,
    )
    monkeypatch.setattr(
        signal,
        "pidfd_send_signal",
        lambda *args: signals.append(tuple(args)),
        raising=False,
    )
    broker._derived_target_pid = 4444
    request = {
        "action": "signal_supervisor",
        "parameters": {"supervisor_start_ticks": 77},
    }
    with pytest.raises(BrokerError, match="live parent of the owned harness"):
        broker._revalidate_execution_target(request, binding)
        broker._execute_pidfd_signal(
            request,
            actual_argv=("/bin/kill", "-KILL", "--", "4444"),
        )
    assert pidfd_opened == []
    assert signals == []


def test_supervisor_child_is_rechecked_after_pidfd_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    manager_environment: dict[str, str] = {}
    child_environment = {"FORT_GYM_RUN_ID": "m1b-runtime-one"}
    manager_command = b"manager\0"
    child_command = b"owned-harness\0"
    broker._execution_process_identity = _ProcessIdentity(
        pid=4444,
        starttime=77,
        process_group_id=4444,
        parent_pid=1111,
        environment_sha256=hashlib.sha256(
            json.dumps(
                manager_environment, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        command_sha256=hashlib.sha256(manager_command).hexdigest(),
        role="supervisor",
    )
    broker._execution_supervisor_child_identity = _ProcessIdentity(
        pid=4242,
        starttime=10,
        process_group_id=4242,
        parent_pid=4444,
        environment_sha256=hashlib.sha256(
            json.dumps(
                child_environment, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        command_sha256=hashlib.sha256(child_command).hexdigest(),
        role="harness",
    )
    read_fd, write_fd = os.pipe()
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(os, "pidfd_open", lambda _pid, _flags: read_fd, raising=False)
    monkeypatch.setattr(broker, "_pidfd_target_pid", lambda _fd: 4444)

    def snapshot(pid: int) -> tuple[int, int, int, str, dict[str, str], bytes]:
        if pid == 4444:
            return (77, 4444, 1111, "S", manager_environment, manager_command)
        if pid == 4242:
            return (10, 4242, 4555, "S", child_environment, child_command)
        raise AssertionError(f"unexpected PID {pid}")

    monkeypatch.setattr(broker, "_proc_snapshot", snapshot)
    monkeypatch.setattr(
        signal,
        "pidfd_send_signal",
        lambda *args: sent.append(tuple(args)),
        raising=False,
    )
    try:
        with pytest.raises(BrokerError, match="child changed before supervisor"):
            broker._execute_pidfd_signal(
                {"action": "signal_supervisor"},
                actual_argv=("/bin/kill", "-KILL", "--", "4444"),
            )
    finally:
        os.close(write_fd)
    assert sent == []


@pytest.mark.parametrize("variant", ["valid", "missing", "duplicate", "foreign", "invalid"])
def test_enospc_covered_directory_requires_unique_root_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    public = {
        "run_id": "run-one", "contract_sha256": SHA_A, "nonce_sha256": SHA_B,
        "cohort_sha256": SHA_C, "container_name": "owned", "port": 58001,
        "container_id": None,
    }
    record = {
        "batch_id": "batch-one", "event": "execution_target_bound",
        "data": {
            "action": "mount_enospc", "binding": public.copy(),
            "covered_directory": {
                "path": str(broker.layout.artifacts_root / "run-one"),
                "device": 1, "inode": 2,
            },
        },
    }
    records = [record]
    if variant == "missing":
        records = []
    elif variant == "duplicate":
        records = [record, record]
    elif variant == "foreign":
        record["data"]["binding"]["contract_sha256"] = SHA_B
    elif variant == "invalid":
        record["data"]["covered_directory"]["inode"] = True
    monkeypatch.setattr(broker, "_state_records", lambda: records)
    # Container binding can be acquired after the prelaunch mount, but its
    # immutable run identity must still match the root record exactly.
    monkeypatch.setattr(broker, "_public_binding", lambda binding: {
        **public, "container_id": "d" * 64
    })
    binding = SimpleNamespace(run_id="run-one")
    if variant == "valid":
        assert broker._enospc_covered_directory({"batch_id": "batch-one"}, binding) == (1, 2)
    else:
        with pytest.raises(BrokerError, match="covered directory"):
            broker._enospc_covered_directory({"batch_id": "batch-one"}, binding)


@pytest.mark.parametrize("changed_underlay", [False, True])
def test_enospc_unmount_checks_original_directory_not_tmpfs_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_underlay: bool
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    target = broker.layout.artifacts_root / "run-one"
    target.mkdir(mode=0o700, parents=True)
    metadata = target.stat()
    broker._execution_mount_identity = _MountIdentity(
        path=target, device=metadata.st_dev + 1, inode=metadata.st_ino + 1,
        ancestry=(), expect_mounted=True,
    )
    monkeypatch.setattr(broker, "_required_evidence_owner_uid", lambda: os.getuid())
    monkeypatch.setattr(broker, "_mount_record", lambda path: None)
    monkeypatch.setattr(broker, "_enospc_covered_directory", lambda request, binding: (
        metadata.st_dev, metadata.st_ino + int(changed_underlay)
    ))
    if changed_underlay:
        with pytest.raises(BrokerError, match="identity changed"):
            broker._validate_enospc_mount_result({}, SimpleNamespace(run_id="run-one"), mounted=False)
    else:
        broker._validate_enospc_mount_result({}, SimpleNamespace(run_id="run-one"), mounted=False)


@pytest.mark.parametrize("valid_mount", [True, False])
def test_enospc_mount_hands_off_only_verified_tmpfs_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_mount: bool
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    target = broker.layout.artifacts_root / "run-one"
    target.mkdir(mode=0o700, parents=True)
    metadata = target.stat()
    broker._execution_mount_identity = _MountIdentity(
        path=target, device=metadata.st_dev, inode=metadata.st_ino,
        ancestry=(), expect_mounted=False,
    )
    monkeypatch.setattr(broker, "_required_evidence_owner_uid", lambda: os.getuid())
    monkeypatch.setattr(broker, "_mount_record", lambda path: {
        "filesystem": "tmpfs" if valid_mount else "ext4",
        "source": "fortgym-m1b-enospc-run-one",
        "options": ["rw", "nosuid", "nodev", "noexec"],
        "super_options": ["size=16384k", "mode=700"],
    })
    calls = []
    original = os.fchown

    def chown(descriptor: int, uid: int, gid: int) -> None:
        assert os.fstat(descriptor).st_ino == metadata.st_ino
        calls.append((uid, gid))
        original(descriptor, uid, gid)

    monkeypatch.setattr(os, "fchown", chown)
    if valid_mount:
        broker._validate_enospc_mount_result({}, SimpleNamespace(run_id="run-one"), mounted=True)
        assert calls == [(os.getuid(), -1)]
        assert stat.S_IMODE(target.stat().st_mode) == 0o700
    else:
        with pytest.raises(BrokerError, match="mount postcondition"):
            broker._validate_enospc_mount_result({}, SimpleNamespace(run_id="run-one"), mounted=True)
        assert calls == []


@pytest.mark.parametrize("unmount", [False, True])
def test_enospc_swap_before_execution_targets_only_the_open_directory_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unmount: bool,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    target = tmp_path / "state" / "artifacts" / "run-one"
    target.mkdir(mode=0o700, parents=True)
    descriptor = os.open(
        target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    metadata = os.fstat(descriptor)
    broker._execution_mount_fd = descriptor
    broker._execution_mount_identity = _MountIdentity(
        path=target,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        ancestry=(),
        expect_mounted=False,
    )
    parent_descriptor = os.open(
        target.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    parent_metadata = os.fstat(parent_descriptor)
    os.fchmod(parent_descriptor, 0o711)
    broker._execution_mount_parent_fd = parent_descriptor
    broker._execution_mount_parent_restore = (
        parent_metadata.st_uid,
        parent_metadata.st_gid,
        0o700,
        parent_metadata.st_dev,
        parent_metadata.st_ino,
    )
    observed_argv: list[tuple[str, ...]] = []

    def execute_fd(
        argv: Any,
        _timeout: float,
        *,
        descriptor: int,
    ) -> CommandCapture:
        assert stat.S_IMODE(os.fstat(parent_descriptor).st_mode) == 0o711
        normalized = tuple(str(item) for item in argv)
        observed_argv.append(normalized)
        if unmount:
            assert descriptor == parent_descriptor
            assert broker._execution_mount_fd is None
            assert normalized[-1] == f"/proc/self/fd/{parent_descriptor}/{target.name}"
        else:
            assert normalized[-1] == f"/proc/self/fd/{descriptor}"
        return CommandCapture(normalized, 0, "", "")

    monkeypatch.setattr(broker, "_execute_with_pass_fd", execute_fd)
    try:
        capture = broker._execute_mount_fd_bound(
            ("/bin/umount", "--", str(target)) if unmount else (
                "/bin/mount",
                "-t",
                "tmpfs",
                "tmpfs-source",
                str(target),
            ),
            timeout_seconds=30.0,
        )
    finally:
        if broker._execution_mount_fd is not None:
            os.close(descriptor)
        broker._execution_mount_fd = None
        os.fchmod(parent_descriptor, 0o700)
        os.close(parent_descriptor)
        broker._execution_mount_parent_fd = None
        broker._execution_mount_parent_restore = None
    assert capture.argv[-1] == str(target)
    assert observed_argv[0][-1] != str(target)
    assert target.is_dir()
    assert not target.with_name("run-one-authenticated").exists()


def test_container_rejects_unstaged_caller_writable_bind_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    _pin_test_stage(broker, binding, monkeypatch)
    document = _inspection(binding)
    document["Mounts"][1]["Source"] = str(binding.runtime_controller.evidence_dir)
    with pytest.raises(BrokerError, match="bind sources differ"):
        broker._validate_owned_container_document(binding, document)


def test_docker_launch_guard_requires_exact_runtime_writable_evidence_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    source = binding.runtime_controller.evidence_dir
    source.mkdir(parents=True, mode=0o700)
    source.chmod(0o1777)
    observed_modes: list[int] = []
    stable_directory_identity = broker._stable_directory_identity
    monkeypatch.setattr(broker, "_required_evidence_owner_uid", os.getuid)

    def observe_mode(
        path: Path,
        *,
        owner_uid: int,
        exact_mode: int,
    ) -> tuple[int, int, int, int]:
        observed_modes.append(exact_mode)
        identity = stable_directory_identity(
            path,
            owner_uid=owner_uid,
            exact_mode=exact_mode,
        )
        raise BrokerError(f"mode-observed-{identity[3]:o}")

    monkeypatch.setattr(broker, "_stable_directory_identity", observe_mode)
    actual = (
        "/usr/bin/docker",
        "run",
        "--volume",
        f"{source}:/artifacts",
    )
    with (
        pytest.raises(BrokerError, match="mode-observed-1777"),
        broker._execution_guard({"action": "docker_run"}, binding, actual),
    ):
        raise AssertionError("execution guard continued past the mode probe")
    assert observed_modes == [0o1777]

    source.chmod(0o700)
    with pytest.raises(BrokerError, match="identity is unsafe"):
        broker._stable_directory_identity(
            source,
            owner_uid=os.getuid(),
            exact_mode=0o1777,
        )


def test_restart_uses_supported_flag_without_changing_logical_fault(
    tmp_path: Path,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    logical, actual, timeout = broker._derive_command(
        {"action": "docker_restart", "parameters": {}}, binding
    )
    assert logical == ("docker", "restart", "--time", "0", binding.container_id)
    assert actual[1:] == ("restart", "--timeout", "0", binding.container_id)
    assert timeout == 60.0
    with pytest.raises(BrokerError, match="restart output differs"):
        broker._validate_command_result(
            {"action": "docker_restart"}, binding,
            CommandCapture(actual, 0, "unexpected output\n" + binding.container_id, ""),
        )


def test_root_staged_source_persists_through_container_and_daemon_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    released: list[str] = []
    monkeypatch.setattr(
        broker,
        "_inspect_container_live",
        lambda _binding, allow_absent: (
            (None if allow_absent else {"State": {"Running": True}}),
            CommandCapture((), 0, "", ""),
        ),
    )
    monkeypatch.setattr(
        broker,
        "_release_root_staged_evidence",
        lambda run_id: released.append(run_id),
    )
    monkeypatch.setattr(broker, "_prior_removed_container_id", lambda _run_id: None)
    monkeypatch.setattr(broker, "_append_state_record", lambda *args, **kwargs: {})

    broker._validate_command_result(
        {"action": "docker_restart"},
        binding,
        CommandCapture(("docker",), 0, f"{binding.container_id}\n", ""),
    )
    broker._validate_command_result(
        {"action": "restart_docker"},
        binding,
        CommandCapture(("systemctl",), 0, "", ""),
    )
    assert released == []

    broker._validate_command_result(
        {"action": "docker_remove"},
        binding,
        CommandCapture(("docker",), 0, f"{binding.container_id}\n", ""),
    )
    assert released == [binding.run_id]


def test_initial_container_inspection_allows_the_container_to_be_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    observed: list[bool] = []
    monkeypatch.setattr(
        broker,
        "_inspect_container_live",
        lambda _binding, *, allow_absent: (
            observed.append(allow_absent),
            (None, CommandCapture((), 1, "", "no such container")),
        )[1],
    )

    broker._revalidate_execution_target(
        {"action": "docker_container_inspect", "parameters": {}}, binding
    )

    assert observed == [True]


def test_port2_nonruntime_revalidation_requires_exact_absence(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path)
    request = {
        "action": "docker_container_inspect",
        "attempt_id": "g02-a02-contender_b",
        "parameters": {},
    }
    expected_argv = (
        "/usr/bin/docker",
        "inspect",
        "--type",
        "container",
        binding.container_name,
    )

    absent_broker = RootBroker(
        layout=_layout(tmp_path),
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
        execute=lambda argv, _timeout: CommandCapture(
            tuple(argv), 1, "", "Error: No such container\n"
        ),
    )
    absent_broker._revalidate_execution_target(request, binding)

    present_broker = RootBroker(
        layout=_layout(tmp_path),
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
        execute=lambda argv, _timeout: CommandCapture(tuple(argv), 0, "[]\n", ""),
    )
    with pytest.raises(BrokerError, match="unexpectedly found a container"):
        present_broker._revalidate_execution_target(request, binding)

    transport_broker = RootBroker(
        layout=_layout(tmp_path),
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
        execute=lambda argv, _timeout: CommandCapture(
            tuple(argv), 125, "", "daemon unavailable\n"
        ),
    )
    with pytest.raises(BrokerError, match="absence is unproved"):
        transport_broker._revalidate_execution_target(request, binding)

    assert expected_argv[1:] == (
        "inspect",
        "--type",
        "container",
        binding.container_name,
    )


def test_image_inspection_uses_only_the_supported_docker_cli_vector(
    tmp_path: Path,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)

    logical, executed, timeout = broker._derive_command(
        {
            "action": "docker_image_inspect",
            "parameters": {"reference_kind": "manifest"},
            "batch_id": "batch-one",
        },
        binding,
    )

    expected = ("docker", "image", "inspect", f"sha256:{MANIFEST}")
    assert logical == expected
    assert executed == ("/usr/bin/docker", *expected[1:])
    assert timeout == 30.0


@pytest.mark.parametrize(
    ("phase", "request_gate"),
    (
        (
            _BatchPhase(
                active_gate=None,
                cleanup_scope="gate",
                cleanup_gate_id="PORT-2",
                batch_head_sha256=SHA_C,
                gate_start_heads={"PORT-2": SHA_A},
                finalized=False,
            ),
            "PORT-2",
        ),
        (
            _BatchPhase(
                active_gate=None,
                cleanup_scope="batch",
                cleanup_gate_id=None,
                batch_head_sha256=SHA_C,
                gate_start_heads={"PORT-2": SHA_A},
                finalized=False,
            ),
            "CLEANUP",
        ),
    ),
)
def test_read_only_cleanup_is_allowed_for_a_started_incomplete_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: _BatchPhase,
    request_gate: str,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    identity = _digest("started-incomplete")
    attempt_records = [
        {
            "event": "attempt_started",
            "payload": {
                "attempt_id": "g02-a01-peer_a",
                "gate_id": "PORT-2",
                "role": "peer_a",
                "kind": "real_runtime",
                "identity_sha256": identity,
                "batch_ledger_head_sha256": SHA_A,
            },
        }
    ]
    records = iter(([], attempt_records))
    monkeypatch.setattr(broker, "_lock_active_batch", lambda _batch_id: None)
    monkeypatch.setattr(
        broker, "_ledger_records", lambda *args, **kwargs: next(records)
    )
    monkeypatch.setattr(broker, "_batch_phase", lambda _records: phase)

    observed = broker._validate_grant(
        {
            "batch_id": "batch-one",
            "grant_kind": "attempt",
            "attempt_id": "g02-a01-peer_a",
            "attempt_identity_sha256": identity,
            "gate_id": request_gate,
            "action": "docker_managed_list",
        },
        caller_uid=os.getuid(),
    )

    assert observed == phase


def test_strict_slot_mirror_allows_final_cleanup_read_of_incomplete_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    batch_id = "batch-one"
    control = broker.layout.batch_evidence_root(batch_id) / "control"
    control.mkdir(parents=True, mode=0o700)
    (control / "batch-ledger.jsonl").write_text("{}\n", encoding="utf-8")
    (control / "attempt-ledger.jsonl").write_text("{}\n", encoding="utf-8")
    identity = _digest("started-incomplete")
    attempt_records = [
        {
            "event": "attempt_started",
            "payload": {
                "attempt_id": "g02-a01-peer_a",
                "gate_id": "PORT-2",
                "batch_ledger_head_sha256": SHA_A,
            },
        }
    ]
    decoded = iter(([{"event": "batch_opened"}], attempt_records))
    phase = _BatchPhase(
        active_gate=None,
        cleanup_scope="batch",
        cleanup_gate_id=None,
        batch_head_sha256=SHA_C,
        gate_start_heads={"PORT-2": SHA_A},
        finalized=False,
    )
    mirror = _AttemptMirror(
        attempt_id="g02-a01-peer_a",
        gate_id="PORT-2",
        role="peer_a",
        kind="real_runtime",
        identity_sha256=identity,
        completed=False,
    )
    monkeypatch.setattr(
        broker,
        "_decode_ledger_records",
        lambda *_args, **_kwargs: next(decoded),
    )
    monkeypatch.setattr(
        broker,
        "_strict_attempt_replay",
        lambda _records: {mirror.attempt_id: mirror},
    )
    monkeypatch.setattr(
        broker,
        "_strict_batch_replay",
        lambda *_args, **_kwargs: phase,
    )

    snapshot = broker._strict_ledger_snapshot(
        {
            "batch_id": batch_id,
            "gate_id": "CLEANUP",
            "action": "docker_managed_list",
            "attempt_id": mirror.attempt_id,
            "attempt_identity_sha256": identity,
        },
        caller_uid=os.getuid(),
    )

    assert snapshot.phase == phase
    assert snapshot.attempts[mirror.attempt_id] == mirror


def test_strict_slot_mirror_allows_only_port2_nonruntime_absence_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    batch_id = "batch-one"
    control = broker.layout.batch_evidence_root(batch_id) / "control"
    control.mkdir(parents=True, mode=0o700)
    (control / "batch-ledger.jsonl").write_text("{}\n", encoding="utf-8")
    (control / "attempt-ledger.jsonl").write_text("{}\n", encoding="utf-8")
    identity = _digest("port2-nonruntime")
    attempt_records = [
        {
            "event": "attempt_started",
            "payload": {
                "attempt_id": "g02-a02-contender_b",
                "gate_id": "PORT-2",
                "batch_ledger_head_sha256": SHA_A,
            },
        }
    ]
    phase = _BatchPhase(
        active_gate="PORT-2",
        cleanup_scope=None,
        cleanup_gate_id=None,
        batch_head_sha256=SHA_C,
        gate_start_heads={"PORT-2": SHA_A},
        finalized=False,
    )
    mirror = _AttemptMirror(
        attempt_id="g02-a02-contender_b",
        gate_id="PORT-2",
        role="contender_b",
        kind="non_runtime_conflict",
        identity_sha256=identity,
        completed=False,
    )

    def invoke(action: str) -> _LedgerSnapshot:
        decoded = iter(([{"event": "batch_opened"}], attempt_records))
        monkeypatch.setattr(
            broker,
            "_decode_ledger_records",
            lambda *_args, **_kwargs: next(decoded),
        )
        monkeypatch.setattr(
            broker,
            "_strict_attempt_replay",
            lambda _records: {mirror.attempt_id: mirror},
        )
        monkeypatch.setattr(
            broker,
            "_strict_batch_replay",
            lambda *_args, **_kwargs: phase,
        )
        return broker._strict_ledger_snapshot(
            {
                "batch_id": batch_id,
                "gate_id": "PORT-2",
                "action": action,
                "attempt_id": mirror.attempt_id,
                "attempt_identity_sha256": identity,
            },
            caller_uid=os.getuid(),
        )

    snapshot = invoke("docker_container_inspect")
    assert snapshot.attempts[mirror.attempt_id] == mirror
    with pytest.raises(BrokerError, match="non-runtime conflict"):
        invoke("docker_managed_list")


def _attempt_record(event: str, attempt_id: str) -> dict[str, Any]:
    gate, role, kind = _FROZEN_ATTEMPTS[attempt_id]
    if event == "attempt_started":
        payload = {
            "gate_id": gate,
            "attempt_id": attempt_id,
            "kind": kind,
            "role": role,
            "identity_sha256": hashlib.sha256(attempt_id.encode()).hexdigest(),
            "batch_ledger_head_sha256": SHA_A,
        }
    else:
        payload = {
            "gate_id": gate,
            "attempt_id": attempt_id,
            "outcome_code": "completed",
            "evidence": [{"path": f"{attempt_id}.json"}],
        }
    return {"event": event, "payload": payload}


def test_attempt_replay_allows_shuffled_co8_and_target_peer_order(
    tmp_path: Path,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    co8 = [f"g04-a{index:02d}-run_{index:02d}" for index in range(1, 9)]
    shuffled = [co8[index] for index in (7, 0, 5, 2, 6, 1, 4, 3)]
    records = [
        _attempt_record("attempt_started", attempt_id) for attempt_id in shuffled
    ]
    records.extend(
        _attempt_record("attempt_completed", attempt_id)
        for attempt_id in reversed(shuffled)
    )
    replayed = broker._strict_attempt_replay(records)
    assert all(replayed[attempt_id].completed for attempt_id in co8)

    pair = ("g05-a02-peer", "g05-a01-target")
    replayed = broker._strict_attempt_replay(
        [_attempt_record("attempt_started", attempt_id) for attempt_id in pair]
    )
    assert all(replayed[attempt_id].identity_sha256 is not None for attempt_id in pair)


def test_batch_opening_freezes_plan_credit_order_and_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    monkeypatch.setattr(broker, "_install_repo_import_path", lambda: None)
    opening = _strict_opening(broker)
    empty = broker._strict_attempt_replay(())
    broker._strict_batch_replay([opening], attempt_records=(), attempts=empty)
    canonical_opening = json.loads(json.dumps(opening, sort_keys=True))
    broker._strict_batch_replay([canonical_opening], attempt_records=(), attempts=empty)

    reordered = json.loads(json.dumps(opening))
    reordered["payload"]["local_credit_boundaries"]["PORT-1"] = "local_subprocedure"
    with pytest.raises(BrokerError, match="batch opening"):
        broker._strict_batch_replay([reordered], attempt_records=(), attempts=empty)

    changed_plan = json.loads(json.dumps(opening))
    changed_plan["payload"]["plan"]["max_real_runtime_attempts"] = 25
    with pytest.raises(BrokerError, match="batch opening"):
        broker._strict_batch_replay([changed_plan], attempt_records=(), attempts=empty)

    credits = [
        _local_credit_record(gate_id, index)
        for index, gate_id in enumerate(
            ("PORT-1", "ORPHAN-1", "PROVIDER-ENV", "CAP-FAKE"), start=2
        )
    ]
    broker._strict_batch_replay([opening, *credits], attempt_records=(), attempts=empty)
    with pytest.raises(BrokerError, match="local credit"):
        broker._strict_batch_replay(
            [opening, credits[1], credits[0], *credits[2:]],
            attempt_records=(),
            attempts=empty,
        )


def test_broker_replays_canonical_controller_cleanup_failure_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay the exact controller JSONL shape that failed on live attempt 10."""

    layout = _layout(tmp_path)
    batch_id = "batch-one"
    evidence_root = layout.batch_evidence_root(batch_id)
    inputs = evidence_root / "inputs"
    inputs.mkdir(parents=True, mode=0o700)
    acceptance = inputs / "acceptance.yaml"
    acceptance.write_bytes(
        (Path(__file__).resolve().parents[1] / "infra/m1b/acceptance.yaml").read_bytes()
    )
    source_bytes = b'{"schema":"source-test"}\n'
    source_path = inputs / "source-manifest.json"
    source_path.write_bytes(source_bytes)
    layout.source_manifest_path.parent.mkdir(parents=True, mode=0o755)
    layout.source_manifest_path.write_bytes(source_bytes)

    credits: list[LocalCreditImport] = []
    for gate in FROZEN_GATE_PLAN:
        if gate.local_credit_scope is None:
            continue
        path = inputs / "local" / f"{gate.gate_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(gate.gate_id, encoding="utf-8")
        credits.append(
            LocalCreditImport(
                gate_id=gate.gate_id,
                scope=gate.local_credit_scope,
                criteria_passed=gate.criteria,
                evidence_paths=(path,),
            )
        )

    canary = evidence_root / "batch-canary-created.json"
    canary.write_text("canary", encoding="utf-8")

    class CleanupFailureAdapter:
        def execute_gate(self, context: object) -> object:
            raise AssertionError("cleanup failure must stop before a runtime gate")

        def cleanup_pass(self, context: Any) -> CleanupPassResult:
            receipt = (
                evidence_root
                / "cleanup"
                / (
                    f"{context.scope}-{context.gate_id or 'batch'}-"
                    f"pass-{context.pass_index}.json"
                )
            )
            receipt.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            receipt.write_text("cleanup", encoding="utf-8")
            return CleanupPassResult(
                scope=context.scope,
                gate_id=context.gate_id,
                pass_index=context.pass_index,
                criteria_passed=(),
                evidence_paths=(receipt, canary),
                failure_code="foreign_canary_changed",
            )

    class NoPrivilege:
        def execute(self, logical_argv: object, *, timeout_seconds: float) -> object:
            raise AssertionError("local credit cleanup must not invoke privilege")

    authorization = authorize_private_m1b_live_acceptance(
        test_mode=True,
        batch_id=batch_id,
        evidence_root=evidence_root,
        contract_path=acceptance,
    )
    controller = LiveAcceptanceBatchController(
        authorization=authorization,
        adapter=CleanupFailureAdapter(),
        privileged_commands=NoPrivilege(),
        source_manifest=SourceManifestLock(
            path=source_path,
            sha256=hashlib.sha256(source_bytes).hexdigest(),
        ),
        local_credits=tuple(credits),
    )
    outcome = controller.run()
    assert outcome.decision.value == "INCOMPLETE_NO_GO"

    records = [
        json.loads(line)
        for line in controller.batch_ledger_path.read_text().splitlines()
    ]
    cleanup_records = [
        record for record in records if record["event"] == "cleanup_pass_completed"
    ]
    assert cleanup_records
    assert [
        reference["path"] for reference in cleanup_records[0]["payload"]["evidence"]
    ] == ["cleanup/gate-PORT-1-pass-1.json", "batch-canary-created.json"]

    broker = RootBroker(
        layout=layout,
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    monkeypatch.setattr(broker, "_install_repo_import_path", lambda: None)
    empty = broker._strict_attempt_replay(())
    phase = broker._strict_batch_replay(
        json.loads(json.dumps(records, sort_keys=True)),
        attempt_records=(),
        attempts=empty,
    )
    assert phase.finalized is True


def test_strict_snapshot_accepts_only_the_durable_empty_attempt_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    broker = RootBroker(
        layout=layout,
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    monkeypatch.setattr(broker, "_install_repo_import_path", lambda: None)
    batch_id = "batch-one"
    opening = _strict_opening(broker, batch_id=batch_id)
    control = layout.batch_evidence_root(batch_id) / "control"
    control.mkdir(parents=True, mode=0o700)
    (control / "batch-ledger.jsonl").write_bytes(b"batch\n")
    (control / "attempt-ledger.jsonl").write_bytes(b"")
    original_decode = broker._decode_ledger_records

    def decode(
        raw: bytes,
        *,
        schema: str,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        assert batch_id == "batch-one"
        if schema == "fortgym.m1b-live-acceptance-batch-ledger/v1":
            assert raw == b"batch\n"
            return [opening]
        assert schema == "fortgym.m1b-live-acceptance-attempt-ledger/v1"
        assert raw == b""
        return original_decode(raw, schema=schema, batch_id=batch_id)

    monkeypatch.setattr(broker, "_decode_ledger_records", decode)

    snapshot = broker._strict_ledger_snapshot(
        {"batch_id": batch_id},
        caller_uid=os.getuid(),
    )

    assert snapshot.attempt_records == ()
    assert snapshot.attempt_file_sha256 == hashlib.sha256(b"").hexdigest()
    broker._confirm_caller_snapshot(
        {"batch_id": batch_id},
        snapshot=snapshot,
        binding=None,
        caller_uid=os.getuid(),
    )

    (control / "attempt-ledger.jsonl").write_bytes(b"late mutation\n")
    with pytest.raises(BrokerError, match="caller ledgers changed"):
        broker._confirm_caller_snapshot(
            {"batch_id": batch_id},
            snapshot=snapshot,
            binding=None,
            caller_uid=os.getuid(),
        )


def _attempt_chain_record(
    event: str,
    attempt_id: str,
    previous: str,
    label: str,
    *,
    gate_start_head: str,
) -> dict[str, Any]:
    record = _attempt_record(event, attempt_id)
    record["previous_record_sha256"] = previous
    record["record_sha256"] = _digest(label)
    if event == "attempt_started":
        record["payload"]["batch_ledger_head_sha256"] = gate_start_head
    return record


def test_gate_completion_head_rejects_random_and_cross_gate_interleaving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    monkeypatch.setattr(broker, "_install_repo_import_path", lambda: None)
    opening = _strict_opening(broker)
    credits = [
        _local_credit_record(gate_id, index)
        for index, gate_id in enumerate(
            ("PORT-1", "ORPHAN-1", "PROVIDER-ENV", "CAP-FAKE"), start=2
        )
    ]
    port1 = next(gate for gate in FROZEN_GATE_PLAN if gate.gate_id == "PORT-1")
    port2 = next(gate for gate in FROZEN_GATE_PLAN if gate.gate_id == "PORT-2")
    port1_start = {
        "sequence": 6,
        "batch_id": "batch-one",
        "event": "gate_started",
        "record_sha256": _digest("port1-start"),
        "payload": {
            "gate": port1.payload(gate_index=1),
            "attempt_ledger_head_sha256": "0" * 64,
        },
    }
    zero_summary = {
        "planned": 0,
        "started": 0,
        "completed": 0,
        "real_runtime_started": 0,
        "real_runtime_completed": 0,
        "non_runtime_started": 0,
        "non_runtime_completed": 0,
    }
    port1_complete = {
        "sequence": 7,
        "batch_id": "batch-one",
        "event": "gate_completed",
        "record_sha256": _digest("port1-complete"),
        "payload": {
            "gate": port1.payload(gate_index=1),
            "status": "PASS_LOCAL",
            "criteria_passed": list(port1.criteria),
            "failure_code": None,
            "evidence": list(credits[0]["payload"]["evidence"]),
            "local_credit": dict(credits[0]["payload"]),
            "attempts": zero_summary,
            "authorization_identity_sha256": None,
            "attempt_ledger_head_sha256": "0" * 64,
        },
    }
    cleanup_pass_payloads = [
        {
            "scope": "gate",
            "gate_id": "PORT-1",
            "pass_index": index,
            "status": "PASS",
            "criteria_passed": list(
                next(
                    gate for gate in FROZEN_GATE_PLAN if gate.gate_id == "CLEANUP"
                ).criteria
            ),
            "failure_code": None,
            "evidence": [
                {
                    "path": f"cleanup/pass-{index}.json",
                    "sha256": _digest(f"cleanup-evidence-{index}"),
                    "size_bytes": 1,
                }
            ],
        }
        for index in (1, 2)
    ]
    cleanup = [
        {
            "sequence": 8,
            "batch_id": "batch-one",
            "event": "cleanup_started",
            "record_sha256": _digest("cleanup-start"),
            "payload": {"scope": "gate", "gate_id": "PORT-1", "required_passes": 2},
        },
        *[
            {
                "sequence": 8 + index,
                "batch_id": "batch-one",
                "event": "cleanup_pass_completed",
                "record_sha256": _digest(f"cleanup-pass-{index}"),
                "payload": cleanup_pass_payloads[index - 1],
            }
            for index in (1, 2)
        ],
        {
            "sequence": 11,
            "batch_id": "batch-one",
            "event": "cleanup_completed",
            "record_sha256": _digest("cleanup-complete"),
            "payload": {
                "scope": "gate",
                "gate_id": "PORT-1",
                "status": "PASS",
                "required_passes": 2,
                "passes": cleanup_pass_payloads,
            },
        },
    ]
    port2_start_head = _digest("port2-start")
    port2_start = {
        "sequence": 12,
        "batch_id": "batch-one",
        "event": "gate_started",
        "record_sha256": port2_start_head,
        "payload": {
            "gate": port2.payload(gate_index=2),
            "attempt_ledger_head_sha256": "0" * 64,
        },
    }
    attempt_records: list[dict[str, Any]] = []
    previous = "0" * 64
    for index, (event, attempt_id) in enumerate(
        (
            ("attempt_started", "g02-a01-peer_a"),
            ("attempt_started", "g02-a02-contender_b"),
            ("attempt_completed", "g02-a02-contender_b"),
            ("attempt_completed", "g02-a01-peer_a"),
        ),
        start=1,
    ):
        record = _attempt_chain_record(
            event,
            attempt_id,
            previous,
            f"port2-attempt-{index}",
            gate_start_head=port2_start_head,
        )
        attempt_records.append(record)
        previous = record["record_sha256"]
    attempts = broker._strict_attempt_replay(attempt_records)
    port2_complete = {
        "sequence": 13,
        "batch_id": "batch-one",
        "event": "gate_completed",
        "record_sha256": _digest("port2-complete"),
        "payload": {
            "gate": port2.payload(gate_index=2),
            "status": "PASS",
            "criteria_passed": list(port2.criteria),
            "failure_code": None,
            "evidence": [
                {"path": "gates/PORT-2.json", "sha256": SHA_A, "size_bytes": 1}
            ],
            "local_credit": None,
            "attempts": {
                "planned": 2,
                "started": 2,
                "completed": 2,
                "real_runtime_started": 1,
                "real_runtime_completed": 1,
                "non_runtime_started": 1,
                "non_runtime_completed": 1,
            },
            "authorization_identity_sha256": None,
            "attempt_ledger_head_sha256": previous,
        },
    }
    batch_records = [
        opening,
        *credits,
        port1_start,
        port1_complete,
        *cleanup,
        port2_start,
        port2_complete,
    ]
    broker._strict_batch_replay(
        batch_records,
        attempt_records=attempt_records,
        attempts=attempts,
    )
    forged = json.loads(json.dumps(port2_complete))
    forged["payload"]["attempt_ledger_head_sha256"] = SHA_A
    with pytest.raises(BrokerError, match="attempt head"):
        broker._strict_batch_replay(
            [*batch_records[:-1], forged],
            attempt_records=attempt_records,
            attempts=attempts,
        )

    cold_start = _attempt_chain_record(
        "attempt_started",
        "g03-a01-suppressed_first",
        attempt_records[0]["record_sha256"],
        "cold-future",
        gate_start_head=_digest("future-gate-start"),
    )
    late_port2 = _attempt_chain_record(
        "attempt_completed",
        "g02-a01-peer_a",
        cold_start["record_sha256"],
        "late-port2",
        gate_start_head=port2_start_head,
    )
    with pytest.raises(BrokerError, match="interleave"):
        broker._strict_attempt_replay([attempt_records[0], cold_start, late_port2])


@pytest.mark.parametrize(
    ("attempt_id", "action", "message"),
    (
        ("g02-a02-contender_b", "docker_run", "non-runtime conflict"),
        ("g05-a01-target", "docker_create", "reserved for the OOM"),
        ("g05-a01-target", "docker_start", "reserved for the OOM"),
        ("g07-a01-target", "docker_run", "held create/start"),
    ),
)
def test_root_action_matrix_rejects_wrong_slot_kind_gate_and_role(
    tmp_path: Path,
    attempt_id: str,
    action: str,
    message: str,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    gate_id, role, kind = _FROZEN_ATTEMPTS[attempt_id]
    mirror = _AttemptMirror(
        attempt_id=attempt_id,
        gate_id=gate_id,
        role=role,
        kind=kind,
        identity_sha256=SHA_A,
        completed=False,
    )
    snapshot = _LedgerSnapshot(
        batch_records=(),
        attempt_records=(),
        phase=_BatchPhase(gate_id, None, None, SHA_A, {}, False),
        attempts={attempt_id: mirror},
        batch_file_sha256=SHA_B,
        attempt_file_sha256=SHA_C,
    )
    with pytest.raises(BrokerError, match=message):
        broker._validate_root_action_transition(
            {"attempt_id": attempt_id, "action": action},
            snapshot=snapshot,
            records=(),
        )


def test_port2_nonruntime_slot_allows_only_exact_absence_inspection(
    tmp_path: Path,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    attempt_id = "g02-a02-contender_b"
    mirror = _AttemptMirror(
        attempt_id=attempt_id,
        gate_id="PORT-2",
        role="contender_b",
        kind="non_runtime_conflict",
        identity_sha256=SHA_A,
        completed=False,
    )
    snapshot = _LedgerSnapshot(
        batch_records=(),
        attempt_records=(),
        phase=_BatchPhase("PORT-2", None, None, SHA_A, {}, False),
        attempts={attempt_id: mirror},
        batch_file_sha256=SHA_B,
        attempt_file_sha256=SHA_C,
    )

    broker._validate_root_action_transition(
        {"attempt_id": attempt_id, "action": "docker_container_inspect"},
        snapshot=snapshot,
        records=(),
    )
    for action in (
        "docker_image_inspect",
        "docker_run",
        "docker_create",
        "docker_start",
        "docker_logs",
        "docker_remove",
        "docker_managed_list",
        "docker_exec_attest",
    ):
        with pytest.raises(BrokerError, match="non-runtime conflict"):
            broker._validate_root_action_transition(
                {"attempt_id": attempt_id, "action": action},
                snapshot=snapshot,
                records=(),
            )


def test_port2_nonruntime_inspection_accepts_only_canonical_absence(
    tmp_path: Path,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    request = {
        "action": "docker_container_inspect",
        "attempt_id": "g02-a02-contender_b",
    }

    absent = broker._validate_command_result(
        request,
        binding,
        CommandCapture(
            ("docker", "inspect"),
            1,
            "",
            "Error: No such container: exact-contender\n",
        ),
    )
    assert absent.returncode == 1
    assert absent.stdout == ""
    assert absent.stderr == "Error: no such object\n"

    with pytest.raises(BrokerError, match="unexpectedly found a container"):
        broker._validate_command_result(
            request,
            binding,
            CommandCapture(
                ("docker", "inspect"),
                0,
                json.dumps([_inspection(binding)]),
                "",
            ),
        )


def test_root_action_matrix_forbids_recreate_after_removal(tmp_path: Path) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    attempt_id = "g07-a01-target"
    mirror = _AttemptMirror(
        attempt_id=attempt_id,
        gate_id="OOM",
        role="target",
        kind="real_runtime",
        identity_sha256=SHA_A,
        completed=False,
    )
    snapshot = _LedgerSnapshot(
        batch_records=(),
        attempt_records=(),
        phase=_BatchPhase("OOM", None, None, SHA_A, {}, False),
        attempts={attempt_id: mirror},
        batch_file_sha256=SHA_B,
        attempt_file_sha256=SHA_C,
    )
    records = (
        {
            "event": "action_completed",
            "data": {"attempt_id": attempt_id, "action": "docker_remove"},
        },
    )
    with pytest.raises(BrokerError, match="follows root-observed removal"):
        broker._validate_root_action_transition(
            {"attempt_id": attempt_id, "action": "docker_create"},
            snapshot=snapshot,
            records=records,
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_final_inventory_rejects_missing_extra_mismatch_and_self_tamper(
    tmp_path: Path,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    broker.layout.receipt_root.mkdir(mode=0o700, parents=True)
    request = {"batch_id": "batch-one", "request_id": SHA_C}
    batch_root = broker.layout.batch_evidence_root("batch-one")
    batch_root.mkdir(mode=0o700, parents=True)
    with pytest.raises(BrokerError, match="receipt root is absent"):
        broker._final_receipt_inventory(
            request,
            batch_root=batch_root,
            caller_uid=os.getuid(),
        )

    root_receipt = {
        "schema": "fortgym.m1b-root-broker-receipt/v1",
        "batch_id": "batch-one",
        "request_id": SHA_A,
        "stdout": "private-poison",
        "stderr": "",
        "ok": True,
    }
    _write_json(broker.layout.receipt_root / f"{SHA_A}.json", root_receipt)
    public_path = batch_root / "broker-client" / "PORT-2" / f"{SHA_A}.json"
    public = {
        key: value
        for key, value in root_receipt.items()
        if key not in {"stdout", "stderr"}
    }
    _write_json(public_path, {**public, "ok": False})
    with pytest.raises(BrokerError, match="differs from root evidence"):
        broker._final_receipt_inventory(
            request,
            batch_root=batch_root,
            caller_uid=os.getuid(),
        )

    public_path.unlink()
    _write_json(
        batch_root / "broker-client" / "CLEANUP" / f"{SHA_C}.json",
        {
            "schema": "fortgym.m1b-root-broker-receipt/v1",
            "batch_id": "batch-one",
            "request_id": SHA_C,
        },
    )
    with pytest.raises(BrokerError, match="current attestation receipt exists"):
        broker._final_receipt_inventory(
            request,
            batch_root=batch_root,
            caller_uid=os.getuid(),
        )

    current = batch_root / "broker-client" / "CLEANUP" / f"{SHA_C}.json"
    current.unlink()
    _write_json(
        batch_root / "broker-client" / "PORT-2" / f"{SHA_B}.json",
        {
            "schema": "fortgym.m1b-root-broker-receipt/v1",
            "batch_id": "batch-one",
            "request_id": SHA_B,
        },
    )
    with pytest.raises(BrokerError, match="lacks a root counterpart"):
        broker._final_receipt_inventory(
            request,
            batch_root=batch_root,
            caller_uid=os.getuid(),
        )


def test_final_controller_export_accepts_bounded_incomplete_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    started_id = "g02-a01-peer_a"
    attempts = {
        attempt_id: _AttemptMirror(
            attempt_id=attempt_id,
            gate_id=gate,
            role=role,
            kind=kind,
            identity_sha256=SHA_A if attempt_id == started_id else None,
            completed=False,
        )
        for attempt_id, (gate, role, kind) in _FROZEN_ATTEMPTS.items()
    }
    snapshot = _LedgerSnapshot(
        batch_records=(),
        attempt_records=(),
        phase=_BatchPhase(None, None, None, SHA_A, {}, True),
        attempts=attempts,
        batch_file_sha256=SHA_B,
        attempt_file_sha256=SHA_C,
    )
    rows = [
        {
            "gate": gate.payload(gate_index=index),
            "status": "FAIL" if gate.gate_id == "PORT-2" else "NOT_RUN",
            "criteria_passed": [],
            "failure_code": "not_run",
            "evidence": [],
            "local_credit": None,
            "attempts": {},
            "authorization_identity_sha256": None,
            "attempt_ledger_head_sha256": SHA_A,
        }
        for index, gate in enumerate(FROZEN_GATE_PLAN, start=1)
    ]
    missing = sorted(set(_FROZEN_ATTEMPTS) - {started_id})
    decision = {
        "schema": "fortgym.m1b-live-acceptance-decision/v1",
        "batch_id": "batch-one",
        "acceptance_sha256": (
            "b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf"
        ),
        "plan_sha256": (
            "d37cad75e7e052ed4463353f0b3138f64143ca1e50337e6ad5eb29cbbca47194"
        ),
        "decision": "INCOMPLETE_NO_GO",
        "hard_gate_count": 16,
        "hard_gates_passed": 0,
        "failed_or_incomplete_gates": ["PORT-2"],
        "real_runtime_attempt_limit": 26,
        "real_runtime_attempts_started": 1,
        "real_runtime_attempts_completed": 0,
        "non_runtime_attempts_started": 0,
        "non_runtime_attempts_completed": 0,
        "incomplete_attempt_ids": [started_id],
        "missing_attempt_ids": missing,
        "reasons": ["attempt_terminal_evidence_incomplete"],
        "provider_calls": 0,
        "provider_cost_usd": 0,
    }
    documents = {
        "gate_results": {
            "schema": "fortgym.m1b-live-acceptance-gate-results/v1",
            "batch_id": "batch-one",
            "acceptance_sha256": decision["acceptance_sha256"],
            "plan_sha256": decision["plan_sha256"],
            "gates": rows,
        },
        "decision": decision,
        "evidence_manifest": {},
        "seal": {"decision": "INCOMPLETE_NO_GO", "decision_sha256": SHA_A},
    }
    monkeypatch.setattr(broker, "_install_repo_import_path", lambda: None)
    monkeypatch.setattr(
        broker, "_validate_final_manifest", lambda *args, **kwargs: None
    )
    counts = broker._validate_final_controller_documents(
        batch_id="batch-one",
        batch_root=tmp_path,
        documents=documents,
        digests={"decision": SHA_A},
        snapshot=snapshot,
        caller_uid=os.getuid(),
    )
    assert counts == {
        "planned": 27,
        "real_runtime_started": 1,
        "real_runtime_completed": 0,
        "non_runtime_started": 0,
        "non_runtime_completed": 0,
    }

    decision["decision"] = "GO"
    decision["hard_gates_passed"] = 16
    decision["failed_or_incomplete_gates"] = []
    decision["reasons"] = []
    documents["seal"] = {"decision": "GO", "decision_sha256": SHA_A}
    with pytest.raises(BrokerError, match="complete frozen matrix"):
        broker._validate_final_controller_documents(
            batch_id="batch-one",
            batch_root=tmp_path,
            documents=documents,
            digests={"decision": SHA_A},
            snapshot=snapshot,
            caller_uid=os.getuid(),
        )


def test_distinct_requests_execute_concurrently_outside_root_state_lock(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    for path in (
        layout.state_root,
        layout.broker_root,
        layout.broker_state_root,
        layout.inflight_root,
    ):
        path.mkdir(mode=0o700, exist_ok=True)
    first_external = threading.Event()
    second_external = threading.Event()
    errors: list[BaseException] = []

    def first_execute(argv: Any, _timeout: float) -> CommandCapture:
        first_external.set()
        if not second_external.wait(2.0):
            raise RuntimeError("second request remained serialized by the state lock")
        return CommandCapture(tuple(argv), 0, "", "")

    def second_execute(argv: Any, _timeout: float) -> CommandCapture:
        second_external.set()
        return CommandCapture(tuple(argv), 0, "", "")

    first = RootBroker(
        layout=layout,
        execute=first_execute,
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )
    second = RootBroker(
        layout=layout,
        execute=second_execute,
        caller_uid=os.getuid(),
        trusted_uid=os.getuid(),
    )

    def run(broker: RootBroker, request_id: str) -> None:
        try:
            with (
                broker._exclusive_broker_lock(),
                broker._request_execution_lock(request_id),
            ):
                capture = broker._execute(("fixed-command",), 2.0)
                assert capture.returncode == 0
        except BaseException as exc:  # noqa: BLE001 - preserve thread failures
            errors.append(exc)

    first_thread = threading.Thread(target=run, args=(first, SHA_A), daemon=True)
    second_thread = threading.Thread(target=run, args=(second, SHA_B), daemon=True)
    first_thread.start()
    assert first_external.wait(2.0)
    second_thread.start()
    first_thread.join(3.0)
    second_thread.join(3.0)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []


def test_midrun_outer_guard_allows_active_bind_pins_but_final_residue_does_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = RootBroker(
        layout=_layout(tmp_path), caller_uid=os.getuid(), trusted_uid=os.getuid()
    )
    binding = _binding(tmp_path)
    active_stage = broker.layout.bind_source_root / binding.run_id / "artifacts"
    active_stage.mkdir(mode=0o700, parents=True)
    broker.layout.bind_source_root.chmod(0o700)
    _write_json(
        broker.layout.control_ssh_flow_evidence,
        {
            "schema": "fortgym.m1b-control-ssh-flow/v1",
            "exact_flow_count": 1,
            "flow": {
                "family": "ipv4",
                "server_address": "192.0.2.10",
                "client_address": "198.51.100.20",
                "client_port": 54321,
            },
        },
    )
    ruleset = {
        "nftables": [
            {"table": {"family": "inet", "name": "fortgym_m1b_outer"}},
            {
                "chain": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "name": "output",
                    "type": "filter",
                    "hook": "output",
                    "prio": -200,
                    "policy": "drop",
                }
            },
            {
                "chain": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "name": "forward",
                    "type": "filter",
                    "hook": "forward",
                    "prio": -10,
                    "policy": "drop",
                }
            },
            {
                "counter": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "name": "output_denied",
                }
            },
            {
                "counter": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "name": "forward_denied",
                }
            },
            {
                "rule": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "chain": "output",
                    "expr": [
                        {
                            "match": {
                                "left": {"meta": {"key": "oifname"}},
                                "op": "==",
                                "right": "lo",
                            }
                        },
                        {"counter": None},
                        {"accept": None},
                    ],
                }
            },
            {
                "rule": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "chain": "output",
                    "expr": [
                        {
                            "match": {
                                "left": {
                                    "payload": {"protocol": "ip", "field": "saddr"}
                                },
                                "op": "==",
                                "right": "192.0.2.10",
                            }
                        },
                        {
                            "match": {
                                "left": {
                                    "payload": {"protocol": "ip", "field": "daddr"}
                                },
                                "op": "==",
                                "right": "198.51.100.20",
                            }
                        },
                        {
                            "match": {
                                "left": {
                                    "payload": {"protocol": "tcp", "field": "sport"}
                                },
                                "op": "==",
                                "right": 22,
                            }
                        },
                        {
                            "match": {
                                "left": {
                                    "payload": {"protocol": "tcp", "field": "dport"}
                                },
                                "op": "==",
                                "right": 54321,
                            }
                        },
                        {"accept": None},
                    ],
                }
            },
            {
                "rule": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "chain": "output",
                    "expr": [
                        {"counter": {"name": "output_denied"}},
                        {"reject": None},
                    ],
                }
            },
            {
                "rule": {
                    "family": "inet",
                    "table": "fortgym_m1b_outer",
                    "chain": "forward",
                    "expr": [
                        {"counter": {"name": "forward_denied"}},
                        {"reject": None},
                    ],
                }
            },
        ]
    }
    request = {"action": "verify_outer_guard", "parameters": {}}
    logical, actual, timeout = broker._derive_command(request, binding)
    assert (
        logical
        == actual
        == (
            "/usr/sbin/nft",
            "--json",
            "list",
            "table",
            "inet",
            "fortgym_m1b_outer",
        )
    )
    assert timeout == 30.0
    with broker._execution_guard(request, binding, actual) as guarded:
        assert guarded == actual
        broker._validate_outer_guard_capture(json.dumps(ruleset))
    assert active_stage.is_dir()

    monkeypatch.setattr(
        broker,
        "_execute",
        lambda argv, _timeout: CommandCapture(tuple(argv), 0, "", ""),
    )
    monkeypatch.setattr(broker, "_mount_record", lambda _path: None)
    snapshot = _LedgerSnapshot(
        batch_records=(),
        attempt_records=(),
        phase=_BatchPhase(None, None, None, SHA_A, {}, True),
        attempts={},
        batch_file_sha256=SHA_B,
        attempt_file_sha256=SHA_C,
    )
    with pytest.raises(BrokerError, match="staging residue remains"):
        broker._validate_final_live_residue(
            {"batch_id": "batch-one"},
            snapshot=snapshot,
            canary_name="fortgym-m1b-canary-aaaaaaaaaaaa",
        )
