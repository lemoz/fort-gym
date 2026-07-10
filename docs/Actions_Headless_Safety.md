# DFHack Action Safety Guidelines

fort-gym executes DFHack actions exclusively through curated Lua helpers stored under `/opt/dwarf-fortress/hook`. Every command is invoked via `dfhack-run`, constrained to the loopback interface, and bounded to 2.5 seconds.

## CLI Wrappers

- `hook/order_make.lua` enqueues real jobs for a limited set of goods (`bed`, `door`, `table`, `chair`, `barrel`, `bin`, `brew`). Quantities are clamped to 1–5. The matching workshop must exist and be complete, and the hook returns success only after linking exactly that many concrete jobs into the workshop. It does not also insert a duplicate manager order, or report a manager record or missing `orders` script as completed enqueueing.
- `hook/designate_rect.lua` designates dig/channel rectangles or, with kind `chop`, designates the tree trunks inside the rect for felling (the same designation a player sets with d-t; woodcutters with an axe then fell them over real time). Rectangles are limited to 30×30 tiles. The dig/channel result reports `newly_designated` / `already_designated` / `non_wall_tiles` / `missing_tiles` counts so a re-designation of already-designated tiles is visibly a no-op (`newly_designated=0`); the chop result reports `trees_designated` / `already_designated` / `non_tree_tiles`. (The previous chop implementation invoked `autochop now`, which does not exist as a script on DFHack v0.47.05 — it was a silent no-op that still reported ok.)
- `hook/complete_dig_rect.lua` completes bounded dig designations by converting designated wall tiles to floor tiles. It is intentionally labeled as DFHack completion, not dwarf labor, and reports changed/skipped tiles as JSON. This helper is not part of gameplay scoring.
- `hook/build_construction.lua`, `hook/build_workshop.lua`, and
  `hook/place_furniture.lua` use existing items and create ordinary
  `ConstructBuilding` jobs. Placement fails closed on hidden, occupied, wet, or
  non-floor targets. This is intentionally a conservative dry/visible FLOOR
  subset of legal placement, not the full vanilla placement surface. Material
  selection requires the target and selected item to share one living
  citizen's current DF walk group; geometric proximity alone is not sufficient,
  and placement fails closed while DF is rebuilding path data. Successful
  responses verify that the resulting job is linked to the selected item. A
  mixed legal/illegal construction rectangle reports every applied and rejected
  tile as `partial_placement` and is not accepted as full command success.
- `hook/work_metrics.lua` reads bounded target-room progress for the default clean 5×5 starter room (`50,35,0` to `54,39,0`), plus the planned east connector (`55,37,0` to `57,37,0`) and workshop room (`58,35,0` to `62,39,0`). Scorecards use this to distinguish elapsed ticks, designations, actual tile completion, bounded utility/production starts, and visible fortress complexity. The room plan (`two_room_workshop`) is currently hardcoded.
- `hook/map_snapshot.lua` reads a bounded tile rectangle (max 64×64, single z-level) for the derived "Map Inspect" replay layer. Read-only; explicitly not gameplay proof.
- `hook/view_state.lua` reads the live DF viewport and cursor without mutating anything; `hook/restore_view_state.lua` writes them back. The runner wraps governed target discovery with this pair so helper probes preserve the live camera/cursor.
- `hook/prepare_keystroke_target.lua` searches for legal work/material/workshop targets near citizens (bounded search radii, 10s timeout). Read-only discovery; used by keystroke mode and (view-state-preserved) by governed mode.
- `hook/job_metrics.lua` reports crew/jobs, completed-stage furniture, farms,
  workshops, and raw dead-citizen facts without mutating game state. It also
  reports bounded active/queued job IDs and reactions with explicit truncation
  flags, planting/brewing job
  counts, raw brewable-plant and empty-barrel inventory, and each farm plot's
  raw outside/light/subterranean/water-table tile counts. Pending
  construction jobs include every assigned item's resolved position and current
  walk-group connectivity (`connected`, `disconnected`, or `unknown`). This is
  an engine connectivity snapshot, not a claim that a dwarf has accepted or can
  complete the haul; `unknown` is reported while path data is rebuilding or
  cannot be read.
- `hook/fort_metrics.lua` reports each detected space's factual bounds,
  furniture/workshop contents, and up to 16 currently open member tiles. These
  are read-only room-membership facts, not a room plan or placement target.
- `hook/g7_evidence.lua` owns a run-scoped DFHack event/eat-history ledger for
  cumulative food/drink production and consumption plus immediate death facts.

## Python Adapters

