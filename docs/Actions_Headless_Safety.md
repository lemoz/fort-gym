# DFHack Action Safety Guidelines

fort-gym executes DFHack actions exclusively through curated Lua helpers stored under `/opt/dwarf-fortress/hook`. Every command is invoked via `dfhack-run`, constrained to the loopback interface, and bounded to 2.5 seconds.

## CLI Wrappers

- `hook/order_make.lua` enqueues manager orders for a limited set of goods (`bed`, `door`, `table`, `chair`, `barrel`, `bin`). Quantities are clamped to 1–5 and the script returns JSON describing the outcome.
- `hook/designate_rect.lua` designates dig/channel rectangles or triggers a tree chop pulse. Rectangles are limited to 30×30 tiles.

## Python Adapters

- `fort_gym.bench.dfhack_exec` provides `run_dfhack` and `run_lua_file`, capturing stdout, timeout, and non-zero exit codes, and translating them into `DFHackError` exceptions.
- `fort_gym.bench.dfhack_backend` exposes high-level helpers `queue_manager_order` and `designate_rect`. Both functions return JSON-compatible dictionaries with an `ok` flag and `error` value if applicable.

## Runtime Guarantees

- API endpoints treat failure responses as no-ops and emit SSE `stderr` frames so frontends can surface the issue.
- Random agents default to a *safe* profile that only emits `noop`, small `DIG`, or whitelisted `ORDER` actions.
- All scripts run from `/opt/dwarf-fortress`, ensuring relative includes resolve and dfhack resources remain available.

For integration tests that exercise the live DFHack path, set `DFHACK_LIVE=1` before invoking `pytest -k actions_live`.
