# Campaign brewing-input measurement correction

## Finding

The old campaign crew hook classified a `PLANT` item as brewable when its material
had `ALCOHOL_PLANT`. That flag belongs to the finished drink material, not the
structural plant ingredient. In the actual checkpoint-929 game raws, a plump
helmet's structural material declares `DRINK_MAT` as a reaction product; its
separate drink material uses `PLANT_ALCOHOL_TEMPLATE`, which carries the alcohol
flag. Therefore the old counter can report zero for a valid brewing ingredient.

DFHack's [item-information implementation](https://github.com/DFHack/scripts/blob/master/view-item-info.lua)
also distinguishes material reaction products and the plant's drink output from
the ingredient. The local retained game raws are the version-specific basis for
this bug finding, not an assumption that current upstream matches the runtime.

The original window-ab snapshots at checkpoints 929, 961 and 993 remain unchanged.
Their old brewing-input zero must not be used to conclude that no brewable plants
were present. This does not invalidate the separate drink-stack or raw-edible-food
measurements. Whether the fortress replenished its supplies requires separate
gameplay evidence; this correction alone is not a production or survival result.

## Corrected campaign-only reader

`hook/campaign_job_metrics_v1.lua` now versions its production-input subsection as
`fortgym.campaign-production-inputs/v2`. It identifies `PLANT` ingredients by a
`DRINK_MAT` reaction-product entry and reads the native `getStackSize()` method.
It reports unassigned plant stacks/units separately from stacks assigned to jobs.
The counts describe raw inventory, not ownership, reachability, kitchen settings,
successful assignment, or completed brewing. Barrel fields retain their older
semantics and are not covered by the plant-scan completeness flag.

An unreadable item type, material, reaction entry, assignment flag or stack size
invalidates the plant totals, with explicit completeness and failure counts.
Unavailable totals are omitted instead of being published as zero or a partial
total. Confirmed empty inventories and confirmed zero-sized stacks remain zero.
The code performs no item, job, inventory or world mutation.

The historical governed `hook/job_metrics.lua` is byte-for-byte unchanged.
The completed window-ab native worktree and image remain frozen on their original
source. The correction was developed in the project's registered
`campaign-brewing-inventory` worktree; it did not hot-patch the running game or
reclassify its immutable snapshots. Astra's native-keyboard condition sees the
game screen, not this crew diagnostic.

## Verification and native acceptance

Tests execute the exact production-input block from the shipped Lua hook using
material and item doubles. They reproduce the old false negative (brewable
structural material without an alcohol flag), reject the inverse false positive,
check assigned stacks, real stack-method use, known zero, unreadable fields and
safe integer overflow. Historical-hook hash tests remain required.

The September 10 provider-free check reopened a disposable copy of final checkpoint
1057 using source `1bc49b9675b1c82ad502bbd6d8461c9cdbf077e9`. The independent
native inventory scan found 69 brewable units in 34 unassigned plump-helmet stacks,
with no assigned plant stacks or read failures. All 34 plant records declared
`DRINK_MAT` reaction products and lacked the old `ALCOHOL_PLANT` flag, reproducing
the old false negative. The corrected campaign hook matched the direct scan.

The [later verification](../experiments/evidence/astra_native_keyboard_checkpoint1057_reload_20260910.json)
is pinned at `a542b0b732b2e59fe316b68d8140dd21bb9ecc39`. It added no model calls,
gameplay keys, ticks, saves or checkpoints. Original evidence stayed unchanged;
normal agent/history/usage continuation and full teardown passed. This closes the
native reader prerequisite for the matched pilot, not the separate question of
completed brewing or sustainable supply production.
