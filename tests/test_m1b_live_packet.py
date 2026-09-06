from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from infra.m1b.build_live_packet import (
    _EXPECTED_AUTHORITY,
    DOCKER_RELEASE_KEY_FINGERPRINT,
    DOCKER_RELEASE_SIGNING_FINGERPRINT,
    DOCKER_RUNTIME_BINARIES,
    DOCKER_RUNTIME_INPUTS,
    DOCKER_RUNTIME_PACKAGES,
    EXPECTED_CANONICAL_GENERATED,
    EXPECTED_PROTOC_SHA256,
    EXPECTED_RUNTIME_BINDING_SHA256,
    EXPECTED_SEED_TREE_SHA256,
    EXPECTED_SEED_WORLD_SHA256,
    EXPECTED_WIRE_GENERATED,
    EXPECTED_WIRE_REFERENCE_SHA256,
    EXPECTED_ZSTD_SHA256,
    MAX_RETAINED_PACKETS_PER_ROOT,
    PacketError,
    _copy_snapshot_file,
    _deterministic_tar,
    _enforce_packet_retention,
    _generate_proto_bindings,
    _git_source_paths,
    _is_live_source_path,
    _read_zstd_tar_members,
    _reject_sensitive_bytes,
    _safe_relative_path,
    _seed_manifest,
    _verify_deterministic_packet_pair,
    _verify_canonical_proto_bindings,
    _verify_docker_runtime,
    _verify_oci_archive,
    _verify_repo_snapshot,
    _verify_wheelhouse,
)

REPO_ROOT = Path(__file__).parents[1]
PRESERVATION_ROOT = Path(
    "/Users/cdossman/Documents/Open Source Projects/"
    "fort-gym-m0a-preservation-20260816/archives"
)
DFHACK_SOURCE_ROOT = PRESERVATION_ROOT / "dfhack-sources/dfhack-0.47.05-r8"
SEED_ROOT = PRESERVATION_ROOT / "seed_saves/seed_region3_fresh"
RUNTIME_ARCHIVE = Path(
    "/Users/cdossman/Documents/Open Source Projects/"
    "fort-gym-m1a-feasibility-20260816/raw/_artifacts/final-host-evidence/"
    "fortgym-df-m1a.tar.zst"
)
CANONICAL_PROTO_ROOT = (
    PRESERVATION_ROOT / "fort-gym-calib-g7v5/fort_gym/bench/env/remote_proto/generated"
)
INPUT_PRIMITIVES_ROOT = Path(
    os.environ.get(
        "FORTGYM_M1B_INPUT_PRIMITIVES",
        "/Volumes/Crucial X10/computer-cleanup-archive/"
        "2026-09-04-fort-gym-m1b-live-runs/"
        "fort-gym-m1b-live-20260817/input-primitives",
    )
)
PROTOC = INPUT_PRIMITIVES_ROOT / "protoc-29.3-root/bin/protoc"
ZSTD = INPUT_PRIMITIVES_ROOT / "zstd-root/bin/zstd"
WHEELHOUSE_ROOT = Path(INPUT_PRIMITIVES_ROOT / "wheelhouse")
DOCKER_RUNTIME_ROOT = INPUT_PRIMITIVES_ROOT / "docker-ce-debian12-amd64"
GPGV = Path("/opt/homebrew/bin/gpgv")


