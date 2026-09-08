# Semantic native checkpoint maintenance

## Why the save profile changed

A provider-free reload of the latest retained save reached its expected paused
calendar and matched every recorded persistent observation. Fourteen job-path
connectivity fields changed to unknown while the native `reindex_pathfinding`
flag was true. The metrics code explicitly reports unknown in that state; no
pathfinding command or game tick was used to make the observations match.

The old save profile then reproduced its pixel-equality failure. The retained
captures show one changed tile between read-only pre-save captures, four across
saving, and three between read-only post-save captures. Native calendar, menu
stack and recorded world observations remained unchanged. Exact raster equality
is therefore not a valid checkpoint invariant for this paused display.

Independent audit verifies these observations and complete game/container/VM
teardown. No model calls, gameplay keys or ticks were requested. See
`experiments/evidence/astra_native_checkpoint_reload_20260908.json`. The previous
strict-observation diagnostic remains failed, and this diagnostic does not itself
create a recovered campaign checkpoint.

## New explicit profile

`native_menu_preserving_save/v2` keeps the same native save operation, zero keys,
zero requested ticks, stable copied inventory, restored menu objects and backup
preference. It additionally verifies unchanged focus, selected unit/building/job/
item identifiers, cursor and viewport coordinates, plus exact recorded world
observations before and after saving. Those are maintenance checks only and are
not supplied to the playing model.

Raw captures and both digests remain recorded. `screen_unchanged` is factual
telemetry and may be false; changed dimensions, semantic menu identity, calendar,
world observations or uncertain save completion still fail. No native save is
retried. The historical v1 profile retains its strict pixel check, and legacy
quicksave is unchanged. A window must explicitly select v2.

## Forward-only checkpoint recovery

The new settled-checkpoint recovery path verifies a complete committed trace,
fully accounted journal, model memory/configuration, inherited discontinuity and
the copied newer native files. It requires fresh native reload with the expected
calendar and persistent observations. Only documented connectivity-to-unknown
transitions under an observed native pending-reindex flag are permitted; the
changed fields remain inspectable rather than silently dropped.

Recovery creates a new checkpoint from the latest state without replaying an
action, calling a model, adding a trace row, resetting usage or adding another
loss boundary. Original failed evidence stays unchanged. The previous clock and
input-rejection recovery protocols are not repurposed for this settled case.
Offline tests and the reload diagnostic are not proof that native recovery has
completed; that requires its own verified checkpoint and fresh reload.

## Verified native recovery

The provider-free native run on source `2a158ae19d2bd6dcfdd1a4bb0013e6c8d42ad57f`
created checkpoint 216 (`36142c131e444003dd8dc7616f330800946566ab614d2f7509b32bbda8f4bca3`)
and verified it in a second native process. The independent audit confirms
47,200 retained elapsed ticks, byte-identical trace and usage journals, unchanged
model memory, all 232 responses and 7,706,555 campaign tokens. All-attempt usage,
including historical failed deliveries, remains 7,775,559 tokens. Subscription
charges are unreported, not zero.

The semantic save check passed despite changed screen pixels. There were zero
model calls, gameplay keys, requested ticks or new discontinuities. Both native
processes, the container and the disposable local VM were stopped and verified.
The original failed window and the earlier 2,000-tick lost branch remain
unchanged. This is recovered infrastructure continuity, not new gameplay or
proof of a functioning fortress. The authored public record is
`experiments/evidence/astra_native_keyboard_settled_recovery_20260908.json`.

## Later unit-selection helper discrepancy

Window g subsequently reached trace cursor 232 / 49,200 ticks and rejected a
changed menu identity while saving. Checkpoint 216 remains the latest verified
campaign checkpoint. All 248 responses and 8,150,227 campaign tokens are retained;
the newer native files have now passed a provider-free reload, but no recovered
checkpoint 232 has been created.

Two independently audited native diagnostics narrow the failed check to
`unit_id`. The selected-unit helper reports no unit inside the save RPC after
saving, while the unit screen's own unit reference, actual screen pixels, menu
stack, world observations and calendar remain unchanged. A separate later RPC
returns the same selected unit as the direct screen reference again. This is a
transient helper-observation inconsistency in the reproduced menu, not a changed
selected dwarf. The original failed operation did not retain its raw receipt;
these are separate reproduced observations, not retroactively invented evidence.

The pinned DFHack implementation reads `getSelectedUnit` through
`Core::getTopViewscreen`, while `getAnyUnit` can read the unit screen directly:
[Gui.cpp](https://github.com/DFHack/dfhack/blob/0.47.05-r8/library/modules/Gui.cpp#L847),
[Core.h](https://github.com/DFHack/dfhack/blob/0.47.05-r8/library/include/Core.h#L177).
That supports investigating the helper's screen-state boundary; it does not prove
every possible native menu behaves identically.

Each successful diagnostic used nine menu-navigation keys, no model call, no
save key and no requested game tick. Input evidence was read-only and unchanged;
all native/container/VM teardown passed. The earlier fixture failed before menu
input on a wrong method name and remains failed. The instrumented diagnostic
deliberately added a private observer field that the original strict receipt
schema rejected; it is not save-profile acceptance.

Next implementation: verify the selected UI state outside the save RPC's
transient helper state, binding the second read to the same paused calendar,
runtime and native screen stack. Preserve the inline receipt and existing world
checks. Then recover cursor 232 forward from the retained runtime save, keeping
all memory, usage and inherited loss history. The correction and recovered
checkpoint remain unimplemented at this record. Authored diagnostic evidence:
`experiments/evidence/astra_native_menu_identity_diagnostic_20260908.json`.

## Separate-RPC identity profile candidate

`native_menu_preserving_save/v3` now adds read-only identity probes immediately
before and after the save RPC. Each probe must identify the same paused runtime,
save calendar and exact native screen-object stack as the save operation. Their
full UI identities must agree with one another and the inline pre-save identity.
The inline post-save helper reading stays retained as diagnostic evidence, but
the settled post-RPC reading is the final identity invariant. Missing, malformed,
changed or unbound probes fail; there is no fallback or save retry.

The save operation, world-observation check, copied-file inventory and input/tick
policy are unchanged. Historical v1/v2 profiles and windows are unchanged. A
window must explicitly select v3. Offline tests do not establish native acceptance
or recover checkpoint 232; both remain separate required checks at this point.

The provider-free native acceptance on source
`adc2aeafcceba1159cb0c624f3c68318846ab398` subsequently passed: v3 saved the
reproduced unit-labor menu, preserved settled identity and world state, and a
second process reloaded the resulting native save with matching observations.
The inline helper discrepancy remained visible. The independent audit verified
all copied files, original evidence preservation and complete teardown. Nine
menu-only setup keys, zero model calls and zero requested game ticks were used.
This establishes the save correction, not a recovered campaign checkpoint.

Recovery now also supports an explicitly selected `retained_runtime_save/v1`
source, identified by a v2 recovery plan. It validates the original semantic
failure and world observations, binds the declared window and entire retained
runtime inventory, then uses the same fresh-load and history-preservation checks.
The original copied-snapshot recovery plan and results remain unchanged. Native
checkpoint-232 recovery remains pending until its own acceptance run completes.
