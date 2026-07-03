# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fort-gym is a Dwarf Fortress agent benchmark with two backends:
- **Mock backend**: Deterministic environment for local development and testing
- **DFHack backend**: Live fortress runs on Linux using DFHack's remote plugin (port 5000)

Agents issue exactly one action per step. The harness records every observation/state/action to JSONL, streams live updates over SSE, and exposes admin/public web UIs plus 10-run job orchestration with summaries and leaderboards.

**Core doctrine**: no fake scoring, no simulated-only proof, no passing off derived visualizations as gameplay. DFHack is a legal command transport only when bounded/audited (the "governed" path); score and progress must come from real DF state changes with replayable evidence. See "Evidence Boundaries & Scoring Provenance" below.

**Model policy**: OpenRouter is the primary LLM provider (`OPENROUTER_MODEL`, default `z-ai/glm-5.2`). Anthropic agents are legacy and disabled by the API server unless `FORT_GYM_ENABLE_ANTHROPIC=1` — do not use Anthropic models for new work.

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

## Operating Model (CEO + Subagents)

We work best when tasks are delegated to small, well-scoped “subagent briefs” with explicit completion criteria.

This repo is typically developed with multiple Codex CLI agents running in parallel. The safest way to do this is:
- one **git worktree** per subagent (isolated working tree + branch)
- optionally, one **tmux window** per subagent (easy supervision + logs)

### Launching Subagents (Worktrees + tmux)

1. Create a worktree per subagent:
```bash
mkdir -p .agents
git worktree add .agents/agent-1 -b agent/agent-1
```

2. Run the subagent non-interactively (per OpenAI Codex CLI docs, `codex exec` is no-approval and defaults to `read-only`; use `--full-auto` to allow edits):
```bash
codex exec --full-auto -m gpt-5.2-codex -C .agents/agent-1 -o .agents/agent-1.last.md - < .agents/agent-1.brief.md
```

To crank reasoning to “extra high” (supported on `gpt-5.1-codex-max` and `gpt-5.2` per Codex docs; if `gpt-5.2-codex` isn’t available in your account, use `gpt-5.2`):
```bash
codex exec --full-auto -m gpt-5.2-codex -c model_reasoning_effort=xhigh -C .agents/agent-1 -o .agents/agent-1.last.md - < .agents/agent-1.brief.md
```

If the brief requires network access (fetching docs, installing deps, etc), use:
```bash
codex exec --sandbox danger-full-access -m gpt-5.2-codex -C .agents/agent-1 -o .agents/agent-1.last.md - < .agents/agent-1.brief.md
```

3. Optional: supervise multiple subagents in tmux:
```bash
tmux new-session -d -s fortgym-agents
tmux new-window -t fortgym-agents -n agent-1 "cd $PWD/.agents/agent-1 && codex exec --full-auto -m gpt-5.2-codex -o $PWD/.agents/agent-1.last.md - < $PWD/.agents/agent-1.brief.md | tee $PWD/.agents/agent-1.log"
tmux attach -t fortgym-agents
```

4. When done: run tests, commit, push, and open a PR:
```bash
cd .agents/agent-1
../../.venv/bin/python -m pytest -q
git status -sb
```

### OpenAI Codex CLI Docs (Canonical)

If anything here conflicts with upstream behavior, prefer the upstream docs:
- https://github.com/openai/codex (README + docs)
- Non-interactive mode: https://github.com/openai/codex/blob/main/docs/exec.md
- Sandbox & approvals: https://github.com/openai/codex/blob/main/docs/sandbox.md
- Configuration + profiles: https://github.com/openai/codex/blob/main/docs/config.md

Useful flags for contract-style subagents:
- `--json` to stream machine-readable events (progress + command/file ops).
- `--output-schema <schema.json>` to require a structured final answer (JSON Schema).

### Subagent Brief Template (Contract)

Copy/paste this into a fresh Codex CLI session (max model config) as the entire prompt:

**Objective**
- What exactly to accomplish (1–2 sentences).

**Context**
- Repo path + relevant files to read first.
- Any URLs/endpoints to verify.

**Scope**
- In-scope (bullet list).
- Out-of-scope (bullet list).

**Deliverables**
- Concrete artifacts: files to change/add, commands to run, screenshots/logs to capture.
- Required docs updates (if any).

**Acceptance Criteria**
- Observable behavior changes (API/UI).
- Tests to run (exact commands) and expected results.
- Backward-compat constraints (if relevant).

**Constraints**
- Don’t refactor unrelated code.
- Keep changes minimal and consistent with existing style.
- No secrets in diffs/logs.

