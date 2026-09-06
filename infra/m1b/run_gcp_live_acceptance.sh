#!/usr/bin/env bash
set -euo pipefail

# Execute exactly one provider-free M1b acceptance batch on a disposable GCE
# host.  The target identity and resource shape are intentionally constants:
# local gcloud defaults can never select the account, project, or zone.

export LC_ALL=C
umask 077

ACCOUNT='cdossman91@gmail.com'
PROJECT='scrolller-307201'
ZONE='us-central1-a'
REGION='us-central1'
IMAGE_PROJECT='debian-cloud'
IMAGE='debian-12-bookworm-v20260811'
MACHINE_TYPE='e2-standard-16'
PROVISIONING_MODEL='STANDARD'
BOOT_DISK_SIZE='50GB'
BOOT_DISK_TYPE='pd-balanced'
AUTHORITY_DATE='2026-09-05'
AUTHORITY_TIMEZONE='America/New_York'
AUTHORITY_EXPIRY='2026-09-06T12:00:00Z'
AUTHORITY_START_EPOCH=1788580800
AUTHORITY_EXPIRY_EPOCH=1788696000
ACCEPTANCE_SHA256='b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf'
PLAN_SHA256='d37cad75e7e052ed4463353f0b3138f64143ca1e50337e6ad5eb29cbbca47194'
ROOT_BROKER_SHA256='fc89ff2094a70da22bceb22696863e1969d2149a89f42a4e800507d8bc6c591b'
HOST_RUNNER_SHA256='022d99a2bbb319ddb5477a8ce36f0ee0d79f9fc3f471166bd1633ea9b9223d13'
DAILY_CEILING_CENTS=21000
MAX_AUTHORIZED_VM_COUNT=26
MAX_RUN_SECONDS=28800
EXPIRY_SAFETY_SECONDS=900
WATCHDOG_TERM_GRACE_SECONDS=3
GCLOUD_READ_TIMEOUT_SECONDS=30
GCLOUD_MUTATION_TIMEOUT_SECONDS=90
SSH_CONTROL_TIMEOUT_SECONDS=10
SSH_TRANSFER_TIMEOUT_SECONDS=1800
SSH_BOOTSTRAP_TIMEOUT_SECONDS=1800
SSH_GUARD_TIMEOUT_SECONDS=180
SSH_EVIDENCE_TIMEOUT_SECONDS=1800
CLEANUP_POLL_INTERVAL_SECONDS=5

# This deliberately overstates the observed standard-instance estimate.  It
# reserves $8 for the whole eight-hour envelope: $0.75/hour compute, $0.02/hour
# ephemeral IPv4, $0.30/GiB-month balanced disk using a conservative 672-hour
# month, plus more than $1.65 unallocated contingency.  A reservation is never
# released because the final provider invoice is outside this bounded pass.
WORST_CASE_COMPUTE_CENTS=600
WORST_CASE_IPV4_CENTS=16
WORST_CASE_DISK_CENTS=18
WORST_CASE_CONTINGENCY_CENTS=166
WORST_CASE_TOTAL_CENTS=800

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
PACKET_DIR=''
MANIFEST_SHA256=''
EVIDENCE_DIR=''
DAILY_LEDGER_DIR=''
RUN_ID=''
TWO_FORT_DIAGNOSTIC=0

INSTANCE_NAME=''
BATCH_ID=''
LABELS=''
MAX_DURATION_SECONDS=0
REMOTE_IP=''
REMOTE_PACKET_DIR=''
SSH_USER='fortgymctl'
SSH_KEY=''
KNOWN_HOSTS=''
CONTROL_PATH=''
TEMP_DIR=''
GCLOUD_BIN=''
SSH_BIN=''
SCP_BIN=''
CONTROL_MASTER_SUPERVISOR_PID=''
CONTROL_MASTER_CHILD_PID_FILE=''
CONTROL_MASTER_SUPERVISOR_READY_FILE=''
CONTROL_MASTER_SUPERVISOR_STATUS_FILE=''
CONTROL_MASTER_SUPERVISOR_RC=-1
CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED=0
TEMP_DIR_ABSENCE_VERIFIED=0

CREATE_ATTEMPTED=0
CREATE_SUCCEEDED=0
CREATE_OPERATION_NAME=''
CREATE_OPERATION_CAPTURED=0
CREATE_OPERATION_TERMINAL=0
CREATE_OPERATION_STATUS='not-attempted'
CREATE_OPERATION_BASELINE_FILE=''
COST_RESERVED=0
CONTROL_MASTER_STARTED=0
CONTROL_MASTER_CLOSED=0
BOOTSTRAP_SUCCEEDED=0
GUARD_SUCCEEDED=0
RUNNER_SUCCEEDED=0
RUNNER_EXIT_CODE=-1
DECISION_RECORDED=0
M1B_DECISION='not-recorded'
EVIDENCE_COLLECTED=0
SEALED_HOST_OUTCOME_VERIFIED=0
POST_SEAL_HOST_CLEANUP_VERIFIED=0
BROKER_ATTESTATION_VERIFIED=0
GCLOUD_IDENTITY_ENV_VERIFIED=0
DELETE_ATTEMPTED=0
DELETE_COMMAND_ATTEMPTS=0
DELETE_COMMAND_RETURNCODES=''
DELETE_RC=-1
DISK_DELETE_COMMAND_ATTEMPTS=0
DISK_DELETE_COMMAND_RETURNCODES=''
DISK_DELETE_RC=-1
CLEANUP_VERIFIED=0
INSTANCE_RESIDUE='not-checked'
DISK_RESIDUE='not-checked'
ADDRESS_RESIDUE='not-checked'
LEDGER_LOCK=''
LEDGER_LOCK_OWNED=0
FAILURE_STAGE='argument-validation'
EXIT_TRIGGER_STAGE='argument-validation'

usage() {
  cat >&2 <<'EOF'
usage: run_gcp_live_acceptance.sh \
  --packet-dir ABSOLUTE_FINAL_PACKET_DIR \
  --manifest-sha256 LOWERCASE_SHA256_OF_MANIFEST_FILE \
  --evidence-dir ABSOLUTE_NEW_LOCAL_EVIDENCE_DIR \
  --daily-ledger-dir ABSOLUTE_LOCAL_LEDGER_DIR \
  --run-id UNIQUE_12_LOWERCASE_HEX [--two-fort-diagnostic]
EOF
  exit 64
}

die() {
  printf 'M1b lifecycle refusal: %s\n' "$1" >&2
  exit "${2:-77}"
}

sha256_file() {
  sha256sum --binary -- "$1" | awk '{print $1}'
}

now_iso() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

