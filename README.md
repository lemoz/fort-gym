# fort-gym

An open-source benchmark for evaluating autonomous agents overseeing Dwarf Fortress colonies via DFHack.

## Project Goals
- Provide a reproducible harness for stepping agents through fortress management with a strict action schema.
- Capture rich observations, memory, and scoring artifacts for benchmarking.
- Enable orchestration of multiple fortress runs with API and web dashboard support.

## Non-Goals
- Adventure Mode agent support.
- Per-dwarf autonomous brains beyond a single overseer controller.
- Pixel or vision-based observation channels.

## Quickstart (Mock)
1. `make api` to launch the FastAPI development server.
2. Check service health: `curl http://localhost:8000/health`.
3. Kick off a placeholder run: `curl -X POST http://localhost:8000/runs` and copy the returned `run_id`.
4. Stream updates via SSE: open `http://localhost:8000/runs/<run_id>/events/stream` or load `web/index.html` in a static server to see live logs.

## DFHack Backend
- Generate protobuf bindings once per DFHack release: `make proto` (requires `grpcio-tools`).
- Start Dwarf Fortress with DFHack's remote server enabled (`remote` plugin) and ensure it listens on the configured host/port (defaults: `127.0.0.1:5000`).
- Launch a run targeting DFHack once the backend is available; the CLI defaults to the mock environment for now.
- Headless environments may need `xvfb-run` or similar virtual displays; see the [Travis CI headless guide](https://docs.travis-ci.com/user/gui-and-headless-browsers/).

### Reference links
- DFHack Remote API overview: [docs.dfhack.org](https://docs.dfhack.org/en/stable/docs/dev/Remote.html)
- RemoteFortressReader plugin details: [docs.dfhack.org tools](https://docs.dfhack.org/en/stable/docs/tools/RemoteFortressReader.html)


### Action Schema Example
```json
{
  "type": "BUILD",
  "params": {
    "structure": "workshop",
    "material": "granite",
    "location": [1, 1, 0]
  },
  "intent": "Expand crafting capacity"
}
```

### SSE Event Frame
```
event: state
data: {"run_id": "<id>", "step": 0, "state": {"time": 0}}

```

## Documentation
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design notes as they develop.

## CLI Quickstart
- Install editable package: `pip install -e .`
- Run the development API server: `fort-gym api`
- Execute a mock benchmark stepper: `fort-gym mock-run`
- List available API routes: `fort-gym routes`

## Public vs Admin UI
- **Public (read-only):** open `web/index.html` directly or serve the directory via `python -m http.server -d web 8080`. Spectators can browse live runs, leaderboards, and consume share-token SSE feeds.
- **Admin:** open `web/admin.html` for lifecycle controls. Start runs, pause/resume/stop them, and mint share links that unlock public live, replay, or export access.

### Batch jobs (10-run)
- Start via Admin panel or API:
  ```bash
  curl -X POST localhost:8000/jobs -H 'Content-Type: application/json' \
    -d '{"model":"random","backend":"mock","n":10,"parallelism":2,"max_steps":200,"ticks_per_step":100}'
  ```
- Results: each run writes `trace.jsonl` and `summary.json`; leaderboard reads summaries.

## DFHack Alpha
- DFHack binaries are currently published for Linux/Windows only. On macOS run the mock backend locally and use a Linux VM/host for DFHack experiments.
- Launch DFHack headless (Linux host/VM): set `DF_DIR` and optional `DFHACK_PORT`, then run `make df-headless` in another terminal. This wraps Dwarf Fortress with `Xvfb` and expects DFHack's remote plugin to listen on that port.
- Enable the backend by exporting `DFHACK_ENABLED=1` (and adjust `DFHACK_HOST` / `DFHACK_PORT` if needed). The API and CLI will otherwise refuse DFHack runs.
- Start a run with `backend="dfhack"` via the admin panel or API. Current support covers basic state polling plus `DIG` designations, manager `ORDER`s, and a Carpenter Workshop `BUILD`. Failures trigger stderr events and terminate the run gracefully.

## LLM Agents
- `random`: built-in baseline that emits schema-valid actions with no external calls.
- `fake`: deterministic tool-call responses for tests and demos (no API requirement).
- `openai`: function-calling agent. Configure `OPENAI_API_KEY`, `OPENAI_MODEL`, `LLM_MAX_TOKENS`, and `LLM_TEMP`.
- `anthropic`: Claude tool-use agent. Configure `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, plus the shared limits above.

**Action Tool Contract** — All LLM agents must answer via the `submit_action` tool/function exactly once per step. See `fort_gym/bench/env/actions.py` (and `ACTIONS.md`) for schema details.

## Local Setup Checklist
1. Copy `.env` (already scaffolded) and fill in:
   - OpenAI/Anthropic API keys if you plan to run LLM agents.
   - `DFHACK_ENABLED=1`, `DF_DIR`, `DFHACK_HOST`, `DFHACK_PORT` only when targeting a Linux DFHack host or VM; leave disabled for mock runs.
2. Install dependencies: `pip install -e .[dev]` plus provider SDKs (`openai`, `anthropic`) when required.
3. For DFHack testing, spin up a Linux machine/VM, launch DFHack via `make df-headless`, and confirm the `remote` plugin listens on the desired port.
4. Start the API (`fort-gym api`) or run CLI helpers (`fort-gym mock-run`, `fort-gym routes`). Use the admin panel to submit runs with your chosen backend and agent model.