def test_authority_projection_is_identical_across_live_execution_seams() -> None:
    from infra.m1b import run_live_acceptance as host_runner

    acceptance = yaml.safe_load(
        (REPO_ROOT / "infra/m1b/acceptance.yaml").read_text(encoding="utf-8")
    )
    assert acceptance["authorization"] == _EXPECTED_AUTHORITY
    infrastructure = acceptance["authorization"]["new_paid_infrastructure"]
    assert infrastructure["prior_reserved_usd"] + infrastructure["daily_ceiling_usd"] == 250
    assert infrastructure["authorized_vm_count"] == 26
    assert infrastructure["authorized_vm_count"] * 8 <= infrastructure["daily_ceiling_usd"]
    assert infrastructure["max_concurrent_vm_count"] == 1
    packet_authority = {
        "provider_calls": 0,
        "provider_cost_usd": 0,
        "paid_models": "forbidden",
        "production_access": "forbidden",
        "production_mutation": "forbidden",
        "publish_deploy_push_tag_e1": "forbidden",
        "infrastructure_daily_ceiling_usd": infrastructure["daily_ceiling_usd"],
        "infrastructure_authorized_local_date": (
            infrastructure["authorized_local_date"].isoformat()
        ),
        "infrastructure_authority_expires_at": (
            infrastructure["expires_at"].isoformat().replace("+00:00", "Z")
        ),
        "ephemeral_only": True,
    }
    assert host_runner._EXPECTED_PACKET_AUTHORITY == packet_authority

    expected_projection = (
        f'"infrastructure_daily_ceiling_usd": {infrastructure["daily_ceiling_usd"]},'
    )
    bootstrap = (REPO_ROOT / "infra/m1b/bootstrap_live_host.sh").read_text(
        encoding="utf-8"
    )
    lifecycle = (REPO_ROOT / "infra/m1b/run_gcp_live_acceptance.sh").read_text(
        encoding="utf-8"
    )
    root_broker = (REPO_ROOT / "infra/m1b/root_broker.py").read_text(encoding="utf-8")
    outer_guard = (REPO_ROOT / "infra/m1b/activate_outer_egress_guard.sh").read_text(
        encoding="utf-8"
    )
    expiry_guard = (REPO_ROOT / "infra/m1b/expire_live_host.sh").read_text(
        encoding="utf-8"
    )
    assert expected_projection in bootstrap
    assert expected_projection in lifecycle
    assert (
        f'authority.get("infrastructure_daily_ceiling_usd") '
        f"!= {infrastructure['daily_ceiling_usd']}"
    ) in root_broker
    assert (
        f"DAILY_CEILING_CENTS={infrastructure['daily_ceiling_usd'] * 100}" in lifecycle
    )
    assert (
        f"MAX_AUTHORIZED_VM_COUNT={infrastructure['authorized_vm_count']}" in lifecycle
    )

    readme = " ".join(
        (REPO_ROOT / "infra/m1b/README.md").read_text(encoding="utf-8").split()
    )
    expiry = infrastructure["expires_at"].isoformat().replace("+00:00", "Z")
    for source in (bootstrap, outer_guard, expiry_guard, lifecycle, root_broker):
        assert expiry in source
    authorized_date = infrastructure["authorized_local_date"].isoformat()
    for source in (bootstrap, lifecycle, root_broker):
        assert authorized_date in source
    assert (
        "The most recently recorded authority permitted "
        f"up to USD {infrastructure['daily_ceiling_usd']} on "
        f"{infrastructure['authorized_local_date'].isoformat()} "
        f"{infrastructure['timezone']}, expiring at {expiry}"
    ) in readme


def _require_local_path(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"retained local prerequisite is unavailable: {path}")
    return path


@pytest.mark.parametrize(
    "raw",
    (
        "",
        "/absolute.py",
        "../escape.py",
        "nested/../../escape.py",
        ".git/config",
        "nested/.venv/key",
        "pkg/__pycache__/module.pyc",
        ".env",
        "nested/.env",
        "nested/.env.production",
        "module.pyc",
        "module.pyo",
        "private.pem",
        "config/credentials.json",
        ".DS_Store",
        "nul\x00name",
    ),
)
def test_safe_relative_path_rejects_escape_secret_and_cache_paths(raw: str) -> None:
    with pytest.raises(PacketError):
        _safe_relative_path(raw)


def test_safe_relative_path_preserves_public_env_template() -> None:
    assert (
        _safe_relative_path("config/.env.example").as_posix() == "config/.env.example"
    )


def test_live_source_allows_only_measurement_bound_scripts() -> None:
    assert _is_live_source_path(Path("scripts/run_p1_live_calibration.py"))
    assert _is_live_source_path(Path("scripts/build_p1_live_calibration_bundle.py"))
    assert not _is_live_source_path(Path("scripts/unrelated.py"))


