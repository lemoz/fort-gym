# Explicit restart after lost native progress

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
