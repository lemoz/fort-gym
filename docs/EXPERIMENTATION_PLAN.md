# Agent Memory, Tools & Experimentation

## Status

The memory, tools, and experiment systems originally planned in this document
are **implemented**. This document now describes what exists, how the pieces
connect, and what the experimentation focus is going forward.

## Direction

The main gameplay-control research path is **DFHack-governed actions**: bounded
legal overseer commands sent through DFHack, followed by observed simulation
progress. The keystroke UI path remains valuable for replay, inspection, and as
a comparison surface, but new policy work happens on the governed action
surface.

- `dfhack-governed-scripted` — deterministic reference agent that validated the
  substrate (dig rooms → build workshop → queue orders → wait).
- `dfhack-governed-llm` — the LLM policy on the same surface (OpenRouter,
  default `z-ai/glm-5.2`). The model plus the loop must solve gameplay; helper
  heuristics stay out of the policy.

Anthropic agents are legacy and disabled unless `FORT_GYM_ENABLE_ANTHROPIC=1`.
Experiments should run on OpenRouter models.

## Implemented Components

### Memory — `fort_gym/bench/agent/memory.py`

`MemoryManager` holds state in-process during a run:

- `recent_steps`: rolling window of full step records (window from
  `FORT_GYM_MEMORY_WINDOW`, default in `config.py`)
- `summary`: compressed digest of older steps (`compress_old_steps`)
- `pois`: up to 40 points of interest with coordinates (`remember_poi`)
- `failed_attempts`: what didn't work and why (`remember_failed_attempt`)
- gameplay plan: `write_gameplay_plan` / `review_gameplay_plan`
- `query_memory` and `get_context()` for prompt assembly

Governed-agent memory can persist across runs through
`FORT_GYM_GOVERNED_MEMORY_PATH`. The G5 ablation found the current design
counterproductive, so production experiments keep it disabled until a new
memory design earns its own matched ablation.

### Tools — `fort_gym/bench/agent/tools.py`

`ToolManager` exposes memory/plan/perception tools (`remember_poi`,
`record_failed_attempt`, `write_gameplay_plan`, `review_gameplay_plan`,
`query_memory`, `record_screen_read`, `review_last_action`) to the
review-mode keystroke agents.

### Experiment runner — `fort_gym/bench/experiment/`

- `config.py`: YAML experiment config (name, description, agent/model, run
  settings)
- `runner.py`: `ExperimentRunner` executes a run and saves experiment metadata
  alongside the artifacts

There are no `/experiments` API endpoints; the runner is Python/CLI-level.

### Trace analysis — `fort_gym/bench/eval/analyzer.py`

Gemini-based post-run analyzer (default `gemini-2.5-flash`, override with
`GEMINI_ANALYZER_MODEL`; requires `GOOGLE_API_KEY`). Writes `analysis.json` /
`analysis.txt` per run. Diagnostic only — it never feeds score or rubric.

## Scoring & Rubric (how experiments are judged)

Scalar score is telemetry, not the final judge. Each `summary.json` includes a
deterministic rubric over the last 100 trace records: survival, layout,
production, breadth, responsiveness, plan coherence, anti-repetition, and legal
evidence, plus explicit blockers (`no_fort_structure`,
`no_production_surface`, `repetitive_policy`,
`illegal_or_assisted_progress_seen`, ...). Experiment reports should compare
rubric blockers alongside score deltas, and only provenance-eligible progress
counts (see `docs/Actions_Headless_Safety.md`).

## Open Experiment Questions

1. **G7 run integrity**: can the policy navigate ordinary paused dialogs while
   the runner terminates genuine tick stalls before another paid model call?
2. **G7 survival**: on `seed_region3_fresh`, can one governed run close food
   and drink loops, survive a year, house migrants, and build three functional
   rooms under the ratified WDSLL predicates?
3. **G6/G7 generalization reliability**: do matched runs repeat structure and
   survival on unseen embarks, rather than producing one exceptional replay?
4. **Memory redesign**: can a causally grounded memory beat the standing
   memory-off control without repeating the G5 inversion?
5. **Action-surface breadth**: when trace forensics prove a missing player
   capability, does a bounded player-parity primitive remove the substrate gap
   without embedding gameplay policy?

## Prerequisites / Blockers

- The G7 run-integrity candidate is implemented, review-hardened, and not
  production-deployed. The complete suite passes (607 passed, 4 skipped). It
  requires a reviewed commit and an explicit operator deployment window before
  attempt 2.
- The dedicated `INTERACT` action is strict zero-tick, governed-only, paused,
  viewscreen-allowlisted, and bounded to eight operations per modal episode
  (three unchanged screens terminate earlier). An isolated live liaison smoke
  passed; the same smoke must pass from the deployed commit.
- Tick stalls and cancellation now fail closed with durable terminal reasons;
  local regression passes and deployed-runtime verification remains the release
  gate.
- Completed furniture, raw death causes, and a run-scoped event/eat-history
  food/drink ledger now reach the trace. The ledger's citizen filter and run
  scope passed an isolated live start/read/stop smoke. `scripts/evaluate_g7.py`
  derives duration from trace ticks, reconciles the summary, and evaluates the
  ratified predicates without filling missing facts by inference.
- A non-hunger/thirst death still requires factual tantrum-chain evidence before
  it can be cleared as non-neglect; zero deaths and direct hunger/thirst deaths
  are unambiguous.
- G8 has no ratified multi-z acceptance protocol or stair/depth action surface.
