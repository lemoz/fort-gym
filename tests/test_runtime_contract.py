from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fort_gym.bench.run import runtime_contract as runtime_contract_module
from fort_gym.bench.run.process_supervisor import build_sanitized_environment
from fort_gym.bench.run.runtime_contract import (
    PreparedRuntimeIdentityError,
    ProviderPolicy,
    RuntimeContract,
    validate_prepared_runtime_environment,
)

HASHES = {
    "image_manifest_sha256": "1" * 64,
    "image_config_sha256": "2" * 64,
    "image_archive_sha256": "3" * 64,
    "seed_tree_sha256": "4" * 64,
    "seed_world_sha256": "5" * 64,
    "code_sha256": "6" * 64,
}


def _expected_supervised_pythonpath() -> str:
    runtime_directory = Path(runtime_contract_module.__file__).resolve().parent
    package_root = Path(runtime_contract_module.__file__).resolve().parents[3]
    return os.pathsep.join((str(runtime_directory), str(package_root)))


def _contract(
    tmp_path: Path,
    *,
    run_id: str = "m1b-runtime-01",
    cohort: tuple[str, ...] = ("m1b-runtime-01", "m1b-runtime-02"),
    backend: str = "dfhack",
    scripted: bool = True,
    provider: ProviderPolicy | None = None,
) -> RuntimeContract:
    return RuntimeContract(
        run_id=run_id,
        backend=backend,
        model="dfhack-governed-scripted" if scripted else "dfhack-governed-llm-test",
        port=58_001 if run_id.endswith("01") else 58_002,
        nonce="a" * 32 if run_id.endswith("01") else "b" * 32,
        db_path=tmp_path / "registry.sqlite3",
        artifacts_root=tmp_path / "artifacts",
        control_root=tmp_path / "control",
        dfroot=tmp_path / "df",
        seed_save="region3-seed",
        runtime_save=f"runtime-{run_id}",
        cohort_run_ids=cohort,
        provider=provider or ProviderPolicy(),
        scripted=scripted,
        **HASHES,
    )


def test_contract_serialization_and_digest_are_deterministic_and_immutable(
    tmp_path: Path,
) -> None:
    first = _contract(tmp_path)
    second = _contract(tmp_path, cohort=("m1b-runtime-02", "m1b-runtime-01"))

    assert first.identity_payload() == second.identity_payload()
    assert first.contract_sha256 == second.contract_sha256
    assert len(first.contract_sha256) == 64
    assert (
        json.loads(json.dumps(first.environment_identity()))["contract_sha256"]
        == first.contract_sha256
    )
    with pytest.raises(FrozenInstanceError):
        first.port = 59_999  # type: ignore[misc]


def test_contract_binds_nonce_port_seed_code_paths_and_runtime(tmp_path: Path) -> None:
    baseline = _contract(tmp_path)
    baseline_digest = baseline.contract_sha256

    variants = [
        {"nonce": "c" * 32},
        {"port": 58_010},
        {"seed_world_sha256": "7" * 64},
        {"code_sha256": "8" * 64},
        {"runtime_save": "different-runtime"},
        {"control_root": tmp_path / "different-control"},
    ]
    for overrides in variants:
        values = {
            **baseline.__dict__,
            **overrides,
        }
        candidate = RuntimeContract(**values)
        assert candidate.contract_sha256 != baseline_digest


def test_cotenancy_is_symmetric_and_order_independent(tmp_path: Path) -> None:
    run_ids = ("m1b-runtime-03", "m1b-runtime-01", "m1b-runtime-02")
    contracts = [
        _contract(tmp_path, run_id=run_id, cohort=tuple(reversed(run_ids)))
        for run_id in sorted(run_ids)
    ]

    assert len({contract.cohort_digest for contract in contracts}) == 1
    for contract in contracts:
        evidence = contract.cotenancy()
        assert evidence["cohort_size"] == 3
        assert set(evidence["peer_run_ids"]) == set(run_ids) - {contract.run_id}
        for peer_id in evidence["peer_run_ids"]:
            peer = next(item for item in contracts if item.run_id == peer_id)
            assert contract.run_id in peer.cotenancy()["peer_run_ids"]