def test_live_source_allows_only_frozen_local_credit_tests() -> None:
    expected = {
        Path("tests/conftest.py"),
        Path("tests/test_cap_fake_end_to_end.py"),
        Path("tests/test_process_supervisor.py"),
        Path("tests/test_provider_environment_subprocess.py"),
        Path("tests/test_residue_audit.py"),
        Path("tests/test_runtime_controller.py"),
        Path("tests/test_supervised_manager.py"),
    }

    assert all(_is_live_source_path(path) for path in expected)
    assert not _is_live_source_path(Path("tests/test_m1b_cloud_lifecycle.py"))
    assert not _is_live_source_path(Path("tests/helpers/test_unrelated.py"))


def test_git_source_enumeration_rejects_tracked_and_ignored_runtime_outputs(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "fort_gym/bench/keep.py"
    tracked_output = repo / "fort_gym/artifacts/tracked/trace.jsonl"
    ignored_output = repo / "fort_gym/artifacts/ignored/trace.jsonl"
    source.parent.mkdir(parents=True)
    tracked_output.parent.mkdir(parents=True)
    ignored_output.parent.mkdir(parents=True)
    source.write_text("SOURCE = True\n", encoding="utf-8")
    tracked_output.write_text('{"tracked":true}\n', encoding="utf-8")
    ignored_output.write_text('{"ignored":true}\n', encoding="utf-8")
    (repo / ".gitignore").write_text("fort_gym/artifacts/ignored/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "add", ".gitignore", "fort_gym/bench/keep.py"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "add", "-f", "fort_gym/artifacts/tracked/trace.jsonl"],
        cwd=repo,
        check=True,
    )

    assert _is_live_source_path(Path("fort_gym/bench/keep.py"))
    assert not _is_live_source_path(Path("fort_gym/artifacts/tracked/trace.jsonl"))
    assert not _is_live_source_path(Path("fort_gym/artifacts/ignored/trace.jsonl"))
    assert (
        subprocess.run(
            [
                "git",
                "ls-files",
                "--error-unmatch",
                "fort_gym/artifacts/tracked/trace.jsonl",
            ],
            cwd=repo,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "fort_gym/artifacts/ignored/trace.jsonl"],
            cwd=repo,
            check=False,
        ).returncode
        == 0
    )
    assert _git_source_paths(repo) == [Path("fort_gym/bench/keep.py")]


@pytest.mark.parametrize(
    "secret",
    (
        b"-----BEGIN " + b"PRIVATE KEY-----\n",
        b"AI" + b"za0123456789abcdefghijklmnopqrstuvwxyz",
        b"AK" + b"IA0123456789ABCDEF",
        b"gh" + b"p_0123456789abcdefghijklmnop",
        b"sk-" + b"or-v1-0123456789abcdefghijklmnop",
        b"xo" + b"xb-0123456789-abcdefghijklmnop",
    ),
)
def test_credential_shaped_source_bytes_fail_closed(secret: bytes) -> None:
    with pytest.raises(PacketError, match="credential-shaped"):
        _reject_sensitive_bytes(Path("source.txt"), b"prefix " + secret + b" suffix")


def test_placeholder_provider_key_name_is_not_a_secret() -> None:
    _reject_sensitive_bytes(Path("source.py"), b"OPENROUTER_API_KEY=poison-test-value")


