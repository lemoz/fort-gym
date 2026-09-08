# Window o: accepted inputs, failed checkpoint

The independent failure audit passed. The window itself failed. The last verified
checkpoint remains **631**, with **143,400 saved elapsed ticks**. No checkpoint 695
was created. Do not resume from 631 with its old usage counters or call the newer
trace a saved continuation.

## What happened

Astra Medium returned 64 valid, accepted keyboard decisions and advanced 21,200
ticks. The trace reached action boundary 695 and 164,600 observed elapsed ticks.
All 12 dwarves were alive, with zero recorded citizen deaths. Observed drinks
changed from 179 to 228 and private food from 82 to 43. Farms, beds and workshops
remained at 7, 5 and 4. These end states were not saved; inventory changes alone
do not establish production, accessibility or sustainability. Food measurements
were complete at 63 boundaries and unknown at two of the 65 boundaries.

The menu-identity probe failed before requesting a native save. Its raw response
was a Lua assertion, `Identity probe requires a native screen`, although the
Python error reported malformed JSON. The rejected stack entry type was not
recorded. Do not attribute the assertion to the visible menu alone or claim the
underlying screen-stack cause is known.

Follow-up: a separate provider-free diagnostic now reproduces the final
status/pets menu path from checkpoint 631. It observes DFHack's status overlay
between the pets and overall-status screens. The opt-in v4 save profile preserves
that stack and passed a real save plus fresh reload. This does not alter the
original failure record or recover its unsaved tail. See
[DFHack screen checkpoint support](DFHACK_SCREEN_CHECKPOINTS.md).

Every persisted save file still matches checkpoint 631 except the event log.
Screen and world observations were unchanged across the failed probe. No newer
save exists to recover the 21,200 unsaved ticks. The original checkpoint, failed
trace, memory and usage records remain intact. Game-process cleanup, container
exit and VM shutdown were verified; the container exited 1 without an OOM kill.

## Accounting and publication

The window returned 1,968,854 tokens. Cumulative accounting is 711 responses,
22,819,077 campaign tokens and 22,888,081 all-attempt tokens. Dollar charges remain
unreported, not zero. No new restart, replay, memory reset, usage reset or strategy
intervention occurred. The earlier 2,000-tick loss and one save-loss restart remain
inherited history; this unsaved tail is recorded separately until a new restart
is explicitly implemented and audited.

The versioned result is
[the pre-save failure summary](../experiments/evidence/astra_native_keyboard_presave_failure_20260908.json).
Its private audit digest is
`8abba48e8f28781676bcffb0037f00226d1ea87267623192fcb75bf87154ee8d`.
The implementation's recorded-data adapter still ends at completed checkpoint
631. The local preview at port 8857 was unreachable when checked; no live website
update is claimed. The new failure record is not in the completed-continuation
allowlist, and its failure surface is not implemented yet. No website deployment
or new completed-continuation claim.

## Next work

1. Expose the failure and the new save/reload acceptance on the website. The
   checkpoint fix has passed its independent native audit; gameplay has not resumed.
2. Use an explicit restart declaration
   that preserves all 711 accounted model responses and records the additional
   lost time. Never silently replay the failed window or reset its counters.

Independent model-selection support was developed while the native source stayed
frozen. It preserves Astra v1 and adds opt-in v2 model identity; no alternative
model was called. See [the model-selection contract](CODEX_KEYBOARD_MODEL_SELECTION.md).
