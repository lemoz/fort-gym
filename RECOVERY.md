# DFHack Fork Storm Recovery Guide

## Problem Diagnosis

Your VM experienced a **fork storm** caused by `system("touch ...")` calls in `ensure_remote_server_started()` on a hot path inside DFHack core. This created thousands of `sh` child processes, exhausted memory, and wedged SSH.

## Root Causes Fixed

1. **No external shells in core**: Removed all `system()` calls from DFHack Core.cpp
2. **Call-once semantics**: Enforced `std::once_flag` to ensure single bind/log per process
3. **Console enabled**: Removed `DFHACK_DISABLE_CONSOLE=1` (required for RPC)
4. **Systemd hardening**:
   - `KillMode=control-group` → all children die on restart
   - `Restart=on-failure` with backoff → no stampedes
   - `MemoryMax=4G`, `TasksMax=512` → resource limits
   - `ExecStartPost` exits 0 → readiness cannot flap the unit

## Recovery Options

### Option 1: Direct Deployment (VM already accessible)

**Use this if you can manually restart the VM via GCP Console and SSH works:**

```bash
# 1. Restart VM via GCP Console
#    Compute Engine → VM Instances → dfhack-host → RESET

# 2. Wait ~30 seconds for boot

# 3. Run direct deployment script
./deploy_fix_direct.sh
```

This script will:
- Stop the service and kill residual processes
- Patch DFHack core to remove `system()` calls
- Rebuild DFHack with hardened changes
- Install fixed systemd unit with resource limits
- Verify RPC connectivity and print payload

**Expected runtime**: 10-15 minutes (rebuild takes ~5-10 min)

### Option 2: Full GCP Recovery (Automated VM restart)

**Use this for fully automated recovery with optional VM resize:**

```bash
# Set your GCP configuration
export DFHACK_GCP_PROJECT="your-gcp-project"
export DFHACK_GCP_ZONE="us-central1-a"
export DFHACK_GCP_INSTANCE="dfhack-host"
export DFHACK_USE_GCLOUD=true

# Optional: resize machine for rebuild headroom
export DFHACK_MACHINE_TYPE="e2-standard-4"

# Run full recovery
./recover_and_deploy.sh
```

This script will:
1. Stop the instance via `gcloud`
2. Add startup script to mask dfhack-headless and add 16GB swap
3. Optionally resize VM for rebuild headroom
4. Start the instance
5. Wait for SSH connectivity
6. Execute all fixes from Option 1
7. Generate final payload report

**Expected runtime**: 15-20 minutes (includes VM stop/start)

## Files Changed

### Local Infrastructure (Ready for Ansible)

1. **`infra/ansible/files/dfhack-headless.sh`**
   - ❌ Removed: `export DFHACK_DISABLE_CONSOLE=1`
   - ✅ Console now enabled for RPC

2. **`infra/ansible/files/dfhack-headless.service`**
   - ❌ Removed: `Environment=DFHACK_DISABLE_CONSOLE=1`
   - ✅ Added: `StartLimitIntervalSec=120`, `StartLimitBurst=3`
   - ✅ Added: `MemoryMax=4G`, `TasksMax=512`, `MemoryAccounting=yes`
   - ✅ Added: `KillMode=control-group`, `TimeoutStopSec=15`
   - ✅ Changed: `Restart=on-failure` with `RestartSec=10`
   - ✅ Added: `ExecStartPost=/opt/dwarf-fortress/bin/df-ready.sh`

3. **`infra/ansible/files/df-ready.sh`** (NEW)
   - Waits up to 60s for port 5000 listener
   - Optionally loads region1 save if present
   - Always exits 0 (non-blocking)

4. **`infra/ansible/roles/dfhack/tasks/main.yml`**
   - Added task to deploy df-ready.sh with mode 0755

### DFHack Core Patch (Applied by scripts)

The scripts automatically patch `/opt/dfhack*/library/Core.cpp` to:
- Remove all `system(...)` calls
- Add `std::once_flag g_remote_once` and `ensure_remote_server_started()` helper
- Call helper from `Core::init()` exactly once
- Log to `/opt/dwarf-fortress/dfhack-remote.log` and stderr
- Neutralize any other direct `ServerMain::listen()` calls

## Verification Payload

Both scripts will output a payload report:

