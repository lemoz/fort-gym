# DFHack Action Safety Guidelines

fort-gym executes DFHack actions exclusively through curated Lua helpers stored under `/opt/dwarf-fortress/hook`. Every command is invoked via `dfhack-run`, constrained to the loopback interface, and bounded to 2.5 seconds.

## CLI Wrappers

- `hook/order_make.lua` enqueues real jobs for a limited set of goods (`bed`, `door`, `table`, `chair`, `barrel`, `bin`, `brew`). Quantities are clamped to 1–5. The matching workshop must exist and be complete, and the hook returns success only after linking exactly that many concrete jobs into the workshop. It does not also insert a duplicate manager order, or report a manager record or missing `orders` script as completed enqueueing.
- `hook/designate_rect.lua` designates bounded dig/channel rectangles or,
  with kind `chop`, the tree trunks inside the rect for felling (the same work
  designations a player issues). Rectangles are limited to 30×30 tiles on one
  z-level. `dig` accepts visible natural walls; `channel` accepts visible
  natural walls or stable floors. Occupied, constructed, wet, frozen, hidden,
  tree, root, pool, river, lava-stone, magma, HFS, underworld-gate, unverified
  feature, and otherwise ineligible tiles fail closed. The entire rectangle is
  preflighted, written transactionally, and reread; a write/readback failure
  rolls every designation and block flag back. Chop and gather use the same
  preflight/commit/readback/verified-rollback contract. Building collisions are
  checked by scanning `buildings.all` directly, independent of the stale-zero
  occupancy shortcut in DFHack 0.47.05. Results separate
  `newly_designated`, `already_designated`, `ineligible_tiles`, and
  `missing_tiles`; neither helper completes mining. Chop separately
  reports `trees_designated` / `already_designated` / `non_tree_tiles`. (The
  previous chop implementation invoked `autochop now`, which does not exist as
  a script on DFHack v0.47.05 — it was a silent no-op that still reported ok.)
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
- `hook/build_farm_plot.lua` accepts only visible, dry, unoccupied native
  soil/grass floors. Stone, constructed, hidden, frozen, wet, unreadable, and
  occupied tiles fail before `constructBuilding`; muddy stone is unsupported
  until separately proven. Its collision check also scans native building
  footprints directly instead of trusting `findAtTile` after a stale occupancy
  bit.
- `hook/set_farm_crop.lua` preflights usable seed stock, season, underground
  depth, and the subterranean-water biome before changing any requested season
  slot. Every requested season must offer the crop or the action is a no-op.
  Surface crop selection fails closed until native surface-biome options are
  proven. All four `plant_id` slots are snapshotted, committed under `pcall`,
  reread from DF, and rolled back together on any write/readback mismatch.
- `hook/work_metrics.lua` retains its bounded legacy target mode for keystroke
  evaluation. Governed runs call its `global` mode, which emits only factual
  job, workshop, labor, and manager-order counters and never scans or emits the
  retired starter, connector, workshop-room, or two-room plan geometry.
- `hook/map_snapshot.lua` reads a bounded tile rectangle (max 64×64, single
  z-level) for the derived "Map Inspect" replay layer. A display snapshot is
  not gameplay proof by itself, and hidden tiles serialize no underlying
  tiletype, shape, material, designation, or building facts. Governed scoring separately compares the exact
  model-authored `DIG` footprint and retains ownership only for observed new
  designations/completions in that footprint.
- `hook/view_state.lua` reads the live DF viewport and cursor without mutating anything; `hook/restore_view_state.lua` writes them back for UI tooling.
- `hook/prepare_keystroke_target.lua` searches for legal work/material/workshop targets near citizens (bounded search radii, 10s timeout). It is a keystroke-mode scaffold only and is never called by governed runs.
- `hook/job_metrics.lua` reports crew/jobs, completed-stage furniture, farms,
  workshops, and raw dead-citizen facts without mutating game state. It also
  reports bounded active/queued job IDs and reactions with explicit truncation
  flags, planting/brewing job
  counts, raw brewable-plant and empty-barrel inventory, and each farm plot's
  raw outside/light/subterranean/water-table tile counts plus per-season
  underground crop options derived from usable seeds and native raw/depth
  constraints. `crop_options_complete=true` means both scans succeeded and all
  eligible options fit the bounded output. A failed scan or a thirteenth option
  makes the result incomplete and suppresses every partial option list; false
  means unavailable/unknown, not "no crops." Pending
  construction jobs include every assigned item's resolved position and current
  walk-group connectivity (`connected`, `disconnected`, or `unknown`). This is
  an engine connectivity snapshot, not a claim that a dwarf has accepted or can
  complete the haul; `unknown` is reported while path data is rebuilding or
  cannot be read.
