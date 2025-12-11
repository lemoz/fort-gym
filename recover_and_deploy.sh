#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# DFHack Fork Storm Recovery & RPC Verification Script
# ==============================================================================
# This script:
# 1. Recovers a wedged GCE VM by masking dfhack-headless on startup
# 2. Patches DFHack core to remove system() calls and enforce call-once
# 3. Installs hardened systemd unit with resource limits
# 4. Verifies RPC connectivity and generates payload report
# ==============================================================================

# Configuration
PROJECT="${DFHACK_GCP_PROJECT:-}"
ZONE="${DFHACK_GCP_ZONE:-us-central1-a}"
INSTANCE="${DFHACK_GCP_INSTANCE:-dfhack-host}"
SSH_KEY="${HOME}/.ssh/google_compute_engine"
VM_USER="cdossman"
VM_IP="34.41.155.134"
RESIZE_MACHINE_TYPE="${DFHACK_MACHINE_TYPE:-e2-standard-4}"
USE_GCLOUD="${DFHACK_USE_GCLOUD:-false}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +'%H:%M:%S')] WARN:${NC} $*"; }
error() { echo -e "${RED}[$(date +'%H:%M:%S')] ERROR:${NC} $*"; }

REMOTE="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ${VM_USER}@${VM_IP}"

# ==============================================================================
# Phase 0: VM Recovery via GCP (Optional)
# ==============================================================================
recovery_via_gcp() {
  if [[ "$USE_GCLOUD" != "true" ]]; then
    warn "Skipping GCP recovery (set DFHACK_USE_GCLOUD=true to enable)"
    return 0
  fi

  if [[ -z "$PROJECT" ]]; then
    error "DFHACK_GCP_PROJECT not set. Cannot use gcloud recovery."
    return 1
  fi

  log "Phase 0: Recovering VM via GCP startup script..."

  log "Stopping instance: $INSTANCE"
  gcloud compute instances stop "$INSTANCE" --zone "$ZONE" --project "$PROJECT" || true
  sleep 10

  log "Adding one-shot startup script to mask dfhack-headless"
  gcloud compute instances add-metadata "$INSTANCE" \
    --zone "$ZONE" --project "$PROJECT" \
    --metadata startup-script='#!/bin/bash
set -euxo pipefail
systemctl stop dfhack-headless  || true
systemctl disable dfhack-headless || true
systemctl mask dfhack-headless || true
pkill -f "dwarfort|dfhack-headless-pty.exp|dfhack-run" || true
if ! swapon --show | grep -q /swapfile; then
  (fallocate -l 16G /swapfile || dd if=/dev/zero of=/swapfile bs=1G count=16)
  chmod 600 /swapfile
  mkswap /swapfile
  grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
  swapon -a
fi
echo "RECOVERY_STARTUP_SCRIPT_RAN $(date)" >> /var/log/startup-script.log
'

  log "Resizing machine to $RESIZE_MACHINE_TYPE for rebuild headroom"
  gcloud compute instances set-machine-type "$INSTANCE" \
    --machine-type "$RESIZE_MACHINE_TYPE" --zone "$ZONE" --project "$PROJECT" || warn "Resize failed, continuing"

  log "Starting instance: $INSTANCE"
  gcloud compute instances start "$INSTANCE" --zone "$ZONE" --project "$PROJECT"

  log "Waiting 30s for boot..."
  sleep 30

  log "Removing startup script (won't run on next boot)"
  gcloud compute instances remove-metadata "$INSTANCE" \
    --keys startup-script --zone "$ZONE" --project "$PROJECT" || warn "Failed to remove startup script"
}

# ==============================================================================
# Phase 1: Wait for SSH
# ==============================================================================
wait_for_ssh() {
  log "Phase 1: Waiting for SSH connectivity..."
  local max_attempts=30
  local attempt=1

  while [[ $attempt -le $max_attempts ]]; do
    log "SSH attempt $attempt/$max_attempts..."
    if $REMOTE 'echo CONNECTED' >/dev/null 2>&1; then
      log "SSH connected successfully!"
      return 0
    fi
    sleep 5
    ((attempt++))
  done

  error "Failed to connect via SSH after $max_attempts attempts"
  return 1
}