```
================================================================================
=== LISTENER ===
tcp    LISTEN  0  5  127.0.0.1:5000  0.0.0.0:*  users:(("dwarfort",pid=1234,fd=3))

=== PID & MAPS ===
PID=1234
7f1234567000-7f1234789000 r-xp 00000000 fd:01 12345  /opt/dwarf-fortress/hack/libdfhack.so

=== EXEC ===
ls
help
die
...

rpc-console-ok

=== REMOTE LOG ===
[core-autoboot] listening on 5000
================================================================================
```

**Acceptance gates**:
- ✅ One `ss` line showing `127.0.0.1:5000` → `dwarfort`
- ✅ `/proc/$PID/maps` shows `/opt/dwarf-fortress/hack/libdfhack.so`
- ✅ `dfhack-run ls` prints command list
- ✅ `dfhack-run lua -e 'print("rpc-console-ok")'` prints `rpc-console-ok`
- ✅ `dfhack-remote.log` shows single `[core-autoboot] listening on 5000`

## Deploy to Production via Ansible

After verifying the fix works, deploy to other hosts:

```bash
# Deploy all changes
make vm-provision

# Or just restart the service
make vm-start
```

## Testing RPC Connectivity

**CRITICAL**: DFHack binds to `127.0.0.1:5000` (loopback only) for security.

### On the VM (Direct)

```bash
ssh -i ~/.ssh/google_compute_engine cdossman@34.41.155.134 'cd /opt/dwarf-fortress && ./dfhack-run help'
```

### From Your Laptop (SSH Tunnel Required)

**Step 1: Create SSH tunnel**
```bash
# Open tunnel in background
ssh -i ~/.ssh/google_compute_engine -N -L 5000:127.0.0.1:5000 cdossman@34.41.155.134 &

# Or keep it in foreground for easier control
ssh -i ~/.ssh/google_compute_engine -N -L 5000:127.0.0.1:5000 cdossman@34.41.155.134
```

**Step 2: Test via fort-gym Python client**
```python
from fort_gym.bench.env.dfhack_client import DFHackClient

# Connect to LOCAL port 5000 (tunneled to VM)
client = DFHackClient('127.0.0.1', 5000)
client.connect()
print('Connected:', client.is_connected())
client.disconnect()
```

**Never connect to `34.41.155.134:5000` directly** - DFHack is not exposed on public interface.

## Monitoring for Fork Storms

Watch for these symptoms:
- High memory usage and swap thrashing
- Thousands of `sh` child processes under `dwarfort`
- SSH timeouts or extreme slowness
- OOM killer messages in `dmesg`

Check process tree:
```bash
ssh -i ~/.ssh/google_compute_engine cdossman@34.41.155.134 'pstree -p $(pgrep dwarfort)'
```

Check for `system()` calls in binary:
```bash
strings /opt/dwarf-fortress/hack/libdfhack.so | grep -i "ensure.touch"
# Should return nothing after fix
```

## Rollback

If issues occur, mask the service:
```bash
ssh -i ~/.ssh/google_compute_engine cdossman@34.41.155.134 'sudo systemctl stop dfhack-headless && sudo systemctl mask dfhack-headless'
```

## Why This Fix Works

1. **No fork storm**: Zero `system()` calls in hot paths
2. **Single bind**: `std::once_flag` ensures one `listen()` per process
3. **Process isolation**: `KillMode=control-group` kills all descendants
4. **Controlled restart**: `Restart=on-failure` with backoff prevents stampedes
5. **Resource limits**: `MemoryMax` and `TasksMax` prevent runaway growth
6. **Swap buffer**: 16GB swap gives OOM killer breathing room
7. **Console enabled**: Required for DFHack RPC protocol
8. **Non-blocking readiness**: `ExecStartPost` exits 0, won't flap service

## Next Steps

1. Run recovery script: `./deploy_fix_direct.sh` or `./recover_and_deploy.sh`
2. Verify payload shows PASS
3. Test fort-gym connectivity
4. Monitor for 24-48 hours
5. Deploy via Ansible: `make vm-provision`

## Support

If recovery fails, capture diagnostics:

```bash
ssh -i ~/.ssh/google_compute_engine cdossman@34.41.155.134 '
sudo systemctl status dfhack-headless --no-pager
ss -lntp | grep 5000
pgrep -af dwarfort
tail -n 100 /opt/dwarf-fortress/dfhack-stderr.log
tail -n 100 /opt/dwarf-fortress/dfhack-remote.log
'
```
