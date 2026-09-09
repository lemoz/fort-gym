# Unavailable native-runtime continuation

Window `campaign_astra_keyboard_window_20260908t.json` declares a continuation
from verified checkpoint 711 after window s lost native UI access. The container
reported OOMKilled; its exact cause and victim are unverified. An extra in-container
observer expanded the full trace and could have contributed. Do not repeat that
observer during native play. Existing host courier receipts are the live surface.

The explicit restart preserves all 842 returned/accounted responses and
26,990,171 campaign tokens. It restores saved model memory, replays no input,
inherits three existing losses, and records 5,200 known unsaved ticks plus an
unknown uncommitted remainder. Unknown is never zero. After application, four
losses have a 35,091-tick known lower bound, but no exact discarded-time total.
Retained elapsed time remains 192,600 ticks until fresh play commits more time.

`keyboard_unavailable_restart` validates the source checkpoint, native reload,
complete paused input receipts, the final model receipt and usage, unchanged
native save files, cleanup, and the complete newer loss history. Changed or
missing evidence rejects this path. It does not declare the failed run successful.
The evaluator emits `discarded_native_ticks: null` and separate confirmed lower
bound/completeness fields when any retained loss has an unknown remainder.

Checkpoint creation and no-action verification now decode one observation at a
time instead of materializing the entire screen history. Immutable trace bytes,
hashes, calendar checks and snapshot formats are unchanged. Regression coverage
includes large-history memory, repeated rollback, unknown first-input loss,
changed source evidence, and checkpoint/resume preservation of usage and losses.

The declared 64-decision window keeps Astra Medium, native keyboard input,
120x40 screen text, model-selected advancement, save/measurement profiles, and
the existing cumulative 1,024-response/40-million-token allocation unchanged.
Declaration and offline tests are not native completion or year-two success.