# ==============================================================================
# Phase 2: Patch DFHack Core (Remove system() calls, enforce call-once)
# ==============================================================================
patch_dfhack_core() {
  log "Phase 2: Patching DFHack core to remove system() calls..."

  $REMOTE 'sudo python3 - <<'"'"'PY'"'"'
from pathlib import Path
import re, sys

roots=[Path("/opt/dfhack"), Path("/opt/dfhack-src"), Path("/opt/dfhack-work"), Path("/opt")]
core=None
for r in roots:
    if not r.exists():
        continue
    for p in r.rglob("Core.cpp"):
        if p.name=="Core.cpp" and "library" in str(p.parent):
            core=p
            break
    if core:
        break

if not core:
    print("ERROR: Core.cpp not found in any of:", [str(r) for r in roots], file=sys.stderr)
    sys.exit(1)

print(f"Found Core.cpp at: {core}", file=sys.stderr)
s=core.read_text()

# 1) Remove any system(...) calls
original_len = len(s)
s = re.sub(r"\bsystem\s*\(.*?\)\s*;\s*", "", s, flags=re.S)
if len(s) != original_len:
    print(f"Removed {original_len - len(s)} chars of system() calls", file=sys.stderr)

# 2) Inject once-guarded helper if missing
ins_head = (
    "\"#include \"RemoteServer.h\"\\n"
    "#include <mutex>\\n#include <fstream>\\n"
    "static std::once_flag g_remote_once;\\n"
    "static void ensure_remote_server_started(){\\n"
    "  std::call_once(g_remote_once, []{\\n"
    "    uint16_t port=5000; if(const char* e=getenv(\"DFHACK_PORT\")){ long v=strtol(e,nullptr,10); if(v>0&&v<65536) port=(uint16_t)v; }\\n"
    "    bool ok=false; try{ ok=DFHack::ServerMain::listen(port).get(); } catch(...){ ok=false; }\\n"
    "    if(FILE* f=fopen(\"/opt/dwarf-fortress/dfhack-remote.log\",\"a\")){ fprintf(f,\"[core-autoboot] %s on %u\\\\n\", ok?\"listening\":\"failed\", port); fclose(f);} \\n"
    "    fprintf(stderr,\"[core-autoboot] %s on %u\\\\n\", ok?\"listening\":\"failed\", port);\\n"
    "  });\\n"
    "}\\n"
)

if "static std::once_flag g_remote_once" not in s:
    print("Injecting once-guarded helper", file=sys.stderr)
    s = s.replace("#include \"RemoteServer.h\"", ins_head)
else:
    print("Once-guarded helper already present", file=sys.stderr)

# 3) Ensure call inside Core::init()
if "ensure_remote_server_started();" not in s:
    print("Adding ensure_remote_server_started() to Core::init()", file=sys.stderr)
    s = re.sub(r"(void\s+Core::init\s*\([^)]*\)\s*\{)", r"\1\\n  ensure_remote_server_started();", s, count=1)
else:
    print("ensure_remote_server_started() already called in init", file=sys.stderr)

# 4) Neutralize any other direct listens
s = re.sub(r"(\bServerMain::listen\s*\()", r"/* disabled: core-autoboot owns listen */ \1", s)

core.write_text(s)
print(f"PATCHED {core}")
PY'

  log "DFHack core patched successfully"
}

# ==============================================================================
# Phase 3: Rebuild DFHack
# ==============================================================================
rebuild_dfhack() {
  log "Phase 3: Rebuilding DFHack..."

  $REMOTE 'set -e
sudo install -d -m 0755 /opt/dfhack-build
cd /opt/dfhack-build

# Find DFHack source
DFHACK_SRC=""
for dir in /opt/dfhack /opt/dfhack-src /opt/dfhack-work/src; do
  if [ -f "$dir/CMakeLists.txt" ]; then
    DFHACK_SRC="$dir"
    break
  fi
done

if [ -z "$DFHACK_SRC" ]; then
  echo "ERROR: DFHack source not found"
  exit 1
fi

echo "Using DFHack source: $DFHACK_SRC"

sudo cmake -S "$DFHACK_SRC" -B . -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/opt/dwarf-fortress
sudo cmake --build . -j
sudo cmake --install .

echo ""
echo "=== BINARY VERIFICATION ==="
echo "Checking for core-autoboot markers (should see output):"
strings /opt/dwarf-fortress/hack/libdfhack.so | grep -E "core-autoboot|ensure_remote_server_started" || echo "ERROR: NO_CORE_AUTOBOOT_MARKERS"

echo ""
echo "Checking for system() artifacts (should be empty):"
if strings /opt/dwarf-fortress/hack/libdfhack.so | grep -i "ensure\.touch"; then
  echo "ERROR: system() artifacts still present!"
  exit 1
else
  echo "OK: No system() artifacts found"
fi
'

  log "DFHack rebuilt and installed"
}

