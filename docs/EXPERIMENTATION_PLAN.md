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

`MemoryManager` holds, per run (in-process):

- `recent_steps`: rolling window of full step records (window from
  `FORT_GYM_MEMORY_WINDOW`, default in `config.py`)
- `summary`: compressed digest of older steps (`compress_old_steps`)
- `pois`: up to 40 points of interest with coordinates (`remember_poi`)
- `failed_attempts`: what didn't work and why (`remember_failed_attempt`)
- gameplay plan: `write_gameplay_plan` / `review_gameplay_plan`
- `query_memory` and `get_context()` for prompt assembly

Known gap: memory does not persist across runs or process restarts (no
serialization on `MemoryManager`).

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
evidence, plus explicit blockers (`no_real_layout_progress`,
`no_production_surface`, `repetitive_policy`,
`illegal_or_assisted_progress_seen`, ...). Experiment reports should compare
rubric blockers alongside score deltas, and only provenance-eligible progress
counts (see `docs/Actions_Headless_Safety.md`).

## Open Experiment Questions

1. **Governed LLM policy quality**: on the fixed seed save, how far can
   `dfhack-governed-llm` progress vs the scripted ceiling? Compare score,
   rubric blockers, and step efficiency.
2. **Memory ablation**: same model with and without memory context — does the
   plan/POI memory reduce repeated failed actions?
3. **Model comparison**: GLM 5.2 vs other OpenRouter models on identical
   governed runs (pin with `OPENROUTER_MODEL`).
4. **Action-surface breadth**: as new bounded helpers land (stockpiles, zones,
   more workshop types), does the policy use them productively without
   heuristic prompting?

## Prerequisites / Blockers

- Cross-run memory persistence (serialize `MemoryManager` state per
  workspace/fortress) — needed before "improves the fortress across sessions"
  experiments.
- `work_metrics.lua` supports only the hardcoded `two_room_workshop` plan —
  layout-diversity experiments need plan-agnostic completion metrics.
- Governed runs lack a per-step `gameplay_proof` tile-diff (keystroke mode has
  one) — add before making cross-mode evidence comparisons.