- `hook/fort_metrics.lua` reports each detected space's factual bounds,
  furniture/workshop contents, and up to 16 currently open member tiles. These
  are read-only room-membership facts, not a room plan or placement target. It
  also reports bounded raw maps around one channel tile whose new designation
  was observed immediately after the model's paused write. Access completion is
  confined to that exact owned tile:
  completed top/lower geometry, a local ramp-step predicate matching DFHack
  0.47.05, and native `canWalkBetween` for the specific endpoints and a citizen.
  No general fort-wide stair/ramp coordinate list or fort-wide
  `citizens_below` count is emitted as proof. Hidden tiles are treated as opaque
  leaks before tiletype/material reads, so hidden walls cannot close a scored
  room flood.
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
- Structured DFHack `DIG` actions designate tiles only by default. Set
  `FORT_GYM_DFHACK_COMPLETE_DIG=1` only for explicit non-governed harness
  debugging. Governed startup fails before connecting when this flag is set,
  and the executor independently disables the completion path for governed
  runs. The administrative `/step` endpoint rejects governed models entirely
  before opening a DFHack client; non-governed administrative steps still
  disable assisted completion.
- Structured DFHack `BUILD` actions allow the audited workshop, farm, furniture,
  wall, and floor kinds. For non-governed models these placements are
  DFHack-assisted state changes, not native gameplay proof, and are excluded
  from gameplay progress scoring.
- Gameplay progress scoring is reserved for provenance-eligible paths: `KEYSTROKE` runs that operate through the visible game surface and then observe resulting DF state, and governed runs (below).
- Assisted-progress zeroing is a run-level one-way gate: once a non-governed model has one accepted structured `DIG`/`BUILD`/`ORDER` on the dfhack backend, all assisted progress fields are zeroed AND the run's scoreable elapsed time stays blocked for the remainder of the run (`score_provenance = "gameplay_only_assisted_progress_zeroed"`).
- Models in `GOVERNED_DFHACK_MODELS` are the exception to the assisted-progress
  rule. Their eight bounded actions are tagged `dfhack_governed` and world
  actions may score only through observed live metrics. A `DIG` designation
  establishes model ownership but pays no scalar work/completion credit; those
  fields rise only when an owned tile is later observed as a native completed
  dig floor or channel ramp top. Ownership is captured before any requested
  ticks, while DF is paused; unfinished owned coordinates are then reread in
  bounded map buckets independent of the replay/camera window. Raw global dig/job counters remain audit
  telemetry and cannot inflate the governed work/completion scalar. `INTERACT` requires an
  explicit zero ticks, a paused allowlisted viewscreen, and an enabled governed
  capability; it never earns progress credit. This path treats DFHack as a
  legal command transport, not as direct state mutation.
- Governed workshop/farm ownership is keyed by the exact `building_id` returned
  by an accepted BUILD. Only a later native completed-stage record for that ID
  and authored kind, with `stage_read_ok=true`, numeric stage/max values, and
  `max_stage > 0`, can unlock duration; only completed owned Carpenter workshops feed the
  existing utility/production capacity score. Global goods, output, workshop,
  room, construction, and furniture deltas stay visible as audit telemetry but
  cannot feed governed utility/production/complexity without exact ownership.
- A governed helper response with `rollback_verified=false` is terminal. The
  runner advances zero ticks, records `governed_rollback_unverified`, cleans up,
  and refuses to publish a successful run. Explicit top-level or per-target
  `error=rollback_failed` is equivalent, so an omitted flag cannot fail open.
- Accepted `ORDER` and workshop-placement commands earn no utility by
  themselves. `carpenter_workshops_usable` requires a completed build stage;
  order IDs, matching output counters, and run-scoped drink/food deltas remain
  audit evidence because the current surface cannot link an output item to one
  exact order job. Ambiguous or incomplete lifecycle reads fail closed.
- `INTERACT finish_topic_meeting` is additionally restricted to
  `viewscreen_topicmeetingst` and sends exactly one `OPTION1`, the live-verified
  semantic key only when the exact visible
  `a - Finish peeking in on conversation` choice is present. If that option
  remains after injection, the action is recorded as `interaction_no_effect`
  rather than success. It remains zero-tick, paused-only, and subject to the
  same modal budgets.
- Governed and keystroke runs record a real CopyScreen `screen_text` frame into every trace record for replay evidence; governed helper probes preserve/restore the live viewport via `view_state.lua`/`restore_view_state.lua`.
- `summary.json` includes a separate `rubric` section that judges legal evidence, repetition, production, layout breadth, and plan coherence over recent trace history. A high scalar score without broad legal progress should show rubric blockers.
- Governed summary and rubric reaggregation require the action-owned v2 marker.
  The summary also requires a boolean `score_duration_blocked` on every row.
  Rubric progress, production, and blocker clearance use owned fields only;
  global rooms and constructions remain audit telemetry until exact ownership
  exists. Unowned world changes during WAIT are concurrent evidence, not
  responsiveness credit.
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
