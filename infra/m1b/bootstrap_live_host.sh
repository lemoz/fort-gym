#!/bin/bash
set -euo pipefail

# One-shot bootstrap for the disposable, provider-free M1b acceptance host.
# The MANIFEST digest is deliberately supplied out of band by the controller.

export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset BASH_ENV CDPATH ENV GLOBIGNORE PYTHONHOME PYTHONPATH PYTHONOPTIMIZE
umask 077

packet_dir=""
manifest_sha256=""
packet_seen=0
manifest_seen=0
while (($#)); do
  case "$1" in
    --packet-dir)
      (($# >= 2)) || { printf 'missing --packet-dir value\n' >&2; exit 64; }
      ((packet_seen == 0)) || { printf 'duplicate --packet-dir\n' >&2; exit 64; }
      packet_dir="$2"
      packet_seen=1
      shift 2
      ;;
    --manifest-sha256)
      (($# >= 2)) || { printf 'missing --manifest-sha256 value\n' >&2; exit 64; }
      ((manifest_seen == 0)) || {
        printf 'duplicate --manifest-sha256\n' >&2
        exit 64
      }
      manifest_sha256="$2"
      manifest_seen=1
      shift 2
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 64
      ;;
  esac
done

if [[ "$EUID" -ne 0 ]]; then
  printf 'bootstrap must run as root\n' >&2
  exit 77
fi
if [[ "$(/usr/bin/uname -s)" != Linux || "$(/usr/bin/uname -m)" != x86_64 ]]; then
  printf 'bootstrap requires isolated x86_64 Linux\n' >&2
  exit 70
fi
if [[ -z "$packet_dir" || "$packet_dir" != /* || -L "$packet_dir" || ! -d "$packet_dir" ]]; then
  printf 'packet directory must be one absolute non-symlink directory\n' >&2
  exit 66
fi
if [[ ! "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'out-of-band MANIFEST.sha256 digest must be lowercase SHA-256\n' >&2
  exit 64
fi
packet_dir="$(/usr/bin/realpath -e -- "$packet_dir")"

readonly authority_expiry='2026-09-06T12:00:00Z'
readonly expected_acceptance_sha256='b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf'
readonly expected_runtime_image_id='sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c'
readonly expected_runtime_image_ref='fortgym-df:m1a-stock-0.47.05-r8'
readonly expected_source_pth_sha256='cfa04bac75c5d609673a9f4e2dcb49639bf291ffbc51b978722d7e0a03938544'
readonly source_root=/opt/fort-gym-m1a
readonly install_root=/opt/fortgym-m1b
readonly packet_stage="$install_root/packet"
readonly docker_runtime_root="$install_root/docker-runtime"
readonly state_root=/var/lib/fortgym-m1b
readonly root_evidence=/var/lib/fortgym-m1b-root-evidence
readonly venv_root="$install_root/venv"
readonly wheel_root="$install_root/wheelhouse"
readonly service_user=fortgym
readonly bootstrap_lock=/run/lock/fortgym-m1b-bootstrap.lock
readonly bootstrap_work=/run/fortgym-m1b-bootstrap

authority_expiry_epoch="$(/usr/bin/date -u -d "$authority_expiry" +%s)"
if (( $(/usr/bin/date -u +%s) >= authority_expiry_epoch )); then
  printf 'the operator infrastructure authority has expired\n' >&2
  exit 77
fi

exec 9>"$bootstrap_lock"
/usr/bin/flock -n 9 || {
  printf 'another M1b bootstrap owns the host\n' >&2
  exit 75
}

for fresh_path in "$source_root" "$install_root" "$state_root" "$root_evidence" "$bootstrap_work"; do
  if [[ -e "$fresh_path" || -L "$fresh_path" ]]; then
    printf 'refusing a non-fresh M1b host filesystem: %s\n' "$fresh_path" >&2
    exit 73
  fi
done

/usr/bin/install -d -o root -g root -m 0700 \
  "$install_root" "$packet_stage" "$docker_runtime_root" \
  "$root_evidence" "$bootstrap_work"

atomic_evidence_copy() {
  local source_path="$1"
  local evidence_name="$2"
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - "$source_path" "$root_evidence" "$evidence_name" <<'PY'
import os
import pathlib
import secrets
import stat
import sys

source = pathlib.Path(sys.argv[1])
parent = pathlib.Path(sys.argv[2])
name = sys.argv[3]
if not name or name in {".", ".."} or "/" in name or "\x00" in name:
    raise SystemExit("unsafe evidence basename")
parent_info = parent.lstat()
if (
    not stat.S_ISDIR(parent_info.st_mode)
    or parent_info.st_uid != 0
    or parent_info.st_gid != 0
    or stat.S_IMODE(parent_info.st_mode) != 0o700
):
    raise SystemExit("root evidence directory ownership or mode differs")
source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = f".{name}.{secrets.token_hex(16)}.tmp"
temporary_fd = None
try:
    if not stat.S_ISREG(os.fstat(source_fd).st_mode):
        raise SystemExit("evidence source is not regular")
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise SystemExit("immutable evidence target already exists")
    temporary_fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            break
        view = memoryview(chunk)
        while view:
            written = os.write(temporary_fd, view)
            view = view[written:]
    os.fchmod(temporary_fd, 0o600)
    os.fsync(temporary_fd)
    os.close(temporary_fd)
    temporary_fd = None
    os.link(
        temporary,
        name,
        src_dir_fd=directory_fd,
        dst_dir_fd=directory_fd,
        follow_symlinks=False,
    )
    os.unlink(temporary, dir_fd=directory_fd)
    published = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(published.st_mode) or published.st_nlink != 1:
        raise SystemExit("published evidence metadata differs")
    os.fsync(directory_fd)
finally:
    if temporary_fd is not None:
        os.close(temporary_fd)
    try:
        os.unlink(temporary, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    os.close(directory_fd)
    os.close(source_fd)
PY
}

# Bind the exact top-level packet to the digest delivered over the controller
# channel, then copy every verified byte into root-only staging. Later checks
# never reopen the caller-owned upload directory.
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - "$packet_dir" "$packet_stage" "$manifest_sha256" <<'PY'
import hashlib
import os
import pathlib
import re
import secrets
import stat
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
out_of_band = sys.argv[3]
required = {
    "docker-runtime-manifest.json",
    "MANIFEST.sha256",
    "PACKET.json",
    "fortgym-df-m1a.tar.zst",
    "fortgym-m1b-docker-runtime.tar",
    "fortgym-m1b-source.tar",
    "fortgym-m1b-wheelhouse.tar",
    "live-requirements.lock",
    "live-wheelhouse.sha256",
    "seed_tree.sha256z",
    "source-manifest.json",
}
record_re = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+)\n")
source_info = source.lstat()
destination_info = destination.lstat()
if not stat.S_ISDIR(source_info.st_mode) or source.is_symlink():
    raise SystemExit("packet source is not a safe directory")
if (
    not stat.S_ISDIR(destination_info.st_mode)
    or destination_info.st_uid != 0
    or destination_info.st_gid != 0
    or stat.S_IMODE(destination_info.st_mode) != 0o700
):
    raise SystemExit("packet staging ownership or mode differs")
entries = list(os.scandir(source))
names = {entry.name for entry in entries}
if names != required or len(entries) != len(required):
    raise SystemExit("packet top-level filename set differs")
for entry in entries:
    info = entry.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or entry.is_symlink()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise SystemExit(f"unsafe packet member: {entry.name}")

directory_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
output_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

def read_regular(name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SystemExit(f"unsafe packet member after open: {name}")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)

try:
    manifest = read_regular("MANIFEST.sha256")
    if hashlib.sha256(manifest).hexdigest() != out_of_band:
        raise SystemExit("out-of-band MANIFEST.sha256 digest differs")
    try:
        manifest_text = manifest.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SystemExit("MANIFEST.sha256 is not ASCII") from exc
    matches = record_re.findall(manifest_text)
    if "".join(f"{digest}  {name}\n" for digest, name in matches) != manifest_text:
        raise SystemExit("MANIFEST.sha256 syntax differs")
    expected_names = required - {"MANIFEST.sha256"}
    digests = {name: digest for digest, name in matches}
    if len(matches) != len(digests) or set(digests) != expected_names:
        raise SystemExit("MANIFEST.sha256 filename set differs")
    digests["MANIFEST.sha256"] = out_of_band

    for name in sorted(required, key=lambda value: value.encode("utf-8")):
        source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        temporary = f".{name}.{secrets.token_hex(16)}.tmp"
        target_fd = None
        digest = hashlib.sha256()
        try:
            before = os.fstat(source_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise SystemExit(f"unsafe packet member while copying: {name}")
            target_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=output_fd,
            )
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(target_fd, view)
                    view = view[written:]
            after = os.fstat(source_fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise SystemExit(f"packet member changed while copying: {name}")
            if digest.hexdigest() != digests[name]:
                raise SystemExit(f"packet member digest differs: {name}")
            os.fchmod(target_fd, 0o600)
            os.fsync(target_fd)
            os.close(target_fd)
            target_fd = None
            os.rename(temporary, name, src_dir_fd=output_fd, dst_dir_fd=output_fd)
        finally:
            if target_fd is not None:
                os.close(target_fd)
            os.close(source_fd)
            try:
                os.unlink(temporary, dir_fd=output_fd)
            except FileNotFoundError:
                pass
    os.fsync(output_fd)
finally:
    os.close(output_fd)
    os.close(directory_fd)
PY

packet_dir="$packet_stage"
/bin/ln -- "$packet_stage/fortgym-df-m1a.tar.zst" "$install_root/runtime-image.tar.zst"

# Verify the semantic contract and both tar streams completely before root
# extraction. Files are reconstructed below fresh roots without bulk extraction.
/usr/bin/install -d -o root -g root -m 0755 "$source_root" "$wheel_root"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$packet_dir" "$source_root" "$wheel_root" "$docker_runtime_root" \
  "$expected_acceptance_sha256" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import tarfile

packet_root = pathlib.Path(sys.argv[1])
source_root = pathlib.Path(sys.argv[2])
wheel_root = pathlib.Path(sys.argv[3])
docker_runtime_root = pathlib.Path(sys.argv[4])
expected_acceptance = sys.argv[5]
expected_authority = {
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
}
sha_re = re.compile(r"[0-9a-f]{64}")
wheel_record_re = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+\.whl)\n")

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

def read_nofollow(path: pathlib.Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink >= 1, f"unsafe file: {path.name}")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)

def safe_member_name(raw: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(raw)
    require(
        bool(raw)
        and raw == path.as_posix()
        and not path.is_absolute()
        and "." not in path.parts
        and ".." not in path.parts
        and "\\" not in raw
        and "\x00" not in raw
        and all(path.parts),
        f"unsafe tar path: {raw!r}",
    )
    return path

def open_tar(path: pathlib.Path) -> tuple[object, tarfile.TarFile]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink < 1:
        os.close(fd)
        raise SystemExit(f"unsafe tar archive: {path.name}")
    handle = os.fdopen(fd, "rb", closefd=True)
    try:
        archive = tarfile.open(fileobj=handle, mode="r:")
    except BaseException:
        handle.close()
        raise
    return handle, archive

def inspect_tar(archive_path: pathlib.Path, expected: dict[str, dict[str, object]]) -> None:
    handle, archive = open_tar(archive_path)
    try:
        members = archive.getmembers()
        names = [member.name for member in members]
        require(len(names) == len(set(names)), f"duplicate tar member in {archive_path.name}")
        require(set(names) == set(expected), f"tar filename set differs: {archive_path.name}")
        for member in members:
            safe_member_name(member.name)
            allowed_pax = not member.pax_headers or member.pax_headers == {"path": member.name}
            require(allowed_pax, f"unsafe PAX headers: {member.name}")
            require(
                member.isfile()
                and member.type in {tarfile.REGTYPE, tarfile.AREGTYPE}
                and not member.issym()
                and not member.islnk()
                and member.uid == 0
                and member.gid == 0
                and member.mtime == 0
                and member.uname == ""
                and member.gname == "",
                f"unsafe tar member type or metadata: {member.name}",
            )
            record = expected[member.name]
            require(member.size == record["size"], f"tar member size differs: {member.name}")
            require(member.mode == record["mode"], f"tar member mode differs: {member.name}")
            extracted = archive.extractfile(member)
            require(extracted is not None, f"unreadable tar member: {member.name}")
            digest = hashlib.sha256()
            observed_size = 0
            while True:
                chunk = extracted.read(1024 * 1024)
                if not chunk:
                    break
                observed_size += len(chunk)
                digest.update(chunk)
            require(observed_size == member.size, f"short tar member: {member.name}")
            require(digest.hexdigest() == record["sha256"], f"tar digest differs: {member.name}")
    finally:
        archive.close()
        handle.close()

def extract_verified_tar(
    archive_path: pathlib.Path,
    destination: pathlib.Path,
    expected: dict[str, dict[str, object]],
) -> None:
    destination_info = destination.lstat()
    require(
        stat.S_ISDIR(destination_info.st_mode)
        and destination_info.st_uid == 0
        and destination_info.st_gid == 0
        and not destination.is_symlink(),
        "extraction root ownership differs",
    )
    handle, archive = open_tar(archive_path)
    try:
        for member in archive.getmembers():
            relative = safe_member_name(member.name)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            current = destination
            for component in relative.parts[:-1]:
                current = current / component
                info = current.lstat()
                require(
                    stat.S_ISDIR(info.st_mode) and not current.is_symlink(),
                    "unsafe extraction parent",
                )
                os.chmod(current, 0o755, follow_symlinks=False)
            extracted = archive.extractfile(member)
            require(extracted is not None, f"unreadable verified member: {member.name}")
            fd = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                int(expected[member.name]["mode"]),
            )
            try:
                while True:
                    chunk = extracted.read(1024 * 1024)
                    if not chunk:
                        break
                    view = memoryview(chunk)
                    while view:
                        written = os.write(fd, view)
                        view = view[written:]
                os.fchmod(fd, int(expected[member.name]["mode"]))
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        archive.close()
        handle.close()

packet = json.loads(read_nofollow(packet_root / "PACKET.json"))
require(isinstance(packet, dict), "PACKET.json must be an object")
require(packet.get("schema") == "fortgym.m1b-live-input-packet/v1", "packet schema differs")
require(packet.get("authority") == expected_authority, "packet authority differs")
require(packet.get("acceptance_sha256") == expected_acceptance, "acceptance digest differs")
runtime_archive = packet.get("runtime_archive")
runtime_proto = packet.get("runtime_proto")
wheelhouse = packet.get("wheelhouse")
source = packet.get("source")
docker_runtime = packet.get("docker_runtime")
require(isinstance(runtime_archive, dict), "runtime archive record is absent")
require(runtime_archive.get("platform") == "linux/amd64", "runtime platform differs")
require(isinstance(runtime_proto, dict), "runtime proto record is absent")
require(
    runtime_proto.get("runtime_binding_sha256")
    == "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f",
    "runtime binding differs",
)
require(runtime_proto.get("e1_binding_changed") is False, "E1 binding mutation is forbidden")
require(isinstance(wheelhouse, dict), "wheelhouse record is absent")
require(wheelhouse.get("python") == "3.11", "wheelhouse Python differs")
require(wheelhouse.get("platform") == "linux/x86_64", "wheelhouse platform differs")
require(wheelhouse.get("network_install_required") is False, "network install is forbidden")
require(wheelhouse.get("provider_sdks_present") is False, "provider SDK wheel is forbidden")
require(isinstance(source, dict), "source record is absent")
require(source.get("archive") == "fortgym-m1b-source.tar", "source archive name differs")
require(source.get("manifest") == "source-manifest.json", "source manifest name differs")
require(source.get("extract_root") == "/opt/fort-gym-m1a", "source extraction root differs")
require(isinstance(docker_runtime, dict), "Docker runtime record is absent")
require(
    set(docker_runtime)
    == {
        "archive",
        "archive_members",
        "archive_sha256",
        "binaries",
        "containerd_snapshotter_required",
        "containerd_version",
        "distribution",
        "docker_server_version",
        "manifest",
        "manifest_sha256",
        "network_install_required",
        "package_install_order",
        "packages",
        "platform",
        "schema",
        "signed_repository",
    },
    "Docker runtime key set differs",
)
require(
    docker_runtime.get("schema") == "fortgym.m1b-docker-runtime/v1"
    and docker_runtime.get("archive") == "fortgym-m1b-docker-runtime.tar"
    and docker_runtime.get("manifest") == "docker-runtime-manifest.json"
    and docker_runtime.get("platform") == "linux/amd64"
    and docker_runtime.get("distribution") == "debian/12"
    and docker_runtime.get("docker_server_version") == "29.1.3"
    and docker_runtime.get("containerd_version") == "2.2.1"
    and docker_runtime.get("containerd_snapshotter_required") is True
    and docker_runtime.get("network_install_required") is False
    and docker_runtime.get("package_install_order")
    == ["containerd.io", "docker-ce-cli", "docker-ce"],
    "Docker runtime contract differs",
)
expected_repository = {
    "architecture": "amd64",
    "base_url": "https://download.docker.com/linux/debian",
    "component": "stable",
    "inrelease_sha256": "19916250e8c2de32f5938227de988b846c36ff0def8dabbb149592c949b80b85",
    "packages_gz_sha256": "c745da94edd1809aa74f0bf45a72b5935e649d524de6405695dbdf4d5e54d7fd",
    "release_key_fingerprint": "9DC858229FC7DD38854AE2D88D81803C0EBFCD88",
    "release_signing_fingerprint": "D3306A018370199E527AE7997EA0A9C3F273FCD8",
    "signature_verified": True,
    "suite": "bookworm",
}
require(docker_runtime.get("signed_repository") == expected_repository, "Docker repository proof differs")
expected_packages = {
    "containerd.io": (
        "2.2.1-1~debian.12~bookworm",
        "containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb",
        23371888,
        "3505acd8a8124077df5608293e933c5dfb0dac988f143019fa6efe98e79b92d5",
    ),
    "docker-ce": (
        "5:29.1.3-1~debian.12~bookworm",
        "docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb",
        21018900,
        "809c748027406afb4563bf61886e5ec0e3b5d34ff0353256ae618a2c6c5b29fc",
    ),
    "docker-ce-cli": (
        "5:29.1.3-1~debian.12~bookworm",
        "docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb",
        16294920,
        "fa4c2ad37fa4e5bc4bc5bd4098daec153e546c9ccd5419adf8f91e54f0a0e2bd",
    ),
}
packages = docker_runtime.get("packages")
require(isinstance(packages, list) and len(packages) == 3, "Docker package list differs")
package_names = set()
for item in packages:
    require(isinstance(item, dict) and set(item) == {
        "architecture", "filename", "package", "repository_path", "sha256", "size_bytes", "version"
    }, "Docker package record shape differs")
    package = item.get("package")
    require(package in expected_packages and package not in package_names, "Docker package identity differs")
    package_names.add(package)
    version, filename, size, digest = expected_packages[package]
    require(
        item == {
            "architecture": "amd64",
            "filename": filename,
            "package": package,
            "repository_path": f"dists/bookworm/pool/stable/amd64/{filename}",
            "sha256": digest,
            "size_bytes": size,
            "version": version,
        },
        f"Docker package record differs: {package}",
    )
require(package_names == set(expected_packages), "Docker package set differs")
expected_binaries = {
    "/usr/bin/containerd": ("containerd.io", 47794968, "8daa1fcfd4007b35fdc5240b2a2c57290bbe9bd4e015b945bb011819acb8f2e0"),
    "/usr/bin/containerd-shim-runc-v2": ("containerd.io", 8310616, "fef09005f009695a8a71427570efd9a4c979a2bb6f45b72c25f673aa39f6f9f2"),
    "/usr/bin/ctr": ("containerd.io", 24890808, "5cbd83cbc7d90828804bde5b10c721b9067add62979b6e45ee1abc80b26e4edb"),
    "/usr/bin/docker": ("docker-ce-cli", 43984210, "57d51e83d3673f4f40ba54c67f8b9ec75d9e3401c5f0795c5f443366eb9c85ec"),
    "/usr/bin/docker-proxy": ("docker-ce", 2831666, "4068c3ddb30f9d304101dfab6901559337611236e359da3cc8494e2a1ec98530"),
    "/usr/bin/dockerd": ("docker-ce", 94463240, "978d5d2e4f36c2904ef6787d0fd148b863a1e2556436900f8278c721b7d07127"),
    "/usr/bin/runc": ("containerd.io", 12019264, "488440797ffe0e90dcfa03537291ad6e7dfe260a0ffe7c395356db242226510e"),
    "/usr/libexec/docker/docker-init": ("docker-ce", 708456, "b831fc949adfbf8afa5c8ccef4db0dacfc92f2cc884d9fcb50382eae17c60626"),
}
binaries = docker_runtime.get("binaries")
require(isinstance(binaries, list) and len(binaries) == len(expected_binaries), "Docker binary list differs")
binary_names = set()
for item in binaries:
    require(isinstance(item, dict), "Docker binary record is not an object")
    path = item.get("path")
    require(path in expected_binaries and path not in binary_names, "Docker binary identity differs")
    binary_names.add(path)
    package, size, digest = expected_binaries[path]
    require(item == {
        "architecture": "amd64", "mode": "0755", "package": package,
        "path": path, "sha256": digest, "size_bytes": size
    }, f"Docker binary record differs: {path}")
require(binary_names == set(expected_binaries), "Docker binary set differs")
docker_manifest_bytes = read_nofollow(packet_root / "docker-runtime-manifest.json")
manifest_sha256 = docker_runtime.get("manifest_sha256")
require(
    isinstance(manifest_sha256, str)
    and sha_re.fullmatch(manifest_sha256) is not None
    and hashlib.sha256(docker_manifest_bytes).hexdigest() == manifest_sha256,
    "Docker runtime manifest digest differs",
)
docker_manifest = json.loads(docker_manifest_bytes)
linked_fields = {"archive", "archive_sha256", "manifest", "manifest_sha256"}
require(
    docker_manifest == {key: value for key, value in docker_runtime.items() if key not in linked_fields},
    "Docker runtime manifest and PACKET record differ",
)
for record, field, filename in (
    (source, "archive_sha256", "fortgym-m1b-source.tar"),
    (wheelhouse, "archive_sha256", "fortgym-m1b-wheelhouse.tar"),
    (docker_runtime, "archive_sha256", "fortgym-m1b-docker-runtime.tar"),
    (runtime_archive, "compressed_sha256", "fortgym-df-m1a.tar.zst"),
):
    value = record.get(field)
    require(isinstance(value, str) and sha_re.fullmatch(value) is not None, f"digest absent: {field}")
    require(
        hashlib.sha256(read_nofollow(packet_root / filename)).hexdigest() == value,
        f"digest differs: {filename}",
    )

source_manifest = json.loads(read_nofollow(packet_root / "source-manifest.json"))
require(
    isinstance(source_manifest, dict)
    and source_manifest.get("schema") == "fortgym.m1b-live-source-manifest/v1",
    "source manifest schema differs",
)
source_files = source_manifest.get("files")
require(isinstance(source_files, list) and bool(source_files), "source file list is absent")
source_expected = {}
for item in source_files:
    require(isinstance(item, dict), "source file record is not an object")
    name = item.get("path")
    size = item.get("size_bytes")
    digest = item.get("sha256")
    mode = item.get("mode")
    require(isinstance(name, str), "source path is absent")
    safe_member_name(name)
    require(name not in source_expected, f"duplicate source path: {name}")
    require(
        isinstance(size, int) and not isinstance(size, bool) and size >= 0,
        f"bad source size: {name}",
    )
    require(
        isinstance(digest, str) and sha_re.fullmatch(digest) is not None,
        f"bad source digest: {name}",
    )
    require(mode in {"0644", "0755"}, f"bad source mode: {name}")
    source_expected[name] = {"size": size, "sha256": digest, "mode": int(mode, 8)}
require(source_manifest.get("file_count") == len(source_expected), "source file count differs")
require(
    source_manifest.get("file_bytes")
    == sum(int(item["size"]) for item in source_expected.values()),
    "source byte count differs",
)

wheel_text = read_nofollow(packet_root / "live-wheelhouse.sha256").decode("ascii")
wheel_matches = wheel_record_re.findall(wheel_text)
require(
    "".join(f"{digest}  {name}\n" for digest, name in wheel_matches) == wheel_text,
    "wheel digest manifest syntax differs",
)
wheel_expected = {}
for digest, name in wheel_matches:
    require(name not in wheel_expected, f"duplicate wheel: {name}")
    wheel_expected[name] = {"size": None, "sha256": digest, "mode": 0o644}
require(bool(wheel_expected), "wheel digest manifest is empty")
wheel_handle, wheel_archive = open_tar(packet_root / "fortgym-m1b-wheelhouse.tar")
try:
    for member in wheel_archive.getmembers():
        if member.name in wheel_expected:
            wheel_expected[member.name]["size"] = member.size
finally:
    wheel_archive.close()
    wheel_handle.close()
require(all(item["size"] is not None for item in wheel_expected.values()), "wheel tar is incomplete")

expected_docker_inputs = {
    "InRelease": (46614, "19916250e8c2de32f5938227de988b846c36ff0def8dabbb149592c949b80b85"),
    "Packages.gz": (95006, "c745da94edd1809aa74f0bf45a72b5935e649d524de6405695dbdf4d5e54d7fd"),
    "containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb": (23371888, "3505acd8a8124077df5608293e933c5dfb0dac988f143019fa6efe98e79b92d5"),
    "docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb": (16294920, "fa4c2ad37fa4e5bc4bc5bd4098daec153e546c9ccd5419adf8f91e54f0a0e2bd"),
    "docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb": (21018900, "809c748027406afb4563bf61886e5ec0e3b5d34ff0353256ae618a2c6c5b29fc"),
    "docker-keyring.gpg": (2760, "a09e26b72228e330d55bf134b8eaca57365ef44bf70b8e27c5f55ea87a8b05e2"),
}
archive_members = docker_runtime.get("archive_members")
require(
    isinstance(archive_members, list) and len(archive_members) == len(expected_docker_inputs),
    "Docker runtime archive member list differs",
)
docker_expected = {}
for item in archive_members:
    require(isinstance(item, dict), "Docker archive member record is not an object")
    name = item.get("path")
    require(name in expected_docker_inputs and name not in docker_expected, "Docker archive member differs")
    size, digest = expected_docker_inputs[name]
    require(
        item == {"mode": "0644", "path": name, "sha256": digest, "size_bytes": size},
        f"Docker archive member metadata differs: {name}",
    )
    docker_expected[name] = {"size": size, "sha256": digest, "mode": 0o644}
require(set(docker_expected) == set(expected_docker_inputs), "Docker archive filename set differs")

inspect_tar(packet_root / "fortgym-m1b-source.tar", source_expected)
inspect_tar(packet_root / "fortgym-m1b-wheelhouse.tar", wheel_expected)
inspect_tar(packet_root / "fortgym-m1b-docker-runtime.tar", docker_expected)
extract_verified_tar(packet_root / "fortgym-m1b-source.tar", source_root, source_expected)
extract_verified_tar(packet_root / "fortgym-m1b-wheelhouse.tar", wheel_root, wheel_expected)
extract_verified_tar(
    packet_root / "fortgym-m1b-docker-runtime.tar", docker_runtime_root, docker_expected
)
PY

running_bootstrap="$(/usr/bin/realpath -e -- "$0")"
running_bootstrap_sha256="$(/usr/bin/sha256sum "$running_bootstrap")"
running_bootstrap_sha256="${running_bootstrap_sha256%% *}"
packet_bootstrap_sha256="$(/usr/bin/sha256sum "$source_root/infra/m1b/bootstrap_live_host.sh")"
packet_bootstrap_sha256="${packet_bootstrap_sha256%% *}"
if [[ "$running_bootstrap_sha256" != "$packet_bootstrap_sha256" ]]; then
  printf 'executing bootstrap digest differs from the packet-bound source\n' >&2
  exit 70
fi

# Installation precedes outer fail-close activation. The Docker daemon is
# packet-bound and remains unable to start until its containerd-store config is
# installed and validated. Distro docker.io is never requested or accepted.
for forbidden_package in docker.io docker-ce docker-ce-cli containerd.io containerd runc; do
  if /usr/bin/dpkg-query -W '-f=${db:Status-Status}\n' "$forbidden_package" \
    2>/dev/null | /usr/bin/grep -qx installed; then
    printf 'fresh host unexpectedly has a container runtime package: %s\n' \
      "$forbidden_package" >&2
    exit 73
  fi
done
if [[ -e /usr/bin/dockerd || -L /usr/bin/dockerd ]] \
  || /usr/bin/systemctl is-active --quiet docker.service docker.socket containerd.service; then
  printf 'fresh host unexpectedly has an active or installed Docker runtime\n' >&2
  exit 73
fi
if [[ -e /usr/sbin/policy-rc.d || -L /usr/sbin/policy-rc.d ]]; then
  printf 'fresh host unexpectedly has a service-start policy override\n' >&2
  exit 73
fi
/usr/bin/printf '%s\n' '#!/bin/sh' 'exit 101' >"$bootstrap_work/policy-rc.d"
/usr/bin/install -o root -g root -m 0755 "$bootstrap_work/policy-rc.d" /usr/sbin/policy-rc.d
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  DEBIAN_FRONTEND=noninteractive /usr/bin/timeout --signal=TERM --kill-after=30s 900s \
  /usr/bin/apt-get update >"$bootstrap_work/apt-update.txt" 2>&1
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  DEBIAN_FRONTEND=noninteractive /usr/bin/timeout --signal=TERM --kill-after=30s 900s \
  /usr/bin/apt-get install -y --no-install-recommends \
  binutils ca-certificates clang diffutils gcc gpgv iproute2 iptables jq libbpf-dev libelf-dev \
  libc6-dev libseccomp2 libssl-dev libsystemd0 linux-libc-dev llvm make \
  nftables pkg-config procps python3 python3-venv sudo util-linux zlib1g-dev zstd \
  >"$bootstrap_work/apt-install.txt" 2>&1
atomic_evidence_copy "$bootstrap_work/apt-update.txt" apt-update.txt
atomic_evidence_copy "$bootstrap_work/apt-install.txt" apt-install.txt
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s /usr/bin/systemctl mask \
  docker.service docker.socket containerd.service
/usr/bin/install -d -o root -g root -m 0755 /etc/docker
/usr/bin/printf '%s\n' \
  '{"features":{"containerd-snapshotter":true},"userland-proxy":false}' \
  >"$bootstrap_work/daemon.json"
/usr/bin/install -o root -g root -m 0644 "$bootstrap_work/daemon.json" /etc/docker/daemon.json

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/gpgv --status-fd 1 --keyring "$docker_runtime_root/docker-keyring.gpg" \
  "$docker_runtime_root/InRelease" >"$bootstrap_work/docker-repository-signature.txt"
atomic_evidence_copy \
  "$bootstrap_work/docker-repository-signature.txt" docker-repository-signature.txt
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  DEBIAN_FRONTEND=noninteractive /usr/bin/timeout --signal=TERM --kill-after=30s 300s \
  /usr/bin/dpkg --install \
  "$docker_runtime_root/containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb" \
  "$docker_runtime_root/docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb" \
  "$docker_runtime_root/docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb"
if /usr/bin/systemctl is-active --quiet docker.service docker.socket containerd.service; then
  printf 'container runtime started before daemon configuration validation\n' >&2
  exit 70
fi
/bin/rm -f -- /usr/sbin/policy-rc.d
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s \
  /usr/bin/dockerd --validate --config-file=/etc/docker/daemon.json \
  >"$bootstrap_work/docker-daemon-config-validate.txt"
atomic_evidence_copy \
  "$bootstrap_work/docker-daemon-config-validate.txt" docker-daemon-config-validate.txt
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s /usr/bin/systemctl unmask \
  docker.service docker.socket containerd.service
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s /usr/bin/systemctl daemon-reload
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s /usr/bin/systemctl enable --now \
  containerd.service docker.service

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s \
  /usr/bin/docker version --format '{{json .}}' >"$bootstrap_work/docker-version.json"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s \
  /usr/bin/docker info --format '{{json .}}' >"$bootstrap_work/docker-info.json"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s \
  /usr/bin/containerd --version >"$bootstrap_work/containerd-version.txt"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/dpkg-query -W \
  '-f=${Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n' \
  containerd.io docker-ce docker-ce-cli >"$bootstrap_work/docker-packages.tsv"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/systemctl show --property ActiveState,SubState,FragmentPath \
  containerd.service docker.service >"$bootstrap_work/docker-services.txt"

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$packet_dir/PACKET.json" "$packet_dir/docker-runtime-manifest.json" \
  "$bootstrap_work/docker-version.json" "$bootstrap_work/docker-info.json" \
  "$bootstrap_work/containerd-version.txt" "$bootstrap_work/docker-packages.tsv" \
  "$bootstrap_work/docker-repository-signature.txt" \
  "$bootstrap_work/docker-runtime-attestation.json" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import stat
import sys

packet = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
runtime_manifest_path = pathlib.Path(sys.argv[2])
runtime_manifest_bytes = runtime_manifest_path.read_bytes()
runtime_manifest = json.loads(runtime_manifest_bytes)
docker_version = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
docker_info = json.loads(pathlib.Path(sys.argv[4]).read_text(encoding="utf-8"))
containerd_version = pathlib.Path(sys.argv[5]).read_text(encoding="utf-8")
package_lines = pathlib.Path(sys.argv[6]).read_text(encoding="utf-8").splitlines()
signature_status = pathlib.Path(sys.argv[7]).read_text(encoding="utf-8")
target = pathlib.Path(sys.argv[8])

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

docker_record = packet.get("docker_runtime")
require(isinstance(docker_record, dict), "Docker runtime packet record is absent")
require(
    hashlib.sha256(runtime_manifest_bytes).hexdigest()
    == docker_record.get("manifest_sha256"),
    "Docker runtime manifest digest differs after install",
)
require(
    runtime_manifest
    == {
        key: value
        for key, value in docker_record.items()
        if key not in {"archive", "archive_sha256", "manifest", "manifest_sha256"}
    },
    "Docker runtime manifest semantic binding differs after install",
)
require(
    isinstance(docker_version, dict)
    and isinstance(docker_version.get("Server"), dict)
    and docker_version["Server"].get("Version") == "29.1.3",
    "Docker Server.Version differs from 29.1.3",
)
driver_status = docker_info.get("DriverStatus") if isinstance(docker_info, dict) else None
require(
    isinstance(driver_status, list)
    and ["driver-type", "io.containerd.snapshotter.v1"] in driver_status,
    "Docker containerd snapshotter DriverStatus proof is absent",
)
CONTAINERD_VERSION_PATTERN = (
    r"containerd containerd\.io v2\.2\.1 "
    r"dea7da592f5d1d2b7755e3a161be07f43fad8f75\n"
)
require(
    re.fullmatch(CONTAINERD_VERSION_PATTERN, containerd_version) is not None,
    "containerd runtime version differs from the pinned containerd.io 2.2.1 build",
)
expected_packages = {
    "containerd.io\t2.2.1-1~debian.12~bookworm\tamd64\tinstalled",
    "docker-ce\t5:29.1.3-1~debian.12~bookworm\tamd64\tinstalled",
    "docker-ce-cli\t5:29.1.3-1~debian.12~bookworm\tamd64\tinstalled",
}
require(set(package_lines) == expected_packages and len(package_lines) == 3, "Docker package install set differs")
require(
    "VALIDSIG D3306A018370199E527AE7997EA0A9C3F273FCD8"
    in signature_status
    and signature_status.rstrip().endswith("9DC858229FC7DD38854AE2D88D81803C0EBFCD88"),
    "Docker repository signature proof differs on host",
)
require(
    pathlib.Path("/etc/docker/daemon.json").read_bytes()
    == b'{"features":{"containerd-snapshotter":true},"userland-proxy":false}\n',
    "Docker daemon configuration differs",
)
binary_records = runtime_manifest.get("binaries")
require(isinstance(binary_records, list) and len(binary_records) == 8, "Docker binary manifest differs")
installed_binaries = []
for item in binary_records:
    require(isinstance(item, dict), "Docker binary manifest entry is not an object")
    path = pathlib.Path(item.get("path", ""))
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == 0
        and stat.S_IMODE(info.st_mode) == 0o755
        and info.st_size == item.get("size_bytes")
        and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256"),
        f"installed Docker binary differs: {path}",
    )
    for ancestor in path.parents:
        ancestor_info = ancestor.lstat()
        require(
            not stat.S_ISLNK(ancestor_info.st_mode)
            and ancestor_info.st_uid == 0
            and stat.S_IMODE(ancestor_info.st_mode) & 0o022 == 0,
            f"installed Docker binary ancestry is mutable: {path}",
        )
    installed_binaries.append(
        {
            "architecture": "amd64",
            "mode": "0755",
            "package": item["package"],
            "path": str(path),
            "sha256": item["sha256"],
            "size_bytes": info.st_size,
        }
    )
payload = {
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
    "runtime_manifest_sha256": hashlib.sha256(runtime_manifest_bytes).hexdigest(),
    "installed_binaries": installed_binaries,
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
atomic_evidence_copy \
  "$bootstrap_work/docker-runtime-attestation.json" docker-runtime-attestation.json

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$packet_dir/PACKET.json" "$install_root/runtime-image.tar.zst" \
  "$bootstrap_work/runtime-archive-attestation.json" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

packet = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
archive = pathlib.Path(sys.argv[2])
target = pathlib.Path(sys.argv[3])
info = archive.lstat()
if (
    not stat.S_ISREG(info.st_mode)
    or archive.is_symlink()
    or info.st_uid != 0
    or info.st_gid != 0
    or stat.S_IMODE(info.st_mode) != 0o600
):
    raise SystemExit("runtime archive trust metadata differs")
digest = hashlib.sha256()
fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
try:
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
finally:
    os.close(fd)
expected = packet.get("runtime_archive", {}).get("compressed_sha256")
if digest.hexdigest() != expected:
    raise SystemExit("installed runtime archive digest differs from packet")
payload = {
    "schema": "fortgym.m1b-runtime-archive-attestation/v1",
    "ok": True,
    "path": str(archive),
    "sha256": digest.hexdigest(),
    "size_bytes": info.st_size,
    "runtime_archive_digest_exact": True,
    "root_owned_mode_0600": True,
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
atomic_evidence_copy \
  "$bootstrap_work/runtime-archive-attestation.json" runtime-archive-attestation.json

if /usr/bin/id "$service_user" >/dev/null 2>&1; then
  printf 'reserved service user already exists\n' >&2
  exit 73
fi
/usr/sbin/useradd --create-home --shell /usr/sbin/nologin "$service_user"
if [[ "$(/usr/bin/id -nG "$service_user")" != fortgym ]]; then
  printf 'service user group membership is broader than its private group\n' >&2
  exit 70
fi
if /usr/sbin/runuser -u "$service_user" -- /usr/bin/test -r /var/run/docker.sock \
  || /usr/sbin/runuser -u "$service_user" -- /usr/bin/test -w /var/run/docker.sock; then
  printf 'service user unexpectedly has direct Docker socket access\n' >&2
  exit 70
fi

/usr/bin/install -d -o root -g root -m 0755 "$state_root"
/usr/bin/install -d -o "$service_user" -g "$service_user" -m 0700 \
  "$state_root/artifacts" "$state_root/control" "$state_root/evidence" \
  "$state_root/canary"
/usr/bin/install -d -o root -g root -m 0755 "$state_root/broker"
/usr/bin/install -d -o "$service_user" -g "$service_user" -m 0700 \
  "$state_root/broker/requests"
/usr/bin/install -d -o root -g root -m 0700 \
  "$root_evidence/batches" "$root_evidence/bind-sources"

if [[ "$(/usr/bin/stat -fc %T /sys/fs/cgroup)" != cgroup2fs ]]; then
  printf 'cgroup v2 is required\n' >&2
  exit 70
fi
if ! /usr/bin/mountpoint -q /sys/fs/bpf; then
  /usr/bin/mount -t bpf bpf /sys/fs/bpf
fi
if [[ "$(/usr/bin/stat -fc %T /sys/fs/bpf)" != bpf_fs ]]; then
  printf 'bpffs is required\n' >&2
  exit 70
fi
/usr/bin/install -d -o root -g root -m 0700 \
  /sys/fs/cgroup/fortgym-provider-net /sys/fs/bpf/fortgym-provider-net

provider_dir="$install_root/provider-network-src"
/usr/bin/install -d -o root -g root -m 0755 "$provider_dir"
/bin/cp -a -- "$source_root/infra/m1b/provider_network/." "$provider_dir/"
build_env=(
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
  SOURCE_DATE_EPOCH=1723766400 CC=/usr/bin/gcc CLANG=/usr/bin/clang
  LLVM_STRIP=/usr/bin/llvm-strip PKG_CONFIG=/usr/bin/pkg-config
  SHA256SUM=/usr/bin/sha256sum
)
"${build_env[@]}" /usr/bin/make -C "$provider_dir" toolchain-report \
  >"$bootstrap_work/provider-toolchain.txt"
"${build_env[@]}" /usr/bin/make -C "$provider_dir" static-contract \
  >"$bootstrap_work/provider-static-contract.txt"
"${build_env[@]}" /usr/bin/make -C "$provider_dir" clean all \
  >"$bootstrap_work/provider-build.txt"
"${build_env[@]}" /usr/bin/make -C "$provider_dir" repro-check \
  >"$bootstrap_work/provider-repro-check.txt"
/usr/bin/cmp -- "$provider_dir/build/provider_network.bpf.o" \
  "$provider_dir/build-repro-a/provider_network.bpf.o"
/usr/bin/cmp -- "$provider_dir/build/provider_network.bpf.o" \
  "$provider_dir/build-repro-b/provider_network.bpf.o"
/usr/bin/cmp -- "$provider_dir/build/fortgym-provider-network-helper" \
  "$provider_dir/build-repro-a/fortgym-provider-network-helper"
/usr/bin/cmp -- "$provider_dir/build/fortgym-provider-network-helper" \
  "$provider_dir/build-repro-b/fortgym-provider-network-helper"
for build_record in provider-toolchain.txt provider-static-contract.txt provider-build.txt provider-repro-check.txt; do
  atomic_evidence_copy "$bootstrap_work/$build_record" "$build_record"
done

/usr/bin/install -d -o root -g root -m 0755 /usr/local/libexec
/usr/bin/install -o root -g "$service_user" -m 4750 \
  "$provider_dir/build/fortgym-provider-network-helper" \
  /usr/local/libexec/fortgym-provider-network-helper
/usr/bin/install -d -o root -g root -m 0755 /usr/local/lib/fortgym
/usr/bin/install -o root -g root -m 0644 \
  "$provider_dir/build/provider_network.bpf.o" \
  /usr/local/lib/fortgym/provider_network.bpf.o
/usr/bin/readelf --file-header /usr/local/libexec/fortgym-provider-network-helper \
  >"$bootstrap_work/provider-helper-elf.txt"
/usr/bin/readelf --file-header /usr/local/lib/fortgym/provider_network.bpf.o \
  >"$bootstrap_work/provider-bpf-elf.txt"
atomic_evidence_copy "$bootstrap_work/provider-helper-elf.txt" provider-helper-elf.txt
atomic_evidence_copy "$bootstrap_work/provider-bpf-elf.txt" provider-bpf-elf.txt

provider_helper_sha256="$(
  /usr/bin/sha256sum /usr/local/libexec/fortgym-provider-network-helper
)"
provider_helper_sha256="${provider_helper_sha256%% *}"
provider_bpf_sha256="$(
  /usr/bin/sha256sum /usr/local/lib/fortgym/provider_network.bpf.o
)"
provider_bpf_sha256="${provider_bpf_sha256%% *}"
provider_probe_identity="$(
  /usr/bin/python3 -I - "$expected_acceptance_sha256" <<'PY'
import hashlib
import sys

parts = (
    "fortgym.provider-network-manifest/v1",
    "bootstrap-provider-probe",
    sys.argv[1],
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "127.0.0.1",
    "44992",
)
print(hashlib.sha256(b"\0".join(part.encode("ascii") for part in parts)).hexdigest())
PY
)"
[[ "$provider_probe_identity" =~ ^[0-9a-f]{64}$ ]] || exit 70
readonly provider_probe_identity
readonly provider_probe_component="bootstrap-probe-${provider_probe_identity:0:16}"
readonly provider_probe_cgroup="/sys/fs/cgroup/fortgym-provider-net/$provider_probe_component"
readonly provider_probe_pins="/sys/fs/bpf/fortgym-provider-net/$provider_probe_component"
readonly provider_probe_guard="$state_root/control/bootstrap-provider-probe-guard.json"
readonly provider_probe_inner="$state_root/control/bootstrap-provider-probe-inner.json"
provider_probe_prepared=0
cleanup_provider_bootstrap_probe() {
  if ((provider_probe_prepared == 1)); then
    /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
      /usr/bin/timeout --signal=TERM --kill-after=2s 15s \
      /usr/sbin/runuser -u "$service_user" -- \
      /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
      /usr/local/libexec/fortgym-provider-network-helper cleanup \
      --cgroup "$provider_probe_cgroup" --pin-root "$provider_probe_pins" \
      --identity-sha256 "$provider_probe_identity" --format json \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup_provider_bootstrap_probe EXIT

if ! /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  /usr/sbin/runuser -u "$service_user" -- \
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  LIBBPF_LOG_LEVEL=debug \
  /usr/local/libexec/fortgym-provider-network-helper probe \
  --bpf-object /usr/local/lib/fortgym/provider_network.bpf.o --format json \
  >"$bootstrap_work/provider-capability-probe.json" \
  2>"$bootstrap_work/provider-capability-probe.stderr"; then
  atomic_evidence_copy \
    "$bootstrap_work/provider-capability-probe.stderr" \
    provider-capability-probe.stderr
  /bin/cat -- "$bootstrap_work/provider-capability-probe.stderr" >&2
  exit 70
fi
atomic_evidence_copy \
  "$bootstrap_work/provider-capability-probe.stderr" \
  provider-capability-probe.stderr
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  /usr/sbin/runuser -u "$service_user" -- \
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/local/libexec/fortgym-provider-network-helper prepare \
  --bpf-object /usr/local/lib/fortgym/provider_network.bpf.o \
  --expected-helper-sha256 "$provider_helper_sha256" \
  --expected-bpf-object-sha256 "$provider_bpf_sha256" \
  --cgroup "$provider_probe_cgroup" --pin-root "$provider_probe_pins" \
  --identity-sha256 "$provider_probe_identity" \
  --allow-connect4 127.0.0.1:44992 \
  --negative-canary-poison 203.0.113.77:44444 \
  --deny-connect6 --deny-sendmsg4 --deny-sendmsg6 --format json \
  >"$bootstrap_work/provider-prepare.json"
provider_probe_prepared=1

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  /usr/sbin/runuser -u "$service_user" -- \
  /usr/bin/env -i HOME=/home/fortgym USER=fortgym LOGNAME=fortgym \
  PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  FORT_GYM_RUN_ID=bootstrap-provider-probe \
  FORT_GYM_RUN_CONTRACT_SHA256="$expected_acceptance_sha256" \
  FORT_GYM_RUN_NONCE=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  FORT_GYM_NETWORK_ALLOWED_HOST=127.0.0.1 FORT_GYM_NETWORK_ALLOWED_PORT=44992 \
  FORT_GYM_NETWORK_POLICY=loopback-port-only \
  FORT_GYM_NETWORK_EVIDENCE_PATH=/var/lib/fortgym-m1b/evidence/bootstrap-provider-probe.json \
  /usr/local/libexec/fortgym-provider-network-helper enter \
  --cgroup "$provider_probe_cgroup" --identity-sha256 "$provider_probe_identity" \
  --require-python-policy loopback-port-only \
  --guard-attestation "$provider_probe_guard" -- \
  /usr/bin/python3 -I -c \
  'import errno,json,pathlib,socket,sys;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM|socket.SOCK_NONBLOCK);result=s.connect_ex(("127.0.0.1",44992));s.close();ok=result not in {errno.EPERM,errno.EACCES};pathlib.Path(sys.argv[1]).write_text(json.dumps({"schema":"fortgym.m1b-provider-bootstrap-inner/v1","ok":ok,"connect4_allowed_not_denied":ok,"connect_ex_errno":result},sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8");raise SystemExit(0 if ok else 70)' \
  "$provider_probe_inner"

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  /usr/sbin/runuser -u "$service_user" -- \
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/local/libexec/fortgym-provider-network-helper snapshot \
  --cgroup "$provider_probe_cgroup" --pin-root "$provider_probe_pins" \
  --identity-sha256 "$provider_probe_identity" \
  --guard-attestation "$provider_probe_guard" --format json \
  >"$bootstrap_work/provider-snapshot.json"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  /usr/sbin/runuser -u "$service_user" -- \
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/local/libexec/fortgym-provider-network-helper cleanup \
  --cgroup "$provider_probe_cgroup" --pin-root "$provider_probe_pins" \
  --identity-sha256 "$provider_probe_identity" --format json \
  >"$bootstrap_work/provider-cleanup.json"
provider_probe_prepared=0
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  /usr/sbin/runuser -u "$service_user" -- \
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/local/libexec/fortgym-provider-network-helper cleanup \
  --cgroup "$provider_probe_cgroup" --pin-root "$provider_probe_pins" \
  --identity-sha256 "$provider_probe_identity" --format json \
  >"$bootstrap_work/provider-cleanup-idempotent.json"
trap - EXIT

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$packet_dir/PACKET.json" "$packet_dir/source-manifest.json" "$provider_dir" \
  /usr/local/libexec/fortgym-provider-network-helper \
  /usr/local/lib/fortgym/provider_network.bpf.o \
  "$bootstrap_work/provider-helper-elf.txt" "$bootstrap_work/provider-bpf-elf.txt" \
  "$bootstrap_work/provider-helper-bpf-attestation.json" \
  "$bootstrap_work/provider-capability-probe.json" \
  "$bootstrap_work/provider-prepare.json" "$bootstrap_work/provider-snapshot.json" \
  "$bootstrap_work/provider-cleanup.json" \
  "$bootstrap_work/provider-cleanup-idempotent.json" \
  "$provider_probe_guard" "$provider_probe_inner" <<'PY'
import hashlib
import json
import os
import pathlib
import pwd
import stat
import sys

packet_path = pathlib.Path(sys.argv[1])
source_manifest_path = pathlib.Path(sys.argv[2])
provider_root = pathlib.Path(sys.argv[3])
helper = pathlib.Path(sys.argv[4])
bpf_object = pathlib.Path(sys.argv[5])
helper_elf = pathlib.Path(sys.argv[6]).read_text(encoding="utf-8")
bpf_elf = pathlib.Path(sys.argv[7]).read_text(encoding="utf-8")
target = pathlib.Path(sys.argv[8])
probe_path = pathlib.Path(sys.argv[9])
prepare_path = pathlib.Path(sys.argv[10])
snapshot_path = pathlib.Path(sys.argv[11])
cleanup_path = pathlib.Path(sys.argv[12])
cleanup_idempotent_path = pathlib.Path(sys.argv[13])
guard_path = pathlib.Path(sys.argv[14])
inner_path = pathlib.Path(sys.argv[15])

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()

packet = json.loads(packet_path.read_text(encoding="utf-8"))
source_manifest_bytes = source_manifest_path.read_bytes()
source_manifest = json.loads(source_manifest_bytes)
require(
    source_manifest.get("tree_sha256") == packet.get("source", {}).get("tree_sha256"),
    "provider source manifest packet binding differs",
)
source_records = {
    item["path"]: item
    for item in source_manifest.get("files", [])
    if isinstance(item, dict) and isinstance(item.get("path"), str)
}
provider_sources = (
    "infra/m1b/provider_network/Makefile",
    "infra/m1b/provider_network/provider_network.bpf.c",
    "infra/m1b/provider_network/provider_network_helper.c",
    "infra/m1b/provider_network/provider_network_shared.h",
)
for relative in provider_sources:
    path = pathlib.Path("/opt/fort-gym-m1a") / relative
    record = source_records.get(relative)
    require(
        isinstance(record, dict)
        and record.get("sha256") == sha256(path)
        and record.get("size_bytes") == path.stat().st_size,
        f"provider source is not packet-bound: {relative}",
    )
main_helper = provider_root / "build/fortgym-provider-network-helper"
main_bpf = provider_root / "build/provider_network.bpf.o"
repro_paths = (
    provider_root / "build-repro-a/fortgym-provider-network-helper",
    provider_root / "build-repro-b/fortgym-provider-network-helper",
    provider_root / "build-repro-a/provider_network.bpf.o",
    provider_root / "build-repro-b/provider_network.bpf.o",
)
helper_digest = sha256(main_helper)
bpf_digest = sha256(main_bpf)
require(
    all(sha256(path) == helper_digest for path in repro_paths[:2])
    and all(sha256(path) == bpf_digest for path in repro_paths[2:]),
    "provider network reproducible outputs differ",
)
service_gid = pwd.getpwnam("fortgym").pw_gid
for path, expected_gid, expected_mode, expected_digest in (
    (helper, service_gid, 0o4750, helper_digest),
    (bpf_object, 0, 0o644, bpf_digest),
):
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == expected_gid
        and stat.S_IMODE(info.st_mode) == expected_mode
        and sha256(path) == expected_digest,
        f"installed provider artifact differs: {path}",
    )
    for ancestor in path.parents:
        ancestor_info = ancestor.lstat()
        require(
            not stat.S_ISLNK(ancestor_info.st_mode)
            and ancestor_info.st_uid == 0
            and stat.S_IMODE(ancestor_info.st_mode) & 0o022 == 0,
            f"provider artifact ancestry is mutable: {path}",
        )
require("Type:" in helper_elf and "DYN" in helper_elf and "X86-64" in helper_elf, "provider helper ELF identity differs")
require("Type:" in bpf_elf and "REL" in bpf_elf and "Linux BPF" in bpf_elf, "provider BPF ELF identity differs")
identity_parts = (
    "fortgym.provider-network-manifest/v1",
    "bootstrap-provider-probe",
    packet["acceptance_sha256"],
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "127.0.0.1",
    "44992",
)
identity = hashlib.sha256(
    b"\0".join(part.encode("ascii") for part in identity_parts)
).hexdigest()
component = f"bootstrap-probe-{identity[:16]}"
hooks = ["connect4", "connect6", "sendmsg4", "sendmsg6"]
policy = {
    "mode": "cgroup_bpf_default_deny",
    "hooks": hooks,
    "allow": {
        "hook": "connect4",
        "family": "AF_INET",
        "protocol": "tcp",
        "host": "127.0.0.1",
        "port": 44992,
    },
    "deny": {
        "connect4_nonmatching": True,
        "connect6": True,
        "sendmsg4": True,
        "sendmsg6": True,
    },
}
documents = {}
for name, path in (
    ("probe", probe_path),
    ("prepare", prepare_path),
    ("snapshot", snapshot_path),
    ("cleanup", cleanup_path),
    ("cleanup_idempotent", cleanup_idempotent_path),
    ("guard", guard_path),
    ("inner", inner_path),
):
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and stat.S_IMODE(info.st_mode) == 0o600,
        f"provider live probe receipt metadata differs: {name}",
    )
    if name in {"guard", "inner"}:
        require(
            info.st_uid == pwd.getpwnam("fortgym").pw_uid
            and info.st_gid == service_gid,
            f"provider nonroot receipt ownership differs: {name}",
        )
    else:
        require(info.st_uid == 0 and info.st_gid == 0, f"provider root receipt ownership differs: {name}")
    documents[name] = json.loads(path.read_text(encoding="utf-8"))
probe = documents["probe"]
require(
    probe
    == {
        "schema": "fortgym.provider-network-capabilities/v1",
        "ok": True,
        "os": "linux",
        "architecture": "x86_64",
        "cgroup_version": 2,
        "bpffs": True,
        "cgroup_bpf": True,
        "default_deny": True,
        "structured_capture": True,
        "join_before_exec": True,
        "hooks": hooks,
        "helper_sha256": helper_digest,
        "bpf_object_sha256": bpf_digest,
    },
    "provider live capability probe differs",
)
prepare = documents["prepare"]
require(
    prepare.get("schema") == "fortgym.provider-network-prepare/v1"
    and prepare.get("ok") is True
    and prepare.get("identity_sha256") == identity
    and prepare.get("cgroup_path")
    == f"/sys/fs/cgroup/fortgym-provider-net/{component}"
    and prepare.get("pin_root")
    == f"/sys/fs/bpf/fortgym-provider-net/{component}"
    and prepare.get("policy") == policy
    and prepare.get("hooks") == hooks
    and prepare.get("evidence_external") is True,
    "provider live prepare receipt differs",
)
guard = documents["guard"]
expected_evidence_digest = hashlib.sha256(
    b"/var/lib/fortgym-m1b/evidence/bootstrap-provider-probe.json"
).hexdigest()
require(
    guard
    == {
        "schema": "fortgym.python-network-guard-attestation/v1",
        "installed": True,
        "identity_sha256": identity,
        "policy": "loopback-port-only",
        "allowed_host": "127.0.0.1",
        "allowed_port": 44992,
        "evidence_path_sha256": expected_evidence_digest,
    },
    "provider nonroot guard receipt differs",
)
inner = documents["inner"]
require(
    isinstance(inner, dict)
    and set(inner) == {"schema", "ok", "connect4_allowed_not_denied", "connect_ex_errno"}
    and inner.get("schema") == "fortgym.m1b-provider-bootstrap-inner/v1"
    and inner.get("ok") is True
    and inner.get("connect4_allowed_not_denied") is True
    and isinstance(inner.get("connect_ex_errno"), int)
    and not isinstance(inner.get("connect_ex_errno"), bool)
    and inner.get("connect_ex_errno") not in {1, 13},
    "provider exact loopback allow probe differs",
)
snapshot = documents["snapshot"]
events = snapshot.get("events") if isinstance(snapshot, dict) else None
require(
    snapshot.get("schema") == "fortgym.provider-network-capture/v1"
    and snapshot.get("final") is True
    and snapshot.get("identity_sha256") == identity
    and snapshot.get("policy") == policy
    and snapshot.get("hooks") == hooks
    and snapshot.get("lost_events") == 0
    and snapshot.get("event_count") == 7
    and isinstance(events, list)
    and len(events) == 7
    and snapshot.get("python_guard") == guard,
    "provider live snapshot contract differs",
)
require(
    [event.get("sequence") for event in events] == list(range(1, 8))
    and all(event.get("identity_sha256") == identity for event in events),
    "provider live event sequence/identity differs",
)
allowed = [event for event in events if event.get("decision") == "allow"]
denied = [event for event in events if event.get("decision") == "deny"]
require(
    allowed
    == [
        {
            "sequence": allowed[0].get("sequence") if allowed else None,
            "identity_sha256": identity,
            "hook": "connect4",
            "operation": "connect",
            "family": "AF_INET",
            "protocol": "tcp",
            "destination_host": "127.0.0.1",
            "destination_port": 44992,
            "decision": "allow",
            "errno": 0,
        }
    ]
    and len(denied) == 6
    and all(event.get("errno") == "EPERM" for event in denied),
    "provider allow/deny event proof differs",
)
deny_hook_counts = {
    hook: sum(event.get("hook") == hook for event in denied) for hook in hooks
}
require(
    deny_hook_counts
    == {"connect4": 3, "connect6": 1, "sendmsg4": 1, "sendmsg6": 1},
    "provider default-deny hook coverage differs",
)
for name in ("cleanup", "cleanup_idempotent"):
    require(
        documents[name]
        == {
            "schema": "fortgym.provider-network-cleanup/v1",
            "ok": True,
            "identity_sha256": identity,
            "cgroup_absent": True,
            "pins_absent": True,
        },
        f"provider live cleanup receipt differs: {name}",
    )
require(
    not pathlib.Path(prepare["cgroup_path"]).exists()
    and not pathlib.Path(prepare["pin_root"]).exists(),
    "provider live probe residue remains",
)
payload = {
    "schema": "fortgym.m1b-provider-helper-bpf-attestation/v1",
    "ok": True,
    "provider_helper_bpf_attested": True,
    "source_tree_sha256": packet["source"]["tree_sha256"],
    "source_manifest_sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
    "helper_path": str(helper),
    "helper_sha256": helper_digest,
    "helper_mode": "4750",
    "bpf_object_path": str(bpf_object),
    "bpf_object_sha256": bpf_digest,
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
    "capability_probe_sha256": sha256(probe_path),
    "prepare_sha256": sha256(prepare_path),
    "snapshot_sha256": sha256(snapshot_path),
    "guard_attestation_sha256": sha256(guard_path),
    "inner_allow_probe_sha256": sha256(inner_path),
    "cleanup_sha256": sha256(cleanup_path),
    "cleanup_idempotent_sha256": sha256(cleanup_idempotent_path),
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
atomic_evidence_copy \
  "$bootstrap_work/provider-helper-bpf-attestation.json" \
  provider-helper-bpf-attestation.json
for provider_probe_receipt in provider-capability-probe.json provider-prepare.json \
  provider-snapshot.json provider-cleanup.json provider-cleanup-idempotent.json; do
  atomic_evidence_copy \
    "$bootstrap_work/$provider_probe_receipt" "$provider_probe_receipt"
done
atomic_evidence_copy "$provider_probe_guard" provider-bootstrap-guard.json
atomic_evidence_copy "$provider_probe_inner" provider-bootstrap-inner.json

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 300s \
  /usr/bin/zstd -dc --no-progress "$packet_dir/fortgym-df-m1a.tar.zst" \
  | /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=TERM --kill-after=10s 300s \
    /usr/bin/docker image load >"$bootstrap_work/docker-image-load.txt"
atomic_evidence_copy "$bootstrap_work/docker-image-load.txt" docker-image-load.txt
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=10s 60s \
  /usr/bin/docker image inspect "$expected_runtime_image_ref" \
  >"$bootstrap_work/docker-image-inspect.json"
atomic_evidence_copy "$bootstrap_work/docker-image-inspect.json" docker-image-inspect.json
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$bootstrap_work/docker-image-inspect.json" "$expected_runtime_image_id" \
  "$packet_dir/PACKET.json" \
  "$bootstrap_work/docker-image-descriptor-attestation.json" <<'PY'
import json
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
packet = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
target = pathlib.Path(sys.argv[4])
if (
    not isinstance(document, list)
    or len(document) != 1
    or not isinstance(document[0], dict)
    or document[0].get("Id") != sys.argv[2]
    or document[0].get("Architecture") != "amd64"
    or document[0].get("Os") != "linux"
):
    raise SystemExit("loaded runtime image identity or platform differs")
image = document[0]
descriptor = image.get("Descriptor")
runtime = packet.get("runtime_archive")
if (
    not isinstance(runtime, dict)
    or runtime.get("manifest_sha256") != sys.argv[2].removeprefix("sha256:")
    or runtime.get("config_sha256")
    != "d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86"
    or runtime.get("manifest_size_bytes") != 2306
    or runtime.get("manifest_media_type")
    != "application/vnd.oci.image.manifest.v1+json"
):
    raise SystemExit("packet OCI descriptor contract differs")
if (
    not isinstance(descriptor, dict)
    or descriptor.get("digest") != sys.argv[2]
    or descriptor.get("size") != 2306
    or descriptor.get("mediaType")
    != "application/vnd.oci.image.manifest.v1+json"
):
    raise SystemExit("loaded runtime image descriptor differs")
platform = descriptor.get("platform")
if isinstance(platform, dict) and (
    platform.get("architecture") != "amd64" or platform.get("os") != "linux"
):
    raise SystemExit("loaded runtime image descriptor platform differs")
repo_digests = image.get("RepoDigests")
if (
    not isinstance(repo_digests, list)
    or f"fortgym-df@{sys.argv[2]}" not in repo_digests
):
    raise SystemExit("loaded runtime image RepoDigest differs")
payload = {
    "schema": "fortgym.m1b-docker-image-descriptor-attestation/v1",
    "ok": True,
    "image_reference": "fortgym-df:m1a-stock-0.47.05-r8",
    "image_id": sys.argv[2],
    "manifest_digest": descriptor["digest"],
    "manifest_media_type": descriptor["mediaType"],
    "manifest_size_bytes": descriptor["size"],
    "config_digest": "sha256:d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86",
    "platform": "linux/amd64",
    "containerd_image_store_descriptor_attested": True,
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
atomic_evidence_copy \
  "$bootstrap_work/docker-image-descriptor-attestation.json" \
  docker-image-descriptor-attestation.json

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I -m venv --copies "$venv_root"
/usr/bin/env -i PATH="$venv_root/bin:/usr/sbin:/usr/bin:/sbin:/bin" LC_ALL=C \
  PIP_NO_INDEX=1 "$venv_root/bin/python" -I -m pip install \
  --disable-pip-version-check --no-index --find-links "$wheel_root" \
  --requirement "$packet_dir/live-requirements.lock"
site_packages="$(
  /usr/bin/env -i PATH="$venv_root/bin:/usr/sbin:/usr/bin:/sbin:/bin" LC_ALL=C \
    "$venv_root/bin/python" -I -c \
    'import sysconfig; print(sysconfig.get_paths()["purelib"])'
)"
if [[ "$site_packages" != "$venv_root"/lib/python3.11/site-packages ]]; then
  printf 'virtualenv site-packages path differs from Python 3.11\n' >&2
  exit 70
fi
/usr/bin/printf '%s\n' "$source_root" >"$bootstrap_work/fortgym-m1b-source.pth"
/usr/bin/install -o root -g root -m 0644 \
  "$bootstrap_work/fortgym-m1b-source.pth" \
  "$site_packages/fortgym-m1b-source.pth"
source_pth_sha256="$(/usr/bin/sha256sum "$site_packages/fortgym-m1b-source.pth")"
source_pth_sha256="${source_pth_sha256%% *}"
if [[ "$source_pth_sha256" != "$expected_source_pth_sha256" ]]; then
  printf 'isolated source .pth digest differs\n' >&2
  exit 70
fi
/bin/chmod -R u+rwX,go+rX,go-w "$venv_root"

broker_source="$source_root/infra/m1b/root_broker.py"
if [[ -L "$broker_source" || ! -f "$broker_source" ]]; then
  printf 'root broker source is absent or unsafe\n' >&2
  exit 66
fi
/usr/bin/install -o root -g root -m 0755 \
  "$broker_source" /usr/local/libexec/fortgym-m1b-root-broker
broker_source_sha256="$(/usr/bin/sha256sum "$broker_source")"
broker_source_sha256="${broker_source_sha256%% *}"
broker_installed_sha256="$(/usr/bin/sha256sum /usr/local/libexec/fortgym-m1b-root-broker)"
broker_installed_sha256="${broker_installed_sha256%% *}"
if [[ "$broker_source_sha256" != "$broker_installed_sha256" ]]; then
  printf 'installed root broker digest differs from verified source\n' >&2
  exit 70
fi

# The runner can traverse root-owned code and the venv, and can read only the
# two verified packet metadata files it consumes. Archives stay root-only and
# are reachable only through the semantic broker.
/bin/chmod 0755 "$install_root" "$packet_stage" "$venv_root"
/bin/chmod 0644 "$packet_stage/PACKET.json" "$packet_stage/source-manifest.json"
/usr/bin/install -d -o root -g root -m 0700 \
  "$state_root/broker/claims" "$state_root/broker/claims/incoming" \
  "$state_root/broker/grants" "$state_root/broker/receipts" \
  "$state_root/broker/state" "$state_root/broker/state/inflight"

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$source_root" "$venv_root" /usr/local/libexec/fortgym-m1b-root-broker \
  "$packet_stage" "$site_packages/fortgym-m1b-source.pth" \
  "$state_root/broker" "$root_evidence/docker-runtime-attestation.json" \
  "$root_evidence/runtime-archive-attestation.json" \
  "$root_evidence/provider-helper-bpf-attestation.json" \
  "$root_evidence/docker-image-descriptor-attestation.json" \
  "$bootstrap_work/trusted-paths.json" <<'PY'
import hashlib
import json
import os
import pathlib
import pwd
import stat
import sys

source_root = pathlib.Path(sys.argv[1])
venv_root = pathlib.Path(sys.argv[2])
broker = pathlib.Path(sys.argv[3])
packet_root = pathlib.Path(sys.argv[4])
source_pth = pathlib.Path(sys.argv[5])
broker_state_root = pathlib.Path(sys.argv[6])
docker_attestation_path = pathlib.Path(sys.argv[7])
archive_attestation_path = pathlib.Path(sys.argv[8])
provider_attestation_path = pathlib.Path(sys.argv[9])
descriptor_attestation_path = pathlib.Path(sys.argv[10])
target = pathlib.Path(sys.argv[11])

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

def require_root_nonwritable(path: pathlib.Path, *, allow_symlink: bool = False) -> None:
    info = path.lstat()
    require(info.st_uid == 0 and info.st_gid == 0, f"trusted path is not root-owned: {path}")
    if path.is_symlink():
        require(allow_symlink, f"trusted path is a symlink: {path}")
        return
    require(stat.S_IMODE(info.st_mode) & 0o022 == 0, f"trusted path is writable by nonroot: {path}")

for root in (source_root, venv_root):
    require_root_nonwritable(root)
    for directory, names, filenames in os.walk(root, followlinks=False):
        base = pathlib.Path(directory)
        require_root_nonwritable(base)
        for name in (*names, *filenames):
            candidate = base / name
            require_root_nonwritable(candidate, allow_symlink=root == venv_root)
            if candidate.is_symlink():
                resolved = candidate.resolve(strict=True)
                require(
                    resolved.is_relative_to(venv_root)
                    or resolved.is_relative_to(pathlib.Path("/usr/bin"))
                    or resolved.is_relative_to(pathlib.Path("/usr/lib")),
                    f"venv symlink escapes trusted system roots: {candidate}",
                )
                require_root_nonwritable(resolved)
                for parent in resolved.parents:
                    require_root_nonwritable(parent)
for trusted_path in (source_root, venv_root, broker):
    for ancestor in trusted_path.parents:
        require_root_nonwritable(ancestor)
require_root_nonwritable(broker)
require_root_nonwritable(pathlib.Path(sys.executable).resolve(strict=True))
require_root_nonwritable(source_pth)
require(source_pth.read_bytes() == b"/opt/fort-gym-m1a\n", "source .pth content differs")
require_root_nonwritable(packet_root)
for name in ("PACKET.json", "source-manifest.json"):
    path = packet_root / name
    require_root_nonwritable(path)
    require(stat.S_IMODE(path.stat().st_mode) == 0o644, f"public packet metadata mode differs: {name}")
for name in (
    "docker-runtime-manifest.json",
    "MANIFEST.sha256",
    "fortgym-df-m1a.tar.zst",
    "fortgym-m1b-docker-runtime.tar",
    "fortgym-m1b-source.tar",
    "fortgym-m1b-wheelhouse.tar",
    "live-requirements.lock",
    "live-wheelhouse.sha256",
    "seed_tree.sha256z",
):
    path = packet_root / name
    require_root_nonwritable(path)
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
        f"private packet mode differs: {name}",
    )
service_uid = pwd.getpwnam("fortgym").pw_uid
service_gid = pwd.getpwnam("fortgym").pw_gid
for path, uid, gid, mode in (
    (broker_state_root, 0, 0, 0o755),
    (broker_state_root / "requests", service_uid, service_gid, 0o700),
    (broker_state_root / "claims", 0, 0, 0o700),
    (broker_state_root / "claims/incoming", 0, 0, 0o700),
    (broker_state_root / "grants", 0, 0, 0o700),
    (broker_state_root / "receipts", 0, 0, 0o700),
    (broker_state_root / "state", 0, 0, 0o700),
    (broker_state_root / "state/inflight", 0, 0, 0o700),
    (docker_attestation_path.parent / "batches", 0, 0, 0o700),
    (docker_attestation_path.parent / "bind-sources", 0, 0, 0o700),
):
    info = path.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == uid
        and info.st_gid == gid
        and stat.S_IMODE(info.st_mode) == mode,
        f"broker state directory trust differs: {path.name}",
    )
attestations = {}
for name, path, schema, flag in (
    (
        "docker_runtime",
        docker_attestation_path,
        "fortgym.m1b-docker-runtime-attestation/v1",
        "docker_server_29_1_3_containerd_store",
    ),
    (
        "runtime_archive",
        archive_attestation_path,
        "fortgym.m1b-runtime-archive-attestation/v1",
        "runtime_archive_digest_exact",
    ),
    (
        "provider_helper_bpf",
        provider_attestation_path,
        "fortgym.m1b-provider-helper-bpf-attestation/v1",
        "provider_helper_bpf_attested",
    ),
    (
        "docker_image_descriptor",
        descriptor_attestation_path,
        "fortgym.m1b-docker-image-descriptor-attestation/v1",
        "containerd_image_store_descriptor_attested",
    ),
):
    require_root_nonwritable(path)
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
        f"root attestation metadata differs: {name}",
    )
    encoded = path.read_bytes()
    record = json.loads(encoded)
    require(
        isinstance(record, dict)
        and record.get("schema") == schema
        and record.get("ok") is True
        and record.get(flag) is True,
        f"root attestation contract differs: {name}",
    )
    attestations[name] = hashlib.sha256(encoded).hexdigest()
payload = {
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
    "docker_runtime_attestation_sha256": attestations["docker_runtime"],
    "runtime_archive_attestation_sha256": attestations["runtime_archive"],
    "provider_helper_bpf_attestation_sha256": attestations["provider_helper_bpf"],
    "docker_image_descriptor_attestation_sha256": attestations["docker_image_descriptor"],
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
atomic_evidence_copy "$bootstrap_work/trusted-paths.json" trusted-paths.json

if ! /usr/sbin/runuser -u "$service_user" -- /usr/bin/test -x "$venv_root/bin/python"; then
  printf 'service user cannot execute the verified virtualenv interpreter\n' >&2
  exit 70
fi
if ! /usr/sbin/runuser -u "$service_user" -- /usr/bin/test -r "$packet_stage/source-manifest.json"; then
  printf 'service user cannot read verified packet metadata\n' >&2
  exit 70
fi
if /usr/sbin/runuser -u "$service_user" -- /usr/bin/test -r "$install_root/runtime-image.tar.zst"; then
  printf 'service user can read the root-only runtime archive\n' >&2
  exit 70
fi
/usr/sbin/runuser -u "$service_user" -- \
  /usr/bin/env -i HOME=/home/fortgym USER=fortgym LOGNAME=fortgym \
  PATH="$venv_root/bin:/usr/bin:/bin" LC_ALL=C DF_PROTO_ENABLED=1 \
  "$venv_root/bin/python" -I - \
  "$source_root" "$source_pth_sha256" \
  >"$bootstrap_work/nonroot-isolated-import.json" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import sys

source_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
source_pth_sha256 = sys.argv[2]
if sys.flags.isolated != 1 or "PYTHONPATH" in os.environ:
    raise SystemExit("nonroot import smoke is not isolated")
if os.geteuid() == 0:
    raise SystemExit("nonroot import smoke unexpectedly retained root")
if any(
    key in os.environ
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
):
    raise SystemExit("provider environment reached nonroot import smoke")
import fort_gym
from fort_gym.bench.env.remote_proto import ensure_proto_modules, runtime_binding_digest
from fort_gym.bench.eval.fort_eval_easy_p1 import p1_measurement_code_digest

package_path = pathlib.Path(fort_gym.__file__).resolve(strict=True)
if package_path != source_root / "fort_gym/__init__.py":
    raise SystemExit("isolated import did not resolve to verified repository source")
if sys.path.count(str(source_root)) != 1:
    raise SystemExit("verified repository source path is absent or duplicated")
modules = ensure_proto_modules()
if sorted(modules) != ["core", "fortress"]:
    raise SystemExit("isolated import protobuf module set differs")
binding = runtime_binding_digest()
if binding != "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f":
    raise SystemExit("isolated import runtime binding differs")
measurement_code_sha256 = p1_measurement_code_digest()
if re.fullmatch(r"[0-9a-f]{64}", measurement_code_sha256) is None:
    raise SystemExit("isolated measurement code digest is invalid")
payload = {
    "schema": "fortgym.m1b-nonroot-isolated-import/v1",
    "ok": True,
    "effective_uid_nonzero": os.geteuid() != 0,
    "python_isolated": True,
    "source_root": str(source_root),
    "package_file": str(package_path),
    "source_pth": "/opt/fortgym-m1b/venv/lib/python3.11/site-packages/fortgym-m1b-source.pth",
    "source_pth_sha256": source_pth_sha256,
    "runtime_binding_sha256": binding,
    "measurement_code_sha256": measurement_code_sha256,
    "provider_environment_present": False,
}
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
PY
atomic_evidence_copy "$bootstrap_work/nonroot-isolated-import.json" nonroot-isolated-import.json

/usr/bin/printf '%s\n' \
  'fortgym ALL=(root) NOPASSWD: /usr/local/libexec/fortgym-m1b-root-broker --request /var/lib/fortgym-m1b/broker/requests/*.json' \
  >"$bootstrap_work/fortgym-m1b-acceptance.sudoers"
/usr/bin/install -o root -g root -m 0440 \
  "$bootstrap_work/fortgym-m1b-acceptance.sudoers" \
  /etc/sudoers.d/fortgym-m1b-acceptance
/usr/sbin/visudo -cf /etc/sudoers.d/fortgym-m1b-acceptance \
  >"$bootstrap_work/sudoers-check.txt"
atomic_evidence_copy "$bootstrap_work/sudoers-check.txt" sudoers-check.txt

expiry_source="$source_root/infra/m1b/expire_live_host.sh"
if [[ -L "$expiry_source" || ! -f "$expiry_source" ]]; then
  printf 'expiry enforcer source is absent or unsafe\n' >&2
  exit 66
fi
/usr/bin/install -o root -g root -m 0755 \
  "$expiry_source" /usr/local/libexec/fortgym-m1b-expire-live-host

timer_on_calendar="$(/usr/bin/date -u -d "$authority_expiry" '+%Y-%m-%d %H:%M:%S UTC')"

/usr/bin/printf '%s\n' \
  '[Unit]' \
  'Description=Revoke Fort Gym M1b execution authority at the exact boundary' \
  '' '[Service]' 'Type=oneshot' \
  'ExecStart=/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C /bin/bash --noprofile --norc /usr/local/libexec/fortgym-m1b-expire-live-host' \
  >"$bootstrap_work/fortgym-m1b-expire.service"
/usr/bin/printf '%s\n' \
  '[Unit]' 'Description=Exact Fort Gym M1b infrastructure-authority expiry' \
  '' '[Timer]' "OnCalendar=$timer_on_calendar" 'AccuracySec=1us' \
  'RandomizedDelaySec=0' 'Persistent=true' \
  'Unit=fortgym-m1b-expire.service' '' '[Install]' 'WantedBy=timers.target' \
  >"$bootstrap_work/fortgym-m1b-expire.timer"
/usr/bin/install -o root -g root -m 0644 \
  "$bootstrap_work/fortgym-m1b-expire.service" \
  /etc/systemd/system/fortgym-m1b-expire.service
/usr/bin/install -o root -g root -m 0644 \
  "$bootstrap_work/fortgym-m1b-expire.timer" \
  /etc/systemd/system/fortgym-m1b-expire.timer
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C /usr/bin/systemctl daemon-reload
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/systemctl enable --now fortgym-m1b-expire.timer
timer_next="$(/usr/bin/systemctl show fortgym-m1b-expire.timer --value --property NextElapseUSecRealtime)"
if [[ -z "$timer_next" || "$(/usr/bin/date -u -d "$timer_next" +%s)" != "$authority_expiry_epoch" ]]; then
  printf 'expiry timer next elapse differs from the authority boundary\n' >&2
  exit 70
fi
/usr/bin/systemctl show fortgym-m1b-expire.timer >"$bootstrap_work/expiry-timer.txt"
atomic_evidence_copy "$bootstrap_work/expiry-timer.txt" expiry-timer.txt

# Isolated-mode imports add only the verified source root. Explicit checks are
# used so optimization can never erase a security decision.
/usr/bin/env -i PATH="$venv_root/bin:/usr/sbin:/usr/bin:/sbin:/bin" LC_ALL=C \
  DF_PROTO_ENABLED=1 "$venv_root/bin/python" -I - \
  "$packet_dir/PACKET.json" "$source_root" "$bootstrap_work/runtime-check.json" <<'PY'
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import sys

packet_path = pathlib.Path(sys.argv[1])
source_root = pathlib.Path(sys.argv[2])
target = pathlib.Path(sys.argv[3])

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)

require(sys.flags.isolated == 1, "Python isolated mode is required")
require("PYTHONPATH" not in os.environ, "PYTHONPATH must be absent")
require(
    not any(key in os.environ for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")),
    "provider credentials reached the bootstrap check",
)
import fort_gym
from fort_gym.bench.env.remote_proto import ensure_proto_modules, runtime_binding_digest
from fort_gym.bench.eval.fort_eval_easy_p1 import p1_measurement_code_digest

packet = json.loads(packet_path.read_text(encoding="utf-8"))
package_path = pathlib.Path(fort_gym.__file__).resolve(strict=True)
require(package_path.is_relative_to(source_root), "runtime import did not preserve repository source path")
modules = ensure_proto_modules()
require(sorted(modules) == ["core", "fortress"], "runtime protobuf module set differs")
binding = runtime_binding_digest()
require(binding == packet["runtime_proto"]["runtime_binding_sha256"], "runtime binding differs")
protobuf_version = importlib.metadata.version("protobuf")
require(protobuf_version == "6.31.1", "protobuf package version differs")
measurement_code_sha256 = p1_measurement_code_digest()
require(
    len(measurement_code_sha256) == 64
    and all(character in "0123456789abcdef" for character in measurement_code_sha256),
    "measurement code digest is invalid",
)
receipt = {
    "schema": "fortgym.m1b-live-runtime-check/v1",
    "ok": True,
    "platform": platform.platform(),
    "machine": platform.machine(),
    "python": platform.python_version(),
    "python_isolated": True,
    "protobuf": protobuf_version,
    "runtime_binding_sha256": binding,
    "measurement_code_sha256": measurement_code_sha256,
    "package_file": str(package_path),
    "source_manifest_sha256": hashlib.sha256(
        packet_path.parent.joinpath("source-manifest.json").read_bytes()
    ).hexdigest(),
    "provider_environment_present": False,
}
target.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
atomic_evidence_copy "$bootstrap_work/runtime-check.json" runtime-check.json

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/dpkg-query -W '-f=${binary:Package}\t${Version}\n' \
  | /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C /usr/bin/sort \
    >"$bootstrap_work/dpkg-packages.tsv"
/usr/bin/env -i PATH="$venv_root/bin:/usr/sbin:/usr/bin:/sbin:/bin" LC_ALL=C \
  "$venv_root/bin/python" -I -m pip freeze --all \
  | /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C /usr/bin/sort \
    >"$bootstrap_work/python-packages.txt"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/lscpu --json >"$bootstrap_work/lscpu.json"
/usr/bin/sha256sum \
  /usr/local/libexec/fortgym-provider-network-helper \
  /usr/local/lib/fortgym/provider_network.bpf.o \
  /usr/local/libexec/fortgym-m1b-root-broker \
  /usr/local/libexec/fortgym-m1b-expire-live-host \
  >"$bootstrap_work/installed-tools.sha256"
for evidence_file in dpkg-packages.tsv python-packages.txt docker-version.json \
  docker-info.json containerd-version.txt docker-packages.tsv docker-services.txt \
  lscpu.json installed-tools.sha256; do
  atomic_evidence_copy "$bootstrap_work/$evidence_file" "$evidence_file"
done

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$packet_dir/PACKET.json" "$bootstrap_work/bootstrap.json" \
  "$manifest_sha256" "$broker_installed_sha256" "$authority_expiry" \
  "$source_pth_sha256" "$root_evidence/nonroot-isolated-import.json" \
  "$expected_runtime_image_id" \
  "$root_evidence/docker-runtime-attestation.json" \
  "$root_evidence/runtime-archive-attestation.json" \
  "$root_evidence/provider-helper-bpf-attestation.json" \
  "$root_evidence/docker-image-descriptor-attestation.json" \
  "$root_evidence/trusted-paths.json" <<'PY'
import datetime
import hashlib
import json
import pathlib
import sys

packet = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
target = pathlib.Path(sys.argv[2])
nonroot_import = json.loads(pathlib.Path(sys.argv[7]).read_text(encoding="utf-8"))
if (
    nonroot_import.get("schema") != "fortgym.m1b-nonroot-isolated-import/v1"
    or nonroot_import.get("ok") is not True
    or nonroot_import.get("effective_uid_nonzero") is not True
    or nonroot_import.get("python_isolated") is not True
    or nonroot_import.get("source_pth_sha256") != sys.argv[6]
    or nonroot_import.get("source_root") != "/opt/fort-gym-m1a"
    or nonroot_import.get("package_file") != "/opt/fort-gym-m1a/fort_gym/__init__.py"
):
    raise SystemExit("nonroot isolated import evidence differs")
subordinate_specs = (
    (9, "fortgym.m1b-docker-runtime-attestation/v1", "docker_server_29_1_3_containerd_store"),
    (10, "fortgym.m1b-runtime-archive-attestation/v1", "runtime_archive_digest_exact"),
    (11, "fortgym.m1b-provider-helper-bpf-attestation/v1", "provider_helper_bpf_attested"),
    (12, "fortgym.m1b-docker-image-descriptor-attestation/v1", "containerd_image_store_descriptor_attested"),
    (13, "fortgym.m1b-trusted-host-paths/v1", "docker_server_29_1_3_containerd_store"),
)
subordinate = []
for index, schema, flag in subordinate_specs:
    path = pathlib.Path(sys.argv[index])
    encoded = path.read_bytes()
    record = json.loads(encoded)
    if (
        not isinstance(record, dict)
        or record.get("schema") != schema
        or record.get("ok") is not True
        or record.get(flag) is not True
    ):
        raise SystemExit(f"bootstrap subordinate attestation differs: {schema}")
    subordinate.append((record, hashlib.sha256(encoded).hexdigest()))
docker_attestation, docker_attestation_sha256 = subordinate[0]
archive_attestation, archive_attestation_sha256 = subordinate[1]
provider_attestation, provider_attestation_sha256 = subordinate[2]
descriptor_attestation, descriptor_attestation_sha256 = subordinate[3]
trusted_paths, trusted_paths_sha256 = subordinate[4]
if (
    trusted_paths.get("runtime_archive_digest_exact") is not True
    or trusted_paths.get("provider_helper_bpf_attested") is not True
):
    raise SystemExit("trusted paths subordinate flags differ")
receipt = {
    "schema": "fortgym.m1b-live-host-bootstrap/v1",
    "ok": True,
    "acceptance_sha256": packet["acceptance_sha256"],
    "authority_expires_at": packet["authority"]["infrastructure_authority_expires_at"],
    "bootstrap_completed_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "manifest_sha256_out_of_band": sys.argv[3],
    "packet_copied_to_root_staging": True,
    "runtime_archive_path": "/opt/fortgym-m1b/runtime-image.tar.zst",
    "runtime_image_id": sys.argv[8],
    "runtime_image_manifest_digest": descriptor_attestation["manifest_digest"],
    "runtime_image_manifest_media_type": descriptor_attestation["manifest_media_type"],
    "runtime_image_manifest_size_bytes": descriptor_attestation["manifest_size_bytes"],
    "safe_archive_preflight_completed": True,
    "docker_runtime_manifest_sha256": packet["docker_runtime"]["manifest_sha256"],
    "docker_runtime_attestation_sha256": docker_attestation_sha256,
    "runtime_archive_attestation_sha256": archive_attestation_sha256,
    "provider_helper_bpf_attestation_sha256": provider_attestation_sha256,
    "docker_image_descriptor_attestation_sha256": descriptor_attestation_sha256,
    "trusted_paths_sha256": trusted_paths_sha256,
    "docker_server_version": docker_attestation["docker_server_version"],
    "containerd_version": docker_attestation["containerd_version"],
    "docker_server_29_1_3_containerd_store": True,
    "runtime_archive_digest_exact": archive_attestation["runtime_archive_digest_exact"],
    "provider_helper_bpf_attested": provider_attestation["provider_helper_bpf_attested"],
    "containerd_image_store_descriptor_attested": descriptor_attestation[
        "containerd_image_store_descriptor_attested"
    ],
    "docker_install_mode": "offline-packet-bound-docker-ce-debs",
    "distro_docker_io_installed": False,
    "daemon_configured_before_first_start": True,
    "docker_userland_proxy_disabled": True,
    "root_broker_sha256": sys.argv[4],
    "root_broker_is_only_sudo_target": True,
    "service_user_in_docker_group": False,
    "expiry_timer_next_elapse": sys.argv[5],
    "python_major_minor": "3.11",
    "dependency_install_mode": "python3.11-venv-offline-pinned-wheels",
    "dependency_waivers": False,
    "source_pth_path": "/opt/fortgym-m1b/venv/lib/python3.11/site-packages/fortgym-m1b-source.pth",
    "source_pth_sha256": sys.argv[6],
    "nonroot_isolated_import_ok": True,
    "nonroot_measurement_code_digest_ok": True,
    "measurement_code_sha256": nonroot_import["measurement_code_sha256"],
    "source_path_preserves_repo_file": True,
    "root_evidence_private": True,
    "provider_calls": 0,
    "provider_cost_usd": 0,
}
target.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
atomic_evidence_copy "$bootstrap_work/bootstrap.json" bootstrap.json

if [[ "$(/usr/bin/stat -c '%U:%G:%a' "$root_evidence")" != root:root:700 ]]; then
  printf 'root evidence directory ownership or mode drifted\n' >&2
  exit 70
fi
for trusted_directory in "$root_evidence/batches" "$root_evidence/bind-sources"; do
  if [[ -L "$trusted_directory" || ! -d "$trusted_directory" \
    || "$(/usr/bin/stat -c '%U:%G:%a' "$trusted_directory")" != root:root:700 ]]; then
    printf 'root evidence trusted directory ownership or mode drifted: %s\n' \
      "$trusted_directory" >&2
    exit 70
  fi
done
if /usr/bin/find "$root_evidence/bind-sources" -mindepth 1 -print -quit \
  | /usr/bin/grep -q .; then
  printf 'root evidence bind-sources directory is not empty\n' >&2
  exit 70
fi
if /usr/bin/find "$root_evidence" -mindepth 1 -maxdepth 1 \
  ! -name batches ! -name bind-sources \
  \( ! -type f -o ! -user root -o ! -group root -o ! -perm 0600 -o ! -links 1 \) \
  | /usr/bin/grep -q .; then
  printf 'root evidence file ownership or mode drifted\n' >&2
  exit 70
fi

printf 'M1b host bootstrap complete; outer egress guard is not yet active.\n'
