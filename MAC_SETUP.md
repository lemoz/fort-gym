# Mac Local Development Setup

This guide walks you through setting up fort-gym for local development on macOS using the [Lazy Mac Pack](https://dffd.bay12games.com/file.php?id=7622) DFHack distribution.

## Prerequisites

- macOS (tested on 10.14+)
- Lazy Mac Pack for Dwarf Fortress 0.47.05 with DFHack
- Python 3.11+ with venv support
- curl (for testing)

## Architecture

fort-gym now supports **cross-platform DFHack integration** via the `DFROOT` environment variable:

- **Mac**: Points to `~/Applications/Lazy Mac Pack/Dwarf Fortress`
- **Linux/VM**: Defaults to `/opt/dwarf-fortress`

All DFHack command paths are dynamically resolved at runtime via `fort_gym.bench.config.dfhack_cmd()`.

## Step 1: Configure Dwarf Fortress for Remote Access

### 1.1 Enable Text Mode (Required for Headless Operation)

Edit `~/Applications/Lazy Mac Pack/Dwarf Fortress/data/init/init.txt`:

```ini
[PRINT_MODE:TEXT]
[GRAPHICS:NO]
```

### 1.2 Enable DFHack Remote Plugin

Append to `~/Applications/Lazy Mac Pack/Dwarf Fortress/hack/init/dfhack.init`:

```
enable remotefortressreader
remote stop
remote start 127.0.0.1 5000
remote allow-remote yes
```

### 1.3 Launch DF and Load a Fortress

1. Open Lazy Mac Pack Dwarf Fortress
2. Load an existing fortress save (or generate a new world and embark)
3. Keep DF running in the background

### 1.4 Verify Remote Listener

```bash
lsof -iTCP:5000 -sTCP:LISTEN
```

Expected output:
```
COMMAND     PID      USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
dwarfort  12345  username   42u  IPv4 0x123456789abcdef0      0t0  TCP localhost:5000 (LISTEN)
```

## Step 2: Install fort-gym

### 2.1 Clone and Set Up Virtual Environment

```bash
cd ~/code  # or wherever you keep projects
git clone <your-fork> fort-gym
cd fort-gym

python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### 2.2 Configure Environment

Create `.env` from the example:

```bash
cp .env.example .env
```

Edit `.env` and set:

```bash
# Enable DFHack backend
DFHACK_ENABLED=1
DFHACK_HOST=127.0.0.1
DFHACK_PORT=5000

# Point to Lazy Mac Pack installation
DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"

# Optional: Set API keys if using LLM agents
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
```

**Note**: The `DFROOT` variable must point to the root of your DF installation (where `dfhack-run` lives).

### 2.3 Install Hook Scripts (Required for DFHack Actions)

The fort-gym uses Lua hook scripts for safe action execution. Copy them to your DF installation:

```bash
mkdir -p "$HOME/Applications/Lazy Mac Pack/Dwarf Fortress/hook"
cp -r hook/* "$HOME/Applications/Lazy Mac Pack/Dwarf Fortress/hook/"
```

Hook scripts include:
- `hook/order_make.lua` - Queue manager orders
- `hook/designate_rect.lua` - Designate dig/channel/chop rectangles

## Step 3: Start the API Server

```bash
cd ~/code/fort-gym
source .venv/bin/activate

# Export environment (if not using .env file)
export DFHACK_ENABLED=1
export DFHACK_HOST=127.0.0.1
export DFHACK_PORT=5000
export DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"

# Start the API
uvicorn fort_gym.bench.api.server:app --host 127.0.0.1 --port 8000
```

Expected output:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

## Step 4: Validate the Setup

### 4.1 Check API Docs

```bash
curl -s http://127.0.0.1:8000/docs | head -n 3
```

Expected: HTML response with FastAPI docs.

### 4.2 Create a Test Run

```bash
RUN_PAYLOAD='{
  "backend": "dfhack",
  "model": "random",
  "max_steps": 10,
  "ticks_per_step": 300
}'

curl -sS -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -d "$RUN_PAYLOAD" | tee /tmp/run.json

RUN_ID=$(jq -r '.id' /tmp/run.json)
echo "Run ID: $RUN_ID"
```

### 4.3 Stream Events (SSE)

```bash
curl -N "http://127.0.0.1:8000/runs/${RUN_ID}/events/stream" | head -n 20
```

You should see real-time event stream:
```
event: state
data: {"run_id":"abc123","step":0,"state":{...}}

event: action
data: {"run_id":"abc123","step":0,"raw":{"type":"dig",...}}

event: validation
data: {"run_id":"abc123","step":0,"valid":true}

...
```

### 4.4 Check Artifacts

```bash
ls -lh artifacts/${RUN_ID}/
cat artifacts/${RUN_ID}/summary.json | jq .
head -n 3 artifacts/${RUN_ID}/trace.jsonl
```

Expected:
- `trace.jsonl` - One JSON line per step
- `summary.json` - Aggregate metrics

## Step 5: Test Interactive `/step` Endpoint

The `/step` endpoint allows external controllers to drive the simulation step-by-step.

### 5.1 Create a DFHack Run

```bash
curl -sS -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -d '{"backend":"dfhack","model":"random","max_steps":100}' \
  | tee /tmp/step_run.json

STEP_RUN_ID=$(jq -r '.id' /tmp/step_run.json)
```

### 5.2 Send a NOOP Action

```bash
STEP_REQ="{
  \"run_id\": \"${STEP_RUN_ID}\",
  \"action\": {\"type\": \"noop\"},
  \"min_step_period_ms\": 1000,
  \"max_ticks\": 300
}"

curl -sS -X POST http://127.0.0.1:8000/step \
  -H 'Content-Type: application/json' \
  -d "$STEP_REQ" | jq .
```

Expected response:
```json
{
  "observation": {...},
  "reward": 0.0,
  "done": false,
  "info": {
    "step_idx": 0,
    "reward_cum": 0.0,
    "metrics": {...},
    "score": 0.0,
    "summary": {...}
  }
}
```

### 5.3 Test Rate Limiting (429 Throttle)

Send two requests in rapid succession:

```bash
# First request (should succeed)
curl -sD /tmp/step1.h -o /tmp/step1.out \
  -X POST http://127.0.0.1:8000/step \
  -H 'Content-Type: application/json' \
  -d "$STEP_REQ"

# Second request immediately after (should fail with 429)
curl -sD /tmp/step2.h -o /tmp/step2.out \
  -X POST http://127.0.0.1:8000/step \
  -H 'Content-Type: application/json' \
  -d "$STEP_REQ" || true

grep 'HTTP/1.1 429' /tmp/step2.h
```

Expected: Second request returns `429 Too Many Requests`.

## Step 6: Web UI (Optional)

Open the admin UI:

```bash
open web/admin.html
```

Or public replay UI:

```bash
open web/index.html
```

Both UIs connect to `http://127.0.0.1:8000` by default.

## Troubleshooting

### DFHack Not Listening on Port 5000

**Symptoms**: `curl` hangs or connection refused errors.

**Fix**:
1. Verify DF is running and a fortress is loaded
2. Check DFHack console shows: `[remote] Listening on 127.0.0.1:5000`
3. Confirm `dfhack.init` has the correct `remote start` command
4. Check for port conflicts: `lsof -iTCP:5000`

### "DFHack backend disabled" Error

**Symptoms**: API returns 400 with "DFHack backend is disabled."

**Fix**: Set `DFHACK_ENABLED=1` in `.env` or export it before starting the API.

### Hook Scripts Not Found

**Symptoms**: Actions fail with `FileNotFoundError` or "hook not found."

**Fix**: Ensure hooks are copied to `$DFROOT/hook/`:
```bash
ls -l "$HOME/Applications/Lazy Mac Pack/Dwarf Fortress/hook/"
```

Should show `order_make.lua`, `designate_rect.lua`, etc.

### DFROOT Path Issues

**Symptoms**: `dfhack-run` not found, or paths resolve incorrectly.

**Fix**: Verify `DFROOT` points to the correct directory:
```bash
export DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"
ls "$DFROOT/dfhack-run"
```

If the path has spaces, ensure it's quoted in `.env`:
```bash
DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"
```

### macOS "Unverified Developer" Warnings

**Symptoms**: macOS blocks `dfhack-run` from executing.

**Fix**: Go to System Preferences → Security & Privacy → Allow anyway.

## Development Workflow

### Quick Iteration Loop

1. **Edit code** in `fort_gym/bench/`
2. **Restart API** (Ctrl+C, then re-run `uvicorn` with `--reload`)
3. **Test via curl** or web UI
4. **Check artifacts** in `artifacts/<run_id>/`

### Running Tests

```bash
pytest -q
```

Mock backend tests run without DFHack. For DFHack integration tests:

```bash
export DFHACK_ENABLED=1
export DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"
pytest -k dfhack
```

### Using `make` Shortcuts

```bash
make api           # Start API server (with reload)
make test          # Run pytest
make mock-run      # Quick smoke test with mock backend
```

## Cross-Platform Compatibility

The same codebase works on both Mac and Linux:

| Platform       | DFROOT                                              | Notes                       |
|----------------|-----------------------------------------------------|-----------------------------|
| Mac (Lazy Mac) | `$HOME/Applications/Lazy Mac Pack/Dwarf Fortress`   | Manual DF launch required   |
| Linux VM       | `/opt/dwarf-fortress` (default)                     | Headless systemd service    |

No code changes needed—just set `DFROOT` appropriately.

## Next Steps

- **Add LLM agents**: Set API keys in `.env` and use `model: "gpt-4o-mini"` or `"claude-3-5-sonnet-latest"`
- **Experiment with actions**: See `fort_gym/bench/env/actions.py` for available action types
- **Build custom agents**: Implement `Agent.decide()` in `fort_gym/bench/agent/`
- **Deploy to VM**: Use Ansible playbooks in `infra/ansible/` for Linux deployment

## References

- [Lazy Mac Pack Download](https://dffd.bay12games.com/file.php?id=7622)
- [DFHack Remote Plugin Docs](https://docs.dfhack.org/en/stable/docs/Plugins.html#remote)
- [fort-gym Actions Safety Doc](docs/Actions_Headless_Safety.md)
- [fort-gym v0.3.0 Interactive Step](docs/FortGym_v0.3.0_Interactive_Step.md)
