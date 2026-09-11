# Model-visible elapsed campaign time

The opt-in observation profile `campaign_state/v2` adds a factual campaign clock.
World year 31 does not mean a model has played 31 years, and crossing the world's
new-year boundary does not by itself mean a full elapsed campaign year has passed.

The loop supplies the sum of **committed actual native tick receipts**, not
requested ticks, wall time, action count, a model's narrative, or a public report.
The observation includes total elapsed ticks, 403,200 ticks per year, completed
elapsed years, the current elapsed year, ticks into it and completed decisions.
At 403,200 elapsed ticks the current elapsed year is two. This is a duration fact,
not proof that a functioning fortress survived.

Checkpoint continuation reconstructs the clock once from the digest-bound trace
prefix and then adds each newly committed receipt. It does not reset on segment
boundaries. Zero-tick actions consume their normal decision/usage allowance but
do not age the campaign. Missing full-prefix evidence remains unknown; the world
calendar is never used to invent a campaign start. Restoring an older checkpoint
retains the older game's elapsed duration and all later accounted charges under
the existing usage policy, not later un-restored gameplay.

This observation version is accepted with the existing `campaign_action/v1`
decision profile and both hosted/local campaign configurations. It changes no
model, action, planning policy, tick limit, scoring or native map control.
Prompt packing retains the clock. Checkpoints bind the observation version and
refuse switching between v1 and v2 on resume. Existing configurations remain v1;
a future experiment must declare a new condition rather than change a live run.
Representative v1 observation bytes have a pre-change digest regression.

## Why this is part of the next gameplay attempt

The recorded reasoning-budget attempt committed 203,339 elapsed native ticks
before a dialog-related harness failure, with a native calendar of year 30.
That is less than a full elapsed year. The original model observation exposed
the world calendar but no explicit elapsed campaign duration. This change tests
whether giving the model the same duration fact used by the evaluator improves
its temporal grounding. It does not establish that missing elapsed time caused
the failed playthrough or that this change improves model performance.

Map control remains a separate limitation. The current campaign native reader
uses a bounded fort-anchored minimap and passes no model-selected focus arguments.
There is no model-controlled pan/z-level inspection action in the campaign
interface. That warrants a separately versioned read-only inspection capability
with checkpointed model-selected view state and ordinary hidden-tile boundaries.
This clock change does not claim to implement it or make the interface complete.

Validation is offline: elapsed-year arithmetic, unknowns, zero-tick decisions,
world-calendar rollover, checkpoint equivalence, version binding, configuration
selection, unchanged v1 output and prompt packing. No native/model experiment,
year-two fortress success, model ranking or website deployment is claimed.
