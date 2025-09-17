# fort-gym Ansible Automation

This directory provisions a single Ubuntu 22.04 VM with a headless DFHack instance and optional fort-gym API.

## Inventory (`inventory.ini`)
```
[gce]
vm1 ansible_host=203.0.113.10 ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/id_rsa

[gce:vars]
ansible_python_interpreter=/usr/bin/python3
```
Modify the host/IP, user, and key path to match your VM.

## Group Variables (`group_vars/all.yml`)
Example (fill in DFHack archive URL and credentials as needed):
```yaml
---
fortgym_repo_url: "https://github.com/lemoz/fort-gym.git"
fortgym_checkout_ref: "main"
fortgym_install_dir: "/opt/fort-gym"
fortgym_venv_dir: "{{ fortgym_install_dir }}/.venv"
fortgym_env_path: "/etc/fort-gym.env"
fortgym_service_enabled: false            # enable API service when ready
fortgym_service_port: 8000

dfhack_archive_url: "https://example.com/dfhack-linux.tar.xz"
dfhack_archive_checksum: ""
dfhack_install_dir: "/opt/dwarf-fortress"
dfhack_env_path: "/etc/dfhack.env"
dfhack_remote_port: 5000
dfhack_display: ":99"
service_user: "ubuntu"
service_group: "ubuntu"
allow_tcp_ports: [22, 5000, 8000]
base_packages:
  - xvfb
  - xauth
  - x11-xserver-utils
  - fonts-dejavu-core
  - libglu1-mesa
  - libxrender1
  - libxi6
  - libxrandr2
  - libxcursor1
  - unzip
  - curl
  - ca-certificates
  - jq
  - git
  - python3
  - python3-venv
  - python3-pip
  - ufw
```

## Playbook (`playbooks/site.yml`)
Applies three roles:
- `base`: installs system packages, configures UFW, ensures the service account exists.
- `dfhack`: downloads/extracts DF + DFHack, installs `dfhack-headless.service` (Xvfb + dfhack remote @ 0.0.0.0:5000).
- `fortgym`: clones fort-gym, creates virtualenv, installs dependencies, renders `fort-gym-api.service` (disabled unless `fortgym_service_enabled: true`).

## Services
- **dfhack-headless.service** — runs Xvfb on DISPLAY :99 and starts `dfhack` with the remote plugin configured on `0.0.0.0:5000`.
- **fort-gym-api.service** — optional uvicorn server on `0.0.0.0:8000` serving the FastAPI API (disabled by default).

Check logs with:
```
sudo journalctl -u dfhack-headless.service -f
sudo journalctl -u fort-gym-api.service -f
```

## Make Targets
```
make vm-provision   # ansible-playbook -i inventory infra/ansible/playbooks/site.yml
make vm-start       # start dfhack-headless (+ fort-gym-api if enabled)
make vm-status      # show systemd status for both services
```

## Troubleshooting (Ansible)
- **SSH auth failed**: verify `ansible_ssh_private_key_file` and user in `inventory.ini`.
- **Unarchive failed**: confirm `dfhack_archive_url` points to a Linux tarball and is reachable.
- **Ports blocked**: check GCE firewall rules and `ufw status` on the VM.
- **Updating DFHack**: adjust `dfhack_archive_url`, rerun `make vm-provision` to deploy the new archive.

