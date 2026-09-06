#!/usr/bin/env python3
"""Build and verify the deterministic, provider-free input packet for live M1b.

The packet is assembled from the exact dirty worktree, the retained M1a OCI
archive, the preserved seed oracle, and protobuf sources from the pinned
DFHack 0.47.05-r8 checkout. It never invokes Git network operations and it
refuses symlinks, ignored files, secrets, digest drift, an existing output
directory, or an over-retained packet root. The CLI verifies determinism with
an independent temporary rebuild and retains only one packet.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

SCHEMA = "fortgym.m1b-live-input-packet/v1"
SOURCE_SCHEMA = "fortgym.m1b-live-source-manifest/v1"
PROTO_SCHEMA = "fortgym.m1b-runtime-proto/v1"
WIRE_PROTO_SCHEMA = "fortgym.m1b-wire-reference-proto/v1"
WHEELHOUSE_SCHEMA = "fortgym.m1b-live-wheelhouse/v1"
DOCKER_RUNTIME_SCHEMA = "fortgym.m1b-docker-runtime/v1"
DETERMINISM_SCHEMA = "fortgym.m1b-packet-determinism/v1"
MAX_RETAINED_PACKETS_PER_ROOT = 2
BASE_HEAD = "236d3187c548b9bc03c4c99829d479d381a008d5"
DFHACK_SOURCE_HEAD = "fed9f763c9c9b0f64d45e8d7bec626f492c752fe"
CANONICAL_PROTO_VERSION = "52.04-r1"
WIRE_PROTO_VERSION = "0.47.05-r8"
EXPECTED_RUNTIME_BINDING_SHA256 = (
    "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f"
)
EXPECTED_WIRE_REFERENCE_SHA256 = (
    "f51106398e5347629b38232447a7cc5a319b58e0c75065324b1eebb2f21cce63"
)
EXPECTED_PROTOC_SHA256 = (
    "8949fe76a001b29303d6b24c106e3b1da0b19fd6fe412038a2d2fce18864a5b0"
)
EXPECTED_ZSTD_SHA256 = (
    "d36baef4919b567feff3973ef2edc07e0373b8015495f0248b80e3646d383cee"
)
EXPECTED_ARCHIVE_SHA256 = (
    "87d66d26553cb271af1b784405d63ea6b95f3bbe20e9429f05e6412133d1f43a"
)
EXPECTED_ARCHIVE_TAR_SHA256 = (
    "39e4cfce8cc65ca4f4a761fd732cc5d3c2faa8d237b85992dae6da1076f8e756"
)
EXPECTED_IMAGE_MANIFEST_SHA256 = (
    "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
)
EXPECTED_IMAGE_CONFIG_SHA256 = (
    "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
)
EXPECTED_SEED_TREE_SHA256 = (
    "49ba1de07b62e7afda93b42059b6c566598bb0f4c83d11ae1dfdb78b54cd9ec0"
)
EXPECTED_SEED_WORLD_SHA256 = (
    "070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d"
)
HOOK_LAYER_SHA256 = "f72894636c450eb191bca1187abe7b4f5472227382f16d92ba6b5e5add77b048"

DOCKER_RELEASE_KEY_FINGERPRINT = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
DOCKER_RELEASE_SIGNING_FINGERPRINT = "D3306A018370199E527AE7997EA0A9C3F273FCD8"
DOCKER_REPOSITORY_BASE_URL = "https://download.docker.com/linux/debian"
DOCKER_RUNTIME_INPUTS = {
    "InRelease": (
        "19916250e8c2de32f5938227de988b846c36ff0def8dabbb149592c949b80b85",
        46_614,
    ),
    "Packages.gz": (
        "c745da94edd1809aa74f0bf45a72b5935e649d524de6405695dbdf4d5e54d7fd",
        95_006,
    ),
    "docker-keyring.gpg": (
        "a09e26b72228e330d55bf134b8eaca57365ef44bf70b8e27c5f55ea87a8b05e2",
        2_760,
    ),
    "containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb": (
        "3505acd8a8124077df5608293e933c5dfb0dac988f143019fa6efe98e79b92d5",
        23_371_888,
    ),
    "docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb": (
        "fa4c2ad37fa4e5bc4bc5bd4098daec153e546c9ccd5419adf8f91e54f0a0e2bd",
        16_294_920,
    ),
    "docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb": (
        "809c748027406afb4563bf61886e5ec0e3b5d34ff0353256ae618a2c6c5b29fc",
        21_018_900,
    ),
}
DOCKER_RUNTIME_PACKAGES = {
    "containerd.io": {
        "version": "2.2.1-1~debian.12~bookworm",
        "filename": "containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb",
    },
    "docker-ce": {
        "version": "5:29.1.3-1~debian.12~bookworm",
        "filename": "docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb",
    },
    "docker-ce-cli": {
        "version": "5:29.1.3-1~debian.12~bookworm",
        "filename": "docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb",
    },
}
DOCKER_RUNTIME_BINARIES = {
    "/usr/bin/containerd": (
        "containerd.io",
        "8daa1fcfd4007b35fdc5240b2a2c57290bbe9bd4e015b945bb011819acb8f2e0",
        47_794_968,
    ),
    "/usr/bin/containerd-shim-runc-v2": (
        "containerd.io",
        "fef09005f009695a8a71427570efd9a4c979a2bb6f45b72c25f673aa39f6f9f2",
        8_310_616,
    ),
    "/usr/bin/ctr": (
        "containerd.io",
        "5cbd83cbc7d90828804bde5b10c721b9067add62979b6e45ee1abc80b26e4edb",
        24_890_808,
    ),
    "/usr/bin/runc": (
        "containerd.io",
        "488440797ffe0e90dcfa03537291ad6e7dfe260a0ffe7c395356db242226510e",
        12_019_264,
    ),
    "/usr/bin/docker": (
        "docker-ce-cli",
        "57d51e83d3673f4f40ba54c67f8b9ec75d9e3401c5f0795c5f443366eb9c85ec",
        43_984_210,
    ),
    "/usr/bin/docker-proxy": (
        "docker-ce",
        "4068c3ddb30f9d304101dfab6901559337611236e359da3cc8494e2a1ec98530",
        2_831_666,
    ),
    "/usr/bin/dockerd": (
        "docker-ce",
        "978d5d2e4f36c2904ef6787d0fd148b863a1e2556436900f8278c721b7d07127",
        94_463_240,
    ),
    "/usr/libexec/docker/docker-init": (
        "docker-ce",
        "b831fc949adfbf8afa5c8ccef4db0dacfc92f2cc884d9fcb50382eae17c60626",
        708_456,
    ),
}

PROTO_SOURCES = {
    "AdventureControl.proto": (
        "plugins/proto/AdventureControl.proto",
        "5597ceccc294ac4f82b72d407656fa2320ad0da22f36e036afd77c69a2e0f7ff",
    ),
    "Basic.proto": (
        "library/proto/Basic.proto",
        "4ae6901ed5f4ba7bdcc4b634d284639fa03d1b048c7a2d6aafaaa4909dcaa948",
    ),
    "BasicApi.proto": (
        "library/proto/BasicApi.proto",
        "266948bf7fd3153ad83a543637715c72cee48a3a712ed402f610afdacb6c6c66",
    ),
    "CoreProtocol.proto": (
        "library/proto/CoreProtocol.proto",
        "12fd8679f6f95fb40e853bab8ff34f30631a89d51f8ba87b8c8db828214b24dc",
    ),
    "DwarfControl.proto": (
        "plugins/proto/DwarfControl.proto",
        "525221cb5ea0b66b086cfcd500fb85dc0773c51c92819e9ffb8dcc6e3b728723",
    ),
    "ItemdefInstrument.proto": (
        "plugins/proto/ItemdefInstrument.proto",
        "131d8fed4bd3e3256acd594001404087accb05806ff7dedb8585deb924489249",
    ),
    "RemoteFortressReader.proto": (
        "plugins/proto/RemoteFortressReader.proto",
        "50f4f8a00bd3ae2e1be70b7b5499135bffd3fb5cc368a48bfe7f1402d2501ce3",
    ),
    "ui_sidebar_mode.proto": (
        "plugins/proto/ui_sidebar_mode.proto",
        "7e95e51f8e61c1e12bc2e714d0181bee7700eb1ad0e9cfe8f3df7386c1b08b61",
    ),
}

EXPECTED_WIRE_GENERATED = {
    "AdventureControl_pb2.py": "093e5955aa14e889841d1fd02714541b20fe6287bf46974d537f8bc319595ae5",
    "BasicApi_pb2.py": "9e5af41600bf387fd45f9cf9034cab6d27ffc5a2fafef94f04c1a57185528389",
    "Basic_pb2.py": "7bca7c704e191f59c0be8a7dddcdb19a3f4cde8cf85ffc3ee3f59dbd432938e3",
    "CoreProtocol_pb2.py": "795bcdf3236d153014fd8afffc66e191624be1b293ff1c9497dbdd2134bc9952",
    "DwarfControl_pb2.py": "959a8d12487ce2a36776ae45f133a5ecfd0bf42b76069679a4426811843fef0c",
    "ItemdefInstrument_pb2.py": "f2d9f2be37e6160830774d0ef53a4dca997817eda431ab4b0523661c64649239",
    "RemoteFortressReader_pb2.py": "80b12779effe42adec10e71ef6b5ef8eb4eed0229308ec63b7a9b883e19116fc",
    "__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "ui_sidebar_mode_pb2.py": "7e8a5ced21f09c32c74d436438400b90719788c24ecd97da4c99ec0636da7529",
}

EXPECTED_CANONICAL_GENERATED = {
    "AdventureControl_pb2.py": "3b46d82e81cbf602be0d912ab166357951a20d18eac019b904d523149f221493",
    "BasicApi_pb2.py": "1a3723f7e51d79880510fd750a0a6f397afd696105a7e10861e472bffc5f0cd4",
    "Basic_pb2.py": "f602c887b06a7882429a803d2f4f814e81ee8b264be84993f5eb67444baf15b1",
    "CoreProtocol_pb2.py": "786a0a5729dc179c05022249a8d0c16c3e7d0e95f8d746ce84edf3b524d076e1",
    "DwarfControl_pb2.py": "be47c5f539e39ca179973238b6cafb7c3b819ee12865bc0faf9050786cc33537",
    "ItemdefInstrument_pb2.py": "57f5ec9ee19291e388abb0da98a5e4e9c705a80922c2181d802b06ff7f0bca93",
    "RemoteFortressReader_pb2.py": "f7cd44698e3673c30c123742dc9e19a9bbef46e67168780f4d4e0ffefe87f71f",
    "__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "ui_sidebar_mode_pb2.py": "800a52e802eb171bb5319f053c7d9d0c55f24e4749d177e39195b7a4cecf6cc1",
}

_DENIED_COMPONENTS = frozenset({".git", ".venv", "__pycache__"})
_GENERATED_PREFIX = PurePosixPath("fort_gym/bench/env/remote_proto/generated")
_ALLOWED_SOURCE_DIRECTORIES = frozenset({"fort_gym", "hook", "infra", "tests"})
_ALLOWED_SCRIPT_SOURCE_FILES = frozenset(
    {
        PurePosixPath("scripts/build_p1_live_calibration_bundle.py"),
        PurePosixPath("scripts/run_p1_live_calibration.py"),
    }
)
_ALLOWED_TEST_SOURCE_FILES = frozenset(
    {
        PurePosixPath("tests/conftest.py"),
        PurePosixPath("tests/test_cap_fake_end_to_end.py"),
        PurePosixPath("tests/test_process_supervisor.py"),
        PurePosixPath("tests/test_provider_environment_subprocess.py"),
        PurePosixPath("tests/test_residue_audit.py"),
        PurePosixPath("tests/test_runtime_controller.py"),
        PurePosixPath("tests/test_supervised_manager.py"),
    }
)
_ALLOWED_ROOT_SOURCE_FILES = frozenset(
    {"AGENTS.md", "LICENSE", "Makefile", "README.md", "pyproject.toml"}
)
_PUBLIC_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
_DENIED_SECRET_NAMES = frozenset(
    {
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "service-account.json",
    }
)
_SECRET_BYTE_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[oprsu]_[0-9A-Za-z]{20,}\b"),
    re.compile(rb"\bsk-(?:ant-|live-|or-v1-|proj-)[0-9A-Za-z_-]{16,}\b"),
    re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{16,}\b"),
)
_WHEEL_RECORD_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_.+-]+\.whl)$")
_REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$")
_AUTHORITY_EXPIRY = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
_EXPECTED_AUTHORITY = {
    "paid_models": "forbidden",
    "production_access": "forbidden",
    "production_mutation": "forbidden",
    "publication": "forbidden",
    "deploy": "forbidden",
    "push": "forbidden",
    "tag": "forbidden",
    "e1": "forbidden",
    "new_paid_infrastructure": {
        "status": "authorized",
        "daily_ceiling_usd": 210,
        "cumulative_ceiling_usd": 250,
        "prior_reserved_usd": 40,
        "authorized_vm_count": 26,
        "max_concurrent_vm_count": 1,
        "authorized_local_date": date(2026, 9, 5),
        "timezone": "America/New_York",
        "expires_at": _AUTHORITY_EXPIRY,
        "ephemeral_only": True,
    },
}


class PacketError(RuntimeError):
    """The requested packet cannot be built without weakening its contract."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json(value) + b"\n")
    path.chmod(0o600)