**Reporting Format**
- Return: (1) what changed, (2) how to verify, (3) risks/edge cases.

### CEO Workflow (How We Use Briefs)

1. CEO defines 1–3 briefs max (right-sized; ≤1–2 days each).
2. Each subagent works on a dedicated branch and pushes frequently.
3. CEO reviews diffs, runs validation, merges to `main`, and deploys to the VM.
4. CEO updates `CLAUDE.md` when the workflow itself changes (so future-us stays aligned).

### Right-Sizing Guidelines

- Prefer “one surface area”: one endpoint, one DB migration, one page, one infra role.
- If a brief needs more than ~5 files or involves >2 subsystems, split it.
- Always include: exact test commands + a concrete “done” signal.

## Architecture

### Core Package Structure
- `fort_gym/bench/agent/` - Agent implementations (base.py defines the Agent ABC)
- `fort_gym/bench/env/` - Environment adapters: mock_env.py (deterministic), dfhack_client.py (gRPC), executor.py (action dispatcher)
- `fort_gym/bench/run/` - Orchestration: runner.py (main run loop), jobs.py (batch orchestration), storage.py (SQLite-backed run registry)
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
   - Admin: `/runs`, `/jobs`, `/runs/{id}/events/stream`, `/screenshot`, `/admin/keys`
   - Public: `/`, `/leaderboard`, `/public/runs`, `/public/runs/{token}/events/{stream|replay}`, `/public/runs/{token}/export/trace`
   - Public leaderboard data: `/public/leaderboard/best-over-time`

### Agents

Agents must implement `Agent.decide(obs_text: str, obs_json: dict) -> dict` returning exactly one action dictionary. Register new agents via `register_agent()` in `agent/base.py`; the API server lazily imports agent modules via `OPTIONAL_AGENT_MODULES` in `api/server.py`, so new model names must be added there too.

Registered models by category:

**Governed (legal DFHack gameplay — the main research path):**
- `dfhack-governed-scripted` (`agent/governed.py`) — deterministic Python state machine that validates the governed action substrate. No LLM.
- `dfhack-governed-llm` (`agent/governed_llm.py`) — LLM policy (OpenRouter, default `z-ai/glm-5.2`) on the same governed action surface: DIG/BUILD/ORDER/WAIT with `MemoryManager` plan/POI memory.
- Governed mode is gated by model name: the model must be in `GOVERNED_DFHACK_MODELS` in `run/runner.py`. A governed model name must NOT contain "keystroke" or end with "-research" (that would also match `_is_keystroke_model`).

**Keystroke (raw UI control via CopyScreen + send-key):**
- `openrouter-keystroke`, `openrouter-keystroke-perception-review`, `openrouter-glm-5.2` (`agent/llm_openrouter.py`) — default path, GLM 5.2 via OpenRouter.
- `openai-keystroke-perception-review` (`agent/llm_openai.py`) — same machinery via OpenAI directly.
- `anthropic-keystroke`, `-poi-review`, `-plan-review`, `-perception-review`, `-perception-review-opus`, `anthropic-research` (`agent/llm_anthropic.py`, `llm_anthropic_research.py`) — **legacy, disabled unless `FORT_GYM_ENABLE_ANTHROPIC=1`**.

**Toolbox (structured actions, dfhack_assisted — does not earn gameplay score on dfhack):**
- `anthropic`, `anthropic-dig-first`, `anthropic-fortress-plan` (legacy, gated), `openai`.

**Utility:** `random` (always available), `fake` (deterministic, CI).

### Evidence Boundaries & Scoring Provenance

Five distinct surfaces — never conflate them:

1. **Live screenshot** — `GET /public/runs/{token}/screenshot` (scope `live`): a live CopyScreen RPC of whatever DF process the server is attached to right now. Not recorded, not per-run isolated (single global `DFHackClient` in `api/server.py`); only meaningful while that run is executing.
2. **Saved replay DF Screen frames** — `screen_text` recorded per step into `trace.jsonl` (runner captures it when `is_keystroke_mode or is_governed_dfhack_mode`). This is the recorded gameplay evidence the replay UI renders as "DF Screen".
3. **Derived map inspection** — `map_snapshot` per step (dfhack backend, ≤64×64 rect via `hook/map_snapshot.lua`). The replay UI labels it "DERIVED DFHACK MAP INSPECTION / not gameplay proof". Analysis layer only.
4. **Old traces without `screen_text`** — replay shows a "No Recorded DF Screen Frame" evidence-gap panel instead of pretending. Toolbox-agent traces also never have screen frames.
5. **Score/rubric** — `eval/scoring.py` `composite_score` over observed state aggregates; `eval/rubric.py` deterministic 8-dimension rubric over the last 100 trace rows with blockers (`illegal_or_assisted_progress_seen`, `repetitive_policy`, ...). Judgment over real state, reported alongside evidence.

