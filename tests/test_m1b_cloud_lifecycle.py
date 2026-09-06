from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from fort_gym.bench.run.live_acceptance import FROZEN_GATE_PLAN
from infra.m1b.build_live_packet import (
    DOCKER_RELEASE_KEY_FINGERPRINT,
    DOCKER_RELEASE_SIGNING_FINGERPRINT,
    DOCKER_REPOSITORY_BASE_URL,
    DOCKER_RUNTIME_BINARIES,
    DOCKER_RUNTIME_INPUTS,
    DOCKER_RUNTIME_PACKAGES,
)

REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "infra/m1b/run_gcp_live_acceptance.sh"
BOOTSTRAP = REPO_ROOT / "infra/m1b/bootstrap_live_host.sh"
ACCEPTANCE_SHA256 = "b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf"
ROOT_BROKER_SHA256 = hashlib.sha256(
    (REPO_ROOT / "infra/m1b/root_broker.py").read_bytes()
).hexdigest()
HOST_RUNNER_SHA256 = hashlib.sha256(
    (REPO_ROOT / "infra/m1b/run_live_acceptance.py").read_bytes()
).hexdigest()


def test_lifecycle_host_runner_pin_matches_source() -> None:
    assert f"HOST_RUNNER_SHA256='{HOST_RUNNER_SHA256}'" in SCRIPT.read_text()
    assert f"ROOT_BROKER_SHA256='{ROOT_BROKER_SHA256}'" in SCRIPT.read_text()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_executable(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _docker_runtime_manifest() -> dict[str, object]:
    packages = []
    for package in sorted(DOCKER_RUNTIME_PACKAGES):
        specification = DOCKER_RUNTIME_PACKAGES[package]
        filename = str(specification["filename"])
        digest, size = DOCKER_RUNTIME_INPUTS[filename]
        packages.append(
            {
                "package": package,
                "version": specification["version"],
                "architecture": "amd64",
                "filename": filename,
                "repository_path": f"dists/bookworm/pool/stable/amd64/{filename}",
                "size_bytes": size,
                "sha256": digest,
            }
        )
    binaries = [
        {
            "path": path,
            "package": package,
            "architecture": "amd64",
            "mode": "0755",
            "size_bytes": size,
            "sha256": digest,
        }
        for path, (package, digest, size) in sorted(DOCKER_RUNTIME_BINARIES.items())
    ]
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
        "schema": "fortgym.m1b-docker-runtime/v1",
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
            "packages_gz_sha256": DOCKER_RUNTIME_INPUTS["Packages.gz"][0],
            "signature_verified": True,
        },
        "packages": packages,
        "binaries": binaries,
        "archive_members": archive_members,
    }


def _refresh_packet_manifest(packet: Path) -> str:
    members = sorted(
        path for path in packet.iterdir() if path.name != "MANIFEST.sha256"
    )
    manifest = packet / "MANIFEST.sha256"
    manifest.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in members),
        encoding="utf-8",
    )
    return _sha256(manifest)