def test_scripted_environment_is_complete_and_drops_ambient_secrets(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    attempt_dir = (
        tmp_path / "control" / contract.run_id / "attempts" / "attempt-0001"
    )
    argv = RuntimeContract.worker_argv(
        python_executable=Path("/usr/bin/python3"),
        config_path=tmp_path / "one-run.yaml",
        run_id=contract.run_id,
    )
    spec = contract.to_run_spec(
        argv=argv,
        cwd=tmp_path,
        attempt_dir=attempt_dir,
    )
    child = build_sanitized_environment(
        allowlist=spec.env_allowlist,
        overrides=spec.env,
        scripted=spec.scripted,
        source={
            "PATH": "/usr/bin",
            "HOME": "/poison-home",
            "PYTHONPATH": "/poison-pythonpath",
            "OPENROUTER_API_KEY": "ambient-openrouter",
            "GOOGLE_API_KEY": "ambient-google",
            "ANTHROPIC_API_KEY": "ambient-anthropic",
        },
    )

    assert child["FORT_GYM_DISABLE_DOTENV"] == "1"
    assert child["FORT_GYM_TERMINAL_OWNER"] == "supervisor"
    assert child["FORT_GYM_DFHACK_TRANSPORT"] == "native-rpc"
    assert child["DF_PROTO_ENABLED"] == "1"
    assert child["DFHACK_HOST"] == "127.0.0.1"
    assert child["DFHACK_PORT"] == "58001"
    assert child["FORT_GYM_NETWORK_POLICY"] == "loopback-port-only"
    assert child["FORT_GYM_NETWORK_ALLOWED_HOST"] == "127.0.0.1"
    assert child["FORT_GYM_NETWORK_ALLOWED_PORT"] == "58001"
    assert child["FORT_GYM_NETWORK_EVIDENCE_PATH"] == str(
        attempt_dir / "network-denials.jsonl"
    )
    assert child["FORT_GYM_CONTROL_DIR"] == str(attempt_dir)
    assert child["FORT_GYM_RUN_NONCE"] == "a" * 32
    assert child["FORT_GYM_RUN_CONTRACT_SHA256"] == contract.contract_sha256
    assert child["FORT_GYM_RUNTIME_PREPARED"] == "1"
    assert child["FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256"] == "1" * 64
    assert child["FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256"] == "2" * 64
    assert child["FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256"] == "3" * 64
    assert child["FORT_GYM_EXPECTED_SEED_TREE_SHA256"] == "4" * 64
    assert child["FORT_GYM_EXPECTED_SEED_WORLD_SHA256"] == "5" * 64
    assert child["FORT_GYM_DB_PATH"] == str(tmp_path / "registry.sqlite3")
    assert child["ARTIFACTS_DIR"] == str(tmp_path / "artifacts")
    assert child["PYTHONPATH"] == _expected_supervised_pythonpath()
    runtime_directory, package_root = child["PYTHONPATH"].split(os.pathsep)
    assert (Path(runtime_directory) / "sitecustomize.py").is_file()
    assert package_root == str(Path(runtime_contract_module.__file__).parents[3])
    assert "/poison-pythonpath" not in child["PYTHONPATH"]
    assert "HOME" not in child
    assert not any(
        "API_KEY" in name or name.startswith("OPENROUTER_") for name in child
    )
    assert spec.artifact_dir == attempt_dir
    assert spec.trace_path == tmp_path / "artifacts" / contract.run_id / "trace.jsonl"
    assert spec.port_lock_dir == tmp_path / "control" / "port-leases"


def test_provider_free_mock_child_denies_inet_with_deterministic_guard_path(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path, backend="mock")
    attempt_dir = (
        tmp_path / "control" / contract.run_id / "attempts" / "attempt-0002"
    )
    argv = RuntimeContract.worker_argv(
        python_executable=Path("/usr/bin/python3"),
        config_path=tmp_path / "one-run.yaml",
        run_id=contract.run_id,
    )
    spec = contract.to_run_spec(
        argv=argv,
        cwd=tmp_path,
        attempt_dir=attempt_dir,
    )
    child = build_sanitized_environment(
        allowlist=spec.env_allowlist,
        overrides=spec.env,
        scripted=spec.scripted,
        source={"PATH": "/usr/bin", "PYTHONPATH": "/ambient-poison"},
    )

    assert child["FORT_GYM_NETWORK_POLICY"] == "deny-inet"
    assert child["FORT_GYM_NETWORK_EVIDENCE_PATH"] == str(
        spec.artifact_dir / "network-denials.jsonl"
    )
    assert child["FORT_GYM_CONTROL_DIR"] == str(attempt_dir)
    assert "FORT_GYM_NETWORK_ALLOWED_HOST" not in child
    assert "FORT_GYM_NETWORK_ALLOWED_PORT" not in child
    assert child["PYTHONPATH"] == _expected_supervised_pythonpath()
    assert "/ambient-poison" not in child["PYTHONPATH"]
    assert spec.port is None


def test_prepared_runtime_environment_validates_exact_non_secret_identity(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)

    identity = validate_prepared_runtime_environment(
        contract.child_environment(),
        backend="dfhack",
        run_id=contract.run_id,
        seed_save=contract.seed_save,
        runtime_save=contract.runtime_save,
    )

    assert identity is not None
    assert identity.contract_sha256 == contract.contract_sha256
    assert identity.seed_tree_sha256 == contract.seed_tree_sha256
    assert identity.seed_world_sha256 == contract.seed_world_sha256
    summary_identity = identity.summary_identity()
    assert summary_identity["image"] == {
        "manifest_sha256": contract.image_manifest_sha256,
        "config_sha256": contract.image_config_sha256,
        "archive_sha256": contract.image_archive_sha256,
    }
    assert summary_identity["seed"]["world_sha256"] == contract.seed_world_sha256
    assert contract.nonce not in json.dumps(summary_identity, sort_keys=True)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("FORT_GYM_RUNTIME_PREPARED", None, "requires.*PREPARED=1"),
        ("FORT_GYM_RUNTIME_PREPARED", "true", "requires.*PREPARED=1"),
        ("FORT_GYM_EXPECTED_SEED_TREE_SHA256", None, "incomplete"),
        ("FORT_GYM_EXPECTED_SEED_WORLD_SHA256", "SHA256:bad", "malformed"),
        ("FORT_GYM_RUN_CONTRACT_SHA256", "A" * 64, "malformed"),
        ("FORT_GYM_RUN_ID", "different-run", "does not match"),
    ],
)
def test_partial_or_malformed_prepared_runtime_identity_fails_closed(
    tmp_path: Path,
    name: str,
    value: str | None,
    message: str,
) -> None:
    contract = _contract(tmp_path)
    environment = contract.child_environment()
    if value is None:
        environment.pop(name)
    else:
        environment[name] = value

    with pytest.raises(PreparedRuntimeIdentityError, match=message):
        validate_prepared_runtime_environment(
            environment,
            backend="dfhack",
            run_id=contract.run_id,
            seed_save=contract.seed_save,
            runtime_save=contract.runtime_save,
        )