def _retained_packet_directories(parent: Path) -> list[Path]:
    """Return complete packet directories directly retained under ``parent``."""

    retained: list[Path] = []
    for candidate in sorted(parent.iterdir(), key=lambda path: path.name.encode()):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        markers = (candidate / "PACKET.json", candidate / "MANIFEST.sha256")
        if all(path.is_file() and not path.is_symlink() for path in markers):
            retained.append(candidate)
    return retained


def _enforce_packet_retention(output_dir: Path) -> None:
    retained = _retained_packet_directories(output_dir.parent)
    if len(retained) < MAX_RETAINED_PACKETS_PER_ROOT:
        return
    names = ", ".join(path.name for path in retained)
    raise PacketError(
        "packet retention limit reached "
        f"({MAX_RETAINED_PACKETS_PER_ROOT}) in {output_dir.parent}: {names}; "
        "archive an older packet before retaining another version"
    )


def _verify_deterministic_packet_pair(first: Path, second: Path) -> dict[str, Any]:
    """Prove two independently built packets have identical content manifests."""

    manifests: list[bytes] = []
    for packet in (first, second):
        if packet.is_symlink() or not packet.is_dir():
            raise PacketError("determinism candidate is not a regular directory")
        manifest = packet / "MANIFEST.sha256"
        if manifest.is_symlink() or not manifest.is_file():
            raise PacketError("determinism candidate lacks a regular manifest")
        manifests.append(manifest.read_bytes())
    if manifests[0] != manifests[1]:
        raise PacketError("independent packet rebuild was not byte-identical")
    return {
        "schema": DETERMINISM_SCHEMA,
        "verification": "independent-byte-identical-manifest",
        "manifest_sha256": _sha256_bytes(manifests[0]),
        "independent_builds": 2,
        "retained_packets": 1,
    }


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    text: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    if extra_env is not None:
        if any(
            not isinstance(name, str)
            or not isinstance(value, str)
            or "\0" in name
            or "\0" in value
            for name, value in extra_env.items()
        ):
            raise PacketError("subprocess environment override is invalid")
        environment.update(extra_env)
    return subprocess.run(
        list(argv),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=text,
        env=environment,
    )