def _make_packet(tmp_path: Path) -> tuple[Path, str]:
    packet = tmp_path / "packet"
    packet.mkdir()
    packet_json = {
        "schema": "fortgym.m1b-live-input-packet/v1",
        "acceptance_sha256": ACCEPTANCE_SHA256,
        "authority": {
            "ephemeral_only": True,
            "infrastructure_authority_expires_at": "2026-09-06T12:00:00Z",
            "infrastructure_authorized_local_date": "2026-09-05",
            "infrastructure_daily_ceiling_usd": 210,
            "paid_models": "forbidden",
            "production_access": "forbidden",
            "production_mutation": "forbidden",
            "provider_calls": 0,
            "provider_cost_usd": 0,
            "publish_deploy_push_tag_e1": "forbidden",
        },
        "runtime_archive": {"platform": "linux/amd64"},
        "runtime_proto": {
            "runtime_binding_sha256": (
                "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f"
            ),
            "e1_binding_changed": False,
        },
        "wheelhouse": {
            "python": "3.11",
            "platform": "linux/x86_64",
            "network_install_required": False,
            "provider_sdks_present": False,
        },
    }
    source_manifest = {
        "schema": "fortgym.m1b-live-source-manifest/v1",
        "files": [
            {
                "path": "infra/m1b/bootstrap_live_host.sh",
                "sha256": _sha256(BOOTSTRAP),
            },
            {
                "path": "infra/m1b/activate_outer_egress_guard.sh",
                "sha256": "1" * 64,
            },
            {
                "path": "infra/m1b/root_broker.py",
                "sha256": (ROOT_BROKER_SHA256),
            },
            {
                "path": "infra/m1b/run_live_acceptance.py",
                "sha256": (HOST_RUNNER_SHA256),
            },
        ],
    }
    (packet / "source-manifest.json").write_text(
        json.dumps(source_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    for name in (
        "fortgym-df-m1a.tar.zst",
        "fortgym-m1b-source.tar",
        "fortgym-m1b-wheelhouse.tar",
        "live-requirements.lock",
        "live-wheelhouse.sha256",
        "seed_tree.sha256z",
    ):
        (packet / name).write_bytes((name + "\n").encode())
    docker_archive = packet / "fortgym-m1b-docker-runtime.tar"
    docker_archive.write_bytes(b"test-only-packet-bound-docker-runtime\n")
    docker_manifest = packet / "docker-runtime-manifest.json"
    docker_record = _docker_runtime_manifest()
    docker_manifest.write_text(
        json.dumps(docker_record, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    runtime_archive_path = packet / "fortgym-df-m1a.tar.zst"
    packet_json["runtime_archive"].update(
        {
            "compressed_sha256": _sha256(runtime_archive_path),
            "size_bytes": runtime_archive_path.stat().st_size,
            "manifest_sha256": (
                "d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
            ),
            "manifest_size_bytes": 2306,
            "manifest_media_type": "application/vnd.oci.image.manifest.v1+json",
            "config_sha256": (
                "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
            ),
        }
    )
    packet_json.update(
        {
            "source": {
                "archive": "fortgym-m1b-source.tar",
                "archive_sha256": _sha256(packet / "fortgym-m1b-source.tar"),
                "manifest": "source-manifest.json",
                "tree_sha256": "3" * 64,
                "extract_root": "/opt/fort-gym-m1a",
            },
            "seed": {
                "tree_sha256": "4" * 64,
                "world_sha256": "5" * 64,
                "file_count": 1,
                "file_bytes": 1,
            },
            "packet_build_tools": {
                "gpgv_sha256": "6" * 64,
                "protoc_sha256": "7" * 64,
                "zstd_sha256": "8" * 64,
            },
            "docker_runtime": {
                **docker_record,
                "archive": docker_archive.name,
                "archive_sha256": _sha256(docker_archive),
                "manifest": docker_manifest.name,
                "manifest_sha256": _sha256(docker_manifest),
            },
        }
    )
    (packet / "PACKET.json").write_text(
        json.dumps(packet_json, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return packet, _refresh_packet_manifest(packet)


def _make_fake_commands(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    state = tmp_path / "fake-state"
    fake_bin.mkdir()
    state.mkdir()
    (state / "frozen-gates.json").write_text(
        json.dumps(
            [
                gate.payload(gate_index=index)
                for index, gate in enumerate(FROZEN_GATE_PLAN, start=1)
            ],
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (state / "acceptance.yaml").write_bytes(
        (REPO_ROOT / "infra/m1b/acceptance.yaml").read_bytes()
    )
    (state / "docker-runtime-record.json").write_text(
        json.dumps(_docker_runtime_manifest(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    dispatcher = fake_bin / "fake-command"
    _write_executable(
        dispatcher,
        r"""
        #!/usr/bin/env python3
        import datetime
        import hashlib
        import io
        import json
        import os
        import pathlib
        import signal
        import shutil
        import subprocess
        import sys
        import tarfile
        import time

        ACCEPTANCE_SHA256 = (
            "b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf"
        )
        ROOT_BROKER_SHA256 = (
            "__CURRENT_ROOT_BROKER_SHA256__"
        )

        command = pathlib.Path(sys.argv[0]).name
        args = sys.argv[1:]
        state = pathlib.Path(os.environ["FAKE_STATE_DIR"])
        if os.environ.get("FAKE_PREPARE_ONLY") != "1":
            with (state / "commands.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps([command, *args]) + "\n")
        if (
            command == "gcloud"
            and os.environ.get("FAKE_MALFORM_WATCHDOG_EVIDENCE") == "1"
            and not (state / "watchdog-malformed").exists()
        ):
            evidence = pathlib.Path(os.environ["FAKE_EVIDENCE_DIR"])
            with (evidence / "watchdog-events.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write("{malformed-test-record\n")
            (state / "watchdog-malformed").write_text("1\n")
        hang_match = os.environ.get("FAKE_HANG_COMMAND_MATCH", "")
        if hang_match and hang_match in " ".join([command, *args]):
            while True:
                time.sleep(1)

        def mux_slave_control_path():
            value = next(
                (item for item in args if item.startswith("ControlPath=")), None
            )
            return pathlib.Path(value.split("=", 1)[1]) if value else None

        def refuse_or_record_direct_fallback():
            control_path = mux_slave_control_path()
            if control_path is None or control_path.exists():
                return
            if "ProxyCommand=/usr/bin/false" in args:
                raise SystemExit(255)
            (state / "direct-network-fallback-attempted").write_text("1\n")

        def canonical_json_bytes(payload):
            return (
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()

        def root_attestation_payloads():
            auxiliary = {
                name: {
                    "schema": "fortgym.m1b-test-bootstrap-leaf/v1",
                    "ok": True,
                    "leaf": name,
                }
                for name in (
                    "provider-capability-probe.json",
                    "provider-prepare.json",
                    "provider-snapshot.json",
                    "provider-bootstrap-guard.json",
                    "provider-bootstrap-inner.json",
                    "provider-cleanup.json",
                    "provider-cleanup-idempotent.json",
                )
            }
            leaf_sha = {
                name: hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
                for name, payload in auxiliary.items()
            }
            docker = {
                "schema": "fortgym.m1b-docker-runtime-attestation/v1",
                "ok": True,
                "docker_server_version": "29.1.3",
                "containerd_version": "2.2.1",
                "containerd_snapshotter_driver": "io.containerd.snapshotter.v1",
                "docker_server_29_1_3_containerd_store": True,
                "daemon_configured_before_first_start": True,
                "userland_proxy_disabled": True,
                "offline_packet_packages_only": True,
                "distro_docker_io_installed": False,
                "signed_repository_verified": True,
                "runtime_manifest_sha256": os.environ[
                    "FAKE_DOCKER_RUNTIME_MANIFEST_SHA"
                ],
                "installed_binaries": json.loads(
                    (state / "docker-runtime-record.json").read_text()
                )["binaries"],
            }
            if os.environ.get("FAKE_BAD_DOCKER_ATTESTATION") == "1":
                docker["docker_server_version"] = "0.0.0"
            archive = {
                "schema": "fortgym.m1b-runtime-archive-attestation/v1",
                "ok": True,
                "path": "/opt/fortgym-m1b/runtime-image.tar.zst",
                "sha256": os.environ["FAKE_RUNTIME_ARCHIVE_SHA"],
                "size_bytes": int(os.environ["FAKE_RUNTIME_ARCHIVE_SIZE"]),
                "runtime_archive_digest_exact": True,
                "root_owned_mode_0600": True,
            }
            provider = {
                "schema": "fortgym.m1b-provider-helper-bpf-attestation/v1",
                "ok": True,
                "provider_helper_bpf_attested": True,
                "source_tree_sha256": "3" * 64,
                "source_manifest_sha256": os.environ[
                    "FAKE_SOURCE_MANIFEST_SHA"
                ],
                "helper_path": "/usr/local/libexec/fortgym-provider-network-helper",
                "helper_sha256": "a" * 64,
                "helper_mode": "4750",
                "bpf_object_path": "/usr/local/lib/fortgym/provider_network.bpf.o",
                "bpf_object_sha256": "b" * 64,
                "bpf_object_mode": "0644",
                "reproducible_build_outputs_match": True,
                "installed_outputs_match_build": True,
                "root_owned_nonwritable_ancestry": True,
                "live_setuid_helper_exercised_as_nonroot": True,
                "kernel_bpf_load_attested": True,
                "cgroup_hooks_attached": True,
                "default_deny_negative_canary_attested": True,
                "negative_canary_event_count": 6,
                "exact_loopback_allow_attested": True,
                "zero_lost_events": True,
                "cleanup_idempotent": True,
                "capability_probe_sha256": leaf_sha[
                    "provider-capability-probe.json"
                ],
                "prepare_sha256": leaf_sha["provider-prepare.json"],
                "snapshot_sha256": leaf_sha["provider-snapshot.json"],
                "guard_attestation_sha256": leaf_sha[
                    "provider-bootstrap-guard.json"
                ],
                "inner_allow_probe_sha256": leaf_sha[
                    "provider-bootstrap-inner.json"
                ],
                "cleanup_sha256": leaf_sha["provider-cleanup.json"],
                "cleanup_idempotent_sha256": leaf_sha[
                    "provider-cleanup-idempotent.json"
                ],
            }
            descriptor = {
                "schema": "fortgym.m1b-docker-image-descriptor-attestation/v1",
                "ok": True,
                "image_reference": "fortgym-df:m1a-stock-0.47.05-r8",
                "image_id": (
                    "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
                ),
                "manifest_digest": (
                    "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
                ),
                "manifest_media_type": (
                    "application/vnd.oci.image.manifest.v1+json"
                ),
                "manifest_size_bytes": 2306,
                "config_digest": (
                    "sha256:d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
                ),
                "platform": "linux/amd64",
                "containerd_image_store_descriptor_attested": True,
            }
            subordinate = {
                "docker-runtime-attestation.json": docker,
                "runtime-archive-attestation.json": archive,
                "provider-helper-bpf-attestation.json": provider,
                "docker-image-descriptor-attestation.json": descriptor,
            }
            subordinate_sha = {
                name: hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
                for name, payload in subordinate.items()
            }
            trusted = {
                "schema": "fortgym.m1b-trusted-host-paths/v1",
                "ok": True,
                "source_root_owned_nonwritable": True,
                "venv_owned_nonwritable": True,
                "interpreter_owned_nonwritable": True,
                "site_packages_owned_nonwritable": True,
                "isolated_source_pth_exact": True,
                "broker_owned_nonwritable": True,
                "packet_metadata_root_owned_readable": True,
                "packet_archives_root_only": True,
                "broker_receipts_root_only": True,
                "docker_server_29_1_3_containerd_store": True,
                "runtime_archive_digest_exact": True,
                "provider_helper_bpf_attested": True,
                "docker_runtime_attestation_sha256": subordinate_sha[
                    "docker-runtime-attestation.json"
                ],
                "runtime_archive_attestation_sha256": subordinate_sha[
                    "runtime-archive-attestation.json"
                ],
                "provider_helper_bpf_attestation_sha256": subordinate_sha[
                    "provider-helper-bpf-attestation.json"
                ],
                "docker_image_descriptor_attestation_sha256": subordinate_sha[
                    "docker-image-descriptor-attestation.json"
                ],
            }
            return {**auxiliary, **subordinate, "trusted-paths.json": trusted}

        def root_attestation_sha(name):
            return hashlib.sha256(
                canonical_json_bytes(root_attestation_payloads()[name])
            ).hexdigest()

        if command == "ssh-keygen":
            target = pathlib.Path(args[args.index("-f") + 1])
            target.write_text("test-only-private-key\n", encoding="utf-8")
            target.chmod(0o600)
            target.with_suffix(target.suffix + ".pub").write_text(
                "ssh-ed25519 AAAATESTONLY fortgym-test\n", encoding="utf-8"
            )
            raise SystemExit(0)

        if command == "ssh":
            joined = " ".join(args)
            if "-O" in args:
                operation = args[args.index("-O") + 1]
                control_path = pathlib.Path(args[args.index("-S") + 1])
                if operation == "check":
                    if os.environ.get("FAKE_HANG_MUX_CHECK") == "1":
                        while True:
                            time.sleep(1)
                    raise SystemExit(0 if control_path.exists() else 1)
                if operation == "exit":
                    if os.environ.get("FAKE_HANG_MUX_CLOSE") == "1":
                        while True:
                            time.sleep(1)
                    (state / "mux-stop").write_text("1\n")
                    control_path.unlink(missing_ok=True)
                    raise SystemExit(0)
            if "-M" in args and "-N" in args:
                control_path = pathlib.Path(args[args.index("-S") + 1])
                attempt_path = state / "mux-attempt-count"
                attempt = (
                    int(attempt_path.read_text(encoding="utf-8")) + 1
                    if attempt_path.exists()
                    else 1
                )
                attempt_path.write_text(f"{attempt}\n", encoding="utf-8")
                if attempt <= int(os.environ.get("FAKE_MUX_FAIL_ATTEMPTS", "0")):
                    print("ssh: connect to host: Connection refused", file=sys.stderr)
                    raise SystemExit(255)
                if os.environ.get("FAKE_MUX_PARTIAL_HANG") != "1":
                    control_path.write_text("fake-control-socket\n")

                def stop_master(_signum, _frame):
                    if os.environ.get("FAKE_MUX_IGNORE_TERM") == "1":
                        return
                    control_path.unlink(missing_ok=True)
                    (state / "mux-master-reaped").write_text("1\n")
                    raise SystemExit(143)

                signal.signal(signal.SIGTERM, stop_master)
                signal.signal(signal.SIGINT, stop_master)
                while not (state / "mux-stop").exists():
                    time.sleep(0.02)
                control_path.unlink(missing_ok=True)
                (state / "mux-master-reaped").write_text("1\n")
                raise SystemExit(0)
            refuse_or_record_direct_fallback()
            if "/usr/bin/sha256sum -- /tmp/fortgym-m1b-bootstrap" in joined:
                print(os.environ["FAKE_BOOTSTRAP_SHA"] + "  remote-bootstrap")
                raise SystemExit(0)
            fail_match = os.environ.get("FAKE_SSH_FAIL_MATCH", "")
            if fail_match and fail_match in joined:
                raise SystemExit(23)
            if "/var/lib/fortgym-m1b-root-evidence/bootstrap.json" in joined:
                bootstrap_receipt = {
                    "schema": "fortgym.m1b-live-host-bootstrap/v1",
                    "ok": True,
                    "acceptance_sha256": ACCEPTANCE_SHA256,
                    "authority_expires_at": "2026-09-06T12:00:00Z",
                    "bootstrap_completed_at": "2026-09-05T14:00:00+00:00",
                    "manifest_sha256_out_of_band": os.environ[
                        "FAKE_PACKET_MANIFEST_SHA"
                    ],
                    "packet_copied_to_root_staging": True,
                    "runtime_archive_path": "/opt/fortgym-m1b/runtime-image.tar.zst",
                    "runtime_image_manifest_digest": (
                        "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
                    ),
                    "runtime_image_manifest_media_type": (
                        "application/vnd.oci.image.manifest.v1+json"
                    ),
                    "runtime_image_manifest_size_bytes": 2306,
                    "safe_archive_preflight_completed": True,
                    "docker_runtime_manifest_sha256": os.environ[
                        "FAKE_DOCKER_RUNTIME_MANIFEST_SHA"
                    ],
                    "docker_runtime_attestation_sha256": root_attestation_sha(
                        "docker-runtime-attestation.json"
                    ),
                    "runtime_archive_attestation_sha256": root_attestation_sha(
                        "runtime-archive-attestation.json"
                    ),
                    "provider_helper_bpf_attestation_sha256": root_attestation_sha(
                        "provider-helper-bpf-attestation.json"
                    ),
                    "docker_image_descriptor_attestation_sha256": root_attestation_sha(
                        "docker-image-descriptor-attestation.json"
                    ),
                    "trusted_paths_sha256": root_attestation_sha(
                        "trusted-paths.json"
                    ),
                    "docker_server_version": "29.1.3",
                    "containerd_version": "2.2.1",
                    "docker_server_29_1_3_containerd_store": True,
                    "runtime_archive_digest_exact": True,
                    "provider_helper_bpf_attested": True,
                    "containerd_image_store_descriptor_attested": True,
                    "docker_install_mode": "offline-packet-bound-docker-ce-debs",
                    "distro_docker_io_installed": False,
                    "daemon_configured_before_first_start": True,
                    "docker_userland_proxy_disabled": True,
                    "root_broker_sha256": ROOT_BROKER_SHA256,
                    "python_major_minor": "3.11",
                    "source_pth_path": (
                        "/opt/fortgym-m1b/venv/lib/python3.11/site-packages/"
                        "fortgym-m1b-source.pth"
                    ),
                    "source_pth_sha256": (
                        "cfa04bac75c5d609673a9f4e2dcb49639bf291ffbc51b978722d7e0a03938544"
                    ),
                    "nonroot_isolated_import_ok": True,
                    "nonroot_measurement_code_digest_ok": True,
                    "measurement_code_sha256": "c" * 64,
                    "source_path_preserves_repo_file": True,
                    "root_broker_is_only_sudo_target": True,
                    "service_user_in_docker_group": False,
                    "root_evidence_private": True,
                    "dependency_install_mode": "python3.11-venv-offline-pinned-wheels",
                    "dependency_waivers": False,
                    "runtime_image_id": (
                        "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
                    ),
                    "expiry_timer_next_elapse": "2026-09-06T12:00:00Z",
                    "provider_calls": 0,
                    "provider_cost_usd": 0,
                }
                (state / "bootstrap-receipt.json").write_text(
                    json.dumps(bootstrap_receipt, sort_keys=True, separators=(",", ":"))
                    + "\n"
                )
                print(json.dumps(bootstrap_receipt, sort_keys=True, separators=(",", ":")))
                raise SystemExit(0)
            if "/var/lib/fortgym-m1b-root-evidence/nonroot-isolated-import.json" in joined:
                import_proof = {
                    "schema": "fortgym.m1b-nonroot-isolated-import/v1",
                    "ok": True,
                    "effective_uid_nonzero": True,
                    "python_isolated": True,
                    "source_root": "/opt/fort-gym-m1a",
                    "package_file": "/opt/fort-gym-m1a/fort_gym/__init__.py",
                    "source_pth": (
                        "/opt/fortgym-m1b/venv/lib/python3.11/site-packages/"
                        "fortgym-m1b-source.pth"
                    ),
                    "source_pth_sha256": (
                        "cfa04bac75c5d609673a9f4e2dcb49639bf291ffbc51b978722d7e0a03938544"
                    ),
                    "runtime_binding_sha256": (
                        "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f"
                    ),
                    "measurement_code_sha256": "c" * 64,
                    "provider_environment_present": (
                        os.environ.get("FAKE_BAD_BOOTSTRAP_PROOF") == "1"
                    ),
                }
                (state / "nonroot-isolated-import.json").write_text(
                    json.dumps(import_proof, sort_keys=True, separators=(",", ":"))
                    + "\n"
                )
                print(json.dumps(import_proof, sort_keys=True, separators=(",", ":")))
                raise SystemExit(0)
            if "sudo /bin/tar" in joined:
                tar_mode = os.environ.get("FAKE_EVIDENCE_TAR_MODE", "valid")
                if tar_mode == "traversal":
                    output = io.BytesIO()
                    with tarfile.open(fileobj=output, mode="w") as archive:
                        payload = b"escape\n"
                        member = tarfile.TarInfo("../outside-receipt.json")
                        member.size = len(payload)
                        archive.addfile(member, io.BytesIO(payload))
                    sys.stdout.buffer.write(output.getvalue())
                    raise SystemExit(0)
                batch_id = (state / "batch-id").read_text()
                staging = state / "tar-staging"
                if staging.exists():
                    shutil.rmtree(staging)
                batch_root = staging / f"fortgym-m1b/evidence/{batch_id}"
                service = batch_root / "control"
                root = staging / "fortgym-m1b-root-evidence"
                service.mkdir(parents=True, exist_ok=True)
                root.mkdir(parents=True, exist_ok=True)

                def canonical_bytes(payload):
                    return (
                        json.dumps(payload, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    ).encode()

                def write_json(path, payload):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(canonical_bytes(payload))
                    return hashlib.sha256(path.read_bytes()).hexdigest()

                def digest(path):
                    return hashlib.sha256(path.read_bytes()).hexdigest()

                def reference(path, relative):
                    return {
                        "path": relative,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "size_bytes": path.stat().st_size,
                    }

                decision_value = os.environ.get("FAKE_RUNNER_DECISION", "GO")
                acceptance_sha = ACCEPTANCE_SHA256
                plan_sha = (
                    "d37cad75e7e052ed4463353f0b3138f64143ca1e50337e6ad5eb29cbbca47194"
                )
                gates = json.loads((state / "frozen-gates.json").read_text())
                local_scopes = {
                    "PORT-1": "complete_local_gate",
                    "ORPHAN-1": "local_subprocedure",
                    "PROVIDER-ENV": "complete_local_gate",
                    "CAP-FAKE": "complete_local_gate",
                }
                local_pass = {"PORT-1", "PROVIDER-ENV", "CAP-FAKE"}
                failed = [] if decision_value == "GO" else ["PROVIDER-NET"]
                rows = []
                artifact_by_path = {}

                batch_ledger = service / "batch-ledger.jsonl"
                attempt_ledger = service / "attempt-ledger.jsonl"
                def write_ledger(path, schema, event):
                    unsigned = {
                        "schema": schema,
                        "batch_id": batch_id,
                        "acceptance_sha256": acceptance_sha,
                        "plan_sha256": plan_sha,
                        "sequence": 1,
                        "previous_record_sha256": "0" * 64,
                        "at": "2026-09-05T14:00:00+00:00",
                        "event": event,
                        "payload": {"test_only": True},
                    }
                    record = {
                        **unsigned,
                        "record_sha256": hashlib.sha256(
                            json.dumps(
                                unsigned, sort_keys=True, separators=(",", ":")
                            ).encode("ascii")
                        ).hexdigest(),
                    }
                    path.write_bytes(canonical_bytes(record))
                    return record["record_sha256"]

                batch_head_sha = write_ledger(
                    batch_ledger,
                    "fortgym.m1b-live-acceptance-batch-ledger/v1",
                    "batch_finalized",
                )
                attempt_head_sha = write_ledger(
                    attempt_ledger,
                    "fortgym.m1b-live-acceptance-attempt-ledger/v1",
                    "attempt_completed",
                )
                source_copy = batch_root / "inputs/source-manifest.json"
                source_copy.parent.mkdir(parents=True, exist_ok=True)
                source_copy.write_bytes(
                    pathlib.Path(os.environ["FAKE_SOURCE_MANIFEST_PATH"]).read_bytes()
                )
                for path, relative in (
                    (state / "acceptance.yaml", "contract/infra/m1b/acceptance.yaml"),
                    (source_copy, "inputs/source-manifest.json"),
                    (batch_ledger, "control/batch-ledger.jsonl"),
                    (attempt_ledger, "control/attempt-ledger.jsonl"),
                ):
                    artifact_by_path[relative] = reference(path, relative)

                for gate in gates:
                    gate_id = gate["id"]
                    relative = f"gates/{gate_id}/receipt.json"
                    evidence_path = batch_root / relative
                    write_json(evidence_path, {
                        "schema": "fortgym.m1b-test-gate-evidence/v1",
                        "batch_id": batch_id,
                        "gate_id": gate_id,
                    })
                    evidence_ref = reference(evidence_path, relative)
                    artifact_by_path[relative] = evidence_ref
                    status = (
                        "FAIL"
                        if gate_id in failed
                        else "PASS_LOCAL"
                        if gate_id in local_pass
                        else "PASS"
                    )
                    criteria = [] if status == "FAIL" else list(gate["pass"])
                    if gate_id == "PORT-1" and status != "FAIL":
                        # The controller preserves the frozen criteria tuple,
                        # while canonical JSON sorts keys inside ``gate.pass``.
                        # Exercise the real order instead of making object-key
                        # order part of the external verification contract.
                        criteria = [
                            "winners",
                            "durable_port_lease_conflicts",
                            "losers_start_runtime_or_harness",
                        ]
                    attempts = gate["attempts"]
                    real = sum(
                        item["kind"] == "real_runtime" for item in attempts
                    )
                    non_runtime = len(attempts) - real
                    local_credit = None
                    if gate_id in local_scopes:
                        local_credit = {
                            "gate_id": gate_id,
                            "scope": local_scopes[gate_id],
                            "criteria_passed": (
                                criteria
                                if gate_id == "PORT-1"
                                else list(gate["pass"])
                            ),
                            "evidence": [evidence_ref],
                        }
                    rows.append({
                        "gate": gate,
                        "status": status,
                        "criteria_passed": criteria,
                        "failure_code": (
                            "test_failure" if status == "FAIL" else None
                        ),
                        "evidence": [evidence_ref],
                        "local_credit": local_credit,
                        "attempts": {
                            "planned": len(attempts),
                            "started": len(attempts),
                            "completed": len(attempts),
                            "real_runtime_started": real,
                            "real_runtime_completed": real,
                            "non_runtime_started": non_runtime,
                            "non_runtime_completed": non_runtime,
                        },
                        "authorization_identity_sha256": (
                            "8" * 64 if gate_id == "ENOSPC" else None
                        ),
                        "attempt_ledger_head_sha256": "7" * 64,
                    })

                if os.environ.get("FAKE_SEALED_BAD_COUNTS") == "1":
                    rows[1]["attempts"]["real_runtime_completed"] = 0
                    rows[1]["attempts"]["completed"] = 1
                gate_payload = {
                    "schema": "fortgym.m1b-live-acceptance-gate-results/v1",
                    "batch_id": batch_id,
                    "acceptance_sha256": acceptance_sha,
                    "plan_sha256": plan_sha,
                    "gates": rows,
                }
                if os.environ.get("FAKE_SEALED_PLACEHOLDER") == "1":
                    gate_payload = {"test_only": True}
                gate_path = service / "gate-results.json"
                gate_sha = write_json(gate_path, gate_payload)
                artifact_by_path["control/gate-results.json"] = reference(
                    gate_path, "control/gate-results.json"
                )

                decision_payload = {
                    "schema": "fortgym.m1b-live-acceptance-decision/v1",
                    "batch_id": batch_id,
                    "acceptance_sha256": acceptance_sha,
                    "plan_sha256": plan_sha,
                    "decision": decision_value,
                    "hard_gate_count": 16,
                    "hard_gates_passed": 16 - len(failed),
                    "failed_or_incomplete_gates": failed,
                    "real_runtime_attempt_limit": 26,
                    "real_runtime_attempts_started": 26,
                    "real_runtime_attempts_completed": 26,
                    "non_runtime_attempts_started": 1,
                    "non_runtime_attempts_completed": 1,
                    "incomplete_attempt_ids": [],
                    "missing_attempt_ids": [],
                    "reasons": [
                        f"gate_not_passed:{gate_id}" for gate_id in failed
                    ],
                    "provider_calls": 0,
                    "provider_cost_usd": 0,
                }
                decision_path = service / "decision.json"
                decision_sha = write_json(decision_path, decision_payload)
                artifact_by_path["control/decision.json"] = reference(
                    decision_path, "control/decision.json"
                )
                manifest_payload = {
                    "schema": "fortgym.m1b-live-acceptance-evidence-manifest/v1",
                    "batch_id": batch_id,
                    "acceptance_sha256": acceptance_sha,
                    "plan_sha256": plan_sha,
                    "artifacts": [
                        artifact_by_path[path] for path in sorted(artifact_by_path)
                    ],
                }
                if os.environ.get("FAKE_SEALED_BAD_MANIFEST") == "1":
                    manifest_payload["artifacts"][0]["sha256"] = "0" * 64
                manifest_sha = write_json(
                    service / "evidence-manifest.json", manifest_payload
                )
                seal_sha = write_json(service / "seal.json", {
                    "schema": "fortgym.m1b-live-acceptance-seal/v1",
                    "batch_id": batch_id,
                    "acceptance_sha256": acceptance_sha,
                    "plan_sha256": plan_sha,
                    "decision": decision_value,
                    "gate_results_sha256": gate_sha,
                    "decision_sha256": decision_sha,
                    "evidence_manifest_sha256": manifest_sha,
                })

                expected_name = "fortgym-m1b-foreign-" + hashlib.sha256(
                    batch_id.encode()
                ).hexdigest()[:16]
                container_id = "f" * 64
                workspace = f"/var/lib/fortgym-m1b/canary/{batch_id}"
                inspect_argv = (
                    "docker", "inspect", "--type", "container", expected_name
                )
                broker_specs = {
                    "creation": (
                        "a" * 64,
                        "BATCH-CANARY",
                        "canary_create",
                        True,
                        0,
                        (
                            "docker", "create", "--name", expected_name,
                            "--network", "none", "--memory", "128m",
                            "--memory-swap", "128m", "--pids-limit", "16",
                            "--cap-drop", "ALL", "--security-opt",
                            "no-new-privileges", "--restart", "no",
                            "--entrypoint", "/bin/sleep",
                            "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c",
                            "28800",
                        ),
                    ),
                    "initial_inspect": (
                        "b" * 64, "BATCH-CANARY", "canary_inspect", True, 0,
                        inspect_argv,
                    ),
                    "pre_removal_inspect": (
                        "c" * 64, "CLEANUP", "canary_inspect", True, 0,
                        inspect_argv,
                    ),
                    "removal": (
                        "d" * 64, "CLEANUP", "canary_remove", True, 0,
                        ("docker", "rm", "--force", expected_name),
                    ),
                    "absence": (
                        "e" * 64, "CLEANUP", "canary_absence", True, 0,
                        (
                            "docker", "ps", "--all", "--no-trunc", "--filter",
                            f"name=^/{expected_name}$", "--format", "{{.ID}}",
                        ),
                    ),
                }
                broker_digests = {}
                broker_private = {}
                broker_root_digests = {}
                broker_state_root = staging / "fortgym-m1b/broker"
                claim_root = broker_state_root / "claims"
                grant_root = broker_state_root / "grants"
                receipt_root = broker_state_root / "receipts"
                for directory in (claim_root, grant_root, receipt_root):
                    directory.mkdir(parents=True, exist_ok=True)
                for role, (request_id, gate_id, action, ok, returncode, argv) in (
                    broker_specs.items()
                ):
                    request_sha = hashlib.sha256(
                        f"request:{role}".encode()
                    ).hexdigest()
                    write_json(claim_root / f"{request_id}.json", {
                        "schema": "fortgym.m1b-root-broker-claim/v1",
                        "request_id": request_id,
                        "request_sha256": request_sha,
                        "acceptance_sha256": acceptance_sha,
                        "plan_sha256": plan_sha,
                        "batch_id": batch_id,
                        "gate_id": gate_id,
                        "grant_kind": "batch_canary",
                        "attempt_id": None,
                        "action": action,
                    })
                    logical_sha = hashlib.sha256(
                        json.dumps(
                            list(argv), sort_keys=True, separators=(",", ":")
                        ).encode("ascii")
                    ).hexdigest()
                    grant_identity = {
                        "batch_id": batch_id,
                        "grant_kind": "batch_canary",
                        "attempt_id": None,
                        "attempt_identity_sha256": None,
                        "gate_id": gate_id,
                        "action": action,
                        "logical_argv_sha256": logical_sha,
                        "recovery_epoch": 0,
                    }
                    if action in {"canary_inspect", "canary_absence"}:
                        grant_identity["request_id"] = request_id
                    grant_id = hashlib.sha256(
                        json.dumps(
                            grant_identity, sort_keys=True, separators=(",", ":")
                        ).encode("ascii")
                    ).hexdigest()
                    grant_sha = write_json(grant_root / f"{grant_id}.json", {
                        "schema": "fortgym.m1b-root-broker-action-grant/v1",
                        "acceptance_sha256": acceptance_sha,
                        "plan_sha256": plan_sha,
                        **grant_identity,
                        "request_id": request_id,
                        "batch_ledger_head_sha256": (
                            None if gate_id == "BATCH-CANARY" else batch_head_sha
                        ),
                        "one_shot": action in {
                            "canary_create", "canary_remove"
                        },
                    })
                    private_receipt = {
                        "schema": "fortgym.m1b-root-broker-receipt/v1",
                        "ok": ok,
                        "request_id": request_id,
                        "request_sha256": request_sha,
                        "acceptance_sha256": ACCEPTANCE_SHA256,
                        "policy_sha256": "2" * 64,
                        "broker_source_sha256": ROOT_BROKER_SHA256,
                        "batch_id": batch_id,
                        "gate_id": gate_id,
                        "grant_kind": "batch_canary",
                        "attempt_id": None,
                        "attempt_identity_sha256": None,
                        "action": action,
                        "binding": None,
                        "logical_argv_sha256": logical_sha,
                        "returncode": returncode,
                        "stdout": "",
                        "stderr": "",
                        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                        "result": None,
                        "shell": False,
                        "action_grant_sha256": grant_sha,
                    }
                    receipt = {
                        key: value
                        for key, value in private_receipt.items()
                        if key not in {"stdout", "stderr"}
                    }
                    broker_private[role] = private_receipt
                    broker_root_digests[role] = write_json(
                        receipt_root / f"{request_id}.json", private_receipt
                    )
                    broker_digests[role] = write_json(
                        batch_root / "broker-client" / gate_id / f"{request_id}.json",
                        receipt,
                    )

                if os.environ.get("FAKE_INCOMPLETE_PARTIAL_ROOT") == "1":
                    partial_logical_sha = hashlib.sha256(
                        json.dumps(
                            list(inspect_argv),
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("ascii")
                    ).hexdigest()
                    for partial_request_id, progression in (
                        ("1" * 64, "claim"),
                        ("2" * 64, "grant"),
                        ("3" * 64, "receipt_without_public_projection"),
                    ):
                        partial_request_sha = hashlib.sha256(
                            f"partial:{partial_request_id}".encode()
                        ).hexdigest()
                        write_json(
                            claim_root / f"{partial_request_id}.json",
                            {
                                "schema": "fortgym.m1b-root-broker-claim/v1",
                                "request_id": partial_request_id,
                                "request_sha256": partial_request_sha,
                                "acceptance_sha256": acceptance_sha,
                                "plan_sha256": plan_sha,
                                "batch_id": batch_id,
                                "gate_id": "CLEANUP",
                                "grant_kind": "batch_canary",
                                "attempt_id": None,
                                "action": "canary_inspect",
                            },
                        )
                        if progression != "claim":
                            partial_grant_identity = {
                                "batch_id": batch_id,
                                "grant_kind": "batch_canary",
                                "attempt_id": None,
                                "attempt_identity_sha256": None,
                                "gate_id": "CLEANUP",
                                "action": "canary_inspect",
                                "logical_argv_sha256": partial_logical_sha,
                                "recovery_epoch": 0,
                                "request_id": partial_request_id,
                            }
                            partial_grant_id = hashlib.sha256(
                                json.dumps(
                                    partial_grant_identity,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ).encode("ascii")
                            ).hexdigest()
                            partial_grant_sha = write_json(
                                grant_root / f"{partial_grant_id}.json",
                                {
                                    "schema": (
                                        "fortgym.m1b-root-broker-action-grant/v1"
                                    ),
                                    "acceptance_sha256": acceptance_sha,
                                    "plan_sha256": plan_sha,
                                    **partial_grant_identity,
                                    "batch_ledger_head_sha256": batch_head_sha,
                                    "one_shot": False,
                                },
                            )
                            if progression == "receipt_without_public_projection":
                                write_json(
                                    receipt_root / f"{partial_request_id}.json",
                                    {
                                        "schema": (
                                            "fortgym.m1b-root-broker-receipt/v1"
                                        ),
                                        "ok": True,
                                        "request_id": partial_request_id,
                                        "request_sha256": partial_request_sha,
                                        "acceptance_sha256": acceptance_sha,
                                        "policy_sha256": "2" * 64,
                                        "broker_source_sha256": ROOT_BROKER_SHA256,
                                        "batch_id": batch_id,
                                        "gate_id": "CLEANUP",
                                        "grant_kind": "batch_canary",
                                        "attempt_id": None,
                                        "attempt_identity_sha256": None,
                                        "action": "canary_inspect",
                                        "binding": None,
                                        "logical_argv_sha256": partial_logical_sha,
                                        "returncode": 0,
                                        "stdout": "",
                                        "stderr": "",
                                        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                                        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                                        "result": None,
                                        "shell": False,
                                        "action_grant_sha256": partial_grant_sha,
                                    },
                                )

                container_state_sha256 = "9" * 64
                write_json(batch_root / "batch-canary-created.json", {
                    "schema": "fortgym.m1b-batch-canary-created/v1",
                    "batch_id": batch_id,
                    "name": expected_name,
                    "container_id": container_id,
                    "process_id": 4242,
                    "process_start_ticks": 99,
                    "workspace": workspace,
                    "workspace_device": 1,
                    "workspace_inode": 2,
                    "container_state_sha256": container_state_sha256,
                    "broker_evidence_sha256": broker_digests["creation"],
                    "inspect_broker_evidence_sha256": broker_digests[
                        "initial_inspect"
                    ],
                })
                cleanup = {
                    "present": True,
                    "removed": True,
                    "name": expected_name,
                    "container_id": container_id,
                    "container_absent": True,
                    "container_absence_returncode": 0,
                    "process_id": 4242,
                    "process_start_ticks": 99,
                    "process_absent": True,
                    "workspace": workspace,
                    "workspace_absent": True,
                    "initial_container_state_sha256": container_state_sha256,
                    "pre_removal_container_state_sha256": container_state_sha256,
                    "pre_removal_broker_evidence_sha256": broker_digests[
                        "pre_removal_inspect"
                    ],
                    "creation_broker_evidence_sha256": broker_digests["creation"],
                    "removal_broker_evidence_sha256": broker_digests["removal"],
                    "absence_broker_evidence_sha256": broker_digests["absence"],
                }
                if os.environ.get("FAKE_BAD_POST_SEAL_CLEANUP") == "1":
                    cleanup["workspace_absent"] = False
                post_cleanup_path = batch_root / "post-seal-host-cleanup.json"
                post_cleanup_sha = write_json(post_cleanup_path, {
                    "schema": "fortgym.m1b-post-seal-host-cleanup/v1",
                    "batch_id": batch_id,
                    "acceptance_sha256": ACCEPTANCE_SHA256,
                    "plan_sha256": (
                        "d37cad75e7e052ed4463353f0b3138f64143ca1e50337e6ad5eb29cbbca47194"
                    ),
                    "controller_seal_sha256": seal_sha,
                    "cleanup": cleanup,
                })

                def inventory(root_directory, schema):
                    records = []
                    for path in sorted(root_directory.glob("*.json")):
                        document = json.loads(path.read_text())
                        if (
                            document.get("schema") == schema
                            and document.get("batch_id") == batch_id
                        ):
                            records.append({"id": path.stem, "sha256": digest(path)})
                    return records

                prior_inventories = {
                    "claims": inventory(
                        claim_root, "fortgym.m1b-root-broker-claim/v1"
                    ),
                    "grants": inventory(
                        grant_root, "fortgym.m1b-root-broker-action-grant/v1"
                    ),
                    "receipts": inventory(
                        receipt_root, "fortgym.m1b-root-broker-receipt/v1"
                    ),
                }
                root_records = {
                    **prior_inventories,
                    "aggregate_sha256": hashlib.sha256(
                        json.dumps(
                            prior_inventories,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("ascii")
                    ).hexdigest(),
                }
                if os.environ.get("FAKE_BAD_ROOT_INVENTORY") == "1":
                    root_records["aggregate_sha256"] = "0" * 64
                public_inventory = []
                for path in sorted((batch_root / "broker-client").rglob("*.json")):
                    public = json.loads(path.read_text())
                    request_id = public["request_id"]
                    public_inventory.append({
                        "request_id": request_id,
                        "path": path.relative_to(batch_root).as_posix(),
                        "sha256": digest(path),
                        "root_receipt_sha256": digest(
                            receipt_root / f"{request_id}.json"
                        ),
                    })

                final_request_id = "6" * 64
                final_request_sha = hashlib.sha256(b"final-request").hexdigest()
                final_logical = (
                    "fortgym-root-broker",
                    "attest-broker-evidence",
                    batch_id,
                    seal_sha,
                    post_cleanup_sha,
                )
                final_logical_sha = hashlib.sha256(
                    json.dumps(
                        list(final_logical), sort_keys=True, separators=(",", ":")
                    ).encode("ascii")
                ).hexdigest()
                final_claim_sha = write_json(
                    claim_root / f"{final_request_id}.json",
                    {
                        "schema": "fortgym.m1b-root-broker-claim/v1",
                        "request_id": final_request_id,
                        "request_sha256": final_request_sha,
                        "acceptance_sha256": acceptance_sha,
                        "plan_sha256": plan_sha,
                        "batch_id": batch_id,
                        "gate_id": "CLEANUP",
                        "grant_kind": "batch_canary",
                        "attempt_id": None,
                        "action": "attest_broker_evidence",
                    },
                )
                final_grant_identity = {
                        "batch_id": batch_id,
                        "grant_kind": "batch_canary",
                        "attempt_id": None,
                        "attempt_identity_sha256": None,
                        "gate_id": "CLEANUP",
                        "action": "attest_broker_evidence",
                        "logical_argv_sha256": final_logical_sha,
                        "recovery_epoch": 0,
                }
                final_grant_id = hashlib.sha256(
                    json.dumps(
                        final_grant_identity,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest()
                final_grant_sha = write_json(
                    grant_root / f"{final_grant_id}.json",
                    {
                        "schema": "fortgym.m1b-root-broker-action-grant/v1",
                        "acceptance_sha256": acceptance_sha,
                        "plan_sha256": plan_sha,
                        **final_grant_identity,
                        "request_id": final_request_id,
                        "batch_ledger_head_sha256": batch_head_sha,
                        "one_shot": True,
                    },
                )
                root_attestation_path = (
                    root / "batches" / batch_id / "broker-attestation.json"
                )
                root_attestation = {
                    "schema": "fortgym.m1b-root-broker-attestation/v1",
                    "ok": True,
                    "batch_id": batch_id,
                    "acceptance_sha256": acceptance_sha,
                    "plan_sha256": plan_sha,
                    "authority_expires_at": "2026-09-06T12:00:00+00:00",
                    "packet": {
                        "packet_sha256": digest(
                            pathlib.Path(os.environ["FAKE_PACKET_PATH"])
                        ),
                        "source_manifest_sha256": os.environ[
                            "FAKE_SOURCE_MANIFEST_SHA"
                        ],
                    },
                    "controller": {
                        "batch_ledger_sha256": digest(batch_ledger),
                        "attempt_ledger_sha256": digest(attempt_ledger),
                        "batch_head_sha256": batch_head_sha,
                        "attempt_head_sha256": attempt_head_sha,
                        "seal_sha256": seal_sha,
                        "post_seal_cleanup_sha256": post_cleanup_sha,
                        "decision": decision_value,
                        "decision_sha256": decision_sha,
                        "gate_results_sha256": gate_sha,
                        "evidence_manifest_sha256": manifest_sha,
                    },
                    "attempts": {
                        "planned": 27,
                        "real_runtime_started": 26,
                        "real_runtime_completed": 26,
                        "non_runtime_started": 1,
                        "non_runtime_completed": 1,
                    },
                    "root_records": root_records,
                    "public_receipts": public_inventory,
                    "excluded_self": {
                        "request_id": final_request_id,
                        "request_sha256": final_request_sha,
                        "claim_sha256": final_claim_sha,
                        "grant_sha256": final_grant_sha,
                        "predicted_receipt_path": (
                            f"broker-client/CLEANUP/{final_request_id}.json"
                        ),
                        "predicted_receipt_digest_derivation": (
                            "sha256(canonical_json(root_receipt_without_stdout_stderr)+LF)"
                        ),
                        "root_records_excludes": ["claim", "grant", "receipt"],
                        "public_receipts_excludes": ["receipt"],
                        "reason": "self_referential_final_attestation_boundary",
                    },
                    "canary": {
                        "created": True,
                        "removed": True,
                        "absence_verified": True,
                    },
                    "provider_calls": 0,
                    "provider_cost_usd": 0,
                    "shell": False,
                }
                if os.environ.get("FAKE_BAD_ROOT_ATTESTATION") == "1":
                    root_attestation["provider_calls"] = 1
                root_attestation_sha = write_json(
                    root_attestation_path, root_attestation
                )
                result = {
                    "schema": "fortgym.m1b-root-broker-attestation-result/v1",
                    "ok": True,
                    "batch_id": batch_id,
                    "path": (
                        "/var/lib/fortgym-m1b-root-evidence/batches/"
                        f"{batch_id}/broker-attestation.json"
                    ),
                    "sha256": root_attestation_sha,
                }
                final_stdout = json.dumps(
                    result, sort_keys=True, separators=(",", ":")
                ) + "\n"
                final_private = {
                    "schema": "fortgym.m1b-root-broker-receipt/v1",
                    "ok": True,
                    "request_id": final_request_id,
                    "request_sha256": final_request_sha,
                    "acceptance_sha256": acceptance_sha,
                    "policy_sha256": "2" * 64,
                    "broker_source_sha256": ROOT_BROKER_SHA256,
                    "batch_id": batch_id,
                    "gate_id": "CLEANUP",
                    "grant_kind": "batch_canary",
                    "attempt_id": None,
                    "attempt_identity_sha256": None,
                    "action": "attest_broker_evidence",
                    "binding": None,
                    "logical_argv_sha256": final_logical_sha,
                    "returncode": 0,
                    "stdout": final_stdout,
                    "stderr": "",
                    "stdout_sha256": hashlib.sha256(
                        final_stdout.encode()
                    ).hexdigest(),
                    "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                    "result": result,
                    "shell": False,
                    "action_grant_sha256": final_grant_sha,
                }
                write_json(
                    receipt_root / f"{final_request_id}.json", final_private
                )
                final_public = {
                    key: value
                    for key, value in final_private.items()
                    if key not in {"stdout", "stderr"}
                }
                if os.environ.get("FAKE_BAD_FINAL_BROKER_RECEIPT") == "1":
                    final_public["broker_source_sha256"] = "0" * 64
                final_public_path = (
                    batch_root
                    / "broker-client"
                    / "CLEANUP"
                    / f"{final_request_id}.json"
                )
                final_public_sha = write_json(final_public_path, final_public)
                reference_path = batch_root / "root-broker-attestation-reference.json"
                reference_sha = write_json(reference_path, {
                    "schema": "fortgym.m1b-root-broker-attestation-reference/v1",
                    "batch_id": batch_id,
                    "acceptance_sha256": acceptance_sha,
                    "plan_sha256": plan_sha,
                    "controller_seal_sha256": seal_sha,
                    "post_seal_cleanup_path": (
                        f"/var/lib/fortgym-m1b/evidence/{batch_id}/"
                        "post-seal-host-cleanup.json"
                    ),
                    "post_seal_cleanup_sha256": post_cleanup_sha,
                    "root_attestation_path": result["path"],
                    "root_attestation_sha256": root_attestation_sha,
                    "broker_request_id": final_request_id,
                    "broker_public_receipt_path": (
                        f"/var/lib/fortgym-m1b/evidence/{batch_id}/"
                        f"broker-client/CLEANUP/{final_request_id}.json"
                    ),
                    "broker_public_receipt_sha256": final_public_sha,
                })
                write_json(state / "outcome-bindings.json", {
                    "post_seal_cleanup_sha256": post_cleanup_sha,
                    "broker_attestation_sha256": root_attestation_sha,
                    "broker_attestation_reference_sha256": reference_sha,
                    "broker_attestation_receipt_sha256": final_public_sha,
                    "final_request_id": final_request_id,
                })
                for name in (
                    "bootstrap.json",
                    "nonroot-isolated-import.json",
                    "trusted-paths.json",
                    "runtime-check.json",
                    "docker-image-inspect.json",
                    "docker-repository-signature.txt",
                    "docker-daemon-config-validate.txt",
                    "docker-runtime-attestation.json",
                    "runtime-archive-attestation.json",
                    "provider-helper-bpf-attestation.json",
                    "docker-image-descriptor-attestation.json",
                    "provider-capability-probe.json",
                    "provider-prepare.json",
                    "provider-snapshot.json",
                    "provider-bootstrap-guard.json",
                    "provider-bootstrap-inner.json",
                    "provider-cleanup.json",
                    "provider-cleanup-idempotent.json",
                    "expiry-timer.txt",
                    "sudoers-check.txt",
                    "outer-egress.json",
                    "outer-egress-rules.json",
                    "output-counter-before.json",
                    "output-counter-after.json",
                    "forward-counter-before.json",
                    "forward-counter-after.json",
                    "forward-canary.json",
                    "loopback-canary.json",
                    "control-ssh-flow.json",
                    "canaries.json",
                    "outer-egress-post-run-rules-before.json",
                    "outer-egress-post-run-rules.json",
                ):
                    (root / name).write_text('{"test_only":true}\n')
                (root / "bootstrap.json").write_bytes(
                    (state / "bootstrap-receipt.json").read_bytes()
                )
                (root / "nonroot-isolated-import.json").write_bytes(
                    (state / "nonroot-isolated-import.json").read_bytes()
                )
                for name, payload in root_attestation_payloads().items():
                    (root / name).write_bytes(canonical_json_bytes(payload))
                flow = {"test_only": True}
                (root / "control-ssh-flow.json").write_text(
                    json.dumps(flow, sort_keys=True, separators=(",", ":")) + "\n"
                )
                activation = {
                    "schema": "fortgym.m1b-outer-egress-guard/v1",
                    "ok": True,
                    "acceptance_sha256": ACCEPTANCE_SHA256,
                    "authority_expires_at": "2026-09-06T12:00:00Z",
                    "output_policy": "drop",
                    "forward_policy": "drop",
                    "preserved_non_loopback_flow": flow,
                    "live_ruleset_verified_before_and_after_canaries": True,
                }
                (root / "outer-egress.json").write_text(
                    json.dumps(activation, sort_keys=True, separators=(",", ":")) + "\n"
                )
                (root / "outer-egress-post-run.json").write_text(json.dumps({
                    "schema": "fortgym.m1b-outer-egress-post-run-verification/v1",
                    "ok": True,
                    "acceptance_sha256": ACCEPTANCE_SHA256,
                    "authority_expires_at": "2026-09-06T12:00:00Z",
                    "verification_mode": "read-only",
                    "network_rules_mutated": False,
                    "table": "inet fortgym_m1b_outer",
                    "output_policy": "drop",
                    "forward_policy": "drop",
                    "exact_control_ssh_flow_sha256": digest(
                        root / "control-ssh-flow.json"
                    ),
                    "activation_guard_receipt_sha256": digest(
                        root / "outer-egress.json"
                    ),
                    "exact_ssh_counter_before": 10,
                    "exact_ssh_counter_after": (
                        10 if os.environ.get("FAKE_BAD_POST_RUN_PROOF") == "1" else 11
                    ),
                    "exact_ssh_counter_delta": (
                        0 if os.environ.get("FAKE_BAD_POST_RUN_PROOF") == "1" else 1
                    ),
                    "rules_before_sha256": digest(
                        root / "outer-egress-post-run-rules-before.json"
                    ),
                    "rules_after_sha256": digest(
                        root / "outer-egress-post-run-rules.json"
                    ),
                    "provider_calls": 0,
                    "provider_cost_usd": 0,
                }) + "\n")
                output = io.BytesIO()
                with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    archive.add(
                        staging / "fortgym-m1b/evidence",
                        arcname="fortgym-m1b/evidence",
                    )
                    for name in ("claims", "grants", "receipts"):
                        archive.add(
                            staging / "fortgym-m1b/broker" / name,
                            arcname=f"fortgym-m1b/broker/{name}",
                        )
                    archive.add(root, arcname="fortgym-m1b-root-evidence")
                sys.stdout.buffer.write(output.getvalue())
                raise SystemExit(0)
            if "run_live_acceptance.py" in joined:
                batch_id = args[args.index("--batch-id") + 1]
                (state / "batch-id").write_text(batch_id)
                prepare_env = os.environ.copy()
                prepare_env["FAKE_EVIDENCE_TAR_MODE"] = "valid"
                prepare_env["FAKE_PREPARE_ONLY"] = "1"
                prepared = subprocess.run(
                    [str(pathlib.Path(sys.argv[0]).parent / "ssh"), "sudo /bin/tar"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=prepare_env,
                )
                if prepared.returncode != 0:
                    sys.stderr.buffer.write(prepared.stderr)
                    raise SystemExit(prepared.returncode)
                bindings = json.loads((state / "outcome-bindings.json").read_text())
                control = f"/var/lib/fortgym-m1b/evidence/{batch_id}/control"
                batch_root = f"/var/lib/fortgym-m1b/evidence/{batch_id}"
                final_request_id = bindings["final_request_id"]
                outcome = {
                    "schema": "fortgym.m1b-host-runner-outcome/v1",
                    "batch_id": batch_id,
                    "decision": os.environ.get("FAKE_RUNNER_DECISION", "GO"),
                    "real_runtime_attempts_started": 26,
                    "real_runtime_attempts_completed": 26,
                    "non_runtime_attempts_started": 1,
                    "non_runtime_attempts_completed": 1,
                    "gate_results_path": f"{control}/gate-results.json",
                    "decision_path": f"{control}/decision.json",
                    "evidence_manifest_path": f"{control}/evidence-manifest.json",
                    "seal_path": f"{control}/seal.json",
                    "post_seal_cleanup_path": (
                        f"{batch_root}/post-seal-host-cleanup.json"
                    ),
                    "post_seal_cleanup_sha256": bindings[
                        "post_seal_cleanup_sha256"
                    ],
                    "broker_attestation_path": (
                        "/var/lib/fortgym-m1b-root-evidence/batches/"
                        f"{batch_id}/broker-attestation.json"
                    ),
                    "broker_attestation_sha256": bindings[
                        "broker_attestation_sha256"
                    ],
                    "broker_attestation_reference_path": (
                        f"{batch_root}/root-broker-attestation-reference.json"
                    ),
                    "broker_attestation_reference_sha256": bindings[
                        "broker_attestation_reference_sha256"
                    ],
                    "broker_attestation_receipt_path": (
                        f"{batch_root}/broker-client/CLEANUP/"
                        f"{final_request_id}.json"
                    ),
                    "broker_attestation_receipt_sha256": bindings[
                        "broker_attestation_receipt_sha256"
                    ],
                }
                if os.environ.get("FAKE_RUNNER_OUTCOME_EXTRA") == "1":
                    outcome["unexpected"] = True
                if os.environ.get("FAKE_RUNNER_BAD_EXPORT_PATH") == "1":
                    outcome["broker_attestation_path"] = "/tmp/forged.json"
                print(json.dumps(outcome))
                raise SystemExit(int(os.environ.get("FAKE_RUNNER_RC", "0")))
            raise SystemExit(0)

        if command == "scp":
            if os.environ.get("FAKE_DROP_MUX_BEFORE_SCP") == "1":
                control_path = mux_slave_control_path()
                if control_path is not None:
                    control_path.unlink(missing_ok=True)
            refuse_or_record_direct_fallback()
            raise SystemExit(0)

        if command == "sleep":
            raise SystemExit(0)

        if command != "gcloud":
            raise SystemExit(f"unexpected fake command: {command}")

        instance_marker = state / "instance-created"
        disk_marker = state / "disk-created"
        operation_path = state / "create-operation.json"

        def requested_instance_name():
            if (state / "instance-name").exists():
                return (state / "instance-name").read_text()
            operation_filter = next(
                item for item in args if item.startswith("--filter=operationType=insert")
            )
            return operation_filter.rsplit("instances/", 1)[1]

        def create_operation(
            status="RUNNING",
            *,
            error=False,
            operation_name="operation-fortgym-m1b-insert",
        ):
            instance_name = requested_instance_name()
            payload = {
                "name": operation_name,
                "operationType": "insert",
                "targetLink": (
                    "https://www.googleapis.com/compute/v1/projects/"
                    "scrolller-307201/zones/us-central1-a/instances/"
                    + instance_name
                ),
                "zone": "projects/scrolller-307201/zones/us-central1-a",
                "status": status,
            }
            if error:
                payload["error"] = {"errors": [{"code": "TEST_ONLY"}]}
            return payload

        if args[:2] == ["config", "get-value"]:
            property_name = args[2]
            if property_name == "auth/impersonate_service_account":
                print(os.environ.get("FAKE_GCLOUD_IMPERSONATION", "(unset)"))
            elif property_name == "auth/credential_file_override":
                print(
                    os.environ.get(
                        "FAKE_GCLOUD_CREDENTIAL_FILE_OVERRIDE", "(unset)"
                    )
                )
            elif property_name == "auth/access_token_file":
                print(os.environ.get("FAKE_GCLOUD_ACCESS_TOKEN_FILE", "(unset)"))
            elif property_name == "auth/token_host":
                print(
                    os.environ.get(
                        "FAKE_GCLOUD_TOKEN_HOST",
                        "https://oauth2.googleapis.com/token",
                    )
                )
            elif property_name == "core/universe_domain":
                print(os.environ.get("FAKE_GCLOUD_UNIVERSE_DOMAIN", "googleapis.com"))
            elif property_name == "api_endpoint_overrides/compute":
                print(os.environ.get("FAKE_GCLOUD_COMPUTE_ENDPOINT", "(unset)"))
            elif property_name == "api_endpoint_overrides/cloudresourcemanager":
                print(os.environ.get("FAKE_GCLOUD_CRM_ENDPOINT", "(unset)"))
            elif property_name == "api_endpoint_overrides/cloudbilling":
                print(os.environ.get("FAKE_GCLOUD_BILLING_ENDPOINT", "(unset)"))
            elif property_name == "auth/disable_ssl_validation":
                print(os.environ.get("FAKE_GCLOUD_DISABLE_SSL", "False"))
            elif property_name == "core/custom_ca_certs_file":
                print(os.environ.get("FAKE_GCLOUD_CUSTOM_CA", "(unset)"))
            elif property_name == "proxy/type":
                print(os.environ.get("FAKE_GCLOUD_PROXY_TYPE", "(unset)"))
            elif property_name == "proxy/address":
                print(os.environ.get("FAKE_GCLOUD_PROXY_ADDRESS", "(unset)"))
            elif property_name == "proxy/port":
                print(os.environ.get("FAKE_GCLOUD_PROXY_PORT", "(unset)"))
            else:
                raise SystemExit(f"unexpected gcloud config property: {property_name}")
            raise SystemExit(0)
        if args[:2] == ["auth", "list"]:
            print("cdossman91@gmail.com")
            raise SystemExit(0)
        if args[:2] == ["projects", "describe"]:
            print(json.dumps({"projectId": "scrolller-307201", "lifecycleState": "ACTIVE"}))
            raise SystemExit(0)
        if args[:3] == ["billing", "projects", "describe"]:
            print(json.dumps({"projectId": "scrolller-307201", "billingEnabled": True}))
            raise SystemExit(0)
        if args[:3] == ["compute", "zones", "describe"]:
            print(json.dumps({
                "name": "us-central1-a",
                "region": "projects/scrolller-307201/regions/us-central1",
                "status": "UP",
            }))
            raise SystemExit(0)
        if args[:3] == ["compute", "regions", "describe"]:
            e2_limit = 15 if os.environ.get("FAKE_LOW_E2_QUOTA") == "1" else 72
            print(json.dumps({
                "name": "us-central1",
                "status": "UP",
                "quotas": [
                    {"metric": "E2_CPUS", "limit": e2_limit, "usage": 0},
                    {"metric": "INSTANCES", "limit": 720, "usage": 5},
                    {"metric": "IN_USE_ADDRESSES", "limit": 69, "usage": 3},
                    {"metric": "DISKS_TOTAL_GB", "limit": 40960, "usage": 400},
                ],
            }))
            raise SystemExit(0)
        if args[:3] == ["compute", "machine-types", "describe"]:
            print(json.dumps({
                "name": "e2-standard-16",
                "guestCpus": 16,
                "memoryMb": 65536,
            }))
            raise SystemExit(0)
        if args[:4] == ["compute", "networks", "subnets", "describe"]:
            subnet = {
                "name": "default",
                "network": "projects/scrolller-307201/global/networks/default",
                "region": "projects/scrolller-307201/regions/us-central1",
                "purpose": "PRIVATE",
                "stackType": "IPV4_ONLY",
                "ipCidrRange": "10.128.0.0/20",
                "gatewayAddress": "10.128.0.1",
            }
            if os.environ.get("FAKE_SUBNET_STATE"):
                subnet["state"] = os.environ["FAKE_SUBNET_STATE"]
            print(json.dumps(subnet))
            raise SystemExit(0)
        if args[:3] == ["compute", "networks", "describe"]:
            print(json.dumps({
                "name": "default",
                "autoCreateSubnetworks": True,
                "routingConfig": {"routingMode": "REGIONAL"},
            }))
            raise SystemExit(0)
        if args[:3] == ["compute", "routes", "list"]:
            routes = [] if os.environ.get("FAKE_NO_DEFAULT_ROUTE") == "1" else [{
                "name": "default-route-internet",
                "network": "projects/scrolller-307201/global/networks/default",
                "destRange": "0.0.0.0/0",
                "nextHopGateway": (
                    "projects/scrolller-307201/global/gateways/"
                    "default-internet-gateway"
                ),
                "priority": 1000,
            }]
            print(json.dumps(routes))
            raise SystemExit(0)
        if args[:3] == ["compute", "firewall-rules", "describe"]:
            allowed = (
                []
                if os.environ.get("FAKE_SSH_INGRESS_BLOCKED") == "1"
                else [{"IPProtocol": "tcp", "ports": ["22"]}]
            )
            print(json.dumps({
                "name": "default-allow-ssh",
                "network": "projects/scrolller-307201/global/networks/default",
                "direction": "INGRESS",
                "disabled": False,
                "priority": 65534,
                "sourceRanges": ["0.0.0.0/0"],
                "allowed": allowed,
            }))
            raise SystemExit(0)
        if args[:3] == ["compute", "project-info", "describe"]:
            items = []
            if os.environ.get("FAKE_OSLOGIN_ENABLED") == "1":
                items.append({"key": "enable-oslogin", "value": "TRUE"})
            print(json.dumps({"commonInstanceMetadata": {"items": items}}))
            raise SystemExit(0)
        if args[:3] == ["compute", "images", "describe"]:
            print(json.dumps({
                "name": "debian-12-bookworm-v20260811",
                "architecture": "X86_64",
                "status": "READY",
            }))
            raise SystemExit(0)
        if args[:3] == ["compute", "operations", "describe"]:
            if not operation_path.exists():
                raise SystemExit(1)
            if (state / "late-materialize-pending").exists():
                instance_marker.write_text("created\n")
                disk_marker.write_text("created\n")
                (state / "late-materialize-pending").unlink()
            payload = create_operation(
                "DONE", error=os.environ.get("FAKE_CREATE_OPERATION_ERROR") == "1"
            )
            operation_path.write_text(json.dumps(payload))
            print(json.dumps(payload))
            raise SystemExit(0)
        if args[:3] == ["compute", "operations", "list"]:
            records = []
            if os.environ.get("FAKE_OLD_CREATE_OPERATION") == "1":
                records.append(
                    create_operation(
                        "DONE", operation_name="operation-fortgym-m1b-old-insert"
                    )
                )
            if operation_path.exists() and (state / "late-materialize-pending").exists():
                instance_marker.write_text("created\n")
                disk_marker.write_text("created\n")
                (state / "late-materialize-pending").unlink()
            if operation_path.exists():
                payload = create_operation("DONE")
                operation_path.write_text(json.dumps(payload))
                records.append(payload)
            if (
                operation_path.exists()
                and os.environ.get("FAKE_CREATE_OPERATION_LOOKUP_AMBIGUOUS") == "1"
            ):
                duplicate = dict(payload)
                duplicate["name"] = "operation-fortgym-m1b-insert-duplicate"
                records.append(duplicate)
            print(json.dumps(records))
            raise SystemExit(0)
        if args[:3] == ["compute", "instances", "create"]:
            (state / "instance-name").write_text(args[3])
            (state / "create-args.json").write_text(json.dumps(args))
            operation_path.write_text(json.dumps(create_operation()))
            if os.environ.get("FAKE_HANG_GCLOUD_CREATE_AFTER_ACCEPT") == "1":
                (state / "late-materialize-pending").write_text("1\n")
                while True:
                    time.sleep(1)
            instance_marker.write_text("created\n")
            disk_marker.write_text("created\n")
            response = [create_operation()]
            if os.environ.get("FAKE_CREATE_SUBMIT_ZERO") == "1":
                response = []
            elif os.environ.get("FAKE_CREATE_SUBMIT_MULTIPLE") == "1":
                duplicate = dict(response[0])
                duplicate["name"] = "operation-fortgym-m1b-insert-duplicate"
                response.append(duplicate)
            print(json.dumps(response))
            raise SystemExit(0)
        if args[:3] == ["compute", "instances", "delete"]:
            attempt_path = state / "delete-attempt-count"
            attempt = int(attempt_path.read_text()) + 1 if attempt_path.exists() else 1
            attempt_path.write_text(str(attempt))
            if (
                os.environ.get("FAKE_HANG_INSTANCE_DELETE_ONCE") == "1"
                and attempt == 1
            ):
                while True:
                    time.sleep(1)
            configured_failures = int(os.environ.get("FAKE_DELETE_FAILURES", "0"))
            if (
                os.environ.get("FAKE_DELETE_PERSISTENT_FAILURE") == "1"
                or attempt <= configured_failures
            ):
                if os.environ.get("FAKE_DELETE_FAILURE_ABSENT") == "1":
                    instance_marker.unlink(missing_ok=True)
                    disk_marker.unlink(missing_ok=True)
                print("transient fake delete failure", file=sys.stderr)
                raise SystemExit(1)
            instance_marker.unlink(missing_ok=True)
            if os.environ.get("FAKE_DISK_SURVIVES_INSTANCE_DELETE") != "1":
                disk_marker.unlink(missing_ok=True)
            (state / "delete-issued").write_text("1\n")
            raise SystemExit(0)
        if args[:3] == ["compute", "disks", "delete"]:
            attempt_path = state / "disk-delete-attempt-count"
            attempt = int(attempt_path.read_text()) + 1 if attempt_path.exists() else 1
            attempt_path.write_text(str(attempt))
            if (
                os.environ.get("FAKE_HANG_DISK_DELETE_ONCE") == "1"
                and attempt == 1
            ):
                while True:
                    time.sleep(1)
            configured_failures = int(
                os.environ.get("FAKE_DISK_DELETE_FAILURES", "0")
            )
            if (
                os.environ.get("FAKE_DISK_DELETE_PERSISTENT_FAILURE") == "1"
                or attempt <= configured_failures
            ):
                print("transient fake disk delete failure", file=sys.stderr)
                raise SystemExit(1)
            disk_marker.unlink(missing_ok=True)
            raise SystemExit(0)
        if args[:3] == ["compute", "instances", "describe"]:
            if not instance_marker.exists():
                raise SystemExit(1)
            if "--format=json" not in args:
                print(args[3])
                raise SystemExit(0)
            create_args = json.loads((state / "create-args.json").read_text())
            duration_flag = next(item for item in create_args if item.startswith("--max-run-duration="))
            duration = int(duration_flag.split("=", 1)[1][:-1])
            labels_flag = next(item for item in create_args if item.startswith("--labels="))
            labels = dict(item.split("=", 1) for item in labels_flag.split("=", 1)[1].split(","))
            now = datetime.datetime(2026, 9, 5, 14, tzinfo=datetime.UTC)
            print(json.dumps({
                "name": args[3],
                "machineType": "zones/us-central1-a/machineTypes/e2-standard-16",
                "scheduling": {
                    "provisioningModel": "STANDARD",
                    "instanceTerminationAction": "DELETE",
                    "maxRunDuration": {"seconds": str(duration), "nanos": 0},
                    "automaticRestart": False,
                    "onHostMaintenance": "MIGRATE",
                },
                "serviceAccounts": [],
                "tags": {},
                "deletionProtection": False,
                "labels": labels,
                "disks": [{"boot": True, "autoDelete": True}],
                "networkInterfaces": [{
                    "stackType": "IPV4_ONLY",
                    "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "natIP": "203.0.113.10"}],
                }],
                "lastStartTimestamp": now.isoformat().replace("+00:00", "Z"),
            }))
            raise SystemExit(0)
        if args[:3] == ["compute", "disks", "describe"]:
            print(json.dumps({
                "name": args[3],
                "sizeGb": "50",
                "type": "zones/us-central1-a/diskTypes/pd-balanced",
                "sourceImage": "global/images/debian-12-bookworm-v20260811",
            }))
            raise SystemExit(0)
        if args[:3] in (
            ["compute", "instances", "list"],
            ["compute", "disks", "list"],
            ["compute", "addresses", "list"],
        ):
            if instance_marker.exists() and args[:3] == [
                "compute",
                "instances",
                "list",
            ]:
                print((state / "instance-name").read_text())
                raise SystemExit(0)
            if (
                os.environ.get("FAKE_FOREIGN_DISK_RESIDUE") == "1"
                and (state / "instance-name").exists()
                and not instance_marker.exists()
                and args[:3] == ["compute", "disks", "list"]
            ):
                print("foreign-disk")
                raise SystemExit(0)
            if disk_marker.exists() and args[:3] == ["compute", "disks", "list"]:
                print((state / "instance-name").read_text())
                raise SystemExit(0)
            delay = int(os.environ.get("FAKE_CLEANUP_DELAY_POLLS", "0"))
            if delay and (state / "delete-issued").exists():
                counter_path = state / "cleanup-poll-count"
                counter = int(counter_path.read_text()) if counter_path.exists() else 0
                if args[:3] == ["compute", "instances", "list"]:
                    counter += 1
                    counter_path.write_text(str(counter))
                if (
                    counter <= delay
                    and args[:3] != ["compute", "addresses", "list"]
                ):
                    print((state / "instance-name").read_text())
            raise SystemExit(0)
        raise SystemExit(f"unexpected gcloud invocation: {args}")
        """.replace("__CURRENT_ROOT_BROKER_SHA256__", ROOT_BROKER_SHA256),
    )
    for name in ("gcloud", "scp", "sleep", "ssh", "ssh-keygen"):
        (fake_bin / name).symlink_to(dispatcher)
    return fake_bin, state


def _test_lifecycle_script(tmp_path: Path) -> Path:
    script_dir = tmp_path / "lifecycle-script"
    script_dir.mkdir()
    for name in (
        "acceptance.yaml",
        "bootstrap_live_host.sh",
        "root_broker.py",
        "run_live_acceptance.py",
        "run_gcp_live_acceptance.sh",
    ):
        shutil.copy2(SCRIPT.parent / name, script_dir / name)
    script = script_dir / SCRIPT.name
    source = script.read_text(encoding="utf-8")
    production_constant = "CLEANUP_POLL_INTERVAL_SECONDS=5"
    assert source.count(production_constant) == 1
    script.write_text(
        source.replace(production_constant, "CLEANUP_POLL_INTERVAL_SECONDS=1"),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _install_unexpired_test_clock(fake_bin: Path) -> None:
    """Pin fake-cloud cases inside the current renewed authority window."""
    _write_executable(
        fake_bin / "date",
        """
        #!/bin/sh
        if [ "$2" = "+%s" ]; then
          printf '%s\\n' 1788616800
        else
          printf '%s\\n' 2026-09-05T14:00:00Z
        fi
        """,
    )


def _run_lifecycle(
    tmp_path: Path,
    *,
    run_id: str = "0123456789ab",
    extra_env: dict[str, str] | None = None,
    extra_args: tuple[str, ...] = (),
    preexisting_ledger_records: list[dict[str, object]] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    packet, manifest_sha = _make_packet(tmp_path)
    fake_bin, state = _make_fake_commands(tmp_path)
    _install_unexpired_test_clock(fake_bin)
    test_script = _test_lifecycle_script(tmp_path)
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "ledger"
    if preexisting_ledger_records is not None:
        ledger.mkdir()
        (ledger / "2026-09-05.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in preexisting_ledger_records),
            encoding="utf-8",
        )
    env = os.environ.copy()
    packet_source = json.loads((packet / "source-manifest.json").read_text())
    bootstrap_sha = next(
        item["sha256"]
        for item in packet_source["files"]
        if item["path"] == "infra/m1b/bootstrap_live_host.sh"
    )
    env.update(
        {
            "PATH": f"{fake_bin}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_STATE_DIR": str(state),
            "FAKE_EVIDENCE_DIR": str(evidence),
            "FAKE_BOOTSTRAP_SHA": bootstrap_sha,
            "FAKE_PACKET_MANIFEST_SHA": manifest_sha,
            "FAKE_PACKET_PATH": str(packet / "PACKET.json"),
            "FAKE_SOURCE_MANIFEST_PATH": str(packet / "source-manifest.json"),
            "FAKE_SOURCE_MANIFEST_SHA": _sha256(packet / "source-manifest.json"),
            "FAKE_DOCKER_RUNTIME_MANIFEST_SHA": _sha256(
                packet / "docker-runtime-manifest.json"
            ),
            "FAKE_RUNTIME_ARCHIVE_SHA": _sha256(packet / "fortgym-df-m1a.tar.zst"),
            "FAKE_RUNTIME_ARCHIVE_SIZE": str(
                (packet / "fortgym-df-m1a.tar.zst").stat().st_size
            ),
            "CLOUDSDK_CORE_ACCOUNT": "wrong-default@example.invalid",
            "CLOUDSDK_CORE_PROJECT": "wrong-default-project",
            "CLOUDSDK_COMPUTE_ZONE": "antarctica-south1-z",
        }
    )
    env.update(extra_env or {})
    completed = subprocess.run(
        [
            str(test_script),
            "--packet-dir",
            str(packet),
            "--manifest-sha256",
            manifest_sha,
            "--evidence-dir",
            str(evidence),
            "--daily-ledger-dir",
            str(ledger),
            "--run-id",
            run_id,
            *extra_args,
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return completed, evidence, ledger, state


def _commands(state: Path) -> list[list[str]]:
    path = state / "commands.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _watchdog_records(evidence: Path) -> list[dict[str, object]]:
    path = evidence / "watchdog-events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_static_contract_pins_target_shape_and_denials() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for exact in (
        "ACCOUNT='cdossman91@gmail.com'",
        "PROJECT='scrolller-307201'",
        "ZONE='us-central1-a'",
        "IMAGE='debian-12-bookworm-v20260811'",
        "MACHINE_TYPE='e2-standard-16'",
        "PROVISIONING_MODEL='STANDARD'",
        "CLEANUP_POLL_INTERVAL_SECONDS=5",
        "BOOT_DISK_SIZE='50GB'",
        "BOOT_DISK_TYPE='pd-balanced'",
        "AUTHORITY_EXPIRY='2026-09-06T12:00:00Z'",
        f"ROOT_BROKER_SHA256='{ROOT_BROKER_SHA256}'",
        f"HOST_RUNNER_SHA256='{HOST_RUNNER_SHA256}'",
        "DAILY_CEILING_CENTS=21000",
        "MAX_AUTHORIZED_VM_COUNT=26",
        "MAX_RUN_SECONDS=28800",
        "--boot-disk-auto-delete",
        "address=,network-tier=PREMIUM,stack-type=IPV4_ONLY",
        "--no-service-account",
        "--no-scopes",
        "--no-restart-on-failure",
        "--maintenance-policy=MIGRATE",
        "--max-run-duration=",
        "--instance-termination-action=DELETE",
        "--async",
        "--format=json",
        "--delete-disks=all",
        "--private-test-mode",
        "launch_control_master_supervisor",
        "run_with_watchdog",
        "start_new_session=True",
        "os.setsid()",
        "fortgym.m1b-ssh-master-supervisor-ready/v1",
        "auth/credential_file_override",
        "auth/access_token_file",
        "auth/token_host",
        "core/universe_domain",
        "ControlMaster=no",
        "ProxyCommand=/usr/bin/false",
        "-O exit",
        "--verify-only",
    ):
        assert exact in source
    for forbidden in (
        "--image-family",
        "--tags=",
        "--preemptible",
        "--spot",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "--local-credit-source",
        "offline_integration",
        "FORTGYM_CLEANUP_POLL_INTERVAL_SECONDS",
        "gcloud config set",
        "status=ACTIVE",
    ):
        assert forbidden not in source
    assert source.count('run_with_watchdog "$label" "$timeout" "$GCLOUD_BIN"') == 1
    assert source.count('run_with_watchdog "$label" "$timeout" "$SSH_BIN"') == 1
    assert source.count('run_with_watchdog "$label" "$timeout" "$SCP_BIN"') == 1
    assert "process.wait()" not in source
    assert source.count('/bin/sleep "$seconds"') == 1
    assert re.search(r"(?m)^\s+sleep\s", source) is None
    assert " -fN" not in source


def test_two_fort_mode_is_forwarded_and_rejects_full_matrix_claim(tmp_path: Path) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path, extra_args=("--two-fort-diagnostic",),
    )
    assert completed.returncode != 0
    assert "two-fort diagnostic outcome exceeds" in completed.stderr
    runner = next(command for command in _commands(state)
                  if "/opt/fort-gym-m1a/infra/m1b/run_live_acceptance.py" in command)
    assert runner.count("--two-fort-diagnostic") == 1
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["cleanup"]["absence_verified"] is True


def test_duplicate_diagnostic_switch_refuses_before_cloud_or_reservation(tmp_path: Path) -> None:
    completed, evidence, ledger, state = _run_lifecycle(
        tmp_path, extra_args=("--two-fort-diagnostic", "--two-fort-diagnostic"),
    )
    assert completed.returncode == 64
    assert not evidence.exists()
    assert not ledger.exists()
    assert _commands(state) == []


def test_fake_success_uses_explicit_target_and_cleans_every_resource(
    tmp_path: Path,
) -> None:
    completed, evidence, ledger, state = _run_lifecycle(tmp_path)
    assert completed.returncode == 0, completed.stderr
    commands = _commands(state)
    create = next(
        command
        for command in commands
        if command[1:4] == ["compute", "instances", "create"]
    )
    assert create[4] == "fortgym-m1b-20260905-0123456789ab"
    for flag in (
        "--account=cdossman91@gmail.com",
        "--project=scrolller-307201",
        "--zone=us-central1-a",
        "--machine-type=e2-standard-16",
        "--provisioning-model=STANDARD",
        "--image=debian-12-bookworm-v20260811",
        "--image-project=debian-cloud",
        "--boot-disk-size=50GB",
        "--boot-disk-type=pd-balanced",
        "--boot-disk-auto-delete",
        "--network-interface=network=default,address=,network-tier=PREMIUM,stack-type=IPV4_ONLY",
        "--no-service-account",
        "--no-scopes",
        "--no-restart-on-failure",
        "--maintenance-policy=MIGRATE",
        "--instance-termination-action=DELETE",
    ):
        assert flag in create
    duration_flag = next(
        item for item in create if item.startswith("--max-run-duration=")
    )
    assert (
        0
        < int(duration_flag.removeprefix("--max-run-duration=").removesuffix("s"))
        <= 28800
    )
    assert not any(item.startswith("--tags") for item in create)
    delete = next(
        command
        for command in commands
        if command[1:4] == ["compute", "instances", "delete"]
    )
    assert "--delete-disks=all" in delete
    assert "--account=cdossman91@gmail.com" in delete
    assert "--project=scrolller-307201" in delete
    assert "--zone=us-central1-a" in delete
    assert (
        evidence / "retrieved/fortgym-m1b/evidence/m1b-live-20260905-0123456789ab/"
        "control/decision.json"
    ).is_file()
    assert (evidence / "retrieved/fortgym-m1b-root-evidence/bootstrap.json").is_file()
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["cleanup"]["absence_verified"] is True
    assert receipt["execution"]["sealed_host_outcome_verified"] is True
    assert receipt["execution"]["post_seal_host_cleanup_verified"] is True
    assert receipt["execution"]["root_broker_attestation_verified"] is True
    assert receipt["authority"]["reserved_worst_case_cents"] == 800
    assert receipt["authority"]["paid_model_provider_calls"] == 0
    assert receipt["authority"]["paid_model_provider_cost_usd"] == 0
    assert receipt["authority"]["gcp_cli_call_attempts"] > 0
    assert "provider_calls" not in receipt["authority"]
    assert "provider_cost_usd" not in receipt["authority"]
    assert receipt["control_transport"] == {
        "post_guard_new_tcp_connections_authorized": False,
        "single_ssh_control_master_closed": True,
        "single_ssh_control_master_started": True,
        "supervisor_child_group_and_socket_absence_verified": True,
        "unresolved_supervisor_process_group_id": None,
        "ephemeral_temp_directory_absence_verified": True,
    }
    assert receipt["local_artifacts_sha256"]["remote-evidence.tar"] == _sha256(
        evidence / "remote-evidence.tar"
    )
    host_cleanup = json.loads(
        (evidence / "post-seal-host-cleanup-verified.json").read_text()
    )
    assert host_cleanup["schema"] == (
        "fortgym.m1b-post-seal-host-cleanup-verification/v1"
    )
    assert host_cleanup["absence_verified"] == {
        "container": True,
        "process": True,
        "workspace": True,
    }
    assert receipt["local_artifacts_sha256"][
        "post-seal-host-cleanup-verified.json"
    ] == _sha256(evidence / "post-seal-host-cleanup-verified.json")
    sealed_outcome = json.loads(
        (evidence / "sealed-host-outcome-verified.json").read_text()
    )
    assert sealed_outcome["schema"] == (
        "fortgym.m1b-sealed-host-outcome-verification/v1"
    )
    assert sealed_outcome["gate_ids"] == [gate.gate_id for gate in FROZEN_GATE_PLAN]
    assert sealed_outcome["real_runtime_attempts_completed"] == 26
    assert sealed_outcome["non_runtime_attempts_completed"] == 1
    assert receipt["local_artifacts_sha256"][
        "sealed-host-outcome-verified.json"
    ] == _sha256(evidence / "sealed-host-outcome-verified.json")
    root_export = json.loads(
        (evidence / "root-broker-attestation-verified.json").read_text()
    )
    assert root_export["schema"] == (
        "fortgym.m1b-root-broker-attestation-verification/v1"
    )
    assert root_export["root_claim_count"] == 6
    assert root_export["root_grant_count"] == 6
    assert root_export["root_receipt_count"] == 6
    assert root_export["prior_public_receipt_count"] == 5
    assert receipt["local_artifacts_sha256"][
        "root-broker-attestation-verified.json"
    ] == _sha256(evidence / "root-broker-attestation-verified.json")
    assert (
        evidence / f"retrieved/fortgym-m1b/broker/receipts/{'6' * 64}.json"
    ).is_file()
    assert receipt["m1b_outcome"] == {
        "decision": "GO",
        "distinct_from_lifecycle_status": True,
        "is_go": True,
    }
    network_proof = json.loads((evidence / "gcp-network-preflight.json").read_text())
    assert network_proof["default_ipv4_route_verified"] is True
    assert network_proof["untagged_tcp_22_ingress_verified"] is True
    assert network_proof["project_oslogin_enabled"] is False
    config_proof = json.loads(
        (evidence / "gcp-effective-config-safety.json").read_text()
    )
    assert config_proof == {
        "schema": "fortgym.m1b-gcloud-effective-config-safety/v1",
        "oauth_token_host": "https://oauth2.googleapis.com/token",
        "universe_domain": "googleapis.com",
        "impersonation_unset": True,
        "credential_file_override_unset": True,
        "access_token_file_unset": True,
        "api_endpoint_overrides_unset": {
            "compute": True,
            "cloudresourcemanager": True,
            "cloudbilling": True,
        },
        "tls_validation_enabled": True,
        "custom_ca_certs_file_unset": True,
        "proxy_configuration_unset": True,
    }
    receipt_hash, name = (evidence / "lifecycle-receipt.sha256").read_text().split()
    assert name == "lifecycle-receipt.json"
    assert receipt_hash == _sha256(evidence / name)
    ledger_records = [
        json.loads(line)
        for line in (ledger / "2026-09-05.jsonl").read_text().splitlines()
    ]
    assert ledger_records[-1]["reserved_after_cents"] == 800
    assert ledger_records[-1]["reservation_released"] is False
    command_shapes = {
        tuple(command[1:3]) for command in commands if command[0] == "gcloud"
    }
    assert {
        ("auth", "list"),
        ("projects", "describe"),
        ("billing", "projects"),
        ("compute", "zones"),
        ("compute", "regions"),
        ("compute", "machine-types"),
        ("compute", "networks"),
        ("compute", "routes"),
        ("compute", "firewall-rules"),
        ("compute", "project-info"),
        ("compute", "images"),
        ("compute", "instances"),
        ("compute", "disks"),
        ("compute", "addresses"),
    } <= command_shapes
    ssh_commands = [command for command in commands if command[0] == "ssh"]
    master_index = next(
        index for index, command in enumerate(ssh_commands) if "-M" in command
    )
    master = ssh_commands[master_index]
    assert "-N" in master
    assert "-fN" not in master
    assert not any(item.startswith("ControlPersist=") for item in master)
    for command in ssh_commands[master_index + 1 :]:
        if "-O" in command:
            assert command[command.index("-O") + 1] in {"check", "exit"}
        else:
            assert "ControlMaster=no" in command
            assert any(item.startswith("ControlPath=") for item in command)
            assert "ProxyCommand=/usr/bin/false" in command
    scp_commands = [command for command in commands if command[0] == "scp"]
    assert scp_commands
    assert all("ControlMaster=no" in command for command in scp_commands)
    assert all("ProxyCommand=/usr/bin/false" in command for command in scp_commands)
    assert any("sudo /bin/tar" in " ".join(command) for command in ssh_commands)
    runner_index = next(
        index
        for index, command in enumerate(ssh_commands)
        if "run_live_acceptance.py" in " ".join(command)
    )
    post_run_guard_index = next(
        index
        for index, command in enumerate(ssh_commands)
        if "--verify-only" in command
    )
    evidence_index = next(
        index
        for index, command in enumerate(ssh_commands)
        if "sudo /bin/tar" in " ".join(command)
    )
    assert runner_index < post_run_guard_index < evidence_index
    assert not any(
        "/tmp/fortgym-m1b-evidence" in " ".join(command) for command in commands
    )
    watchdog_records = [
        json.loads(line)
        for line in (evidence / "watchdog-events.jsonl").read_text().splitlines()
    ]
    watchdog_labels = {record["label"] for record in watchdog_records}
    assert {
        "gcloud-read",
        "gcloud-instances-create",
        "gcloud-instances-delete",
        "ssh-master",
        "ssh-mux-check",
        "scp-packet",
        "ssh-bootstrap",
        "ssh-runner",
        "ssh-evidence",
        "ssh-mux-exit",
    } <= watchdog_labels
    assert all(record["reaped"] is True for record in watchdog_records)
    assert not any(record["timed_out"] for record in watchdog_records)
    assert (state / "mux-master-reaped").is_file()


def test_control_master_retries_only_after_failed_attempt_is_fully_reaped(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="55a000000001",
        extra_env={"FAKE_MUX_FAIL_ATTEMPTS": "2"},
    )
    assert completed.returncode == 0, completed.stderr
    masters = [
        command
        for command in _commands(state)
        if command[0] == "ssh" and "-M" in command and "-N" in command
    ]
    assert len(masters) == 3
    events = [
        json.loads(line)
        for line in (evidence / "lifecycle-events.jsonl").read_text().splitlines()
    ]
    absence = [
        event
        for event in events
        if event["event"] == "ssh_control_master_local_absence_verified"
    ]
    assert len(absence) == 3
    assert all(
        "supervisor=true child_process_group=true control_path=true" in event["detail"]
        for event in absence
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["cleanup"]["absence_verified"] is True


@pytest.mark.parametrize(
    ("shape_env", "expected_records"),
    [
        ("FAKE_CREATE_SUBMIT_ZERO", 0),
        ("FAKE_CREATE_SUBMIT_MULTIPLE", 2),
    ],
)
def test_async_create_submit_requires_exactly_one_operation_record(
    tmp_path: Path,
    shape_env: str,
    expected_records: int,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id=f"a{expected_records:011x}",
        extra_env={shape_env: "1"},
    )
    assert completed.returncode != 0
    assert "instance create returned no exact operation identity" in completed.stderr
    submit = json.loads((evidence / "create-operation-submit.json").read_text())
    assert isinstance(submit, list)
    assert len(submit) == expected_records
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["execution"]["create_succeeded"] is False
    assert receipt["execution"]["create_operation_captured"] is True
    assert receipt["execution"]["create_operation_terminal"] is True
    assert receipt["cleanup"]["absence_verified"] is True
    assert not (state / "instance-created").exists()
    assert not (state / "disk-created").exists()


def test_malformed_watchdog_evidence_prevents_receipt_pair_and_complete_signal(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, _state = _run_lifecycle(
        tmp_path,
        run_id="bad0bad0bad0",
        extra_env={"FAKE_MALFORM_WATCHDOG_EVIDENCE": "1"},
    )
    assert completed.returncode != 0
    assert "complete and residue-free" not in completed.stdout
    assert "failed or cleanup proof is incomplete" in completed.stderr
    assert not (evidence / "lifecycle-receipt.json").exists()
    assert not (evidence / "lifecycle-receipt.sha256").exists()


def test_failure_after_receipt_json_publication_removes_complete_pair(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, _state = _run_lifecycle(
        tmp_path,
        run_id="bad0bad0bad1",
        extra_env={"FAKE_RECEIPT_FAIL_AFTER_JSON": "1"},
    )
    assert completed.returncode != 0
    assert "forced failure after lifecycle receipt publication" in completed.stderr
    assert "complete and residue-free" not in completed.stdout
    assert "failed or cleanup proof is incomplete" in completed.stderr
    assert not (evidence / "lifecycle-receipt.json").exists()
    assert not (evidence / "lifecycle-receipt.sha256").exists()
    assert not list(evidence.glob(".lifecycle-receipt*"))


def test_wrong_gcloud_defaults_never_replace_explicit_target(tmp_path: Path) -> None:
    completed, _evidence, _ledger, state = _run_lifecycle(tmp_path)
    assert completed.returncode == 0, completed.stderr
    commands = [command for command in _commands(state) if command[0] == "gcloud"]
    for command in commands:
        assert "--account=cdossman91@gmail.com" in command
        if command[1:3] == ["auth", "list"]:
            continue
        expected_project = (
            "--project=debian-cloud"
            if command[1:3] == ["compute", "images"]
            else "--project=scrolller-307201"
        )
        assert expected_project in command
        assert not any(
            "wrong-default" in item or "antarctica" in item for item in command
        )
    target_commands = [
        command
        for command in commands
        if command[1:3] == ["compute", "instances"]
        or command[1:3] == ["compute", "disks"]
    ]
    assert target_commands
    for command in target_commands:
        assert "--account=cdossman91@gmail.com" in command
        assert "--project=scrolller-307201" in command
        assert any(
            item in command
            for item in ("--zone=us-central1-a", "--zones=us-central1-a")
        )
        assert not any(
            "wrong-default" in item or "antarctica" in item for item in command
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", "/tmp/forbidden-creds.json"),
        ("CLOUDSDK_PYTHON", "/tmp/forbidden-python"),
        ("HTTPS_PROXY", "http://127.0.0.1:9999"),
        ("ALL_PROXY", "socks5://127.0.0.1:9999"),
    ],
)
def test_redirecting_command_environment_refuses_before_cloud_or_spend(
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    completed, evidence, ledger, state = _run_lifecycle(
        tmp_path, extra_env={name: value}
    )
    assert completed.returncode != 0
    assert f"redirecting command environment is forbidden: {name}" in completed.stderr
    assert _commands(state) == []
    assert not list(ledger.glob("*.jsonl"))
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["identity_environment_verified"] is False
    assert receipt["authority"]["gcp_cli_call_attempts"] == 0
    assert (
        receipt["control_transport"][
            "supervisor_child_group_and_socket_absence_verified"
        ]
        is True
    )


@pytest.mark.parametrize(
    "extra_env",
    [
        {"FAKE_GCLOUD_IMPERSONATION": "attacker@example.invalid"},
        {"FAKE_GCLOUD_CREDENTIAL_FILE_OVERRIDE": "/tmp/forged.json"},
        {"FAKE_GCLOUD_ACCESS_TOKEN_FILE": "/tmp/forged-token"},
        {"FAKE_GCLOUD_TOKEN_HOST": "https://attacker.invalid/token"},
        {"FAKE_GCLOUD_UNIVERSE_DOMAIN": "attacker.invalid"},
        {"FAKE_GCLOUD_COMPUTE_ENDPOINT": "https://attacker.invalid/compute"},
        {"FAKE_GCLOUD_CRM_ENDPOINT": "https://attacker.invalid/crm"},
        {"FAKE_GCLOUD_BILLING_ENDPOINT": "https://attacker.invalid/billing"},
        {"FAKE_GCLOUD_DISABLE_SSL": "True"},
        {"FAKE_GCLOUD_CUSTOM_CA": "/tmp/attacker-ca.pem"},
        {"FAKE_GCLOUD_PROXY_TYPE": "http"},
        {"FAKE_GCLOUD_PROXY_ADDRESS": "attacker.invalid"},
        {"FAKE_GCLOUD_PROXY_PORT": "8080"},
    ],
)
def test_effective_gcloud_identity_route_or_tls_override_refuses_before_spend(
    tmp_path: Path,
    extra_env: dict[str, str],
) -> None:
    completed, evidence, ledger, state = _run_lifecycle(
        tmp_path,
        run_id="c0f100000001",
        extra_env=extra_env,
    )
    assert completed.returncode != 0
    commands = _commands(state)
    assert commands
    assert all(command[1:3] == ["config", "get-value"] for command in commands)
    assert not any(command[1:3] == ["auth", "list"] for command in commands)
    assert not any(
        command[1:4] == ["compute", "instances", "create"] for command in commands
    )
    assert not list(ledger.glob("*.jsonl"))
    assert not (evidence / "gcp-effective-config-safety.json").exists()
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["identity_environment_verified"] is False
    assert receipt["authority"]["gcp_cli_call_attempts"] == len(commands)


def test_hung_gcloud_read_is_killed_reaped_and_sealed_before_spend(
    tmp_path: Path,
) -> None:
    completed, evidence, ledger, state = _run_lifecycle(
        tmp_path,
        run_id="dead00000001",
        extra_env={
            "FAKE_HANG_COMMAND_MATCH": "gcloud compute zones describe",
            "FORTGYM_WATCHDOG_CAP_LABEL": "gcloud-read",
            "FORTGYM_WATCHDOG_CAP_SECONDS": "1",
        },
    )
    assert completed.returncode != 0
    assert "local watchdog timed out: gcloud-read" in completed.stderr
    assert not list(ledger.glob("*.jsonl"))
    assert not any(
        command[1:4] == ["compute", "instances", "create"]
        for command in _commands(state)
    )
    timed_out = [
        record
        for record in _watchdog_records(evidence)
        if record["label"] == "gcloud-read" and record["timed_out"] is True
    ]
    assert len(timed_out) == 1
    assert timed_out[0]["term_sent"] is True
    assert timed_out[0]["reaped"] is True
    assert timed_out[0]["returncode"] == 124
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["cleanup"]["delete_attempted"] is False


def test_timed_out_create_recovers_unique_new_operation_then_deletes_late_instance(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="c0de00000001",
        extra_env={
            "FAKE_HANG_GCLOUD_CREATE_AFTER_ACCEPT": "1",
            "FAKE_OLD_CREATE_OPERATION": "1",
            "FORTGYM_WATCHDOG_CAP_LABEL": "gcloud-instances-create",
            "FORTGYM_WATCHDOG_CAP_SECONDS": "1",
        },
    )
    assert completed.returncode != 0
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["create_attempted"] is True
    assert receipt["execution"]["create_succeeded"] is False
    assert receipt["execution"]["create_operation_captured"] is True
    assert receipt["execution"]["create_operation_name"] == (
        "operation-fortgym-m1b-insert"
    )
    assert receipt["execution"]["create_operation_terminal"] is True
    assert receipt["execution"]["create_operation_status"] == "DONE_OK"
    assert receipt["cleanup"]["absence_verified"] is True
    assert not (state / "instance-created").exists()
    assert not (state / "disk-created").exists()
    baseline = json.loads((evidence / "create-operation-baseline.json").read_text())
    assert baseline["operation_names"] == ["operation-fortgym-m1b-old-insert"]
    events = [
        json.loads(line)
        for line in (evidence / "lifecycle-events.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "create_operation_recovered" for event in events)
    create_watchdog = next(
        record
        for record in _watchdog_records(evidence)
        if record["label"] == "gcloud-instances-create"
    )
    assert create_watchdog["timed_out"] is True
    assert create_watchdog["reaped"] is True


def test_ambiguous_new_create_operations_never_authorize_residue_free_claim(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="c0de00000003",
        extra_env={
            "FAKE_HANG_GCLOUD_CREATE_AFTER_ACCEPT": "1",
            "FAKE_CREATE_OPERATION_LOOKUP_AMBIGUOUS": "1",
            "FORTGYM_WATCHDOG_CAP_LABEL": "gcloud-instances-create",
            "FORTGYM_WATCHDOG_CAP_SECONDS": "1",
        },
    )
    assert completed.returncode != 0
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["create_operation_captured"] is False
    assert receipt["execution"]["create_operation_terminal"] is False
    assert receipt["execution"]["create_operation_status"] == "lookup-ambiguous"
    assert receipt["cleanup"]["absence_verified"] is False
    assert any(
        command[1:4] == ["compute", "instances", "delete"]
        for command in _commands(state)
    )


@pytest.mark.parametrize("diagnostic_args", [(), ("--two-fort-diagnostic",)])
def test_expired_authority_refuses_before_any_cloud_command(
    tmp_path: Path, diagnostic_args: tuple[str, ...]
) -> None:
    packet, manifest_sha = _make_packet(tmp_path)
    fake_bin, state = _make_fake_commands(tmp_path)
    _write_executable(
        fake_bin / "date",
        """
        #!/bin/sh
        if [ "$3" = "+%s" ] || [ "$2" = "+%s" ]; then
          printf '%s\\n' 1788696000
        else
          printf '%s\\n' 2026-09-06T12:00:00Z
        fi
        """,
    )
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "ledger"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_STATE_DIR": str(state),
            "FAKE_BOOTSTRAP_SHA": _sha256(BOOTSTRAP),
        }
    )
    completed = subprocess.run(
        [
            str(SCRIPT),
            "--packet-dir",
            str(packet),
            "--manifest-sha256",
            manifest_sha,
            "--evidence-dir",
            str(evidence),
            "--daily-ledger-dir",
            str(ledger),
            "--run-id",
            "abcdef012345",
            *diagnostic_args,
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode != 0
    assert "expired or too close" in completed.stderr
    assert not any(command[0] == "gcloud" for command in _commands(state))
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["create_attempted"] is False
    assert receipt["authority"]["reserved_worst_case_cents"] == 0


def test_authorized_vm_count_refuses_before_create(tmp_path: Path) -> None:
    packet, manifest_sha = _make_packet(tmp_path)
    fake_bin, state = _make_fake_commands(tmp_path)
    _install_unexpired_test_clock(fake_bin)
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    prior_id = "000000000000"
    entry = {
        "schema": "fortgym.m1b-cost-reservation/v1",
        "authorized_local_date": "2026-09-05",
        "timezone": "America/New_York",
        "run_id": prior_id,
        "instance_name": f"fortgym-m1b-20260905-{prior_id}",
        "packet_manifest_sha256": "a" * 64,
        "reserved_before_cents": 0,
        "reserved_worst_case_cents": 800,
        "reserved_after_cents": 800,
        "daily_ceiling_cents": 21000,
        "reservation_released": False,
    }
    entries = []
    for index in range(26):
        previous_id = f"{index:012x}"
        entries.append({
            **entry,
            "run_id": previous_id,
            "instance_name": f"fortgym-m1b-20260905-{previous_id}",
            "reserved_before_cents": index * 800,
            "reserved_after_cents": (index + 1) * 800,
        })
    (ledger / "2026-09-05.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in entries), encoding="utf-8"
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_STATE_DIR": str(state),
            "FAKE_BOOTSTRAP_SHA": _sha256(BOOTSTRAP),
        }
    )
    completed = subprocess.run(
        [
            str(SCRIPT),
            "--packet-dir",
            str(packet),
            "--manifest-sha256",
            manifest_sha,
            "--evidence-dir",
            str(evidence),
            "--daily-ledger-dir",
            str(ledger),
            "--run-id",
            "fedcba987654",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode != 0
    assert "authorized VM count refusal" in completed.stderr
    assert not any(
        command[1:4] == ["compute", "instances", "create"]
        for command in _commands(state)
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["create_attempted"] is False


def test_continuation_carries_prior_reservation_into_next_attempt(tmp_path: Path) -> None:
    previous = [
        {
            "schema": "fortgym.m1b-cost-reservation/v1",
            "authorized_local_date": "2026-09-05",
            "timezone": "America/New_York",
            "run_id": f"{index:012x}",
            "instance_name": f"fortgym-m1b-20260905-{index:012x}",
            "packet_manifest_sha256": "a" * 64,
            "reserved_before_cents": index * 800,
            "reserved_worst_case_cents": 800,
            "reserved_after_cents": (index + 1) * 800,
            "daily_ceiling_cents": 21000,
            "reservation_released": False,
        }
        for index in range(1)
    ]
    completed, _evidence, ledger, _state = _run_lifecycle(
        tmp_path, preexisting_ledger_records=previous
    )
    assert completed.returncode == 0, completed.stderr
    records = [json.loads(line) for line in (ledger / "2026-09-05.jsonl").read_text().splitlines()]
    assert records[:-1] == previous
    assert records[-1]["reserved_before_cents"] == 800
    assert records[-1]["reserved_after_cents"] == 1600
    assert 4000 + records[-1]["reserved_after_cents"] <= 25000


@pytest.mark.parametrize("legacy_ceiling", (10000, 20000, 30000))
def test_daily_ledger_rejects_legacy_ceiling_under_one_vm_renewal(
    tmp_path: Path,
    legacy_ceiling: int,
) -> None:
    prior_id = "000000000000"
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="fee100000002",
        preexisting_ledger_records=[
            {
                "schema": "fortgym.m1b-cost-reservation/v1",
                "authorized_local_date": "2026-09-05",
                "timezone": "America/New_York",
                "run_id": prior_id,
                "instance_name": f"fortgym-m1b-20260905-{prior_id}",
                "packet_manifest_sha256": "a" * 64,
                "reserved_before_cents": 0,
                "reserved_worst_case_cents": 800,
                "reserved_after_cents": 800,
                "daily_ceiling_cents": legacy_ceiling,
                "reservation_released": False,
            }
        ],
    )
    assert completed.returncode != 0
    assert "inconsistent reservation" in completed.stderr
    assert not any(
        command[1:4] == ["compute", "instances", "create"]
        for command in _commands(state)
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["create_attempted"] is False


def test_insufficient_quota_refuses_before_cost_reservation_or_create(
    tmp_path: Path,
) -> None:
    completed, evidence, ledger, state = _run_lifecycle(
        tmp_path,
        run_id="eeeeeeeeeeee",
        extra_env={"FAKE_LOW_E2_QUOTA": "1"},
    )
    assert completed.returncode != 0
    assert "insufficient E2_CPUS quota" in completed.stderr
    assert not any(
        command[1:4] == ["compute", "instances", "create"]
        for command in _commands(state)
    )
    assert not (ledger / "2026-09-05.jsonl").exists()
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["create_attempted"] is False


@pytest.mark.parametrize(
    ("environment", "message"),
    (
        ({"FAKE_NO_DEFAULT_ROUTE": "1"}, "IPv4 internet route"),
        ({"FAKE_SUBNET_STATE": "DRAINING"}, "subnet contract"),
        ({"FAKE_SSH_INGRESS_BLOCKED": "1"}, "TCP/22 ingress"),
        ({"FAKE_OSLOGIN_ENABLED": "1"}, "enables enable-oslogin"),
    ),
)
def test_network_and_oslogin_preflight_fail_closed_before_spend(
    tmp_path: Path,
    environment: dict[str, str],
    message: str,
) -> None:
    completed, evidence, ledger, state = _run_lifecycle(
        tmp_path,
        run_id="e0e0e0e0e0e0",
        extra_env=environment,
    )
    assert completed.returncode != 0
    assert message in completed.stderr
    assert not (ledger / "2026-09-05.jsonl").exists()
    assert not any(
        command[1:4] == ["compute", "instances", "create"]
        for command in _commands(state)
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["create_attempted"] is False


def test_post_create_failure_still_deletes_and_proves_absence(tmp_path: Path) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="deadbeefcafe",
        extra_env={"FAKE_SSH_FAIL_MATCH": "/bin/bash /tmp/fortgym-m1b-bootstrap"},
    )
    assert completed.returncode != 0
    commands = _commands(state)
    assert any(
        command[1:4] == ["compute", "instances", "create"] for command in commands
    )
    assert any(
        command[1:4] == ["compute", "instances", "delete"] for command in commands
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["last_stage"] == "host-bootstrap"
    assert receipt["execution"]["create_succeeded"] is True
    assert receipt["execution"]["bootstrap_succeeded"] is False
    assert receipt["cleanup"]["absence_verified"] is True


def test_dead_mux_socket_cannot_fall_back_to_a_second_tcp_connection(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="fa11ba000001",
        extra_env={"FAKE_DROP_MUX_BEFORE_SCP": "1"},
    )
    assert completed.returncode != 0
    assert not (state / "direct-network-fallback-attempted").exists()
    scp = next(command for command in _commands(state) if command[0] == "scp")
    assert "ProxyCommand=/usr/bin/false" in scp
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["bootstrap_succeeded"] is False
    assert receipt["cleanup"]["absence_verified"] is True
    assert (
        receipt["control_transport"][
            "supervisor_child_group_and_socket_absence_verified"
        ]
        is True
    )


def test_hung_remote_stage_is_killed_and_cleanup_still_runs(tmp_path: Path) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="bad500000001",
        extra_env={
            "FAKE_HANG_COMMAND_MATCH": (
                "/usr/bin/sha256sum -- /tmp/fortgym-m1b-bootstrap"
            ),
            "FORTGYM_WATCHDOG_CAP_LABEL": "ssh-bootstrap-digest",
            "FORTGYM_WATCHDOG_CAP_SECONDS": "1",
        },
    )
    assert completed.returncode != 0
    timeout_record = next(
        record
        for record in _watchdog_records(evidence)
        if record["label"] == "ssh-bootstrap-digest"
    )
    assert timeout_record["timed_out"] is True
    assert timeout_record["reaped"] is True
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["cleanup"]["absence_verified"] is True
    assert any(
        command[1:4] == ["compute", "instances", "delete"]
        for command in _commands(state)
    )


def test_hung_mux_close_and_term_ignoring_master_are_force_reaped(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="c105e0000001",
        extra_env={
            "FAKE_HANG_MUX_CLOSE": "1",
            "FAKE_MUX_IGNORE_TERM": "1",
            "FORTGYM_WATCHDOG_CAP_LABEL": "ssh-mux-exit",
            "FORTGYM_WATCHDOG_CAP_SECONDS": "1",
        },
    )
    assert completed.returncode != 0
    records = _watchdog_records(evidence)
    mux_exit = next(record for record in records if record["label"] == "ssh-mux-exit")
    master = next(record for record in records if record["label"] == "ssh-master")
    assert mux_exit["timed_out"] is True
    assert mux_exit["reaped"] is True
    assert master["term_sent"] is True
    assert master["kill_sent"] is True
    assert master["reaped"] is True
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["control_transport"]["single_ssh_control_master_closed"] is False
    assert (
        receipt["control_transport"][
            "supervisor_child_group_and_socket_absence_verified"
        ]
        is True
    )
    assert (
        receipt["control_transport"]["unresolved_supervisor_process_group_id"] is None
    )
    assert receipt["cleanup"]["absence_verified"] is True
    assert any(
        command[1:4] == ["compute", "instances", "delete"]
        for command in _commands(state)
    )


def test_pre_ready_supervisor_hang_is_stopped_by_positive_pid_without_ssh_child(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="fee100000001",
        extra_env={"FAKE_SUPERVISOR_PRE_READY_HANG": "1"},
    )
    assert completed.returncode != 0
    assert not any(
        "-M" in command for command in _commands(state) if command[0] == "ssh"
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["control_transport"]["single_ssh_control_master_started"] is False
    assert (
        receipt["control_transport"][
            "supervisor_child_group_and_socket_absence_verified"
        ]
        is True
    )
    assert (
        receipt["control_transport"]["unresolved_supervisor_process_group_id"] is None
    )
    assert not (evidence / "control-master-local-cleanup-failure.json").exists()
    assert receipt["cleanup"]["absence_verified"] is True
    events = [
        json.loads(line)
        for line in (evidence / "lifecycle-events.jsonl").read_text().splitlines()
    ]
    absence = [
        event
        for event in events
        if event["event"] == "ssh_control_master_local_absence_verified"
    ]
    assert any("pre_ready_stopped=0" in event["detail"] for event in absence)


def test_invalid_nonroot_import_proof_blocks_guard_and_runner(tmp_path: Path) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="bad00000f00d",
        extra_env={"FAKE_BAD_BOOTSTRAP_PROOF": "1"},
    )
    assert completed.returncode != 0
    commands = _commands(state)
    assert not any(
        "activate_outer_egress_guard.sh" in " ".join(command) for command in commands
    )
    assert not any(
        "run_live_acceptance.py" in " ".join(command) for command in commands
    )
    assert any(
        command[1:4] == ["compute", "instances", "delete"] for command in commands
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["bootstrap_succeeded"] is False
    assert receipt["cleanup"]["absence_verified"] is True


def test_invalid_post_run_guard_proof_blocks_evidence_completion(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="bad900df00d1",
        extra_env={"FAKE_BAD_POST_RUN_PROOF": "1"},
    )
    assert completed.returncode != 0
    commands = _commands(state)
    assert any("--verify-only" in command for command in commands)
    assert any(
        command[1:4] == ["compute", "instances", "delete"] for command in commands
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["evidence_collected"] is False
    assert receipt["cleanup"]["absence_verified"] is True


def test_failed_post_seal_host_cleanup_proof_blocks_lifecycle_completion(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="badc1ea00001",
        extra_env={"FAKE_BAD_POST_SEAL_CLEANUP": "1"},
    )
    assert completed.returncode != 0
    assert not (evidence / "post-seal-host-cleanup-verified.json").exists()
    assert any(
        command[1:4] == ["compute", "instances", "delete"]
        for command in _commands(state)
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["post_seal_host_cleanup_verified"] is False
    assert receipt["execution"]["evidence_collected"] is False
    assert receipt["cleanup"]["absence_verified"] is True


@pytest.mark.parametrize(
    "extra_env",
    [
        {"FAKE_BAD_ROOT_ATTESTATION": "1"},
        {"FAKE_BAD_ROOT_INVENTORY": "1"},
        {"FAKE_BAD_FINAL_BROKER_RECEIPT": "1"},
        {"FAKE_BAD_DOCKER_ATTESTATION": "1"},
    ],
)
def test_root_export_or_bootstrap_attestation_tamper_fails_closed(
    tmp_path: Path,
    extra_env: dict[str, str],
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="badb20ce0001",
        extra_env=extra_env,
    )
    assert completed.returncode != 0
    assert not (evidence / "root-broker-attestation-verified.json").exists()
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["sealed_host_outcome_verified"] is True
    assert receipt["execution"]["post_seal_host_cleanup_verified"] is True
    assert receipt["execution"]["root_broker_attestation_verified"] is False
    assert receipt["execution"]["evidence_collected"] is False
    assert receipt["cleanup"]["absence_verified"] is True
    assert any(
        command[1:4] == ["compute", "instances", "delete"]
        for command in _commands(state)
    )


def test_valid_incomplete_no_go_is_distinct_from_successful_lifecycle(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, _state = _run_lifecycle(
        tmp_path,
        run_id="dec1de000001",
        extra_env={
            "FAKE_RUNNER_DECISION": "INCOMPLETE_NO_GO",
            "FAKE_INCOMPLETE_PARTIAL_ROOT": "1",
        },
    )
    assert completed.returncode == 0, completed.stderr
    decision = json.loads((evidence / "m1b-decision.json").read_text())
    assert decision["m1b_decision"] == "INCOMPLETE_NO_GO"
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["m1b_outcome"]["decision"] == "INCOMPLETE_NO_GO"
    assert receipt["m1b_outcome"]["is_go"] is False
    assert receipt["execution"]["sealed_host_outcome_verified"] is True


def test_go_rejects_partial_root_broker_progression(tmp_path: Path) -> None:
    completed, evidence, _ledger, _state = _run_lifecycle(
        tmp_path,
        run_id="badc105e0001",
        extra_env={"FAKE_INCOMPLETE_PARTIAL_ROOT": "1"},
    )
    assert completed.returncode != 0
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["root_broker_attestation_verified"] is False


@pytest.mark.parametrize(
    "extra_env",
    [
        {"FAKE_SEALED_PLACEHOLDER": "1"},
        {"FAKE_SEALED_BAD_MANIFEST": "1"},
        {"FAKE_SEALED_BAD_COUNTS": "1"},
    ],
)
def test_malformed_or_placeholder_sealed_evidence_fails_closed_after_retrieval(
    tmp_path: Path,
    extra_env: dict[str, str],
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="bad5ea1ed001",
        extra_env=extra_env,
    )
    assert completed.returncode != 0
    assert not (evidence / "sealed-host-outcome-verified.json").exists()
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["sealed_host_outcome_verified"] is False
    assert receipt["execution"]["evidence_collected"] is False
    assert receipt["cleanup"]["absence_verified"] is True
    assert any(
        command[1:4] == ["compute", "instances", "delete"]
        for command in _commands(state)
    )


def test_malformed_runner_decision_fails_lifecycle_but_still_cleans_up(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, _state = _run_lifecycle(
        tmp_path,
        run_id="baddec000001",
        extra_env={"FAKE_RUNNER_DECISION": "MAYBE"},
    )
    assert completed.returncode != 0
    assert "host runner outcome is absent or malformed" in completed.stderr
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["runner_decision_recorded"] is False
    assert receipt["cleanup"]["absence_verified"] is True


@pytest.mark.parametrize(
    "extra_env",
    [
        {"FAKE_RUNNER_OUTCOME_EXTRA": "1"},
        {"FAKE_RUNNER_BAD_EXPORT_PATH": "1"},
    ],
)
def test_runner_outcome_exact_export_schema_fails_closed(
    tmp_path: Path,
    extra_env: dict[str, str],
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="bad0c7c00001",
        extra_env=extra_env,
    )
    assert completed.returncode != 0
    assert "host runner outcome is absent or malformed" in completed.stderr
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["runner_decision_recorded"] is False
    assert receipt["cleanup"]["absence_verified"] is True
    assert any(
        command[1:4] == ["compute", "instances", "delete"]
        for command in _commands(state)
    )


def test_cleanup_absence_verification_polls_bounded_eventual_consistency(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="c1ea00000003",
        extra_env={"FAKE_CLEANUP_DELAY_POLLS": "2"},
    )
    assert completed.returncode == 0, completed.stderr
    assert (state / "cleanup-poll-count").read_text() == "4"
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["cleanup"]["absence_verified"] is True
    events = [
        json.loads(line)
        for line in (evidence / "lifecycle-events.jsonl").read_text().splitlines()
    ]
    cleanup = [event for event in events if event["event"] == "cleanup_verified"]
    assert "convergence_attempt=4" in cleanup[-1]["detail"]
    assert "instance_delete_commands=3" in cleanup[-1]["detail"]


def test_transient_delete_failure_is_reissued_then_absence_proved(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="de1e7e000001",
        extra_env={"FAKE_DELETE_FAILURES": "1"},
    )
    assert completed.returncode == 0, completed.stderr
    deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "instances", "delete"]
    ]
    assert len(deletes) == 2
    for command in deletes:
        assert "--account=cdossman91@gmail.com" in command
        assert "--project=scrolller-307201" in command
        assert "--zone=us-central1-a" in command
        assert "--delete-disks=all" in command
        assert "--quiet" in command
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["cleanup"] == {
        "absence_verified": True,
        "address_residue": "none",
        "delete_attempted": True,
        "delete_command_attempts": 2,
        "delete_command_rc": 0,
        "delete_command_returncodes": [1, 0],
        "disk_delete_attempted": False,
        "disk_delete_command_attempts": 0,
        "disk_delete_command_rc": -1,
        "disk_delete_command_returncodes": [],
        "disk_residue": "none",
        "instance_residue": "none",
    }
    events = [
        json.loads(line)
        for line in (evidence / "lifecycle-events.jsonl").read_text().splitlines()
    ]
    delete_events = [event for event in events if event["event"] == "delete_attempt"]
    assert [event["detail"] for event in delete_events] == [
        "command_attempt=1 convergence_attempt=1 rc=1",
        "command_attempt=2 convergence_attempt=2 rc=0",
    ]


def test_hung_instance_delete_is_killed_then_exact_delete_is_reissued(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="de1e7e000004",
        extra_env={
            "FAKE_HANG_INSTANCE_DELETE_ONCE": "1",
            "FORTGYM_WATCHDOG_CAP_LABEL": "gcloud-instances-delete",
            "FORTGYM_WATCHDOG_CAP_SECONDS": "1",
        },
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["cleanup"]["delete_command_attempts"] == 2
    assert receipt["cleanup"]["delete_command_returncodes"] == [124, 0]
    assert receipt["cleanup"]["absence_verified"] is True
    deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "instances", "delete"]
    ]
    assert len(deletes) == 2
    timed_out = [
        record
        for record in _watchdog_records(evidence)
        if record["label"] == "gcloud-instances-delete" and record["timed_out"] is True
    ]
    assert len(timed_out) == 1
    assert timed_out[0]["reaped"] is True


def test_delete_not_found_semantics_stop_after_proved_absence(tmp_path: Path) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="de1e7e000003",
        extra_env={
            "FAKE_DELETE_FAILURES": "1",
            "FAKE_DELETE_FAILURE_ABSENT": "1",
        },
    )
    assert completed.returncode == 0, completed.stderr
    deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "instances", "delete"]
    ]
    assert len(deletes) == 1
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["cleanup"]["delete_command_attempts"] == 1
    assert receipt["cleanup"]["delete_command_returncodes"] == [1]
    assert receipt["cleanup"]["delete_command_rc"] == 1
    assert receipt["cleanup"]["absence_verified"] is True


def test_persistent_delete_failure_seals_incomplete_cleanup_evidence(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="de1e7e000002",
        extra_env={"FAKE_DELETE_PERSISTENT_FAILURE": "1"},
    )
    assert completed.returncode != 0
    deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "instances", "delete"]
    ]
    assert len(deletes) == 12
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["cleanup"] == {
        "absence_verified": False,
        "address_residue": "none",
        "delete_attempted": True,
        "delete_command_attempts": 12,
        "delete_command_rc": 1,
        "delete_command_returncodes": [1] * 12,
        "disk_delete_attempted": False,
        "disk_delete_command_attempts": 0,
        "disk_delete_command_rc": -1,
        "disk_delete_command_returncodes": [],
        "disk_residue": "fortgym-m1b-20260905-de1e7e000002",
        "instance_residue": "fortgym-m1b-20260905-de1e7e000002",
    }
    events = [
        json.loads(line)
        for line in (evidence / "lifecycle-events.jsonl").read_text().splitlines()
    ]
    assert len([event for event in events if event["event"] == "delete_attempt"]) == 12
    incomplete = [event for event in events if event["event"] == "cleanup_incomplete"]
    assert len(incomplete) == 1
    assert "fortgym-m1b-20260905-de1e7e000002" in incomplete[0]["detail"]


def test_transient_disk_only_residue_uses_exact_bounded_disk_delete(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="d15c00000001",
        extra_env={
            "FAKE_DISK_SURVIVES_INSTANCE_DELETE": "1",
            "FAKE_DISK_DELETE_FAILURES": "1",
        },
    )
    assert completed.returncode == 0, completed.stderr
    instance_deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "instances", "delete"]
    ]
    disk_deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "disks", "delete"]
    ]
    assert len(instance_deletes) == 1
    assert len(disk_deletes) == 2
    for command in disk_deletes:
        assert command[4] == "fortgym-m1b-20260905-d15c00000001"
        assert "--account=cdossman91@gmail.com" in command
        assert "--project=scrolller-307201" in command
        assert "--zone=us-central1-a" in command
        assert "--quiet" in command
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["cleanup"]["delete_command_returncodes"] == [0]
    assert receipt["cleanup"]["disk_delete_attempted"] is True
    assert receipt["cleanup"]["disk_delete_command_attempts"] == 2
    assert receipt["cleanup"]["disk_delete_command_returncodes"] == [1, 0]
    assert receipt["cleanup"]["disk_delete_command_rc"] == 0
    assert receipt["cleanup"]["absence_verified"] is True
    events = [
        json.loads(line)
        for line in (evidence / "lifecycle-events.jsonl").read_text().splitlines()
    ]
    assert [
        event["detail"] for event in events if event["event"] == "disk_delete_attempt"
    ] == [
        "command_attempt=1 convergence_attempt=2 rc=1",
        "command_attempt=2 convergence_attempt=3 rc=0",
    ]


def test_hung_disk_delete_is_killed_then_exact_disk_delete_is_reissued(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="d15c00000004",
        extra_env={
            "FAKE_DISK_SURVIVES_INSTANCE_DELETE": "1",
            "FAKE_HANG_DISK_DELETE_ONCE": "1",
            "FORTGYM_WATCHDOG_CAP_LABEL": "gcloud-disks-delete",
            "FORTGYM_WATCHDOG_CAP_SECONDS": "1",
        },
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["cleanup"]["disk_delete_command_attempts"] == 2
    assert receipt["cleanup"]["disk_delete_command_returncodes"] == [124, 0]
    assert receipt["cleanup"]["absence_verified"] is True
    disk_deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "disks", "delete"]
    ]
    assert len(disk_deletes) == 2
    timed_out = next(
        record
        for record in _watchdog_records(evidence)
        if record["label"] == "gcloud-disks-delete" and record["timed_out"] is True
    )
    assert timed_out["reaped"] is True


def test_persistent_disk_only_residue_seals_failed_cleanup_receipt(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="d15c00000002",
        extra_env={
            "FAKE_DISK_SURVIVES_INSTANCE_DELETE": "1",
            "FAKE_DISK_DELETE_PERSISTENT_FAILURE": "1",
        },
    )
    assert completed.returncode != 0
    disk_deletes = [
        command
        for command in _commands(state)
        if command[1:4] == ["compute", "disks", "delete"]
    ]
    assert len(disk_deletes) == 11
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["cleanup"]["delete_command_returncodes"] == [0]
    assert receipt["cleanup"]["disk_delete_command_attempts"] == 11
    assert receipt["cleanup"]["disk_delete_command_returncodes"] == [1] * 11
    assert receipt["cleanup"]["disk_delete_command_rc"] == 1
    assert receipt["cleanup"]["instance_residue"] == "none"
    assert receipt["cleanup"]["disk_residue"] == ("fortgym-m1b-20260905-d15c00000002")
    assert receipt["cleanup"]["absence_verified"] is False
    receipt_hash, name = (evidence / "lifecycle-receipt.sha256").read_text().split()
    assert name == "lifecycle-receipt.json"
    assert receipt_hash == _sha256(evidence / name)


def test_ambiguous_disk_residue_fails_closed_without_broad_delete(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, state = _run_lifecycle(
        tmp_path,
        run_id="d15c00000003",
        extra_env={"FAKE_FOREIGN_DISK_RESIDUE": "1"},
    )
    assert completed.returncode != 0
    assert not any(
        command[1:4] == ["compute", "disks", "delete"] for command in _commands(state)
    )
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["cleanup"]["disk_delete_attempted"] is False
    assert receipt["cleanup"]["disk_residue"] == (
        "unexpected-or-ambiguous:foreign-disk"
    )
    assert receipt["cleanup"]["absence_verified"] is False


def test_packet_digest_is_out_of_band_and_mismatch_refuses(tmp_path: Path) -> None:
    packet, _manifest_sha = _make_packet(tmp_path)
    fake_bin, state = _make_fake_commands(tmp_path)
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "ledger"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_STATE_DIR": str(state),
            "FAKE_BOOTSTRAP_SHA": _sha256(BOOTSTRAP),
        }
    )
    completed = subprocess.run(
        [
            str(SCRIPT),
            "--packet-dir",
            str(packet),
            "--manifest-sha256",
            "0" * 64,
            "--evidence-dir",
            str(evidence),
            "--daily-ledger-dir",
            str(ledger),
            "--run-id",
            "123456abcdef",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode != 0
    assert "out-of-band packet manifest digest differs" in completed.stderr
    assert not any(command[0] == "gcloud" for command in _commands(state))


def test_extra_packet_member_refuses_before_any_cloud_command(tmp_path: Path) -> None:
    packet, manifest_sha = _make_packet(tmp_path)
    (packet / "unexpected.bin").write_bytes(b"not part of the final packet\n")
    fake_bin, state = _make_fake_commands(tmp_path)
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "ledger"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_STATE_DIR": str(state),
            "FAKE_BOOTSTRAP_SHA": _sha256(BOOTSTRAP),
        }
    )
    completed = subprocess.run(
        [
            str(SCRIPT),
            "--packet-dir",
            str(packet),
            "--manifest-sha256",
            manifest_sha,
            "--evidence-dir",
            str(evidence),
            "--daily-ledger-dir",
            str(ledger),
            "--run-id",
            "123456abcdea",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode != 0
    assert not any(command[0] == "gcloud" for command in _commands(state))


@pytest.mark.parametrize("tamper", ["version", "archive_digest"])
def test_docker_runtime_packet_tamper_refuses_before_any_cloud_command(
    tmp_path: Path,
    tamper: str,
) -> None:
    packet, _old_manifest_sha = _make_packet(tmp_path)
    packet_path = packet / "PACKET.json"
    packet_record = json.loads(packet_path.read_text(encoding="utf-8"))
    docker_record = packet_record["docker_runtime"]
    if tamper == "version":
        docker_record["docker_server_version"] = "29.1.4"
        runtime_manifest = {
            key: value
            for key, value in docker_record.items()
            if key not in {"archive", "archive_sha256", "manifest", "manifest_sha256"}
        }
        manifest_path = packet / "docker-runtime-manifest.json"
        manifest_path.write_text(
            json.dumps(runtime_manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        docker_record["manifest_sha256"] = _sha256(manifest_path)
    else:
        docker_record["archive_sha256"] = "0" * 64
    packet_path.write_text(
        json.dumps(packet_record, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_sha = _refresh_packet_manifest(packet)
    fake_bin, state = _make_fake_commands(tmp_path)
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "ledger"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_STATE_DIR": str(state),
            "FAKE_BOOTSTRAP_SHA": _sha256(BOOTSTRAP),
        }
    )
    completed = subprocess.run(
        [
            str(SCRIPT),
            "--packet-dir",
            str(packet),
            "--manifest-sha256",
            manifest_sha,
            "--evidence-dir",
            str(evidence),
            "--daily-ledger-dir",
            str(ledger),
            "--run-id",
            "123456abcdeb",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode != 0
    assert "packet semantic verification failed" in completed.stderr
    assert not any(command[0] == "gcloud" for command in _commands(state))


def test_malicious_remote_evidence_tar_is_rejected_before_extraction(
    tmp_path: Path,
) -> None:
    completed, evidence, _ledger, _state = _run_lifecycle(
        tmp_path,
        run_id="badc0ffee123",
        extra_env={"FAKE_EVIDENCE_TAR_MODE": "traversal"},
    )
    assert completed.returncode != 0
    assert not (tmp_path / "outside-receipt.json").exists()
    receipt = json.loads((evidence / "lifecycle-receipt.json").read_text())
    assert receipt["execution"]["evidence_collected"] is False
    assert receipt["cleanup"]["absence_verified"] is True


@pytest.mark.parametrize(
    "argument,value",
    (
        ("--run-id", "not-a-safe-id"),
        ("--manifest-sha256", "ABCDEF" * 10 + "ABCD"),
    ),
)
def test_unsafe_identity_arguments_are_rejected(
    tmp_path: Path, argument: str, value: str
) -> None:
    packet, manifest_sha = _make_packet(tmp_path)
    evidence = tmp_path / "evidence"
    ledger = tmp_path / "ledger"
    args = [
        str(SCRIPT),
        "--packet-dir",
        str(packet),
        "--manifest-sha256",
        manifest_sha,
        "--evidence-dir",
        str(evidence),
        "--daily-ledger-dir",
        str(ledger),
        "--run-id",
        "0123456789ab",
    ]
    args[args.index(argument) + 1] = value
    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 64
    assert not evidence.exists()