def test_legacy_and_mock_runtime_environment_remain_unprepared() -> None:
    assert (
        validate_prepared_runtime_environment(
            {},
            backend="dfhack",
            run_id="legacy-run",
            seed_save="seed",
            runtime_save="runtime",
        )
        is None
    )
    assert (
        validate_prepared_runtime_environment(
            {"FORT_GYM_RUNTIME_PREPARED": "malformed-but-mock"},
            backend="mock",
            run_id="mock-run",
            seed_save=None,
            runtime_save=None,
        )
        is None
    )


def test_provider_enabled_contract_is_explicit_strict_and_redacted(
    tmp_path: Path,
) -> None:
    provider = ProviderPolicy.openrouter(
        model="openai/test-model",
        provider_name="OpenAI",
        api_key="explicit-test-key",
        max_total_tokens=500,
        max_cost_usd=0.25,
    )
    contract = _contract(tmp_path, scripted=False, provider=provider)
    attempt_dir = (
        tmp_path / "control" / contract.run_id / "attempts" / "attempt-provider"
    )
    argv = RuntimeContract.worker_argv(
        python_executable="/usr/bin/python3",
        config_path=tmp_path / "one-run.yaml",
        run_id=contract.run_id,
    )
    spec = contract.to_run_spec(
        argv=argv,
        cwd=tmp_path,
        attempt_dir=attempt_dir,
    )
    environment = build_sanitized_environment(
        allowlist=spec.env_allowlist,
        overrides=spec.env,
        scripted=spec.scripted,
        source={
            "PATH": "/usr/bin",
            "PYTHONPATH": "/ambient-poison",
            "OPENROUTER_API_KEY": "ambient-wrong-key",
        },
    )

    assert spec.provider_enabled is True
    assert spec.provider_route == "openrouter"
    assert spec.provider_model == "openai/test-model"
    assert spec.provider_name == "OpenAI"
    assert spec.max_total_tokens == 500
    assert spec.max_cost_usd == 0.25
    assert environment["OPENROUTER_API_KEY"] == "explicit-test-key"
    assert environment["OPENROUTER_STRICT_SUPERVISED"] == "1"
    assert environment["FORT_GYM_CONTROL_DIR"] == str(attempt_dir)
    assert environment["PYTHONPATH"] == _expected_supervised_pythonpath()
    assert "/ambient-poison" not in environment["PYTHONPATH"]
    assert "FORT_GYM_NETWORK_POLICY" not in environment
    assert "FORT_GYM_NETWORK_ALLOWED_HOST" not in environment
    assert "FORT_GYM_NETWORK_ALLOWED_PORT" not in environment
    assert "FORT_GYM_NETWORK_EVIDENCE_PATH" not in environment
    serialized_identity = json.dumps(contract.environment_identity(), sort_keys=True)
    assert "explicit-test-key" not in serialized_identity
    assert "ambient-wrong-key" not in serialized_identity
    assert "OPENROUTER_API_KEY" not in serialized_identity
    assert "API_KEY" not in serialized_identity
    assert "explicit-test-key" not in repr(spec.environment_identity)
    assert contract.environment_identity()["provider"]["credential_present"] is True


