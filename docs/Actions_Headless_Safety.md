# DFHack Action Safety Guidelines

fort-gym executes DFHack actions exclusively through curated Lua helpers stored under `/opt/dwarf-fortress/hook`. Every command is invoked via `dfhack-run`, constrained to the loopback interface, and bounded to 2.5 seconds.

## CLI Wrappers

- `hook/order_make.lua` enqueues manager orders for a limited set of goods (`bed`, `door`, `table`, `chair`, `barrel`, `bin`). Quantities are clamped to 1–5 and the script returns JSON describing the outcome.
- `hook/designate_rect.lua` designates dig/channel rectangles or triggers a tree chop pulse. Rectangles are limited to 30×30 tiles.
- `hook/complete_dig_rect.lua` completes bounded dig designations by converting designated wall tiles to floor tiles. It is intentionally labeled as DFHack completion, not dwarf labor, and reports changed/skipped tiles as JSON. This helper is not part of gameplay scoring.
- `hook/build_workshop.lua` places a bounded 3×3 carpenter workshop in either the starter room or the planned workshop annex via DFHack building APIs and returns before/after workshop counts.
- `hook/work_metrics.lua` reads bounded target-room progress for the default clean 5×5 starter room (`50,35,0` to `54,39,0`), plus the planned east connector (`55,37,0` to `57,37,0`) and workshop room (`58,35,0` to `62,39,0`). Scorecards use this to distinguish elapsed ticks, designations, actual tile completion, bounded utility/production starts, and visible fortress complexity.

## Python Adapters

- `fort_gym.bench.dfhack_exec` provides helpers like `run_dfhack`, `run_lua_file`, `run_lua_expr`, `tick_read`, `set_paused`, and `read_game_state`, wrapping dfhack-run with tight timeouts and consistent `DFHackError` handling.
- `fort_gym.bench.dfhack_backend` exposes high-level helpers `queue_manager_order`, `build_workshop`, `designate_rect`, `complete_dig_rect`, `read_work_metrics`, and `advance_ticks_exact_external`. Each helper returns JSON-compatible dictionaries with an `ok` flag and `error` value if applicable.
- `read_game_state()` retrieves tick count, population, and stocks via CLI since RPC does not capture Lua print output.

## Runtime Guarantees

- API endpoints treat failure responses as no-ops and emit SSE `stderr` frames so frontends can surface the issue.
- Random agents default to a *safe* profile that only emits `noop`, small `DIG`, or whitelisted `ORDER` actions.
- Structured DFHack `DIG` actions designate tiles only by default. Set `FORT_GYM_DFHACK_COMPLETE_DIG=1` only for explicit harness-assisted debugging; completion from this path is not dwarf labor and is excluded from gameplay progress scoring.
- Structured DFHack `BUILD` actions currently allow only `CarpenterWorkshop` within the configured starter room or planned workshop annex. These placements are DFHack-assisted state changes, not native gameplay proof, and are excluded from gameplay progress scoring.
- Gameplay progress scoring is reserved for unassisted state changes, such as future `KEYSTROKE` runs that operate through the visible game surface and then observe resulting DF state.
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

For integration tests that exercise the live DFHack path, set `DFHACK_LIVE=1` before invoking `pytest -k actions_live`.
