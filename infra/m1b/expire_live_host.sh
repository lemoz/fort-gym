#!/bin/bash
set -euo pipefail

# Local fail-close at the operator authority boundary. Provider-side automatic
# VM deletion remains mandatory and independent; this script does not call a
# cloud API and never weakens the outer network guard while deletion is pending.

export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset BASH_ENV CDPATH ENV GLOBIGNORE PYTHONHOME PYTHONPATH PYTHONOPTIMIZE
umask 077

if (($# != 0)); then
  printf 'expiry enforcement accepts no arguments\n' >&2
  exit 64
fi
if [[ "$EUID" -ne 0 || "$(/usr/bin/uname -s)" != Linux ]]; then
  printf 'expiry enforcement requires root on Linux\n' >&2
  exit 77
fi

readonly authority_expiry='2026-09-06T12:00:00Z'
readonly root_evidence=/var/lib/fortgym-m1b-root-evidence
expiry_epoch="$(/usr/bin/date -u -d "$authority_expiry" +%s)"
now_epoch="$(/usr/bin/date -u +%s)"
if (( now_epoch < expiry_epoch )); then
  printf 'refusing to revoke M1b authority before its exact expiry\n' >&2
  exit 77
fi

# The higher-priority fail-close is the first state change after root/Linux/time
# checks. A pre-existing table is never trusted: delete plus recreation is one
# nft -f transaction, so malformed crash residue cannot survive and there is
# no partially configured ruleset between the two operations. Debian 12's nft
# lacks the newer non-failing `destroy table`, hence the read-only presence
# branch. Any batch failure aborts before privilege or process cleanup.
install_expiry_fail_close() {
  if /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=TERM --kill-after=2s 10s \
    /usr/sbin/nft list table inet fortgym_m1b_expired >/dev/null 2>&1; then
    /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
      /usr/bin/timeout --signal=TERM --kill-after=2s 10s \
      /usr/sbin/nft -f - <<'NFT'
delete table inet fortgym_m1b_expired
table inet fortgym_m1b_expired {
  counter output_denied {}
  counter forward_denied {}
  chain output {
    type filter hook output priority -300; policy drop;
    oifname "lo" counter accept
    counter name output_denied reject with icmpx type admin-prohibited
  }
  chain forward {
    type filter hook forward priority -300; policy drop;
    counter name forward_denied reject with icmpx type admin-prohibited
  }
}
NFT
  else
    /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
      /usr/bin/timeout --signal=TERM --kill-after=2s 10s \
      /usr/sbin/nft -f - <<'NFT'
table inet fortgym_m1b_expired {
  counter output_denied {}
  counter forward_denied {}
  chain output {
    type filter hook output priority -300; policy drop;
    oifname "lo" counter accept
    counter name output_denied reject with icmpx type admin-prohibited
  }
  chain forward {
    type filter hook forward priority -300; policy drop;
    counter name forward_denied reject with icmpx type admin-prohibited
  }
}
NFT
  fi
}

install_expiry_fail_close
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 10s \
  /usr/sbin/nft --json list table inet fortgym_m1b_expired \
  >/run/fortgym-m1b-expired-rules.json
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 10s \
  /usr/bin/python3 -I - /run/fortgym-m1b-expired-rules.json <<'PY'
import json
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
entries = document.get("nftables") if isinstance(document, dict) else None
if not isinstance(entries, list):
    raise SystemExit("early expiry fail-close ruleset is malformed")
objects = []
for entry in entries:
    if not isinstance(entry, dict) or len(entry) != 1:
        raise SystemExit("early expiry fail-close nft object is malformed")
    kind, value = next(iter(entry.items()))
    if kind == "metainfo":
        continue
    if not isinstance(value, dict):
        raise SystemExit("early expiry fail-close nft value is malformed")
    if value.get("family") == "inet" and value.get(
        "table", value.get("name")
    ) == "fortgym_m1b_expired":
        objects.append((kind, value))
tables = [value for kind, value in objects if kind == "table"]
chains = {value.get("name"): value for kind, value in objects if kind == "chain"}
counters = {value.get("name"): value for kind, value in objects if kind == "counter"}
rules = [value for kind, value in objects if kind == "rule"]
if len(tables) != 1 or set(chains) != {"output", "forward"}:
    raise SystemExit("early expiry fail-close table or chain set differs")
if set(counters) != {"output_denied", "forward_denied"}:
    raise SystemExit("early expiry fail-close counter set differs")
for name, hook in (("output", "output"), ("forward", "forward")):
    chain = chains[name]
    if (
        chain.get("type") != "filter"
        or chain.get("hook") != hook
        or chain.get("prio") != -300
        or chain.get("policy") != "drop"
    ):
        raise SystemExit("early expiry fail-close base chain differs")
output_rules = [rule for rule in rules if rule.get("chain") == "output"]
forward_rules = [rule for rule in rules if rule.get("chain") == "forward"]
if len(output_rules) != 2 or len(forward_rules) != 1 or len(rules) != 3:
    raise SystemExit("early expiry fail-close rule count differs")
encoded = [
    json.dumps(rule.get("expr"), sort_keys=True, separators=(",", ":"))
    for rule in (*output_rules, *forward_rules)
]
if not all(token in encoded[0] for token in ('"oifname"', '"lo"', '"accept"')):
    raise SystemExit("early expiry loopback rule differs")
if not all(token in encoded[1] for token in ('"output_denied"', '"reject"')):
    raise SystemExit("early expiry OUTPUT reject rule differs")
if not all(token in encoded[2] for token in ('"forward_denied"', '"reject"')):
    raise SystemExit("early expiry FORWARD reject rule differs")
if any('"accept"' in value for value in encoded[1:]):
    raise SystemExit("early expiry fail-close unexpectedly allows non-loopback traffic")
PY

bounded_cleanup() {
  local duration="$1"
  shift
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=TERM --kill-after=2s "$duration" "$@"
}

if [[ ! -e "$root_evidence" && ! -L "$root_evidence" ]]; then
  /usr/bin/install -d -o root -g root -m 0700 "$root_evidence"
fi
if [[ -L "$root_evidence" || "$(/usr/bin/stat -c '%U:%G:%a' "$root_evidence")" != root:root:700 ]]; then
  printf 'root evidence directory ownership or mode differs\n' >&2
  exit 70
fi

# Revoke every entry point before cleanup. Existing bounded broker/helper
# processes are killed explicitly; new ones lose both sudo/setuid access.
bounded_cleanup 5s /bin/rm -f -- /etc/sudoers.d/fortgym-m1b-acceptance
if [[ -e /usr/local/libexec/fortgym-m1b-root-broker && ! -L /usr/local/libexec/fortgym-m1b-root-broker ]]; then
  bounded_cleanup 5s /bin/chmod 000 /usr/local/libexec/fortgym-m1b-root-broker
fi
if [[ -e /usr/local/libexec/fortgym-provider-network-helper && ! -L /usr/local/libexec/fortgym-provider-network-helper ]]; then
  bounded_cleanup 5s /bin/chmod 000 /usr/local/libexec/fortgym-provider-network-helper
fi
bounded_cleanup 5s /usr/bin/pkill -KILL -f \
  '/usr/local/libexec/fortgym-m1b-root-broker' >/dev/null 2>&1 || true
bounded_cleanup 5s /usr/bin/pkill -KILL -f \
  '/usr/local/libexec/fortgym-provider-network-helper' >/dev/null 2>&1 || true
if bounded_cleanup 5s /usr/bin/id fortgym >/dev/null 2>&1; then
  bounded_cleanup 5s /usr/bin/pkill -KILL -u fortgym >/dev/null 2>&1 || true
fi

managed_container_file=/run/fortgym-m1b-expired-containers.txt
if ! bounded_cleanup 10s /usr/bin/docker ps --all --quiet --no-trunc \
  --filter label=fortgym.m1b.managed=true >"$managed_container_file" 2>/dev/null; then
  : >"$managed_container_file"
fi
mapfile -t managed_containers <"$managed_container_file"
for container_id in "${managed_containers[@]}"; do
  if [[ "$container_id" =~ ^[0-9a-f]{64}$ ]]; then
    bounded_cleanup 15s /usr/bin/docker rm --force "$container_id" \
      >/dev/null 2>&1 || true
  fi
done

mount_table=/run/fortgym-m1b-expired-mounts.txt
if ! bounded_cleanup 10s /usr/bin/findmnt --raw --noheadings \
  --output TARGET,FSTYPE,SOURCE >"$mount_table" 2>/dev/null; then
  : >"$mount_table"
fi
bounded_cleanup 5s /usr/bin/awk \
  '$1 ~ "^/var/lib/fortgym-m1b/artifacts/" && $2 == "tmpfs" && $3 ~ "^fortgym-m1b-enospc-" {print $1}' \
  "$mount_table" >"$mount_table.selected"
while IFS= read -r mountpoint; do
  [[ "$mountpoint" == /var/lib/fortgym-m1b/artifacts/* ]] || continue
  bounded_cleanup 10s /bin/umount -- "$mountpoint" >/dev/null 2>&1 || true
done <"$mount_table.selected"

# Broker-owned bind sources persist for each managed container lifetime. After
# container removal, revoke any exact safe-run bind mount and then remove only
# its now-empty root-owned leaf and parent. Every discovery and cleanup command
# remains bounded under the already-live expiry fail-close table.
bind_source_root="$root_evidence/bind-sources"
bind_mount_table=/run/fortgym-m1b-expired-bind-mounts.txt
if ! bounded_cleanup 10s /usr/bin/findmnt --raw --noheadings --output TARGET \
  >"$bind_mount_table" 2>/dev/null; then
  : >"$bind_mount_table"
fi
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 5s \
  /usr/bin/python3 -I - "$bind_mount_table" "$bind_source_root" \
  >"$bind_mount_table.selected" <<'PY'
import pathlib
import re
import sys

mounts = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
root = pathlib.Path(sys.argv[2])
safe_id = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
selected = []
for raw in mounts:
    target = pathlib.Path(raw)
    try:
        relative = target.relative_to(root)
    except ValueError:
        continue
    if len(relative.parts) != 2 or relative.parts[1] != "artifacts":
        continue
    if safe_id.fullmatch(relative.parts[0]) is None:
        continue
    selected.append(str(target))
for target in sorted(set(selected)):
    print(target)
PY
while IFS= read -r mountpoint; do
  [[ "$mountpoint" =~ ^/var/lib/fortgym-m1b-root-evidence/bind-sources/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/artifacts$ ]] \
    || continue
  bounded_cleanup 10s /bin/umount -- "$mountpoint" >/dev/null 2>&1 || true
done <"$bind_mount_table.selected"

bind_source_directories=/run/fortgym-m1b-expired-bind-directories.txt
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 5s \
  /usr/bin/python3 -I - "$bind_source_root" \
  >"$bind_source_directories" <<'PY'
import os
import pathlib
import re
import stat
import sys

root = pathlib.Path(sys.argv[1])
if not root.exists() or root.is_symlink():
    raise SystemExit(0)
info = root.lstat()
if (
    not stat.S_ISDIR(info.st_mode)
    or info.st_uid != 0
    or info.st_gid != 0
    or stat.S_IMODE(info.st_mode) != 0o700
):
    raise SystemExit("bind-source root metadata differs")
safe_id = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    for name in sorted(os.listdir(root_fd)):
        if safe_id.fullmatch(name) is None:
            continue
        run_info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(run_info.st_mode)
            or run_info.st_uid != 0
            or run_info.st_gid != 0
            or stat.S_IMODE(run_info.st_mode) != 0o700
        ):
            continue
        run_fd = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        try:
            children = os.listdir(run_fd)
            if children != ["artifacts"]:
                continue
            leaf = os.stat("artifacts", dir_fd=run_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(leaf.st_mode)
                or leaf.st_uid != 0
                or leaf.st_gid != 0
                or stat.S_IMODE(leaf.st_mode) != 0o700
            ):
                continue
        finally:
            os.close(run_fd)
        print(root / name / "artifacts")
finally:
    os.close(root_fd)
PY
while IFS= read -r artifacts_directory; do
  [[ "$artifacts_directory" =~ ^/var/lib/fortgym-m1b-root-evidence/bind-sources/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/artifacts$ ]] \
    || continue
  bounded_cleanup 5s /bin/rmdir -- "$artifacts_directory" >/dev/null 2>&1 || true
  bounded_cleanup 5s /bin/rmdir -- "${artifacts_directory%/artifacts}" \
    >/dev/null 2>&1 || true
done <"$bind_source_directories"

bounded_cleanup 30s /usr/bin/systemctl stop docker.socket docker.service \
  >/dev/null 2>&1 || true
bounded_cleanup 10s /usr/bin/systemctl mask --runtime docker.socket docker.service \
  >/dev/null 2>&1 || true

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$root_evidence" /run/fortgym-m1b-expired-rules.json "$authority_expiry" <<'PY'
import datetime
import json
import os
import pathlib
import secrets
import stat
import sys

parent = pathlib.Path(sys.argv[1])
rules_path = pathlib.Path(sys.argv[2])
expiry = sys.argv[3]
name = "authority-expired.json"
parent_info = parent.lstat()
if (
    not stat.S_ISDIR(parent_info.st_mode)
    or parent_info.st_uid != 0
    or parent_info.st_gid != 0
    or stat.S_IMODE(parent_info.st_mode) != 0o700
):
    raise SystemExit("root evidence directory ownership or mode differs")
rules = json.loads(rules_path.read_text(encoding="utf-8"))
entries = rules.get("nftables") if isinstance(rules, dict) else None
if not isinstance(entries, list):
    raise SystemExit("expiry fail-close live ruleset is malformed")
objects = []
for entry in entries:
    if not isinstance(entry, dict) or len(entry) != 1:
        raise SystemExit("expiry fail-close nft object is malformed")
    kind, value = next(iter(entry.items()))
    if kind == "metainfo":
        continue
    if not isinstance(value, dict):
        raise SystemExit("expiry fail-close nft value is malformed")
    if value.get("family") == "inet" and value.get(
        "table", value.get("name")
    ) == "fortgym_m1b_expired":
        objects.append((kind, value))
tables = [value for kind, value in objects if kind == "table"]
chains = {value.get("name"): value for kind, value in objects if kind == "chain"}
counters = {value.get("name"): value for kind, value in objects if kind == "counter"}
nft_rules = [value for kind, value in objects if kind == "rule"]
if len(tables) != 1 or set(chains) != {"output", "forward"}:
    raise SystemExit("expiry fail-close table or chain set differs")
if set(counters) != {"output_denied", "forward_denied"}:
    raise SystemExit("expiry fail-close counter set differs")
for name, hook in (("output", "output"), ("forward", "forward")):
    chain = chains[name]
    if (
        chain.get("type") != "filter"
        or chain.get("hook") != hook
        or chain.get("prio") != -300
        or chain.get("policy") != "drop"
    ):
        raise SystemExit("expiry fail-close base chain differs")
output_rules = [rule for rule in nft_rules if rule.get("chain") == "output"]
forward_rules = [rule for rule in nft_rules if rule.get("chain") == "forward"]
if len(output_rules) != 2 or len(forward_rules) != 1 or len(nft_rules) != 3:
    raise SystemExit("expiry fail-close rule count differs")
encoded = [
    json.dumps(rule.get("expr"), sort_keys=True, separators=(",", ":"))
    for rule in (*output_rules, *forward_rules)
]
if not all(token in encoded[0] for token in ('"oifname"', '"lo"', '"accept"')):
    raise SystemExit("expiry loopback rule differs")
if not all(token in encoded[1] for token in ('"output_denied"', '"reject"')):
    raise SystemExit("expiry OUTPUT reject rule differs")
if not all(token in encoded[2] for token in ('"forward_denied"', '"reject"')):
    raise SystemExit("expiry FORWARD reject rule differs")
if any('"accept"' in value for value in encoded[1:]):
    raise SystemExit("expiry fail-close unexpectedly allows non-loopback traffic")
payload = {
    "schema": "fortgym.m1b-authority-expired/v1",
    "authority_expired_at": expiry,
    "enforced_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "privilege_revoked": True,
    "root_broker_disabled": True,
    "provider_network_helper_disabled": True,
    "service_process_termination_attempted": True,
    "managed_containers_removal_attempted": True,
    "private_tmpfs_unmount_attempted": True,
    "root_bind_source_unmount_attempted": True,
    "root_bind_source_empty_directory_cleanup_attempted": True,
    "docker_stop_and_runtime_mask_attempted": True,
    "expiry_fail_close_installed_before_cleanup": True,
    "cleanup_commands_bounded": True,
    "outer_egress_fail_close_retained": True,
    "expiry_fail_close_table": "inet fortgym_m1b_expired",
    "previous_control_ssh_flow_revoked": True,
    "provider_deletion_still_required": True,
    "provider_api_called": False,
}
encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = f".{name}.{secrets.token_hex(16)}.tmp"
descriptor = None
try:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise SystemExit("immutable expiry evidence already exists")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    view = memoryview(encoded)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]
    os.fchmod(descriptor, 0o600)
    os.fsync(descriptor)
    os.close(descriptor)
    descriptor = None
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
        raise SystemExit("published expiry evidence metadata differs")
    os.fsync(directory_fd)
finally:
    if descriptor is not None:
        os.close(descriptor)
    try:
        os.unlink(temporary, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    os.close(directory_fd)
PY

printf 'M1b host authority revoked; fail-close retained; provider deletion remains mandatory.\n'