@pytest.mark.parametrize(
    ("attempt_dir", "message"),
    [
        (Path("relative-attempt"), "must be absolute"),
        (Path("{outside}"), "contained under"),
        (Path("{root}"), "identify a child"),
        (Path("{root}") / "attempt-0001" / ".." / "escape", "path traversal"),
    ],
)
def test_explicit_attempt_directory_fails_closed_outside_exact_run_attempts(
    tmp_path: Path,
    attempt_dir: Path,
    message: str,
) -> None:
    contract = _contract(tmp_path)
    attempts_root = tmp_path / "control" / contract.run_id / "attempts"
    candidate = Path(
        str(attempt_dir).format(
            outside=tmp_path / "control" / "different-run" / "attempts" / "one",
            root=attempts_root,
        )
    )
    argv = RuntimeContract.worker_argv(
        python_executable="/usr/bin/python3",
        config_path=tmp_path / "one-run.yaml",
        run_id=contract.run_id,
    )

    with pytest.raises(ValueError, match=message):
        contract.to_run_spec(
            argv=argv,
            cwd=tmp_path,
            attempt_dir=candidate,
        )


def test_legacy_run_spec_attempt_directory_default_remains_compatible(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    argv = RuntimeContract.worker_argv(
        python_executable="/usr/bin/python3",
        config_path=tmp_path / "one-run.yaml",
        run_id=contract.run_id,
    )

    spec = contract.to_run_spec(argv=argv, cwd=tmp_path)

    assert spec.artifact_dir == tmp_path / "control" / contract.run_id
    assert spec.env["FORT_GYM_NETWORK_EVIDENCE_PATH"] == str(
        spec.artifact_dir / "network-denials.jsonl"
    )


@pytest.mark.parametrize(
    "provider",
    [
        ProviderPolicy(),
        ProviderPolicy.openrouter(
            model="openai/test-model",
            provider_name="OpenAI",
            api_key="key",
            max_total_tokens=1,
            max_cost_usd=0.01,
        ),
    ],
)
def test_worker_argv_must_bind_exact_run_id(
    tmp_path: Path,
    provider: ProviderPolicy,
) -> None:
    contract = _contract(
        tmp_path,
        scripted=not provider.enabled,
        provider=provider,
    )
    with pytest.raises(ValueError, match="exact external run ID"):
        contract.to_run_spec(
            argv=("/usr/bin/python3", "-m", "fort_gym.bench.cli", "experiment"),
            cwd=tmp_path,
        )


def test_invalid_identity_provider_and_path_inputs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nonce"):
        RuntimeContract(**{**_contract(tmp_path).__dict__, "nonce": "too-short"})
    with pytest.raises(ValueError, match="SHA-256"):
        RuntimeContract(
            **{
                **_contract(tmp_path).__dict__,
                "image_manifest_sha256": "not-a-digest",
            }
        )
    with pytest.raises(ValueError, match="control_root"):
        RuntimeContract(
            **{
                **_contract(tmp_path).__dict__,
                "control_root": tmp_path / "artifacts",
            }
        )
    with pytest.raises(ValueError, match="scripted"):
        _contract(
            tmp_path,
            scripted=True,
            provider=ProviderPolicy.openrouter(
                model="openai/test-model",
                provider_name="OpenAI",
                api_key="key",
                max_total_tokens=1,
                max_cost_usd=0.01,
            ),
        )
    with pytest.raises(ValueError, match="positive"):
        ProviderPolicy.openrouter(
            model="openai/test-model",
            provider_name="OpenAI",
            api_key="key",
            max_total_tokens=0,
            max_cost_usd=0.01,
        )


def test_port_slot_allocator_is_bounded() -> None:
    assert (
        RuntimeContract.port_for_slot(base_port=58_000, slot=7, cohort_size=8) == 58_007
    )
    with pytest.raises(ValueError):
        RuntimeContract.port_for_slot(base_port=65_535, slot=1, cohort_size=2)
    with pytest.raises(ValueError):
        RuntimeContract.port_for_slot(base_port=58_000, slot=8, cohort_size=8)
