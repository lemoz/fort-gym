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

### Provision with Ansible (optional)
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

### Headless DFHack runtime checklist
These are the manual steps we currently run on `dfhack-host` before kicking off live jobs:

1. **Upload and unpack the fortress save.**
   ```bash
   gcloud compute scp ~/Desktop/mvp_test1.zip dfhack-host:/tmp/
   gcloud compute ssh dfhack-host --command '
     set -e
     cd /opt/dwarf-fortress
     mkdir -p data/save
     unzip -o /tmp/mvp_test1.zip -d data/save/
     test -f data/save/mvp_test1/world.sav
   '
   ```

2. **Regenerate DFHack protobuf bindings.** The public DFHack repo for 0.47.05 no longer ships the remote fort proto sources, so we copy them from the checked-out `dfhack-src` tree that ships with the VM image:
   ```bash
   gcloud compute ssh dfhack-host --command '
     set -e
     SRC=/opt/fort-gym/fort_gym/bench/env/remote_proto
     rm -rf "${SRC}/generated"
     mkdir -p "${SRC}/generated"
     source /opt/fort-gym/.venv/bin/activate
     cd ${SRC}/sources/library/proto
     python -m grpc_tools.protoc --proto_path=. --python_out=../../../generated CoreProtocol.proto Basic.proto BasicApi.proto
     cd ${SRC}/sources/plugins/remotefortressreader/proto
     python -m grpc_tools.protoc --proto_path=. --proto_path=../../../library/proto --python_out=../../../../generated RemoteFortressReader.proto ItemdefInstrument.proto DwarfControl.proto AdventureControl.proto ui_sidebar_mode.proto
     : > ${SRC}/generated/__init__.py
   '
   ```

3. **Configure DFHack to auto-load the save and expose the remote plugin on loopback.**
   ```bash
   gcloud compute ssh dfhack-host --command "
     sudo tee /opt/dwarf-fortress/dfhack-config/init/dfhack.init >/dev/null <<'EOF'
enable remotefortressreader
remote stop 2> /dev/null
remote start 127.0.0.1 5000
remote allow-remote yes
load-save mvp_test1
EOF
   "
   ```

4. **Install the systemd service.**
   ```bash
   gcloud compute ssh dfhack-host --command "
     sudo tee /etc/systemd/system/dfhack.service >/dev/null <<'EOF'
[Unit]
Description=Dwarf Fortress 0.47.05 + DFHack headless (loopback only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/dwarf-fortress
Environment=DFHACK_DISABLE_CONSOLE=1
Environment=SDL_VIDEODRIVER=dummy
Environment=TERM=xterm-256color
ExecStart=/opt/dwarf-fortress/bin/dfhack-headless.sh +load-save mvp_test1
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=true
ProtectKernelTunables=yes
ProtectControlGroups=yes
ProtectClock=yes
MemoryMax=1G
TasksMax=512
KillMode=control-group

[Install]
WantedBy=multi-user.target
EOF
     sudo systemctl daemon-reload
     sudo systemctl enable dfhack.service
     sudo systemctl restart dfhack.service
   "
   ```
   Verify it came up cleanly:
   ```bash
   gcloud compute ssh dfhack-host --command '
     sudo systemctl status dfhack.service --no-pager
     sudo ss -lntp | grep 5000
     /opt/dwarf-fortress/dfhack-run lua "print(dfhack.getSavePath())"
   '
   ```

5. **Run the fort-gym API in tmux.**
   ```bash
   gcloud compute ssh dfhack-host --command '
     cd /opt/fort-gym
     source .venv/bin/activate
     export DFHACK_ENABLED=1 DFHACK_HOST=127.0.0.1 DFHACK_PORT=5000
     tmux new-session -d -s fortgym "uvicorn fort_gym.bench.api.server:app --host 0.0.0.0 --port 8000 > /tmp/fort-gym-api.log 2>&1"
     tmux list-sessions | grep fortgym
     ss -lntp | grep 8000
     curl -s http://127.0.0.1:8000/docs | head -n 5
   '
   ```
   To inspect later: `tmux attach -t fortgym` (detach via `Ctrl-b d`).

## Running DFHack Jobs from the API
With the service running:
```bash
curl -s -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -d '{"backend":"dfhack","model":"fake","max_steps":50,"ticks_per_step":500}'
```
Then:
```bash
curl -s http://127.0.0.1:8000/runs/<run_id>
curl -N "http://127.0.0.1:8000/runs/<run_id>/events/stream" | head -n 15
ls -l fort_gym/artifacts/<run_id>/
head -n 3 fort_gym/artifacts/<run_id>/trace.jsonl
cat fort_gym/artifacts/<run_id>/summary.json | jq .
```
The SSE endpoint emits `state`, `action`, `validation`, `execute`, `advance`, `metrics`, and `score` events. `summary.json` accumulates aggregate metrics (currently a simple placeholder for DFHack runs).

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
- **SSE shows no events**: confirm the tmux `fortgym` session is live; inspect `/tmp/fort-gym-api.log` for stack traces.
- **Jobs stall**: query `/runs/<id>` to check progress, tail `/tmp/fort-gym-api.log`, and ensure DFHack remote is responsive (`/opt/dwarf-fortress/dfhack-run lua 'print(dfhack.getSavePath())'`).
- **Missing DFHack protobuf bindings**: the `make proto` helper expects protos in `fort_gym/bench/env/remote_proto/sources`. If upstream URLs move, copy the `.proto` files out of `/opt/dfhack-src` and regenerate with the commands listed above.
- **LLM invalid actions**: adjust prompts or ACTION_TOOL_SPEC usage; ensure the tool call returns a single action dict.
