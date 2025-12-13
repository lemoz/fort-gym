#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Direct DFHack Fix Deployment (VM already accessible)
# ==============================================================================
# Run this AFTER manually restarting the VM via GCP Console
# This script assumes SSH is working
# ==============================================================================

VM_USER="cdossman"
VM_IP="34.41.155.134"
SSH_KEY="${HOME}/.ssh/google_compute_engine"

REMOTE="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ${VM_USER}@${VM_IP}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $*"; }
error() { echo -e "${RED}[$(date +'%H:%M:%S')] ERROR:${NC} $*"; }

# Test connectivity
log "Testing SSH connectivity..."
if ! $REMOTE 'echo CONNECTED' >/dev/null 2>&1; then
  error "Cannot connect to VM. Please restart it via GCP Console first."
  exit 1
fi
log "SSH connection successful!"

# Stop service and clean up
log "Stopping dfhack-headless and cleaning up..."
$REMOTE 'set -e
sudo systemctl stop dfhack-headless || true
sudo pkill -x dwarfort || true
sudo pkill -f "[d]fhack-headless-pty\\.exp" || true
sudo pkill -f "[d]fhack-run" || true
sudo pkill -f "ensure\\.touc[h]" || true
sudo rm -f /opt/dwarf-fortress/ensure.touch
sudo truncate -s 0 /opt/dwarf-fortress/dfhack-stdout.log /opt/dwarf-fortress/dfhack-stderr.log /opt/dwarf-fortress/dfhack-remote.log || true
'

# Patch DFHack core
log "Patching DFHack core to remove system() calls..."
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

assert core, "Core.cpp not found"
print(f"Found Core.cpp at: {core}", file=sys.stderr)
s=core.read_text()

# Remove system() calls
s = re.sub(r"\bsystem\s*\(.*?\)\s*;\s*", "", s, flags=re.S)

# Inject once-guarded helper
ins_head = """#include "RemoteServer.h"
#include <mutex>
#include <fstream>
static std::once_flag g_remote_once;
static void ensure_remote_server_started(){
  std::call_once(g_remote_once, []{
    uint16_t port=5000; if(const char* e=getenv("DFHACK_PORT")){ long v=strtol(e,nullptr,10); if(v>0&&v<65536) port=(uint16_t)v; }
    bool ok=false; try{ ok=DFHack::ServerMain::listen(port).get(); } catch(...){ ok=false; }
    if(FILE* f=fopen("/opt/dwarf-fortress/dfhack-remote.log","a")){ fprintf(f,"[core-autoboot] %s on %u\\n", ok?"listening":"failed", port); fclose(f);}
    fprintf(stderr,"[core-autoboot] %s on %u\\n", ok?"listening":"failed", port);
  });
}
"""

if "static std::once_flag g_remote_once" not in s:
    s = s.replace("#include \"RemoteServer.h\"", ins_head)

if "ensure_remote_server_started();" not in s:
    s = re.sub(r"(void\s+Core::init\s*\([^)]*\)\s*\{)", r"\1\n  ensure_remote_server_started();", s, count=1)

s = re.sub(r"(\bServerMain::listen\s*\()", r"/* disabled: core-autoboot owns listen */ \1", s)

core.write_text(s)
print(f"PATCHED {core}")
PY'

# Rebuild DFHack
log "Rebuilding DFHack (this may take 5-10 minutes)..."
$REMOTE 'set -e
sudo install -d -m 0755 /opt/dfhack-build
cd /opt/dfhack-build

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

# Install hardened unit
log "Installing hardened systemd unit..."
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

$REMOTE "sudo tee /opt/dwarf-fortress/bin/dfhack-headless-pty.exp >/dev/null" <<'EXP'
#!/usr/bin/expect -f
set timeout -1
spawn -noecho /opt/dwarf-fortress/bin/dfhack-headless.sh
for {set i 0} {$i < 12} {incr i} { after 400; send "\r" }
interact
EXP

$REMOTE 'sudo chmod 0755 /opt/dwarf-fortress/bin/dfhack-headless-pty.exp'

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

# Start service
log "Starting dfhack-headless service..."
$REMOTE 'sudo systemctl enable dfhack-headless && sudo systemctl restart dfhack-headless'

log "Waiting 10s for service to stabilize..."
sleep 10

# Verify and report
log "Verifying RPC connectivity..."
$REMOTE 'set +e
echo ""
echo "================================================================================"
echo "=== LISTENER ==="
ss -lntp 2>/dev/null | grep -E "127\\.0\\.0\\.1:5000.+dwarfort" || echo "NO_LISTENER"

echo ""
echo "=== PID & MAPS ==="
PID=$(pgrep -n -f "dwarfort" || true)
echo "PID=$PID"
[ -n "$PID" ] && awk "/libdfhack\\.so/{print; exit}" /proc/$PID/maps || echo "NO_LIB_MAPPED"

echo ""
echo "=== EXEC ==="
cd /opt/dwarf-fortress
./dfhack-run ls | head -n 10 || echo "RUN_FAIL_LS"
./dfhack-run lua -e '"'"'print("rpc-console-ok")'"'"' || echo "RUN_FAIL_LUA"

echo ""
echo "=== REMOTE LOG ==="
tail -n 10 /opt/dwarf-fortress/dfhack-remote.log || echo "NO_REMOTE_LOG"
echo "================================================================================"
'

log "Deployment complete!"
