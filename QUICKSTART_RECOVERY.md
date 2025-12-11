# DFHack Fork Storm - Quick Recovery

## TL;DR

Your VM is frozen due to fork storm from `system()` calls in DFHack core. Two recovery paths:

### Path A: Manual VM Restart (Fastest - 10 min)

```bash
# 1. Go to GCP Console → Compute Engine → dfhack-host → RESET

# 2. Wait 30 seconds, then run:
./deploy_fix_direct.sh
```

### Path B: Fully Automated (15-20 min)

```bash
export DFHACK_GCP_PROJECT="your-project"
export DFHACK_USE_GCLOUD=true
./recover_and_deploy.sh
```

## What Gets Fixed

✅ Removes all `system()` calls from DFHack core
✅ Enforces call-once semantics with `std::once_flag`
✅ Enables console (removes `DFHACK_DISABLE_CONSOLE=1`)
✅ Adds resource limits: `MemoryMax=4G`, `TasksMax=512`
✅ Installs hardened systemd unit with proper restart logic

## Success Looks Like

```
=== LISTENER ===
tcp  LISTEN  127.0.0.1:5000  ...  dwarfort

=== EXEC ===
ls
help
...

rpc-console-ok
```

## If It Fails

Check diagnostics:
```bash
ssh -i ~/.ssh/google_compute_engine cdossman@34.41.155.134 \
  'sudo systemctl status dfhack-headless; tail -n 50 /opt/dwarf-fortress/dfhack-stderr.log'
```

## Files Changed Locally (Ready for Ansible)

- `infra/ansible/files/dfhack-headless.sh` - console enabled
- `infra/ansible/files/dfhack-headless.service` - hardened unit
- `infra/ansible/files/df-ready.sh` - NEW readiness script
- `infra/ansible/roles/dfhack/tasks/main.yml` - deploy df-ready.sh

Deploy to other hosts later: `make vm-provision`

See `RECOVERY.md` for full details.