resolve_external_commands() {
  GCLOUD_BIN="$(type -P gcloud || true)"
  SSH_BIN="$(type -P ssh || true)"
  SCP_BIN="$(type -P scp || true)"
  [[ "$GCLOUD_BIN" == /* && -x "$GCLOUD_BIN" ]] \
    || die 'gcloud executable is absent or unsafe' 69
  [[ "$SSH_BIN" == /* && -x "$SSH_BIN" ]] \
    || die 'ssh executable is absent or unsafe' 69
  [[ "$SCP_BIN" == /* && -x "$SCP_BIN" ]] \
    || die 'scp executable is absent or unsafe' 69
}

validate_local_command_environment() {
  local name value configured_real
  local -a forbidden=(
    CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE
    CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT
    CLOUDSDK_PYTHON
    CLOUDSDK_PYTHON_SITEPACKAGES
    SSL_CERT_FILE
    REQUESTS_CA_BUNDLE
    HTTPS_PROXY
    HTTP_PROXY
    NO_PROXY
    https_proxy
    http_proxy
    no_proxy
    ALL_PROXY
    all_proxy
    FTP_PROXY
    ftp_proxy
  )
  for name in "${forbidden[@]}"; do
    value="${!name:-}"
    [[ -z "$value" ]] \
      || die "redirecting command environment is forbidden: $name" 77
  done
  [[ "${HOME:-}" == /* && -d "$HOME" && ! -L "$HOME" ]] \
    || die 'HOME is not one absolute non-symlink directory' 77
  if [[ -n "${TMPDIR:-}" ]]; then
    [[ "$TMPDIR" == /* && -d "$TMPDIR" && ! -L "$TMPDIR" ]] \
      || die 'TMPDIR is not one absolute non-symlink directory' 77
  fi
  if [[ -n "${CLOUDSDK_CONFIG:-}" ]]; then
    [[ "$CLOUDSDK_CONFIG" == /* && -d "$CLOUDSDK_CONFIG" \
       && ! -L "$CLOUDSDK_CONFIG" ]] \
      || die 'CLOUDSDK_CONFIG is not one absolute non-symlink directory' 77
    configured_real="$(realpath -- "$CLOUDSDK_CONFIG")"
    [[ "$configured_real" == "$CLOUDSDK_CONFIG" ]] \
      || die 'CLOUDSDK_CONFIG contains unresolved path components' 77
  fi
  if [[ -n "${FORTGYM_WATCHDOG_CAP_SECONDS:-}" \
        || -n "${FORTGYM_WATCHDOG_CAP_LABEL:-}" ]]; then
    [[ "${FORTGYM_WATCHDOG_CAP_SECONDS:-}" =~ ^[1-9][0-9]*$ \
       && "${FORTGYM_WATCHDOG_CAP_SECONDS}" -le 28800 \
       && "${FORTGYM_WATCHDOG_CAP_LABEL:-}" \
          =~ ^[a-z][a-z0-9-]{0,63}$ ]] \
      || die 'local watchdog test cap pair is invalid' 64
  fi
}

watchdog_effective_limit() {
  local configured="$1"
  local label="$2"
  local cap="${FORTGYM_WATCHDOG_CAP_SECONDS:-}"
  local cap_label="${FORTGYM_WATCHDOG_CAP_LABEL:-}"
  local now remaining
  now="$(date -u +%s)"
  [[ "$now" =~ ^[0-9]+$ ]] || return 1
  remaining=$((AUTHORITY_EXPIRY_EPOCH - now - WATCHDOG_TERM_GRACE_SECONDS - 1))
  if (( remaining <= 0 )); then
    printf '0\n'
    return 0
  fi
  if (( configured > remaining )); then
    configured="$remaining"
  fi
  if [[ -n "$cap" || -n "$cap_label" ]]; then
    [[ "$cap_label" == "$label" ]] \
      || {
        printf '%s\n' "$configured"
        return 0
      }
    [[ "$cap" =~ ^[1-9][0-9]*$ && "$cap" -le "$configured" ]] \
      || die 'local watchdog cap is invalid or would widen a stage limit' 64
    printf '%s\n' "$cap"
  else
    printf '%s\n' "$configured"
  fi
}

authority_bounded_sleep() {
  local seconds="$1" now remaining
  [[ "$seconds" =~ ^[1-9][0-9]*$ ]] || return 1
  now="$(date -u +%s)"
  [[ "$now" =~ ^[0-9]+$ ]] || return 1
  remaining=$((AUTHORITY_EXPIRY_EPOCH - now - WATCHDOG_TERM_GRACE_SECONDS - 1))
  (( remaining > seconds )) || return 1
  /bin/sleep "$seconds"
}

run_with_watchdog() {
  local label="$1"
  local configured_limit="$2"
  local executable="$3"
  shift 3
  local effective_limit
  effective_limit="$(watchdog_effective_limit "$configured_limit" "$label")" \
    || return 124
  if [[ "$effective_limit" -eq 0 ]]; then
    append_event local_watchdog_deadline_exhausted "label=$label"
    return 124
  fi
  python3 -I - \
    "$label" "$effective_limit" "$WATCHDOG_TERM_GRACE_SECONDS" \
    "$EVIDENCE_DIR/watchdog-events.jsonl" "$executable" "$@" <<'PY'
import datetime
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time

label = sys.argv[1]
maximum_seconds = int(sys.argv[2])
term_grace_seconds = int(sys.argv[3])
evidence_path = pathlib.Path(sys.argv[4])
executable = sys.argv[5]
argv = [executable, *sys.argv[6:]]
if (
    re.fullmatch(r"[a-z][a-z0-9-]{0,63}", label) is None
    or not 1 <= maximum_seconds <= 28_800
    or not 1 <= term_grace_seconds <= 10
    or not pathlib.Path(executable).is_absolute()
):
    raise SystemExit("invalid local watchdog contract")

source_env = os.environ
command_dir = str(pathlib.Path(executable).resolve().parent)
safe_path = ":".join(
    dict.fromkeys(
        (
            command_dir,
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        )
    )
)
allowed = {
    "HOME",
    "TMPDIR",
    "CLOUDSDK_CONFIG",
}
child_env = {key: source_env[key] for key in allowed if key in source_env}
for key, value in source_env.items():
    if key.startswith("FAKE_"):
        child_env[key] = value
child_env.update(
    {
        "PATH": safe_path,
        "LC_ALL": "C",
        "LANG": "C",
        "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
    }
)

started = time.monotonic()
timed_out = False
term_sent = False
kill_sent = False
reaped = False
returncode = 127
process = None


def stop_child_group() -> None:
    global term_sent, kill_sent, reaped, returncode
    if process is None or process.poll() is not None:
        if process is not None:
            returncode = process.returncode
            reaped = True
        return
    term_sent = True
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        returncode = process.wait(timeout=term_grace_seconds)
    except subprocess.TimeoutExpired:
        kill_sent = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            returncode = process.wait(timeout=term_grace_seconds)
        except subprocess.TimeoutExpired:
            returncode = 125
            reaped = False
            return
    reaped = True


def interrupted(signum: int, _frame: object) -> None:
    stop_child_group()
    raise SystemExit(128 + signum)


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGHUP, interrupted)
try:
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=child_env,
    )
    try:
        returncode = process.wait(timeout=maximum_seconds)
        reaped = True
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_child_group()
        returncode = 124
except OSError as exc:
    print(f"watchdog could not start {label}: {exc}", file=sys.stderr)
finally:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    record = {
        "schema": "fortgym.m1b-local-process-watchdog/v1",
        "label": label,
        "executable": pathlib.Path(executable).name,
        "maximum_seconds": maximum_seconds,
        "term_grace_seconds": term_grace_seconds,
        "timed_out": timed_out,
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "reaped": reaped,
        "returncode": returncode,
        "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
        "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    descriptor = os.open(
        evidence_path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
if timed_out:
    print(f"local watchdog timed out: {label}", file=sys.stderr)
raise SystemExit(returncode if 0 <= returncode <= 255 else 128 + abs(returncode))
PY
}

gcloud() {
  local timeout="$GCLOUD_READ_TIMEOUT_SECONDS"
  local label='gcloud-read'
  local first="${1:-}" second="${2:-}" third="${3:-}"
  if [[ "$first" == compute && ( \
        ( "$second" == instances && ( "$third" == create || "$third" == delete ) ) \
        || ( "$second" == disks && "$third" == delete ) ) ]]; then
    timeout="$GCLOUD_MUTATION_TIMEOUT_SECONDS"
    label="gcloud-$second-$third"
  fi
  run_with_watchdog "$label" "$timeout" "$GCLOUD_BIN" "$@"
}

bounded_ssh() {
  local label="$1" timeout="$2"
  shift 2
  run_with_watchdog "$label" "$timeout" "$SSH_BIN" "$@"
}

bounded_scp() {
  local label="$1" timeout="$2"
  shift 2
  run_with_watchdog "$label" "$timeout" "$SCP_BIN" "$@"
}

remaining_runner_timeout() {
  local now remaining
  now="$(date -u +%s)"
  [[ "$now" =~ ^[0-9]+$ ]] || die 'UTC clock did not return an epoch' 70
  remaining=$((AUTHORITY_EXPIRY_EPOCH - now - EXPIRY_SAFETY_SECONDS))
  (( remaining > 0 )) || die 'no authority remains for the host runner' 77
  if (( remaining > MAX_RUN_SECONDS )); then
    remaining="$MAX_RUN_SECONDS"
  fi
  printf '%s\n' "$remaining"
}

launch_control_master_supervisor() {
  local maximum_seconds="$1"
  shift
  maximum_seconds="$(watchdog_effective_limit "$maximum_seconds" ssh-master)" \
    || return 124
  if [[ "$maximum_seconds" -eq 0 ]]; then
    append_event local_watchdog_deadline_exhausted 'label=ssh-master'
    return 124
  fi
  [[ ! -e "$CONTROL_MASTER_CHILD_PID_FILE" \
     && ! -e "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
     && ! -e "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" ]] || return 1
  CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED=0
  python3 -I - \
    "$maximum_seconds" "$WATCHDOG_TERM_GRACE_SECONDS" \
    "$EVIDENCE_DIR/watchdog-events.jsonl" "$CONTROL_MASTER_CHILD_PID_FILE" \
    "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
    "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" "$SSH_BIN" "$@" <<'PY' &
import datetime
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time

maximum_seconds = int(sys.argv[1])
term_grace_seconds = int(sys.argv[2])
evidence_path = pathlib.Path(sys.argv[3])
child_pid_path = pathlib.Path(sys.argv[4])
ready_path = pathlib.Path(sys.argv[5])
status_path = pathlib.Path(sys.argv[6])
executable = sys.argv[7]
argv = [executable, *sys.argv[8:]]
command_dir = str(pathlib.Path(executable).resolve().parent)
safe_path = ":".join(
    dict.fromkeys(
        (
            command_dir,
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        )
    )
)
child_env = {
    key: os.environ[key]
    for key in ("HOME", "TMPDIR", "CLOUDSDK_CONFIG")
    if key in os.environ
}
for key, value in os.environ.items():
    if key.startswith("FAKE_"):
        child_env[key] = value
child_env.update({"PATH": safe_path, "LC_ALL": "C", "LANG": "C"})

started = time.monotonic()
process = None
timed_out = False
term_sent = False
kill_sent = False
reaped = False
returncode = 127
failure = None
supervisor_pid = os.getpid()
process_group_id = None


def stop_child() -> None:
    global term_sent, kill_sent, reaped, returncode
    if process is None or process.poll() is not None:
        if process is not None:
            returncode = process.returncode
            reaped = True
        return
    term_sent = True
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        returncode = process.wait(timeout=term_grace_seconds)
    except subprocess.TimeoutExpired:
        kill_sent = True
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            returncode = process.wait(timeout=term_grace_seconds)
        except subprocess.TimeoutExpired:
            returncode = 125
            reaped = False
            return
    reaped = True


def interrupted(signum: int, _frame: object) -> None:
    global returncode
    stop_child()
    returncode = 128 + signum
    raise SystemExit(returncode)


def write_json_atomic(target: pathlib.Path, payload: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


try:
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    if os.environ.get("FAKE_SUPERVISOR_PRE_READY_HANG") == "1":
        while True:
            time.sleep(1)
    os.setsid()
    process_group_id = os.getpgrp()
    if process_group_id != supervisor_pid:
        raise OSError("control-master supervisor failed to become its group leader")
    write_json_atomic(
        ready_path,
        {
            "schema": "fortgym.m1b-ssh-master-supervisor-ready/v1",
            "ready": True,
            "supervisor_pid": supervisor_pid,
            "process_group_id": process_group_id,
            "child_spawned": False,
        },
    )
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        env=child_env,
    )
    descriptor = os.open(
        child_pid_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(f"{process.pid}\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        returncode = process.wait(timeout=maximum_seconds)
        reaped = True
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_child()
        returncode = 124 if reaped else 125
except SystemExit:
    raise
except BaseException as exc:
    failure = type(exc).__name__
    stop_child()
    if returncode == 127:
        returncode = 126
finally:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    record = {
        "schema": "fortgym.m1b-local-process-watchdog/v1",
        "label": "ssh-master",
        "executable": pathlib.Path(executable).name,
        "maximum_seconds": maximum_seconds,
        "term_grace_seconds": term_grace_seconds,
        "timed_out": timed_out,
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "reaped": reaped,
        "returncode": returncode,
        "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
        "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    descriptor = os.open(
        evidence_path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    status = {
        "schema": "fortgym.m1b-ssh-master-supervisor/v1",
        "final": True,
        "supervisor_pid": supervisor_pid,
        "process_group_id": process_group_id,
        "process_started": process is not None,
        "child_pid": process.pid if process is not None else None,
        "child_reaped": reaped,
        "timed_out": timed_out,
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "returncode": returncode,
        "failure": failure,
        "watchdog_record_written": True,
    }
    write_json_atomic(status_path, status)
raise SystemExit(returncode if 0 <= returncode <= 255 else 128 + abs(returncode))
PY
  CONTROL_MASTER_SUPERVISOR_PID=$!
  local poll
  for poll in $(seq 1 5); do
    if [[ -f "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
          && ! -L "$CONTROL_MASTER_SUPERVISOR_READY_FILE" ]] \
        && python3 -I - "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
          "$CONTROL_MASTER_SUPERVISOR_PID" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
pid = int(sys.argv[2])
if payload != {
    "schema": "fortgym.m1b-ssh-master-supervisor-ready/v1",
    "ready": True,
    "supervisor_pid": pid,
    "process_group_id": pid,
    "child_spawned": False,
}:
    raise SystemExit("control-master supervisor ready identity differs")
PY
    then
      kill -0 -- "-$CONTROL_MASTER_SUPERVISOR_PID" 2>/dev/null || return 1
      return 0
    fi
    kill -0 "$CONTROL_MASTER_SUPERVISOR_PID" 2>/dev/null || return 1
    authority_bounded_sleep 1 || return 1
  done
  return 1
}

stop_control_master_supervisor() {
  local request_term="$1"
  local poll supervisor_pid status_result status_rc status_process_started=0
  local shell_reap_rc=-1 expected_shell_rc
  local supervisor_pid_absent=0 supervisor_group_absent=0 socket_absent=1
  local status_verified=0 ready_verified=0 pre_ready_stopped=0 completion_verified=0
  CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED=0
  supervisor_pid="$CONTROL_MASTER_SUPERVISOR_PID"
  if [[ -z "$supervisor_pid" ]]; then
    [[ ! -e "$CONTROL_MASTER_CHILD_PID_FILE" \
       && ! -e "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
       && ! -e "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" \
       && ! -e "$CONTROL_PATH" ]] || return 1
    CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED=1
    return 0
  fi
  [[ "$supervisor_pid" =~ ^[1-9][0-9]*$ ]] || return 1
  if [[ "$request_term" -eq 1 ]]; then
    for poll in $(seq 1 2); do
      if [[ -e "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" ]] \
          || ( ! kill -0 "$supervisor_pid" 2>/dev/null \
               && ! kill -0 -- "-$supervisor_pid" 2>/dev/null ); then
        break
      fi
      authority_bounded_sleep 1 || break
    done
    if kill -0 "$supervisor_pid" 2>/dev/null \
        && [[ ! -e "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" ]]; then
      kill -TERM "$supervisor_pid" 2>/dev/null || true
    fi
  fi
  for poll in $(seq 1 5); do
    if ! kill -0 "$supervisor_pid" 2>/dev/null \
        && ! kill -0 -- "-$supervisor_pid" 2>/dev/null; then
      break
    fi
    authority_bounded_sleep 1 || break
  done
  if kill -0 -- "-$supervisor_pid" 2>/dev/null; then
    kill -KILL -- "-$supervisor_pid" 2>/dev/null || true
  elif kill -0 "$supervisor_pid" 2>/dev/null; then
    kill -KILL "$supervisor_pid" 2>/dev/null || true
  fi
  for poll in $(seq 1 5); do
    if ! kill -0 "$supervisor_pid" 2>/dev/null \
        && ! kill -0 -- "-$supervisor_pid" 2>/dev/null; then
      break
    fi
    authority_bounded_sleep 1 || break
  done
  if ! kill -0 "$supervisor_pid" 2>/dev/null; then
    supervisor_pid_absent=1
  fi
  if ! kill -0 -- "-$supervisor_pid" 2>/dev/null; then
    supervisor_group_absent=1
  fi
  if [[ "$supervisor_pid_absent" -eq 1 \
        && "$supervisor_group_absent" -eq 1 ]]; then
    # Both positive PID and exact PGID are absent, so this direct-child wait is
    # a nonblocking status reap rather than an open-ended process wait.
    if wait "$supervisor_pid" 2>/dev/null; then
      shell_reap_rc=0
    else
      shell_reap_rc=$?
    fi
  fi

  if [[ -f "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
        && ! -L "$CONTROL_MASTER_SUPERVISOR_READY_FILE" ]]; then
    if python3 -I - "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
        "$supervisor_pid" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
pid = int(sys.argv[2])
if payload != {
    "schema": "fortgym.m1b-ssh-master-supervisor-ready/v1",
    "ready": True,
    "supervisor_pid": pid,
    "process_group_id": pid,
    "child_spawned": False,
}:
    raise SystemExit("control-master supervisor ready identity differs")
PY
    then
      ready_verified=1
    fi
  fi

  if [[ -f "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" \
        && ! -L "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" ]]; then
    if status_result="$(python3 -I - "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" \
        "$supervisor_pid" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
supervisor_pid = int(sys.argv[2])
payload = json.loads(path.read_text(encoding="utf-8"))
expected = {
    "schema",
    "final",
    "supervisor_pid",
    "process_group_id",
    "process_started",
    "child_pid",
    "child_reaped",
    "timed_out",
    "term_sent",
    "kill_sent",
    "returncode",
    "failure",
    "watchdog_record_written",
}
if not isinstance(payload, dict) or set(payload) != expected:
    raise SystemExit("control-master supervisor status fields differ")
if (
    payload.get("schema") != "fortgym.m1b-ssh-master-supervisor/v1"
    or payload.get("final") is not True
    or payload.get("supervisor_pid") != supervisor_pid
    or not isinstance(payload.get("process_started"), bool)
    or not isinstance(payload.get("child_reaped"), bool)
    or any(
        not isinstance(payload.get(key), bool)
        for key in (
            "timed_out",
            "term_sent",
            "kill_sent",
            "watchdog_record_written",
        )
    )
    or payload.get("watchdog_record_written") is not True
    or not isinstance(payload.get("returncode"), int)
    or isinstance(payload.get("returncode"), bool)
    or not -255 <= payload["returncode"] <= 255
    or payload.get("failure") not in {None, "OSError"}
):
    raise SystemExit("control-master supervisor status differs")
if payload["process_started"]:
    if (
        payload.get("process_group_id") != supervisor_pid
        or
        not isinstance(payload.get("child_pid"), int)
        or isinstance(payload.get("child_pid"), bool)
        or payload["child_pid"] <= 0
        or payload["child_reaped"] is not True
    ):
        raise SystemExit("control-master child was not durably reaped")
elif (
    payload.get("process_group_id") not in {None, supervisor_pid}
    or payload.get("child_pid") is not None
    or payload["child_reaped"] is not False
):
    raise SystemExit("control-master no-child status differs")
print(f"{payload['returncode']}|{int(payload['process_started'])}")
PY
)"; then
      status_rc="${status_result%%|*}"
      status_process_started="${status_result#*|}"
      CONTROL_MASTER_SUPERVISOR_RC="$status_rc"
      status_verified=1
      expected_shell_rc="$status_rc"
      if [[ "$expected_shell_rc" -lt 0 ]]; then
        expected_shell_rc=$((128 + -expected_shell_rc))
      fi
      if [[ "$shell_reap_rc" -ne "$expected_shell_rc" ]]; then
        status_verified=0
      fi
    fi
  fi

  if [[ "$status_verified" -eq 1 && "$status_process_started" -eq 1 \
        && "$ready_verified" -eq 1 ]]; then
    completion_verified=1
  elif [[ "$status_verified" -eq 1 && "$status_process_started" -eq 0 ]]; then
    completion_verified=1
  elif [[ "$status_verified" -eq 0 && "$ready_verified" -eq 0 \
          && ! -e "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
          && ! -e "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" \
          && "$supervisor_pid_absent" -eq 1 \
          && "$supervisor_group_absent" -eq 1 ]]; then
    pre_ready_stopped=1
    completion_verified=1
    CONTROL_MASTER_SUPERVISOR_RC=137
  fi

  if [[ "$supervisor_pid_absent" -eq 1 \
        && "$supervisor_group_absent" -eq 1 \
        && "$completion_verified" -eq 1 ]]; then
    if [[ -e "$CONTROL_MASTER_CHILD_PID_FILE" ]]; then
      rm -f -- "$CONTROL_MASTER_CHILD_PID_FILE" || socket_absent=0
    fi
    if [[ -e "$CONTROL_MASTER_SUPERVISOR_READY_FILE" ]]; then
      rm -f -- "$CONTROL_MASTER_SUPERVISOR_READY_FILE" || socket_absent=0
    fi
    if [[ -e "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" ]]; then
      rm -f -- "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" || socket_absent=0
    fi
    if [[ -e "$CONTROL_PATH" ]]; then
      rm -f -- "$CONTROL_PATH" || socket_absent=0
    fi
    if [[ -e "$CONTROL_PATH" || -e "$CONTROL_MASTER_CHILD_PID_FILE" \
          || -e "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
          || -e "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" ]]; then
      socket_absent=0
    fi
  fi
  if [[ "$supervisor_pid_absent" -eq 1 \
        && "$supervisor_group_absent" -eq 1 \
        && "$completion_verified" -eq 1 && "$socket_absent" -eq 1 ]]; then
    CONTROL_MASTER_SUPERVISOR_PID=''
    CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED=1
    append_event ssh_control_master_local_absence_verified \
      "supervisor=true child_process_group=true control_path=true pre_ready_stopped=$pre_ready_stopped"
    return 0
  fi
  return 1
}

refresh_max_duration() {
  local now remaining
  now="$(date -u +%s)"
  [[ "$now" =~ ^[0-9]+$ ]] || die 'UTC clock did not return an epoch' 70
  (( now >= AUTHORITY_START_EPOCH )) \
    || die 'infrastructure authority is not active yet' 77
  remaining=$((AUTHORITY_EXPIRY_EPOCH - now - EXPIRY_SAFETY_SECONDS))
  (( remaining > 0 )) \
    || die 'infrastructure authority is expired or too close to expiry' 77
  if (( remaining < MAX_RUN_SECONDS )); then
    MAX_DURATION_SECONDS="$remaining"
  else
    MAX_DURATION_SECONDS="$MAX_RUN_SECONDS"
  fi
  (( MAX_DURATION_SECONDS > 0 && MAX_DURATION_SECONDS <= MAX_RUN_SECONDS )) \
    || die 'provider duration cannot fit inside the authority window' 77
}

append_event() {
  local event="$1"
  local detail="$2"
  python3 -I - "$EVIDENCE_DIR/lifecycle-events.jsonl" "$event" "$detail" \
    "$(now_iso)" <<'PY'
import json
import os
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
record = {
    "schema": "fortgym.m1b-cloud-lifecycle-event/v1",
    "event": sys.argv[2],
    "detail": sys.argv[3],
    "recorded_at": sys.argv[4],
}
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
with os.fdopen(fd, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    handle.flush()
    os.fsync(handle.fileno())
PY
}

release_ledger_lock() {
  if [[ "$LEDGER_LOCK_OWNED" -eq 1 && -n "$LEDGER_LOCK" ]]; then
    rmdir -- "$LEDGER_LOCK" >/dev/null 2>&1 || true
    LEDGER_LOCK_OWNED=0
  fi
}

write_receipt() {
  local exit_code="$1"
  local status='failed'
  if [[ "$exit_code" -eq 0 && "$RUNNER_SUCCEEDED" -eq 1 \
        && "$EVIDENCE_COLLECTED" -eq 1 \
        && "$SEALED_HOST_OUTCOME_VERIFIED" -eq 1 \
        && "$POST_SEAL_HOST_CLEANUP_VERIFIED" -eq 1 \
        && "$BROKER_ATTESTATION_VERIFIED" -eq 1 \
        && "$CLEANUP_VERIFIED" -eq 1 ]]; then
    status='complete'
  fi
  python3 -I - \
    "$EVIDENCE_DIR/lifecycle-receipt.json" \
    "$status" "$exit_code" "$EXIT_TRIGGER_STAGE" "$RUN_ID" "$INSTANCE_NAME" \
    "$BATCH_ID" "$MANIFEST_SHA256" "$MAX_DURATION_SECONDS" \
    "$COST_RESERVED" "$CONTROL_MASTER_STARTED" "$CONTROL_MASTER_CLOSED" \
    "$CREATE_ATTEMPTED" "$CREATE_SUCCEEDED" "$BOOTSTRAP_SUCCEEDED" \
    "$GUARD_SUCCEEDED" "$RUNNER_SUCCEEDED" "$RUNNER_EXIT_CODE" \
    "$DECISION_RECORDED" "$M1B_DECISION" "$EVIDENCE_COLLECTED" \
    "$SEALED_HOST_OUTCOME_VERIFIED" \
    "$POST_SEAL_HOST_CLEANUP_VERIFIED" \
    "$BROKER_ATTESTATION_VERIFIED" \
    "$DELETE_ATTEMPTED" "$DELETE_COMMAND_ATTEMPTS" \
    "$DELETE_COMMAND_RETURNCODES" "$DELETE_RC" \
    "$DISK_DELETE_COMMAND_ATTEMPTS" \
    "$DISK_DELETE_COMMAND_RETURNCODES" "$DISK_DELETE_RC" \
    "$CLEANUP_VERIFIED" \
    "$INSTANCE_RESIDUE" "$DISK_RESIDUE" "$ADDRESS_RESIDUE" \
    "$CREATE_OPERATION_NAME" "$CREATE_OPERATION_CAPTURED" \
    "$CREATE_OPERATION_TERMINAL" "$CREATE_OPERATION_STATUS" \
    "$GCLOUD_IDENTITY_ENV_VERIFIED" \
    "$CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED" \
    "$CONTROL_MASTER_SUPERVISOR_PID" \
    "$TEMP_DIR_ABSENCE_VERIFIED" "$(now_iso)" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile

target = pathlib.Path(sys.argv[1])

delete_attempted = bool(int(sys.argv[25]))
delete_command_attempts = int(sys.argv[26])
delete_command_returncodes = (
    [int(item) for item in sys.argv[27].split(",")] if sys.argv[27] else []
)
delete_command_rc = int(sys.argv[28])
disk_delete_command_attempts = int(sys.argv[29])
disk_delete_command_returncodes = (
    [int(item) for item in sys.argv[30].split(",")] if sys.argv[30] else []
)
disk_delete_command_rc = int(sys.argv[31])
if (
    delete_attempted is not (delete_command_attempts > 0)
    or len(delete_command_returncodes) != delete_command_attempts
    or any(not 0 <= value <= 255 for value in delete_command_returncodes)
    or (
        delete_command_returncodes
        and delete_command_rc != delete_command_returncodes[-1]
    )
    or (not delete_command_returncodes and delete_command_rc != -1)
):
    raise SystemExit("delete-attempt receipt accounting differs")
if (
    len(disk_delete_command_returncodes) != disk_delete_command_attempts
    or any(not 0 <= value <= 255 for value in disk_delete_command_returncodes)
    or (
        disk_delete_command_returncodes
        and disk_delete_command_rc != disk_delete_command_returncodes[-1]
    )
    or (not disk_delete_command_returncodes and disk_delete_command_rc != -1)
):
    raise SystemExit("disk-delete receipt accounting differs")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


artifact_digests = {}
for path in sorted(target.parent.iterdir(), key=lambda item: item.name):
    if path.name in {target.name, "lifecycle-receipt.sha256"}:
        continue
    if path.is_symlink():
        raise SystemExit(f"refusing symlink in local lifecycle evidence: {path.name}")
    if path.is_file():
        artifact_digests[path.name] = sha256_file(path)
gcp_cli_call_attempts = 0
watchdog_path = target.parent / "watchdog-events.jsonl"
if watchdog_path.is_file() and not watchdog_path.is_symlink():
    for line_number, raw in enumerate(
        watchdog_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            watchdog_record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid watchdog evidence line {line_number}") from exc
        if watchdog_record.get("executable") == "gcloud":
            gcp_cli_call_attempts += 1
payload = {
    "schema": "fortgym.m1b-gcp-lifecycle-receipt/v1",
    "status": sys.argv[2],
    "exit_code": int(sys.argv[3]),
    "last_stage": sys.argv[4],
    "target": {
        "account": "cdossman91@gmail.com",
        "project": "scrolller-307201",
        "zone": "us-central1-a",
        "instance_name": sys.argv[6],
        "run_id": sys.argv[5],
        "batch_id": sys.argv[7],
    },
    "packet_manifest_sha256": sys.argv[8],
    "authority": {
        "authorized_local_date": "2026-09-05",
        "timezone": "America/New_York",
        "expires_at": "2026-09-06T12:00:00Z",
        "daily_ceiling_cents": 21000,
        "authorized_vm_count": 26,
        "reserved_worst_case_cents": 800 if bool(int(sys.argv[10])) else 0,
        "cost_reservation_recorded": bool(int(sys.argv[10])),
        "max_run_duration_seconds": int(sys.argv[9]),
        "paid_models": "forbidden",
        "production_access": "forbidden",
        "production_mutation": "forbidden",
        "paid_model_provider_calls": 0,
        "paid_model_provider_cost_usd": 0,
        "gcp_cli_call_attempts": gcp_cli_call_attempts,
    },
    "control_transport": {
        "single_ssh_control_master_started": bool(int(sys.argv[11])),
        "single_ssh_control_master_closed": bool(int(sys.argv[12])),
        "supervisor_child_group_and_socket_absence_verified": bool(
            int(sys.argv[41])
        ),
        "unresolved_supervisor_process_group_id": (
            int(sys.argv[42]) if sys.argv[42] else None
        ),
        "ephemeral_temp_directory_absence_verified": bool(int(sys.argv[43])),
        "post_guard_new_tcp_connections_authorized": False,
    },
    "execution": {
        "create_attempted": bool(int(sys.argv[13])),
        "create_succeeded": bool(int(sys.argv[14])),
        "create_operation_name": sys.argv[36],
        "create_operation_captured": bool(int(sys.argv[37])),
        "create_operation_terminal": bool(int(sys.argv[38])),
        "create_operation_status": sys.argv[39],
        "bootstrap_succeeded": bool(int(sys.argv[15])),
        "outer_egress_guard_succeeded": bool(int(sys.argv[16])),
        "runner_succeeded": bool(int(sys.argv[17])),
        "runner_exit_code": int(sys.argv[18]),
        "runner_decision_recorded": bool(int(sys.argv[19])),
        "evidence_collected": bool(int(sys.argv[21])),
        "sealed_host_outcome_verified": bool(int(sys.argv[22])),
        "post_seal_host_cleanup_verified": bool(int(sys.argv[23])),
        "root_broker_attestation_verified": bool(int(sys.argv[24])),
    },
    "m1b_outcome": {
        "decision": sys.argv[20],
        "is_go": sys.argv[20] == "GO",
        "distinct_from_lifecycle_status": True,
    },
    "cleanup": {
        "delete_attempted": delete_attempted,
        "delete_command_attempts": delete_command_attempts,
        "delete_command_returncodes": delete_command_returncodes,
        "delete_command_rc": delete_command_rc,
        "disk_delete_attempted": disk_delete_command_attempts > 0,
        "disk_delete_command_attempts": disk_delete_command_attempts,
        "disk_delete_command_returncodes": disk_delete_command_returncodes,
        "disk_delete_command_rc": disk_delete_command_rc,
        "absence_verified": bool(int(sys.argv[32])),
        "instance_residue": sys.argv[33],
        "disk_residue": sys.argv[34],
        "address_residue": sys.argv[35],
    },
    "local_artifacts_sha256": artifact_digests,
    "identity_environment_verified": bool(int(sys.argv[40])),
    "sealed_at": sys.argv[44],
}
seal = target.with_name("lifecycle-receipt.sha256")
for published in (target, seal):
    if published.is_symlink() or published.exists():
        raise SystemExit(f"refusing pre-existing receipt artifact: {published.name}")

receipt_temporary = None
seal_temporary = None
receipt_published = False
seal_published = False
try:
    fd, receipt_temporary = tempfile.mkstemp(
        prefix=".lifecycle-receipt.", dir=target.parent
    )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(receipt_temporary, 0o600)
    digest = sha256_file(pathlib.Path(receipt_temporary))
    fd, seal_temporary = tempfile.mkstemp(
        prefix=".lifecycle-receipt-seal.", dir=target.parent
    )
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(f"{digest}  {target.name}\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(seal_temporary, 0o600)
    if pathlib.Path(seal_temporary).read_text(encoding="ascii") != (
        f"{digest}  {target.name}\n"
    ):
        raise RuntimeError("temporary lifecycle receipt seal differs")
    os.replace(receipt_temporary, target)
    receipt_temporary = None
    receipt_published = True
    if os.environ.get("FAKE_RECEIPT_FAIL_AFTER_JSON") == "1":
        raise RuntimeError("forced failure after lifecycle receipt publication")
    os.replace(seal_temporary, seal)
    seal_temporary = None
    seal_published = True
    directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    if (
        target.is_symlink()
        or seal.is_symlink()
        or not target.is_file()
        or not seal.is_file()
        or sha256_file(target) != digest
        or seal.read_text(encoding="ascii") != f"{digest}  {target.name}\n"
    ):
        raise RuntimeError("published lifecycle receipt pair did not verify")
except BaseException:
    for published, was_published in (
        (seal, seal_published),
        (target, receipt_published),
    ):
        if was_published:
            try:
                published.unlink()
            except FileNotFoundError:
                pass
    try:
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        pass
    raise
finally:
    for temporary in (receipt_temporary, seal_temporary):
        if temporary is None:
            continue
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
PY
}

verify_lifecycle_receipt_pair() {
  local expected_exit_code="$1"
  local receipt="$EVIDENCE_DIR/lifecycle-receipt.json"
  local seal="$EVIDENCE_DIR/lifecycle-receipt.sha256"
  local digest sealed_line
  [[ -f "$receipt" && ! -L "$receipt" && -f "$seal" && ! -L "$seal" ]] \
    || return 1
  digest="$(sha256_file "$receipt")" || return 1
  IFS= read -r sealed_line <"$seal" || return 1
  [[ "$sealed_line" == "$digest  lifecycle-receipt.json" ]] || return 1
  python3 -I - "$receipt" "$expected_exit_code" <<'PY'
import json
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
expected_exit_code = int(sys.argv[2])
try:
    payload = json.loads(target.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("published lifecycle receipt is malformed") from exc
if payload.get("schema") != "fortgym.m1b-gcp-lifecycle-receipt/v1":
    raise SystemExit("published lifecycle receipt schema differs")
expected_status = "complete" if expected_exit_code == 0 else "failed"
if payload.get("status") != expected_status:
    raise SystemExit("published lifecycle receipt status differs")
if payload.get("exit_code") != expected_exit_code or isinstance(
    payload.get("exit_code"), bool
):
    raise SystemExit("published lifecycle receipt exit code differs")
PY
}

gcloud_delete_and_verify() {
  local instance_output disk_output address_output
  local attempt instance_query_ok disk_query_ok address_query_ok
  local instance_exact_present disk_exact_present
  local should_delete_instance=1
  local should_delete_disk=0
  local consecutive_empty_observations=0
  DELETE_ATTEMPTED=1
  for attempt in $(seq 1 12); do
    if [[ "$should_delete_instance" -eq 1 ]]; then
      DELETE_COMMAND_ATTEMPTS=$((DELETE_COMMAND_ATTEMPTS + 1))
      if gcloud compute instances delete "$INSTANCE_NAME" \
          --account="$ACCOUNT" \
          --project="$PROJECT" \
          --zone="$ZONE" \
          --delete-disks=all \
          --quiet; then
        DELETE_RC=0
      else
        DELETE_RC=$?
      fi
      if [[ -z "$DELETE_COMMAND_RETURNCODES" ]]; then
        DELETE_COMMAND_RETURNCODES="$DELETE_RC"
      else
        DELETE_COMMAND_RETURNCODES+=",$DELETE_RC"
      fi
      append_event delete_attempt \
        "command_attempt=$DELETE_COMMAND_ATTEMPTS convergence_attempt=$attempt rc=$DELETE_RC"
    fi
    if [[ "$should_delete_disk" -eq 1 ]]; then
      DISK_DELETE_COMMAND_ATTEMPTS=$((DISK_DELETE_COMMAND_ATTEMPTS + 1))
      if gcloud compute disks delete "$INSTANCE_NAME" \
          --account="$ACCOUNT" \
          --project="$PROJECT" \
          --zone="$ZONE" \
          --quiet; then
        DISK_DELETE_RC=0
      else
        DISK_DELETE_RC=$?
      fi
      if [[ -z "$DISK_DELETE_COMMAND_RETURNCODES" ]]; then
        DISK_DELETE_COMMAND_RETURNCODES="$DISK_DELETE_RC"
      else
        DISK_DELETE_COMMAND_RETURNCODES+=",$DISK_DELETE_RC"
      fi
      append_event disk_delete_attempt \
        "command_attempt=$DISK_DELETE_COMMAND_ATTEMPTS convergence_attempt=$attempt rc=$DISK_DELETE_RC"
    fi

    instance_query_ok=1
    disk_query_ok=1
    address_query_ok=1
    instance_exact_present=0
    disk_exact_present=0
    if ! instance_output="$(gcloud compute instances list \
        --account="$ACCOUNT" \
        --project="$PROJECT" \
        --zones="$ZONE" \
        --filter="(name=$INSTANCE_NAME) OR (labels.fortgym-run-id=$RUN_ID)" \
        --format='value(name)' 2>/dev/null)"; then
      instance_query_ok=0
      INSTANCE_RESIDUE='verification-command-failed'
    elif [[ -z "$instance_output" ]]; then
      INSTANCE_RESIDUE='none'
    elif [[ "$instance_output" == "$INSTANCE_NAME" ]]; then
      INSTANCE_RESIDUE="$INSTANCE_NAME"
      instance_exact_present=1
    else
      INSTANCE_RESIDUE="unexpected-or-ambiguous:$instance_output"
    fi
    if ! disk_output="$(gcloud compute disks list \
        --account="$ACCOUNT" \
        --project="$PROJECT" \
        --zones="$ZONE" \
        --filter="name=$INSTANCE_NAME" \
        --format='value(name)' 2>/dev/null)"; then
      disk_query_ok=0
      DISK_RESIDUE='verification-command-failed'
    elif [[ -z "$disk_output" ]]; then
      DISK_RESIDUE='none'
    elif [[ "$disk_output" == "$INSTANCE_NAME" ]]; then
      DISK_RESIDUE="$INSTANCE_NAME"
      disk_exact_present=1
    else
      DISK_RESIDUE="unexpected-or-ambiguous:$disk_output"
    fi
    if ! address_output="$(gcloud compute addresses list \
        --account="$ACCOUNT" \
        --project="$PROJECT" \
        --regions="$REGION" \
        --filter="(name=$INSTANCE_NAME) OR (labels.fortgym-run-id=$RUN_ID)" \
        --format='value(name)' 2>/dev/null)"; then
      address_query_ok=0
      ADDRESS_RESIDUE='verification-command-failed'
    else
      ADDRESS_RESIDUE="${address_output:-none}"
    fi
    should_delete_instance=0
    should_delete_disk=0
    if [[ "$instance_query_ok" -ne 1 || "$instance_exact_present" -eq 1 ]]; then
      should_delete_instance=1
    elif [[ "$INSTANCE_RESIDUE" == none && "$disk_query_ok" -eq 1 \
            && "$disk_exact_present" -eq 1 ]]; then
      should_delete_disk=1
    fi
    if [[ "$instance_query_ok" -eq 1 && "$disk_query_ok" -eq 1 \
          && "$address_query_ok" -eq 1 && "$INSTANCE_RESIDUE" == none \
          && "$DISK_RESIDUE" == none && "$ADDRESS_RESIDUE" == none ]]; then
      consecutive_empty_observations=$((consecutive_empty_observations + 1))
      append_event cleanup_empty_observation \
        "convergence_attempt=$attempt consecutive=$consecutive_empty_observations"
      if [[ "$CREATE_OPERATION_TERMINAL" -eq 1 \
            && "$consecutive_empty_observations" -ge 2 ]]; then
        CLEANUP_VERIFIED=1
        append_event cleanup_verified \
          "terminal_create_operation=true stable_empty_observations=$consecutive_empty_observations convergence_attempt=$attempt instance_delete_commands=$DELETE_COMMAND_ATTEMPTS last_instance_delete_rc=$DELETE_RC disk_delete_commands=$DISK_DELETE_COMMAND_ATTEMPTS last_disk_delete_rc=$DISK_DELETE_RC"
        return 0
      fi
      if [[ "$CREATE_OPERATION_TERMINAL" -ne 1 \
            && "$consecutive_empty_observations" -ge 2 ]]; then
        append_event cleanup_incomplete \
          "create operation is not terminal; stable empty residue cannot close an ambiguous insert"
        return 1
      fi
    else
      consecutive_empty_observations=0
    fi
    if [[ "$INSTANCE_RESIDUE" == unexpected-or-ambiguous:* \
          || "$DISK_RESIDUE" == unexpected-or-ambiguous:* \
          || ( "$ADDRESS_RESIDUE" != none \
               && "$ADDRESS_RESIDUE" != verification-command-failed ) ]]; then
      append_event cleanup_incomplete \
        "ambiguous or non-ephemeral residue prevents exact bounded deletion"
      return 1
    fi
    if [[ "$attempt" -lt 12 && "$should_delete_instance" -eq 0 \
          && "$should_delete_disk" -eq 0 ]]; then
      authority_bounded_sleep "$CLEANUP_POLL_INTERVAL_SECONDS" || break
    fi
  done
  append_event cleanup_incomplete \
    "create_operation_terminal=$CREATE_OPERATION_TERMINAL create_operation_status=$CREATE_OPERATION_STATUS stable_empty_observations=$consecutive_empty_observations instance=$INSTANCE_RESIDUE disk=$DISK_RESIDUE address=$ADDRESS_RESIDUE instance_delete_commands=$DELETE_COMMAND_ATTEMPTS last_instance_delete_rc=$DELETE_RC disk_delete_commands=$DISK_DELETE_COMMAND_ATTEMPTS last_disk_delete_rc=$DISK_DELETE_RC"
  return 1
}

extract_evidence_tar() {
  python3 -I - "$1" "$2" <<'PY'
import pathlib
import shutil
import tarfile
import sys

archive_path = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
allowed = (
    "fortgym-m1b/evidence",
    "fortgym-m1b/broker/claims",
    "fortgym-m1b/broker/grants",
    "fortgym-m1b/broker/receipts",
    "fortgym-m1b-root-evidence",
)
maximum_files = 100_000
maximum_member_bytes = 2 * 1024 * 1024 * 1024
maximum_total_bytes = 8 * 1024 * 1024 * 1024
with tarfile.open(archive_path, mode="r:") as archive:
    members = archive.getmembers()
    if not members or len(members) > maximum_files:
        raise SystemExit("remote evidence archive is empty")
    seen = set()
    total_bytes = 0
    for member in members:
        original = member.name
        path = pathlib.PurePosixPath(original)
        if (
            not original
            or original.startswith("/")
            or path.is_absolute()
            or original != path.as_posix()
            or any(part in ("", ".", "..") for part in path.parts)
        ):
            raise SystemExit(f"unsafe evidence member: {member.name}")
        name = path.as_posix()
        if name in seen:
            raise SystemExit(f"duplicate evidence member: {member.name}")
        seen.add(name)
        if not any(name == root or name.startswith(root + "/") for root in allowed):
            raise SystemExit(f"unexpected evidence member: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"non-regular evidence member: {member.name}")
        if member.size < 0 or member.size > maximum_member_bytes:
            raise SystemExit(f"oversized evidence member: {member.name}")
        total_bytes += member.size
        if total_bytes > maximum_total_bytes:
            raise SystemExit("remote evidence archive exceeds the aggregate byte limit")
        target = destination.joinpath(*path.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit(f"unreadable evidence member: {member.name}")
        with source, target.open("wb") as handle:
            shutil.copyfileobj(source, handle)
        target.chmod(0o600)
    if not set(allowed).issubset(seen):
        raise SystemExit("remote evidence archive lacks a required evidence root")
PY
}

validate_sealed_host_outcome() {
  local batch_root="$1"
  local normalized="$EVIDENCE_DIR/sealed-host-outcome-verified.json"
  if ! python3 -I - \
    "$batch_root" "$normalized" "$EVIDENCE_DIR/host-runner-stdout.json" \
    "$BATCH_ID" "$ACCEPTANCE_SHA256" "$PLAN_SHA256" \
    "$SCRIPT_DIR/acceptance.yaml" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import tempfile

batch_root = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
host_outcome_path = pathlib.Path(sys.argv[3])
batch_id, acceptance_sha256, plan_sha256 = sys.argv[4:7]
contract_path = pathlib.Path(sys.argv[7])
sha256_pattern = re.compile(r"[0-9a-f]{64}")
code_pattern = re.compile(r"[a-z][a-z0-9_]{0,127}")
path_part_pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
expected_gate_ids = [
    "PORT-1",
    "PORT-2",
    "COLD-RETRY",
    "CO-8",
    "DF-KILL",
    "HARNESS-KILL",
    "OOM",
    "ENOSPC",
    "CONTAINER-RESTART",
    "DAEMON-RESTART",
    "ORPHAN-1",
    "ORPHAN-2",
    "PROVIDER-ENV",
    "PROVIDER-NET",
    "CAP-FAKE",
    "CLEANUP",
]
local_credit_scopes = {
    "PORT-1": "complete_local_gate",
    "ORPHAN-1": "local_subprocedure",
    "PROVIDER-ENV": "complete_local_gate",
    "CAP-FAKE": "complete_local_gate",
}
pass_local_gates = {"PORT-1", "PROVIDER-ENV", "CAP-FAKE"}


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_regular_json(
    path: pathlib.Path, *, maximum_bytes: int = 32 * 1024 * 1024
) -> tuple[dict[str, object], str]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"sealed host JSON is absent: {path.name}") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size < 2
        or info.st_size > maximum_bytes
    ):
        raise SystemExit(f"sealed host JSON is unsafe or oversized: {path.name}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"sealed host JSON is malformed: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"sealed host JSON is not an object: {path.name}")
    return payload, hashlib.sha256(raw).hexdigest()


def bounded_integer(value: object, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def reference_list(value: object, *, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > 4096:
        raise SystemExit(f"{label} evidence references are not a bounded list")
    references = []
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size_bytes"}:
            raise SystemExit(f"{label} evidence reference fields differ")
        raw_path = item.get("path")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        path = pathlib.PurePosixPath(raw_path) if isinstance(raw_path, str) else None
        if (
            path is None
            or not raw_path
            or raw_path.startswith("/")
            or raw_path != path.as_posix()
            or any(
                part in {"", ".", ".."} or path_part_pattern.fullmatch(part) is None
                for part in path.parts
            )
            or len(raw_path) > 512
            or not isinstance(digest, str)
            or sha256_pattern.fullmatch(digest) is None
            or not bounded_integer(size, 0, 1024 * 1024 * 1024)
            or raw_path in seen
        ):
            raise SystemExit(f"{label} evidence reference is invalid")
        seen.add(raw_path)
        references.append(dict(item))
    return references


try:
    raw_outcome = host_outcome_path.read_text(encoding="utf-8")
except (OSError, UnicodeDecodeError) as exc:
    raise SystemExit("host runner outcome is unreadable") from exc
outcome_lines = raw_outcome.splitlines()
if len(outcome_lines) != 1 or not outcome_lines[0]:
    raise SystemExit("host runner outcome is not exactly one JSON line")
try:
    host_outcome = json.loads(outcome_lines[0])
except json.JSONDecodeError as exc:
    raise SystemExit("host runner outcome JSON is malformed") from exc
outcome_keys = {
    "schema",
    "batch_id",
    "decision",
    "real_runtime_attempts_started",
    "real_runtime_attempts_completed",
    "non_runtime_attempts_started",
    "non_runtime_attempts_completed",
    "gate_results_path",
    "decision_path",
    "evidence_manifest_path",
    "seal_path",
    "post_seal_cleanup_path",
    "post_seal_cleanup_sha256",
    "broker_attestation_path",
    "broker_attestation_sha256",
    "broker_attestation_reference_path",
    "broker_attestation_reference_sha256",
    "broker_attestation_receipt_path",
    "broker_attestation_receipt_sha256",
}
control_remote = f"/var/lib/fortgym-m1b/evidence/{batch_id}/control"
batch_remote = f"/var/lib/fortgym-m1b/evidence/{batch_id}"
root_attestation_remote = (
    f"/var/lib/fortgym-m1b-root-evidence/batches/{batch_id}/broker-attestation.json"
)
public_receipt_pattern = re.compile(
    rf"{re.escape(batch_remote)}/broker-client/CLEANUP/[0-9a-f]{{64}}\.json"
)
if not isinstance(host_outcome, dict) or set(host_outcome) != outcome_keys or (
    host_outcome.get("schema") != "fortgym.m1b-host-runner-outcome/v1"
    or host_outcome.get("batch_id") != batch_id
    or host_outcome.get("decision") not in {"GO", "INCOMPLETE_NO_GO"}
    or host_outcome.get("gate_results_path") != f"{control_remote}/gate-results.json"
    or host_outcome.get("decision_path") != f"{control_remote}/decision.json"
    or host_outcome.get("evidence_manifest_path")
    != f"{control_remote}/evidence-manifest.json"
    or host_outcome.get("seal_path") != f"{control_remote}/seal.json"
    or host_outcome.get("post_seal_cleanup_path")
    != f"{batch_remote}/post-seal-host-cleanup.json"
    or host_outcome.get("broker_attestation_path") != root_attestation_remote
    or host_outcome.get("broker_attestation_reference_path")
    != f"{batch_remote}/root-broker-attestation-reference.json"
    or not isinstance(host_outcome.get("broker_attestation_receipt_path"), str)
    or public_receipt_pattern.fullmatch(
        str(host_outcome.get("broker_attestation_receipt_path"))
    )
    is None
):
    raise SystemExit("host runner outcome identity or paths differ")
for key in (
    "post_seal_cleanup_sha256",
    "broker_attestation_sha256",
    "broker_attestation_reference_sha256",
    "broker_attestation_receipt_sha256",
):
    if not isinstance(host_outcome.get(key), str) or sha256_pattern.fullmatch(
        str(host_outcome.get(key))
    ) is None:
        raise SystemExit(f"host runner content address is invalid: {key}")
for key, maximum in (
    ("real_runtime_attempts_started", 26),
    ("real_runtime_attempts_completed", 26),
    ("non_runtime_attempts_started", 1),
    ("non_runtime_attempts_completed", 1),
):
    if not bounded_integer(host_outcome.get(key), 0, maximum):
        raise SystemExit(f"host runner attempt count is invalid: {key}")

control_root = batch_root / "control"
gate_results_path = control_root / "gate-results.json"
decision_path = control_root / "decision.json"
manifest_path = control_root / "evidence-manifest.json"
seal_path = control_root / "seal.json"
gate_results, gate_results_sha256 = load_regular_json(gate_results_path)
decision, decision_sha256 = load_regular_json(decision_path)
manifest, manifest_sha256 = load_regular_json(manifest_path)
seal, seal_sha256 = load_regular_json(seal_path)
post_cleanup_path = batch_root / "post-seal-host-cleanup.json"
reference_path = batch_root / "root-broker-attestation-reference.json"
receipt_path = batch_root / "broker-client" / "CLEANUP" / pathlib.PurePosixPath(
    str(host_outcome["broker_attestation_receipt_path"])
).name
for key, path in (
    ("post_seal_cleanup_sha256", post_cleanup_path),
    ("broker_attestation_reference_sha256", reference_path),
    ("broker_attestation_receipt_sha256", receipt_path),
):
    _payload, observed = load_regular_json(path)
    if host_outcome.get(key) != observed:
        raise SystemExit(f"host runner content address differs: {key}")
try:
    contract_info = contract_path.lstat()
except OSError as exc:
    raise SystemExit("local frozen acceptance contract is absent") from exc
if (
    not stat.S_ISREG(contract_info.st_mode)
    or contract_info.st_nlink != 1
    or sha256_file(contract_path) != acceptance_sha256
):
    raise SystemExit("local frozen acceptance contract digest differs")
seal_keys = {
    "schema",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "decision",
    "gate_results_sha256",
    "decision_sha256",
    "evidence_manifest_sha256",
}
if set(seal) != seal_keys or (
    seal.get("schema") != "fortgym.m1b-live-acceptance-seal/v1"
    or seal.get("batch_id") != batch_id
    or seal.get("acceptance_sha256") != acceptance_sha256
    or seal.get("plan_sha256") != plan_sha256
    or seal.get("decision") != host_outcome.get("decision")
    or seal.get("gate_results_sha256") != gate_results_sha256
    or seal.get("decision_sha256") != decision_sha256
    or seal.get("evidence_manifest_sha256") != manifest_sha256
):
    raise SystemExit("controller seal identity or content addresses differ")

gate_results_keys = {
    "schema",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "gates",
}
rows = gate_results.get("gates")
if set(gate_results) != gate_results_keys or (
    gate_results.get("schema") != "fortgym.m1b-live-acceptance-gate-results/v1"
    or gate_results.get("batch_id") != batch_id
    or gate_results.get("acceptance_sha256") != acceptance_sha256
    or gate_results.get("plan_sha256") != plan_sha256
    or not isinstance(rows, list)
    or len(rows) != 16
):
    raise SystemExit("sealed gate-results schema or identity differs")

gate_objects = []
planned_attempt_ids = []
planned_real = 0
planned_non_runtime = 0
for index, (expected_id, row) in enumerate(zip(expected_gate_ids, rows), start=1):
    if not isinstance(row, dict) or not isinstance(row.get("gate"), dict):
        raise SystemExit("sealed gate-results row is not an object")
    gate = row["gate"]
    if set(gate) != {
        "index",
        "id",
        "class",
        "procedure",
        "pass",
        "attempts",
        "local_credit_scope",
        "derived",
        "hard",
    } or (
        gate.get("index") != index
        or isinstance(gate.get("index"), bool)
        or gate.get("id") != expected_id
        or not isinstance(gate.get("class"), str)
        or not gate.get("class")
        or not isinstance(gate.get("procedure"), str)
        or not gate.get("procedure")
        or not isinstance(gate.get("pass"), dict)
        or not gate.get("pass")
        or gate.get("local_credit_scope") != local_credit_scopes.get(expected_id)
        or gate.get("derived") is not (expected_id == "CLEANUP")
        or gate.get("hard") is not True
    ):
        raise SystemExit(f"sealed gate contract differs: {expected_id}")
    attempts = gate.get("attempts")
    if not isinstance(attempts, list):
        raise SystemExit(f"sealed gate attempt plan is not a list: {expected_id}")
    for slot, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict) or set(attempt) != {
            "attempt_id",
            "kind",
            "role",
        }:
            raise SystemExit(f"sealed attempt slot fields differ: {expected_id}")
        role = attempt.get("role")
        kind = attempt.get("kind")
        expected_attempt_id = f"g{index:02d}-a{slot:02d}-{role}"
        if (
            not isinstance(role, str)
            or code_pattern.fullmatch(role) is None
            or kind not in {"real_runtime", "non_runtime_conflict"}
            or attempt.get("attempt_id") != expected_attempt_id
            or expected_attempt_id in planned_attempt_ids
        ):
            raise SystemExit(f"sealed attempt slot identity differs: {expected_id}")
        planned_attempt_ids.append(expected_attempt_id)
        planned_real += kind == "real_runtime"
        planned_non_runtime += kind == "non_runtime_conflict"
    gate_objects.append(gate)

try:
    plan_bytes = json.dumps(
        {
            "schema": "fortgym.m1b-live-acceptance-plan/v1",
            "acceptance_sha256": acceptance_sha256,
            "max_real_runtime_attempts": 26,
            "required_cleanup_passes": 2,
            "gates": gate_objects,
        },
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
except (TypeError, ValueError) as exc:
    raise SystemExit("sealed gate plan is not canonical JSON") from exc
if (
    hashlib.sha256(plan_bytes).hexdigest() != plan_sha256
    or planned_real != 26
    or planned_non_runtime != 1
):
    raise SystemExit("sealed 16-gate/26-slot plan digest or accounting differs")

row_references = []
failed_gate_ids = []
derived_counts = {
    "real_runtime_attempts_started": 0,
    "real_runtime_attempts_completed": 0,
    "non_runtime_attempts_started": 0,
    "non_runtime_attempts_completed": 0,
}
row_keys = {
    "gate",
    "status",
    "criteria_passed",
    "failure_code",
    "evidence",
    "local_credit",
    "attempts",
    "authorization_identity_sha256",
    "attempt_ledger_head_sha256",
}
attempt_summary_keys = {
    "planned",
    "started",
    "completed",
    "real_runtime_started",
    "real_runtime_completed",
    "non_runtime_started",
    "non_runtime_completed",
}
for expected_id, row, gate in zip(expected_gate_ids, rows, gate_objects):
    if set(row) != row_keys:
        raise SystemExit(f"sealed gate-result row fields differ: {expected_id}")
    expected_passing_status = "PASS_LOCAL" if expected_id in pass_local_gates else "PASS"
    status_value = row.get("status")
    if status_value not in {"PASS", "PASS_LOCAL", "FAIL", "NOT_RUN"}:
        raise SystemExit(f"sealed gate status is invalid: {expected_id}")
    criteria = row.get("criteria_passed")
    expected_criteria = set(gate["pass"])
    if (
        not isinstance(criteria, list)
        or any(not isinstance(item, str) for item in criteria)
        or len(criteria) != len(set(criteria))
        or not set(criteria).issubset(expected_criteria)
    ):
        raise SystemExit(f"sealed gate criteria are invalid: {expected_id}")
    evidence = reference_list(row.get("evidence"), label=f"gate {expected_id}")
    if status_value == expected_passing_status:
        if (
            set(criteria) != expected_criteria
            or len(criteria) != len(expected_criteria)
            or row.get("failure_code") is not None
            or not evidence
        ):
            raise SystemExit(f"sealed passing gate is contradictory: {expected_id}")
    elif status_value == "FAIL":
        failure_code = row.get("failure_code")
        if not isinstance(failure_code, str) or code_pattern.fullmatch(failure_code) is None:
            raise SystemExit(f"sealed failed gate lacks a safe code: {expected_id}")
    elif status_value == "NOT_RUN":
        if criteria or row.get("failure_code") != "not_run" or evidence:
            raise SystemExit(f"sealed not-run gate is contradictory: {expected_id}")
    else:
        raise SystemExit(f"sealed gate uses the wrong pass status: {expected_id}")
    if status_value != expected_passing_status:
        failed_gate_ids.append(expected_id)
    row_references.extend(evidence)

    expected_scope = local_credit_scopes.get(expected_id)
    local_credit = row.get("local_credit")
    if expected_scope is None:
        if local_credit is not None:
            raise SystemExit(f"sealed gate has an unexpected local credit: {expected_id}")
    else:
        if not isinstance(local_credit, dict) or set(local_credit) != {
            "gate_id",
            "scope",
            "criteria_passed",
            "evidence",
        }:
            raise SystemExit(f"sealed local credit fields differ: {expected_id}")
        local_criteria = local_credit.get("criteria_passed")
        local_evidence = reference_list(
            local_credit.get("evidence"), label=f"local credit {expected_id}"
        )
        if (
            local_credit.get("gate_id") != expected_id
            or local_credit.get("scope") != expected_scope
            or not isinstance(local_criteria, list)
            or any(not isinstance(item, str) for item in local_criteria)
            or len(local_criteria) != len(set(local_criteria))
            or set(local_criteria) != expected_criteria
            or not local_evidence
        ):
            raise SystemExit(f"sealed local credit contract differs: {expected_id}")
        row_references.extend(local_evidence)

    authorization = row.get("authorization_identity_sha256")
    if expected_id == "ENOSPC":
        if authorization is not None and (
            not isinstance(authorization, str)
            or sha256_pattern.fullmatch(authorization) is None
        ):
            raise SystemExit("sealed ENOSPC authorization identity is invalid")
        if status_value == "PASS" and authorization is None:
            raise SystemExit("sealed passing ENOSPC gate lacks its authorization identity")
    elif authorization is not None:
        raise SystemExit(f"sealed non-ENOSPC gate exposes authorization: {expected_id}")
    ledger_head = row.get("attempt_ledger_head_sha256")
    if not isinstance(ledger_head, str) or sha256_pattern.fullmatch(ledger_head) is None:
        raise SystemExit(f"sealed gate ledger head is invalid: {expected_id}")

    summary = row.get("attempts")
    if not isinstance(summary, dict) or set(summary) != attempt_summary_keys:
        raise SystemExit(f"sealed gate attempt summary fields differ: {expected_id}")
    planned = len(gate["attempts"])
    expected_real = sum(
        attempt["kind"] == "real_runtime" for attempt in gate["attempts"]
    )
    expected_non_runtime = planned - expected_real
    for key, maximum in (
        ("planned", planned),
        ("started", planned),
        ("completed", planned),
        ("real_runtime_started", expected_real),
        ("real_runtime_completed", expected_real),
        ("non_runtime_started", expected_non_runtime),
        ("non_runtime_completed", expected_non_runtime),
    ):
        value = summary.get(key)
        if not bounded_integer(value, 0, maximum):
            raise SystemExit(f"sealed gate attempt count is invalid: {expected_id}/{key}")
    if (
        summary["planned"] != planned
        or summary["completed"] > summary["started"]
        or summary["real_runtime_completed"] > summary["real_runtime_started"]
        or summary["non_runtime_completed"] > summary["non_runtime_started"]
        or summary["started"]
        != summary["real_runtime_started"] + summary["non_runtime_started"]
        or summary["completed"]
        != summary["real_runtime_completed"] + summary["non_runtime_completed"]
    ):
        raise SystemExit(f"sealed gate attempt accounting differs: {expected_id}")
    if status_value == expected_passing_status and (
        summary["started"] != planned or summary["completed"] != planned
    ):
        raise SystemExit(f"sealed passing gate lacks every attempt: {expected_id}")
    derived_counts["real_runtime_attempts_started"] += summary[
        "real_runtime_started"
    ]
    derived_counts["real_runtime_attempts_completed"] += summary[
        "real_runtime_completed"
    ]
    derived_counts["non_runtime_attempts_started"] += summary[
        "non_runtime_started"
    ]
    derived_counts["non_runtime_attempts_completed"] += summary[
        "non_runtime_completed"
    ]

decision_keys = {
    "schema",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "decision",
    "hard_gate_count",
    "hard_gates_passed",
    "failed_or_incomplete_gates",
    "real_runtime_attempt_limit",
    "real_runtime_attempts_started",
    "real_runtime_attempts_completed",
    "non_runtime_attempts_started",
    "non_runtime_attempts_completed",
    "incomplete_attempt_ids",
    "missing_attempt_ids",
    "reasons",
    "provider_calls",
    "provider_cost_usd",
}
if set(decision) != decision_keys or (
    decision.get("schema") != "fortgym.m1b-live-acceptance-decision/v1"
    or decision.get("batch_id") != batch_id
    or decision.get("acceptance_sha256") != acceptance_sha256
    or decision.get("plan_sha256") != plan_sha256
    or decision.get("decision") != host_outcome.get("decision")
    or decision.get("hard_gate_count") != 16
    or decision.get("hard_gates_passed") != 16 - len(failed_gate_ids)
    or decision.get("failed_or_incomplete_gates") != failed_gate_ids
    or decision.get("real_runtime_attempt_limit") != 26
    or isinstance(decision.get("provider_calls"), bool)
    or decision.get("provider_calls") != 0
    or isinstance(decision.get("provider_cost_usd"), bool)
    or decision.get("provider_cost_usd") != 0
):
    raise SystemExit("sealed decision schema, identity, or gate accounting differs")
for key, value in derived_counts.items():
    if decision.get(key) != value or host_outcome.get(key) != value:
        raise SystemExit(f"sealed decision/runner attempt count differs: {key}")
if not (
    0
    <= derived_counts["real_runtime_attempts_completed"]
    <= derived_counts["real_runtime_attempts_started"]
    <= 26
    and 0
    <= derived_counts["non_runtime_attempts_completed"]
    <= derived_counts["non_runtime_attempts_started"]
    <= 1
):
    raise SystemExit("sealed aggregate attempt counts exceed the frozen slots")

missing_ids = decision.get("missing_attempt_ids")
incomplete_ids = decision.get("incomplete_attempt_ids")
planned_id_set = set(planned_attempt_ids)
for label, values in (("missing", missing_ids), ("incomplete", incomplete_ids)):
    if (
        not isinstance(values, list)
        or values != sorted(values)
        or len(values) != len(set(values))
        or any(not isinstance(item, str) or item not in planned_id_set for item in values)
    ):
        raise SystemExit(f"sealed {label} attempt IDs are invalid")
if set(missing_ids).intersection(incomplete_ids) or (
    len(missing_ids)
    != 27
    - derived_counts["real_runtime_attempts_started"]
    - derived_counts["non_runtime_attempts_started"]
) or (
    len(incomplete_ids)
    != derived_counts["real_runtime_attempts_started"]
    + derived_counts["non_runtime_attempts_started"]
    - derived_counts["real_runtime_attempts_completed"]
    - derived_counts["non_runtime_attempts_completed"]
):
    raise SystemExit("sealed missing/incomplete attempt cardinality differs")
expected_reasons = [f"gate_not_passed:{gate_id}" for gate_id in failed_gate_ids]
if derived_counts["real_runtime_attempts_started"] != 26:
    expected_reasons.append("real_runtime_attempt_count_not_26")
if derived_counts["real_runtime_attempts_completed"] != 26:
    expected_reasons.append("real_runtime_terminal_count_not_26")
if derived_counts["non_runtime_attempts_started"] != 1:
    expected_reasons.append("port2_non_runtime_conflict_start_missing")
if derived_counts["non_runtime_attempts_completed"] != 1:
    expected_reasons.append("port2_non_runtime_conflict_terminal_missing")
if incomplete_ids:
    expected_reasons.append("attempt_terminal_evidence_incomplete")
if missing_ids:
    expected_reasons.append("planned_attempts_not_run")
expected_decision = "GO" if not expected_reasons else "INCOMPLETE_NO_GO"
if decision.get("reasons") != expected_reasons or decision.get("decision") != expected_decision:
    raise SystemExit("sealed decision reasons or value differ")
if expected_decision == "GO" and derived_counts != {
    "real_runtime_attempts_started": 26,
    "real_runtime_attempts_completed": 26,
    "non_runtime_attempts_started": 1,
    "non_runtime_attempts_completed": 1,
}:
    raise SystemExit("sealed GO decision lacks the exact frozen attempt counts")

manifest_keys = {
    "schema",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "artifacts",
}
artifacts = reference_list(manifest.get("artifacts"), label="manifest")
artifact_paths = [str(item["path"]) for item in artifacts]
if set(manifest) != manifest_keys or (
    manifest.get("schema") != "fortgym.m1b-live-acceptance-evidence-manifest/v1"
    or manifest.get("batch_id") != batch_id
    or manifest.get("acceptance_sha256") != acceptance_sha256
    or manifest.get("plan_sha256") != plan_sha256
    or not artifacts
    or artifact_paths != sorted(artifact_paths)
):
    raise SystemExit("sealed evidence-manifest schema, identity, or ordering differs")
artifact_by_path = {str(item["path"]): item for item in artifacts}
required_artifacts = {
    "contract/infra/m1b/acceptance.yaml",
    "control/batch-ledger.jsonl",
    "control/attempt-ledger.jsonl",
    "control/gate-results.json",
    "control/decision.json",
}
if not required_artifacts.issubset(artifact_by_path) or {
    "control/evidence-manifest.json",
    "control/seal.json",
}.intersection(artifact_by_path):
    raise SystemExit("sealed evidence manifest required/control members differ")
for relative, reference in artifact_by_path.items():
    path = (
        contract_path
        if relative == "contract/infra/m1b/acceptance.yaml"
        else batch_root.joinpath(*pathlib.PurePosixPath(relative).parts)
    )
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"manifest artifact is absent: {relative}") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size != reference["size_bytes"]
        or sha256_file(path) != reference["sha256"]
    ):
        raise SystemExit(f"manifest artifact content address differs: {relative}")
for reference in row_references:
    if artifact_by_path.get(str(reference["path"])) != reference:
        raise SystemExit("gate/local-credit evidence is absent from the sealed manifest")
if artifact_by_path["control/gate-results.json"]["sha256"] != gate_results_sha256 or (
    artifact_by_path["control/decision.json"]["sha256"] != decision_sha256
):
    raise SystemExit("sealed control artifacts differ from their manifest references")

normalized = {
    "schema": "fortgym.m1b-sealed-host-outcome-verification/v1",
    "batch_id": batch_id,
    "acceptance_sha256": acceptance_sha256,
    "plan_sha256": plan_sha256,
    "decision": expected_decision,
    **derived_counts,
    "gate_ids": expected_gate_ids,
    "failed_or_incomplete_gates": failed_gate_ids,
    "gate_results_sha256": gate_results_sha256,
    "decision_sha256": decision_sha256,
    "evidence_manifest_sha256": manifest_sha256,
    "controller_seal_sha256": seal_sha256,
    "host_runner_outcome_sha256": hashlib.sha256(
        host_outcome_path.read_bytes()
    ).hexdigest(),
    "manifest_artifact_count": len(artifacts),
}
if target.exists() or target.is_symlink():
    raise SystemExit("normalized sealed host outcome already exists")
descriptor, temporary = tempfile.mkstemp(prefix=".sealed-host-outcome.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
  then
    return 1
  fi
  SEALED_HOST_OUTCOME_VERIFIED=1
}

validate_post_seal_host_cleanup() {
  local batch_root="$1"
  local normalized="$EVIDENCE_DIR/post-seal-host-cleanup-verified.json"
  if ! python3 -I - \
    "$batch_root" "$normalized" "$BATCH_ID" "$ACCEPTANCE_SHA256" \
    "$PLAN_SHA256" "$M1B_DECISION" "$ROOT_BROKER_SHA256" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import tempfile

batch_root = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
batch_id, acceptance_sha256, plan_sha256, decision, root_broker_sha256 = sys.argv[3:8]
sha256_pattern = re.compile(r"[0-9a-f]{64}")


def load_regular(path: pathlib.Path) -> tuple[dict[str, object], str]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"required host evidence is absent: {path.name}") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size > 16 * 1024 * 1024
    ):
        raise SystemExit(f"host evidence is not one regular file: {path.name}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"host evidence is not JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"host evidence is not an object: {path.name}")
    return payload, hashlib.sha256(raw).hexdigest()


def positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_argv_sha256(argv: tuple[str, ...]) -> str:
    raw = json.dumps(list(argv), sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


cleanup_path = batch_root / "post-seal-host-cleanup.json"
creation_path = batch_root / "batch-canary-created.json"
control_root = batch_root / "control"
seal_path = control_root / "seal.json"
gate_results_path = control_root / "gate-results.json"
decision_path = control_root / "decision.json"
manifest_path = control_root / "evidence-manifest.json"
post, post_sha256 = load_regular(cleanup_path)
created, created_sha256 = load_regular(creation_path)
seal, seal_sha256 = load_regular(seal_path)
if set(post) != {
    "schema",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "controller_seal_sha256",
    "cleanup",
}:
    raise SystemExit("post-seal host cleanup keys differ")
if (
    post.get("schema") != "fortgym.m1b-post-seal-host-cleanup/v1"
    or post.get("batch_id") != batch_id
    or post.get("acceptance_sha256") != acceptance_sha256
    or post.get("plan_sha256") != plan_sha256
    or post.get("controller_seal_sha256") != seal_sha256
):
    raise SystemExit("post-seal host cleanup identity or seal binding differs")

expected_seal_keys = {
    "schema",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "decision",
    "gate_results_sha256",
    "decision_sha256",
    "evidence_manifest_sha256",
}
if set(seal) != expected_seal_keys or (
    seal.get("schema") != "fortgym.m1b-live-acceptance-seal/v1"
    or seal.get("batch_id") != batch_id
    or seal.get("acceptance_sha256") != acceptance_sha256
    or seal.get("plan_sha256") != plan_sha256
    or seal.get("decision") != decision
    or seal.get("gate_results_sha256") != sha256_file(gate_results_path)
    or seal.get("decision_sha256") != sha256_file(decision_path)
    or seal.get("evidence_manifest_sha256") != sha256_file(manifest_path)
):
    raise SystemExit("controller seal identity, decision, or artifact binding differs")

cleanup = post.get("cleanup")
expected_cleanup_keys = {
    "present",
    "removed",
    "name",
    "container_id",
    "container_absent",
    "container_absence_returncode",
    "process_id",
    "process_start_ticks",
    "process_absent",
    "workspace",
    "workspace_absent",
    "initial_container_state_sha256",
    "pre_removal_container_state_sha256",
    "pre_removal_broker_evidence_sha256",
    "creation_broker_evidence_sha256",
    "removal_broker_evidence_sha256",
    "absence_broker_evidence_sha256",
}
if not isinstance(cleanup, dict) or set(cleanup) != expected_cleanup_keys:
    raise SystemExit("post-seal host cleanup fields differ")
expected_name = "fortgym-m1b-foreign-" + hashlib.sha256(
    batch_id.encode("utf-8")
).hexdigest()[:16]
expected_workspace = f"/var/lib/fortgym-m1b/canary/{batch_id}"
container_id = cleanup.get("container_id")
container_absence_returncode = cleanup.get("container_absence_returncode")
if (
    cleanup.get("present") is not True
    or cleanup.get("removed") is not True
    or cleanup.get("name") != expected_name
    or not isinstance(container_id, str)
    or sha256_pattern.fullmatch(container_id) is None
    or cleanup.get("container_absent") is not True
    or isinstance(container_absence_returncode, bool)
    or container_absence_returncode != 0
    or not positive_integer(cleanup.get("process_id"))
    or not positive_integer(cleanup.get("process_start_ticks"))
    or cleanup.get("process_absent") is not True
    or cleanup.get("workspace") != expected_workspace
    or cleanup.get("workspace_absent") is not True
):
    raise SystemExit("post-seal host cleanup absence proof differs")
initial_state = cleanup.get("initial_container_state_sha256")
pre_removal_state = cleanup.get("pre_removal_container_state_sha256")
if (
    not isinstance(initial_state, str)
    or sha256_pattern.fullmatch(initial_state) is None
    or pre_removal_state != initial_state
):
    raise SystemExit("post-seal canary state changed before removal")

expected_creation_keys = {
    "schema",
    "batch_id",
    "name",
    "container_id",
    "process_id",
    "process_start_ticks",
    "workspace",
    "workspace_device",
    "workspace_inode",
    "container_state_sha256",
    "broker_evidence_sha256",
    "inspect_broker_evidence_sha256",
}
if set(created) != expected_creation_keys or (
    created.get("schema") != "fortgym.m1b-batch-canary-created/v1"
    or created.get("batch_id") != batch_id
    or created.get("name") != expected_name
    or created.get("container_id") != container_id
    or created.get("process_id") != cleanup.get("process_id")
    or created.get("process_start_ticks") != cleanup.get("process_start_ticks")
    or created.get("workspace") != expected_workspace
    or not positive_integer(created.get("workspace_device"))
    or not positive_integer(created.get("workspace_inode"))
    or created.get("container_state_sha256") != initial_state
    or created.get("broker_evidence_sha256")
    != cleanup.get("creation_broker_evidence_sha256")
):
    raise SystemExit("batch canary creation identity differs from its cleanup")

broker_root = batch_root / "broker-client"
try:
    broker_root_info = broker_root.lstat()
except OSError as exc:
    raise SystemExit("broker client evidence root is absent") from exc
if not stat.S_ISDIR(broker_root_info.st_mode):
    raise SystemExit("broker client evidence root is not a directory")
broker_by_digest: dict[str, tuple[pathlib.Path, dict[str, object]]] = {}
for path in sorted(broker_root.rglob("*")):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise SystemExit("broker client evidence contains a symlink")
    if stat.S_ISDIR(info.st_mode):
        continue
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.suffix != ".json":
        raise SystemExit("broker client evidence contains an unexpected member")
    payload, digest = load_regular(path)
    if digest in broker_by_digest:
        raise SystemExit("broker client evidence has a duplicate file digest")
    broker_by_digest[digest] = (path, payload)

roles = {
    "creation": (
        cleanup.get("creation_broker_evidence_sha256"),
        "BATCH-CANARY",
        "canary_create",
        True,
        0,
        (
            "docker",
            "create",
            "--name",
            expected_name,
            "--network",
            "none",
            "--memory",
            "128m",
            "--memory-swap",
            "128m",
            "--pids-limit",
            "16",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--restart",
            "no",
            "--entrypoint",
            "/bin/sleep",
            "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c",
            "28800",
        ),
    ),
    "initial_inspect": (
        created.get("inspect_broker_evidence_sha256"),
        "BATCH-CANARY",
        "canary_inspect",
        True,
        0,
        ("docker", "inspect", "--type", "container", expected_name),
    ),
    "pre_removal_inspect": (
        cleanup.get("pre_removal_broker_evidence_sha256"),
        "CLEANUP",
        "canary_inspect",
        True,
        0,
        ("docker", "inspect", "--type", "container", expected_name),
    ),
    "removal": (
        cleanup.get("removal_broker_evidence_sha256"),
        "CLEANUP",
        "canary_remove",
        True,
        0,
        ("docker", "rm", "--force", expected_name),
    ),
    "absence": (
        cleanup.get("absence_broker_evidence_sha256"),
        "CLEANUP",
        "canary_absence",
        True,
        0,
        (
            "docker",
            "ps",
            "--all",
            "--no-trunc",
            "--filter",
            f"name=^/{expected_name}$",
            "--format",
            "{{.ID}}",
        ),
    ),
}
role_digests = [role[0] for role in roles.values()]
if any(
    not isinstance(value, str) or sha256_pattern.fullmatch(value) is None
    for value in role_digests
) or len(set(role_digests)) != len(role_digests):
    raise SystemExit("post-seal broker receipt digests are invalid or duplicate")
public_receipt_keys = {
    "schema",
    "ok",
    "request_id",
    "request_sha256",
    "acceptance_sha256",
    "policy_sha256",
    "broker_source_sha256",
    "batch_id",
    "gate_id",
    "grant_kind",
    "attempt_id",
    "attempt_identity_sha256",
    "action",
    "binding",
    "logical_argv_sha256",
    "returncode",
    "stdout_sha256",
    "stderr_sha256",
    "result",
    "shell",
    "action_grant_sha256",
}
for role, (digest, gate_id, action, ok, returncode, argv) in roles.items():
    located = broker_by_digest.get(str(digest))
    if located is None:
        raise SystemExit(f"post-seal broker receipt is absent: {role}")
    _path, receipt = located
    digest_fields = (
        "request_id",
        "request_sha256",
        "policy_sha256",
        "broker_source_sha256",
        "logical_argv_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "action_grant_sha256",
    )
    if set(receipt) != public_receipt_keys or (
        receipt.get("schema") != "fortgym.m1b-root-broker-receipt/v1"
        or receipt.get("ok") is not ok
        or receipt.get("acceptance_sha256") != acceptance_sha256
        or receipt.get("batch_id") != batch_id
        or receipt.get("gate_id") != gate_id
        or receipt.get("grant_kind") != "batch_canary"
        or receipt.get("attempt_id") is not None
        or receipt.get("attempt_identity_sha256") is not None
        or receipt.get("action") != action
        or receipt.get("binding") is not None
        or receipt.get("returncode") != returncode
        or receipt.get("shell") is not False
        or receipt.get("broker_source_sha256") != root_broker_sha256
        or receipt.get("result") is not None
        or receipt.get("logical_argv_sha256") != canonical_argv_sha256(argv)
        or any(
            not isinstance(receipt.get(field), str)
            or sha256_pattern.fullmatch(str(receipt.get(field))) is None
            for field in digest_fields
        )
    ):
        raise SystemExit(f"post-seal public broker receipt differs: {role}")
    if role == "absence" and (
        receipt.get("stdout_sha256") != hashlib.sha256(b"").hexdigest()
        or receipt.get("stderr_sha256") != hashlib.sha256(b"").hexdigest()
    ):
        raise SystemExit("post-seal canary absence is not an authenticated empty listing")

normalized = {
    "schema": "fortgym.m1b-post-seal-host-cleanup-verification/v1",
    "batch_id": batch_id,
    "acceptance_sha256": acceptance_sha256,
    "plan_sha256": plan_sha256,
    "m1b_decision": decision,
    "post_seal_host_cleanup_sha256": post_sha256,
    "batch_canary_created_sha256": created_sha256,
    "controller_seal_sha256": seal_sha256,
    "canary_identity": {
        "name": expected_name,
        "container_id": container_id,
        "process_id": cleanup["process_id"],
        "process_start_ticks": cleanup["process_start_ticks"],
        "workspace": expected_workspace,
        "container_state_sha256": initial_state,
    },
    "absence_verified": {
        "container": True,
        "process": True,
        "workspace": True,
    },
    "broker_receipts_sha256": {
        role: digest for role, (digest, *_rest) in sorted(roles.items())
    },
}
if target.exists() or target.is_symlink():
    raise SystemExit("normalized post-seal cleanup proof already exists")
descriptor, temporary = tempfile.mkstemp(prefix=".post-seal-cleanup.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
  then
    return 1
  fi
  POST_SEAL_HOST_CLEANUP_VERIFIED=1
}

validate_root_broker_attestation() {
  local batch_root="$1"
  local retrieved_root="$2"
  local broker_root="$3"
  local normalized="$EVIDENCE_DIR/root-broker-attestation-verified.json"
  if ! python3 -I - \
    "$batch_root" "$retrieved_root" "$broker_root" "$normalized" \
    "$EVIDENCE_DIR/host-runner-stdout.json" "$PACKET_DIR/PACKET.json" \
    "$PACKET_DIR/source-manifest.json" "$BATCH_ID" "$ACCEPTANCE_SHA256" \
    "$PLAN_SHA256" "$ROOT_BROKER_SHA256" "$AUTHORITY_EXPIRY" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import tempfile

batch_root = pathlib.Path(sys.argv[1])
root_evidence = pathlib.Path(sys.argv[2])
broker_root = pathlib.Path(sys.argv[3])
target = pathlib.Path(sys.argv[4])
host_outcome_path = pathlib.Path(sys.argv[5])
packet_path = pathlib.Path(sys.argv[6])
source_manifest_path = pathlib.Path(sys.argv[7])
batch_id, acceptance_sha256, plan_sha256 = sys.argv[8:11]
broker_source_sha256, authority_expiry = sys.argv[11:13]
sha256_pattern = re.compile(r"[0-9a-f]{64}")
request_id_pattern = sha256_pattern


def canonical_bytes(value: object, *, newline: bool = False) -> bytes:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return encoded + (b"\n" if newline else b"")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(
    path: pathlib.Path, *, maximum_bytes: int = 32 * 1024 * 1024
) -> tuple[dict[str, object], str]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"broker evidence is absent: {path}") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size < 2
        or info.st_size > maximum_bytes
    ):
        raise SystemExit(f"broker evidence is unsafe or oversized: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"broker evidence is malformed JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"broker evidence is not an object: {path}")
    return value, sha256_bytes(raw)


def require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or sha256_pattern.fullmatch(value) is None:
        raise SystemExit(f"{label} is not a lowercase SHA-256")
    return value


def require_zero(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != 0:
        raise SystemExit(f"{label} is not exact zero")


def remote_to_local(remote: object) -> pathlib.Path:
    if not isinstance(remote, str) or not remote.startswith(
        f"/var/lib/fortgym-m1b/evidence/{batch_id}/"
    ):
        raise SystemExit("service evidence path escaped the frozen batch")
    relative = pathlib.PurePosixPath(remote).relative_to(
        f"/var/lib/fortgym-m1b/evidence/{batch_id}"
    )
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise SystemExit("service evidence path is unsafe")
    return batch_root.joinpath(*relative.parts)


def validate_ledger(path: pathlib.Path, schema: str) -> tuple[str, str]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SystemExit(f"controller ledger is absent: {path.name}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0:
        raise SystemExit(f"controller ledger is unsafe: {path.name}")
    raw = path.read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise SystemExit(f"controller ledger is oversized: {path.name}")
    lines = raw.splitlines()
    if not lines or len(lines) > 8192:
        raise SystemExit(f"controller ledger record count differs: {path.name}")
    previous = "0" * 64
    expected_keys = {
        "schema",
        "batch_id",
        "acceptance_sha256",
        "plan_sha256",
        "sequence",
        "previous_record_sha256",
        "at",
        "event",
        "payload",
        "record_sha256",
    }
    for sequence, raw_line in enumerate(lines, start=1):
        if not raw_line or len(raw_line) > 128 * 1024:
            raise SystemExit(f"controller ledger record is invalid: {path.name}")
        try:
            record = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"controller ledger is malformed: {path.name}") from exc
        claimed = record.get("record_sha256") if isinstance(record, dict) else None
        unsigned = dict(record) if isinstance(record, dict) else {}
        unsigned.pop("record_sha256", None)
        if (
            not isinstance(record, dict)
            or set(record) != expected_keys
            or record.get("schema") != schema
            or record.get("batch_id") != batch_id
            or record.get("acceptance_sha256") != acceptance_sha256
            or record.get("plan_sha256") != plan_sha256
            or record.get("sequence") != sequence
            or isinstance(record.get("sequence"), bool)
            or record.get("previous_record_sha256") != previous
            or not isinstance(record.get("at"), str)
            or not isinstance(record.get("event"), str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", record["event"])
            is None
            or not isinstance(record.get("payload"), dict)
            or require_sha(claimed, f"{path.name} record hash")
            != sha256_bytes(canonical_bytes(unsigned))
        ):
            raise SystemExit(f"controller ledger hash chain differs: {path.name}")
        previous = str(claimed)
    return sha256_bytes(raw), previous


try:
    outcome_lines = host_outcome_path.read_text(encoding="utf-8").splitlines()
except (OSError, UnicodeDecodeError) as exc:
    raise SystemExit("host outcome is unreadable") from exc
if len(outcome_lines) != 1 or not outcome_lines[0]:
    raise SystemExit("host outcome is not exactly one line")
host = json.loads(outcome_lines[0])
if not isinstance(host, dict):
    raise SystemExit("host outcome is not an object")

reference_path = remote_to_local(host.get("broker_attestation_reference_path"))
public_final_path = remote_to_local(host.get("broker_attestation_receipt_path"))
post_cleanup_path = remote_to_local(host.get("post_seal_cleanup_path"))
expected_root_remote = (
    f"/var/lib/fortgym-m1b-root-evidence/batches/{batch_id}/broker-attestation.json"
)
if host.get("broker_attestation_path") != expected_root_remote:
    raise SystemExit("host root attestation path differs")
root_attestation_path = root_evidence / "batches" / batch_id / "broker-attestation.json"

reference, reference_sha256 = load_json(reference_path)
attestation, attestation_sha256 = load_json(root_attestation_path)
public_final, public_final_sha256 = load_json(public_final_path)
post_cleanup, post_cleanup_sha256 = load_json(post_cleanup_path)
control = batch_root / "control"
seal, seal_sha256 = load_json(control / "seal.json")
decision, decision_sha256 = load_json(control / "decision.json")
_gates, gates_sha256 = load_json(control / "gate-results.json")
_manifest, evidence_manifest_sha256 = load_json(control / "evidence-manifest.json")

for field, observed in (
    ("broker_attestation_sha256", attestation_sha256),
    ("broker_attestation_reference_sha256", reference_sha256),
    ("broker_attestation_receipt_sha256", public_final_sha256),
    ("post_seal_cleanup_sha256", post_cleanup_sha256),
):
    if host.get(field) != observed:
        raise SystemExit(f"host runner root export content address differs: {field}")

reference_keys = {
    "schema",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "controller_seal_sha256",
    "post_seal_cleanup_path",
    "post_seal_cleanup_sha256",
    "root_attestation_path",
    "root_attestation_sha256",
    "broker_request_id",
    "broker_public_receipt_path",
    "broker_public_receipt_sha256",
}
final_request_id = reference.get("broker_request_id")
if (
    set(reference) != reference_keys
    or reference.get("schema")
    != "fortgym.m1b-root-broker-attestation-reference/v1"
    or reference.get("batch_id") != batch_id
    or reference.get("acceptance_sha256") != acceptance_sha256
    or reference.get("plan_sha256") != plan_sha256
    or reference.get("controller_seal_sha256") != seal_sha256
    or reference.get("post_seal_cleanup_path") != host.get("post_seal_cleanup_path")
    or reference.get("post_seal_cleanup_sha256") != post_cleanup_sha256
    or reference.get("root_attestation_path") != expected_root_remote
    or reference.get("root_attestation_sha256") != attestation_sha256
    or not isinstance(final_request_id, str)
    or request_id_pattern.fullmatch(final_request_id) is None
    or reference.get("broker_public_receipt_path")
    != host.get("broker_attestation_receipt_path")
    or reference.get("broker_public_receipt_sha256") != public_final_sha256
):
    raise SystemExit("root broker attestation reference differs")

top_keys = {
    "schema",
    "ok",
    "batch_id",
    "acceptance_sha256",
    "plan_sha256",
    "authority_expires_at",
    "packet",
    "controller",
    "attempts",
    "root_records",
    "public_receipts",
    "excluded_self",
    "canary",
    "provider_calls",
    "provider_cost_usd",
    "shell",
}
if set(attestation) != top_keys or (
    attestation.get("schema") != "fortgym.m1b-root-broker-attestation/v1"
    or attestation.get("ok") is not True
    or attestation.get("batch_id") != batch_id
    or attestation.get("acceptance_sha256") != acceptance_sha256
    or attestation.get("plan_sha256") != plan_sha256
    or attestation.get("authority_expires_at")
    != authority_expiry.replace("Z", "+00:00")
    or attestation.get("shell") is not False
):
    raise SystemExit("root broker attestation identity differs")
require_zero(attestation.get("provider_calls"), "root attestation provider calls")
require_zero(attestation.get("provider_cost_usd"), "root attestation provider cost")

packet = attestation.get("packet")
if not isinstance(packet, dict) or set(packet) != {
    "packet_sha256",
    "source_manifest_sha256",
} or (
    packet.get("packet_sha256") != sha256_file(packet_path)
    or packet.get("source_manifest_sha256") != sha256_file(source_manifest_path)
    or sha256_file(batch_root / "inputs" / "source-manifest.json")
    != packet.get("source_manifest_sha256")
):
    raise SystemExit("root broker packet/source binding differs")

bootstrap, bootstrap_sha256 = load_json(root_evidence / "bootstrap.json")
cached_bootstrap, cached_bootstrap_sha256 = load_json(
    host_outcome_path.parent / "bootstrap-host-receipt.json"
)
if bootstrap != cached_bootstrap or bootstrap_sha256 != cached_bootstrap_sha256:
    raise SystemExit("retrieved bootstrap receipt differs from the pre-guard receipt")
packet_document = json.loads(packet_path.read_text(encoding="utf-8"))
subordinate_specs = {
    "docker_runtime_attestation_sha256": (
        "docker-runtime-attestation.json",
        "fortgym.m1b-docker-runtime-attestation/v1",
        "docker_server_29_1_3_containerd_store",
    ),
    "runtime_archive_attestation_sha256": (
        "runtime-archive-attestation.json",
        "fortgym.m1b-runtime-archive-attestation/v1",
        "runtime_archive_digest_exact",
    ),
    "provider_helper_bpf_attestation_sha256": (
        "provider-helper-bpf-attestation.json",
        "fortgym.m1b-provider-helper-bpf-attestation/v1",
        "provider_helper_bpf_attested",
    ),
    "docker_image_descriptor_attestation_sha256": (
        "docker-image-descriptor-attestation.json",
        "fortgym.m1b-docker-image-descriptor-attestation/v1",
        "containerd_image_store_descriptor_attested",
    ),
    "trusted_paths_sha256": (
        "trusted-paths.json",
        "fortgym.m1b-trusted-host-paths/v1",
        "docker_server_29_1_3_containerd_store",
    ),
}
subordinates = {}
for pointer, (name, schema, flag) in subordinate_specs.items():
    document, digest = load_json(root_evidence / name)
    if (
        bootstrap.get(pointer) != digest
        or document.get("schema") != schema
        or document.get("ok") is not True
        or document.get(flag) is not True
    ):
        raise SystemExit(f"bootstrap subordinate binding differs: {name}")
    subordinates[name] = document

docker_attestation = subordinates["docker-runtime-attestation.json"]
expected_docker_keys = {
    "schema",
    "ok",
    "docker_server_version",
    "containerd_version",
    "containerd_snapshotter_driver",
    "docker_server_29_1_3_containerd_store",
    "daemon_configured_before_first_start",
    "userland_proxy_disabled",
    "offline_packet_packages_only",
    "distro_docker_io_installed",
    "signed_repository_verified",
    "runtime_manifest_sha256",
    "installed_binaries",
}
if set(docker_attestation) != expected_docker_keys or (
    docker_attestation.get("docker_server_version") != "29.1.3"
    or docker_attestation.get("containerd_version") != "2.2.1"
    or docker_attestation.get("containerd_snapshotter_driver")
    != "io.containerd.snapshotter.v1"
    or docker_attestation.get("daemon_configured_before_first_start") is not True
    or docker_attestation.get("userland_proxy_disabled") is not True
    or docker_attestation.get("offline_packet_packages_only") is not True
    or docker_attestation.get("distro_docker_io_installed") is not False
    or docker_attestation.get("signed_repository_verified") is not True
    or docker_attestation.get("runtime_manifest_sha256")
    != packet_document["docker_runtime"]["manifest_sha256"]
    or docker_attestation.get("installed_binaries")
    != packet_document["docker_runtime"]["binaries"]
):
    raise SystemExit("Docker runtime bootstrap attestation differs")

archive_attestation = subordinates["runtime-archive-attestation.json"]
if set(archive_attestation) != {
    "schema",
    "ok",
    "path",
    "sha256",
    "size_bytes",
    "runtime_archive_digest_exact",
    "root_owned_mode_0600",
} or archive_attestation != {
    "schema": "fortgym.m1b-runtime-archive-attestation/v1",
    "ok": True,
    "path": "/opt/fortgym-m1b/runtime-image.tar.zst",
    "sha256": packet_document["runtime_archive"]["compressed_sha256"],
    "size_bytes": packet_document["runtime_archive"]["size_bytes"],
    "runtime_archive_digest_exact": True,
    "root_owned_mode_0600": True,
}:
    raise SystemExit("runtime archive bootstrap attestation differs")

descriptor = subordinates["docker-image-descriptor-attestation.json"]
if descriptor != {
    "schema": "fortgym.m1b-docker-image-descriptor-attestation/v1",
    "ok": True,
    "image_reference": "fortgym-df:m1a-stock-0.47.05-r8",
    "image_id": "sha256:" + packet_document["runtime_archive"]["manifest_sha256"],
    "manifest_digest": "sha256:"
    + packet_document["runtime_archive"]["manifest_sha256"],
    "manifest_media_type": packet_document["runtime_archive"]["manifest_media_type"],
    "manifest_size_bytes": packet_document["runtime_archive"]["manifest_size_bytes"],
    "config_digest": "sha256:" + packet_document["runtime_archive"]["config_sha256"],
    "platform": "linux/amd64",
    "containerd_image_store_descriptor_attested": True,
}:
    raise SystemExit("Docker image descriptor bootstrap attestation differs")

provider = subordinates["provider-helper-bpf-attestation.json"]
provider_leaf_pointers = {
    "capability_probe_sha256": "provider-capability-probe.json",
    "prepare_sha256": "provider-prepare.json",
    "snapshot_sha256": "provider-snapshot.json",
    "guard_attestation_sha256": "provider-bootstrap-guard.json",
    "inner_allow_probe_sha256": "provider-bootstrap-inner.json",
    "cleanup_sha256": "provider-cleanup.json",
    "cleanup_idempotent_sha256": "provider-cleanup-idempotent.json",
}
expected_provider_keys = {
    "schema",
    "ok",
    "provider_helper_bpf_attested",
    "source_tree_sha256",
    "source_manifest_sha256",
    "helper_path",
    "helper_sha256",
    "helper_mode",
    "bpf_object_path",
    "bpf_object_sha256",
    "bpf_object_mode",
    "reproducible_build_outputs_match",
    "installed_outputs_match_build",
    "root_owned_nonwritable_ancestry",
    "live_setuid_helper_exercised_as_nonroot",
    "kernel_bpf_load_attested",
    "cgroup_hooks_attached",
    "default_deny_negative_canary_attested",
    "negative_canary_event_count",
    "exact_loopback_allow_attested",
    "zero_lost_events",
    "cleanup_idempotent",
    *provider_leaf_pointers,
}
if set(provider) != expected_provider_keys or (
    provider.get("source_tree_sha256") != packet_document["source"]["tree_sha256"]
    or provider.get("source_manifest_sha256") != sha256_file(source_manifest_path)
    or provider.get("helper_path")
    != "/usr/local/libexec/fortgym-provider-network-helper"
    or provider.get("helper_mode") != "4750"
    or provider.get("bpf_object_path") != "/usr/local/lib/fortgym/provider_network.bpf.o"
    or provider.get("bpf_object_mode") != "0644"
    or any(
        provider.get(flag) is not True
        for flag in (
            "reproducible_build_outputs_match",
            "installed_outputs_match_build",
            "root_owned_nonwritable_ancestry",
            "live_setuid_helper_exercised_as_nonroot",
            "kernel_bpf_load_attested",
            "cgroup_hooks_attached",
            "default_deny_negative_canary_attested",
            "exact_loopback_allow_attested",
            "zero_lost_events",
            "cleanup_idempotent",
        )
    )
    or provider.get("negative_canary_event_count") != 6
):
    raise SystemExit("provider helper/BPF bootstrap attestation differs")
for pointer, name in provider_leaf_pointers.items():
    if provider.get(pointer) != sha256_file(root_evidence / name):
        raise SystemExit(f"provider proof leaf binding differs: {name}")
for pointer in ("helper_sha256", "bpf_object_sha256"):
    require_sha(provider.get(pointer), f"provider attestation {pointer}")

trusted = subordinates["trusted-paths.json"]
trusted_flags = {
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
trusted_pointer_names = {
    "docker_runtime_attestation_sha256": "docker-runtime-attestation.json",
    "runtime_archive_attestation_sha256": "runtime-archive-attestation.json",
    "provider_helper_bpf_attestation_sha256": "provider-helper-bpf-attestation.json",
    "docker_image_descriptor_attestation_sha256": (
        "docker-image-descriptor-attestation.json"
    ),
}
if set(trusted) != {"schema", "ok", *trusted_flags, *trusted_pointer_names} or (
    trusted.get("schema") != "fortgym.m1b-trusted-host-paths/v1"
    or trusted.get("ok") is not True
    or any(trusted.get(flag) is not True for flag in trusted_flags)
):
    raise SystemExit("trusted host paths bootstrap attestation differs")
for pointer, name in trusted_pointer_names.items():
    if trusted.get(pointer) != sha256_file(root_evidence / name):
        raise SystemExit(f"trusted host path pointer differs: {pointer}")

batch_ledger_sha256, batch_head_sha256 = validate_ledger(
    control / "batch-ledger.jsonl",
    "fortgym.m1b-live-acceptance-batch-ledger/v1",
)
attempt_ledger_sha256, attempt_head_sha256 = validate_ledger(
    control / "attempt-ledger.jsonl",
    "fortgym.m1b-live-acceptance-attempt-ledger/v1",
)
controller = attestation.get("controller")
controller_keys = {
    "batch_ledger_sha256",
    "attempt_ledger_sha256",
    "batch_head_sha256",
    "attempt_head_sha256",
    "seal_sha256",
    "post_seal_cleanup_sha256",
    "decision",
    "decision_sha256",
    "gate_results_sha256",
    "evidence_manifest_sha256",
}
if not isinstance(controller, dict) or set(controller) != controller_keys or controller != {
    "batch_ledger_sha256": batch_ledger_sha256,
    "attempt_ledger_sha256": attempt_ledger_sha256,
    "batch_head_sha256": batch_head_sha256,
    "attempt_head_sha256": attempt_head_sha256,
    "seal_sha256": seal_sha256,
    "post_seal_cleanup_sha256": post_cleanup_sha256,
    "decision": host.get("decision"),
    "decision_sha256": decision_sha256,
    "gate_results_sha256": gates_sha256,
    "evidence_manifest_sha256": evidence_manifest_sha256,
}:
    raise SystemExit("root broker controller binding differs")
if decision.get("decision") != host.get("decision") or seal.get("decision") != host.get(
    "decision"
):
    raise SystemExit("root broker decision binding differs")

attempts = attestation.get("attempts")
expected_attempts = {
    "planned": 27,
    "real_runtime_started": host.get("real_runtime_attempts_started"),
    "real_runtime_completed": host.get("real_runtime_attempts_completed"),
    "non_runtime_started": host.get("non_runtime_attempts_started"),
    "non_runtime_completed": host.get("non_runtime_attempts_completed"),
}
if not isinstance(attempts, dict) or attempts != expected_attempts:
    raise SystemExit("root broker attempt accounting differs")
if host.get("decision") == "GO" and attempts != {
    "planned": 27,
    "real_runtime_started": 26,
    "real_runtime_completed": 26,
    "non_runtime_started": 1,
    "non_runtime_completed": 1,
}:
    raise SystemExit("root broker GO attestation lacks all frozen attempts")

canary = attestation.get("canary")
if canary != {"created": True, "removed": True, "absence_verified": True} or (
    post_cleanup.get("cleanup", {}).get("container_absence_returncode") != 0
):
    raise SystemExit("root broker canary closure differs")

excluded = attestation.get("excluded_self")
excluded_keys = {
    "request_id",
    "request_sha256",
    "claim_sha256",
    "grant_sha256",
    "predicted_receipt_path",
    "predicted_receipt_digest_derivation",
    "root_records_excludes",
    "public_receipts_excludes",
    "reason",
}
if not isinstance(excluded, dict) or set(excluded) != excluded_keys or (
    excluded.get("request_id") != final_request_id
    or excluded.get("predicted_receipt_path")
    != f"broker-client/CLEANUP/{final_request_id}.json"
    or excluded.get("predicted_receipt_digest_derivation")
    != "sha256(canonical_json(root_receipt_without_stdout_stderr)+LF)"
    or excluded.get("root_records_excludes") != ["claim", "grant", "receipt"]
    or excluded.get("public_receipts_excludes") != ["receipt"]
    or excluded.get("reason") != "self_referential_final_attestation_boundary"
):
    raise SystemExit("root broker self-exclusion boundary differs")
for key in ("request_sha256", "claim_sha256", "grant_sha256"):
    require_sha(excluded.get(key), f"root attestation excluded {key}")

claim_keys = {
    "schema",
    "request_id",
    "request_sha256",
    "acceptance_sha256",
    "plan_sha256",
    "batch_id",
    "gate_id",
    "grant_kind",
    "attempt_id",
    "action",
}
grant_keys = {
    "schema",
    "acceptance_sha256",
    "plan_sha256",
    "batch_id",
    "grant_kind",
    "attempt_id",
    "attempt_identity_sha256",
    "gate_id",
    "action",
    "logical_argv_sha256",
    "recovery_epoch",
    "request_id",
    "batch_ledger_head_sha256",
    "one_shot",
}
private_receipt_keys = {
    "schema",
    "ok",
    "request_id",
    "request_sha256",
    "acceptance_sha256",
    "policy_sha256",
    "broker_source_sha256",
    "batch_id",
    "gate_id",
    "grant_kind",
    "attempt_id",
    "attempt_identity_sha256",
    "action",
    "binding",
    "logical_argv_sha256",
    "returncode",
    "stdout",
    "stderr",
    "stdout_sha256",
    "stderr_sha256",
    "result",
    "shell",
    "action_grant_sha256",
}
public_receipt_keys = private_receipt_keys - {"stdout", "stderr"}
read_only_actions = {
    "docker_image_inspect",
    "docker_container_inspect",
    "docker_logs",
    "docker_managed_list",
    "docker_exec_attest",
    "canary_inspect",
    "canary_absence",
    "verify_outer_guard",
}


def validate_claim(document: dict[str, object]) -> None:
    if set(document) != claim_keys or (
        document.get("schema") != "fortgym.m1b-root-broker-claim/v1"
        or document.get("batch_id") != batch_id
        or document.get("acceptance_sha256") != acceptance_sha256
        or document.get("plan_sha256") != plan_sha256
        or request_id_pattern.fullmatch(str(document.get("request_id") or "")) is None
        or sha256_pattern.fullmatch(str(document.get("request_sha256") or "")) is None
    ):
        raise SystemExit("root broker claim differs")


def validate_grant(document: dict[str, object]) -> None:
    ledger_head = document.get("batch_ledger_head_sha256")
    if set(document) != grant_keys or (
        document.get("schema") != "fortgym.m1b-root-broker-action-grant/v1"
        or document.get("batch_id") != batch_id
        or document.get("acceptance_sha256") != acceptance_sha256
        or document.get("plan_sha256") != plan_sha256
        or request_id_pattern.fullmatch(str(document.get("request_id") or "")) is None
        or sha256_pattern.fullmatch(str(document.get("logical_argv_sha256") or ""))
        is None
        or document.get("recovery_epoch") not in {0, 1}
        or not isinstance(document.get("one_shot"), bool)
        or (
            ledger_head is not None
            and sha256_pattern.fullmatch(str(ledger_head)) is None
        )
    ):
        raise SystemExit("root broker action grant differs")


def validate_private_receipt(document: dict[str, object]) -> None:
    stdout = document.get("stdout")
    stderr = document.get("stderr")
    returncode = document.get("returncode")
    if set(document) != private_receipt_keys or (
        document.get("schema") != "fortgym.m1b-root-broker-receipt/v1"
        or document.get("batch_id") != batch_id
        or document.get("acceptance_sha256") != acceptance_sha256
        or document.get("broker_source_sha256") != broker_source_sha256
        or request_id_pattern.fullmatch(str(document.get("request_id") or "")) is None
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
        or isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or document.get("ok") is not (returncode == 0)
        or document.get("stdout_sha256") != sha256_bytes(stdout.encode("utf-8"))
        or document.get("stderr_sha256") != sha256_bytes(stderr.encode("utf-8"))
        or document.get("shell") is not False
    ):
        raise SystemExit("root broker private receipt differs")
    for key in (
        "request_sha256",
        "policy_sha256",
        "broker_source_sha256",
        "logical_argv_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "action_grant_sha256",
    ):
        require_sha(document.get(key), f"root receipt {key}")


def regular_json_files(root: pathlib.Path) -> list[pathlib.Path]:
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise SystemExit(f"root broker evidence directory is absent: {root}") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise SystemExit(f"root broker evidence directory is unsafe: {root}")
    files = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
            raise SystemExit(f"root broker record is unsafe: {path}")
        files.append(path)
    return files


claim_root = broker_root / "claims"
grant_root = broker_root / "grants"
receipt_root = broker_root / "receipts"
claims: dict[str, tuple[pathlib.Path, dict[str, object], str]] = {}
grants: dict[str, tuple[pathlib.Path, dict[str, object], str]] = {}
receipts: dict[str, tuple[pathlib.Path, dict[str, object], str]] = {}
for path in regular_json_files(claim_root):
    document, digest = load_json(path, maximum_bytes=4 * 1024 * 1024)
    if document.get("schema") != "fortgym.m1b-root-broker-claim/v1" or document.get(
        "batch_id"
    ) != batch_id:
        continue
    validate_claim(document)
    if document.get("request_id") != path.stem:
        raise SystemExit("root broker claim path identity differs")
    claims[path.stem] = (path, document, digest)
for path in regular_json_files(grant_root):
    document, digest = load_json(path, maximum_bytes=4 * 1024 * 1024)
    if document.get("schema") != "fortgym.m1b-root-broker-action-grant/v1" or document.get(
        "batch_id"
    ) != batch_id:
        continue
    validate_grant(document)
    grant_identity = {
        "batch_id": document["batch_id"],
        "grant_kind": document["grant_kind"],
        "attempt_id": document["attempt_id"],
        "attempt_identity_sha256": document["attempt_identity_sha256"],
        "gate_id": document["gate_id"],
        "action": document["action"],
        "logical_argv_sha256": document["logical_argv_sha256"],
        "recovery_epoch": document["recovery_epoch"],
    }
    if document["action"] in read_only_actions:
        grant_identity["request_id"] = document["request_id"]
    if path.stem != sha256_bytes(canonical_bytes(grant_identity)):
        raise SystemExit("root broker action-grant path identity differs")
    grants[path.stem] = (path, document, digest)
for path in regular_json_files(receipt_root):
    document, digest = load_json(path, maximum_bytes=8 * 1024 * 1024)
    if document.get("schema") != "fortgym.m1b-root-broker-receipt/v1" or document.get(
        "batch_id"
    ) != batch_id:
        continue
    validate_private_receipt(document)
    if document.get("request_id") != path.stem:
        raise SystemExit("root broker receipt path identity differs")
    receipts[path.stem] = (path, document, digest)
if len(claims) != len(set(claims)) or len(grants) != len(set(grants)) or len(receipts) != len(
    set(receipts)
):
    raise SystemExit("root broker records contain duplicate identities")

final_claim = claims.get(final_request_id)
final_private = receipts.get(final_request_id)
if final_claim is None or final_private is None:
    raise SystemExit("final root broker claim/private receipt is absent")
if final_claim[2] != excluded.get("claim_sha256"):
    raise SystemExit("final root broker claim digest differs")
final_grant_matches = [
    item for item in grants.values() if item[2] == excluded.get("grant_sha256")
]
if len(final_grant_matches) != 1:
    raise SystemExit("final root broker action grant is absent or ambiguous")
final_grant_path, final_grant, final_grant_sha256 = final_grant_matches[0]
final_claim_document = final_claim[1]
final_private_document = final_private[1]

logical_argv = (
    "fortgym-root-broker",
    "attest-broker-evidence",
    batch_id,
    seal_sha256,
    post_cleanup_sha256,
)
logical_sha256 = sha256_bytes(canonical_bytes(list(logical_argv)))
expected_result = {
    "schema": "fortgym.m1b-root-broker-attestation-result/v1",
    "ok": True,
    "batch_id": batch_id,
    "path": expected_root_remote,
    "sha256": attestation_sha256,
}
if (
    final_claim_document.get("request_sha256") != excluded.get("request_sha256")
    or final_claim_document.get("gate_id") != "CLEANUP"
    or final_claim_document.get("grant_kind") != "batch_canary"
    or final_claim_document.get("attempt_id") is not None
    or final_claim_document.get("action") != "attest_broker_evidence"
    or final_grant.get("request_id") != final_request_id
    or final_grant.get("gate_id") != "CLEANUP"
    or final_grant.get("grant_kind") != "batch_canary"
    or final_grant.get("attempt_id") is not None
    or final_grant.get("attempt_identity_sha256") is not None
    or final_grant.get("action") != "attest_broker_evidence"
    or final_grant.get("logical_argv_sha256") != logical_sha256
    or final_grant.get("recovery_epoch") != 0
    or final_grant.get("batch_ledger_head_sha256") != batch_head_sha256
    or final_grant.get("one_shot") is not True
    or final_private_document.get("request_id") != final_request_id
    or final_private_document.get("request_sha256") != excluded.get("request_sha256")
    or final_private_document.get("gate_id") != "CLEANUP"
    or final_private_document.get("grant_kind") != "batch_canary"
    or final_private_document.get("attempt_id") is not None
    or final_private_document.get("attempt_identity_sha256") is not None
    or final_private_document.get("action") != "attest_broker_evidence"
    or final_private_document.get("binding") is not None
    or final_private_document.get("logical_argv_sha256") != logical_sha256
    or final_private_document.get("returncode") != 0
    or final_private_document.get("stdout")
    != canonical_bytes(expected_result, newline=True).decode("ascii")
    or final_private_document.get("stderr") != ""
    or final_private_document.get("result") != expected_result
    or final_private_document.get("action_grant_sha256") != final_grant_sha256
):
    raise SystemExit("final root broker claim/grant/private receipt closure differs")
expected_public_final = {
    key: value
    for key, value in final_private_document.items()
    if key not in {"stdout", "stderr"}
}
if set(public_final) != public_receipt_keys or public_final != expected_public_final:
    raise SystemExit("final public broker receipt differs from its root receipt")
if excluded.get("request_sha256") != final_private_document.get("request_sha256"):
    raise SystemExit("final broker request digest binding differs")

root_records = attestation.get("root_records")
if not isinstance(root_records, dict) or set(root_records) != {
    "claims",
    "grants",
    "receipts",
    "aggregate_sha256",
}:
    raise SystemExit("root broker inventory fields differ")
expected_inventory = {
    "claims": [
        {"id": identity, "sha256": item[2]}
        for identity, item in sorted(claims.items())
        if identity != final_request_id
    ],
    "grants": [
        {"id": identity, "sha256": item[2]}
        for identity, item in sorted(grants.items())
        if item[0] != final_grant_path
    ],
    "receipts": [
        {"id": identity, "sha256": item[2]}
        for identity, item in sorted(receipts.items())
        if identity != final_request_id
    ],
}
if any(root_records.get(key) != value for key, value in expected_inventory.items()) or (
    root_records.get("aggregate_sha256")
    != sha256_bytes(canonical_bytes(expected_inventory))
):
    raise SystemExit("root broker inventory differs from retrieved root records")
prior_claim_ids = {item["id"] for item in expected_inventory["claims"]}
prior_receipt_ids = {item["id"] for item in expected_inventory["receipts"]}
prior_grant_request_ids = {
    item[1].get("request_id")
    for item in grants.values()
    if item[0] != final_grant_path
}
for grant_path, grant_document, _grant_sha256 in grants.values():
    if grant_path == final_grant_path:
        continue
    request_id = grant_document.get("request_id")
    claim_item = claims.get(str(request_id))
    if claim_item is None:
        raise SystemExit("root broker grant lacks its prior claim")
    claim_document = claim_item[1]
    for key in ("request_id", "gate_id", "grant_kind", "attempt_id", "action"):
        if grant_document.get(key) != claim_document.get(key):
            raise SystemExit("root broker partial claim/grant identity differs")
if (
    not prior_receipt_ids.issubset(prior_grant_request_ids)
    or not prior_grant_request_ids.issubset(prior_claim_ids)
    or len(expected_inventory["grants"]) != len(prior_grant_request_ids)
):
    raise SystemExit("root broker prior record progression is contradictory")
if host.get("decision") == "GO" and (
    prior_claim_ids != prior_receipt_ids
    or prior_grant_request_ids != prior_receipt_ids
    or len(expected_inventory["grants"]) != len(prior_receipt_ids)
):
    raise SystemExit("root broker GO claim/grant/receipt closure is incomplete")

public_inventory = attestation.get("public_receipts")
if not isinstance(public_inventory, list) or len(public_inventory) > 8192:
    raise SystemExit("public broker receipt inventory is invalid")
observed_public_paths = []
observed_public_ids = set()
for item in public_inventory:
    if not isinstance(item, dict) or set(item) != {
        "request_id",
        "path",
        "sha256",
        "root_receipt_sha256",
    }:
        raise SystemExit("public broker inventory record fields differ")
    request_id = item.get("request_id")
    relative = item.get("path")
    if (
        not isinstance(request_id, str)
        or request_id_pattern.fullmatch(request_id) is None
        or request_id == final_request_id
        or request_id in observed_public_ids
    ):
        raise SystemExit("public broker inventory identity differs")
    claim_item = claims.get(request_id)
    if claim_item is None:
        raise SystemExit("public broker receipt lacks its root claim")
    expected_relative = (
        f"broker-client/{str(claim_item[1].get('gate_id'))}/{request_id}.json"
    )
    if not isinstance(relative, str) or relative != expected_relative:
        raise SystemExit("public broker inventory path differs")
    relative_path = pathlib.PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise SystemExit("public broker inventory path is unsafe")
    public_path = batch_root.joinpath(*relative_path.parts)
    public_document, public_digest = load_json(public_path, maximum_bytes=8 * 1024 * 1024)
    root_item = receipts.get(request_id)
    if root_item is None:
        raise SystemExit("public broker receipt lacks its root counterpart")
    root_document, root_digest = root_item[1], root_item[2]
    expected_public = {
        key: value for key, value in root_document.items() if key not in {"stdout", "stderr"}
    }
    if (
        set(public_document) != public_receipt_keys
        or public_document != expected_public
        or item.get("sha256") != public_digest
        or item.get("root_receipt_sha256") != root_digest
        or root_document.get("result") is not None
        or root_document.get("request_sha256") != claims[request_id][1].get(
            "request_sha256"
        )
    ):
        raise SystemExit("public/root broker receipt cross-binding differs")
    matching_grants = [
        grant
        for grant in grants.values()
        if grant[2] == root_document.get("action_grant_sha256")
    ]
    if len(matching_grants) != 1:
        raise SystemExit("prior root broker receipt lacks one action grant")
    grant_document = matching_grants[0][1]
    claim_document = claims[request_id][1]
    for key in ("request_id", "gate_id", "grant_kind", "attempt_id", "action"):
        if root_document.get(key) != claim_document.get(key) or root_document.get(
            key
        ) != grant_document.get(key):
            raise SystemExit("prior claim/grant/receipt identity differs")
    if (
        root_document.get("logical_argv_sha256")
        != grant_document.get("logical_argv_sha256")
        or root_document.get("attempt_identity_sha256")
        != grant_document.get("attempt_identity_sha256")
    ):
        raise SystemExit("prior broker grant/receipt command binding differs")
    observed_public_ids.add(request_id)
    observed_public_paths.append(relative)
root_receipt_ids = {item["id"] for item in expected_inventory["receipts"]}
if (
    observed_public_paths != sorted(observed_public_paths)
    or not observed_public_ids.issubset(root_receipt_ids)
    or (host.get("decision") == "GO" and observed_public_ids != root_receipt_ids)
):
    raise SystemExit("public broker receipt inventory is incomplete or unordered")

for forbidden in (
    "openai_api_key",
    "openrouter_api_key",
    "anthropic_api_key",
    "authorization: bearer",
    "sk-",
):
    for root in (claim_root, grant_root, receipt_root):
        for path in regular_json_files(root):
            if forbidden in path.read_text(encoding="utf-8", errors="strict").lower():
                raise SystemExit("broker evidence contains credential/provider material")

normalized = {
    "schema": "fortgym.m1b-root-broker-attestation-verification/v1",
    "batch_id": batch_id,
    "acceptance_sha256": acceptance_sha256,
    "plan_sha256": plan_sha256,
    "decision": host.get("decision"),
    "root_attestation_sha256": attestation_sha256,
    "root_reference_sha256": reference_sha256,
    "final_public_receipt_sha256": public_final_sha256,
    "final_request_id": final_request_id,
    "root_claim_count": len(expected_inventory["claims"]) + 1,
    "root_grant_count": len(expected_inventory["grants"]) + 1,
    "root_receipt_count": len(expected_inventory["receipts"]) + 1,
    "prior_public_receipt_count": len(public_inventory),
    "provider_calls": 0,
    "provider_cost_usd": 0,
    "shell": False,
}
if target.exists() or target.is_symlink():
    raise SystemExit("normalized root broker verification already exists")
descriptor, temporary = tempfile.mkstemp(prefix=".root-broker-attestation.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(canonical_bytes(normalized, newline=True).decode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
  then
    return 1
  fi
  BROKER_ATTESTATION_VERIFIED=1
}

collect_remote_evidence() {
  [[ -n "$REMOTE_IP" && -n "$SSH_KEY" \
     && "$CONTROL_MASTER_STARTED" -eq 1 \
     && "$CONTROL_MASTER_CLOSED" -eq 0 ]] || return 1
  local local_tar="$EVIDENCE_DIR/remote-evidence.tar"
  local partial_tar extract_stage
  local -a ssh_options=(
    -F /dev/null
    -i "$SSH_KEY"
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ConnectionAttempts=1
    -o ControlMaster=no
    -o "ControlPath=$CONTROL_PATH"
    -o ProxyCommand=/usr/bin/false
    -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=$KNOWN_HOSTS"
  )
  [[ ! -e "$local_tar" ]] || return 1
  [[ ! -e "$EVIDENCE_DIR/retrieved" ]] || return 1
  partial_tar="$(mktemp "$EVIDENCE_DIR/.remote-evidence.XXXXXX")"
  extract_stage="$(mktemp -d "$EVIDENCE_DIR/.retrieved.XXXXXX")"
  chmod 0600 "$partial_tar"
  if ! bounded_ssh ssh-evidence "$SSH_EVIDENCE_TIMEOUT_SECONDS" \
      "${ssh_options[@]}" "$SSH_USER@$REMOTE_IP" \
      sudo /bin/tar --format=posix --numeric-owner --owner=0 --group=0 \
        --sort=name --mtime=@0 -C /var/lib -cf - \
        fortgym-m1b/evidence \
        fortgym-m1b/broker/claims \
        fortgym-m1b/broker/grants \
        fortgym-m1b/broker/receipts \
        fortgym-m1b-root-evidence >"$partial_tar"; then
    return 1
  fi
  extract_evidence_tar "$partial_tar" "$extract_stage" || return 1
  mv -- "$partial_tar" "$local_tar" || return 1
  mv -- "$extract_stage" "$EVIDENCE_DIR/retrieved" || return 1
  local control_root="$EVIDENCE_DIR/retrieved/fortgym-m1b/evidence/$BATCH_ID/control"
  local required
  for required in gate-results.json decision.json evidence-manifest.json seal.json; do
    [[ -f "$control_root/$required" && ! -L "$control_root/$required" ]] \
      || return 1
  done
  for required in \
    bootstrap.json \
    nonroot-isolated-import.json \
    trusted-paths.json \
    runtime-check.json \
    docker-image-inspect.json \
    docker-repository-signature.txt \
    docker-daemon-config-validate.txt \
    docker-runtime-attestation.json \
    runtime-archive-attestation.json \
    provider-helper-bpf-attestation.json \
    docker-image-descriptor-attestation.json \
    provider-capability-probe.json \
    provider-prepare.json \
    provider-snapshot.json \
    provider-bootstrap-guard.json \
    provider-bootstrap-inner.json \
    provider-cleanup.json \
    provider-cleanup-idempotent.json \
    expiry-timer.txt \
    sudoers-check.txt \
    outer-egress.json \
    outer-egress-rules.json \
    output-counter-before.json \
    output-counter-after.json \
    forward-counter-before.json \
    forward-counter-after.json \
    forward-canary.json \
    loopback-canary.json \
    control-ssh-flow.json \
    canaries.json \
    outer-egress-post-run-rules-before.json \
    outer-egress-post-run-rules.json \
    outer-egress-post-run.json; do
    [[ -f "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence/$required" \
       && ! -L "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence/$required" ]] \
      || return 1
  done
  if ! python3 -I - \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence/outer-egress-post-run.json" \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence/outer-egress.json" \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence/control-ssh-flow.json" \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence/outer-egress-post-run-rules-before.json" \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence/outer-egress-post-run-rules.json" \
    "$ACCEPTANCE_SHA256" "$AUTHORITY_EXPIRY" <<'PY'
import hashlib
import json
import pathlib
import sys

post_path, activation_path, flow_path, before_path, after_path = map(
    pathlib.Path, sys.argv[1:6]
)
acceptance_sha256, authority_expiry = sys.argv[6:8]
payload = json.loads(post_path.read_text(encoding="utf-8"))
activation = json.loads(activation_path.read_text(encoding="utf-8"))
flow = json.loads(flow_path.read_text(encoding="utf-8"))
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
before = payload.get("exact_ssh_counter_before")
after = payload.get("exact_ssh_counter_after")
delta = payload.get("exact_ssh_counter_delta")
if (
    payload.get("schema")
    != "fortgym.m1b-outer-egress-post-run-verification/v1"
    or payload.get("ok") is not True
    or payload.get("acceptance_sha256") != acceptance_sha256
    or payload.get("authority_expires_at") != authority_expiry
    or payload.get("verification_mode") != "read-only"
    or payload.get("network_rules_mutated") is not False
    or payload.get("table") != "inet fortgym_m1b_outer"
    or payload.get("output_policy") != "drop"
    or payload.get("forward_policy") != "drop"
    or any(isinstance(value, bool) or not isinstance(value, int) for value in (before, after, delta))
    or after - before != delta
    or delta < 1
    or payload.get("exact_control_ssh_flow_sha256") != digest(flow_path)
    or payload.get("activation_guard_receipt_sha256") != digest(activation_path)
    or payload.get("rules_before_sha256") != digest(before_path)
    or payload.get("rules_after_sha256") != digest(after_path)
    or isinstance(payload.get("provider_calls"), bool)
    or payload.get("provider_calls") != 0
    or isinstance(payload.get("provider_cost_usd"), bool)
    or payload.get("provider_cost_usd") != 0
):
    raise SystemExit("post-run outer-egress verification evidence differs")
if (
    not isinstance(activation, dict)
    or activation.get("schema") != "fortgym.m1b-outer-egress-guard/v1"
    or activation.get("ok") is not True
    or activation.get("acceptance_sha256") != acceptance_sha256
    or activation.get("authority_expires_at") != authority_expiry
    or activation.get("output_policy") != "drop"
    or activation.get("forward_policy") != "drop"
    or activation.get("preserved_non_loopback_flow") != flow
    or activation.get("live_ruleset_verified_before_and_after_canaries") is not True
):
    raise SystemExit("activation outer-egress evidence differs")
PY
  then
    return 1
  fi
  validate_sealed_host_outcome \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b/evidence/$BATCH_ID" || return 1
  validate_post_seal_host_cleanup \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b/evidence/$BATCH_ID" || return 1
  validate_root_broker_attestation \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b/evidence/$BATCH_ID" \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b-root-evidence" \
    "$EVIDENCE_DIR/retrieved/fortgym-m1b/broker" || return 1
  local evidence_sha
  evidence_sha="$(sha256_file "$local_tar")"
  printf '%s  remote-evidence.tar\n' "$evidence_sha" \
    >"$EVIDENCE_DIR/remote-evidence.sha256"
  chmod 0600 "$EVIDENCE_DIR/remote-evidence.sha256"
  EVIDENCE_COLLECTED=1
  append_event evidence_retrieved "$evidence_sha"
}

close_control_master() {
  local graceful=0
  if [[ "$CONTROL_MASTER_CLOSED" -eq 1 ]]; then
    return 0
  fi
  if [[ -e "$CONTROL_PATH" ]]; then
    if bounded_ssh ssh-mux-exit "$SSH_CONTROL_TIMEOUT_SECONDS" \
        -F /dev/null -S "$CONTROL_PATH" -O exit "$SSH_USER@$REMOTE_IP"; then
      graceful=1
    fi
  elif [[ "$CONTROL_MASTER_STARTED" -eq 0 ]]; then
    graceful=1
  fi
  stop_control_master_supervisor 1 || graceful=0
  if [[ "$CONTROL_MASTER_STARTED" -eq 1 && "$graceful" -eq 1 ]]; then
    CONTROL_MASTER_CLOSED=1
    append_event ssh_control_master_closed 'the sole control TCP flow was closed'
    return 0
  fi
  if [[ "$CONTROL_MASTER_STARTED" -eq 0 ]]; then
    return 0
  fi
  append_event ssh_control_master_close_failed 'control master exit command failed'
  return 1
}

preserve_control_master_failure_evidence() {
  python3 -I - \
    "$EVIDENCE_DIR/control-master-local-cleanup-failure.json" \
    "$CONTROL_MASTER_SUPERVISOR_PID" \
    "$CONTROL_MASTER_SUPERVISOR_READY_FILE" \
    "$CONTROL_MASTER_SUPERVISOR_STATUS_FILE" \
    "$CONTROL_MASTER_CHILD_PID_FILE" "$CONTROL_PATH" <<'PY'
import hashlib
import json
import os
import pathlib
import sys
import tempfile

target = pathlib.Path(sys.argv[1])
pid_text = sys.argv[2]
ready_path, status_path, child_path, control_path = map(pathlib.Path, sys.argv[3:7])


def bounded_record(path: pathlib.Path):
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
        return {"present": True, "safe_regular_file": False}
    data = path.read_bytes()
    record = {
        "present": True,
        "safe_regular_file": True,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    try:
        record["json"] = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        record["json"] = None
    return record


child_pid = None
if child_path.exists() and child_path.is_file() and not child_path.is_symlink():
    raw = child_path.read_text(encoding="ascii", errors="strict").strip()
    if raw.isdigit() and int(raw) > 0:
        child_pid = int(raw)
payload = {
    "schema": "fortgym.m1b-control-master-local-cleanup-failure/v1",
    "absence_verified": False,
    "supervisor_process_group_id": int(pid_text) if pid_text.isdigit() else None,
    "child_pid": child_pid,
    "ready_receipt": bounded_record(ready_path),
    "final_receipt": bounded_record(status_path),
    "control_path_present": control_path.exists(),
    "temp_cleanup_attempted": False,
    "temp_directory_present_after_cleanup": None,
    "ephemeral_private_key_present_after_cleanup": None,
}
descriptor, temporary = tempfile.mkstemp(prefix=".control-master-failure.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

record_control_master_temp_cleanup_result() {
  local temp_present=0 key_present=0
  [[ -e "$TEMP_DIR" ]] && temp_present=1
  [[ -e "$SSH_KEY" ]] && key_present=1
  python3 -I - \
    "$EVIDENCE_DIR/control-master-local-cleanup-failure.json" \
    "$temp_present" "$key_present" <<'PY'
import json
import os
import pathlib
import sys
import tempfile

target = pathlib.Path(sys.argv[1])
payload = json.loads(target.read_text(encoding="utf-8"))
if payload.get("schema") != "fortgym.m1b-control-master-local-cleanup-failure/v1":
    raise SystemExit("control-master local cleanup evidence schema differs")
payload["temp_cleanup_attempted"] = True
payload["temp_directory_present_after_cleanup"] = bool(int(sys.argv[2]))
payload["ephemeral_private_key_present_after_cleanup"] = bool(int(sys.argv[3]))
descriptor, temporary = tempfile.mkstemp(prefix=".control-master-failure.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

on_exit() {
  local original_rc=$?
  local final_rc="$original_rc"
  local cleanup_convergence_rc=0
  local create_operation_reconcile_rc=0
  local receipt_pair_verified=0
  EXIT_TRIGGER_STAGE="$FAILURE_STAGE"
  trap - EXIT INT TERM HUP
  set +e
  release_ledger_lock

  if [[ "$CREATE_ATTEMPTED" -eq 1 ]]; then
    if reconcile_create_operation; then
      create_operation_reconcile_rc=0
    else
      create_operation_reconcile_rc=$?
    fi
  fi

  if [[ "$CREATE_SUCCEEDED" -eq 1 && "$EVIDENCE_COLLECTED" -eq 0 ]]; then
    collect_remote_evidence
    if [[ $? -ne 0 ]]; then
      append_event evidence_retrieval_failed 'remote evidence could not be retrieved'
    fi
  fi
  close_control_master || true
  if [[ "$CREATE_ATTEMPTED" -eq 1 ]]; then
    if gcloud_delete_and_verify; then
      cleanup_convergence_rc=0
    else
      cleanup_convergence_rc=$?
    fi
  fi
  if [[ "$CREATE_ATTEMPTED" -eq 1 \
        && ( "$create_operation_reconcile_rc" -ne 0 \
             || "$CREATE_OPERATION_TERMINAL" -ne 1 \
             || "$cleanup_convergence_rc" -ne 0 \
             || "$CLEANUP_VERIFIED" -ne 1 || "$EVIDENCE_COLLECTED" -ne 1 \
             || "$SEALED_HOST_OUTCOME_VERIFIED" -ne 1 \
             || "$POST_SEAL_HOST_CLEANUP_VERIFIED" -ne 1 \
             || "$BROKER_ATTESTATION_VERIFIED" -ne 1 ) ]]; then
    final_rc=1
  fi
  if [[ "$CONTROL_MASTER_STARTED" -eq 1 && "$CONTROL_MASTER_CLOSED" -ne 1 ]]; then
    final_rc=1
  fi
  if [[ "$CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED" -ne 1 ]]; then
    final_rc=1
  fi
  if [[ "$original_rc" -eq 0 && "$RUNNER_SUCCEEDED" -ne 1 ]]; then
    final_rc=1
  fi
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    if [[ "$CONTROL_MASTER_LOCAL_ABSENCE_VERIFIED" -ne 1 ]]; then
      preserve_control_master_failure_evidence || true
    fi
    if rm -rf -- "$TEMP_DIR" && [[ ! -e "$TEMP_DIR" ]]; then
      TEMP_DIR_ABSENCE_VERIFIED=1
    else
      final_rc=1
      if [[ ! -e "$EVIDENCE_DIR/control-master-local-cleanup-failure.json" ]]; then
        preserve_control_master_failure_evidence || true
      fi
    fi
    if [[ -e "$EVIDENCE_DIR/control-master-local-cleanup-failure.json" ]]; then
      record_control_master_temp_cleanup_result || final_rc=1
      append_event local_transport_cleanup_incomplete \
        "nonsecret_evidence=control-master-local-cleanup-failure.json supervisor_pid=${CONTROL_MASTER_SUPERVISOR_PID:-unknown}"
    fi
  elif [[ -n "$TEMP_DIR" && ! -e "$TEMP_DIR" ]]; then
    TEMP_DIR_ABSENCE_VERIFIED=1
  else
    final_rc=1
  fi
  if [[ -d "$EVIDENCE_DIR" ]]; then
    if write_receipt "$final_rc" \
        && verify_lifecycle_receipt_pair "$final_rc"; then
      receipt_pair_verified=1
    else
      final_rc=1
      /bin/rm -f -- \
        "$EVIDENCE_DIR/lifecycle-receipt.sha256" \
        "$EVIDENCE_DIR/lifecycle-receipt.json" >/dev/null 2>&1 || true
      if [[ -e "$EVIDENCE_DIR/lifecycle-receipt.sha256" \
            || -e "$EVIDENCE_DIR/lifecycle-receipt.json" ]]; then
        printf 'M1b lifecycle receipt pair could not be invalidated\n' >&2
      fi
    fi
  else
    final_rc=1
  fi
  if [[ "$final_rc" -eq 0 && "$receipt_pair_verified" -eq 1 ]]; then
    printf 'M1b lifecycle complete and residue-free: %s\n' "$EVIDENCE_DIR"
  else
    final_rc=1
    printf 'M1b lifecycle failed or cleanup proof is incomplete: %s\n' \
      "$EVIDENCE_DIR" >&2
  fi
  exit "$final_rc"
}

reserve_daily_cost() {
  local ledger="$DAILY_LEDGER_DIR/$AUTHORITY_DATE.jsonl"
  LEDGER_LOCK="$DAILY_LEDGER_DIR/$AUTHORITY_DATE.lock"
  if ! mkdir -- "$LEDGER_LOCK" 2>/dev/null; then
    die 'the daily cost ledger is locked by another lifecycle' 75
  fi
  LEDGER_LOCK_OWNED=1
  python3 -I - \
    "$ledger" "$RUN_ID" "$INSTANCE_NAME" "$MANIFEST_SHA256" \
    "$DAILY_CEILING_CENTS" "$WORST_CASE_TOTAL_CENTS" \
    "$MAX_AUTHORIZED_VM_COUNT" "$(now_iso)" <<'PY'
import json
import os
import pathlib
import re
import sys

ledger = pathlib.Path(sys.argv[1])
run_id = sys.argv[2]
instance_name = sys.argv[3]
manifest_sha256 = sys.argv[4]
ceiling = int(sys.argv[5])
reservation = int(sys.argv[6])
max_vm_count = int(sys.argv[7])
recorded_at = sys.argv[8]
reserved = 0
seen = set()
prior_ceiling = 0
if ledger.exists():
    if ledger.is_symlink() or not ledger.is_file():
        raise SystemExit("daily ledger is not one regular file")
    for line_number, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid daily ledger line {line_number}: {exc}")
        if item.get("schema") != "fortgym.m1b-cost-reservation/v1":
            raise SystemExit(f"unexpected daily ledger schema on line {line_number}")
        if item.get("authorized_local_date") != "2026-09-05":
            raise SystemExit(f"wrong authority date on ledger line {line_number}")
        amount = item.get("reserved_worst_case_cents")
        if amount != 800 or isinstance(amount, bool):
            raise SystemExit(f"invalid reservation on ledger line {line_number}")
        prior_id = item.get("run_id")
        if (
            not isinstance(prior_id, str)
            or re.fullmatch(r"[0-9a-f]{12}", prior_id) is None
            or prior_id in seen
        ):
            raise SystemExit(f"invalid or duplicate run id on ledger line {line_number}")
        if item.get("instance_name") != f"fortgym-m1b-20260905-{prior_id}":
            raise SystemExit(f"invalid instance name on ledger line {line_number}")
        if re.fullmatch(r"[0-9a-f]{64}", item.get("packet_manifest_sha256", "")) is None:
            raise SystemExit(f"invalid packet digest on ledger line {line_number}")
        item_ceiling = item.get("daily_ceiling_cents")
        if (
            item.get("timezone") != "America/New_York"
            or isinstance(item_ceiling, bool)
            or not isinstance(item_ceiling, int)
            or item_ceiling != ceiling
            or item_ceiling < prior_ceiling
            or item.get("reservation_released") is not False
            or item.get("reserved_before_cents") != reserved
            or item.get("reserved_after_cents") != reserved + amount
            or item.get("reserved_after_cents") > item_ceiling
        ):
            raise SystemExit(f"inconsistent reservation on ledger line {line_number}")
        seen.add(prior_id)
        reserved += amount
        prior_ceiling = item_ceiling
if len(seen) >= max_vm_count:
    raise SystemExit(
        f"authorized VM count refusal: {len(seen)}>={max_vm_count}"
    )
if run_id in seen:
    raise SystemExit("run id is already reserved in the daily ledger")
if reserved + reservation > ceiling:
    raise SystemExit(
        f"daily ceiling refusal: {reserved}+{reservation}>{ceiling} cents"
    )
record = {
    "schema": "fortgym.m1b-cost-reservation/v1",
    "authorized_local_date": "2026-09-05",
    "timezone": "America/New_York",
    "run_id": run_id,
    "instance_name": instance_name,
    "packet_manifest_sha256": manifest_sha256,
    "reserved_before_cents": reserved,
    "reserved_worst_case_cents": reservation,
    "reserved_after_cents": reserved + reservation,
    "daily_ceiling_cents": ceiling,
    "recorded_at": recorded_at,
    "reservation_released": False,
}
fd = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
with os.fdopen(fd, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    handle.flush()
    os.fsync(handle.fileno())
PY
  COST_RESERVED=1
  cp -p -- "$ledger" "$EVIDENCE_DIR/daily-cost-ledger.snapshot.jsonl"
  release_ledger_lock
  append_event cost_reserved \
    "worst_case_cents=$WORST_CASE_TOTAL_CENTS ceiling_cents=$DAILY_CEILING_CENTS"
}

validate_packet() {
  local manifest="$PACKET_DIR/MANIFEST.sha256"
  local name
  local -a required_packet_members=(
    MANIFEST.sha256
    PACKET.json
    docker-runtime-manifest.json
    fortgym-df-m1a.tar.zst
    fortgym-m1b-docker-runtime.tar
    fortgym-m1b-source.tar
    fortgym-m1b-wheelhouse.tar
    live-requirements.lock
    live-wheelhouse.sha256
    seed_tree.sha256z
    source-manifest.json
  )
  for name in "${required_packet_members[@]}"; do
    [[ -f "$PACKET_DIR/$name" && ! -L "$PACKET_DIR/$name" ]] \
      || die "required final packet member is absent or unsafe: $name" 66
  done
  python3 -I - "$PACKET_DIR" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
expected = {
    "MANIFEST.sha256",
    "PACKET.json",
    "docker-runtime-manifest.json",
    "fortgym-df-m1a.tar.zst",
    "fortgym-m1b-docker-runtime.tar",
    "fortgym-m1b-source.tar",
    "fortgym-m1b-wheelhouse.tar",
    "live-requirements.lock",
    "live-wheelhouse.sha256",
    "seed_tree.sha256z",
    "source-manifest.json",
}
entries = list(root.iterdir())
if {entry.name for entry in entries} != expected:
    raise SystemExit("final packet contains missing, nested, or extra top-level members")
if any(entry.is_symlink() or not entry.is_file() for entry in entries):
    raise SystemExit("every final packet member must be one regular non-symlink file")
manifest_members = expected - {"MANIFEST.sha256"}
records = {}
pattern = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+)")
for line_number, line in enumerate(
    (root / "MANIFEST.sha256").read_text(encoding="ascii").splitlines(), 1
):
    match = pattern.fullmatch(line)
    if match is None:
        raise SystemExit(f"invalid packet manifest line {line_number}")
    digest, name = match.groups()
    if name in records:
        raise SystemExit(f"duplicate packet manifest member: {name}")
    records[name] = digest
if set(records) != manifest_members:
    raise SystemExit("packet manifest member set differs from the final packet")
PY
  [[ -f "$manifest" && ! -L "$manifest" ]] \
    || die 'packet MANIFEST.sha256 is absent or unsafe' 66
  local observed_manifest
  observed_manifest="$(sha256_file "$manifest")"
  [[ "$observed_manifest" == "$MANIFEST_SHA256" ]] \
    || die 'out-of-band packet manifest digest differs' 65
  (
    cd -- "$PACKET_DIR"
    sha256sum --check --strict MANIFEST.sha256
  ) >"$EVIDENCE_DIR/packet-manifest-verification.txt"

  local packet_check
  packet_check="$(python3 -I - \
    "$PACKET_DIR/PACKET.json" "$PACKET_DIR/source-manifest.json" "$SCRIPT_DIR" \
    "$ACCEPTANCE_SHA256" "$ROOT_BROKER_SHA256" "$HOST_RUNNER_SHA256" <<'PY'
import hashlib
import json
import pathlib
import re
import sys

packet_path = pathlib.Path(sys.argv[1])
source_path = pathlib.Path(sys.argv[2])
script_dir = pathlib.Path(sys.argv[3])
expected_acceptance = sys.argv[4]
expected_root_broker_sha256 = sys.argv[5]
expected_host_runner_sha256 = sys.argv[6]
for path in (packet_path, source_path):
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"unsafe required packet member: {path.name}")
packet = json.loads(packet_path.read_text(encoding="utf-8"))
source = json.loads(source_path.read_text(encoding="utf-8"))
if not isinstance(packet, dict) or set(packet) != {
    "schema",
    "authority",
    "acceptance_sha256",
    "source",
    "runtime_archive",
    "docker_runtime",
    "wheelhouse",
    "seed",
    "runtime_proto",
    "packet_build_tools",
}:
    raise SystemExit("packet top-level fields differ")
if packet.get("schema") != "fortgym.m1b-live-input-packet/v1":
    raise SystemExit("wrong packet schema")
if packet.get("acceptance_sha256") != expected_acceptance:
    raise SystemExit("wrong acceptance digest")
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
if packet.get("authority") != expected_authority:
    raise SystemExit("packet authority differs")
if any(
    isinstance(packet["authority"].get(key), bool)
    for key in ("provider_calls", "provider_cost_usd")
):
    raise SystemExit("packet provider counters use booleans")
runtime_archive = packet.get("runtime_archive")
runtime_proto = packet.get("runtime_proto")
wheelhouse = packet.get("wheelhouse")
if not isinstance(runtime_archive, dict) or runtime_archive.get("platform") != "linux/amd64":
    raise SystemExit("packet runtime is not linux/amd64")
if not isinstance(runtime_proto, dict) or runtime_proto.get("runtime_binding_sha256") != (
    "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f"
):
    raise SystemExit("packet runtime binding differs")
if runtime_proto.get("e1_binding_changed") is not False:
    raise SystemExit("packet changes the E1 binding")
if not isinstance(wheelhouse, dict):
    raise SystemExit("packet wheelhouse record is absent")
if wheelhouse.get("network_install_required") is not False:
    raise SystemExit("packet requires a network install")
if wheelhouse.get("provider_sdks_present") is not False:
    raise SystemExit("packet includes provider SDKs")

docker_runtime = packet.get("docker_runtime")
docker_keys = {
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
}
if not isinstance(docker_runtime, dict) or set(docker_runtime) != docker_keys:
    raise SystemExit("packet Docker runtime fields differ")
if not (
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
    == ["containerd.io", "docker-ce-cli", "docker-ce"]
):
    raise SystemExit("packet Docker runtime contract differs")
expected_repository = {
    "architecture": "amd64",
    "base_url": "https://download.docker.com/linux/debian",
    "component": "stable",
    "inrelease_sha256": (
        "19916250e8c2de32f5938227de988b846c36ff0def8dabbb149592c949b80b85"
    ),
    "packages_gz_sha256": (
        "c745da94edd1809aa74f0bf45a72b5935e649d524de6405695dbdf4d5e54d7fd"
    ),
    "release_key_fingerprint": "9DC858229FC7DD38854AE2D88D81803C0EBFCD88",
    "release_signing_fingerprint": "D3306A018370199E527AE7997EA0A9C3F273FCD8",
    "signature_verified": True,
    "suite": "bookworm",
}
if docker_runtime.get("signed_repository") != expected_repository:
    raise SystemExit("packet Docker signed-repository proof differs")
expected_packages = {
    "containerd.io": (
        "2.2.1-1~debian.12~bookworm",
        "containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb",
        23_371_888,
        "3505acd8a8124077df5608293e933c5dfb0dac988f143019fa6efe98e79b92d5",
    ),
    "docker-ce": (
        "5:29.1.3-1~debian.12~bookworm",
        "docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb",
        21_018_900,
        "809c748027406afb4563bf61886e5ec0e3b5d34ff0353256ae618a2c6c5b29fc",
    ),
    "docker-ce-cli": (
        "5:29.1.3-1~debian.12~bookworm",
        "docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb",
        16_294_920,
        "fa4c2ad37fa4e5bc4bc5bd4098daec153e546c9ccd5419adf8f91e54f0a0e2bd",
    ),
}
packages = docker_runtime.get("packages")
if not isinstance(packages, list) or [
    item.get("package") if isinstance(item, dict) else None for item in packages
] != sorted(expected_packages):
    raise SystemExit("packet Docker package order or identities differ")
for item in packages:
    package = item["package"]
    version, filename, size, digest = expected_packages[package]
    if item != {
        "architecture": "amd64",
        "filename": filename,
        "package": package,
        "repository_path": f"dists/bookworm/pool/stable/amd64/{filename}",
        "sha256": digest,
        "size_bytes": size,
        "version": version,
    }:
        raise SystemExit(f"packet Docker package differs: {package}")
expected_binaries = {
    "/usr/bin/containerd": (
        "containerd.io",
        47_794_968,
        "8daa1fcfd4007b35fdc5240b2a2c57290bbe9bd4e015b945bb011819acb8f2e0",
    ),
    "/usr/bin/containerd-shim-runc-v2": (
        "containerd.io",
        8_310_616,
        "fef09005f009695a8a71427570efd9a4c979a2bb6f45b72c25f673aa39f6f9f2",
    ),
    "/usr/bin/ctr": (
        "containerd.io",
        24_890_808,
        "5cbd83cbc7d90828804bde5b10c721b9067add62979b6e45ee1abc80b26e4edb",
    ),
    "/usr/bin/docker": (
        "docker-ce-cli",
        43_984_210,
        "57d51e83d3673f4f40ba54c67f8b9ec75d9e3401c5f0795c5f443366eb9c85ec",
    ),
    "/usr/bin/docker-proxy": (
        "docker-ce",
        2_831_666,
        "4068c3ddb30f9d304101dfab6901559337611236e359da3cc8494e2a1ec98530",
    ),
    "/usr/bin/dockerd": (
        "docker-ce",
        94_463_240,
        "978d5d2e4f36c2904ef6787d0fd148b863a1e2556436900f8278c721b7d07127",
    ),
    "/usr/bin/runc": (
        "containerd.io",
        12_019_264,
        "488440797ffe0e90dcfa03537291ad6e7dfe260a0ffe7c395356db242226510e",
    ),
    "/usr/libexec/docker/docker-init": (
        "docker-ce",
        708_456,
        "b831fc949adfbf8afa5c8ccef4db0dacfc92f2cc884d9fcb50382eae17c60626",
    ),
}
binaries = docker_runtime.get("binaries")
if not isinstance(binaries, list) or [
    item.get("path") if isinstance(item, dict) else None for item in binaries
] != sorted(expected_binaries):
    raise SystemExit("packet Docker binary order or identities differ")
for item in binaries:
    path = item["path"]
    package, size, digest = expected_binaries[path]
    if item != {
        "architecture": "amd64",
        "mode": "0755",
        "package": package,
        "path": path,
        "sha256": digest,
        "size_bytes": size,
    }:
        raise SystemExit(f"packet Docker binary differs: {path}")
expected_inputs = {
    "InRelease": (
        46_614,
        "19916250e8c2de32f5938227de988b846c36ff0def8dabbb149592c949b80b85",
    ),
    "Packages.gz": (
        95_006,
        "c745da94edd1809aa74f0bf45a72b5935e649d524de6405695dbdf4d5e54d7fd",
    ),
    "containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb": (
        23_371_888,
        "3505acd8a8124077df5608293e933c5dfb0dac988f143019fa6efe98e79b92d5",
    ),
    "docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb": (
        16_294_920,
        "fa4c2ad37fa4e5bc4bc5bd4098daec153e546c9ccd5419adf8f91e54f0a0e2bd",
    ),
    "docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb": (
        21_018_900,
        "809c748027406afb4563bf61886e5ec0e3b5d34ff0353256ae618a2c6c5b29fc",
    ),
    "docker-keyring.gpg": (
        2_760,
        "a09e26b72228e330d55bf134b8eaca57365ef44bf70b8e27c5f55ea87a8b05e2",
    ),
}
archive_members = docker_runtime.get("archive_members")
if not isinstance(archive_members, list) or [
    item.get("path") if isinstance(item, dict) else None for item in archive_members
] != sorted(expected_inputs):
    raise SystemExit("packet Docker archive member order or identities differ")
for item in archive_members:
    name = item["path"]
    size, digest = expected_inputs[name]
    if item != {
        "mode": "0644",
        "path": name,
        "sha256": digest,
        "size_bytes": size,
    }:
        raise SystemExit(f"packet Docker archive member differs: {name}")
docker_manifest_path = packet_path.parent / "docker-runtime-manifest.json"
docker_archive_path = packet_path.parent / "fortgym-m1b-docker-runtime.tar"
docker_manifest_bytes = docker_manifest_path.read_bytes()
try:
    docker_manifest = json.loads(docker_manifest_bytes)
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("Docker runtime manifest is malformed") from exc
unlinked = {
    key: value
    for key, value in docker_runtime.items()
    if key not in {"archive", "archive_sha256", "manifest", "manifest_sha256"}
}
canonical_manifest = (
    json.dumps(
        docker_manifest,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n"
).encode("ascii")
if docker_manifest != unlinked or docker_manifest_bytes != canonical_manifest:
    raise SystemExit("Docker runtime manifest differs from PACKET.json")
if docker_runtime.get("manifest_sha256") != hashlib.sha256(
    docker_manifest_bytes
).hexdigest():
    raise SystemExit("Docker runtime manifest digest differs")
if docker_runtime.get("archive_sha256") != hashlib.sha256(
    docker_archive_path.read_bytes()
).hexdigest():
    raise SystemExit("Docker runtime archive digest differs")
source_files = source.get("files")
if not isinstance(source_files, list):
    raise SystemExit("source manifest file list is absent")
records = {
    item["path"]: item
    for item in source_files
    if isinstance(item, dict) and isinstance(item.get("path"), str)
}
if len(records) != len(source_files):
    raise SystemExit("source manifest contains invalid or duplicate paths")
required = (
    "infra/m1b/bootstrap_live_host.sh",
    "infra/m1b/activate_outer_egress_guard.sh",
    "infra/m1b/root_broker.py",
    "infra/m1b/run_live_acceptance.py",
)
for relative in required:
    item = records.get(relative)
    if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")):
        raise SystemExit(f"source manifest lacks pinned {relative}")
bootstrap = script_dir / "bootstrap_live_host.sh"
bootstrap_sha = hashlib.sha256(bootstrap.read_bytes()).hexdigest()
if bootstrap_sha != records[required[0]]["sha256"]:
    raise SystemExit("local bootstrap launcher differs from the final packet")
frozen_sources = {
    "infra/m1b/root_broker.py": expected_root_broker_sha256,
    "infra/m1b/run_live_acceptance.py": expected_host_runner_sha256,
}
for relative, expected in frozen_sources.items():
    local_path = script_dir / pathlib.PurePosixPath(relative).name
    if records[relative]["sha256"] != expected or hashlib.sha256(
        local_path.read_bytes()
    ).hexdigest() != expected:
        raise SystemExit(f"frozen packet source differs: {relative}")
print(bootstrap_sha)
PY
)" || die 'packet semantic verification failed' 65
  [[ "$packet_check" =~ ^[0-9a-f]{64}$ ]] \
    || die 'packet verification returned an invalid bootstrap digest' 65
  printf '%s  bootstrap_live_host.sh\n' "$packet_check" \
    >"$EVIDENCE_DIR/bootstrap-launcher.sha256"
  chmod 0600 "$EVIDENCE_DIR/bootstrap-launcher.sha256"
  append_event packet_verified "$MANIFEST_SHA256"
}

write_cost_proof() {
  python3 -I - "$EVIDENCE_DIR/cost-proof.json" "$MAX_DURATION_SECONDS" <<'PY'
import json
import os
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
duration = int(sys.argv[2])
payload = {
    "schema": "fortgym.m1b-conservative-cost-proof/v1",
    "machine_type": "e2-standard-16",
    "provisioning_model": "STANDARD",
    "maximum_duration_seconds": duration,
    "pricing_envelope": {
        "compute_cents": 600,
        "ephemeral_ipv4_cents": 16,
        "pd_balanced_50gib_cents": 18,
        "unallocated_contingency_cents": 166,
    },
    "reserved_worst_case_cents": 800,
    "daily_ceiling_cents": 21000,
    "within_ceiling": 800 <= 21000,
    "basis": (
        "8h upper envelope: compute <=$0.75/h; IPv4 <=$0.02/h; "
        "50 GiB pd-balanced <=$0.30/GiB-month with 672h/month; plus contingency"
    ),
    "hard_ceiling_not_target": True,
}
if duration <= 0 or duration > 28800 or not payload["within_ceiling"]:
    raise SystemExit("invalid cost envelope")
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
target.chmod(0o600)
PY
  local proof_sha
  proof_sha="$(sha256_file "$EVIDENCE_DIR/cost-proof.json")"
  printf '%s  cost-proof.json\n' "$proof_sha" >"$EVIDENCE_DIR/cost-proof.sha256"
  chmod 0600 "$EVIDENCE_DIR/cost-proof.sha256"
}

cloud_preflight() {
  local active_account impersonation credential_file_override access_token_file
  local token_host universe_domain compute_endpoint crm_endpoint billing_endpoint
  local disable_ssl custom_ca proxy_type proxy_address proxy_port
  local instance_residue disk_residue address_residue
  impersonation="$(gcloud config get-value auth/impersonate_service_account \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  [[ -z "$impersonation" || "$impersonation" == '(unset)' ]] \
    || die 'effective gcloud service-account impersonation is forbidden' 77
  printf '%s\n' "${impersonation:-'(unset)'}" \
    >"$EVIDENCE_DIR/gcp-effective-impersonation.txt"

  credential_file_override="$(gcloud config get-value auth/credential_file_override \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  [[ -z "$credential_file_override" \
     || "$credential_file_override" == '(unset)' ]] \
    || die 'effective gcloud credential-file override is forbidden' 77
  printf '%s\n' "${credential_file_override:-'(unset)'}" \
    >"$EVIDENCE_DIR/gcp-effective-credential-file-override.txt"

  access_token_file="$(gcloud config get-value auth/access_token_file \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  [[ -z "$access_token_file" || "$access_token_file" == '(unset)' ]] \
    || die 'effective gcloud access-token file is forbidden' 77
  printf '%s\n' "${access_token_file:-'(unset)'}" \
    >"$EVIDENCE_DIR/gcp-effective-access-token-file.txt"

  token_host="$(gcloud config get-value auth/token_host \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  [[ "$token_host" == 'https://oauth2.googleapis.com/token' ]] \
    || die 'effective gcloud OAuth token host differs' 77
  universe_domain="$(gcloud config get-value core/universe_domain \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  [[ "$universe_domain" == googleapis.com ]] \
    || die 'effective gcloud universe domain differs' 77
  compute_endpoint="$(gcloud config get-value api_endpoint_overrides/compute \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  crm_endpoint="$(gcloud config get-value \
    api_endpoint_overrides/cloudresourcemanager \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  billing_endpoint="$(gcloud config get-value api_endpoint_overrides/cloudbilling \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  for value in "$compute_endpoint" "$crm_endpoint" "$billing_endpoint"; do
    [[ -z "$value" || "$value" == '(unset)' ]] \
      || die 'effective gcloud API endpoint override is forbidden' 77
  done
  disable_ssl="$(gcloud config get-value auth/disable_ssl_validation \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  [[ -z "$disable_ssl" || "$disable_ssl" == '(unset)' \
     || "$disable_ssl" == False || "$disable_ssl" == false ]] \
    || die 'effective gcloud TLS validation is disabled' 77
  custom_ca="$(gcloud config get-value core/custom_ca_certs_file \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  proxy_type="$(gcloud config get-value proxy/type \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  proxy_address="$(gcloud config get-value proxy/address \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  proxy_port="$(gcloud config get-value proxy/port \
    --account="$ACCOUNT" --project="$PROJECT" 2>/dev/null)"
  for value in "$custom_ca" "$proxy_type" "$proxy_address" "$proxy_port"; do
    [[ -z "$value" || "$value" == '(unset)' ]] \
      || die 'effective gcloud custom trust or proxy configuration is forbidden' 77
  done
  python3 -I - "$EVIDENCE_DIR/gcp-effective-config-safety.json" \
    "$token_host" "$universe_domain" <<'PY'
import json
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
payload = {
    "schema": "fortgym.m1b-gcloud-effective-config-safety/v1",
    "oauth_token_host": sys.argv[2],
    "universe_domain": sys.argv[3],
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
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
target.chmod(0o600)
PY

  active_account="$(gcloud auth list \
    --account="$ACCOUNT" \
    --filter="account=$ACCOUNT" \
    --format='value(account)')"
  [[ "$active_account" == "$ACCOUNT" ]] \
    || die 'the immutable GCP account is not credentialed' 77
  GCLOUD_IDENTITY_ENV_VERIFIED=1
  printf '%s\n' "$active_account" >"$EVIDENCE_DIR/gcp-explicit-account.txt"

  gcloud projects describe "$PROJECT" \
    --account="$ACCOUNT" --project="$PROJECT" \
    --format='json(projectId,lifecycleState)' \
    >"$EVIDENCE_DIR/gcp-project.json"
  gcloud billing projects describe "$PROJECT" \
    --account="$ACCOUNT" --project="$PROJECT" \
    --format='json(projectId,billingEnabled)' \
    >"$EVIDENCE_DIR/gcp-billing.json"
  gcloud compute zones describe "$ZONE" \
    --account="$ACCOUNT" --project="$PROJECT" \
    --format='json(name,region,status)' \
    >"$EVIDENCE_DIR/gcp-zone.json"
  gcloud compute regions describe "$REGION" \
    --account="$ACCOUNT" --project="$PROJECT" \
    --format='json(name,status,quotas)' \
    >"$EVIDENCE_DIR/gcp-region-quotas.json"
  gcloud compute machine-types describe "$MACHINE_TYPE" \
    --account="$ACCOUNT" --project="$PROJECT" --zone="$ZONE" \
    --format='json(name,guestCpus,memoryMb)' \
    >"$EVIDENCE_DIR/gcp-machine-type.json"
  gcloud compute networks describe default \
    --account="$ACCOUNT" --project="$PROJECT" \
    --format='json(name,autoCreateSubnetworks,routingConfig)' \
    >"$EVIDENCE_DIR/gcp-default-network.json"
  gcloud compute networks subnets describe default \
    --account="$ACCOUNT" --project="$PROJECT" --region="$REGION" \
    --format='json(name,network,region,state,purpose,stackType,ipCidrRange,gatewayAddress)' \
    >"$EVIDENCE_DIR/gcp-default-subnet.json"
  gcloud compute routes list \
    --account="$ACCOUNT" --project="$PROJECT" \
    --filter='network:default AND destRange=0.0.0.0/0' \
    --format='json(name,network,destRange,nextHopGateway,priority)' \
    >"$EVIDENCE_DIR/gcp-default-routes.json"
  gcloud compute firewall-rules describe default-allow-ssh \
    --account="$ACCOUNT" --project="$PROJECT" \
    --format='json(name,network,direction,disabled,priority,sourceRanges,sourceTags,sourceServiceAccounts,targetTags,targetServiceAccounts,allowed,denied)' \
    >"$EVIDENCE_DIR/gcp-default-allow-ssh.json"
  gcloud compute project-info describe \
    --account="$ACCOUNT" --project="$PROJECT" \
    --format='json(commonInstanceMetadata)' \
    >"$EVIDENCE_DIR/gcp-project-common-metadata.json"

  python3 -I - \
    "$EVIDENCE_DIR/gcp-project.json" \
    "$EVIDENCE_DIR/gcp-billing.json" \
    "$EVIDENCE_DIR/gcp-zone.json" \
    "$EVIDENCE_DIR/gcp-region-quotas.json" \
    "$EVIDENCE_DIR/gcp-machine-type.json" \
    "$EVIDENCE_DIR/gcp-default-network.json" \
    "$EVIDENCE_DIR/gcp-default-subnet.json" \
    "$EVIDENCE_DIR/gcp-default-routes.json" \
    "$EVIDENCE_DIR/gcp-default-allow-ssh.json" \
    "$EVIDENCE_DIR/gcp-project-common-metadata.json" \
    "$EVIDENCE_DIR/gcp-network-preflight.json" <<'PY'
import hashlib
import ipaddress
import json
import pathlib
import sys

project, billing, zone, region, machine, network, subnet, routes, ssh_rule, metadata = (
    json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    for path in sys.argv[1:11]
)
output = pathlib.Path(sys.argv[11])
if project != {"projectId": "scrolller-307201", "lifecycleState": "ACTIVE"}:
    raise SystemExit("target project identity/state differs")
if billing != {"projectId": "scrolller-307201", "billingEnabled": True}:
    raise SystemExit("target project billing is not enabled")
if zone.get("name") != "us-central1-a" or zone.get("status") != "UP":
    raise SystemExit("target zone is not UP")
if not str(zone.get("region", "")).endswith("/us-central1"):
    raise SystemExit("target zone belongs to a different region")
if region.get("name") != "us-central1" or region.get("status") != "UP":
    raise SystemExit("target region is not UP")
if (
    machine.get("name") != "e2-standard-16"
    or int(machine.get("guestCpus", -1)) != 16
    or int(machine.get("memoryMb", -1)) != 65536
):
    raise SystemExit("machine type shape differs")
quotas = {}
for item in region.get("quotas", []):
    if not isinstance(item, dict) or not isinstance(item.get("metric"), str):
        raise SystemExit("region quota record is malformed")
    quotas[item["metric"]] = float(item.get("limit", 0)) - float(item.get("usage", 0))
required = {
    "E2_CPUS": 16,
    "INSTANCES": 1,
    "IN_USE_ADDRESSES": 1,
    "DISKS_TOTAL_GB": 50,
}
for metric, minimum in required.items():
    if quotas.get(metric, -1) < minimum:
        raise SystemExit(f"insufficient {metric} quota")

if (
    not isinstance(network, dict)
    or network.get("name") != "default"
    or network.get("autoCreateSubnetworks") is not True
    or not isinstance(network.get("routingConfig"), dict)
    or network["routingConfig"].get("routingMode") not in {"REGIONAL", "GLOBAL"}
):
    raise SystemExit("default VPC routing contract differs")
try:
    subnet_cidr = ipaddress.ip_network(subnet.get("ipCidrRange"), strict=True)
    gateway = ipaddress.ip_address(subnet.get("gatewayAddress"))
except (TypeError, ValueError) as exc:
    raise SystemExit("default regional subnet addressing is invalid") from exc
if (
    not isinstance(subnet, dict)
    or subnet.get("name") != "default"
    or not str(subnet.get("network", "")).endswith("/global/networks/default")
    or not str(subnet.get("region", "")).endswith("/regions/us-central1")
    or subnet.get("state") not in {None, "READY"}
    or subnet.get("purpose") != "PRIVATE"
    or subnet.get("stackType") != "IPV4_ONLY"
    or not isinstance(subnet_cidr, ipaddress.IPv4Network)
    or gateway not in subnet_cidr
):
    raise SystemExit("default regional subnet contract differs")
if not isinstance(routes, list) or len(routes) != 1:
    raise SystemExit("default VPC must have one unambiguous IPv4 internet route")
route = routes[0]
priority = route.get("priority") if isinstance(route, dict) else None
if (
    not isinstance(route, dict)
    or not isinstance(route.get("name"), str)
    or not str(route.get("network", "")).endswith("/global/networks/default")
    or route.get("destRange") != "0.0.0.0/0"
    or not str(route.get("nextHopGateway", "")).endswith(
        "/global/gateways/default-internet-gateway"
    )
    or isinstance(priority, bool)
    or not isinstance(priority, int)
    or not 0 <= priority <= 65535
):
    raise SystemExit("default VPC internet route differs")
ssh_priority = ssh_rule.get("priority") if isinstance(ssh_rule, dict) else None
if (
    not isinstance(ssh_rule, dict)
    or ssh_rule.get("name") != "default-allow-ssh"
    or not str(ssh_rule.get("network", "")).endswith("/global/networks/default")
    or ssh_rule.get("direction") != "INGRESS"
    or ssh_rule.get("disabled") is not False
    or isinstance(ssh_priority, bool)
    or not isinstance(ssh_priority, int)
    or not 0 <= ssh_priority <= 65535
    or ssh_rule.get("sourceRanges") != ["0.0.0.0/0"]
    or ssh_rule.get("sourceTags") not in (None, [])
    or ssh_rule.get("sourceServiceAccounts") not in (None, [])
    or ssh_rule.get("targetTags") not in (None, [])
    or ssh_rule.get("targetServiceAccounts") not in (None, [])
    or ssh_rule.get("allowed") != [{"IPProtocol": "tcp", "ports": ["22"]}]
    or ssh_rule.get("denied") not in (None, [])
):
    raise SystemExit("default VPC cannot prove untagged TCP/22 ingress")
common = metadata.get("commonInstanceMetadata") if isinstance(metadata, dict) else None
if common is None:
    items = []
elif isinstance(common, dict) and isinstance(common.get("items", []), list):
    items = common.get("items", [])
else:
    raise SystemExit("project common-instance metadata is malformed")
metadata_values = {}
for item in items:
    if (
        not isinstance(item, dict)
        or set(item) != {"key", "value"}
        or not isinstance(item.get("key"), str)
        or not isinstance(item.get("value"), str)
    ):
        raise SystemExit("project common-instance metadata item is malformed")
    key = item["key"].strip().lower()
    if not key or key in metadata_values:
        raise SystemExit("project common-instance metadata keys are ambiguous")
    metadata_values[key] = item["value"].strip().lower()
for key in ("enable-oslogin", "enable-oslogin-2fa"):
    if key in metadata_values and metadata_values[key] != "false":
        raise SystemExit(f"project common-instance metadata enables {key}")
raw_paths = [pathlib.Path(path) for path in sys.argv[6:11]]
proof = {
    "schema": "fortgym.m1b-gcp-network-preflight/v1",
    "project": "scrolller-307201",
    "zone": "us-central1-a",
    "region": "us-central1",
    "network": "default",
    "subnetwork": "default",
    "default_ipv4_route_verified": True,
    "untagged_tcp_22_ingress_verified": True,
    "project_oslogin_enabled": False,
    "project_oslogin_2fa_enabled": False,
    "inputs_sha256": {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in raw_paths
    },
}
output.write_text(
    json.dumps(proof, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
output.chmod(0o600)
PY

  instance_residue="$(gcloud compute instances list \
    --account="$ACCOUNT" --project="$PROJECT" --zones="$ZONE" \
    --filter="(name=$INSTANCE_NAME) OR (labels.fortgym-run-id=$RUN_ID)" \
    --format='value(name)')"
  disk_residue="$(gcloud compute disks list \
    --account="$ACCOUNT" --project="$PROJECT" --zones="$ZONE" \
    --filter="name=$INSTANCE_NAME" --format='value(name)')"
  address_residue="$(gcloud compute addresses list \
    --account="$ACCOUNT" --project="$PROJECT" --regions="$REGION" \
    --filter="(name=$INSTANCE_NAME) OR (labels.fortgym-run-id=$RUN_ID)" \
    --format='value(name)')"
  [[ -z "$instance_residue" && -z "$disk_residue" && -z "$address_residue" ]] \
    || die 'matching GCP residue exists before creation' 73
  append_event cloud_preflight_complete \
    'identity, billing, zone, quota, shape, default routing, SSH ingress, OS Login, and residue are valid'
}

capture_create_operation_baseline() {
  local raw="$EVIDENCE_DIR/create-operation-baseline-raw.json"
  CREATE_OPERATION_BASELINE_FILE="$EVIDENCE_DIR/create-operation-baseline.json"
  gcloud compute operations list \
    --account="$ACCOUNT" --project="$PROJECT" --zones="$ZONE" \
    --filter="operationType=insert AND targetLink~instances/$INSTANCE_NAME" \
    --format=json >"$raw" || return 1
  python3 -I - "$raw" "$CREATE_OPERATION_BASELINE_FILE" \
    "$INSTANCE_NAME" <<'PY'
import json
import os
import pathlib
import re
import sys
import tempfile

raw_path = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
instance_name = sys.argv[3]
payload = json.loads(raw_path.read_text(encoding="utf-8"))
if not isinstance(payload, list):
    raise SystemExit("pre-submit operation baseline is not a list")
names = []
for item in payload:
    if (
        not isinstance(item, dict)
        or item.get("operationType") != "insert"
        or not str(item.get("targetLink", "")).endswith(
            f"/zones/us-central1-a/instances/{instance_name}"
        )
        or not str(item.get("zone", "")).endswith("/zones/us-central1-a")
        or not isinstance(item.get("name"), str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", item["name"])
        is None
        or item.get("status") not in {"PENDING", "RUNNING", "DONE"}
    ):
        raise SystemExit("pre-submit operation baseline identity differs")
    if item["status"] != "DONE":
        raise SystemExit("a prior matching insert operation is not terminal")
    names.append(item["name"])
if len(names) != len(set(names)):
    raise SystemExit("pre-submit operation baseline has duplicate identities")
normalized = {
    "schema": "fortgym.m1b-create-operation-baseline/v1",
    "instance_name": instance_name,
    "operation_names": sorted(names),
    "all_prior_operations_terminal": True,
}
descriptor, temporary = tempfile.mkstemp(prefix=".create-operation-baseline.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
  append_event create_operation_baseline_captured \
    "path=$CREATE_OPERATION_BASELINE_FILE"
}

parse_create_operation() {
  local path="$1" parsed
  parsed="$(python3 -I - "$path" "$INSTANCE_NAME" \
    "$CREATE_OPERATION_BASELINE_FILE" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
instance_name = sys.argv[2]
baseline = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
try:
    response = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("create operation response is missing or malformed") from exc
if (
    not isinstance(response, list)
    or len(response) != 1
    or not isinstance(response[0], dict)
):
    raise SystemExit("create operation response must contain exactly one record")
payload = response[0]
name = payload.get("name")
status = payload.get("status")
if (
    not isinstance(baseline, dict)
    or baseline.get("schema") != "fortgym.m1b-create-operation-baseline/v1"
    or baseline.get("instance_name") != instance_name
    or baseline.get("all_prior_operations_terminal") is not True
    or not isinstance(baseline.get("operation_names"), list)
):
    raise SystemExit("create operation baseline differs")
if (
    not isinstance(name, str)
    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is None
    or payload.get("operationType") != "insert"
    or not str(payload.get("targetLink", "")).endswith(
        f"/zones/us-central1-a/instances/{instance_name}"
    )
    or not str(payload.get("zone", "")).endswith("/zones/us-central1-a")
    or status not in {"PENDING", "RUNNING", "DONE"}
    or name in baseline["operation_names"]
):
    raise SystemExit("create operation identity differs")
print(f"{name}|{status}")
PY
)" || return 1
  CREATE_OPERATION_NAME="${parsed%%|*}"
  CREATE_OPERATION_STATUS="${parsed#*|}"
  CREATE_OPERATION_CAPTURED=1
  append_event create_operation_captured \
    "name=$CREATE_OPERATION_NAME status=$CREATE_OPERATION_STATUS"
}

poll_create_operation() {
  [[ "$CREATE_OPERATION_CAPTURED" -eq 1 \
     && "$CREATE_OPERATION_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] \
    || return 1
  local attempt status_file parsed
  for attempt in $(seq 1 12); do
    status_file="$EVIDENCE_DIR/create-operation-status-$attempt.json"
    if ! gcloud compute operations describe "$CREATE_OPERATION_NAME" \
        --account="$ACCOUNT" --project="$PROJECT" --zone="$ZONE" \
        --format=json >"$status_file"; then
      CREATE_OPERATION_STATUS='status-query-failed'
    else
      parsed="$(python3 -I - "$status_file" "$INSTANCE_NAME" \
        "$CREATE_OPERATION_NAME" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
instance_name, operation_name = sys.argv[2:4]
if (
    not isinstance(payload, dict)
    or payload.get("name") != operation_name
    or payload.get("operationType") != "insert"
    or not str(payload.get("targetLink", "")).endswith(
        f"/zones/us-central1-a/instances/{instance_name}"
    )
    or not str(payload.get("zone", "")).endswith("/zones/us-central1-a")
    or payload.get("status") not in {"PENDING", "RUNNING", "DONE"}
):
    raise SystemExit("create operation status identity differs")
if payload["status"] == "DONE":
    print("DONE_ERROR" if payload.get("error") else "DONE_OK")
else:
    print(payload["status"])
PY
)" || return 1
      CREATE_OPERATION_STATUS="$parsed"
      if [[ "$parsed" == DONE_OK || "$parsed" == DONE_ERROR ]]; then
        CREATE_OPERATION_TERMINAL=1
        append_event create_operation_terminal \
          "name=$CREATE_OPERATION_NAME status=$parsed attempt=$attempt"
        return 0
      fi
    fi
    if [[ "$attempt" -lt 12 ]]; then
      authority_bounded_sleep 5 || break
    fi
  done
  append_event create_operation_incomplete \
    "name=$CREATE_OPERATION_NAME status=$CREATE_OPERATION_STATUS"
  return 1
}

lookup_create_operation() {
  local attempt listing parsed lookup_rc
  for attempt in $(seq 1 12); do
    listing="$EVIDENCE_DIR/create-operation-lookup-$attempt.json"
    if gcloud compute operations list \
        --account="$ACCOUNT" --project="$PROJECT" --zones="$ZONE" \
        --filter="operationType=insert AND targetLink~instances/$INSTANCE_NAME" \
        --format=json >"$listing"; then
      if parsed="$(python3 -I - "$listing" "$INSTANCE_NAME" \
          "$CREATE_OPERATION_BASELINE_FILE" <<'PY'
import json
import pathlib
import re
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
instance_name = sys.argv[2]
baseline = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
if (
    not isinstance(payload, list)
    or not isinstance(baseline, dict)
    or baseline.get("schema") != "fortgym.m1b-create-operation-baseline/v1"
    or baseline.get("instance_name") != instance_name
    or baseline.get("all_prior_operations_terminal") is not True
    or not isinstance(baseline.get("operation_names"), list)
    or any(not isinstance(item, str) for item in baseline["operation_names"])
):
    raise SystemExit(2)
matching = []
for item in payload:
    if not (
        isinstance(item, dict)
        and item.get("operationType") == "insert"
        and str(item.get("targetLink", "")).endswith(
            f"/zones/us-central1-a/instances/{instance_name}"
        )
        and str(item.get("zone", "")).endswith("/zones/us-central1-a")
        and isinstance(item.get("name"), str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", item["name"])
        is not None
        and item.get("status") in {"PENDING", "RUNNING", "DONE"}
    ):
        raise SystemExit(2)
    if item["name"] not in baseline["operation_names"]:
        matching.append(item["name"])
if len(matching) != len(set(matching)) or len(matching) > 1:
    raise SystemExit(2)
if not matching:
    raise SystemExit(1)
print(matching[0])
PY
)"; then
        CREATE_OPERATION_NAME="$parsed"
        CREATE_OPERATION_CAPTURED=1
        CREATE_OPERATION_STATUS='recovered'
        append_event create_operation_recovered \
          "name=$CREATE_OPERATION_NAME lookup_attempt=$attempt"
        return 0
      else
        lookup_rc=$?
        if [[ "$lookup_rc" -eq 2 ]]; then
          CREATE_OPERATION_STATUS='lookup-ambiguous'
          append_event create_operation_ambiguous "lookup_attempt=$attempt"
          return 1
        fi
      fi
    else
      CREATE_OPERATION_STATUS='lookup-query-failed'
    fi
    if [[ "$attempt" -lt 12 ]]; then
      authority_bounded_sleep 5 || break
    fi
  done
  CREATE_OPERATION_STATUS='lookup-empty-or-failed'
  append_event create_operation_unresolved 'bounded lookup found no unique insert operation'
  return 1
}

reconcile_create_operation() {
  [[ "$CREATE_ATTEMPTED" -eq 1 ]] || return 0
  if [[ "$CREATE_OPERATION_TERMINAL" -eq 1 ]]; then
    return 0
  fi
  if [[ "$CREATE_OPERATION_CAPTURED" -ne 1 ]]; then
    lookup_create_operation || return 1
  fi
  poll_create_operation
}

verify_created_instance() {
  local instance_json="$EVIDENCE_DIR/instance.json"
  local disk_json="$EVIDENCE_DIR/boot-disk.json"
  gcloud compute instances describe "$INSTANCE_NAME" \
    --account="$ACCOUNT" --project="$PROJECT" --zone="$ZONE" \
    --format=json >"$instance_json"
  gcloud compute disks describe "$INSTANCE_NAME" \
    --account="$ACCOUNT" --project="$PROJECT" --zone="$ZONE" \
    --format=json >"$disk_json"
  REMOTE_IP="$(python3 -I - \
    "$instance_json" "$disk_json" "$INSTANCE_NAME" "$RUN_ID" \
    "$MAX_DURATION_SECONDS" "$AUTHORITY_EXPIRY_EPOCH" <<'PY'
import datetime
import json
import pathlib
import sys

instance = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
disk = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
name, run_id = sys.argv[3], sys.argv[4]
duration, expiry = int(sys.argv[5]), int(sys.argv[6])
def require(condition, message):
    if not condition:
        raise SystemExit(message)

require(instance.get("name") == name, "instance name differs")
require(
    str(instance.get("machineType", "")).endswith("/e2-standard-16"),
    "machine type differs",
)
scheduling = instance["scheduling"]
require(scheduling.get("provisioningModel") == "STANDARD", "provisioning model differs")
require(scheduling.get("instanceTerminationAction") == "DELETE", "termination action differs")
max_duration = scheduling.get("maxRunDuration")
require(
    isinstance(max_duration, dict)
    and set(max_duration) == {"seconds", "nanos"}
    and max_duration.get("seconds") == str(duration)
    and max_duration.get("nanos") == 0
    and not isinstance(max_duration.get("nanos"), bool),
    "max duration differs",
)
require(scheduling.get("automaticRestart") is False, "automatic restart is enabled")
require(scheduling.get("onHostMaintenance") == "MIGRATE", "maintenance policy differs")
require(not instance.get("serviceAccounts"), "instance has a service account")
require(not instance.get("tags", {}).get("items"), "instance has network tags")
require(instance.get("deletionProtection") is False, "deletion protection is enabled")
expected_labels = {
    "fortgym-expiry": "20260905-200000z",
    "fortgym-owner": "cdossman",
    "fortgym-purpose": "m1b-live-acceptance",
    "fortgym-run-id": run_id,
}
require(instance.get("labels") == expected_labels, "instance labels differ")
disks = instance["disks"]
require(
    len(disks) == 1 and disks[0].get("boot") is True and disks[0].get("autoDelete") is True,
    "boot disk count or auto-delete differs",
)
interfaces = instance["networkInterfaces"]
require(
    len(interfaces) == 1 and interfaces[0].get("stackType", "IPV4_ONLY") == "IPV4_ONLY",
    "network interface or stack type differs",
)
access = interfaces[0]["accessConfigs"]
require(
    len(access) == 1 and access[0].get("type") == "ONE_TO_ONE_NAT",
    "external access configuration differs",
)
ip = access[0]["natIP"]
require(isinstance(ip, str) and bool(ip), "ephemeral IPv4 is absent")
require(disk.get("name") == name, "boot disk name differs")
require(disk.get("sizeGb") == "50", "boot disk size differs")
require(str(disk.get("type", "")).endswith("/pd-balanced"), "boot disk type differs")
require(
    str(disk.get("sourceImage", "")).endswith("/debian-12-bookworm-v20260811"),
    "boot disk source image differs",
)
require(not disk.get("sourceSnapshot"), "boot disk came from a snapshot")
started = datetime.datetime.fromisoformat(instance["lastStartTimestamp"].replace("Z", "+00:00"))
require(int(started.timestamp()) + duration <= expiry, "provider deletion exceeds authority expiry")
print(ip)
PY
)" || die 'created instance differs from the immutable lifecycle contract' 70
  [[ -n "$REMOTE_IP" && "$REMOTE_IP" != *[[:space:]]* ]] \
    || die 'created instance has no safe ephemeral IPv4 address' 70
  local reserved
  reserved="$(gcloud compute addresses list \
    --account="$ACCOUNT" --project="$PROJECT" --regions="$REGION" \
    --filter="address=$REMOTE_IP" --format='value(name)')"
  [[ -z "$reserved" ]] || die 'assigned IPv4 is a reserved address, not ephemeral' 70
  append_event instance_verified "$INSTANCE_NAME"
}

start_control_master() {
  local -a options=(
    -F /dev/null
    -i "$SSH_KEY"
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ConnectionAttempts=1
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o "UserKnownHostsFile=$KNOWN_HOSTS"
  )
  local attempt readiness master_timeout supervisor_rc abort_start
  master_timeout="$(remaining_runner_timeout)"
  for attempt in $(seq 1 30); do
    abort_start=0
    [[ ! -e "$CONTROL_PATH" ]] || return 1
    if ! launch_control_master_supervisor "$master_timeout" \
        "${options[@]}" -M -N -S "$CONTROL_PATH" "$SSH_USER@$REMOTE_IP"; then
      if stop_control_master_supervisor 1 \
          && [[ "$CONTROL_MASTER_SUPERVISOR_RC" -eq 255 ]] \
          && [[ "$attempt" -lt 30 ]]; then
        authority_bounded_sleep 5 || return 1
        continue
      fi
      return 1
    fi
    for readiness in $(seq 1 12); do
      if [[ -e "$CONTROL_PATH" ]] && bounded_ssh \
          ssh-mux-check "$SSH_CONTROL_TIMEOUT_SECONDS" \
          -F /dev/null -S "$CONTROL_PATH" -O check "$SSH_USER@$REMOTE_IP"; then
        CONTROL_MASTER_STARTED=1
        append_event ssh_control_master_ready \
          "attempt=$attempt single_tcp_flow=true"
        return 0
      fi
      if ! kill -0 "$CONTROL_MASTER_SUPERVISOR_PID" 2>/dev/null; then
        stop_control_master_supervisor 0 || abort_start=1
        supervisor_rc="$CONTROL_MASTER_SUPERVISOR_RC"
        if [[ "$supervisor_rc" -eq 124 ]]; then
          abort_start=1
        fi
        break
      fi
      if ! authority_bounded_sleep 1; then
        abort_start=1
        break
      fi
    done
    if [[ -n "$CONTROL_MASTER_SUPERVISOR_PID" ]]; then
      if [[ -e "$CONTROL_PATH" ]]; then
        bounded_ssh ssh-mux-abort "$SSH_CONTROL_TIMEOUT_SECONDS" \
          -F /dev/null -S "$CONTROL_PATH" -O exit "$SSH_USER@$REMOTE_IP" \
          >/dev/null 2>&1 || true
      fi
      if ! stop_control_master_supervisor 1; then
        abort_start=1
      elif [[ "$CONTROL_MASTER_SUPERVISOR_RC" -eq 124 ]]; then
        abort_start=1
      fi
    fi
    if [[ "$abort_start" -eq 1 ]]; then
      return 1
    fi
    if [[ "$attempt" -lt 30 ]]; then
      authority_bounded_sleep 5 || return 1
    fi
  done
  return 1
}

record_runner_outcome() {
  local raw="$EVIDENCE_DIR/host-runner-stdout.json"
  local normalized="$EVIDENCE_DIR/m1b-decision.json"
  M1B_DECISION="$(python3 -I - "$raw" "$normalized" "$BATCH_ID" "$TWO_FORT_DIAGNOSTIC" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile

raw_path = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
batch_id = sys.argv[3]
two_fort_diagnostic = sys.argv[4] == "1"
lines = raw_path.read_text(encoding="utf-8").splitlines()
if len(lines) != 1 or not lines[0]:
    raise SystemExit("host runner stdout is not exactly one JSON line")
payload = json.loads(lines[0])
required = {
    "schema",
    "batch_id",
    "decision",
    "real_runtime_attempts_started",
    "real_runtime_attempts_completed",
    "non_runtime_attempts_started",
    "non_runtime_attempts_completed",
    "gate_results_path",
    "decision_path",
    "evidence_manifest_path",
    "seal_path",
    "post_seal_cleanup_path",
    "post_seal_cleanup_sha256",
    "broker_attestation_path",
    "broker_attestation_sha256",
    "broker_attestation_reference_path",
    "broker_attestation_reference_sha256",
    "broker_attestation_receipt_path",
    "broker_attestation_receipt_sha256",
}
if not isinstance(payload, dict) or set(payload) != required:
    raise SystemExit("host runner outcome keys differ from the frozen schema")
if payload.get("schema") != "fortgym.m1b-host-runner-outcome/v1":
    raise SystemExit("host runner outcome schema differs")
if payload.get("batch_id") != batch_id:
    raise SystemExit("host runner batch identity differs")
decision = payload.get("decision")
if decision not in {"GO", "INCOMPLETE_NO_GO"}:
    raise SystemExit("host runner decision is invalid")
for started_name, completed_name, maximum in (
    ("real_runtime_attempts_started", "real_runtime_attempts_completed", 26),
    ("non_runtime_attempts_started", "non_runtime_attempts_completed", 1),
):
    started = payload[started_name]
    completed = payload[completed_name]
    if (
        not isinstance(started, int)
        or isinstance(started, bool)
        or not isinstance(completed, int)
        or isinstance(completed, bool)
        or not 0 <= completed <= started <= maximum
    ):
        raise SystemExit(f"invalid host runner attempt counts: {started_name}")
if decision == "GO" and (
    payload["real_runtime_attempts_started"] != 26
    or payload["real_runtime_attempts_completed"] != 26
    or payload["non_runtime_attempts_started"] != 1
    or payload["non_runtime_attempts_completed"] != 1
):
    raise SystemExit("GO host runner outcome lacks all exact attempt terminals")
if two_fort_diagnostic and (
    decision != "INCOMPLETE_NO_GO"
    or payload["real_runtime_attempts_started"] > 2
    or payload["non_runtime_attempts_started"] != 0
):
    raise SystemExit("two-fort diagnostic outcome exceeds its scope or claims full GO")
control = f"/var/lib/fortgym-m1b/evidence/{batch_id}/control"
batch_root = f"/var/lib/fortgym-m1b/evidence/{batch_id}"
expected_paths = {
    "gate_results_path": f"{control}/gate-results.json",
    "decision_path": f"{control}/decision.json",
    "evidence_manifest_path": f"{control}/evidence-manifest.json",
    "seal_path": f"{control}/seal.json",
    "post_seal_cleanup_path": f"{batch_root}/post-seal-host-cleanup.json",
    "broker_attestation_path": (
        f"/var/lib/fortgym-m1b-root-evidence/batches/{batch_id}/"
        "broker-attestation.json"
    ),
    "broker_attestation_reference_path": (
        f"{batch_root}/root-broker-attestation-reference.json"
    ),
}
for key, expected in expected_paths.items():
    if payload.get(key) != expected:
        raise SystemExit(f"host runner path differs: {key}")
receipt_path = payload.get("broker_attestation_receipt_path")
receipt_prefix = f"{batch_root}/broker-client/CLEANUP/"
if (
    not isinstance(receipt_path, str)
    or not receipt_path.startswith(receipt_prefix)
    or re.fullmatch(r"[0-9a-f]{64}\.json", receipt_path[len(receipt_prefix):]) is None
):
    raise SystemExit("host runner broker attestation receipt path differs")
for key in (
    "post_seal_cleanup_sha256",
    "broker_attestation_sha256",
    "broker_attestation_reference_sha256",
    "broker_attestation_receipt_sha256",
):
    if re.fullmatch(r"[0-9a-f]{64}", str(payload.get(key) or "")) is None:
        raise SystemExit(f"host runner content address is invalid: {key}")
record = {
    "schema": "fortgym.m1b-lifecycle-decision-observation/v1",
    "batch_id": batch_id,
    "m1b_decision": decision,
    "lifecycle_status": "pending_evidence_retrieval_and_cleanup",
    "decision_is_not_lifecycle_completion": True,
    "host_runner_outcome_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    "host_runner_outcome": payload,
}
fd, temporary = tempfile.mkstemp(prefix=".m1b-decision.", dir=target.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
print(decision)
PY
)" || die 'host runner outcome is absent or malformed' 70
  DECISION_RECORDED=1
}

verify_bootstrap_receipt() {
  local receipt="$EVIDENCE_DIR/bootstrap-host-receipt.json"
  local import_proof="$EVIDENCE_DIR/bootstrap-nonroot-isolated-import.json"
  local -a options=(
    -F /dev/null
    -i "$SSH_KEY"
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ConnectionAttempts=1
    -o ControlMaster=no
    -o "ControlPath=$CONTROL_PATH"
    -o ProxyCommand=/usr/bin/false
    -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=$KNOWN_HOSTS"
  )
  bounded_ssh ssh-bootstrap-receipt "$SSH_CONTROL_TIMEOUT_SECONDS" \
    "${options[@]}" "$SSH_USER@$REMOTE_IP" \
    sudo /bin/cat -- /var/lib/fortgym-m1b-root-evidence/bootstrap.json \
    >"$receipt"
  bounded_ssh ssh-import-receipt "$SSH_CONTROL_TIMEOUT_SECONDS" \
    "${options[@]}" "$SSH_USER@$REMOTE_IP" \
    sudo /bin/cat -- \
      /var/lib/fortgym-m1b-root-evidence/nonroot-isolated-import.json \
    >"$import_proof"
  chmod 0600 "$receipt" "$import_proof"
  python3 -I - \
    "$receipt" "$import_proof" "$ACCEPTANCE_SHA256" \
    "$PACKET_DIR/PACKET.json" "$MANIFEST_SHA256" \
    "$ROOT_BROKER_SHA256" <<'PY'
import datetime
import json
import pathlib
import re
import sys

receipt = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
proof = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
expected_acceptance = sys.argv[3]
packet = json.loads(pathlib.Path(sys.argv[4]).read_text(encoding="utf-8"))
manifest_sha256 = sys.argv[5]
root_broker_sha256 = sys.argv[6]
expected_pth = (
    "/opt/fortgym-m1b/venv/lib/python3.11/site-packages/fortgym-m1b-source.pth"
)
expected_pth_sha256 = "cfa04bac75c5d609673a9f4e2dcb49639bf291ffbc51b978722d7e0a03938544"
if receipt.get("schema") != "fortgym.m1b-live-host-bootstrap/v1":
    raise SystemExit("bootstrap receipt schema differs")
exact_receipt = {
    "ok": True,
    "acceptance_sha256": expected_acceptance,
    "authority_expires_at": "2026-09-06T12:00:00Z",
    "manifest_sha256_out_of_band": manifest_sha256,
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
    "docker_runtime_manifest_sha256": packet["docker_runtime"]["manifest_sha256"],
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
    "python_major_minor": "3.11",
    "source_pth_path": expected_pth,
    "nonroot_isolated_import_ok": True,
    "nonroot_measurement_code_digest_ok": True,
    "source_path_preserves_repo_file": True,
    "root_broker_is_only_sudo_target": True,
    "service_user_in_docker_group": False,
    "root_evidence_private": True,
    "dependency_install_mode": "python3.11-venv-offline-pinned-wheels",
    "dependency_waivers": False,
    "runtime_image_id": (
        "sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c"
    ),
    "root_broker_sha256": root_broker_sha256,
    "expiry_timer_next_elapse": "2026-09-06T12:00:00Z",
    "provider_calls": 0,
    "provider_cost_usd": 0,
}
for key, expected in exact_receipt.items():
    if receipt.get(key) != expected:
        raise SystemExit(f"bootstrap receipt differs: {key}")
if any(
    isinstance(receipt.get(key), bool)
    for key in ("provider_calls", "provider_cost_usd")
):
    raise SystemExit("bootstrap provider counters use booleans")
if receipt.get("source_pth_sha256") != expected_pth_sha256:
    raise SystemExit("bootstrap source pth digest differs")
if re.fullmatch(r"[0-9a-f]{64}", receipt.get("measurement_code_sha256", "")) is None:
    raise SystemExit("bootstrap measurement code digest is invalid")
for key in (
    "docker_runtime_attestation_sha256",
    "runtime_archive_attestation_sha256",
    "provider_helper_bpf_attestation_sha256",
    "docker_image_descriptor_attestation_sha256",
    "trusted_paths_sha256",
):
    if re.fullmatch(r"[0-9a-f]{64}", receipt.get(key, "")) is None:
        raise SystemExit(f"bootstrap subordinate digest is invalid: {key}")
expected_receipt_keys = {
    "schema",
    "bootstrap_completed_at",
    "source_pth_sha256",
    "measurement_code_sha256",
    "docker_runtime_attestation_sha256",
    "runtime_archive_attestation_sha256",
    "provider_helper_bpf_attestation_sha256",
    "docker_image_descriptor_attestation_sha256",
    "trusted_paths_sha256",
    *exact_receipt,
}
if set(receipt) != expected_receipt_keys:
    raise SystemExit("bootstrap receipt fields differ")
try:
    completed_at = datetime.datetime.fromisoformat(receipt["bootstrap_completed_at"])
except (KeyError, TypeError, ValueError) as exc:
    raise SystemExit("bootstrap completion timestamp is invalid") from exc
if completed_at.tzinfo is None or not (
    datetime.datetime(2026, 9, 5, 4, tzinfo=datetime.UTC)
    <= completed_at.astimezone(datetime.UTC)
    <= datetime.datetime(2026, 9, 6, 12, tzinfo=datetime.UTC)
):
    raise SystemExit("bootstrap completed outside infrastructure authority")
exact_proof = {
    "schema": "fortgym.m1b-nonroot-isolated-import/v1",
    "ok": True,
    "effective_uid_nonzero": True,
    "python_isolated": True,
    "source_root": "/opt/fort-gym-m1a",
    "package_file": "/opt/fort-gym-m1a/fort_gym/__init__.py",
    "source_pth": expected_pth,
    "runtime_binding_sha256": (
        "9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f"
    ),
    "provider_environment_present": False,
}
if set(proof) != {*exact_proof, "source_pth_sha256", "measurement_code_sha256"}:
    raise SystemExit("nonroot isolated import proof fields differ")
for key, expected in exact_proof.items():
    if proof.get(key) != expected:
        raise SystemExit(f"nonroot isolated import proof differs: {key}")
if proof.get("source_pth_sha256") != expected_pth_sha256:
    raise SystemExit("bootstrap and nonroot proof pth digests differ")
if proof.get("measurement_code_sha256") != receipt.get("measurement_code_sha256"):
    raise SystemExit("bootstrap and nonroot proof measurement digests differ")
PY
}

upload_and_execute() {
  local remote_bootstrap="/tmp/fortgym-m1b-bootstrap-$RUN_ID.sh"
  local local_bootstrap_sha remote_bootstrap_sha
  local_bootstrap_sha="$(sha256_file "$SCRIPT_DIR/bootstrap_live_host.sh")"
  local -a options=(
    -F /dev/null
    -i "$SSH_KEY"
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o ConnectTimeout=15
    -o ConnectionAttempts=1
    -o ControlMaster=no
    -o "ControlPath=$CONTROL_PATH"
    -o ProxyCommand=/usr/bin/false
    -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=$KNOWN_HOSTS"
  )
  REMOTE_PACKET_DIR="/tmp/fortgym-m1b-packet-$RUN_ID"
  bounded_scp scp-packet "$SSH_TRANSFER_TIMEOUT_SECONDS" \
    -r "${options[@]}" "$PACKET_DIR" \
    "$SSH_USER@$REMOTE_IP:$REMOTE_PACKET_DIR"
  bounded_scp scp-bootstrap "$SSH_TRANSFER_TIMEOUT_SECONDS" \
    "${options[@]}" "$SCRIPT_DIR/bootstrap_live_host.sh" \
    "$SSH_USER@$REMOTE_IP:$remote_bootstrap"
  remote_bootstrap_sha="$(bounded_ssh ssh-bootstrap-digest \
    "$SSH_CONTROL_TIMEOUT_SECONDS" "${options[@]}" "$SSH_USER@$REMOTE_IP" \
    /usr/bin/sha256sum -- "$remote_bootstrap" | awk '{print $1}')"
  [[ "$remote_bootstrap_sha" == "$local_bootstrap_sha" ]] \
    || die 'remote bootstrap launcher digest differs' 65

  FAILURE_STAGE='host-bootstrap'
  bounded_ssh ssh-bootstrap "$SSH_BOOTSTRAP_TIMEOUT_SECONDS" \
    "${options[@]}" "$SSH_USER@$REMOTE_IP" \
    sudo /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
      /bin/bash "$remote_bootstrap" \
      --packet-dir "$REMOTE_PACKET_DIR" \
      --manifest-sha256 "$MANIFEST_SHA256"
  verify_bootstrap_receipt
  BOOTSTRAP_SUCCEEDED=1
  append_event bootstrap_complete "$INSTANCE_NAME"

  FAILURE_STAGE='outer-egress-guard'
  bounded_ssh ssh-guard "$SSH_GUARD_TIMEOUT_SECONDS" \
    "${options[@]}" "$SSH_USER@$REMOTE_IP" \
    sudo /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
      /bin/bash /opt/fort-gym-m1a/infra/m1b/activate_outer_egress_guard.sh
  GUARD_SUCCEEDED=1
  append_event outer_egress_guard_active "$INSTANCE_NAME"

  FAILURE_STAGE='live-acceptance-runner'
  set +e
  local runner_timeout
  local -a runner_options=(--private-test-mode)
  if [[ "$TWO_FORT_DIAGNOSTIC" -eq 1 ]]; then
    runner_options+=(--two-fort-diagnostic)
  fi
  runner_timeout="$(remaining_runner_timeout)"
  bounded_ssh ssh-runner "$runner_timeout" \
    "${options[@]}" "$SSH_USER@$REMOTE_IP" \
    sudo -u fortgym /usr/bin/env -i \
      HOME=/home/fortgym USER=fortgym LOGNAME=fortgym \
      PATH=/opt/fortgym-m1b/venv/bin:/usr/bin:/bin \
      DF_PROTO_ENABLED=1 \
      /opt/fortgym-m1b/venv/bin/python -I \
      /opt/fort-gym-m1a/infra/m1b/run_live_acceptance.py \
      "${runner_options[@]}" \
      --batch-id "$BATCH_ID" \
      --packet-root /opt/fortgym-m1b/packet \
      --state-root /var/lib/fortgym-m1b \
    | tee "$EVIDENCE_DIR/host-runner-stdout.json"
  local -a pipeline_status=("${PIPESTATUS[@]}")
  set -e
  RUNNER_EXIT_CODE="${pipeline_status[0]}"
  [[ "${pipeline_status[1]}" -eq 0 ]] \
    || die 'local host-runner outcome capture failed' 74
  [[ "$RUNNER_EXIT_CODE" -eq 0 ]] \
    || die "host runner failed with exit code $RUNNER_EXIT_CODE" 70
  record_runner_outcome
  RUNNER_SUCCEEDED=1
  append_event runner_complete "$BATCH_ID decision=$M1B_DECISION"

  FAILURE_STAGE='outer-egress-post-run-verification'
  bounded_ssh ssh-guard-post-run "$SSH_GUARD_TIMEOUT_SECONDS" \
    "${options[@]}" "$SSH_USER@$REMOTE_IP" \
    sudo /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
      /bin/bash /opt/fort-gym-m1a/infra/m1b/activate_outer_egress_guard.sh \
      --verify-only
  append_event outer_egress_post_run_verified "$INSTANCE_NAME"
}

main() {
  while (($#)); do
    case "$1" in
      --two-fort-diagnostic)
        [[ "$TWO_FORT_DIAGNOSTIC" -eq 0 ]] || usage
        TWO_FORT_DIAGNOSTIC=1
        shift
        ;;
      --packet-dir)
        (($# >= 2)) || usage
        PACKET_DIR="$2"
        shift 2
        ;;
      --manifest-sha256)
        (($# >= 2)) || usage
        MANIFEST_SHA256="$2"
        shift 2
        ;;
      --evidence-dir)
        (($# >= 2)) || usage
        EVIDENCE_DIR="$2"
        shift 2
        ;;
      --daily-ledger-dir)
        (($# >= 2)) || usage
        DAILY_LEDGER_DIR="$2"
        shift 2
        ;;
      --run-id)
        (($# >= 2)) || usage
        RUN_ID="$2"
        shift 2
        ;;
      *) usage ;;
    esac
  done

  [[ "$PACKET_DIR" == /* && -d "$PACKET_DIR" && ! -L "$PACKET_DIR" ]] || usage
  [[ "$EVIDENCE_DIR" == /* && ! -e "$EVIDENCE_DIR" ]] || usage
  [[ "$DAILY_LEDGER_DIR" == /* && ! -L "$DAILY_LEDGER_DIR" ]] || usage
  [[ "$MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]] || usage
  [[ "$RUN_ID" =~ ^[0-9a-f]{12}$ ]] || usage
  PACKET_DIR="$(realpath -- "$PACKET_DIR")"
  mkdir -m 0700 -- "$EVIDENCE_DIR"
  EVIDENCE_DIR="$(realpath -- "$EVIDENCE_DIR")"
  mkdir -p -m 0700 -- "$DAILY_LEDGER_DIR"
  DAILY_LEDGER_DIR="$(realpath -- "$DAILY_LEDGER_DIR")"
  trap on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM HUP

  INSTANCE_NAME="fortgym-m1b-20260905-$RUN_ID"
  BATCH_ID="m1b-live-20260905-$RUN_ID"
  LABELS="fortgym-expiry=20260905-200000z,fortgym-owner=cdossman,fortgym-purpose=m1b-live-acceptance,fortgym-run-id=$RUN_ID"
  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/fortgym-m1b-lifecycle.XXXXXX")"
  SSH_KEY="$TEMP_DIR/id_ed25519"
  KNOWN_HOSTS="$TEMP_DIR/known_hosts"
  CONTROL_PATH="$TEMP_DIR/c"
  CONTROL_MASTER_CHILD_PID_FILE="$TEMP_DIR/master-child.pid"
  CONTROL_MASTER_SUPERVISOR_READY_FILE="$TEMP_DIR/master-supervisor-ready.json"
  CONTROL_MASTER_SUPERVISOR_STATUS_FILE="$TEMP_DIR/master-supervisor-final.json"
  : >"$KNOWN_HOSTS"

  FAILURE_STAGE='local-command-environment'
  resolve_external_commands
  validate_local_command_environment

  FAILURE_STAGE='packet-verification'
  validate_packet

  refresh_max_duration

  FAILURE_STAGE='cost-proof'
  write_cost_proof

  FAILURE_STAGE='cloud-preflight'
  cloud_preflight
  gcloud compute images describe "$IMAGE" \
    --account="$ACCOUNT" --project="$IMAGE_PROJECT" --format=json \
    >"$EVIDENCE_DIR/image.json"
  python3 -I - "$EVIDENCE_DIR/image.json" <<'PY'
import json
import pathlib
import sys

image = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if image.get("name") != "debian-12-bookworm-v20260811":
    raise SystemExit("image name differs")
if image.get("architecture") != "X86_64":
    raise SystemExit("image architecture is not X86_64")
if image.get("status") != "READY":
    raise SystemExit("image is not READY")
PY
  reserve_daily_cost

  FAILURE_STAGE='ssh-key-generation'
  ssh-keygen -q -t ed25519 -N '' -C "$INSTANCE_NAME" -f "$SSH_KEY"
  local public_key
  public_key="$(tr -d '\n' <"$SSH_KEY.pub")"
  [[ "$public_key" == ssh-ed25519\ * ]] || die 'ephemeral SSH public key is invalid' 70

  FAILURE_STAGE='authority-recheck'
  refresh_max_duration

  FAILURE_STAGE='create-operation-baseline'
  capture_create_operation_baseline \
    || die 'could not freeze the pre-submit insert-operation baseline' 70

  FAILURE_STAGE='instance-create'
  CREATE_ATTEMPTED=1
  local create_rc
  if gcloud compute instances create "$INSTANCE_NAME" \
      --account="$ACCOUNT" \
      --project="$PROJECT" \
      --zone="$ZONE" \
      --machine-type="$MACHINE_TYPE" \
      --provisioning-model="$PROVISIONING_MODEL" \
      --image="$IMAGE" \
      --image-project="$IMAGE_PROJECT" \
      --boot-disk-size="$BOOT_DISK_SIZE" \
      --boot-disk-type="$BOOT_DISK_TYPE" \
      --boot-disk-auto-delete \
      --network-interface='network=default,address=,network-tier=PREMIUM,stack-type=IPV4_ONLY' \
      --no-service-account \
      --no-scopes \
      --no-restart-on-failure \
      --maintenance-policy=MIGRATE \
      --no-deletion-protection \
      --max-run-duration="${MAX_DURATION_SECONDS}s" \
      --instance-termination-action=DELETE \
      --labels="$LABELS" \
      --metadata="block-project-ssh-keys=true,ssh-keys=$SSH_USER:$public_key" \
      --async \
      --format=json \
      --quiet >"$EVIDENCE_DIR/create-operation-submit.json"; then
    create_rc=0
  else
    create_rc=$?
  fi
  if [[ -s "$EVIDENCE_DIR/create-operation-submit.json" ]]; then
    parse_create_operation "$EVIDENCE_DIR/create-operation-submit.json" || true
  fi
  [[ "$create_rc" -eq 0 ]] \
    || die "bounded instance create failed with exit code $create_rc" 70
  [[ "$CREATE_OPERATION_CAPTURED" -eq 1 ]] \
    || die 'instance create returned no exact operation identity' 70
  poll_create_operation \
    || die 'instance insert operation did not reach a terminal state' 70
  [[ "$CREATE_OPERATION_STATUS" == DONE_OK ]] \
    || die 'instance insert operation terminated with an error' 70
  CREATE_SUCCEEDED=1
  append_event instance_created "$INSTANCE_NAME"

  FAILURE_STAGE='instance-contract-verification'
  verify_created_instance

  FAILURE_STAGE='ssh-control-master'
  start_control_master \
    || die 'instance did not establish the sole pinned SSH control flow' 70

  upload_and_execute

  FAILURE_STAGE='evidence-retrieval'
  collect_remote_evidence
  FAILURE_STAGE='workload-complete'
}

main "$@"
