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
