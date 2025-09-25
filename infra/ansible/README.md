# fort-gym Ansible Automation

Provision an Ubuntu 22.04 host (or VM) with the headless DFHack runtime required by fort-gym.

## Inventory (`inventory.ini`)
Example:
```
[dfhack_host]
vm1 ansible_host=203.0.113.10 ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/id_rsa

[dfhack_host:vars]
ansible_python_interpreter=/usr/bin/python3
```
Adjust host/IP, SSH user, and key path for your environment.

## Group Variables (`group_vars/all.yml`)
Key variables:
```yaml
---
dfhack_install_dir: "/opt/dwarf-fortress"
dfhack_remote_port: 5000
service_user: "dfh"
service_group: "dfh"
```
Additional variables (packages, firewall, etc.) continue to live in this file; the defaults install required SDL/OpenAL dependencies and open TCP/5000.

## Playbooks
- `playbooks/dfhack.yml` — runs the `dfhack` role to build DFHack from the repo’s `dfhack-work/src` tree, install into `/opt/dwarf-fortress`, deploy the systemd unit, and verify RPC connectivity.
- `playbooks/site.yml` — broader provisioning (if you need the full fort-gym stack); still composes the `dfhack` role.

## dfhack role
- Installs build prerequisites (cmake, ninja, protobuf, SDL2, ncurses, etc.).
- Rsyncs the local `dfhack-work/src/` checkout onto the target host.
- Configures, builds, and installs DFHack with the RPC autoboot patch into `/opt/dwarf-fortress`.
- Writes `dfhack-config/remote-server.json` (default port 5000, loopback only).
- Installs and enables `dfhack-headless.service`, which starts `/opt/dwarf-fortress/dfhack` with `PRINT_MODE=TEXT`, `SDL_VIDEODRIVER=dummy`, and `DFHACK_HEADLESS=1`.
- Verifies two invariants after deployment:
  1. `ss -lntp` shows `127.0.0.1:5000` owned by `dwarfort`.
  2. `dfhack-run help` connects successfully.

## Services
- **dfhack-headless.service** — runs DFHack headless and exposes the RPC server on `127.0.0.1:${DFHACK_PORT}` (default 5000). Logs append to `/opt/dwarf-fortress/dfhack-stdout.log`, `/opt/dwarf-fortress/dfhack-stderr.log`, and `/opt/dwarf-fortress/dfhack-remote.log`.

Check logs with:
```
sudo journalctl -u dfhack-headless.service -f
```

## Common commands
```
ansible-playbook -i infra/ansible/inventory.ini infra/ansible/playbooks/dfhack.yml
ansible -i infra/ansible/inventory.ini dfhack_host -b -m shell -a "ss -lntp | grep ':5000'"
```

## Troubleshooting
- **Build failures** — ensure the host has at least 6 GB of free RAM and disk space; rerun the playbook to resume after transient apt failures.
- **Listener missing** — inspect `/opt/dwarf-fortress/dfhack-remote.log` and `journalctl -u dfhack-headless` for bind errors. Confirm nothing else occupies TCP/5000.
- **dfhack-run help fails** — verify `DFHACK_PORT` matches the port in `dfhack-config/remote-server.json` and that the service restarted after config changes.
