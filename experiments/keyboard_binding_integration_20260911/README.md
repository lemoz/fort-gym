# Integrated displayed-key native acceptance

This provider-free diagnostic tests committed harness revision
`8b9fffa1de4f93506cbcbdf82fd154aeb17b5697`, not the earlier standalone parser.
All tested input uses `NativeCampaignEnvironment.apply` with
`native_keyboard_bindings/v1`. No native action aliases, job insertion, model
calls, time advancement, native saves or campaign checkpoints are requested.

Predeclared sequence on one fresh copy of Astra attempt 1 checkpoint 256:

1. Operator-only reset/reveal establishes a paused map view. Displayed q enters
   building-query mode, Escape leaves it, and q reenters it.
2. Operator-only positioning selects the completed carpenter workshop. Left
   moves the cursor one tile; Right returns it to the original coordinate.
3. a opens AddJob; Escape leaves it; a then b queues exactly one ConstructBed
   job while all original jobs remain unchanged.
4. Ctrl+n opens naming. Separate mixed-case characters type FgAb7; Backspace
   changes the visible text to FgAb; Enter closes the entry interaction. Capture
   the actual native name where exposed and the complete screen at every step.
5. Escape returns from query mode. All sampled boundaries must remain paused
   at year 30, tick 152201, with identical binding-file and source-save hashes.

Escape's behavior in a naming dialog is not assumed to revert a name. This
version tests Enter completion and Escape menu exit, not cancellation semantics.
Operator positioning is explicitly outside the tested navigation. This copy
must never become a scored campaign origin. Passing proves only the declared
integrated controls, not physical-device equivalence or autonomous gameplay.

The bounded owner derives a local image from the retained runtime, with no
network during build or execution, and must stop the container and local VM.
Raw private evidence belongs in the existing project runtime artifact tree;
this directory contains reproducible source, not proprietary game/save files.

## Observed result

The [versioned result](../evidence/keyboard_binding_integration_20260911.json)
records a passing integrated native run: 14 action batches, 18 individual key
presses, one new ConstructBed job, and the actual workshop name FgAb after
mixed-case typing, Backspace and Enter. Query/AddJob entry and exit and the
one-tile cursor round trip passed. No game ticks elapsed; the original jobs,
binding file and source checkpoint were unchanged. Native process cleanup,
container exit and VM shutdown passed, including a separate live stopped check.

The first packaging attempt failed before creating a game container. BuildKit
interpreted the raw image ID in the original Dockerfile as a registry name and
attempted a metadata lookup despite network-disabled build steps. Preserve that
failure. `Dockerfile.v2` uses the already retained local tag, whose exact image
ID the owner verifies before building. The fixture, probe, source revision and
predeclared game checks are identical across versions. Both VM starts ended in
verified shutdown. Neither attempt made a provider call.

`review.py` independently reads the retained native receipts and screens; it
does not launch or control a game. These results support proceeding with the
separate Astra trial, which has not yet launched. They are not campaign progress.