def _sealed_tool_environment(executable: Path) -> dict[str, str]:
    """Use only dependency libraries copied beside a preserved local tool."""

    root = executable.parent.parent
    library_dirs = [
        candidate
        for candidate in (root / "lib", root / "abseil-lib", root / "deps-lib")
        if candidate.is_dir()
    ]
    if not library_dirs:
        return {}
    return {"DYLD_LIBRARY_PATH": ":".join(str(path) for path in library_dirs)}


def _safe_relative_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "\x00" in raw:
        raise PacketError(f"unsafe source path: {raw!r}")
    if any(part in _DENIED_COMPONENTS for part in path.parts):
        raise PacketError(f"denied source path: {raw!r}")
    if (
        (path.name == ".env" or path.name.startswith(".env."))
        and path.name not in _PUBLIC_ENV_TEMPLATES
    ) or path.suffix in {".pyc", ".pyo"}:
        raise PacketError(f"secret/cache source path: {raw!r}")
    if (
        path.name in _DENIED_SECRET_NAMES
        or path.suffix.lower() in {".key", ".p12", ".pem", ".pfx"}
        or path.name == ".DS_Store"
    ):
        raise PacketError(f"credential/private source path: {raw!r}")
    return path


def _is_live_source_path(path: PurePosixPath) -> bool:
    if len(path.parts) == 1:
        return path.name in _ALLOWED_ROOT_SOURCE_FILES
    if path.parts[0] == "scripts":
        return path in _ALLOWED_SCRIPT_SOURCE_FILES
    if path.parts[0] == "tests":
        return path in _ALLOWED_TEST_SOURCE_FILES
    if path.parts[0] not in _ALLOWED_SOURCE_DIRECTORIES:
        return False
    if path.parts[:2] == ("fort_gym", "artifacts"):
        return False
    return not (
        path.parts[0] == "infra" and (len(path.parts) < 2 or path.parts[1] != "m1b")
    )


def _reject_sensitive_bytes(path: Path, data: bytes) -> None:
    for pattern in _SECRET_BYTE_PATTERNS:
        if pattern.search(data) is not None:
            raise PacketError(f"source contains credential-shaped bytes: {path}")


def _git_source_paths(repo_root: Path) -> list[PurePosixPath]:
    result = _run(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=repo_root,
        text=False,
    )
    raw_paths = result.stdout.split(b"\0")
    validated = [_safe_relative_path(os.fsdecode(raw)) for raw in raw_paths if raw]
    paths = sorted(
        (path for path in validated if _is_live_source_path(path)),
        key=lambda item: item.as_posix().encode("utf-8"),
    )
    if len(paths) != len(set(paths)):
        raise PacketError("Git source enumeration contains duplicate paths")
    return paths


def _verify_repo_snapshot(
    repo_root: Path,
    paths: Sequence[PurePosixPath],
    records: Sequence[Mapping[str, Any]],
) -> None:
    """Fail if the dirty source tree changed while its packet was assembled."""

    if _git_source_paths(repo_root) != list(paths):
        raise PacketError("Git source file set changed during packet assembly")
    expected = {
        str(record["path"]): record
        for record in records
        if not (
            PurePosixPath(str(record["path"])) == _GENERATED_PREFIX
            or _GENERATED_PREFIX in PurePosixPath(str(record["path"])).parents
        )
    }
    if set(expected) != {path.as_posix() for path in paths}:
        raise PacketError("source manifest and Git source paths differ")
    for relative in paths:
        source = repo_root / relative
        if source.is_symlink() or not source.is_file():
            raise PacketError(f"source changed type during packet assembly: {relative}")
        record = expected[relative.as_posix()]
        mode = "0755" if source.stat().st_mode & stat.S_IXUSR else "0644"
        if (
            source.stat().st_size != record["size_bytes"]
            or _sha256_file(source) != record["sha256"]
            or mode != record["mode"]
        ):
            raise PacketError(f"source changed during packet assembly: {relative}")


