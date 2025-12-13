# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fort-gym is a Dwarf Fortress agent benchmark with two backends:
- **Mock backend**: Deterministic environment for local development and testing
- **DFHack backend**: Live fortress runs on Linux using DFHack's remote plugin (port 5000)

Agents issue exactly one action per step. The harness records every observation/state/action to JSONL, streams live updates over SSE, and exposes admin/public web UIs plus 10-run job orchestration with summaries and leaderboards.

## Common Commands

### Development
```bash
# Install with development dependencies
pip install -e .[dev]
# or
make install

# Run the API server (port 8000)
fort-gym api
# or
make api

# Run tests
pytest -q
# or
make test

# Run a specific test
pytest -k test_name

# Quick smoke test with mock backend
make mock-run
```

### Mac Local Development
For local development on macOS with Lazy Mac Pack, see [MAC_SETUP.md](MAC_SETUP.md) for complete setup instructions.

Quick setup:
```bash
# Set DFROOT to your Lazy Mac Pack installation
export DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"
export DFHACK_ENABLED=1

# Ensure hook scripts are copied
mkdir -p "$DFROOT/hook"
cp -r hook/* "$DFROOT/hook/"

# Start API
uvicorn fort_gym.bench.api.server:app --host 127.0.0.1 --port 8000
```

### Protocol Buffers
```bash
# Regenerate DFHack protocol bindings
make proto

# Clean generated protocol files
make clean-proto
```

### DFHack VM Management (Google Cloud)
```bash
# Provision VM with Ansible
make vm-provision

# Start DFHack and fort-gym services
make vm-start

# Check service status
make vm-status

# Run pytest in the VM test checkout
make vm-test

# Deploy current origin/main to the production checkout
make vm-deploy
```

### Local DFHack Testing
```bash
# Launch DFHack headless sandbox (Linux only)
make df-headless
```

## Architecture

### Core Package Structure
- `fort_gym/bench/agent/` - Agent implementations (base.py defines the Agent ABC)
- `fort_gym/bench/env/` - Environment adapters: mock_env.py (deterministic), dfhack_client.py (gRPC), executor.py (action dispatcher)
- `fort_gym/bench/run/` - Orchestration: runner.py (main run loop), jobs.py (batch orchestration), storage.py (in-memory registry)
- `fort_gym/bench/api/` - FastAPI server and SSE streaming
- `fort_gym/bench/eval/` - Metrics, scoring, milestones, and summary generation
- `fort_gym/bench/cli.py` - `fort-gym` CLI entrypoint (Typer)

### Key Data Flow

1. **Run execution** (`runner.run_once`):
   - Pause environment → Observe state → Agent decides action → Validate → Execute → Advance time → Compute metrics/score → Write JSONL line
   - Repeats for `max_steps`
   - Writes `trace.jsonl` and `summary.json` to `fort_gym/artifacts/<run_id>/`

2. **Action validation** (`env/actions.py`):
   - All actions are single dicts with `{"type": str, "params": dict, "intent": str}`
   - Agents returning lists or dicts with "actions"/"plan" keys are rejected
   - Types: DIG, BUILD, ORDER, WAIT, INSPECT
   - Each action is validated against current state before execution

3. **Backend dispatch** (`env/executor.py`):
   - Mock: validates then calls `MockEnvironment.apply()`
   - DFHack: validates then calls `DFHackClient` methods (designate_rect, queue_manager_order, place_building)

4. **Job orchestration** (`run/jobs.py`):
   - `JobRegistry.start()` manages N runs with parallelism cap
   - Spawns worker threads that call `runner.run_once()` with RUN_REGISTRY bound

5. **API endpoints** (`api/server.py`):
   - Admin: POST /runs, POST /jobs, GET /runs, GET /jobs/{id}
   - Public: GET /public/runs/{token}, GET /public/trace/{token}
   - SSE: GET /runs/{id}/events, GET /public/runs/{token}/events

### Agents

