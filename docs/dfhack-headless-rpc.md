# DFHack Headless RPC (Autoboot)

The DFHack core now starts the TCP RPC server during `Core::init()` so it is available in headless and TTY-less launches without relying on `dfhack.init`, `+` commands, or console startup hooks.

## Runtime behaviour
- Listens on `127.0.0.1:${DFHACK_PORT:-5000}`
- Reads `DFHACK_PORT` to override the port; otherwise defaults to 5000
- Optional config: `dfhack-config/remote-server.json` (port, `allow_remote`)
- Recommended environment for headless service:
  - `DFHACK_HEADLESS=1`
  - `PRINT_MODE=TEXT`
  - `SDL_VIDEODRIVER=dummy`

## Verification
```bash
ss -lntp | grep ':5000'
./dfhack-run help
tail -n 50 /opt/dwarf-fortress/dfhack-remote.log
```

## Service unit
Systemd unit `dfhack-headless.service` launches `/opt/dwarf-fortress/dfhack` with the environment above and captures stdout/stderr logs alongside `/opt/dwarf-fortress/dfhack-remote.log`.
