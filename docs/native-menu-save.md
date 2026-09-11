# Menu-preserving native checkpoints

The optional window setting `snapshot_profile: native_menu_preserving_save/v1`
selects checkpoint maintenance for the version-matched DF 0.47.05 runtime.
Omitted settings retain historical `native_quicksave/v1` behavior. Existing
experiment files and their executed conditions are unchanged.

The helper verifies the expected runtime and paused fortress, temporarily hides
the same native menu objects using DFHack's `hideGuard`, sets the autosave flag,
and calls the paused fortress screen's native logic once to process the save.
It restores the original menu stack and backup preference even on Lua failure.
It sends no keyboard events, does not unpause, and does not edit world counters
or orders. It is not exposed to the playing model.

A successful checkpoint requires a structured operational receipt, identical
native calendar and save identity, exact menu stack restoration, unchanged raw
screen capture, completed native save flag, changed world-save signature, and
a stable copied file inventory. The checkpoint retains the receipt and screen
digest. Unknown completion or RPC failure is not retried; copied partial output
is forensic only, not an accepted checkpoint. Reloading DF still resets its UI:
this profile preserves menus during saving, not across process restarts.

## Evidence and current limitation

A provider-free diagnostic on source `4802a234a415c5a4acae17453bd2e7105533fefa`
saved and freshly reloaded a unit-menu case and a normal-quicksave control.
Both preserved exact before/after-save observations and screens, with zero save
keys and ticks. Independently reviewed JSON world observations matched after
reload in both cases and between cases. The initial apparent `map_bounds`
difference was a Python tuple versus its JSON list, not different values.
This covers recorded observer fields, not every internal native world object.
All four game processes, the container and isolated local VM were stopped.

The committed production helper at `693f1c4ccf12050f1cfa48b5a3144a4d37da3b99`
subsequently passed save and fresh reload in the nested unit menu and normal
fortress view. Independent audit verifies both cases, stable inventories,
unchanged screens and observer fields, zero snapshot keys/ticks, and all five
native-process cleanups plus container/VM teardown. A third build-menu fixture
used an invalid diagnostic key and stopped before a save; it is untested, not
a helper failure or a passed case. The whole fixture remains failed. See
`experiments/evidence/astra_native_menu_save_20260907.json` for the scoped result.

The source passed 80 focused checks and exact-source
[CI](https://github.com/lemoz/fort-gym/actions/runs/34171215489).
A broader local pass ran 2,476 tests successfully with ten skips; its sole
sandbox-denied localhost test passed separately, and final boundary-type edits
passed the focused run. Changed modules pass Ruff and scoped mypy.

No model calls were made by those diagnostics. The historical checkpoint-200 timeout and unsaved
16-decision tail remain failed and retained; this fix does not recover them or
authorize a silent rewind. The historical durable parent was checkpoint 184.
The corrected build-menu check subsequently passed on source `60c5a3eee` using
the catalog's `D_BUILDING` key. Its two native processes, container and local VM
were stopped. See `experiments/evidence/astra_native_build_menu_save_20260907.json`.
No old failure is reclassified. The local VM's data-disk allowance was expanded
from 10 to 16 GiB to preserve evidence; no other VM configuration changed.

[Window e](native-save-loss-restart.md) subsequently completed an independently
audited loss-aware restart with 16 new accepted Astra decisions and a verified
new-branch checkpoint 200. It is not recovery of the old unsaved tail. The new
save retains the snapshot receipt and unchanged screen, with zero save keys or
ticks. All game/container/VM teardown is verified; see the linked result for
retained time, complete usage and the declared next continuation.

The subsequent window f failed screen equality after making a changed save copy.
The copy matches the stopped runtime, but reload/reconciliation is still required.
The latest implementation retains private before/after screens, a completed Lua
receipt and copied-save metadata on failure. It preserves the original failure
and sends no retries; the screen-change cause remains unproven. See the window
result above before choosing a new gameplay run.

Primary implementation references: bundled DFHack 0.47.05-r8 `quicksave.lua`,
[quicksave documentation](https://docs.dfhack.org/en/0.47.05-r8/docs/tools/quicksave.html),
and the version-matched
[Lua screen API](https://docs.dfhack.org/en/0.47.05-r8/docs/dev/Lua%20API.html).
