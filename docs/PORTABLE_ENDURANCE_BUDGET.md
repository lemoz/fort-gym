# Portable endurance budget continuation

This isolated candidate extends the existing checkpoint mechanism; it does not
change or rerun the active selected-workshop v2 cohort. Its parent is
`af922cb4c3e0cf33bfe62cf6ba702bdf83363e1a`, which includes the separately reviewed
workshop job-screen feedback correction. No native image has been built for
this candidate, and native acceptance is not yet established.

## What changes

Portable continuation accepts a new `fortgym.codex-keyboard-window/v2`
declaration. Its original condition file stays byte-for-byte unchanged.
In addition to the existing window fields, v2 requires:

- `continuation_checkpoint_sha256`: the exact verified parent manifest.
- `budget_before`: the two cumulative limits already present in that parent,
  including any earlier append-only extensions.
- Optional `budget_extension`: new `max_dispatches` and
  `max_total_tokens` limits. Neither can decrease, and at least one must increase.

The owner and native launcher verify the parent budget before play. The native
worker appends an extension only for the first segment and binds it to the
parent's digest and settled usage. Later segments and windows inherit that
history. A later v2 window with no extension still declares the actual inherited
budget; it does not return to the original, smaller limits.

Memory, original configuration, cumulative usage, prompt history and full
trace/journal prefixes remain preserved. No strategy or prompt change, restart,
automatic account reset, API fallback or extra model call is introduced.
Existing admission checks and finite window/segment limits remain in force.
Budget values are accounting declarations, not new spending authorization.

## Verification path

The portable plan, host courier, native launcher, segment/window auditors,
live spectator and recorded export share the same continuation boundary.
Replay export follows every saved segment within a window and links the first
save of each new window to the previous window's final save. It no longer
mistakes a valid multi-save window for a broken cross-window lineage.
Auditors verify the actual append in the native agent-before and final save,
not merely the presence of an extension declaration. The public audit retains
before/after limits and whether the append-only history was verified.

The offline integration fixture starts with a two-response budget, extends it
to eight at its own checkpoint, plays two further segments, and then resumes
through another window without adding the extension again. It verifies the
original save bytes, eight-response/800-token cumulative accounting, memory,
live-viewer input and complete eight-frame export. Fake game/model/container
receipts are used; this is not native gameplay acceptance.

Legacy portable v1 windows still reject budget changes. Historical native v1
declarations keep their earlier behavior and evidence. Source/image migration,
runtime resource changes and observational or control changes are not silently
enabled by this budget version. Existing owner and chain checks still require
the declared source/image.

The final complete local regression suite passed 5,729 tests with ten skips and
eight warnings. All 22 new budget tests passed, including the multi-save replay
and missing-append rejection cases. Changed-file Ruff checks and the patch
whitespace check passed. Repository-wide Ruff and Mypy still report the same
ten and 465 diagnostics as the parent, respectively; no new diagnostics were
introduced. An earlier suite was intentionally interrupted after a focused test
exposed the multi-save replay issue; that partial run is not acceptance. The
counts above come from the complete rerun after the correction.

## Remaining delivery work

Verify exact-head hosted CI before treating this as a CI-accepted candidate.
After the frozen six-attempt controls cohort finishes,
verify a real native same-save extension with this implementation. Extending an
old cohort checkpoint with a new source/image also needs an explicit, separately
audited runtime transition; this candidate does not claim that transition exists.
A fresh long-budget campaign is a distinct experiment, never a relabelled
continuation of the old control trials.

This worktree is retained at
`fort_gym/artifacts/worktrees/portable-endurance-budget` under the owning
environment-layer repository. It is separate from the frozen active source.