Provenance rules (`run/runner.py`):
- Governed model + action in `GOVERNED_DFHACK_ACTIONS` ({DIG, BUILD, ORDER, WAIT}) → `execute.provenance = "dfhack_governed"`, `gameplay_progress_eligible = true`, `metrics.score_provenance = "dfhack_governed_observed_state"`.
- Any other dfhack model + structured DIG/BUILD/ORDER → `execute.provenance = "dfhack_assisted"`; `_zero_assisted_dfhack_progress()` zeroes all progress fields AND one accepted assisted action permanently blocks scoreable elapsed time for the rest of the run (`score_provenance = "gameplay_only_assisted_progress_zeroed"`).
- Keystroke mode scores only steps with observed current-step progress (`keystroke_ui_work_rect` vs `keystroke_no_*_progress` provenance), with per-step `gameplay_proof` tile-diff evidence.
- `hook/complete_dig_rect.lua` (`FORT_GYM_DFHACK_COMPLETE_DIG=1`) instantly forges dig outcomes — debug only, never scores, and the rubric flags it (`debug_complete_dig`).
- Governed target discovery wraps `prepare_keystroke_target` with `read_view_state`/`restore_view_state` (`hook/view_state.lua`, `hook/restore_view_state.lua`) so probes preserve the live camera/cursor.

When adding features: never add a metric to the score matrix just because the agent did it — score only observed DF state changes, and tag provenance.

### Keystroke Mode

The keystroke agents (default: `openrouter-keystroke-perception-review`, GLM 5.2) control DF via raw keystrokes:
- Screen captured via CopyScreen RPC, converted to 80x25 text
- The model decides what keys to press based on screen content
- Keys sent via `devel/send-key` command
- Key module: `fort_gym/bench/env/keystroke_exec.py`
- **Action history**: recent actions shown in observation for context/memory
- **Pause on end**: Game is paused when run completes to prevent state drift

The system prompt encourages the model to take action (dig, build, create stockpiles) rather than just exploring menus. Key behaviors:
- Recognizes main menu is NOT an overlay to dismiss
- Uses STRING_A### keys for typing letters (e.g., STRING_A097 = 'a')
- Tries alternative keys (STANDARDSCROLL_PAGEDOWN, Space) when SELECT doesn't close popups
- On embark site selection (`viewscreen_choose_start_sitest`), the `e` hotkey maps to interface key `SETUP_EMBARK`. fort-gym auto-translates `STRING_A101`/`CUSTOM_E` to `SETUP_EMBARK` so keystroke/admin control can embark reliably.

Note: the keystroke prompts in `llm_anthropic.py` are imported by the OpenRouter/OpenAI keystroke agents — prompt text lives there for historical reasons even though Anthropic models are disabled by default.

## Environment Variables

Copy `.env.example` to `.env` and configure:
- `OPENROUTER_API_KEY` - Primary LLM key. `OPENROUTER_MODEL` (default `z-ai/glm-5.2`), `OPENROUTER_BASE_URL`, `OPENROUTER_TIMEOUT_SECONDS`, `OPENROUTER_MAX_ATTEMPTS`, `OPENROUTER_MAX_TOOL_ROUNDS`, `OPENROUTER_DISABLE_REASONING`
- `OPENAI_API_KEY` - Optional, for OpenAI agents
- `FORT_GYM_ENABLE_ANTHROPIC` - Must be `1` for any `anthropic*` model; the API server returns HTTP 400 for them otherwise. `ANTHROPIC_API_KEY` alone is not sufficient. Legacy — leave off.
- `FORT_GYM_ADMIN_PASSWORD` - Required for `/admin` and all admin APIs (`/runs`, `/jobs`, `/step`, `/screenshot`, `/admin/keys`, `/runs/{id}/pause|resume|stop|share`, `/runs/{id}/export/trace`)
- `FORT_GYM_ADMIN_USER` - Basic auth user (default `admin`)
- `FORT_GYM_INSECURE_ADMIN=1` - Dev-only escape hatch to enable admin endpoints without a password
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
- `FORT_GYM_DB_PATH` - SQLite path for persistent run history (default `$ARTIFACTS_DIR/fort_gym.sqlite3`)
- `FORT_GYM_TRUST_PROXY=1` - Trust `X-Forwarded-For` when behind a local reverse proxy (Caddy/Nginx)
- `FORT_GYM_RATE_LIMIT_ADMIN_RPM` / `FORT_GYM_RATE_LIMIT_RUNS_RPM` - Simple in-process rate limits

