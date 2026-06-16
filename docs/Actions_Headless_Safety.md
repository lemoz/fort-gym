# DFHack Action Safety Guidelines

fort-gym executes DFHack actions exclusively through curated Lua helpers stored under `/opt/dwarf-fortress/hook`. Every command is invoked via `dfhack-run`, constrained to the loopback interface, and bounded to 2.5 seconds.

## CLI Wrappers

- `hook/order_make.lua` enqueues manager orders for a limited set of goods (`bed`, `door`, `table`, `chair`, `barrel`, `bin`). Quantities are clamped to 1–5 and the script returns JSON describing the outcome.
- `hook/designate_rect.lua` designates dig/channel rectangles or triggers a tree chop pulse. Rectangles are limited to 30×30 tiles.
- `hook/complete_dig_rect.lua` completes bounded dig designations by converting designated wall tiles to floor tiles. It is intentionally labeled as DFHack completion, not dwarf labor, and reports changed/skipped tiles as JSON.
- `hook/work_metrics.lua` reads bounded target-room progress for the default clean 5×5 starter room (`50,35,0` to `54,39,0`), including dig designations, opened floor/wall deltas, hidden target tiles, target/citizen z-level diagnostics, active dig jobs, manager-order counts, and carpenter-workshop counts. Scorecards use this to distinguish elapsed ticks, designations, actual tile completion, and bounded utility-work starts.

## Python Adapters

- `fort_gym.bench.dfhack_exec` provides helpers like `run_dfhack`, `run_lua_file`, `run_lua_expr`, `tick_read`, `set_paused`, and `read_game_state`, wrapping dfhack-run with tight timeouts and consistent `DFHackError` handling.
- `fort_gym.bench.dfhack_backend` exposes high-level helpers `queue_manager_order`, `designate_rect`, `complete_dig_rect`, `read_work_metrics`, and `advance_ticks_exact_external`. Each helper returns JSON-compatible dictionaries with an `ok` flag and `error` value if applicable.
- `read_game_state()` retrieves tick count, population, and stocks via CLI since RPC does not capture Lua print output.

## Runtime Guarantees

- API endpoints treat failure responses as no-ops and emit SSE `stderr` frames so frontends can surface the issue.
- Random agents default to a *safe* profile that only emits `noop`, small `DIG`, or whitelisted `ORDER` actions.
- Structured DFHack `DIG` actions call `complete_dig_rect` by default after designation so live scorecards can prove tile completion in headless saves. Set `FORT_GYM_DFHACK_COMPLETE_DIG=0` to measure designation-only behavior.
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
