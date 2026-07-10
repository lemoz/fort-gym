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

1. **G7 run integrity**: after attempt 4's infrastructure abort, can every
   accepted build reserve a material a citizen can actually haul, can every
   accepted order create real workshop jobs, and can bounded dialog interaction
   traverse the observed topic-meeting screen without arbitrary key access?
2. **G7 survival**: on `seed_region3_fresh`, can one governed run close food
   and drink loops, survive a year, house migrants, and build three functional
   rooms under the ratified WDSLL predicates?
3. **G6/G7 generalization reliability**: do matched runs repeat structure and
   survival on unseen embarks, rather than producing one exceptional replay?
4. **Memory redesign**: can a causally grounded memory beat the standing
   memory-off control without repeating the G5 inversion?
5. **Action-surface breadth**: when trace forensics prove a missing legal
   gameplay capability, does a bounded command primitive remove the substrate
   gap without embedding gameplay policy or bypassing materials, jobs, labor,
   and elapsed simulation time?

## Prerequisites / Blockers

- Attempt 3's material-reuse and terminal-lifecycle follow-up merged as PR #69,
  deployed at `808f25d6942b89844768c78b80911646dbb0d5b0`, and passed the
  deployed cleanup-before-terminal boundary smoke.
- Attempt 4 is an infrastructure-aborted FAIL with no policy verdict. Its public
  replay and exact gate output are in `docs/WDSLL.md`. It failed closed after
  208 rows; cleanup, detached ledger, and durable summary all passed.
- Post-terminal read-only evidence classified all 36 pending construction jobs
  as walk-group disconnected. The follow-up candidate requires the target and
  selected item to share one living citizen's current DF walk group, verifies a
  conservative dry/visible FLOOR target and resulting job linkage, exposes the
  connectivity snapshot, and rejects ORDER unless a completed matching
  workshop receives concrete jobs. This does not assert that a dwarf has
  accepted the haul. Fresh-seed candidate and deployed smokes proved a connected
  wall and Still completed through dwarf labor, then linked exactly two concrete brew
  jobs without inserting a duplicate manager order. PR #70 merged and deployed
  as `e012e704b7a45cd509034700c3524801217130ef`; attempt 5 is now running from
  that SHA with a [permanent replay](https://fortgym.live/r/88uZqRulANyNG_e7t7c6KFlEOYRvHZdz).
- The dedicated `INTERACT` action is strict zero-tick, governed-only, paused,
  viewscreen-allowlisted, and bounded to eight operations per modal episode
  (three unchanged screens terminate earlier). Attempt 4 proved generic confirm
  is insufficient for `viewscreen_topicmeetingst`; a post-terminal live probe
  proved semantic `OPTION1` exits the visible one-option screen without advancing
  a tick. The deployed path exposes that key only as `finish_topic_meeting` on
  that exact viewscreen.
- Tick stalls, modal loops, and cancellation fail closed with durable terminal
  reasons; attempt 4 terminated on its third unchanged topic-meeting interaction.
- Completed furniture, raw death causes, and a run-scoped event/eat-history
  food/drink ledger now reach the trace. The ledger's citizen filter and run
  scope passed an isolated live start/read/stop smoke. `scripts/evaluate_g7.py`
  derives duration from trace ticks, reconciles the summary, and evaluates the
  ratified predicates without filling missing facts by inference.
- A non-hunger/thirst death still requires factual tantrum-chain evidence before
  it can be cleared as non-neglect; zero deaths and direct hunger/thirst deaths
  are unambiguous.
- G8 has no ratified multi-z acceptance protocol or stair/depth action surface.