See `fort_gym/bench/config.py` for full list.

## GCE VM Deployment (dfhack-host)

### Current VM
- **GCP project/zone**: `scrolller-307201` / `us-central1-a`
- **IP**: 34.41.155.134, **domain**: fortgym.live (A record → this VM)
- **Web UI**: https://fortgym.live/ (spectator), https://fortgym.live/admin (admin)
- **Leaderboard**: https://fortgym.live/leaderboard
- **Public replay links**: https://fortgym.live/r/{token}
- **DFHack RPC**: port 5000 (loopback)
- **DFHack version**: v0.47.05
- **Save loaded**: `region1` (reset from seed before runs)

Caddy serves HTTPS for fortgym.live and proxies to the API on loopback.

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
curl -s https://fortgym.live/health

# Start a test run (auto-creates share token for spectator view)
curl -s -u admin:'<password>' -X POST https://fortgym.live/runs \
  -H "Content-Type: application/json" \
  -d '{"backend": "dfhack", "model": "dfhack-governed-scripted", "max_steps": 5, "ticks_per_step": 1000}'
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

### VM Workflow (User Folder → Production)

We want the VM to be reproducible and drift‑free, while keeping day-to-day work in the user home directory.

**Directories**
- `~/fort-gym-test` (VM user folder): **scratch/test checkout** for running pytest, trying WIP SHAs, and ad-hoc experiments.
- `/opt/fort-gym` (system folder): **production checkout** used by systemd. Keep it clean; update it only via `make vm-deploy`.

**Rules**
- Never edit `/opt/fort-gym` by hand or via rsync. Treat it as a deployed artifact.
- Do all day-to-day work against git commits (feature branches) and test them from `~/fort-gym-test`.
- The API runs under systemd (`fort-gym-api.service`) behind HTTPS (Caddy). Do not start uvicorn in tmux on the prod VM.
- For public deployments, `FORT_GYM_ADMIN_PASSWORD` must be non-empty or admin endpoints are disabled.

**Workflow**
Convenience wrappers live in the Makefile:
- `make vm-test SHA=<sha-or-branch> [LIVE=1]`
- `make vm-deploy SHA=<sha-or-tag>`

1. **Local**: create a branch, commit, push.
2. **VM test**: run tests on the VM (avoids bogging down your laptop):
```bash
make vm-test SHA=origin/<branch>
# Optional live DFHack checks:
make vm-test SHA=origin/<branch> LIVE=1

# Full clean-clone live smoke on dfhack-host:
make vm-live-smoke VM_LIVE_SMOKE_REF=<branch-or-main>

# Full live demo rehearsal with public endpoint checks and packet output:
make vm-live-demo VM_LIVE_DEMO_REF=<branch-or-main>

# Real-model public API run plus baseline comparison packet:
make vm-deploy SHA=origin/<branch-or-main>
make vm-live-agent VM_LIVE_AGENT_REF=<branch-or-main> \
  LIVE_AGENT_MODEL=openrouter-keystroke-perception-review LIVE_AGENT_MAX_STEPS=4

# Multi-trial live scorecard across model/control variants:
make vm-live-agent-suite VM_LIVE_AGENT_REF=<branch-or-main> \
  LIVE_AGENT_MODELS=openrouter-keystroke-perception-review,openrouter-glm-5.2 \
  LIVE_AGENT_TRIALS=2 LIVE_AGENT_MAX_STEPS=6
```

The suite scorecard includes both total score and target-room work metrics from
`hook/work_metrics.lua`: work score, completion score, utility score,
production score, complexity score, designation progress, completion progress,
dig-designation delta, opened floor/wall delta, active dig jobs, two-room
fortress complexity progress, hidden/z-level diagnostics, and tick-only/no-mining
blockers. Structured DFHack `DIG` actions also run `hook/complete_dig_rect.lua`
by default so live traces can prove completed tile changes; set
`FORT_GYM_DFHACK_COMPLETE_DIG=0` to measure designation-only behavior.
3. **Merge**: once tested, merge to `main` (PR merge preferred).
4. **VM deploy**: deploy the exact git ref to production and restart the API:
```bash
make vm-deploy SHA=origin/main
curl -fsSL http://34.41.155.134/health
```

If you must rsync for speed, do it **only** to `~/fort-gym-test` with strict excludes, never `/opt/fort-gym`.

