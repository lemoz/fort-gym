# DFHack Headless RPC (Autoboot)

The DFHack core now owns startup of the TCP RPC server so that it is available for headless jobs without depending on console autoload hooks or manual key presses.

## Runtime Behaviour
- `ensure_remote_server_started()` is invoked from the core constructor, `InitMainThread()`, and `InitSimulationThread()` and runs once via `std::call_once`.
- The server binds `127.0.0.1:${DFHACK_PORT:-5000}` and respects the `DFHACK_PORT` environment variable.
- Messages and exceptions are appended to `/opt/dwarf-fortress/dfhack-remote.log` with the `[core-autoboot] …` prefix.
- Optional config lives in `dfhack-config/remote-server.json` (`{"port": ..., "allow_remote": ...}`).

Recommended environment for headless services:
- `DFHACK_HEADLESS=1`
- `DFHACK_DISABLE_CONSOLE=1`
- `PRINT_MODE=TEXT`
- `TERM=xterm-256color`

## Launch Flow
- `/opt/dwarf-fortress/bin/dfhack-headless.sh` sets up `LD_PRELOAD=hack/libdfhack.so`, exports the headless environment, and execs `./dwarfort`.
- `/opt/dwarf-fortress/bin/dfhack-headless-pty.exp` (Expect) spawns the launcher under a PTY and sends a dozen `ENTER` keystrokes to clear the TEXT-mode "Press any key…" prompt, then `interact`s so the process stays attached for systemd.
- `/etc/systemd/system/dfhack-headless.service` executes the expect wrapper, clears `LD_PRELOAD` in the unit, and logs stdout/stderr to `/opt/dwarf-fortress/dfhack-{stdout,stderr}.log`.

## Verification Checklist
```bash
ss -lntp | grep '127.0.0.1:5000'
cd /opt/dwarf-fortress && ./dfhack-run help | head -n 10
tail -n 50 /opt/dwarf-fortress/dfhack-remote.log
```

The Ansible role `infra/ansible/roles/dfhack` applies the core patch, enforces the TEXT+curses init settings, installs the launcher scripts + unit, removes the legacy `autoboot_remote` autoload, and runs the listener/`dfhack-run` verifications as part of the deployment.
