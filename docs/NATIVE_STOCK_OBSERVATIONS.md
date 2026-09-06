# Native stock observations

## Drink units, not an assumed-fresh UI counter

A read-only check during `local-long-v2-qwen35-20260906-a` at year 30,
tick 67809 found **46 drink units in 11 native item records**, while
`ui.tasks.food.drink` still reported **60**. Every item type and drink stack
was readable. None of those drink items was removed or pending garbage collection.
The map was already paused; its calendar and pause state did not change.
This proves a disagreement with that counter, not a consumption-rate measurement
or an established explanation for the UI's update schedule.

The [versioned diagnostic](../experiments/evidence/native_drink_inventory_observation_20260906.json)
records the exact execution revision, native calendar, read-only acceptance,
and private audit hashes. Historical campaign traces remain unchanged.

## New reader semantics

`read_game_state` now scans `world.items.other.IN_PLAY` for `DRINK` items
and sums `stack_size` into `stocks.drink`. It excludes items marked `removed`
or `garbage_collect`. It does not change any flags, refresh UI counters, move
items, advance game time, or enable gameplay assistance.

This is a count of existing drink units, **not proof of ownership, reachability,
potability, available production inputs, production, or consumption**. Forbidden,
rotten and in-job unit counts are reported separately. Drinks inside containers
remain included; `in_inventory` is not an exclusion rule.

`stock_observations` carries versioned source/quality information through state
normalization and the general observation encoder:

- `drink.complete` distinguishes a full scan from a partial/unavailable one.
- `drink.units` exists only after a complete scan; `scanned_units` is explicitly
  the partial subtotal when any item type, stack/flags, or list read fails.
- Python emits `stocks.drink = null` for incomplete scans, never the old UI
  estimate or an invented zero. Empty but completely scanned inventory is zero.
- `drink.ui_estimate` retains the original UI counter for comparison.
- `food` remains sourced from UI counters with freshness explicitly unverified.

The change is part of the reader's source revision. New experiment conditions
must declare that revision; do not silently apply it to a resumed frozen run or
recompute old model scores with the new semantics. The separate campaign encoder
and quality summary in the integration branch must forward the metadata before
any new campaign uses the corrected reader.

## Acceptance boundaries

The actual candidate Lua was executed read-only against the separate original
DF 0.47.05 / DFHack 0.47.05-r8 map. It counted 60 units in 12 item records,
matching an independent native sum with no calendar/pause change. This validates
the candidate against native objects; it is not a rerun of the discrepant campaign,
a production deployment, or proof of a sustainable fortress.

Executable Lua engine-double tests cover multi-unit stacks, empty inventory,
container inventory, excluded items, flagged units, invalid sizes, type/flag/list
read failures, and absence of item mutations. Python tests cover normalization,
legacy payloads, and preservation of unknown values and source metadata.

Validation on the isolated main-based change: **1,082 tests passed, 5 skipped**;
115 targeted observation tests passed, including all 14 executable Lua scenarios.
Changed-file Ruff 0.15.21 passes. Targeted mypy passes for the scanner and native
reader. State normalization retains one existing mypy finding in its unchanged
workshop handling, reproduced on the base. Full-repository Ruff still reports
10 existing findings; mypy reports 470 errors in 28 files, so repository-wide
lint/type cleanliness is not claimed. A restricted full-test run could not bind
the quickstart test's ephemeral loopback port; the complete rerun with that
permission passed without changing or skipping the test.