Agents must implement `Agent.decide(obs_text: str, obs_json: dict) -> dict` returning exactly one action dictionary. Available agents:
- `RandomAgent` (always available)
- `FakeAgent` (deterministic responses, requires `fort_gym.bench.agent.fake_llm`)
- OpenAI agents (requires `OPENAI_API_KEY`)
- Anthropic agents (requires `ANTHROPIC_API_KEY`):
  - `anthropic` - Toolbox mode with predefined actions (DIG, BUILD, ORDER)
  - `anthropic-keystroke` - Pure keystroke control, Claude sees screen and sends key commands

Register new agents via `AGENT_FACTORIES` in `agent/base.py`.

### Keystroke Mode

The `anthropic-keystroke` agent enables Claude to control DF via raw keystrokes:
- Screen captured via CopyScreen RPC, converted to 80x25 text
- Claude decides what keys to press based on screen content
- Keys sent via `devel/send-key` command
- Key module: `fort_gym/bench/env/keystroke_exec.py`
- **Action history**: Last 5 actions shown in observation for context/memory
- **Pause on end**: Game is paused when run completes to prevent state drift

The system prompt encourages Claude to take action (dig, build, create stockpiles) rather than just exploring menus. Key behaviors:
- Recognizes main menu is NOT an overlay to dismiss
- Uses STRING_A### keys for typing letters (e.g., STRING_A097 = 'a')
- Tries alternative keys (STANDARDSCROLL_PAGEDOWN, Space) when SELECT doesn't close popups
- On embark site selection (`viewscreen_choose_start_sitest`), the `e` hotkey maps to interface key `SETUP_EMBARK`. fort-gym auto-translates `STRING_A101`/`CUSTOM_E` to `SETUP_EMBARK` so keystroke/admin control can embark reliably.

## Environment Variables

Copy `.env.example` to `.env` and configure:
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` - Required for LLM agents
- `DFHACK_ENABLED` - Set to 1 to enable DFHack backend
- `DF_PROTO_ENABLED` - Set to 1 to enable DFHack protobuf bindings (required for DFHack backend)
- `DFHACK_HOST` / `DFHACK_PORT` - DFHack remote plugin endpoint (default 127.0.0.1:5000)
- `DFROOT` - Path to DF installation (auto-detected: `/opt/dwarf-fortress` on Linux, override for Mac)
  - Mac (Lazy Mac Pack): `export DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"`
  - Linux/VM: `/opt/dwarf-fortress` (default)
- `FORT_GYM_SEED_SAVE` - Optional pristine seed save name. When set and backend is `dfhack`, fort-gym copies this save to `FORT_GYM_RUNTIME_SAVE` and restarts `dfhack-headless` (then `load-save`s that runtime) before each run.
- `FORT_GYM_RUNTIME_SAVE` - Runtime save directory name to load after seed reset (default `current`).
- `TICKS_PER_STEP` - Game ticks to advance per step (default 200)
- `ARTIFACTS_DIR` - Where to store run artifacts (default fort_gym/artifacts)

See `fort_gym/bench/config.py` for full list.

## GCE VM Deployment (dfhack-host)

### Current VM
- **IP**: 34.41.155.134
- **Web UI**: http://34.41.155.134:8000/ (spectator), http://34.41.155.134:8000/admin (admin)
- **DFHack RPC**: port 5000 (loopback)
- **DFHack version**: v0.47.05
- **Save loaded**: `region1` (reset from seed before runs)

### Seed Save Workflow (VM)
We keep a read-only pristine seed save and reset the runtime save from it before every DFHack run.

- **Seed save**: `/opt/dwarf-fortress/data/seed_saves/seed_region1_fresh` (read-only)
- **Runtime save**: `/opt/dwarf-fortress/data/save/region1`
- **Automation**: set in `/etc/fort-gym.env`:
  - `FORT_GYM_SEED_SAVE=seed_region1_fresh`
  - `FORT_GYM_RUNTIME_SAVE=region1`

fort-gym will:
1. Copy the seed → runtime save
2. Restart `dfhack-headless`
3. `load-save` the runtime save and wait for the map to load
4. Start the run