def test_deterministic_tar_ignores_source_mtime_and_owner(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for root in (first, second):
        (root / "nested").mkdir()
        (root / "nested/data.txt").write_bytes(b"same bytes\n")
        (root / "run.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
        (root / "nested/data.txt").chmod(0o644)
        (root / "run.sh").chmod(0o755)
    os.utime(first / "nested/data.txt", (1, 1))
    os.utime(second / "nested/data.txt", (2_000_000_000, 2_000_000_000))
    first_tar = tmp_path / "first.tar"
    second_tar = tmp_path / "second.tar"

    _deterministic_tar(first, first_tar)
    _deterministic_tar(second, second_tar)

    assert first_tar.read_bytes() == second_tar.read_bytes()
    with tarfile.open(first_tar, mode="r:") as archive:
        members = archive.getmembers()
    assert [member.name for member in members] == ["nested/data.txt", "run.sh"]
    assert [(member.uid, member.gid, member.mtime) for member in members] == [
        (0, 0, 0),
        (0, 0, 0),
    ]
    assert [member.mode for member in members] == [0o644, 0o755]


def test_packet_retention_guard_allows_rollover_but_blocks_third(
    tmp_path: Path,
) -> None:
    first = tmp_path / "packet-first"
    first.mkdir()
    (first / "PACKET.json").write_text("{}\n", encoding="utf-8")
    (first / "MANIFEST.sha256").write_text("manifest\n", encoding="utf-8")
    _enforce_packet_retention(tmp_path / "packet-second")

    second = tmp_path / "packet-second"
    second.mkdir()
    (second / "PACKET.json").write_text("{}\n", encoding="utf-8")
    (second / "MANIFEST.sha256").write_text("manifest\n", encoding="utf-8")

    assert MAX_RETAINED_PACKETS_PER_ROOT == 2
    with pytest.raises(PacketError, match="packet retention limit reached"):
        _enforce_packet_retention(tmp_path / "packet-third")


def test_determinism_receipt_replaces_second_retained_packet(tmp_path: Path) -> None:
    first = tmp_path / "packet-first"
    second = tmp_path / "packet-second"
    first.mkdir()
    second.mkdir()
    for packet in (first, second):
        (packet / "MANIFEST.sha256").write_text(
            "0" * 64 + "  PACKET.json\n", encoding="ascii"
        )

    receipt = _verify_deterministic_packet_pair(first, second)

    assert receipt["independent_builds"] == 2
    assert receipt["retained_packets"] == 1
    assert "temporary_verification_packet_removed" not in receipt


def test_determinism_verification_rejects_different_manifests(tmp_path: Path) -> None:
    first = tmp_path / "packet-first"
    second = tmp_path / "packet-second"
    first.mkdir()
    second.mkdir()
    (first / "MANIFEST.sha256").write_text("first\n", encoding="ascii")
    (second / "MANIFEST.sha256").write_text("second\n", encoding="ascii")

    with pytest.raises(PacketError, match="not byte-identical"):
        _verify_deterministic_packet_pair(first, second)


def test_missing_selected_oci_member_fails_closed(tmp_path: Path) -> None:
    zstd = _require_local_path(ZSTD)
    source_tar = tmp_path / "source.tar"
    with tarfile.open(source_tar, mode="w") as archive:
        payload = b"{}"
        info = tarfile.TarInfo("index.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    compressed = tmp_path / "source.tar.zst"
    subprocess.run(
        [str(zstd), "-q", "-f", str(source_tar), "-o", str(compressed)],
        check=True,
        capture_output=True,
    )

    with pytest.raises(PacketError, match="lacks members"):
        _read_zstd_tar_members(
            compressed,
            zstd=zstd,
            selected={"index.json", "missing.json"},
        )


def test_preserved_seed_manifest_matches_frozen_identity() -> None:
    seed_root = _require_local_path(SEED_ROOT)

    manifest, record = _seed_manifest(seed_root)

    assert hashlib.sha256(manifest).hexdigest() == EXPECTED_SEED_TREE_SHA256
    assert record == {
        "tree_sha256": EXPECTED_SEED_TREE_SHA256,
        "world_sha256": EXPECTED_SEED_WORLD_SHA256,
        "file_count": 127,
        "file_bytes": 8_591_055,
    }
    assert manifest.count(b"\0") == 127


def test_exact_dfhack_047_proto_generation_is_pinned(tmp_path: Path) -> None:
    source_root = _require_local_path(DFHACK_SOURCE_ROOT)
    protoc = _require_local_path(PROTOC)

    generated, record = _generate_proto_bindings(
        dfhack_source_root=source_root,
        protoc=protoc,
        scratch_root=tmp_path,
    )

    assert record["protocol_version"] == "0.47.05-r8"
    assert {path.name for path in generated.iterdir()} == set(EXPECTED_WIRE_GENERATED)
    assert {
        item["path"]: item["sha256"] for item in record["generated"]
    } == EXPECTED_WIRE_GENERATED
    assert record["wire_reference_sha256"] == EXPECTED_WIRE_REFERENCE_SHA256
    assert record["protoc_sha256"] == EXPECTED_PROTOC_SHA256


def test_preserved_zstd_builder_binary_is_pinned() -> None:
    zstd = _require_local_path(ZSTD)

    assert hashlib.sha256(zstd.read_bytes()).hexdigest() == EXPECTED_ZSTD_SHA256


def test_canonical_g7_v5_runtime_bindings_remain_byte_exact() -> None:
    root = _require_local_path(CANONICAL_PROTO_ROOT)

    generated, record = _verify_canonical_proto_bindings(root)

    assert generated == root.resolve()
    assert record["protocol_version"] == "52.04-r1"
    assert record["wire_target"] == "0.47.05-r8"
    assert record["runtime_binding_sha256"] == EXPECTED_RUNTIME_BINDING_SHA256
    assert {
        item["path"]: item["sha256"] for item in record["generated"]
    } == EXPECTED_CANONICAL_GENERATED


def test_pinned_offline_linux_wheelhouse_is_complete_and_provider_free() -> None:
    root = _require_local_path(WHEELHOUSE_ROOT)

    record = _verify_wheelhouse(
        wheelhouse_root=root,
        requirements_path=REPO_ROOT / "infra/m1b/live-requirements.lock",
        digest_manifest_path=REPO_ROOT / "infra/m1b/live-wheelhouse.sha256",
    )

    assert record["python"] == "3.11"
    assert record["platform"] == "linux/x86_64"
    assert record["file_count"] == 34
    assert record["total_bytes"] == 18_917_535
    assert any(
        item["filename"].startswith("protobuf-6.31.1-") for item in record["files"]
    )
    assert not any(
        item["filename"].startswith(("openai-", "anthropic-"))
        for item in record["files"]
    )


def test_offline_docker_ce_runtime_is_signed_exact_and_binary_bound() -> None:
    root = _require_local_path(DOCKER_RUNTIME_ROOT)
    gpgv = _require_local_path(GPGV)

    record = _verify_docker_runtime(docker_runtime_root=root, gpgv=gpgv)

    assert record["schema"] == "fortgym.m1b-docker-runtime/v1"
    assert record["platform"] == "linux/amd64"
    assert record["distribution"] == "debian/12"
    assert record["docker_server_version"] == "29.1.3"
    assert record["containerd_version"] == "2.2.1"
    assert record["containerd_snapshotter_required"] is True
    assert record["network_install_required"] is False
    assert (
        record["signed_repository"]["release_key_fingerprint"]
        == DOCKER_RELEASE_KEY_FINGERPRINT
    )
    assert (
        record["signed_repository"]["release_signing_fingerprint"]
        == DOCKER_RELEASE_SIGNING_FINGERPRINT
    )
    assert record["signed_repository"]["signature_verified"] is True
    assert {item["path"] for item in record["archive_members"]} == set(
        DOCKER_RUNTIME_INPUTS
    )
    assert {item["package"] for item in record["packages"]} == set(
        DOCKER_RUNTIME_PACKAGES
    )
    assert {item["path"] for item in record["binaries"]} == set(DOCKER_RUNTIME_BINARIES)
    assert all(item["mode"] == "0755" for item in record["binaries"])
    assert all(item["architecture"] == "amd64" for item in record["binaries"])


def test_docker_runtime_input_root_rejects_unverified_members(tmp_path: Path) -> None:
    (tmp_path / "unverified.deb").write_bytes(b"not trusted")

    with pytest.raises(PacketError, match="filename/type/mode set differs"):
        _verify_docker_runtime(docker_runtime_root=tmp_path, gpgv=Path("/bin/false"))


def test_wheelhouse_rejects_provider_sdk_requirement(tmp_path: Path) -> None:
    wheel = tmp_path / "openai-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"not a real wheel")
    requirements = tmp_path / "requirements.lock"
    requirements.write_text(
        "protobuf==6.31.1\nopenai==1.0.0\n",
        encoding="utf-8",
    )
    digest_manifest = tmp_path / "wheelhouse.sha256"
    digest_manifest.write_text(
        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n",
        encoding="utf-8",
    )

    with pytest.raises(PacketError, match="provider SDKs"):
        _verify_wheelhouse(
            wheelhouse_root=tmp_path,
            requirements_path=requirements,
            digest_manifest_path=digest_manifest,
        )


def test_wheelhouse_rejects_unverified_subtrees(tmp_path: Path) -> None:
    wheel = tmp_path / "protobuf-6.31.1-py3-none-any.whl"
    wheel.write_bytes(b"not a real wheel")
    (tmp_path / "unverified").mkdir()
    (tmp_path / "unverified/secret.txt").write_text("unverified\n", encoding="utf-8")
    requirements = tmp_path / "requirements.lock"
    requirements.write_text("protobuf==6.31.1\n", encoding="utf-8")
    digest_manifest = tmp_path / "wheelhouse.sha256"
    digest_manifest.write_text(
        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n",
        encoding="utf-8",
    )

    with pytest.raises(PacketError, match="only pinned regular"):
        _verify_wheelhouse(
            wheelhouse_root=tmp_path,
            requirements_path=requirements,
            digest_manifest_path=digest_manifest,
        )


def test_preserved_oci_archive_and_hook_layer_match_source() -> None:
    archive = _require_local_path(RUNTIME_ARCHIVE)
    zstd = _require_local_path(ZSTD)

    record = _verify_oci_archive(
        archive,
        zstd=zstd,
        repo_hook_root=REPO_ROOT / "hook",
    )

    assert record["platform"] == "linux/amd64"
    assert record["hook_count"] == 20
    assert record["size_bytes"] == 168_197_408


def test_git_source_enumeration_excludes_generated_cache_and_secrets() -> None:
    paths = _git_source_paths(REPO_ROOT)
    names = {path.as_posix() for path in paths}

    assert "infra/m1b/build_live_packet.py" in names
    assert ".env" not in names
    assert not any("/__pycache__/" in f"/{name}/" for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)
    assert not any(
        name.startswith("fort_gym/bench/env/remote_proto/generated/") for name in names
    )
    assert not any(name.startswith("fort_gym/artifacts/") for name in names)
    assert not any(name.startswith(("docs/", "experiments/", "web/")) for name in names)
    assert not any(
        name.startswith("infra/") and not name.startswith("infra/m1b/")
        for name in names
    )
    assert shutil.which("git") is not None


def test_current_two_fort_sources_survive_packet_snapshot(tmp_path: Path) -> None:
    """Check source assembly without creating an authorized launch packet."""
    paths = _git_source_paths(REPO_ROOT)
    required = {
        "infra/m1b/diagnostics.py",
        "infra/m1b/run_live_acceptance.py",
        "infra/m1b/run_gcp_live_acceptance.sh",
        "infra/m1b/root_broker.py",
        "fort_gym/bench/run/fault_driver.py",
        "fort_gym/bench/run/live_acceptance.py",
    }
    assert required <= {path.as_posix() for path in paths}
    records = []
    for relative in paths:
        destination = tmp_path / relative
        record = _copy_snapshot_file(REPO_ROOT / relative, destination)
        records.append({"path": relative.as_posix(), **record})
        if relative.as_posix() in required and relative.suffix == ".py":
            compile(destination.read_bytes(), relative.as_posix(), "exec")
    _verify_repo_snapshot(REPO_ROOT, paths, records)
    assert b"--two-fort-diagnostic" in (
        tmp_path / "infra/m1b/run_gcp_live_acceptance.sh"
    ).read_bytes()


def test_expired_authority_refuses_packet_before_copying_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.m1b import build_live_packet as builder

    class ExpiredClock:
        @staticmethod
        def now(tz: object) -> datetime:
            assert tz is UTC
            return builder._AUTHORITY_EXPIRY

    monkeypatch.setattr(builder, "datetime", ExpiredClock)
    output = tmp_path / "packet"
    absent = tmp_path / "unread-input"
    with pytest.raises(PacketError, match="operator infrastructure authority has expired"):
        builder.build_packet(
            repo_root=REPO_ROOT,
            output_dir=output,
            runtime_archive=absent,
            seed_root=absent,
            dfhack_source_root=absent,
            canonical_proto_root=absent,
            wheelhouse_root=absent,
            docker_runtime_root=absent,
            protoc=absent,
            zstd=absent,
            gpgv=absent,
        )
    assert list(tmp_path.iterdir()) == []