- `fort_gym.bench.dfhack_exec` provides helpers like `run_dfhack`, `run_lua_file`, `run_lua_expr`, `tick_read`, `set_paused`, and `read_game_state`, wrapping dfhack-run with tight timeouts and consistent `DFHackError` handling.
- `fort_gym.bench.dfhack_backend` exposes the bounded build, designation,
  order, labor, farm, observation, survival-ledger, and tick helpers. Each
  helper returns JSON-compatible dictionaries with an `ok` flag and `error`
  value if applicable.
- `read_game_state()` retrieves tick count, population, and stocks via CLI since RPC does not capture Lua print output.

## Runtime Guarantees

- API endpoints treat failure responses as no-ops and emit SSE `stderr` frames so frontends can surface the issue.
- Random agents default to a *safe* profile that only emits `noop`, small `DIG`, or whitelisted `ORDER` actions.
- Structured DFHack `DIG` actions designate tiles only by default. Set `FORT_GYM_DFHACK_COMPLETE_DIG=1` only for explicit harness-assisted debugging; completion from this path is not dwarf labor and is excluded from gameplay progress scoring.
- Structured DFHack `BUILD` actions allow the audited workshop, farm, furniture,
  wall, and floor kinds. For non-governed models these placements are
  DFHack-assisted state changes, not native gameplay proof, and are excluded
  from gameplay progress scoring.
- Gameplay progress scoring is reserved for provenance-eligible paths: `KEYSTROKE` runs that operate through the visible game surface and then observe resulting DF state, and governed runs (below).
- Assisted-progress zeroing is a run-level one-way gate: once a non-governed model has one accepted structured `DIG`/`BUILD`/`ORDER` on the dfhack backend, all assisted progress fields are zeroed AND the run's scoreable elapsed time stays blocked for the remainder of the run (`score_provenance = "gameplay_only_assisted_progress_zeroed"`).
- Models in `GOVERNED_DFHACK_MODELS` are the exception to the assisted-progress
  rule. Their eight bounded actions are tagged `dfhack_governed` and world
  actions may score only through observed live metrics. `INTERACT` requires an
  explicit zero ticks, a paused allowlisted viewscreen, and an enabled governed
  capability; it never earns progress credit. This path treats DFHack as a
  legal command transport, not as direct state mutation.
- Accepted `ORDER` and workshop-placement commands earn no utility by
  themselves. `carpenter_workshops_usable` requires a completed build stage;
  order IDs are acceptance evidence until a surviving job or causally
  attributable matching output is observed. Ambiguous older-job output and
  incomplete lifecycle reads fail closed.
- `INTERACT finish_topic_meeting` is additionally restricted to
  `viewscreen_topicmeetingst` and sends exactly one `OPTION1`, the live-verified
  semantic key only when the exact visible
  `a - Finish peeking in on conversation` choice is present. If that option
  remains after injection, the action is recorded as `interaction_no_effect`
  rather than success. It remains zero-tick, paused-only, and subject to the
  same modal budgets.
- Governed and keystroke runs record a real CopyScreen `screen_text` frame into every trace record for replay evidence; governed helper probes preserve/restore the live viewport via `view_state.lua`/`restore_view_state.lua`.
- `summary.json` includes a separate `rubric` section that judges legal evidence, repetition, production, layout breadth, and plan coherence over recent trace history. A high scalar score without broad legal progress should show rubric blockers.
- All scripts run from `/opt/dwarf-fortress`, ensuring relative includes resolve and dfhack resources remain available.

## Tick Advancement

The `advance_ticks_exact_external()` function handles tick advancement:

1. Enables `nopause 1` to prevent auto-pausing while the smoke check is running
2. Samples `df.global.cur_year_tick` to see whether the headless game is already moving
3. Attempts to unpause only if the tick clock is stalled
4. Polls `df.global.cur_year_tick` until the requested ticks elapse
5. Attempts to re-pause as best effort and reports whether the final pause state stuck

Timeout is set to `max(10000, ticks * 200)` ms to accommodate slow headless FPS (~5-10 ticks/second).
On the current `dfhack-host`, pause commands are not durable, so successful advancement is based on
the observed tick delta rather than the pause flag.

Caveat: if the tick clock stays stalled after `nopause` and unpause attempts, the helper falls back
to sending a space keystroke (`STRING_A032`) through the UI as a last resort, reported in the result
as `resume_fallback`. Tick advancement is therefore not strictly UI-free in that edge case.

For integration tests that exercise the live DFHack path, set `DFHACK_LIVE=1` before invoking `pytest -k actions_live`.
