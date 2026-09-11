# Model-controlled terrain inspection

The opt-in pair `campaign_action/v2` and `campaign_state/v3` adds a read-only
`VIEW` action. The model chooses `origin:[x,y,z]` and `size:[width,height]`;
width and height are 1-34 tiles and `advance_ticks` must be exactly zero.
Any region inside the loaded map may be selected, including other z-levels.
The harness does not choose a location, clamp coordinates or move the view toward
a target. Out-of-map requests receive rejection feedback and keep the prior view.

The ordinary fort-centered overview remains available. A separate `map_view`
observation contains the selected rectangle, native dimensions, terrain rows,
visibility/completeness counts and the paused native calendar. The selected view
persists across actions and is digest-bound in the checkpoint's runner state.
Continuation restores that selection before the next model decision, without
replaying a VIEW, changing its configuration or resetting accounted usage.

The native hook reads terrain only: no units, buildings, items or pathfinding
claims. Hidden tiles are checked before reading their type, material or liquid
detail. Hidden or unreadable tiles are blank; unreadable tiles make the scan
incomplete. No game block is allocated, fog revealed, native camera moved,
dialog dismissed, dwarf relocated, world command dispatched or time advanced.
VIEW can inspect a loaded paused map while a meeting is open, but it does not
handle the meeting for the model. The same decision/token budgets still apply.

The hook uses the documented `getTileSize` and `getTileBlock` APIs.
`getSize` would return blocks rather than tile dimensions.
[DFHack 0.47 Lua map API](https://docs.dfhack.org/en/0.47.05-r7/docs/Lua%20API.html#maps-module).
Python binds successful read receipts to the exact selected rectangle and
paused calendar, retaining unknowns and rejecting inconsistent dimensions,
rows or completeness counts. An inconsistent native map receipt is classified
as a runtime failure, not fortress collapse or a model's invalid gameplay choice.
If a world command has already advanced time, its tick receipt remains in the
failure journal even if the subsequent map observation fails.

## Model adapters and historical conditions

The new pair is supported by the existing hosted and local adapters. The typed
local response schema includes VIEW with strict integer coordinates and zero
ticks. The new campaign text decoder recognizes VIEW without discarding it in
favor of a later old-style action. Prompt packing retains the current selected
view and native facts. The v3 observation also retains the elapsed campaign clock
introduced by v2.

Historical action parsers, benchmark hooks, v1/v2 observation content and existing
experiment configurations are unchanged. Legacy campaign profiles never query
this hook or gain VIEW. Action/observation pairs are validated together and
checkpoint configuration identity prevents silently switching an old run to the
new interface.

## Experiment hypothesis and remaining proof

The previous campaign used a fort-anchored map with no model-selected region or
z-level inspection control. This interface makes looking
around an explicit model decision. The hypothesis is that controllable spatial
inspection, together with factual elapsed time and recoverable dialog feedback,
supports more effective development than the prior restricted observation.
That hypothesis has not been tested in a new native/model run.

Offline checks execute the shipped Lua against engine doubles, exercise the
native Python adapter, and pass model-selected VIEW through actual hosted/local
policy adapters with fake responses. They cover hidden reads, unknown tiles,
map edges, z selection, zero ticks, rejection, checkpoint resume, output pause,
usage preservation and historical compatibility. These are not real native
acceptance, model-performance or year-two fortress evidence.

## Native acceptance and next model condition

The provider-free native check is complete. The original fixture and its
instrumented diagnostic remain failed. The diagnostic isolated changing rendered
glyphs during a control read with no action, while native invariants were unchanged.
The corrected fixture therefore verifies the native calendar, pause state, camera,
allocated blocks and viewscreen type, retaining rendered differences as diagnostics
instead of asserting byte-identical animated rendering.

The corrected fixture passed region/z selection, hidden-tile handling, rejected
region feedback and selection persistence through an actual native checkpoint,
game-process stop and fresh-process reload. An independent read-only audit verified
the retained checkpoint, trace prefix, usage, original seed and completed teardown.
No model chose these actions. This does not establish live dialog inspection or
better gameplay. See the [operational outcome summary](../experiments/evidence/local_native_map_inspection_outcomes_20260907.json).
Captured maps, screens, coordinates, saves and detailed game-state result payloads
remain local; only code, declarations and non-content test outcomes are published.

The next [fresh local condition](../experiments/campaigns/local_native_qwen35_year_two_inspection_v1.json)
uses the new profile pair with unchanged Qwen3.5 weights, sampling, output/reasoning
budgets, segment bounds and original seed. It also incorporates the dialog and clock
implementation changes, so this is not a strict single-variable comparison. The
model must choose its own view and all gameplay actions. Historical runs are not
resumed or rewritten. This new model condition has not run; no new comparison row,
year-two result, merge or deployment is claimed.
