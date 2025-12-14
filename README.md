# fort-gym

## Overview
fort-gym is a Dwarf Fortress agent benchmark with two backends: a deterministic mock environment for local development and a DFHack-powered backend for live fortress runs on Linux. Agents issue exactly one action per step, the harness records every observation/state/action to JSONL, streams live updates over SSE, and exposes admin/public web UIs plus 10-run job orchestration with summaries and leaderboards.

## Local (Mock) Quickstart
```bash
pip install -e .[dev]
export FORT_GYM_INSECURE_ADMIN=1   # dev-only; in prod set FORT_GYM_ADMIN_PASSWORD
fort-gym api                       # API on :8000
# open http://127.0.0.1:8000/admin and start a mock run (model=fake|random)
```
Artifacts (trace JSONL + summary) land under `fort_gym/artifacts/<run_id>/`. You can replay them via the public UI (`/`) or inspect the leaderboard (`/leaderboard`).

## Mac Local Development with DFHack

For local development on macOS using the **Lazy Mac Pack** with DFHack, see **[MAC_SETUP.md](MAC_SETUP.md)** for complete instructions including:
- Configuring DF for remote access (TEXT mode, remote plugin)
- Setting `DFROOT` environment variable
- Installing hook scripts
- Running the API against local DF on port 5000

The same fort-gym codebase works on both Mac and Linux—only the `DFROOT` path differs.

## Deploy on a Google Cloud VM (DFHack)
### Prerequisites
- Google Cloud SDK (`gcloud`) configured with project/zone.
- VM firewall needs TCP 80/443 for HTTPS.
- DFHack RPC should stay loopback-only; use SSH tunnels if you need access from your laptop.

### Create the VM + firewall rules
```bash
gcloud compute firewall-rules create allow-fortgym-http-https --allow tcp:80,tcp:443 --direction=INGRESS --target-tags=fortgym
gcloud compute instances create dfhack-host   --machine-type=e2-standard-2   --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud   --boot-disk-size=50GB   --tags=dfhack,fortgym
```

### Provision with Ansible (recommended)
1. Edit `infra/ansible/inventory.ini` with your VM IP/user/key.
2. Update `infra/ansible/group_vars/all.yml`:
   - `dfhack_archive_url` (Linux DF+DFHack bundle) and optional checksum.
   - `service_user`/`service_group` (default `ubuntu`).
   - `fortgym_repo_url` (defaults to this repo) & `fortgym_checkout_ref`.
3. Export `FORT_GYM_ADMIN_PASSWORD` before running Ansible (admin endpoints are disabled without it).
4. Run:
   ```bash
   make vm-provision
   make vm-start
   make vm-status
   ```

See `CLAUDE.md` for the current VM workflow (seed saves, systemd services, HTTPS reverse proxy).

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
> Note: the interactive `/step` flow is validated against the single-action schema used by the `fake` agent. Manager orders issued by the exploratory `random` agent remain experimental and may be rejected until DFHack execution coverage improves.
The SSE endpoint emits `state`, `action`, `validation`, `execute`, `advance`, `metrics`, and `score` events. `summary.json` accumulates aggregate metrics (currently a simple placeholder for DFHack runs).

## Keystroke Control Mode (Claude Plays Like a Human)

The `anthropic-keystroke` model enables Claude to control Dwarf Fortress via raw keystrokes, seeing the game screen and sending key commands just like a human player would.

### How It Works
1. **Screen Observation**: The game screen is captured via DFHack's CopyScreen RPC and converted to an 80x25 text representation
2. **Claude Decides**: Claude sees the screen text and decides what keystrokes to send
3. **Keystroke Execution**: Keys are sent via DFHack's `devel/send-key` command
4. **Game Responds**: The game processes the input and advances

### Running Keystroke Mode
```bash
curl -s -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -d '{"backend":"dfhack","model":"anthropic-keystroke","max_steps":10,"ticks_per_step":200}'
```

