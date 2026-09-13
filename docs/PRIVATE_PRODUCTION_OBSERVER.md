# Private production-event observer candidate

Status: offline-tested candidate, not installed in a game or connected to an
agent, campaign profile, public API or website. Keep the active Astra endurance
campaign on its frozen source and image.

## Why a separate observer

Current paused food/drink scans measure inventories. Their differences cannot
identify production, consumption, trade, spoilage, theft, stack merging or
accessibility. A private event stream is needed alongside those inventories.
This candidate captures evidence needed for that stream; it does not yet close
the sustainability measurement requirement.

The pinned [DFHack event manager](https://github.com/DFHack/dfhack/blob/0.47.05-r8/library/modules/EventManager.cpp)
detects completed-job notifications from timer transitions and removal. Its
repeat-job path documents a precisely timed cancellation false positive.
Its item-creation detector filters foreign, trader-owned, owned and spider-web
items. Neither event provides a complete balance of arrivals and departures.
The [eventful implementation](https://github.com/DFHack/dfhack/blob/0.47.05-r8/plugins/eventful.cpp)
passes those notifications to Lua; its polling-frequency API can reduce the
shared frequency but cannot restore a previous higher frequency.

Its reaction-complete hook passes the cumulative output-item vector after a
product appends items. Later callbacks can therefore repeat earlier outputs.
The collector preserves reaction code, worker identity and every output-item
identity, including overlap, without treating recipe quantities or repeated
vectors as newly produced units. Coverage of ordinary built-in workshop jobs
still needs native verification; this hook is not a complete production meter.

Therefore record job notifications and item observations separately, retain
uncertainty, and validate native coverage before assigning quantities or causes.
Do not sum item observations into a production claim or subtract inventories to
label consumption. Duplicate notifications remain observations, not extra goods.

## Candidate implementation

`fort_gym/bench/production_observer_lua.py` exports a Lua factory only. Importing
the module does not contact or modify any game. A future isolated process can
construct it with its real `df`, `dfhack`, `plugins.eventful` and a declaration:

- campaign identity, segment identity, exact root and a 1–8,192 event capacity;
- DF v0.47.05 linux64 / DFHack 0.47.05-r8;
- paused start and snapshot boundaries, monotonic native calendar and frames;
- zero-frequency job and item notifications, reaction-complete callbacks,
  read-only item methods, and an unload listener that removes only this
  observer's own callbacks.

Events contain a sequence, native clock, job type/identity or item identity,
food/drink classification, stack units at observation and item flags. They do
not contain agent memory, prompts, model responses or a gameplay action.
An item-creation observation is not attributed to a recipe or worker. Reaction
observations preserve a cumulative vector of food, drink and nonfood outputs,
mark quantities `not_totalled`, and report duplicate item identities within a
vector. Job quantity is explicitly unmeasured. Production, consumption, trade
and loss statuses remain `not_measured`; no zero-valued quantities replace
missing measurements.

Snapshots copy the buffer without consuming it. Read failures, missing items,
clock/save changes and overflow stay visible. The memory bound retains the first
events and reports how many later events were dropped. Event count and total
retained item records each have the declared capacity; a reaction vector over
32 items is a read failure, and an event that exceeds retained capacity is
dropped whole. Inputs, reagents and the reaction pre-completion hook are never
modified. Failed installation consumes the observer identity and cannot appear
complete. A caller cannot mutate
the declaration or a returned snapshot to change retained observations.
`collector_records_complete` describes only collector retention/read success.
`native_coverage_validated` remains false, including in passing unit tests.

Stopping removes owned listeners, not shared plugin polling registration. Use
only in a disposable, separately declared native process whose teardown bounds
that overhead. Never install this candidate into the current frozen campaign.

## Item-level inventory boundaries

The candidate now also exposes `inventory_snapshot()` while its collector is
installed. This is an explicit read, not an automatic scan in each callback or
an addition to the agent observation. A fixture should call it at its initial and
final paused boundaries, alongside event snapshots, to retain identities needed
for later reconciliation.

It scans `world.items.other.IN_PLAY`, using the same pinned food predicate as the
existing private food scan: `isEdibleRaw(0)`, with `DRINK` classified separately.
Each retained food/drink record has its actual item ID, type, stack size and flags.
Removed/garbage-collection entries and nonfood items have separate counters;
forbidden, rotten, foreign, trader-owned and other flagged supplies remain visible,
not silently relabeled as accessible fortress supplies.

The declaration's optional `max_inventory_items` defaults to 8,192 and is bounded
at 65,536 scanned entries, including nonfood entries. A scan stops at that bound
and reports omitted entries. It attests the native save/calendar/frame boundary
before and after the read and includes the collector start and event sequence.
Changing clocks, pause state, event sequence or list length, missing reads,
duplicate IDs, total overflow and truncation prevent a complete inventory total.
Partial records remain inspectable; `units` is false rather than a misleading
zero or partial sum. A complete empty scan is the distinct case with zero totals.
Snapshots neither consume the event buffer nor mutate retained game records.

This inventory is still not production or consumption attribution. Matching a
new item with a reaction callback, deduplicating cumulative output vectors and
accounting for stack changes need a separately verified reconciliation layer.
Native coverage, accessibility and reload/checkpoint binding remain unproven.

## Prepared native binding probe

`scripts/campaign_production_probe.py` now provides a provider-free, passive
native-interval probe. It is prepared and offline-tested, not native-accepted.
It does not queue production jobs or provide an independent production oracle.

The `run` command belongs **inside a caller-owned, admitted Linux runtime**.
It does not provision or own a VM, choose a source image, or perform host-level
admission. Do not run it while the active endurance coordinator owns the sole
local runtime. Its inner process owner copies a verified checkpoint, loads it
paused, and tears down only its owned game process. It verifies the original
checkpoint contents again after the run, including on failure. It cannot run
directly on the development Mac.

The explicit inputs are `--source` (retained native runtime), `--checkpoint`,
`--revision` (the clean candidate checkout), and a new `--output` directory.
`--port` defaults to 5610. `--intervals` defaults to 4, bounded at 32, and
`--ticks` defaults to 250 per interval, bounded at 2,000. Thus the maximum
declared advance is 64,000 ticks, with a separate 600-second worker deadline.
No API/model credentials are forwarded by the isolated-process launcher.

The worker uses direct local RPC with CLI fallback forbidden. It checks its
expected copied-runtime path and creates an unpredictable observer ownership
identity. Start, read and stop operations guard the exact runtime and owner;
collisions never remove another observer's slot. Cleanup is attempted even if
the start RPC times out, because it may already have installed the observer.
The event capacity is 256 retained events/item records and the inventory scan
capacity is 8,192 entries; reaching either limit remains incomplete evidence.

Each paused boundary retains separate item inventory and cumulative event
snapshots in a hashed JSON artifact. It must match the adapter's actual calendar,
save identity, event sequence and observer origin. Tick receipts and before/after
clocks are retained before validation, including incomplete intervals. A native
interruption stops the probe; it never dismisses a dialog, presses keys, retries
a tick timeout, places an order, injects items or creates a continuation save.
Worker errors and stop failures are retained, and the outer result binds worker
and game-process cleanup receipts by hash.

Even a `completed` probe reports `production_coverage: inconclusive`,
`native_coverage_validated: false`, and `flow_attribution: not_measured`.
`completed` only means its declared observation intervals finished. Natural
callbacks may provide examples to investigate, but item arrivals or completed-job
notifications are not independent proof of a particular production quantity.
Controlled brewing/cooking, cancellation, multi-output and observer-free control
fixtures below remain separate acceptance work. No active campaign profile or
website metric has been changed.

## Native acceptance still required

1. Pin source/image and the measurement profile in a new fixture declaration.
   Wait for the existing coordinator's runtime ownership to end before using the
   one local VM. No new cloud infrastructure or model call is needed for a
   controlled measurement fixture.
2. Capture independently verifiable single and repeated workshop completions,
   cancellation at relevant timer boundaries, actual product item identities and
   stacks, edible non-drink production and irrelevant/nonfood item creation.
   Include multi-product reactions whose callbacks share a cumulative vector,
   and distinguish those from built-in jobs that may bypass the reaction hook.
3. Check trade/migrant arrivals, splitting/merging stacks, disappearance before a
   callback, consumption and spoilage. If the event interface cannot identify
   a cause, retain it as unattributed and add a separately tested native hook.
   The attribution layer must reconcile these identity-level inventory snapshots,
   recipe outputs and event records; this collector alone cannot do so.
4. Verify no game state or agent-visible observation is changed by callbacks.
   Measure callback overhead and missed events against an observer-free control.
5. Bind snapshots to checkpoint manifests and trace boundaries, preserve them
   through actual reload, and attest any gap or buffer overflow. Only then wire
   a declared opt-in private profile into the harness and reporting surfaces.

Lua fixture tests execute the collector code with fake objects and callbacks.
They validate its data handling, not DFHack event coverage, real production,
campaign recovery or native noninterference.

The candidate CI explicitly installs Lua 5.3 and verifies the interpreter before
running tests, so these fixtures cannot silently skip because Lua is absent.
This matches the version family of the pinned DFHack build's
[embedded Lua 5.3.6 header](https://github.com/DFHack/dfhack/blob/0.47.05-r8/depends/lua/include/lua.h).
The development host currently runs the fixtures with Lua 5.5.1; neither host
interpreter substitutes for real DFHack binding and gameplay acceptance.