# ==============================================================================
# Phase 4: Install Hardened Systemd Unit & Launchers
# ==============================================================================
install_hardened_unit() {
  log "Phase 4: Installing hardened systemd unit and launchers..."

  # Install dfhack-headless.sh
  $REMOTE "sudo tee /opt/dwarf-fortress/bin/dfhack-headless.sh >/dev/null" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/dwarf-fortress
export TERM=xterm-256color
export DFHACK_HEADLESS=1
: "${DFHACK_PORT:=5000}"
export LD_LIBRARY_PATH="$PWD/libs:$PWD/hack"
export LD_PRELOAD="$PWD/hack/libdfhack.so"
exec ./dwarfort
SH

  $REMOTE 'sudo chmod 0755 /opt/dwarf-fortress/bin/dfhack-headless.sh'

  # Install dfhack-headless-pty.exp
  $REMOTE "sudo tee /opt/dwarf-fortress/bin/dfhack-headless-pty.exp >/dev/null" <<'EXP'
#!/usr/bin/expect -f
set timeout -1
spawn -noecho /opt/dwarf-fortress/bin/dfhack-headless.sh
for {set i 0} {$i < 12} {incr i} { after 400; send "\r" }
interact
EXP

  $REMOTE 'sudo chmod 0755 /opt/dwarf-fortress/bin/dfhack-headless-pty.exp'

  # Install df-ready.sh
  $REMOTE "sudo tee /opt/dwarf-fortress/bin/df-ready.sh >/dev/null" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
for i in {1..120}; do ss -lnt | grep -q "127.0.0.1:5000" && break; sleep 0.5; done
[ -d /opt/dwarf-fortress/data/save/region1 ] || exit 0
for i in {1..10}; do /opt/dwarf-fortress/dfhack-run load-save region1 && break; sleep 1; done
/opt/dwarf-fortress/dfhack-run lua -e 'print("savePath=", dfhack.getSavePath())' || true
exit 0
SH

  $REMOTE 'sudo chmod 0755 /opt/dwarf-fortress/bin/df-ready.sh'

  # Install systemd unit
  $REMOTE "sudo tee /etc/systemd/system/dfhack-headless.service >/dev/null" <<'UNIT'
[Unit]
Description=DF + DFHack (headless, RPC autoboot)
After=network.target
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
Type=simple
WorkingDirectory=/opt/dwarf-fortress
Environment=TERM=xterm-256color
Environment=DFHACK_HEADLESS=1
Environment=DFHACK_PORT=5000
ExecStart=/opt/dwarf-fortress/bin/dfhack-headless-pty.exp
ExecStartPost=/opt/dwarf-fortress/bin/df-ready.sh
Restart=on-failure
RestartSec=10
KillMode=control-group
TimeoutStopSec=15
MemoryAccounting=yes
MemoryMax=4G
TasksMax=512
StandardOutput=append:/opt/dwarf-fortress/dfhack-stdout.log
StandardError=append:/opt/dwarf-fortress/dfhack-stderr.log

[Install]
WantedBy=multi-user.target
UNIT

  $REMOTE 'sudo systemctl daemon-reload'

  log "Hardened unit and launchers installed"
}

