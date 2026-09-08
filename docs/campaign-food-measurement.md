# Campaign food measurement

## Current proof state

Historical keyboard campaign food stock is unknown, not zero. The native
observation copies `ui.tasks.food` counters but explicitly marks their freshness
unverified. The descriptive evaluator correctly leaves those values out of
verified food totals. The existing drink measurement scans native item units;
neither a rising drink count nor a completed farm establishes production or
sustainability.

The `food_inventory.py` collector provides a read-only native scan and strict
result validator. Its optional campaign adapter now retains the result as
private evaluation data, without putting it in the playing model's prompt.
Historical G7 hooks and UI estimates remain unchanged. A separate provider-free
native check passed on checkpoint
567, alongside independent retained-evidence reconciliation. The following
integrated window n also completed: all 65 observation boundaries had complete
readings, from 27 initial to 82 final native-predicate units. The final count
matched the saved state, and independent save/usage/measurement audit and full
teardown passed. This is inventory integration evidence, not sustainability.

The `fortgym.campaign-food-measurement/v1` window setting opts into the adapter.
Omitting it preserves existing behavior and issues no new measurement RPC.
Each reading binds the loaded paused runtime, save and calendar around the scan;
the evaluator requires matching calendar and validated complete inventory before
reporting units. Missing, stale or partial readings remain unknown. The original
`stocks.food` UI estimate is not overwritten. Completed window n kept
the model, native keys, screen-only observations, memory and cumulative limits.
It is a continuation with new private measurement coverage, not a comparable
independent trial or a retroactive update to earlier results.

## Exact candidate definition

Use `world.items.other.IN_PLAY`, exclude removed/garbage-collected items and the
DRINK type, and count stack units only when the native `isEdibleRaw(0)` query
returns true. Use `getStackSize()` rather than assuming every candidate has the
same concrete item fields. The argument is deliberately recorded as literal
zero; no unverified interpretation of hunger thresholds or dwarf preference is
attached to it. This is a versioned native predicate count, not a claim that every
dwarf can or will eat every counted unit.

The methods and argument type were checked in the DFHack 0.47.05-r8 data-structure
submodule, pinned to
[`afe7e908e9e7e863412e8983f9feb2b999fae498`](https://github.com/DFHack/df-structures/blob/afe7e908e9e7e863412e8983f9feb2b999fae498/df.items.xml).
The release's scripts submodule is
[`4138a8c4fa2f569128433b6675de100ded6e2ee4`](https://github.com/DFHack/scripts/tree/4138a8c4fa2f569128433b6675de100ded6e2ee4).
The locally retained version's `gui/dfstatus.lua` uses the stack-size query for
prepared meals, but prepared meals are not the whole food supply.

Keep these distinctions visible:

- `units` is a complete native-predicate count or explicit unknown. A partial
  scan never publishes its partial sum as the total.
- `scanned_units` is diagnostic partial evidence, not a substitute total.
- Removed and garbage-collected records are counted as exclusions, not food.
- Duplicate identities, unreadable lists/items, non-boolean predicates/flags and
  invalid or overflowing counts invalidate completeness. They cannot become
  successful empty scans.
- Forbidden, rotten, job-held, trader and hidden unit counts are separate,
  potentially overlapping annotations. Do not add them and subtract the result
  from inventory, or call the remainder accessible food.
- No item IDs, positions, native captures or raw content are included in the
  validated aggregate projection. Extra source fields are discarded.
- No item flags, job queues, menu state, UI refresh, clock or global callback
  registration is changed by the collector.

## Validation completed

The actual candidate Lua executes against controlled engine doubles. Tests cover
empty and zero-unit inventories, mixed food/nonfood/drink records, excluded and
duplicate items, virtual stack sizes, overlapping flags, partial list/item reads,
unreadable predicates, unsafe counters and non-mutation. Python validation checks
the exact provenance, all counter types and totals, completeness, explicit unknowns
and removal of extra content. All 141 candidate tests passed; the combined food,
drink and campaign-profile selection passed 180 tests. Scoped Ruff/mypy passed.

## Native check completed on checkpoint 567

Frozen candidate source `ab53e54dd321b596b0f189cadf94cbbda65dfd95` was tested
after window m and its teardown. A fresh native process loaded verified
checkpoint 567, remained paused, and measured **27 native-predicate units across
15 item records**, from 1,537 in-play records. An independent enumeration through
the all-items vector agreed with the in-play scan, and concrete stack sizes
agreed with the virtual stack-size results for counted foods. A repeated scan
agreed. One unit had the in-job flag; forbidden, rotten, trader and hidden unit
counts were zero. These flags do not establish accessibility.

Calendar, native menu identity, actual 120x40 screen and copied world-save files
were unchanged across the reads; the query event log was excluded from world-file
comparison. The original checkpoint was reverified unchanged. No model calls,
gameplay keys, clock ticks, new native save or strategy intervention were made.
Native process/listener, container and VM teardown all verified.

The raw-food cases present at this checkpoint exercised the actual native
predicate. No prepared-meal item was present, so this probe does **not** add native
prepared-meal coverage. The UI estimate was 28 in the preceding gameplay record;
that difference does not establish the cause or meaning of either counter.
The published aggregate is
[`food_inventory_native_20260908.json`](../experiments/evidence/food_inventory_native_20260908.json).
Raw inventory details, screens, saves and the independent audit remain private.

The optional private measurement adapter was exercised in completed window n,
with tests for native-read failure, malformed/stale/partial counts,
unchanged defaults, worker wiring, and absence from model inputs and feedback.
The native run used frozen source `567251e7414795d52c87e1450eca146bfb419069`.
It completed 64 accepted decisions and added 21,200 ticks, saving checkpoint 631
with 143,400 retained ticks. Native-predicate food units increased 27 to 82,
drinks changed 181 to 179, and twelve dwarves remained alive. Completed farms,
beds and workshops increased from five/four/three to seven/five/four. These are
observed changes, not production attribution. Final functional-room measurement
is unknown. The model requests retained only the declared screen/memory/control
feedback contract. There were zero unknown food readings in this window; partial
and unavailable synthetic coverage cases remain explicitly unknown in the audit.
The authored aggregate is
[`astra_native_keyboard_food_continuation_20260908.json`](../experiments/evidence/astra_native_keyboard_food_continuation_20260908.json).
The optional measurement remains enabled in declared next window o, whose native
process must verify fresh loading of checkpoint 631 before another model call.
Do not rewrite historical `food_stock: null` results. Prepared-meal native
coverage and longitudinal production/consumption measurement remain open.

## Production and consumption remain separate work

The old `g7_evidence.lua` is a run-scoped global callback ledger. Starting it would
reset that ledger, not preserve campaign-wide flow through checkpoint reloads.
Its item-created records count units; its citizen eating-history differences
count events. These quantities cannot be silently compared as matching units.
Do not start or modify that historical hook to fill the campaign's missing fields.

A campaign flow measurement needs its own versioned identity and persisted
coverage across saves/reloads, deduplicated native events, explicit callback or
history gaps, and separate units for creation and eating/drinking events.
Item creation, import, splitting or relocation must not automatically become
fortress production. Attribute output to supported native production evidence,
retain unclassified changes, and measure availability separately from existence.
Only then can longitudinal evidence support food replenishment and sustainability
claims for the year-two goal. This candidate inventory alone cannot do so.