def _copy_snapshot_file(source: Path, destination: Path) -> dict[str, Any]:
    if source.is_symlink() or not source.is_file():
        raise PacketError(f"source is not a regular non-symlink file: {source}")
    data = source.read_bytes()
    _reject_sensitive_bytes(source, data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    executable = bool(source.stat().st_mode & stat.S_IXUSR)
    destination.chmod(0o755 if executable else 0o644)
    return {
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
        "mode": "0755" if executable else "0644",
    }


def _generate_proto_bindings(
    *,
    dfhack_source_root: Path,
    protoc: Path,
    scratch_root: Path,
) -> tuple[Path, dict[str, Any]]:
    source_head = str(
        _run(
            ["git", "--no-optional-locks", "rev-parse", "HEAD"],
            cwd=dfhack_source_root,
        ).stdout
    ).strip()
    if source_head != DFHACK_SOURCE_HEAD:
        raise PacketError(
            f"DFHack source HEAD differs: expected {DFHACK_SOURCE_HEAD}, got {source_head}"
        )
    flat = scratch_root / "proto-flat"
    generated = scratch_root / "proto-generated"
    flat.mkdir()
    generated.mkdir()
    source_records: list[dict[str, Any]] = []
    for flat_name, (relative, expected_sha256) in sorted(PROTO_SOURCES.items()):
        source = dfhack_source_root / relative
        observed = _sha256_file(source)
        if observed != expected_sha256:
            raise PacketError(f"pinned proto source drifted: {relative}")
        shutil.copyfile(source, flat / flat_name)
        source_records.append(
            {
                "flat_name": flat_name,
                "source_path": relative,
                "sha256": observed,
                "size_bytes": source.stat().st_size,
            }
        )
    (generated / "__init__.py").write_bytes(b"")
    tool_env = _sealed_tool_environment(protoc)
    version = str(
        _run(
            [str(protoc), "--version"],
            cwd=scratch_root,
            extra_env=tool_env,
        ).stdout
    ).strip()
    _run(
        [
            str(protoc),
            f"--proto_path={flat}",
            f"--python_out={generated}",
            *(str(flat / name) for name in sorted(PROTO_SOURCES)),
        ],
        cwd=scratch_root,
        extra_env=tool_env,
    )
    generated_records: list[dict[str, Any]] = []
    observed_names = {path.name for path in generated.iterdir() if path.is_file()}
    if observed_names != set(EXPECTED_WIRE_GENERATED):
        raise PacketError("generated protobuf file set differs from the pinned set")
    for name, expected_sha256 in sorted(EXPECTED_WIRE_GENERATED.items()):
        path = generated / name
        observed = _sha256_file(path)
        if observed != expected_sha256:
            raise PacketError(f"generated protobuf drifted: {name}")
        generated_records.append(
            {"path": name, "sha256": observed, "size_bytes": path.stat().st_size}
        )
    digest = hashlib.sha256()
    digest.update(b"fort-gym.remote-proto-wire-reference/v1\0")
    digest.update(WIRE_PROTO_VERSION.encode("ascii"))
    digest.update(b"\0")
    for record in generated_records:
        path = generated / str(record["path"])
        digest.update(str(record["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    wire_reference_sha256 = digest.hexdigest()
    protoc_sha256 = _sha256_file(protoc)
    if wire_reference_sha256 != EXPECTED_WIRE_REFERENCE_SHA256:
        raise PacketError("wire-reference protobuf identity differs")
    if protoc_sha256 != EXPECTED_PROTOC_SHA256:
        raise PacketError("pinned protoc executable digest differs")
    return generated, {
        "schema": WIRE_PROTO_SCHEMA,
        "protocol_version": WIRE_PROTO_VERSION,
        "dfhack_source_head": source_head,
        "protoc_version": version,
        "sources": source_records,
        "generated": generated_records,
        "wire_reference_sha256": wire_reference_sha256,
        "protoc_sha256": protoc_sha256,
    }


def _verify_canonical_proto_bindings(
    canonical_root: Path,
) -> tuple[Path, dict[str, Any]]:
    canonical_root = canonical_root.resolve(strict=True)
    observed_names = {path.name for path in canonical_root.iterdir() if path.is_file()}
    if observed_names != set(EXPECTED_CANONICAL_GENERATED):
        raise PacketError("canonical generated protobuf file set differs")
    generated_records: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    digest.update(b"fort-gym.remote-proto-runtime/v1\0")
    digest.update(CANONICAL_PROTO_VERSION.encode("ascii"))
    digest.update(b"\0")
    for name, expected_sha256 in sorted(EXPECTED_CANONICAL_GENERATED.items()):
        path = canonical_root / name
        if path.is_symlink() or not path.is_file():
            raise PacketError(f"canonical protobuf is not a regular file: {name}")
        observed = _sha256_file(path)
        if observed != expected_sha256:
            raise PacketError(f"canonical generated protobuf drifted: {name}")
        data = path.read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        generated_records.append(
            {"path": name, "sha256": observed, "size_bytes": len(data)}
        )
    runtime_digest = digest.hexdigest()
    if runtime_digest != EXPECTED_RUNTIME_BINDING_SHA256:
        raise PacketError("canonical runtime protobuf digest differs")
    return canonical_root, {
        "schema": PROTO_SCHEMA,
        "protocol_version": CANONICAL_PROTO_VERSION,
        "provenance": "preserved-g7-v5-byte-exact",
        "wire_target": WIRE_PROTO_VERSION,
        "generated": generated_records,
        "runtime_binding_sha256": runtime_digest,
    }


def _verify_wheelhouse(
    *,
    wheelhouse_root: Path,
    requirements_path: Path,
    digest_manifest_path: Path,
) -> dict[str, Any]:
    wheelhouse_root = wheelhouse_root.resolve(strict=True)
    if not wheelhouse_root.is_dir():
        raise PacketError("wheelhouse is not a directory")
    expected: dict[str, str] = {}
    for line in digest_manifest_path.read_text(encoding="utf-8").splitlines():
        match = _WHEEL_RECORD_RE.fullmatch(line)
        if match is None or match.group(2) in expected:
            raise PacketError("wheelhouse digest manifest is malformed or duplicated")
        expected[match.group(2)] = match.group(1)
    requirements: dict[str, str] = {}
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQUIREMENT_RE.fullmatch(line)
        if match is None:
            raise PacketError("live requirement is not one exact name==version pin")
        name = re.sub(r"[-_.]+", "_", match.group(1)).lower()
        if name in requirements:
            raise PacketError("live requirements contain a duplicate package")
        requirements[name] = match.group(2).lower()
    if requirements.get("protobuf") != "6.31.1":
        raise PacketError("live protobuf runtime is not pinned to 6.31.1")
    if {"openai", "anthropic"} & set(requirements):
        raise PacketError("provider SDKs are forbidden from the live wheelhouse")
    wheel_entries = list(wheelhouse_root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in wheel_entries):
        raise PacketError(
            "wheelhouse may contain only pinned regular non-symlink wheel files"
        )
    observed_names = {path.name for path in wheel_entries}
    if observed_names != set(expected):
        raise PacketError("wheelhouse file set differs from its pinned manifest")
    records: list[dict[str, Any]] = []
    matched_requirements: set[str] = set()
    for filename, expected_sha256 in sorted(expected.items()):
        path = wheelhouse_root / filename
        if path.is_symlink() or not path.is_file():
            raise PacketError(f"wheel is not a regular file: {filename}")
        observed = _sha256_file(path)
        if observed != expected_sha256:
            raise PacketError(f"wheel digest differs: {filename}")
        normalized = filename.lower().split("-", 1)[0]
        matches = [
            name
            for name, version in requirements.items()
            if normalized == name and filename.lower().startswith(f"{name}-{version}-")
        ]
        if len(matches) != 1:
            raise PacketError(f"wheel does not match one exact requirement: {filename}")
        matched_requirements.add(matches[0])
        records.append(
            {
                "filename": filename,
                "sha256": observed,
                "size_bytes": path.stat().st_size,
            }
        )
    if matched_requirements != set(requirements):
        raise PacketError("live requirements and wheelhouse are not one-to-one")
    return {
        "schema": WHEELHOUSE_SCHEMA,
        "python": "3.11",
        "platform": "linux/x86_64",
        "requirements_sha256": _sha256_file(requirements_path),
        "digest_manifest_sha256": _sha256_file(digest_manifest_path),
        "file_count": len(records),
        "total_bytes": sum(int(record["size_bytes"]) for record in records),
        "files": records,
    }


def _read_ar_members(path: Path) -> dict[str, bytes]:
    """Read the small, traditional ar subset required by Debian packages."""

    payload = path.read_bytes()
    if not payload.startswith(b"!<arch>\n"):
        raise PacketError(f"Debian package is not an ar archive: {path.name}")
    cursor = 8
    members: dict[str, bytes] = {}
    while cursor < len(payload):
        if cursor + 60 > len(payload):
            raise PacketError(f"Debian package has a truncated ar header: {path.name}")
        header = payload[cursor : cursor + 60]
        cursor += 60
        if header[58:60] != b"`\n":
            raise PacketError(f"Debian package has an invalid ar header: {path.name}")
        raw_name = header[:16].decode("ascii", errors="strict").rstrip()
        if raw_name.startswith("#1/") or raw_name in {"/", "//"}:
            raise PacketError(
                f"Debian package uses an unsupported ar name: {path.name}"
            )
        name = raw_name.removesuffix("/")
        if not name or "/" in name or name in members:
            raise PacketError(
                f"Debian package has an unsafe/duplicate member: {path.name}"
            )
        try:
            size = int(header[48:58].decode("ascii").strip())
        except ValueError as exc:
            raise PacketError(
                f"Debian package has an invalid member size: {path.name}"
            ) from exc
        end = cursor + size
        if size < 0 or end > len(payload):
            raise PacketError(f"Debian package member exceeds the archive: {path.name}")
        members[name] = payload[cursor:end]
        cursor = end
        if size % 2:
            if cursor >= len(payload) or payload[cursor : cursor + 1] != b"\n":
                raise PacketError(f"Debian package has invalid ar padding: {path.name}")
            cursor += 1
    if cursor != len(payload) or members.get("debian-binary") != b"2.0\n":
        raise PacketError(f"Debian package format marker differs: {path.name}")
    return members


def _decompress_deb_tar(name: str, payload: bytes, *, package: str) -> bytes:
    if name.endswith(".xz"):
        try:
            return lzma.decompress(payload, format=lzma.FORMAT_XZ)
        except lzma.LZMAError as exc:
            raise PacketError(
                f"Debian package xz stream is invalid: {package}"
            ) from exc
    if name.endswith(".gz"):
        try:
            return gzip.decompress(payload)
        except gzip.BadGzipFile as exc:
            raise PacketError(
                f"Debian package gzip stream is invalid: {package}"
            ) from exc
    if name.endswith(".tar"):
        return payload
    raise PacketError(f"Debian package compression is unsupported: {package}")


def _control_fields(payload: bytes, *, source: str) -> dict[str, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PacketError(f"Debian control data is not UTF-8: {source}") from exc
    result: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith((" ", "\t")):
            if current is None:
                raise PacketError(f"Debian control continuation is orphaned: {source}")
            result[current] += "\n" + line
            continue
        if ": " not in line:
            if line:
                raise PacketError(f"Debian control field is malformed: {source}")
            continue
        name, value = line.split(": ", 1)
        if not name or name in result:
            raise PacketError(f"Debian control field is duplicated: {source}")
        result[name] = value
        current = name
    return result


def _deb_control_and_binaries(
    path: Path,
    *,
    expected_binary_paths: set[str],
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    members = _read_ar_members(path)
    if set(members) != {"debian-binary", "control.tar.xz", "data.tar.xz"}:
        raise PacketError(f"Debian package member set differs: {path.name}")
    control_tar = _decompress_deb_tar(
        "control.tar.xz", members["control.tar.xz"], package=path.name
    )
    with tarfile.open(fileobj=io.BytesIO(control_tar), mode="r:") as archive:
        candidates = [
            member
            for member in archive.getmembers()
            if member.name.removeprefix("./") == "control"
        ]
        if len(candidates) != 1 or not candidates[0].isfile():
            raise PacketError(f"Debian package control member differs: {path.name}")
        handle = archive.extractfile(candidates[0])
        if handle is None:
            raise PacketError(f"Debian package control is unreadable: {path.name}")
        control = _control_fields(handle.read(), source=path.name)
    data_tar = _decompress_deb_tar(
        "data.tar.xz", members["data.tar.xz"], package=path.name
    )
    binaries: dict[str, dict[str, Any]] = {}
    with tarfile.open(fileobj=io.BytesIO(data_tar), mode="r:") as archive:
        for member in archive.getmembers():
            raw = member.name.removeprefix("./")
            absolute = f"/{raw}"
            if absolute not in expected_binary_paths:
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise PacketError(
                    f"pinned Docker binary is not a regular file: {absolute}"
                )
            handle = archive.extractfile(member)
            if handle is None or absolute in binaries:
                raise PacketError(
                    f"pinned Docker binary is unreadable/duplicate: {absolute}"
                )
            data = handle.read()
            if (
                len(data) < 20
                or data[:4] != b"\x7fELF"
                or data[4] != 2
                or data[5] != 1
                or int.from_bytes(data[18:20], "little") != 62
            ):
                raise PacketError(
                    f"pinned Docker binary architecture differs: {absolute}"
                )
            binaries[absolute] = {
                "architecture": "amd64",
                "mode": f"{stat.S_IMODE(member.mode):04o}",
                "size_bytes": len(data),
                "sha256": _sha256_bytes(data),
            }
    return control, binaries


def _verify_docker_runtime(*, docker_runtime_root: Path, gpgv: Path) -> dict[str, Any]:
    """Verify Docker-official signed metadata, packages, and installed bytes."""

    root = docker_runtime_root.resolve(strict=True)
    if not root.is_dir():
        raise PacketError("Docker runtime input root is not a directory")
    entries = list(root.iterdir())
    if {item.name for item in entries} != set(DOCKER_RUNTIME_INPUTS) or any(
        not item.is_file()
        or item.is_symlink()
        or stat.S_IMODE(item.stat().st_mode) & 0o022
        for item in entries
    ):
        raise PacketError("Docker runtime input filename/type/mode set differs")
    for filename, (expected_digest, expected_size) in DOCKER_RUNTIME_INPUTS.items():
        path = root / filename
        if (
            path.stat().st_size != expected_size
            or _sha256_file(path) != expected_digest
        ):
            raise PacketError(f"Docker runtime input digest/size differs: {filename}")

    signature = _run(
        [
            str(gpgv.resolve(strict=True)),
            "--status-fd",
            "1",
            "--keyring",
            str(root / "docker-keyring.gpg"),
            str(root / "InRelease"),
        ],
        cwd=root,
    )
    status = str(signature.stdout)
    valid_signature = re.findall(
        r"^\[GNUPG:\] VALIDSIG ([0-9A-F]{40}) .* ([0-9A-F]{40})$",
        status,
        flags=re.MULTILINE,
    )
    if valid_signature != [
        (DOCKER_RELEASE_SIGNING_FINGERPRINT, DOCKER_RELEASE_KEY_FINGERPRINT)
    ]:
        raise PacketError("Docker repository signature fingerprint differs")

    inrelease = (root / "InRelease").read_text(encoding="utf-8")
    packages_digest = DOCKER_RUNTIME_INPUTS["Packages.gz"][0]
    packages_size = DOCKER_RUNTIME_INPUTS["Packages.gz"][1]
    packages_release_lines = re.findall(
        r"^ ([0-9a-f]{64}) +([0-9]+) +stable/binary-amd64/Packages\.gz$",
        inrelease,
        flags=re.MULTILINE,
    )
    if packages_release_lines != [(packages_digest, str(packages_size))]:
        raise PacketError("signed Docker release does not bind Packages.gz")
    try:
        packages_text = gzip.decompress((root / "Packages.gz").read_bytes()).decode(
            "utf-8"
        )
    except (gzip.BadGzipFile, UnicodeDecodeError) as exc:
        raise PacketError("Docker Packages.gz is invalid") from exc
    package_index: dict[str, dict[str, str]] = {}
    for paragraph in packages_text.strip().split("\n\n"):
        fields = _control_fields(paragraph.encode("utf-8"), source="Packages.gz")
        package = fields.get("Package")
        version = fields.get("Version")
        if (
            package in DOCKER_RUNTIME_PACKAGES
            and version == DOCKER_RUNTIME_PACKAGES[package]["version"]
        ):
            if package in package_index:
                raise PacketError(
                    f"Docker repository package entry is duplicated: {package}"
                )
            package_index[package] = fields
    if set(package_index) != set(DOCKER_RUNTIME_PACKAGES):
        raise PacketError("signed Docker package set is incomplete")

    package_records: list[dict[str, Any]] = []
    binary_records: dict[str, dict[str, Any]] = {}
    for package in sorted(DOCKER_RUNTIME_PACKAGES):
        expectation = DOCKER_RUNTIME_PACKAGES[package]
        filename = str(expectation["filename"])
        fields = package_index[package]
        expected_digest, expected_size = DOCKER_RUNTIME_INPUTS[filename]
        expected_repository_path = f"dists/bookworm/pool/stable/amd64/{filename}"
        if (
            fields.get("Architecture") != "amd64"
            or fields.get("Filename") != expected_repository_path
            or fields.get("Size") != str(expected_size)
            or fields.get("SHA256") != expected_digest
        ):
            raise PacketError(f"signed Docker package metadata differs: {package}")
        expected_paths = {
            path
            for path, (owner, _digest, _size) in DOCKER_RUNTIME_BINARIES.items()
            if owner == package
        }
        control, binaries = _deb_control_and_binaries(
            root / filename,
            expected_binary_paths=expected_paths,
        )
        if (
            control.get("Package") != package
            or control.get("Version") != expectation["version"]
            or control.get("Architecture") != "amd64"
            or set(binaries) != expected_paths
        ):
            raise PacketError(
                f"Docker Debian package identity/content differs: {package}"
            )
        for binary_path, record in binaries.items():
            owner, expected_binary_digest, expected_binary_size = (
                DOCKER_RUNTIME_BINARIES[binary_path]
            )
            if (
                owner != package
                or record["mode"] != "0755"
                or record["sha256"] != expected_binary_digest
                or record["size_bytes"] != expected_binary_size
            ):
                raise PacketError(f"Docker package binary differs: {binary_path}")
            binary_records[binary_path] = {
                "path": binary_path,
                "package": package,
                **record,
            }
        package_records.append(
            {
                "package": package,
                "version": expectation["version"],
                "architecture": "amd64",
                "filename": filename,
                "repository_path": expected_repository_path,
                "size_bytes": expected_size,
                "sha256": expected_digest,
            }
        )
    if set(binary_records) != set(DOCKER_RUNTIME_BINARIES):
        raise PacketError("Docker critical installed binary set differs")

    archive_members = [
        {
            "path": filename,
            "size_bytes": size,
            "sha256": digest,
            "mode": "0644",
        }
        for filename, (digest, size) in sorted(DOCKER_RUNTIME_INPUTS.items())
    ]
    return {
        "schema": DOCKER_RUNTIME_SCHEMA,
        "platform": "linux/amd64",
        "distribution": "debian/12",
        "docker_server_version": "29.1.3",
        "containerd_version": "2.2.1",
        "containerd_snapshotter_required": True,
        "network_install_required": False,
        "package_install_order": ["containerd.io", "docker-ce-cli", "docker-ce"],
        "signed_repository": {
            "base_url": DOCKER_REPOSITORY_BASE_URL,
            "suite": "bookworm",
            "component": "stable",
            "architecture": "amd64",
            "release_key_fingerprint": DOCKER_RELEASE_KEY_FINGERPRINT,
            "release_signing_fingerprint": DOCKER_RELEASE_SIGNING_FINGERPRINT,
            "inrelease_sha256": DOCKER_RUNTIME_INPUTS["InRelease"][0],
            "packages_gz_sha256": packages_digest,
            "signature_verified": True,
        },
        "packages": package_records,
        "binaries": [binary_records[path] for path in sorted(binary_records)],
        "archive_members": archive_members,
    }


def _manifest_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix().encode("utf-8"),
    ):
        if path.is_symlink():
            raise PacketError(f"snapshot contains a symlink: {path}")
        mode = "0755" if path.stat().st_mode & stat.S_IXUSR else "0644"
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
                "mode": mode,
            }
        )
    return records


def _deterministic_tar(root: Path, output: Path) -> None:
    with tarfile.open(output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for record in _manifest_records(root):
            path = root / str(record["path"])
            info = tarfile.TarInfo(str(record["path"]))
            info.size = int(record["size_bytes"])
            info.mode = int(str(record["mode"]), 8)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            info.pax_headers = {}
            with path.open("rb") as handle:
                archive.addfile(info, handle)
    output.chmod(0o600)


def _seed_manifest(seed_root: Path) -> tuple[bytes, dict[str, Any]]:
    files = sorted(
        (path for path in seed_root.rglob("*") if path.is_file()),
        key=lambda path: ("./" + path.relative_to(seed_root).as_posix()).encode(
            "utf-8"
        ),
    )
    if not files or any(path.is_symlink() for path in files):
        raise PacketError("seed tree must contain regular non-symlink files")
    manifest = b"".join(
        hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        + b"  ./"
        + path.relative_to(seed_root).as_posix().encode("utf-8")
        + b"\0"
        for path in files
    )
    tree_sha256 = _sha256_bytes(manifest)
    world = seed_root / "world.sav"
    if tree_sha256 != EXPECTED_SEED_TREE_SHA256 or not world.is_file():
        raise PacketError("preserved seed tree identity differs")
    world_sha256 = _sha256_file(world)
    if world_sha256 != EXPECTED_SEED_WORLD_SHA256:
        raise PacketError("preserved seed world identity differs")
    return manifest, {
        "tree_sha256": tree_sha256,
        "world_sha256": world_sha256,
        "file_count": len(files),
        "file_bytes": sum(path.stat().st_size for path in files),
    }


def _read_zstd_tar_members(
    archive_path: Path,
    *,
    zstd: Path,
    selected: Iterable[str],
    maximum_member_bytes: int = 64 * 1024 * 1024,
) -> dict[str, bytes]:
    wanted = set(selected)
    found: dict[str, bytes] = {}
    process = subprocess.Popen(
        [str(zstd), "-dc", "--no-progress", str(archive_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            **_sealed_tool_environment(zstd),
        },
    )
    if process.stdout is None:
        process.kill()
        process.wait()
        raise PacketError("OCI decompressor stdout pipe is unavailable")
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as outer:
            for member in outer:
                name = member.name.removeprefix("./")
                if name not in wanted:
                    continue
                if name in found or not member.isfile():
                    raise PacketError(f"invalid duplicate OCI member: {name}")
                if member.size < 0 or member.size > maximum_member_bytes:
                    raise PacketError(f"OCI member exceeds bound: {name}")
                handle = outer.extractfile(member)
                if handle is None:
                    raise PacketError(f"OCI member is unreadable: {name}")
                found[name] = handle.read()
        process.stdout.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        returncode = process.wait()
        if returncode != 0:
            raise PacketError(f"OCI decompression failed: {stderr[:500]!r}")
        if set(found) != wanted:
            raise PacketError(
                f"OCI archive lacks members: {sorted(wanted - set(found))}"
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return found


def _sha256_uncompressed_zstd(path: Path, *, zstd: Path) -> str:
    process = subprocess.Popen(
        [str(zstd), "-dc", "--no-progress", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            **_sealed_tool_environment(zstd),
        },
    )
    if process.stdout is None:
        process.kill()
        process.wait()
        raise PacketError("OCI decompressor stdout pipe is unavailable")
    digest = hashlib.sha256()
    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(chunk)
    process.stdout.close()
    stderr = process.stderr.read() if process.stderr is not None else b""
    if process.wait() != 0:
        raise PacketError(f"OCI decompression failed: {stderr[:500]!r}")
    return digest.hexdigest()


def _hook_files_from_layer(layer_bytes: bytes) -> dict[str, bytes]:
    if _sha256_bytes(layer_bytes) != HOOK_LAYER_SHA256:
        raise PacketError("hook layer compressed digest differs")
    result: dict[str, bytes] = {}
    with (
        gzip.GzipFile(fileobj=io.BytesIO(layer_bytes), mode="rb") as uncompressed,
        tarfile.open(fileobj=uncompressed, mode="r|") as layer,
    ):
        for member in layer:
            name = member.name.removeprefix("./")
            prefix = "opt/fort-gym-m1a/hook/"
            if not name.startswith(prefix) or not member.isfile():
                continue
            relative = name.removeprefix(prefix)
            if "/" in relative or not relative:
                raise PacketError("hook layer has an unexpected nested path")
            handle = layer.extractfile(member)
            if handle is None or relative in result:
                raise PacketError("hook layer has an unreadable/duplicate file")
            result[relative] = handle.read()
    return result


def _verify_oci_archive(
    archive_path: Path,
    *,
    zstd: Path,
    repo_hook_root: Path,
) -> dict[str, Any]:
    compressed = _sha256_file(archive_path)
    if compressed != EXPECTED_ARCHIVE_SHA256:
        raise PacketError("compressed OCI archive SHA-256 differs")
    uncompressed = _sha256_uncompressed_zstd(archive_path, zstd=zstd)
    if uncompressed != EXPECTED_ARCHIVE_TAR_SHA256:
        raise PacketError("uncompressed OCI archive SHA-256 differs")
    manifest_member = f"blobs/sha256/{EXPECTED_IMAGE_MANIFEST_SHA256}"
    config_member = f"blobs/sha256/{EXPECTED_IMAGE_CONFIG_SHA256}"
    hook_member = f"blobs/sha256/{HOOK_LAYER_SHA256}"
    members = _read_zstd_tar_members(
        archive_path,
        zstd=zstd,
        selected={"index.json", manifest_member, config_member, hook_member},
    )
    index = json.loads(members["index.json"])
    manifest_bytes = members[manifest_member]
    config_bytes = members[config_member]
    manifest = json.loads(manifest_bytes)
    config = json.loads(config_bytes)
    descriptors = index.get("manifests")
    if (
        index.get("schemaVersion") != 2
        or not isinstance(descriptors, list)
        or len(descriptors) != 1
        or descriptors[0].get("mediaType")
        != "application/vnd.oci.image.manifest.v1+json"
        or descriptors[0].get("digest") != f"sha256:{EXPECTED_IMAGE_MANIFEST_SHA256}"
        or descriptors[0].get("size") != len(manifest_bytes)
        or _sha256_bytes(manifest_bytes) != EXPECTED_IMAGE_MANIFEST_SHA256
    ):
        raise PacketError("OCI index/manifest binding differs")
    config_descriptor = manifest.get("config")
    layers = manifest.get("layers")
    if (
        manifest.get("schemaVersion") != 2
        or not isinstance(config_descriptor, Mapping)
        or config_descriptor.get("digest") != f"sha256:{EXPECTED_IMAGE_CONFIG_SHA256}"
        or config_descriptor.get("size") != len(config_bytes)
        or _sha256_bytes(config_bytes) != EXPECTED_IMAGE_CONFIG_SHA256
        or not isinstance(layers, list)
        or sum(
            1
            for item in layers
            if isinstance(item, Mapping)
            and item.get("digest") == f"sha256:{HOOK_LAYER_SHA256}"
        )
        != 1
    ):
        raise PacketError("OCI manifest/config/layer binding differs")
    if config.get("architecture") != "amd64" or config.get("os") != "linux":
        raise PacketError("OCI image is not linux/amd64")
    image_hooks = _hook_files_from_layer(members[hook_member])
    repo_hooks = {
        path.name: path.read_bytes()
        for path in repo_hook_root.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    if image_hooks != repo_hooks:
        raise PacketError("host source hooks differ from the pinned image hook layer")
    return {
        "compressed_sha256": compressed,
        "uncompressed_tar_sha256": uncompressed,
        "size_bytes": archive_path.stat().st_size,
        "manifest_sha256": EXPECTED_IMAGE_MANIFEST_SHA256,
        "manifest_size_bytes": len(manifest_bytes),
        "manifest_media_type": "application/vnd.oci.image.manifest.v1+json",
        "config_sha256": EXPECTED_IMAGE_CONFIG_SHA256,
        "hook_layer_sha256": HOOK_LAYER_SHA256,
        "hook_count": len(image_hooks),
        "platform": "linux/amd64",
    }


def build_packet(
    *,
    repo_root: Path,
    output_dir: Path,
    runtime_archive: Path,
    seed_root: Path,
    dfhack_source_root: Path,
    canonical_proto_root: Path,
    wheelhouse_root: Path,
    docker_runtime_root: Path,
    protoc: Path,
    zstd: Path,
    gpgv: Path,
) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    requested_output = output_dir.absolute()
    if requested_output.exists():
        raise PacketError("output directory already exists")
    if requested_output.name in {"", ".", ".."}:
        raise PacketError("output directory name is invalid")
    output_dir = requested_output.parent.resolve(strict=True) / requested_output.name
    try:
        output_dir.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise PacketError("output directory must remain outside the source repository")
    _enforce_packet_retention(output_dir)
    acceptance_path = repo_root / "infra/m1b/acceptance.yaml"
    acceptance = yaml.safe_load(acceptance_path.read_text(encoding="utf-8"))
    if not isinstance(acceptance, Mapping):
        raise PacketError("acceptance contract must be a mapping")
    if acceptance.get("authorization") != _EXPECTED_AUTHORITY:
        raise PacketError("acceptance authority differs from the bounded live pass")
    if datetime.now(UTC) >= _AUTHORITY_EXPIRY:
        raise PacketError("operator infrastructure authority has expired")
    if _sha256_file(zstd.resolve(strict=True)) != EXPECTED_ZSTD_SHA256:
        raise PacketError("pinned zstd executable digest differs")
    runtime_identity = acceptance.get("runtime_identity", {})
    expected_acceptance = {
        "compressed_oci_archive_sha256": EXPECTED_ARCHIVE_SHA256,
        "uncompressed_oci_archive_sha256": EXPECTED_ARCHIVE_TAR_SHA256,
        "oci_manifest_digest": f"sha256:{EXPECTED_IMAGE_MANIFEST_SHA256}",
        "oci_config_digest": f"sha256:{EXPECTED_IMAGE_CONFIG_SHA256}",
        "seed_tree_sha256": EXPECTED_SEED_TREE_SHA256,
        "seed_world_sha256": EXPECTED_SEED_WORLD_SHA256,
    }
    if any(
        runtime_identity.get(key) != value for key, value in expected_acceptance.items()
    ):
        raise PacketError("acceptance runtime identity differs from packet constants")
    head = str(_run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout).strip()
    if head != BASE_HEAD:
        raise PacketError(f"repository base HEAD differs: {head}")
    branch = str(
        _run(["git", "branch", "--show-current"], cwd=repo_root).stdout
    ).strip()
    scratch_parent = output_dir.parent.resolve(strict=True)
    scratch = Path(tempfile.mkdtemp(prefix=".fortgym-m1b-packet-", dir=scratch_parent))
    try:
        source_stage = scratch / "source"
        source_stage.mkdir()
        source_paths = _git_source_paths(repo_root)
        for relative in source_paths:
            if relative == _GENERATED_PREFIX or _GENERATED_PREFIX in relative.parents:
                raise PacketError(
                    "generated protobuf path unexpectedly entered Git snapshot"
                )
            _copy_snapshot_file(repo_root / relative, source_stage / relative)
        wire_generated, wire_proto_record = _generate_proto_bindings(
            dfhack_source_root=dfhack_source_root.resolve(strict=True),
            protoc=protoc.resolve(strict=True),
            scratch_root=scratch,
        )
        del wire_generated
        generated, proto_record = _verify_canonical_proto_bindings(canonical_proto_root)
        generated_target = source_stage / _GENERATED_PREFIX
        for path in generated.iterdir():
            if path.is_file():
                _copy_snapshot_file(path, generated_target / path.name)
        source_records = _manifest_records(source_stage)
        _verify_repo_snapshot(repo_root, source_paths, source_records)
        source_manifest = {
            "schema": SOURCE_SCHEMA,
            "base_head": head,
            "branch": branch,
            "file_count": len(source_records),
            "file_bytes": sum(int(item["size_bytes"]) for item in source_records),
            "tree_sha256": _sha256_bytes(_canonical_json(source_records)),
            "files": source_records,
            "runtime_proto": {
                "canonical_runtime": proto_record,
                "wire_reference": wire_proto_record,
            },
        }
        packet_stage = scratch / "packet"
        packet_stage.mkdir()
        source_tar = packet_stage / "fortgym-m1b-source.tar"
        _deterministic_tar(source_stage, source_tar)
        _write_json(packet_stage / "source-manifest.json", source_manifest)
        requirements_path = repo_root / "infra/m1b/live-requirements.lock"
        wheel_digest_path = repo_root / "infra/m1b/live-wheelhouse.sha256"
        wheelhouse_record = _verify_wheelhouse(
            wheelhouse_root=wheelhouse_root,
            requirements_path=requirements_path,
            digest_manifest_path=wheel_digest_path,
        )
        wheel_stage = scratch / "wheelhouse"
        wheel_stage.mkdir()
        for record in wheelhouse_record["files"]:
            filename = str(record["filename"])
            source = wheelhouse_root.resolve(strict=True) / filename
            destination = wheel_stage / filename
            shutil.copyfile(source, destination)
            destination.chmod(0o644)
        wheelhouse_tar = packet_stage / "fortgym-m1b-wheelhouse.tar"
        _deterministic_tar(wheel_stage, wheelhouse_tar)
        shutil.copyfile(requirements_path, packet_stage / requirements_path.name)
        shutil.copyfile(wheel_digest_path, packet_stage / wheel_digest_path.name)
        for path in (
            packet_stage / requirements_path.name,
            packet_stage / wheel_digest_path.name,
        ):
            path.chmod(0o600)
        docker_runtime_record = _verify_docker_runtime(
            docker_runtime_root=docker_runtime_root,
            gpgv=gpgv,
        )
        docker_stage = scratch / "docker-runtime"
        docker_stage.mkdir()
        for record in docker_runtime_record["archive_members"]:
            filename = str(record["path"])
            source = docker_runtime_root.resolve(strict=True) / filename
            destination = docker_stage / filename
            shutil.copyfile(source, destination)
            destination.chmod(0o644)
        docker_runtime_tar = packet_stage / "fortgym-m1b-docker-runtime.tar"
        _deterministic_tar(docker_stage, docker_runtime_tar)
        docker_runtime_manifest = packet_stage / "docker-runtime-manifest.json"
        _write_json(docker_runtime_manifest, docker_runtime_record)
        seed_manifest, seed_record = _seed_manifest(seed_root.resolve(strict=True))
        (packet_stage / "seed_tree.sha256z").write_bytes(seed_manifest)
        (packet_stage / "seed_tree.sha256z").chmod(0o600)
        shutil.copyfile(
            runtime_archive.resolve(strict=True),
            packet_stage / "fortgym-df-m1a.tar.zst",
        )
        (packet_stage / "fortgym-df-m1a.tar.zst").chmod(0o600)
        archive_record = _verify_oci_archive(
            packet_stage / "fortgym-df-m1a.tar.zst",
            zstd=zstd.resolve(strict=True),
            repo_hook_root=repo_root / "hook",
        )
        packet_manifest = {
            "schema": SCHEMA,
            "authority": {
                "provider_calls": 0,
                "provider_cost_usd": 0,
                "paid_models": "forbidden",
                "production_access": "forbidden",
                "production_mutation": "forbidden",
                "publish_deploy_push_tag_e1": "forbidden",
                "infrastructure_daily_ceiling_usd": 210,
                "infrastructure_authorized_local_date": "2026-09-05",
                "infrastructure_authority_expires_at": "2026-09-06T12:00:00Z",
                "ephemeral_only": True,
            },
            "acceptance_sha256": _sha256_file(acceptance_path),
            "source": {
                "archive": source_tar.name,
                "archive_sha256": _sha256_file(source_tar),
                "manifest": "source-manifest.json",
                "tree_sha256": source_manifest["tree_sha256"],
                "extract_root": "/opt/fort-gym-m1a",
            },
            "runtime_archive": archive_record,
            "docker_runtime": {
                **docker_runtime_record,
                "archive": docker_runtime_tar.name,
                "archive_sha256": _sha256_file(docker_runtime_tar),
                "manifest": docker_runtime_manifest.name,
                "manifest_sha256": _sha256_file(docker_runtime_manifest),
            },
            "wheelhouse": {
                **wheelhouse_record,
                "archive": wheelhouse_tar.name,
                "archive_sha256": _sha256_file(wheelhouse_tar),
                "requirements": requirements_path.name,
                "digest_manifest": wheel_digest_path.name,
                "network_install_required": False,
                "provider_sdks_present": False,
            },
            "seed": seed_record,
            "runtime_proto": {
                "protocol_version": proto_record["protocol_version"],
                "wire_target": proto_record["wire_target"],
                "dfhack_source_head": wire_proto_record["dfhack_source_head"],
                "runtime_binding_sha256": proto_record["runtime_binding_sha256"],
                "wire_reference_sha256": wire_proto_record["wire_reference_sha256"],
                "wire_protoc_sha256": wire_proto_record["protoc_sha256"],
                "e1_binding_changed": False,
            },
            "packet_build_tools": {
                "gpgv_sha256": _sha256_file(gpgv.resolve(strict=True)),
                "protoc_sha256": wire_proto_record["protoc_sha256"],
                "zstd_sha256": EXPECTED_ZSTD_SHA256,
            },
        }
        _write_json(packet_stage / "PACKET.json", packet_manifest)
        manifest_lines = []
        for path in sorted(
            (item for item in packet_stage.iterdir() if item.is_file()),
            key=lambda item: item.name.encode("utf-8"),
        ):
            if path.name == "MANIFEST.sha256":
                continue
            manifest_lines.append(f"{_sha256_file(path)}  {path.name}\n")
        (packet_stage / "MANIFEST.sha256").write_text(
            "".join(manifest_lines), encoding="utf-8"
        )
        (packet_stage / "MANIFEST.sha256").chmod(0o600)
        os.replace(packet_stage, output_dir)
        return packet_manifest
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-archive", type=Path, required=True)
    parser.add_argument("--seed-root", type=Path, required=True)
    parser.add_argument("--dfhack-source-root", type=Path, required=True)
    parser.add_argument("--canonical-proto-root", type=Path, required=True)
    parser.add_argument("--wheelhouse-root", type=Path, required=True)
    parser.add_argument("--docker-runtime-root", type=Path, required=True)
    parser.add_argument("--protoc", type=Path, default=Path("/opt/homebrew/bin/protoc"))
    parser.add_argument("--zstd", type=Path, default=Path("/opt/homebrew/bin/zstd"))
    parser.add_argument("--gpgv", type=Path, default=Path("/opt/homebrew/bin/gpgv"))
    return parser


def main() -> None:
    args = _parser().parse_args()
    requested_output = args.output_dir.absolute()
    receipt_path = requested_output.with_name(
        f"{requested_output.name}.determinism.json"
    )
    if receipt_path.exists():
        raise PacketError(f"determinism receipt already exists: {receipt_path}")
    common = {
        "repo_root": args.repo_root,
        "runtime_archive": args.runtime_archive,
        "seed_root": args.seed_root,
        "dfhack_source_root": args.dfhack_source_root,
        "canonical_proto_root": args.canonical_proto_root,
        "wheelhouse_root": args.wheelhouse_root,
        "docker_runtime_root": args.docker_runtime_root,
        "protoc": args.protoc,
        "zstd": args.zstd,
        "gpgv": args.gpgv,
    }
    result = build_packet(output_dir=requested_output, **common)
    verification_root = Path(
        tempfile.mkdtemp(
            prefix=".fortgym-m1b-determinism-", dir=requested_output.parent
        )
    )
    try:
        try:
            verification_output = verification_root / "packet"
            verification_result = build_packet(
                output_dir=verification_output,
                **common,
            )
            if result != verification_result:
                raise PacketError("independent packet metadata rebuild differs")
            verification = _verify_deterministic_packet_pair(
                requested_output, verification_output
            )
        finally:
            shutil.rmtree(verification_root, ignore_errors=True)
        if verification_root.exists():
            raise PacketError("temporary determinism packet could not be removed")
        verification["packet_dir"] = requested_output.name
        verification["temporary_verification_packet_removed"] = True
        _write_json(receipt_path, verification)
    except BaseException:
        shutil.rmtree(requested_output, ignore_errors=True)
        if receipt_path.exists() and not receipt_path.is_symlink():
            receipt_path.unlink()
        raise
    output = dict(result)
    output["build_verification"] = verification
    output["build_verification"]["receipt"] = receipt_path.name
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