# ==============================================================================
# Phase 5: Start Service & Clean Logs
# ==============================================================================
start_service() {
  log "Phase 5: Starting dfhack-headless service..."

  $REMOTE 'set -e
sudo systemctl unmask dfhack-headless || true
sudo systemctl enable dfhack-headless
sudo systemctl stop dfhack-headless || true
sudo pkill -f "dwarfort|dfhack-headless-pty.exp|ensure.touch" || true
sudo rm -f /opt/dwarf-fortress/ensure.touch
sudo truncate -s 0 /opt/dwarf-fortress/dfhack-stdout.log /opt/dwarf-fortress/dfhack-stderr.log /opt/dwarf-fortress/dfhack-remote.log || true
sudo systemctl restart dfhack-headless
'

  log "Waiting 10s for service to stabilize..."
  sleep 10
}

# ==============================================================================
# Phase 6: Verify RPC Connectivity & Generate Payload
# ==============================================================================
verify_and_report() {
  log "Phase 6: Verifying RPC connectivity and generating payload..."

  # Generate payload
  local output
  output=$($REMOTE 'set +e
echo "=== LISTENER ==="
ss -lntp 2>/dev/null | grep -E "127\\.0\\.0\\.1:5000.+dwarfort" || echo "NO_LISTENER"

echo "=== PID & MAPS ==="
PID=$(pgrep -n -f "dwarfort|Dwarf Fortress" || true)
echo "PID=$PID"
if [ -n "$PID" ]; then
  awk "/libdfhack\\.so/{print; exit}" /proc/$PID/maps 2>/dev/null || echo "NO_LIB_MAPPED"
else
  echo "NO_LIB_MAPPED"
fi

echo "=== EXEC ==="
cd /opt/dwarf-fortress
./dfhack-run ls 2>&1 | head -n 10 || echo "RUN_FAIL_LS"
./dfhack-run lua -e '"'"'print("rpc-console-ok")'"'"' 2>&1 || echo "RUN_FAIL_LUA"

echo "=== REMOTE LOG ==="
tail -n 10 /opt/dwarf-fortress/dfhack-remote.log 2>/dev/null || echo "NO_REMOTE_LOG"
')

  echo ""
  echo "================================================================================"
  echo " VERIFICATION PAYLOAD"
  echo "================================================================================"
  echo "$output"
  echo "================================================================================"

  # Parse output to determine PASS/FAIL
  if echo "$output" | grep -q "NO_LISTENER"; then
    error "FAIL: No RPC listener detected"
    echo ""
    echo "FAIL"
    echo "$output"

    # Diagnostics
    warn "Gathering diagnostics..."
    $REMOTE 'set +e
echo "=== ENV ==="
PID=$(pgrep -n -f "dwarfort" || true)
if [ -n "$PID" ]; then
  tr "\\0" "\\n" < /proc/$PID/environ 2>/dev/null | grep -E "^(DFHACK_|TERM=)" | sort
fi

echo "=== STDERR ==="
tail -n 100 /opt/dwarf-fortress/dfhack-stderr.log 2>/dev/null || echo "NO_STDERR_LOG"
'
    return 1
  elif echo "$output" | grep -q "RUN_FAIL_LS\|RUN_FAIL_LUA"; then
    error "FAIL: RPC execution failed"
    echo ""
    echo "FAIL"
    echo "$output"
    return 1
  elif echo "$output" | grep -q "NO_LIB_MAPPED"; then
    error "FAIL: libdfhack.so not loaded"
    echo ""
    echo "FAIL"
    echo "$output"
    return 1
  else
    log "PASS: RPC connectivity verified!"
    echo ""
    echo "PASS"
    echo "$output"
    return 0
  fi
}

# ==============================================================================
# Main
# ==============================================================================
main() {
  log "Starting DFHack recovery and deployment..."
  log "VM: ${VM_USER}@${VM_IP}"
  log "GCP Mode: $USE_GCLOUD"

  if [[ "$USE_GCLOUD" == "true" ]]; then
    recovery_via_gcp
  else
    warn "Skipping GCP recovery. If VM is wedged, manually restart it first."
    warn "Or set: DFHACK_USE_GCLOUD=true DFHACK_GCP_PROJECT=your-project"
  fi

  wait_for_ssh
  patch_dfhack_core
  rebuild_dfhack
  install_hardened_unit
  start_service
  verify_and_report

  log "Recovery and deployment complete!"
}

main "$@"
