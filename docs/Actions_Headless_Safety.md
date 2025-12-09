# DFHack Action Safety Guidelines

fort-gym executes DFHack actions exclusively through curated Lua helpers stored under `/opt/dwarf-fortress/hook`. Every command is invoked via `dfhack-run`, constrained to the loopback interface, and bounded to 2.5 seconds.

## CLI Wrappers

- `hook/order_make.lua` enqueues manager orders for a limited set of goods (`bed`, `door`, `table`, `chair`, `barrel`, `bin`). Quantities are clamped to 1–5 and the script returns JSON describing the outcome.
- `hook/designate_rect.lua` designates dig/channel rectangles or triggers a tree chop pulse. Rectangles are limited to 30×30 tiles.

## Python Adapters

- `fort_gym.bench.dfhack_exec` provides helpers like `run_dfhack`, `run_lua_file`, `run_lua_expr`, `tick_read`, `set_paused`, and `read_game_state`, wrapping dfhack-run with tight timeouts and consistent `DFHackError` handling.
- `fort_gym.bench.dfhack_backend` exposes high-level helpers `queue_manager_order`, `designate_rect`, and `advance_ticks_exact_external`. Each helper returns JSON-compatible dictionaries with an `ok` flag and `error` value if applicable.
- `read_game_state()` retrieves tick count, population, and stocks via CLI since RPC does not capture Lua print output.

## Runtime Guarantees

- API endpoints treat failure responses as no-ops and emit SSE `stderr` frames so frontends can surface the issue.
- Random agents default to a *safe* profile that only emits `noop`, small `DIG`, or whitelisted `ORDER` actions.
- All scripts run from `/opt/dwarf-fortress`, ensuring relative includes resolve and dfhack resources remain available.

## Tick Advancement

The `advance_ticks_exact_external()` function handles tick advancement:

1. Enables `nopause 1` to prevent auto-pausing (required in headless mode)
2. Unpauses the game via `df.global.pause_state = false`
3. Polls `df.global.cur_year_tick` until the requested ticks elapse
4. Re-pauses the game

Timeout is set to `max(10000, ticks * 200)` ms to accommodate slow headless FPS (~5-10 ticks/second).

For integration tests that exercise the live DFHack path, set `DFHACK_LIVE=1` before invoking `pytest -k actions_live`.
