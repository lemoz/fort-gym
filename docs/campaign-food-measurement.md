# Campaign food measurement

## Current proof state

The keyboard campaign's food stock is unknown, not zero. Its current native
observation copies `ui.tasks.food` counters but explicitly marks their freshness
unverified. The descriptive evaluator correctly leaves those values out of
verified food totals. The existing drink measurement scans native item units;
neither a rising drink count nor a completed farm establishes production or
sustainability.

The isolated `food_inventory.py` candidate now provides a read-only native scan
and strict result validator. It is **not connected** to campaign observations,
the model prompt, the evaluator, the website, or the historical G7 hooks. This
separation lets the current Astra continuation stay frozen while measurement is
developed. A separate provider-free native check has now passed on checkpoint
567, alongside independent retained-evidence reconciliation. This is one
checkpoint's inventory evidence, not integration or sustainability acceptance.

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

Next, integrate a declared private measurement profile without expanding the
playing model's screen-only observations, and test continuation and failure
behavior. Do not rewrite historical `food_stock: null` results. Prepared-meal
native coverage and longitudinal production/consumption measurement remain open.

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