If you need a new seed:
1. Boot DF to title, create/embark a fresh fortress, save immediately, and exit.
2. Copy to a new read-only seed folder:
   `sudo cp -a /opt/dwarf-fortress/data/save/<new_world> /opt/dwarf-fortress/data/seed_saves/seed_<name> && sudo chmod -R a-w /opt/dwarf-fortress/data/seed_saves/seed_<name>`
3. Update `FORT_GYM_SEED_SAVE` to the new seed name.

**Important**: keep `/opt/dwarf-fortress/bin/df-ready.sh` disabled (no-op). Earlier autoload logic there caused DF segfaults during startup/worldgen.

### Full System Startup (from scratch)

Both services are managed via systemd and auto-start on boot.

1. **Start services** (if not running):
```bash
ssh cdossman@34.41.155.134 'sudo systemctl start dfhack-headless fort-gym-api'
```

2. **Check status**:
```bash
ssh cdossman@34.41.155.134 'systemctl status dfhack-headless fort-gym-api'
```

3. **Test the system**:
```bash
# Check API responds
curl -s http://34.41.155.134:8000/health

# Start a test run (auto-creates share token for spectator view)
curl -s -u admin:'<password>' -X POST http://34.41.155.134:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"backend": "dfhack", "model": "anthropic-keystroke", "max_steps": 5}'
```

### Systemd Services

**fort-gym-api.service** (`/etc/systemd/system/fort-gym-api.service`):
- Runs as `cdossman` user
- Loads env from `/etc/fort-gym.env` (contains ANTHROPIC_API_KEY)
- Auto-restarts on failure

**dfhack-headless.service** (`/etc/systemd/system/dfhack-headless.service`):
- Runs as `ubuntu` user
- Starts DF + DFHack headless; fort-gym uses `load-save $FORT_GYM_RUNTIME_SAVE` during seed reset (currently `region1`)
- Logs to `/opt/dwarf-fortress/dfhack-stdout.log`

```bash
# Restart API after code deploy
ssh cdossman@34.41.155.134 'sudo systemctl restart fort-gym-api'

# View API logs
ssh cdossman@34.41.155.134 'sudo journalctl -u fort-gym-api -f'

# View DFHack logs
ssh cdossman@34.41.155.134 'tail -f /opt/dwarf-fortress/dfhack-stdout.log'
```

### Deploying Code Changes to VM (Best Practice)

We want the production VM to be reproducible and drift‑free.

**Rules**
- `/opt/fort-gym` is the **production checkout** and must stay on a clean git commit (preferably a tag). No rsync/manual edits here.
- Use a separate **test checkout** (e.g. `~/fort-gym-test`) for trying WIP branches/SHAs.
- The API runs under systemd (`fort-gym-api.service`). Do not start uvicorn in tmux.
- For public deployments, set `FORT_GYM_ADMIN_PASSWORD` (and optionally `FORT_GYM_ADMIN_USER`) to protect admin UI and non‑public endpoints.

**Workflow**
Convenience wrappers live in the Makefile:
- `make vm-test SHA=<sha-or-branch> [LIVE=1]`
- `make vm-deploy SHA=<sha-or-tag>`

1. **Local**: commit + push to GitHub.
2. **VM test**: pull that exact commit into the test checkout and run smoke/live tests:
```bash
ssh -i ~/.ssh/google_compute_engine cdossman@34.41.155.134 '
  cd ~/fort-gym-test &&
  git fetch origin &&
  git checkout <sha-or-branch> &&
  source /opt/fort-gym/.venv/bin/activate &&
  pytest -q
'
```
3. **VM deploy**: fast‑forward production to the same SHA and restart the API:
```bash
ssh -i ~/.ssh/google_compute_engine cdossman@34.41.155.134 '
  sudo systemctl stop fort-gym-api &&
  cd /opt/fort-gym &&
  git fetch origin &&
  git reset --hard <sha-or-tag> &&
  sudo systemctl start fort-gym-api
'
```

If you must rsync for speed, do it **only** to the test checkout with strict excludes, never `/opt/fort-gym`.