### Available Keys
Common interface keys include:
- **Navigation**: `CURSOR_UP`, `CURSOR_DOWN`, `CURSOR_LEFT`, `CURSOR_RIGHT`, `CURSOR_UP_Z`, `CURSOR_DOWN_Z`
- **Selection**: `SELECT`, `DESELECT`, `LEAVESCREEN`
- **Main Menus**: `D_DESIGNATE`, `D_BUILDJOB`, `D_STOCKPILES`, `D_ZONES`, `D_ORDERS`
- **Designate**: `DESIGNATE_DIG`, `DESIGNATE_CHANNEL`, `DESIGNATE_STAIR_DOWN`, `DESIGNATE_CHOP`

Full list of 1600+ keys available via: `dfhack-run lua "@df.interface_key"`

### Example Output
```json
{
  "type": "KEYSTROKE",
  "params": {"keys": ["D_DESIGNATE", "DESIGNATE_DIG", "CURSOR_DOWN", "SELECT"]},
  "intent": "Designating a dig area below current position"
}
```

Generate a leaderboard snapshot for the static site:

```bash
python scripts/publish_leaderboard.py
cat web/leaderboard.json | head
```

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
| `allow_tcp_ports` | List of TCP ports opened via UFW (e.g. [22, 80, 443]). |

## Web UI

The web interface at `https://<host>/` (or local dev at `http://127.0.0.1:8000/`) provides:

- **Live Game View**: Real-time rendering of the DF screen using the public run token screenshot endpoint (`/public/runs/{token}/screenshot`). Click "Start Live View" to begin streaming. Uses [pcface](https://github.com/susam/pcface) for pixel-perfect CP437 bitmap font rendering.
- **Leaderboard**: Best score over time per backend/model/version (`/leaderboard`).
- **Live/Replay Streams**: SSE event streams for watching runs in real-time or replaying traces.
- **Admin Panel** (`/admin`): Create runs, manage jobs, generate share tokens (basic auth required; disabled if `FORT_GYM_ADMIN_PASSWORD` is empty).

The Live Game View captures the screen via RemoteFortressReader's `CopyScreen` RPC (tiles are returned in column-major order) and renders them on an HTML canvas with proper DF color palette.

## Security Notes
- Set a non-empty `FORT_GYM_ADMIN_PASSWORD` before exposing the service.
- Keep DFHack RPC on loopback only; do not expose port 5000 directly.
- Serve the API behind HTTPS (Caddy/Nginx) and restrict inbound traffic (GCE firewall/UFW).
- Rotate API keys regularly; never commit `.env` with secrets.

## Roadmap

### Agent Memory & Experimentation System (Planned)

Currently each agent step is stateless. Planned improvements:

1. **Hybrid Memory**: Last N steps as full conversation + summary of older history
2. **Agent Tools**: Web search and DF Wiki lookup during decision-making
3. **Experimentation Framework**: YAML-based configs to test different memory strategies, prompts, and tools

See `CLAUDE.md` for detailed design.

## Troubleshooting
- **DFHack service won't start**: check `/var/log/syslog` and `journalctl -u dfhack-headless`. Verify `dfhack_archive_url` points to a Linux build.
- **Remote not listening**: ensure the remote plugin is enabled; run `ss -lntp | grep 5000`.
- **SSE shows no events**: inspect API logs (`journalctl -u fort-gym-api -f` on the VM) and confirm the share token has `live` scope.
- **Jobs stall**: query `/runs/<id>` to check progress, tail `journalctl -u fort-gym-api -f`, and ensure DFHack is responsive (`/opt/dwarf-fortress/dfhack-run lua 'print(dfhack.getSavePath())'`).
- **Missing DFHack protobuf bindings**: the `make proto` helper expects protos in `fort_gym/bench/env/remote_proto/sources`. If upstream URLs move, copy the `.proto` files out of `/opt/dfhack-src` and regenerate with the commands listed above.
- **LLM invalid actions**: adjust prompts or ACTION_TOOL_SPEC usage; ensure the tool call returns a single action dict.
