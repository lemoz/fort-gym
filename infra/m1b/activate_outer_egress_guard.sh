#!/bin/bash
set -euo pipefail

# Activate after installation and image import. Only loopback and replies from
# the host SSH server remain possible; all other OUTPUT and all FORWARD traffic
# fail closed. The exact live ruleset and a counter-bound negative canary are
# required before this script reports success.

export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset BASH_ENV CDPATH ENV GLOBIGNORE PYTHONHOME PYTHONPATH PYTHONOPTIMIZE
umask 077

mode=activate
if (($# == 1)) && [[ "$1" == --verify-only ]]; then
  mode=verify-only
  shift
elif (($# != 0)); then
  printf 'outer egress guard accepts only --verify-only\n' >&2
  exit 64
fi
if [[ "$EUID" -ne 0 ]]; then
  printf 'outer egress guard must run as root\n' >&2
  exit 77
fi
if [[ "$(/usr/bin/uname -s)" != Linux || "$(/usr/bin/uname -m)" != x86_64 ]]; then
  printf 'outer egress guard requires isolated x86_64 Linux\n' >&2
  exit 70
fi

readonly authority_expiry='2026-09-06T12:00:00Z'
readonly expected_acceptance_sha256='b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf'
readonly expected_runtime_image_id='sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c'
readonly root_evidence=/var/lib/fortgym-m1b-root-evidence
guard_work=/run/fortgym-m1b-egress
if [[ "$mode" == verify-only ]]; then
  guard_work=/run/fortgym-m1b-egress-post-run
fi
readonly guard_work
readonly guard_exec_root=/opt/fortgym-m1b/security-canary
readonly table_name=fortgym_m1b_outer
expiry_epoch="$(/usr/bin/date -u -d "$authority_expiry" +%s)"
if (( $(/usr/bin/date -u +%s) >= expiry_epoch )); then
  printf 'the operator infrastructure authority has expired\n' >&2
  exit 77
fi
if [[ -e "$guard_work" || -L "$guard_work" ]]; then
  printf 'outer egress guard work directory already exists\n' >&2
  exit 73
fi
if [[ "$mode" == activate && ( -e "$guard_exec_root" || -L "$guard_exec_root" ) ]]; then
  printf 'outer egress guard canary directory already exists\n' >&2
  exit 73
fi
/usr/bin/install -d -o root -g root -m 0700 "$guard_work"
if [[ "$mode" == activate ]]; then
  /usr/bin/install -d -o root -g root -m 0700 "$guard_exec_root"
fi

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

verify_root_evidence_topology() {
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - "$root_evidence" <<'PY'
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
root_info = root.lstat()
if (
    not stat.S_ISDIR(root_info.st_mode)
    or root.is_symlink()
    or root_info.st_uid != 0
    or root_info.st_gid != 0
    or stat.S_IMODE(root_info.st_mode) != 0o700
):
    raise SystemExit("root evidence directory ownership or mode differs")
root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    names = os.listdir(root_fd)
    required_directories = {"batches", "bind-sources"}
    if not required_directories.issubset(names):
        raise SystemExit("required root evidence directory is absent")
    for name in names:
        info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if name in required_directories:
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0
                or info.st_gid != 0
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise SystemExit(f"root evidence directory metadata differs: {name}")
            if name == "bind-sources":
                bind_sources_fd = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
                )
                try:
                    if os.listdir(bind_sources_fd):
                        raise SystemExit("root evidence bind-sources directory is not empty")
                finally:
                    os.close(bind_sources_fd)
            continue
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0
            or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise SystemExit(f"root evidence top-level member metadata differs: {name}")
finally:
    os.close(root_fd)
PY
}

verify_bind_sources_unmounted() {
  local bind_sources="$root_evidence/bind-sources"
  local prefix="$guard_work/bind-sources-findmnt"
  local findmnt_rc
  set +e
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=TERM --kill-after=2s 10s \
    /usr/bin/findmnt --mountpoint "$bind_sources" --noheadings --output TARGET \
    >"$prefix.stdout" 2>"$prefix.stderr"
  findmnt_rc=$?
  set -e
  /usr/bin/printf '%s\n' "$findmnt_rc" >"$prefix.rc"
  if (( findmnt_rc != 1 )) || [[ -s "$prefix.stdout" || -s "$prefix.stderr" ]]; then
    printf 'root evidence bind-sources directory is mounted or findmnt failed\n' >&2
    exit 70
  fi
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - \
    "$prefix.rc" "$prefix.stdout" "$prefix.stderr" \
    "$guard_work/bind-sources-residue.json" "$mode" "$bind_sources" <<'PY'
import hashlib
import json
import pathlib
import sys

rc = int(pathlib.Path(sys.argv[1]).read_text(encoding="ascii").strip())
stdout = pathlib.Path(sys.argv[2]).read_bytes()
stderr = pathlib.Path(sys.argv[3]).read_bytes()
if rc != 1 or stdout or stderr:
    raise SystemExit("bind-sources findmnt absence proof differs")
payload = {
    "schema": "fortgym.m1b-bind-sources-residue/v1",
    "ok": True,
    "mode": sys.argv[5],
    "path": sys.argv[6],
    "empty": True,
    "unmounted": True,
    "findmnt_returncode": rc,
    "findmnt_stdout_sha256": hashlib.sha256(stdout).hexdigest(),
    "findmnt_stderr_sha256": hashlib.sha256(stderr).hexdigest(),
}
target = pathlib.Path(sys.argv[4])
target.write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
target.chmod(0o600)
PY
}

capture_live_rules() {
  local destination="$1"
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/sbin/nft --json list table inet "$table_name" >"$destination"
}

verify_live_rules() {
  local rules_path="$1"
  local flow_path="$2"
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - "$rules_path" "$flow_path" <<'PY'
import json
import os
import pathlib
import stat
import sys


def load_regular_nofollow(path: pathlib.Path) -> object:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SystemExit(f"live-rule input is not regular: {path.name}")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            return json.load(handle)
    finally:
        os.close(descriptor)


document = load_regular_nofollow(pathlib.Path(sys.argv[1]))
flow_document = load_regular_nofollow(pathlib.Path(sys.argv[2]))
if (
    not isinstance(flow_document, dict)
    or flow_document.get("schema") != "fortgym.m1b-control-ssh-flow/v1"
    or flow_document.get("exact_flow_count") != 1
    or not isinstance(flow_document.get("flow"), dict)
):
    raise SystemExit("control SSH evidence contract differs")
control_flow = flow_document["flow"]
entries = document.get("nftables") if isinstance(document, dict) else None
if not isinstance(entries, list):
    raise SystemExit("live nft JSON is malformed")
objects = []
for entry in entries:
    if not isinstance(entry, dict) or len(entry) != 1:
        raise SystemExit("live nft entry is malformed")
    kind, value = next(iter(entry.items()))
    if kind == "metainfo":
        continue
    if not isinstance(value, dict):
        raise SystemExit("live nft object is malformed")
    if value.get("family") == "inet" and value.get(
        "table", value.get("name")
    ) == "fortgym_m1b_outer":
        objects.append((kind, value))

tables = [value for kind, value in objects if kind == "table"]
chains = {value.get("name"): value for kind, value in objects if kind == "chain"}
counters = {value.get("name"): value for kind, value in objects if kind == "counter"}
rules = [value for kind, value in objects if kind == "rule"]
if len(tables) != 1 or set(chains) != {"output", "forward"}:
    raise SystemExit("outer table or chain set differs")
if set(counters) != {"output_denied", "forward_denied"}:
    raise SystemExit("outer named counter set differs")
for name, hook, priority in (("output", "output", -200), ("forward", "forward", -10)):
    chain = chains[name]
    if (
        chain.get("type") != "filter"
        or chain.get("hook") != hook
        or chain.get("prio") != priority
        or chain.get("policy") != "drop"
    ):
        raise SystemExit(f"{name} base-chain fail-close contract differs")

output_rules = [rule for rule in rules if rule.get("chain") == "output"]
forward_rules = [rule for rule in rules if rule.get("chain") == "forward"]
if len(output_rules) != 3 or len(forward_rules) != 1 or len(rules) != 4:
    raise SystemExit("outer rule count differs")


def encoded(rule: dict[str, object]) -> str:
    return json.dumps(rule.get("expr"), sort_keys=True, separators=(",", ":"))


loopback, ssh_reply, output_deny = (encoded(rule) for rule in output_rules)
forward_deny = encoded(forward_rules[0])
if not all(token in loopback for token in ('"oifname"', '"lo"', '"accept"', '"counter"')):
    raise SystemExit("loopback allow rule differs")
if "reject" in loopback:
    raise SystemExit("loopback rule has an unexpected verdict")
expected_ssh_tokens = (
    '"saddr"',
    '"daddr"',
    '"sport"',
    '"dport"',
    '22',
    str(control_flow["server_address"]),
    str(control_flow["client_address"]),
    str(control_flow["client_port"]),
    '"accept"',
)
if control_flow.get("family") not in {"ipv4", "ipv6"}:
    raise SystemExit("control SSH address family differs")
if not all(token in ssh_reply for token in expected_ssh_tokens):
    raise SystemExit("exact SSH control-flow rule differs")
expected_address_token = '"ip"' if control_flow["family"] == "ipv4" else '"ip6"'
wrong_address_token = '"ip6"' if control_flow["family"] == "ipv4" else '"ip"'
if expected_address_token not in ssh_reply or wrong_address_token in ssh_reply:
    raise SystemExit("exact SSH control-flow family differs")
if '"state"' in ssh_reply or '"related"' in ssh_reply or '"udp"' in ssh_reply:
    raise SystemExit("SSH control-flow scope is broader than its exact 4-tuple")
ssh_counter_packets = [
    expression["counter"].get("packets")
    for expression in output_rules[1].get("expr", [])
    if isinstance(expression, dict)
    and isinstance(expression.get("counter"), dict)
    and "name" not in expression["counter"]
]
if (
    len(ssh_counter_packets) != 1
    or isinstance(ssh_counter_packets[0], bool)
    or not isinstance(ssh_counter_packets[0], int)
    or ssh_counter_packets[0] < 1
):
    raise SystemExit("exact SSH control-flow checkpoint was not observed live")
if not all(token in output_deny for token in ('"output_denied"', '"reject"')) or '"accept"' in output_deny:
    raise SystemExit("OUTPUT deny rule differs")
if not all(token in forward_deny for token in ('"forward_denied"', '"reject"')) or '"accept"' in forward_deny:
    raise SystemExit("FORWARD deny rule differs")
if any(rule.get("chain") not in {"output", "forward"} for rule in rules):
    raise SystemExit("unexpected outer rule chain")
PY
}

ssh_rule_counter() {
  local rules_path="$1"
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - "$rules_path" <<'PY'
import json
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
rules = [
    entry["rule"]
    for entry in document.get("nftables", [])
    if isinstance(entry, dict)
    and isinstance(entry.get("rule"), dict)
    and entry["rule"].get("family") == "inet"
    and entry["rule"].get("table") == "fortgym_m1b_outer"
    and entry["rule"].get("chain") == "output"
]
if len(rules) != 3:
    raise SystemExit("outer OUTPUT rule count differs")
packets = [
    expression["counter"].get("packets")
    for expression in rules[1].get("expr", [])
    if isinstance(expression, dict)
    and isinstance(expression.get("counter"), dict)
    and "name" not in expression["counter"]
]
if len(packets) != 1 or isinstance(packets[0], bool) or not isinstance(packets[0], int):
    raise SystemExit("exact SSH rule counter is malformed")
print(packets[0])
PY
}

# Bootstrap evidence is an input capability. Read it no-follow and require the
# exact timer before installing a network rule.
verify_root_evidence_topology
verify_bind_sources_unmounted
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$root_evidence" "$expected_acceptance_sha256" "$authority_expiry" \
  "$expected_runtime_image_id" <<'PY'
import json
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
root_info = root.lstat()
if (
    not stat.S_ISDIR(root_info.st_mode)
    or root_info.st_uid != 0
    or root_info.st_gid != 0
    or stat.S_IMODE(root_info.st_mode) != 0o700
):
    raise SystemExit("root evidence directory ownership or mode differs")
root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
fd = os.open("bootstrap.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
try:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise SystemExit("bootstrap evidence metadata differs")
    with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as handle:
        receipt = json.load(handle)
finally:
    os.close(fd)
    os.close(root_fd)
if (
    receipt.get("schema") != "fortgym.m1b-live-host-bootstrap/v1"
    or receipt.get("ok") is not True
    or receipt.get("acceptance_sha256") != sys.argv[2]
    or receipt.get("authority_expires_at") != sys.argv[3]
    or receipt.get("runtime_image_id") != sys.argv[4]
    or receipt.get("root_broker_is_only_sudo_target") is not True
    or receipt.get("service_user_in_docker_group") is not False
):
    raise SystemExit("bootstrap evidence contract differs")
PY

timer_next="$(/usr/bin/systemctl show fortgym-m1b-expire.timer --value --property NextElapseUSecRealtime)"
if [[ -z "$timer_next" || "$(/usr/bin/date -u -d "$timer_next" +%s)" != "$expiry_epoch" ]]; then
  printf 'expiry timer is absent or differs from the authority boundary\n' >&2
  exit 70
fi
if [[ "$(/usr/bin/systemctl is-active fortgym-m1b-expire.timer)" != active ]]; then
  printf 'expiry timer is not active\n' >&2
  exit 70
fi
if [[ "$mode" == verify-only ]]; then
  if ! /usr/sbin/nft list table inet "$table_name" >/dev/null 2>&1; then
    printf 'outer egress table is absent during post-run verification\n' >&2
    exit 70
  fi
  for evidence_name in control-ssh-flow.json outer-egress.json; do
    evidence_path="$root_evidence/$evidence_name"
    if [[ -L "$evidence_path" || ! -f "$evidence_path" \
      || "$(/usr/bin/stat -c '%U:%G:%a:%h' "$evidence_path")" != root:root:600:1 ]]; then
      printf 'guard input evidence metadata differs: %s\n' "$evidence_name" >&2
      exit 70
    fi
  done
  capture_live_rules "$guard_work/outer-egress-post-run-rules-before.json"
  verify_live_rules \
    "$guard_work/outer-egress-post-run-rules-before.json" \
    "$root_evidence/control-ssh-flow.json"
  post_run_ssh_before="$(
    ssh_rule_counter "$guard_work/outer-egress-post-run-rules-before.json"
  )"
  # This byte must traverse the already-open ControlMaster. A positive delta on
  # only its exact 4-tuple proves DAEMON-RESTART did not sever or broaden it.
  printf 'FORTGYM_M1B_POST_RUN_SSH_CHECKPOINT\n'
  /bin/sleep 1
  capture_live_rules "$guard_work/outer-egress-post-run-rules.json"
  verify_live_rules \
    "$guard_work/outer-egress-post-run-rules.json" \
    "$root_evidence/control-ssh-flow.json"
  post_run_ssh_after="$(
    ssh_rule_counter "$guard_work/outer-egress-post-run-rules.json"
  )"
  if (( post_run_ssh_after - post_run_ssh_before < 1 )); then
    printf 'post-run checkpoint did not increment the exact SSH flow counter\n' >&2
    exit 70
  fi
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - \
    "$root_evidence/outer-egress.json" \
    "$root_evidence/control-ssh-flow.json" \
    "$guard_work/outer-egress-post-run-rules-before.json" \
    "$guard_work/outer-egress-post-run-rules.json" \
    "$guard_work/outer-egress-post-run.json" \
    "$post_run_ssh_before" "$post_run_ssh_after" \
    "$expected_acceptance_sha256" "$authority_expiry" \
    "$guard_work/bind-sources-residue.json" <<'PY'
import datetime
import hashlib
import json
import os
import pathlib
import stat
import sys


def load_root_regular(path: pathlib.Path) -> tuple[dict[str, object], str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise SystemExit(f"guard evidence metadata differs: {path.name}")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise SystemExit(f"guard evidence is not an object: {path.name}")
    return document, hashlib.sha256(raw).hexdigest()


outer, outer_sha256 = load_root_regular(pathlib.Path(sys.argv[1]))
flow, flow_sha256 = load_root_regular(pathlib.Path(sys.argv[2]))
if (
    outer.get("schema") != "fortgym.m1b-outer-egress-guard/v1"
    or outer.get("ok") is not True
    or outer.get("acceptance_sha256") != sys.argv[8]
    or outer.get("authority_expires_at") != sys.argv[9]
    or outer.get("output_policy") != "drop"
    or outer.get("forward_policy") != "drop"
    or outer.get("preserved_non_loopback_flow") != flow
    or outer.get("live_ruleset_verified_before_and_after_canaries") is not True
):
    raise SystemExit("activation guard receipt differs")
before_path = pathlib.Path(sys.argv[3])
after_path = pathlib.Path(sys.argv[4])
before = int(sys.argv[6])
after = int(sys.argv[7])
if after - before < 1:
    raise SystemExit("post-run exact SSH counter delta is absent")
bind_sources_residue = json.loads(pathlib.Path(sys.argv[10]).read_text(encoding="utf-8"))
if (
    set(bind_sources_residue)
    != {
        "schema",
        "ok",
        "mode",
        "path",
        "empty",
        "unmounted",
        "findmnt_returncode",
        "findmnt_stdout_sha256",
        "findmnt_stderr_sha256",
    }
    or bind_sources_residue.get("schema")
    != "fortgym.m1b-bind-sources-residue/v1"
    or bind_sources_residue.get("ok") is not True
    or bind_sources_residue.get("mode") != "verify-only"
    or bind_sources_residue.get("path")
    != "/var/lib/fortgym-m1b-root-evidence/bind-sources"
    or bind_sources_residue.get("empty") is not True
    or bind_sources_residue.get("unmounted") is not True
    or bind_sources_residue.get("findmnt_returncode") != 1
    or bind_sources_residue.get("findmnt_stdout_sha256")
    != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    or bind_sources_residue.get("findmnt_stderr_sha256")
    != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
):
    raise SystemExit("post-run bind-sources residue proof differs")
payload = {
    "schema": "fortgym.m1b-outer-egress-post-run-verification/v1",
    "ok": True,
    "acceptance_sha256": sys.argv[8],
    "authority_expires_at": sys.argv[9],
    "verified_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "verification_mode": "read-only",
    "network_rules_mutated": False,
    "table": "inet fortgym_m1b_outer",
    "output_policy": "drop",
    "forward_policy": "drop",
    "exact_control_ssh_flow_sha256": flow_sha256,
    "activation_guard_receipt_sha256": outer_sha256,
    "exact_ssh_counter_before": before,
    "exact_ssh_counter_after": after,
    "exact_ssh_counter_delta": after - before,
    "rules_before_sha256": hashlib.sha256(before_path.read_bytes()).hexdigest(),
    "rules_after_sha256": hashlib.sha256(after_path.read_bytes()).hexdigest(),
    "bind_sources_residue": bind_sources_residue,
    "provider_calls": 0,
    "provider_cost_usd": 0,
}
target = pathlib.Path(sys.argv[5])
target.write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
target.chmod(0o600)
PY
  for record in \
    outer-egress-post-run-rules-before.json \
    outer-egress-post-run-rules.json \
    outer-egress-post-run.json; do
    atomic_evidence_copy "$guard_work/$record" "$record"
  done
  verify_root_evidence_topology
  verify_bind_sources_unmounted
  printf 'M1b outer egress guard remains exact after the run.\n'
  exit 0
fi
if /usr/sbin/nft list table inet "$table_name" >/dev/null 2>&1; then
  printf 'outer egress table already exists; refusing to replace it\n' >&2
  exit 73
fi

# Discover the one control-master SSH flow that invoked this guard. The cloud
# controller deliberately keeps that TCP flow alive through evidence retrieval;
# every other pre-existing or future non-loopback flow is denied.
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - "$guard_work/control-ssh-flow.json" <<'PY'
import ipaddress
import json
import pathlib
import socket
import sys
import time

target = pathlib.Path(sys.argv[1])
proc_root = pathlib.Path(sys.argv[2]) if len(sys.argv) == 3 else pathlib.Path("/proc")
if len(sys.argv) not in (2, 3):
    raise SystemExit("control SSH flow discovery arguments differ")

def decode_ipv4(raw: str) -> str:
    return socket.inet_ntop(socket.AF_INET, bytes.fromhex(raw)[::-1])

def decode_ipv6(raw: str) -> str:
    packed = b"".join(bytes.fromhex(raw[index : index + 8])[::-1] for index in range(0, 32, 8))
    return socket.inet_ntop(socket.AF_INET6, packed)

def established_ssh_flows() -> list[dict[str, object]]:
    flows = []
    for proc_path, family, decoder in (
        (proc_root / "net/tcp", "ipv4", decode_ipv4),
        (proc_root / "net/tcp6", "ipv6", decode_ipv6),
    ):
        if not proc_path.is_file():
            continue
        for line in proc_path.read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4 or fields[3] != "01":
                continue
            local_raw, peer_raw = fields[1], fields[2]
            local_address_raw, local_port_raw = local_raw.split(":", 1)
            peer_address_raw, peer_port_raw = peer_raw.split(":", 1)
            local_port = int(local_port_raw, 16)
            if local_port != 22:
                continue
            local_ip = ipaddress.ip_address(decoder(local_address_raw))
            peer_ip = ipaddress.ip_address(decoder(peer_address_raw))
            normalized_family = family
            if isinstance(local_ip, ipaddress.IPv6Address):
                if local_ip.ipv4_mapped is not None and peer_ip.ipv4_mapped is not None:
                    local_ip = local_ip.ipv4_mapped
                    peer_ip = peer_ip.ipv4_mapped
                    normalized_family = "ipv4"
                elif (local_ip.ipv4_mapped is None) != (peer_ip.ipv4_mapped is None):
                    raise SystemExit("control SSH flow mixes mapped and native addressing")
            local_address = str(local_ip)
            peer_address = str(peer_ip)
            peer_port = int(peer_port_raw, 16)
            if not 1 <= peer_port <= 65535 or local_address == peer_address:
                raise SystemExit("control SSH flow addressing is invalid")
            flows.append(
                {
                    "family": normalized_family,
                    "server_address": local_address,
                    "server_port": 22,
                    "client_address": peer_address,
                    "client_port": peer_port,
                }
            )
    return flows


deadline = time.monotonic() + 15.0
stable_flow = None
stable_samples = 0
last_count = -1
while True:
    flows = established_ssh_flows()
    last_count = len(flows)
    candidate = flows[0] if len(flows) == 1 else None
    if candidate is not None and candidate == stable_flow:
        stable_samples += 1
    elif candidate is not None:
        stable_flow = candidate
        stable_samples = 1
    else:
        stable_flow = None
        stable_samples = 0
    if stable_samples >= 3:
        break
    if time.monotonic() >= deadline:
        raise SystemExit(
            f"expected one exact established SSH control flow, observed {last_count}"
        )
    time.sleep(0.25)
flows = [stable_flow]
payload = {
    "schema": "fortgym.m1b-control-ssh-flow/v1",
    "exact_flow_count": 1,
    "flow": flows[0],
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
read -r ssh_family ssh_server_address ssh_client_address ssh_client_port < <(
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - "$guard_work/control-ssh-flow.json" <<'PY'
import json
import pathlib
import sys

flow = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["flow"]
print(flow["family"], flow["server_address"], flow["client_address"], flow["client_port"])
PY
)
if [[ "$ssh_family" == ipv4 ]]; then
  ssh_flow_rule="ip saddr $ssh_server_address ip daddr $ssh_client_address tcp sport 22 tcp dport $ssh_client_port counter accept"
elif [[ "$ssh_family" == ipv6 ]]; then
  ssh_flow_rule="ip6 saddr $ssh_server_address ip6 daddr $ssh_client_address tcp sport 22 tcp dport $ssh_client_port counter accept"
else
  printf 'control SSH address family differs\n' >&2
  exit 70
fi

# OUTPUT -200 classifies the caller's original 127/8 destination before Docker
# destination NAT (-100). The only non-loopback allow is the exact SSH 4-tuple.
/usr/bin/printf '%s\n' \
  'table inet fortgym_m1b_outer {' \
  '  counter output_denied {}' \
  '  counter forward_denied {}' \
  '  chain output {' \
  '    type filter hook output priority -200; policy drop;' \
  '    oifname "lo" counter accept' \
  "    $ssh_flow_rule" \
  '    counter name output_denied reject with icmpx type admin-prohibited' \
  '  }' \
  '  chain forward {' \
  '    type filter hook forward priority -10; policy drop;' \
  '    counter name forward_denied reject with icmpx type admin-prohibited' \
  '  }' \
  '}' >"$guard_work/rules.nft"

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/sbin/nft --check --file "$guard_work/rules.nft"
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/sbin/nft --file "$guard_work/rules.nft"
# This literal checkpoint traverses the already-established ControlMaster TCP
# flow. Its rule counter must observe the packet before activation can succeed.
printf 'FORTGYM_M1B_EXACT_SSH_FLOW_CHECKPOINT\n'
/bin/sleep 1

capture_live_rules "$guard_work/rules-before-canary.json"
verify_live_rules "$guard_work/rules-before-canary.json" "$guard_work/control-ssh-flow.json"

counter_value() {
  local counter_name="$1"
  local destination="$2"
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/sbin/nft --json list counter inet "$table_name" "$counter_name" \
    >"$destination"
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/python3 -I - "$destination" "$counter_name" <<'PY'
import json
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
matches = []
for entry in document.get("nftables", []):
    counter = entry.get("counter") if isinstance(entry, dict) else None
    if isinstance(counter, dict) and counter.get("name") == sys.argv[2]:
        matches.append(counter.get("packets"))
if len(matches) != 1 or isinstance(matches[0], bool) or not isinstance(matches[0], int):
    raise SystemExit("named nft counter is absent or malformed")
print(matches[0])
PY
}

output_before="$(counter_value output_denied "$guard_work/output-counter-before.json")"
forward_before="$(counter_value forward_denied "$guard_work/forward-counter-before.json")"

# Prove that pre-DNAT loopback classification still permits the host to reach
# one 127.0.0.1-published container port. This is a tiny fixed TCP responder,
# not a DF runtime attempt. It is compiled locally, cannot initiate traffic,
# and is removed before the proof is accepted.
/bin/cat >"$guard_work/loopback_canary.c" <<'C'
#include <arpa/inet.h>
#include <netinet/in.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(void) {
    const char message[] = "FORTGYM_LOOPBACK_OK\n";
    const int one = 1;
    const int listener = socket(AF_INET, SOCK_STREAM, 0);
    if (listener < 0) return 10;
    if (setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) != 0) return 11;
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons(44991);
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(listener, (const struct sockaddr *)&address, sizeof(address)) != 0) return 12;
    if (listen(listener, 1) != 0) return 13;
    alarm(10);
    const int peer = accept(listener, NULL, NULL);
    if (peer < 0) return 14;
    const ssize_t written = write(peer, message, sizeof(message) - 1U);
    close(peer);
    close(listener);
    return written == (ssize_t)(sizeof(message) - 1U) ? 0 : 15;
}
C
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C SOURCE_DATE_EPOCH=1723766400 \
  /usr/bin/gcc -static -O2 -std=c17 -Wall -Wextra -Werror -Wformat=2 \
  -fstack-protector-strong -D_FORTIFY_SOURCE=3 \
  "$guard_work/loopback_canary.c" -o "$guard_exec_root/loopback-canary"
/bin/chmod 0755 "$guard_exec_root/loopback-canary"

loopback_canary_name=fortgym-m1b-loopback-canary
forward_canary_name=fortgym-m1b-forward-canary
loopback_canary_owned=0
forward_canary_owned=0
capture_docker_name_listing() {
  local container_name="$1"
  local output_prefix="$2"
  local stage="$3"
  local nonempty_exit="$4"
  local returncode

  set +e
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=TERM --kill-after=2s 15s \
    /usr/bin/docker ps --all --quiet --no-trunc \
    --filter "name=^/${container_name}$" \
    >"${output_prefix}.stdout" 2>"${output_prefix}.stderr"
  returncode=$?
  set -e
  /usr/bin/printf '%s\n' "$returncode" >"${output_prefix}.rc"
  if (( returncode != 0 )); then
    printf '%s Docker listing failed with return code %s\n' \
      "$stage" "$returncode" >&2
    return 70
  fi
  if [[ -s "${output_prefix}.stdout" ]]; then
    printf '%s Docker listing was not exactly empty\n' "$stage" >&2
    return "$nonempty_exit"
  fi
}

capture_docker_removal() {
  local container_name="$1"
  local output_prefix="$2"
  local returncode

  set +e
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=TERM --kill-after=2s 15s \
    /usr/bin/docker rm --force "$container_name" \
    >"${output_prefix}.stdout" 2>"${output_prefix}.stderr"
  returncode=$?
  set -e
  /usr/bin/printf '%s\n' "$returncode" >"${output_prefix}.rc"
}

cleanup_security_canaries() {
  if (( loopback_canary_owned == 1 )); then
    /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
      /usr/bin/timeout --signal=TERM --kill-after=2s 15s \
      /usr/bin/docker rm --force "$loopback_canary_name" >/dev/null 2>&1 || true
  fi
  if (( forward_canary_owned == 1 )); then
    /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
      /usr/bin/timeout --signal=TERM --kill-after=2s 15s \
      /usr/bin/docker rm --force "$forward_canary_name" >/dev/null 2>&1 || true
  fi
}
trap cleanup_security_canaries EXIT

capture_docker_name_listing \
  "$loopback_canary_name" "$guard_work/loopback-before" \
  'loopback canary name already exists' 73
loopback_container_id="$(
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
    /usr/bin/docker create \
    --pull never \
    --name "$loopback_canary_name" \
    --network bridge \
    --publish 127.0.0.1:44991:44991/tcp \
    --read-only \
    --memory 32m \
    --memory-swap 32m \
    --pids-limit 8 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --label fortgym.m1b.security-canary=true \
    --mount "type=bind,src=$guard_exec_root/loopback-canary,dst=/fortgym-loopback-canary,readonly" \
    --entrypoint /fortgym-loopback-canary \
    "$expected_runtime_image_id"
)"
if [[ ! "$loopback_container_id" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'loopback canary container identity differs\n' >&2
  exit 70
fi
loopback_canary_owned=1
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 30s \
  /usr/bin/docker start "$loopback_container_id" >/dev/null
set +e
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=TERM --kill-after=2s 5s \
  /usr/bin/pgrep --exact docker-proxy \
  >"$guard_work/docker-proxy.stdout" 2>"$guard_work/docker-proxy.stderr"
docker_proxy_rc=$?
set -e
/usr/bin/printf '%s\n' "$docker_proxy_rc" >"$guard_work/docker-proxy.rc"
if (( docker_proxy_rc == 0 )); then
  printf 'Docker userland proxy remains enabled\n' >&2
  exit 70
fi
if (( docker_proxy_rc != 1 )); then
  printf 'Docker userland proxy process probe failed\n' >&2
  exit 70
fi
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$guard_work/loopback-canary.json" "$guard_exec_root/loopback-canary" \
  "$loopback_container_id" <<'PY'
import hashlib
import json
import pathlib
import socket
import sys
import time

target = pathlib.Path(sys.argv[1])
binary = pathlib.Path(sys.argv[2])
deadline = time.monotonic() + 8.0
observed = b""
last_unexpected = b""
last_error = ""
while time.monotonic() < deadline:
    candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    candidate.settimeout(0.5)
    try:
        candidate.connect(("127.0.0.1", 44991))
        response = bytearray()
        while len(response) < 128:
            chunk = candidate.recv(128 - len(response))
            if not chunk:
                break
            response.extend(chunk)
            if response.endswith(b"\n"):
                break
        observed = bytes(response)
        if observed == b"FORTGYM_LOOPBACK_OK\n":
            break
        last_unexpected = observed
        observed = b""
        last_error = "UnexpectedResponse"
        time.sleep(0.1)
    except OSError as exc:
        last_error = type(exc).__name__
        time.sleep(0.1)
    finally:
        candidate.close()
if observed != b"FORTGYM_LOOPBACK_OK\n":
    detail = (
        f"{last_error} length={len(last_unexpected)} "
        f"sha256={hashlib.sha256(last_unexpected).hexdigest()}"
    )
    raise SystemExit(f"published loopback handshake failed: {detail}")
payload = {
    "schema": "fortgym.m1b-published-loopback-canary/v1",
    "ok": True,
    "container_id": sys.argv[3],
    "host_address": "127.0.0.1",
    "host_port": 44991,
    "response_sha256": hashlib.sha256(observed).hexdigest(),
    "responder_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    "docker_userland_proxy_process_absent": True,
    "real_df_runtime_attempt": False,
    "provider_calls": 0,
    "provider_cost_usd": 0,
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
loopback_wait="$(
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
    /usr/bin/timeout --signal=KILL --kill-after=2s 10s \
    /usr/bin/docker wait "$loopback_container_id"
)"
if [[ "$loopback_wait" != 0 ]]; then
  printf 'loopback canary responder did not exit cleanly\n' >&2
  exit 70
fi
capture_docker_removal \
  "$loopback_canary_name" "$guard_work/loopback-removal"
capture_docker_name_listing \
  "$loopback_canary_name" "$guard_work/loopback-after" \
  'loopback canary residue remains after removal' 70
loopback_canary_owned=0
/bin/rm -f -- "$guard_exec_root/loopback-canary"
/usr/bin/rmdir -- "$guard_exec_root"

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - "$guard_work/canaries.json" <<'PY'
import errno
import json
import pathlib
import socket
import sys

target = pathlib.Path(sys.argv[1])
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(("127.0.0.1", 0))
server.listen(1)
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.settimeout(1.0)
client.connect(server.getsockname())
accepted, _ = server.accept()
accepted.close()
client.close()
server.close()

observations = []
for family, address in (
    (socket.AF_INET, ("198.51.100.10", 443)),
    (socket.AF_INET, ("203.0.113.10", 443)),
    (socket.AF_INET6, ("2001:db8::10", 443, 0, 0)),
):
    candidate = socket.socket(family, socket.SOCK_STREAM)
    candidate.settimeout(1.0)
    try:
        candidate.connect(address)
    except OSError as exc:
        observations.append(
            {
                "family": "ipv4" if family == socket.AF_INET else "ipv6",
                "destination": address[0],
                "port": address[1],
                "blocked": True,
                "errno": exc.errno,
                "error_type": type(exc).__name__,
            }
        )
    else:
        raise SystemExit("outer egress guard allowed a documentation-prefix connect")
    finally:
        candidate.close()
payload = {
    "schema": "fortgym.m1b-outer-egress-canaries/v1",
    "loopback_connect_succeeded": True,
    "negative_canaries": observations,
    "provider_calls": 0,
    "provider_cost_usd": 0,
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY

# Exercise the FORWARD hook with one fixed, root-controlled bridge container.
# The image is already digest-pinned and loaded, --pull=never forbids registry
# fallback, the destination is an IANA documentation address, and the container
# is forcibly removed before its counter observation is accepted.
forward_canary_image="$expected_runtime_image_id"
capture_docker_name_listing \
  "$forward_canary_name" "$guard_work/forward-before" \
  'forward canary name already exists' 73
forward_canary_owned=1
set +e
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/timeout --signal=KILL --kill-after=2s 8s \
  /usr/bin/docker run \
  --pull never \
  --name "$forward_canary_name" \
  --network bridge \
  --memory 64m \
  --memory-swap 64m \
  --pids-limit 16 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --label fortgym.m1b.security-canary=true \
  --entrypoint /bin/bash \
  "$forward_canary_image" \
  -c 'exec 3<>/dev/tcp/198.51.100.10/443' \
  >"$guard_work/forward-canary.stdout" \
  2>"$guard_work/forward-canary.stderr"
forward_canary_returncode=$?
set -e
capture_docker_removal \
  "$forward_canary_name" "$guard_work/forward-removal"
if (( forward_canary_returncode == 0 )); then
  printf 'forward canary unexpectedly reached the documentation address\n' >&2
  exit 70
fi
capture_docker_name_listing \
  "$forward_canary_name" "$guard_work/forward-after" \
  'forward canary residue remains after forced removal' 70
forward_canary_owned=0
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$guard_work/forward-canary.json" "$forward_canary_returncode" <<'PY'
import hashlib
import json
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
stdout = target.parent.joinpath("forward-canary.stdout").read_bytes()
stderr = target.parent.joinpath("forward-canary.stderr").read_bytes()
payload = {
    "schema": "fortgym.m1b-forward-egress-canary/v1",
    "ok": True,
    "container_name": "fortgym-m1b-forward-canary",
    "image": "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c",
    "destination": "198.51.100.10",
    "port": 443,
    "returncode": int(sys.argv[2]),
    "container_absent_after_cleanup": True,
    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
    "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    "provider_calls": 0,
    "provider_cost_usd": 0,
}
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
target.chmod(0o600)
PY

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$guard_work" "$guard_work/docker-canary-lifecycle.json" <<'PY'
import hashlib
import json
import pathlib
import re
import sys

work = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])

def read_bytes(name: str) -> bytes:
    return work.joinpath(name).read_bytes()

def read_returncode(prefix: str) -> int:
    encoded = read_bytes(f"{prefix}.rc")
    if re.fullmatch(rb"(?:0|[1-9][0-9]{0,2})\n", encoded) is None:
        raise SystemExit(f"Docker command return-code record differs: {prefix}")
    value = int(encoded)
    if value > 255:
        raise SystemExit(f"Docker command return code is out of range: {prefix}")
    return value

listings = {}
for name, prefix in (
    ("loopback_before", "loopback-before"),
    ("loopback_after_removal", "loopback-after"),
    ("forward_before", "forward-before"),
    ("forward_after_removal", "forward-after"),
):
    returncode = read_returncode(prefix)
    stdout = read_bytes(f"{prefix}.stdout")
    stderr = read_bytes(f"{prefix}.stderr")
    if returncode != 0 or stdout != b"":
        raise SystemExit(f"Docker exact-name absence proof differs: {name}")
    listings[name] = {
        "returncode": 0,
        "stdout_exact_empty": True,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }

removals = {}
for name, prefix in (
    ("loopback", "loopback-removal"),
    ("forward", "forward-removal"),
):
    stdout = read_bytes(f"{prefix}.stdout")
    stderr = read_bytes(f"{prefix}.stderr")
    removals[name] = {
        "returncode": read_returncode(prefix),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }

payload = {
    "schema": "fortgym.m1b-docker-canary-lifecycle/v1",
    "ok": True,
    "listings": listings,
    "removals": removals,
    "all_absence_listings_returncode_zero": True,
    "all_absence_stdout_exact_empty": True,
    "removal_failure_accepted_only_after_independent_absence": True,
}
target.write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
target.chmod(0o600)
PY

output_after="$(counter_value output_denied "$guard_work/output-counter-after.json")"
forward_after="$(counter_value forward_denied "$guard_work/forward-counter-after.json")"
if (( output_after - output_before < 2 )); then
  printf 'negative canaries did not increment the live OUTPUT deny counter\n' >&2
  exit 70
fi
if (( forward_after - forward_before < 1 )); then
  printf 'bridge canary did not increment the live FORWARD deny counter\n' >&2
  exit 70
fi

capture_live_rules "$guard_work/outer-egress-rules.json"
verify_live_rules "$guard_work/outer-egress-rules.json" "$guard_work/control-ssh-flow.json"

/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /usr/bin/python3 -I - \
  "$guard_work/canaries.json" "$guard_work/forward-canary.json" \
  "$guard_work/loopback-canary.json" \
  "$guard_work/control-ssh-flow.json" \
  "$guard_work/outer-egress.json" \
  "$output_before" "$output_after" "$forward_before" "$forward_after" \
  "$expected_acceptance_sha256" "$guard_work/docker-canary-lifecycle.json" \
  "$guard_work/bind-sources-residue.json" <<'PY'
import datetime
import json
import pathlib
import sys

canaries = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
forward_canary = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
loopback_canary = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
control_ssh_flow = json.loads(pathlib.Path(sys.argv[4]).read_text(encoding="utf-8"))
docker_canary_lifecycle = json.loads(
    pathlib.Path(sys.argv[11]).read_text(encoding="utf-8")
)
bind_sources_residue = json.loads(
    pathlib.Path(sys.argv[12]).read_text(encoding="utf-8")
)
if (
    set(bind_sources_residue)
    != {
        "schema",
        "ok",
        "mode",
        "path",
        "empty",
        "unmounted",
        "findmnt_returncode",
        "findmnt_stdout_sha256",
        "findmnt_stderr_sha256",
    }
    or bind_sources_residue.get("schema")
    != "fortgym.m1b-bind-sources-residue/v1"
    or bind_sources_residue.get("ok") is not True
    or bind_sources_residue.get("mode") != "activate"
    or bind_sources_residue.get("path")
    != "/var/lib/fortgym-m1b-root-evidence/bind-sources"
    or bind_sources_residue.get("empty") is not True
    or bind_sources_residue.get("unmounted") is not True
    or bind_sources_residue.get("findmnt_returncode") != 1
    or bind_sources_residue.get("findmnt_stdout_sha256")
    != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    or bind_sources_residue.get("findmnt_stderr_sha256")
    != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
):
    raise SystemExit("activation bind-sources residue proof differs")
before = int(sys.argv[6])
after = int(sys.argv[7])
payload = {
    "schema": "fortgym.m1b-outer-egress-guard/v1",
    "ok": True,
    "acceptance_sha256": sys.argv[10],
    "activated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "authority_expires_at": "2026-09-06T12:00:00Z",
    "table": "inet fortgym_m1b_outer",
    "output_policy": "drop",
    "forward_policy": "drop",
    "loopback": "allowed",
    "preserved_non_loopback_flow": control_ssh_flow,
    "output_denied_counter_before": before,
    "output_denied_counter_after": after,
    "output_denied_counter_delta": after - before,
    "forward_denied_counter_before": int(sys.argv[8]),
    "forward_denied_counter_after": int(sys.argv[9]),
    "forward_canary": forward_canary,
    "published_loopback_canary": loopback_canary,
    "docker_canary_lifecycle": docker_canary_lifecycle,
    "bind_sources_residue": bind_sources_residue,
    "negative_canaries": canaries["negative_canaries"],
    "loopback_canary": canaries["loopback_connect_succeeded"],
    "live_ruleset_verified_before_and_after_canaries": True,
    "provider_calls": 0,
    "provider_cost_usd": 0,
}
pathlib.Path(sys.argv[5]).write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
pathlib.Path(sys.argv[5]).chmod(0o600)
PY

for record in \
  outer-egress-rules.json \
  output-counter-before.json \
  output-counter-after.json \
  forward-counter-before.json \
  forward-counter-after.json \
  forward-canary.json \
  loopback-canary.json \
  docker-canary-lifecycle.json \
  control-ssh-flow.json \
  canaries.json \
  outer-egress.json; do
  atomic_evidence_copy "$guard_work/$record" "$record"
done

verify_root_evidence_topology
verify_bind_sources_unmounted

trap - EXIT

printf 'M1b outer egress guard active and live-verified.\n'