### Creating Public Share Tokens
Runs must have share tokens to appear in the public UI:
```bash
curl -s -u admin:'<password>' -X POST "http://34.41.155.134:8000/runs/{run_id}/share" \
  -H "Content-Type: application/json" \
  -d '{"scope": ["export", "live", "replay"]}'
```

### Troubleshooting

**DFHack keeps crashing**: Usually a bad save under `/opt/dwarf-fortress/data/save/` (DF scans saves on boot). Keep pristine seeds under `/opt/dwarf-fortress/data/seed_saves/` and set `/etc/fort-gym.env` `FORT_GYM_SEED_SAVE` + `FORT_GYM_RUNTIME_SAVE`, then restart `dfhack-headless`.

**RemoteFortressReader won't enable**: This plugin sometimes fails on first load. Wait for the world to fully load, then verify with `plug` command.

**API timeouts**: Ensure DFHack is fully loaded before starting the API. The API creates RPC connections that will fail if DFHack isn't ready.

## DFHack CLI Compatibility

**IMPORTANT**: The VM's DFHack version does NOT support `-q` or `-e` flags for `dfhack-run lua`:

```bash
# BROKEN - do not use:
dfhack-run lua -q -f script.lua    # -q flag causes syntax error
dfhack-run lua -e "print(1)"       # -e flag causes syntax error

# CORRECT:
dfhack-run lua -f script.lua args...
dfhack-run lua "print(1)"
```

DFHack output includes ANSI color codes (`\x1b[0m`) that must be stripped before parsing JSON. See `_strip_ansi()` in `dfhack_exec.py`.

## Code Style

- Python 3.11+, four-space indentation
- Type hints on public APIs
- Format with `black` (line length 100) and `isort --profile black`
- Lint with `ruff check fort_gym tests` and `mypy fort_gym`
- Modules: `snake_case`, classes: `PascalCase`, constants: `UPPER_SNAKE_CASE`

## Design Principles

### Prefer LLMs Over Heuristics
For analysis, pattern detection, and anomaly detection tasks, **always use LLM-based approaches** instead of hardcoded heuristics. Heuristics are biased toward known patterns and cannot discover new failure modes.

**Trace Analysis**: Use Gemini 3.0 Pro Preview (1M token context) for analyzing run traces:
- For traces < 1M tokens: Single LLM call with full trace
- For traces > 1M tokens: Chunk at 500k tokens, carry forward key insights to next chunk
- Let the LLM identify patterns, anomalies, and generate hypotheses without predefined rules

**Environment Variables**:
- `GOOGLE_API_KEY` - Required for Gemini-based trace analysis

## Testing

- Tests live in `tests/` mirroring `fort_gym/bench/` structure
- Use pytest fixtures from existing test files
- Tests writing artifacts should use pytest tmp_path fixtures
- Mock backend tests are fast; DFHack tests require DFHACK_ENABLED=1

## Commit Style

Follow existing prefixes: `dfhack:`, `api:`, `infra:`, `agent:`, `env:`, `run:`, `eval:`, `test:`, `docs:`. Keep subject line ≤72 chars, imperative mood.

## Deployment

Infrastructure uses Ansible playbooks in `infra/ansible/`:
- Edit `inventory.ini` with VM IP/user/SSH key
- Configure `group_vars/all.yml` (DFHack archive URL, service settings)
- Playbooks install Xvfb, DF/DFHack to `/opt/dfhack`, fort-gym to `/opt/fort-gym`
- Services: `dfhack-headless.service` (port 5000), `fort-gym-api.service` (port 8000)
- Default service user: `ubuntu`

Firewall: open TCP ports 5000 (DFHack) and 8000 (fort-gym API).

## DFHack v0.47.05 Compatibility Notes

The VM runs DFHack v0.47.05 which has some API differences from newer versions:

### Tick Advancement Requires `nopause`
The game auto-pauses frequently in headless mode. The `advance_ticks_exact_external()` function enables `nopause 1` before each tick advancement to prevent this.

### State Reading Uses CLI (Not RPC)
RPC's `CoreRunCommandRequest` doesn't capture `dfhack.print()` output. State reading uses CLI-based `read_game_state()` in `dfhack_exec.py` instead.