### Creating Public Share Tokens
Runs must have share tokens to appear in the public UI:
```bash
curl -s -u admin:'<password>' -X POST "http://34.41.155.134/runs/{run_id}/share" \
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

**Trace Analysis**: Use Gemini (`eval/analyzer.py`, default `gemini-2.5-flash`, override with `GEMINI_ANALYZER_MODEL`) for analyzing run traces:
- For traces < 1M tokens: Single LLM call with full trace
- For traces > 1M tokens: Chunk at 500k tokens, carry forward key insights to next chunk
- Let the LLM identify patterns, anomalies, and generate hypotheses without predefined rules

**Environment Variables**:
- `GOOGLE_API_KEY` - Required for Gemini-based trace analysis

## Testing

- Tests live in `tests/` mirroring `fort_gym/bench/` structure
- Use pytest fixtures from existing test files
- Tests writing artifacts should use pytest tmp_path fixtures
- Run with the project venv: `./.venv/bin/python -m pytest -q` (system python has incompatible pydantic/fastapi)
- Mock/offline tests cover everything by default; the 4 live-DFHack integration tests are gated by `DFHACK_LIVE=1` (not `DFHACK_ENABLED`)

## Commit Style

Follow existing prefixes: `dfhack:`, `api:`, `infra:`, `agent:`, `env:`, `run:`, `eval:`, `test:`, `docs:`. Keep subject line ≤72 chars, imperative mood.

## Deployment

Infrastructure uses Ansible playbooks in `infra/ansible/`:
- Edit `inventory.ini` with VM IP/user/SSH key
- Configure `group_vars/all.yml` (DFHack archive URL, service settings)
- Playbooks install Xvfb, DF/DFHack to `/opt/dfhack`, fort-gym to `/opt/fort-gym`
- Services: `dfhack-headless.service` (loopback 5000), `fort-gym-api.service` (127.0.0.1:8000), `caddy` (public 80/443)
- Default service user: `ubuntu`

Firewall: open TCP ports 80/443 for HTTPS; keep 8000 private (loopback) and never expose DFHack RPC directly.

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

## Agent Memory, Tools & Experimentation (Implemented)

### Memory (`fort_gym/bench/agent/memory.py`)
`MemoryManager` provides: a rolling window of recent steps (`FORT_GYM_MEMORY_WINDOW`), a compressed summary of older steps, POIs (max 40, with coordinates), failed-attempt records, a gameplay plan with `write_gameplay_plan`/`review_gameplay_plan`, and `query_memory`. It is in-process per run — nothing persists across runs or process restarts (known gap).

Used by: the keystroke review agents (`llm_anthropic.py`, `llm_openrouter.py`) via `ToolManager`, and the governed LLM agent (`governed_llm.py`) via prompt context.

### Tools (`fort_gym/bench/agent/tools.py`)
`ToolManager` wires memory/plan/perception tools (`remember_poi`, `record_failed_attempt`, `write_gameplay_plan`, `review_gameplay_plan`, `query_memory`, `record_screen_read`, `review_last_action`) into the review-mode agents.

### Experimentation (`fort_gym/bench/experiment/`)
YAML config (`config.py`) → `ExperimentRunner` (`runner.py`) → run with experiment metadata saved alongside artifacts.

### Trace Analysis (LLM-based)
Automated post-run analysis using Gemini (default `gemini-2.5-flash`, `GEMINI_ANALYZER_MODEL` to override) to identify failure patterns and generate improvement hypotheses. Diagnostic only — analyzer output never feeds the score or rubric.

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

### Remaining gaps (real, verified against code)
- Memory is in-process only — no persistence across runs/restarts, no serialization on `MemoryManager`.
- The governed helper surface is narrow: `ALLOWED_WORKSHOPS = {CarpenterWorkshop}`, 6 orderable items, `work_metrics.lua` hardcodes the `two_room_workshop` plan — an agent cannot yet earn derived completion signal for any other layout.
- Governed mode has no per-step `gameplay_proof` tile-diff object (keystroke mode has one); governed evidence is `screen_text` + metrics deltas.
- No `/experiments` API endpoints (experiment runner is CLI/Python-level only).

## Known Issues

- The `/step` interactive endpoint (`api/routes_step.py`) is a separate code path from `run_once()` — it records no `screen_text`, `map_snapshot`, provenance tags, or assisted-progress zeroing. Do not use `/step` traces as gameplay proof or scoring evidence.
- The public screenshot endpoint uses one global DFHack connection: with multiple concurrent dfhack runs it can show a different run's screen. Only one live dfhack run at a time is supported in practice.
- Share-token `expires_at` is stored but not enforced at read time.
