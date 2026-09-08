# Explicit restart after lost native progress

## Audited result, September 8, 2026 UTC

Window e completed at source `93af69fe4866cf325dcae3a8b4099bc458b6fdfc`.
Astra returned 16 new accepted decisions and advanced 2,000 retained ticks.
New branch checkpoint 200 is independently verified at digest
`aabb513a50309812f900d9e346807710acb0935f271a200e9df4cda59aef1cdb`.
The retained timeline is 46,000 ticks. The original unsaved 2,000 ticks remain
lost, and the original failed window remains immutable. All 216 model responses
are accounted: 6,984,036 campaign tokens, including the old tail's 531,913 tokens,
and 7,053,040 with historical failed deliveries. New usage was 518,169 tokens;
exact subscription charges remain unreported. Native game, container and VM
teardown are independently verified. No worker is live at this checkpoint.

The recorded website source projects this new branch separately from the old
failure and checkpoint 184. It does not claim uninterrupted play, recovered
lost state, a comparison attempt, fortress sustainability or live activity.
Public operational evidence:
`experiments/evidence/astra_native_keyboard_restart_20260908.json`.

## Subsequent window f: screen validation failure

Window f executed at `1198ece397eec679c04dcf4e948b2b419bbde956` and returned
16 accepted decisions with 1,200 new ticks before checkpoint validation failed:
`Native screen changed during menu-preserving save`. It preserved memory, full
usage and the inherited discontinuity without another restart or budget extension.
All 232 responses are accounted: 7,706,555 campaign tokens, or 7,775,559 including
historical failed deliveries. New usage is 722,519 tokens; charges are unreported.
Independent audit verifies unchanged original prefixes and game/container/VM teardown.

The helper completed a copied native save before rejecting screen equality.
Copied files match the stopped runtime and its world save differs from checkpoint
200. This is not proof of lost state or a resumable checkpoint 216. Last verified
checkpoint remains 200 / 46,000 ticks; the retained trace reaches 47,200 ticks.
Fresh reload and forward-only reconciliation are next. Do not rewind, replay
actions, repeat the loss-aware restart or silently discard this newer save/usage.
Public evidence: `experiments/evidence/astra_native_keyboard_checkpoint_review_20260908.json`.

The executed helper did not persist the exact before/after screen pair or Lua
receipt on validation failure, so the screen-change cause is unproven. The updated
implementation retains these privately in `save-attempt.json` on failure, with
any completed copy receipt. It does not retry saving or relax screen equality.
This is diagnostic instrumentation, not a claim that the underlying issue is fixed.

## Restart protocol

### Pre-save identity failure extension

The verifier also recognizes the retained Lua assertion `Identity probe requires
a native screen` before the save operation. The broad malformed-JSON label alone
does not enable restart. The private save-attempt must contain exactly the
before/after world and screen plus the original failed pre-probe output, with no
save operation, post-save identity, copied-save receipt or capture error. Both
world and screen must be unchanged and match the segment's final observations.
The unchanged native-save, accepted-tail and full-usage checks still apply.

These v1 discontinuities additionally bind `source_save_attempt_sha256` and
`save_failure_stage: identity_before_save`; existing timeout receipts remain
unchanged. The original evidence is never edited. This is declared loss, not
forward recovery or an automatic save retry.

Window p declares one 16-decision Astra Medium segment from checkpoint 631 with
the native-verified v4 save profile. It retains all 711 prior responses and
22,819,077 campaign tokens, restores checkpoint memory, and records 21,200 lost
ticks alongside the inherited 2,000-tick loss. The 1,024-dispatch / 40-million-token
cumulative limits are unchanged. The shorter save cadence is an explicit
infrastructure condition, not a model-comparison result. This configuration and
provider-free verification do not claim that a new native restart has run.

### Historical window e

Window e uses the verified menu-preserving save profile and performs one
16-decision segment from durable checkpoint 184. This is not an uninterrupted
campaign, a recovery of the unsaved tail, or an independent comparison attempt.
The original failed window, 200-response trace and usage remain immutable.

The restart verifier checks the exact failed segment, accepted trace tail,
complete usage journal and original trace prefix, native calendar, and the fact
that actual save files still match the older checkpoint. Newer native state,
an existing checkpoint, unsettled dispatch, missing usage or changed source
identity prevents restart. DFHack's append-only load log is the only excluded
file when comparing unchanged saves.

The model starts from checkpoint 184's memory and native state. All 200 prior
responses and 6,465,867 campaign tokens remain in its cumulative usage. The
existing 1,024-dispatch / 40-million-token ceiling is re-declared at this restored
boundary, not added to itself. Historical failed-delivery tokens remain separate.
The first model feedback identifies the restored cursor and 2,000 lost ticks.
It contains no replacement keys or strategy. No old action is replayed.

The digest-bound discontinuity is retained in the segment result, runner state
and subsequent trace rows/checkpoints, including after another normal resume.
Overlapping step numbers belong to different retained branches; do not present
the newer branch as restoring the old window's missing state, add both traces'
ticks together, or count this as an independent comparative attempt.

The normal window path still refuses later usage with an older checkpoint.
Only an explicit restart declaration plus its retained failed source enables
this path. The existing native launcher, model exchange and checkpoint verifier
remain in use. No GCE, model fallback, credit purchase/reset, merge or deployment.