### Lua Module Differences
- `require('dfhack.units')` does NOT exist - use direct unit field access
- `df.workorder.WorkOrder` does NOT exist - use `df.manager_order:new()`
- Job types use `df.job_type.ConstructBed` (not `MakeBed`)

### Manager Order Creation
```lua
-- Correct for v0.47.05:
local wo = df.manager_order:new()
wo.job_type = df.job_type.ConstructBed  -- 71
wo.amount_total = qty
wo.amount_left = qty
df.global.world.manager_orders:insert("#", wo)
```

## Roadmap: Agent Memory & Experimentation System

The following features are planned to improve agent performance through memory, tools, and systematic experimentation.

### Current Limitation
Each step is currently **stateless** - the agent makes a fresh LLM call with no memory of previous steps. Keystroke mode has minimal context: last 5 actions shown in observation text, but no conversation history or goal tracking.

### Implemented Features

#### Trace Analysis (LLM-based)
Automated post-run analysis using Gemini 3.0 Pro Preview to identify failure patterns and generate improvement hypotheses.

**Usage**:
```bash
# Analyze a completed run
fort-gym analyze <run_id>

# Auto-analysis runs after each run (if GOOGLE_API_KEY is set)
```

**Output**: `analysis.json` and `analysis.txt` in the run's artifact directory.

**Chunking**: For traces > 1M tokens, chunks at 500k with carry-forward of insights.

#### Action Feedback in Observations
Agent now receives feedback about game state and action results:

**Observation text now includes**:
```
Game Status: PAUSED (press SPACE to unpause)
Last Action: REJECTED - tile not accessible
Time: tick 1000
Population: 7 dwarves
...
```

**State JSON includes**:
- `pause_state: true/false` - Whether game is paused
- Previous action result is tracked and passed to encoder

### Planned Features

#### 1. Agent Memory (Hybrid Strategy)
- **Last N steps**: Keep full conversation history for recent steps (configurable window, default 10)
- **Summary of older steps**: Compress older history into a running summary
- **Implementation**: New `MemoryManager` class in `fort_gym/bench/agent/memory.py`

#### 2. Agent Tools
- **Web search**: Agent can look up Dwarf Fortress information during decision-making
- **DF Wiki tool**: Query embedded DF documentation
- **Implementation**: New `ToolManager` class in `fort_gym/bench/agent/tools.py`

#### 3. Experimentation Framework
YAML-based configuration system to test different agent variants:

```yaml
# Example: experiments/with_memory.yaml
name: hybrid-memory-10
agent_type: anthropic-keystroke
memory_strategy: hybrid
memory_window: 10
tools_enabled: [df_wiki]
max_steps: 50
```

**Experiment types**:
- Different memory strategies (none, conversation, summary, hybrid)
- Different system prompts
- Different tools enabled/disabled
- A/B testing between agent variants

**New files**:
- `fort_gym/bench/experiment/config.py` - Config dataclasses
- `fort_gym/bench/experiment/runner.py` - Experiment execution
- `fort_gym/bench/experiment/analysis.py` - Comparison utilities
- `fort_gym/bench/agent/experimental.py` - Configurable agent

**New API endpoints**:
- `POST /experiments` - Launch experiment from config
- `GET /experiments` - List all experiment runs
- `GET /experiments/compare?ids=run1,run2` - Compare results

### Implementation Order
1. **Action Feedback** - Add pause_state and action results to observation (quick win, high impact)
2. Memory Manager - Core memory abstraction
3. Experimental Agent - Agent that uses memory
4. Config System - Load experiments from YAML
5. Tool Manager - Web search / wiki tools
6. API Endpoints - Launch/compare experiments
7. Analysis Tools - Compare results across runs

## Known Issues

### Action Type "WAIT" Not in Schema
The `FakeLLMAgent` emits `WAIT` actions but `WAIT` is not in `ALLOWED_TYPES`. Either add `WaitAction` to `actions.py` or change `FakeLLMAgent` to emit a valid action type.
