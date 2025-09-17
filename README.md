# fort-gym

## Overview
fort-gym is a Dwarf Fortress agent benchmark with two backends: a deterministic mock environment for local development and a DFHack-powered backend for live fortress runs on Linux. Agents issue exactly one action per step, the harness records every observation/state/action to JSONL, streams live updates over SSE, and exposes admin/public web UIs plus 10-run job orchestration with summaries and leaderboards.

## Local (Mock) Quickstart
```bash
pip install -e .[dev]
fort-gym api              # API on :8000
# open web/admin.html and start a mock run (model=fake|random)
```
Artifacts (trace JSONL + summary) land under `fort_gym/artifacts/<run_id>/`. You can replay them via the public UI (`web/index.html`) or inspect the leaderboard which reads summaries.

## Deploy on a Google Cloud VM (DFHack)
### Prerequisites
- Google Cloud SDK (`gcloud`) configured with project/zone.
- VM firewall needs TCP 5000 (DFHack) and 8000 (fort-gym API).

### Create the VM + firewall rules
```bash
gcloud compute firewall-rules create allow-dfhack --allow tcp:5000 --direction=INGRESS --target-tags=dfhack
gcloud compute firewall-rules create allow-fortgym --allow tcp:8000 --direction=INGRESS --target-tags=fortgym
gcloud compute instances create dfhack-host   --machine-type=e2-standard-2   --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud   --boot-disk-size=50GB   --tags=dfhack,fortgym
```

### Provision with Ansible
1. Edit `infra/ansible/inventory.ini` with your VM IP/user/key.
2. Update `infra/ansible/group_vars/all.yml`:
   - `dfhack_archive_url` (Linux DF+DFHack bundle) and optional checksum.
   - `service_user`/`service_group` (default `ubuntu`).
   - `fortgym_repo_url` (defaults to this repo) & `fortgym_checkout_ref`.
3. Run:
```bash
make vm-provision
make vm-start
make vm-status
```

### What it does
- Installs Xvfb and dependencies, downloads DF/DFHack to `/opt/dfhack`, and runs `dfhack-headless` with the remote plugin listening on `0.0.0.0:5000`.
- Clones fort-gym into `/opt/fort-gym`, sets up a virtualenv, installs the package.
- Deploys an optional `fort-gym-api` service on `0.0.0.0:8000` (disabled unless `fortgym_service_enabled: true`).

## Running DFHack Jobs from the API
If the API service is enabled:
```bash
curl -s -X POST http://<VM_IP>:8000/jobs   -H 'Content-Type: application/json'   -d '{"model":"fake","backend":"mock","n":10,"parallelism":2,"max_steps":100,"ticks_per_step":50}'
```
Otherwise SSH into the VM, run `fort-gym api` manually, and use the admin UI in a browser.

## Environment & Keys
Copy the example env and fill it in:
```bash
cp .env.example .env
```
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` required for those agents.
- DFHack backend runs on Linux; macOS typically uses the mock backend or targets the Linux VM.

## Variables Reference (Ansible)
| Variable | Description |
|----------|-------------|
| `dfhack_install_dir` | Path where DF/DFHack is installed (`/opt/dfhack`). |
| `dfhack_archive_url` | URL of Linux DFHack bundle to download. |
| `dfhack_remote_port` | Remote plugin TCP port (default 5000). |
| `service_user` / `service_group` | Unix account running services. |
| `fortgym_repo_url` | Git repository URL (default GitHub). |
| `fortgym_checkout_ref` | Branch/tag for fort-gym checkout. |
| `fortgym_install_dir` | Install path (`/opt/fort-gym`). |
| `fortgym_venv_dir` | Virtualenv directory (`/opt/fort-gym/.venv`). |
| `fortgym_service_enabled` | Enable fort-gym API systemd service (false by default). |
| `fortgym_service_port` | API bind port (default 8000). |
| `allow_tcp_ports` | List of TCP ports opened via UFW (e.g. [22, 5000, 8000]). |

## Security Notes
- Restrict inbound traffic to trusted IPs using GCE firewall rules or UFW.
- Consider a reverse proxy with auth in front of the fort-gym API.
- Rotate API keys regularly; never commit `.env` with secrets.

## Troubleshooting
- **DFHack service won’t start**: check `/var/log/syslog` and `journalctl -u dfhack-headless`. Verify `dfhack_archive_url` points to a Linux build.
- **Remote not listening**: ensure the remote plugin is enabled; run `ss -lntp | grep 5000`.
- **SSE shows no events**: confirm `fort-gym api` is running; inspect browser devtools for SSE/CORS issues.
- **Jobs stall**: query `/jobs` to inspect JobRegistry state; review server logs.
- **LLM invalid actions**: adjust prompts or ACTION_TOOL_SPEC usage; ensure the tool call returns a single action dict.
