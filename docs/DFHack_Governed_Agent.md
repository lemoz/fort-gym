# DFHack-Governed Fortress Agent

## Goal

The governed path makes DFHack the command transport, not a cheat engine. The
agent issues bounded overseer commands that a human player could issue through
the UI, then the simulation must advance and produce observable state changes.
The UI remains useful for replay and inspection, but it is no longer the primary
control surface for this path.

## Legal Gameplay Boundary

Legal actions:

- Designate bounded dig/channel work.
- Place bounded buildings that create normal construction/jobs.
- Queue bounded manager or workshop production orders.
- Create stockpiles, zones, labor/admin assignments, and alerts once backed by
  audited helpers.
- Wait for a chosen number of ticks so dwarves can perform the work.

Illegal actions:

- Directly create items, material, food, drink, wealth, or dwarves.
- Instantly complete mining, construction, hauling, or production.
- Teleport units, mutate stocks, or write score state.
- Give mechanical score credit to `dfhack_assisted` debug helpers.

`hook/complete_dig_rect.lua` stays available only for explicit harness debugging.
It must not be treated as legal fortress gameplay.

## Governed Models

Governed mode is gated by model name: `GOVERNED_DFHACK_MODELS` in
`fort_gym/bench/run/runner.py`. The runner marks a governed model's structured
`DIG`, `BUILD`, `ORDER`, and `WAIT` actions as `execute.provenance =
"dfhack_governed"` with `gameplay_progress_eligible = true`, and per-step
metrics carry `score_provenance = "dfhack_governed_observed_state"`. Older
structured DFHack agents still get `dfhack_assisted` progress zeroed for scalar
scoring (and one accepted assisted action blocks scoreable elapsed time for the
rest of that run).

### `dfhack-governed-scripted` (substrate validation)

The first governed model. It is intentionally scripted (a Python state machine
over the `work` metrics, no LLM) so the runner and evaluator could prove the
command substrate before an LLM policy used the same action surface. Its plan:

1. Dig the starter room.
2. Dig the connector east of the starter room.
3. Dig the workshop room.
4. Place a carpenter workshop in the completed workshop room.
5. Queue small manager orders (bed, door, table, chair, barrel, bin).
6. Wait while dwarves resolve queued jobs.

The substrate is validated: live runs show workshop placement with a real
material item, real created job IDs, tick advancement, and in-game date
progression, all recorded with per-step CopyScreen frames.

### `dfhack-governed-llm` (LLM policy)

The LLM policy on the same legal action surface (`agent/governed_llm.py`).
It uses OpenRouter chat completions (default `z-ai/glm-5.2`, override with
`OPENROUTER_MODEL`) with a single `submit_action` tool restricted to
`DIG`/`BUILD`/`ORDER`/`WAIT`. Per step it receives:

- the encoded observation (including the recorded CopyScreen text and the
  bounded `work` metrics),
- its own memory context from `MemoryManager` (recent steps, summary, POIs,
  failed attempts, current gameplay plan).

The agent maintains its plan and POIs across steps via the action's
`plan_step`/`memory_update` fields and the executed-result feedback loop. It
holds no gameplay heuristics — the model plus the loop must solve gameplay.
Invalid or failed LLM output degrades to a safe `WAIT` (time still advances;
the failure is recorded in the trace).

## Replay Evidence

Every governed step records into `trace.jsonl`:

- `screen_text` — a real CopyScreen frame at that step (the replay UI's
  "DF Screen" mode). This is the recorded gameplay evidence.
- `map_snapshot` — a derived DFHack tile read, shown only under the explicit
  "Map Inspect" label ("not gameplay proof").
- `execute.provenance` / `metrics.score_provenance` — the legality tags above.

Governed target discovery wraps helper probes with
`hook/view_state.lua` / `hook/restore_view_state.lua` so the live DF
camera/cursor is preserved — probes never disturb the visible game. Traces
recorded before screen capture existed show "No Recorded DF Screen Frame" in
replay instead of pretending a derived view is gameplay.

## Rubric Evaluation

The scalar score remains useful telemetry, but it is not enough. `summary.json`
includes a deterministic (non-LLM) `rubric` object computed over the last 100
trace rows with dimensions for:

- survival management
- shelter layout
- production economy
- fortress breadth
- responsiveness
- plan coherence
- anti-repetition
- legal evidence

The rubric returns a 0-100 score, per-dimension evidence, blockers, and a short
critique. It is designed to flag exactly the failure mode where score rises while
the fort stays narrow, repetitive, or non-legal.

## Known Limits and Next Steps

Current structural limits of the governed surface:

- `ALLOWED_WORKSHOPS = {CarpenterWorkshop}` and a 6-item order whitelist —
  no mason/smith/farm/still support yet.
- `hook/work_metrics.lua` hardcodes the `two_room_workshop` plan; completion
  signal exists only for that layout.
- Memory (`MemoryManager`) is in-process per run — nothing persists across runs.
- Governed mode records `screen_text` + metrics deltas but has no per-step
  `gameplay_proof` tile-diff object like keystroke mode.

The next action helpers should be added only after their legal semantics are
clear:

- bounded stockpile creation
- bounded activity zone creation
- labor/admin assignment through normal DF state
- richer read-only metadata for messages, announcements, jobs, units, and POIs

Each helper needs tests showing that it rejects unbounded or illegal state
mutation, and live traces showing that progress came from simulation resolution.
