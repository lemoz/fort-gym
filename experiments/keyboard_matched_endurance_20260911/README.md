# Decision-128 continuation preparation

These configurations reproduce from the audited Astra1, Sol1, Terra1, Terra2 and Sol2
decision-128 results and their complete earlier public histories. Each owns
two 64-decision save segments, up to decision 256, under the unchanged original
campaign limits. They are preparation, not launch admission or future results.

The five decision-128 source results are already on the remote campaign
branch: Astra at `0c2aaeb63f1a209cf7ec299a473a77911ddd10ed`, Sol at
`91cab28293ed75f968fca12b4f1acbc5908da68e`, and Terra at
`b17449c294ab154126192ab926603dfd59589114`. Terra2 is at
`1f3b10db4e35fb9560254cb1bd789838dedd3264`; Sol2 is at
`840402a411d69e868a6b93429d35a8f6502ca52f`. Exact result hashes and complete
own-save chains are verified by `tests/test_matched_128_continuation_configs.py`.

Only these five audited parents are included in this preparation revision.
Astra2's configuration must be derived from its own audited result;
no parent is invented for it. Complete and audit the
current stage for all six attempts before advancing the next stage in the
same original order. Do not tune prompts, choose winners early, reset memory
or substitute checkpoints. Terra1's zero-progress window remains in its chain.

`keyboard_window_audit.settled_segment_spans` prepares a full private auditor
to inspect a variable number of native save segments. It rejects gaps, extra
segments, changed identities, unsettled saves and work after a pause. A pause
may occur before any response in a later segment; completed earlier segments
remain part of the same window. Its synthetic tests establish structure only.

The new `keyboard_segment_audit` verifies each checkpoint's full file inventory,
parent identity, loaded calendar, retained agent state, settled usage, complete
trace prefix, new action ticks and native cleanup receipts. Its window composer,
`keyboard_window_checkpoint_audit`, reconciles all segments with the declared
prior totals. Only a verified load by the following segment establishes that
an intermediate save was freshly reloaded; the last save remains unverified
for a separate fresh reload.

Read-only checks against all four actual completed windows reproduced their
previously audited checkpoint hashes, tokens and ticks, including Terra1's
zero-progress result and Terra2's unsupported-key outcome. Deterministic fake
game/runtime tests exercise two-segment continuity, zero-response pauses,
missing segments and tampered load/agent/save evidence. These fixtures are not
native multi-segment gameplay. Provider receipts, resource limits, measurement
coverage, VM teardown and complete owner/auditor integration remain separate
requirements before launch. Historical owners and native source remain frozen.

`keyboard_window_receipts` composes the existing actual-provider and admission
reviewers across an entire window. It checks every host/native request and
response pair, exact dispatch order, memory continuity across save boundaries,
strict counters, and the final pause. Its return value is private, including
model memory and actions; it is not a public website projection. Twenty-two
synthetic checks cover the composition. A read-only check of all five actual
completed 64-to-128 windows reproduced every original provider review, returned
token total and final model memory. These are rereads, not new model calls.

A separate private next-stage controller/auditor draft now binds these helpers
and the five available decision-128 parents. Its 28 offline controller tests
cover startup, unchanged resource limits, failures, admission and teardown.
Together with cumulative-usage and teardown audit checks, 42 private offline
tests pass. Combined collection exposed a host/frozen-package import-order
issue; the host package is now selected before loading frozen support, and
the combined tests pass. The frozen agent/environment/evaluator code remains
byte-unchanged relative to the native revision.
The full next-stage publication and end-to-end integration review remain open;
no decision-256 run is launched by this preparation work.

This isolated preparation checkout does not replace the current website,
change its registered results, start a VM or make model calls. Year-Two
Autonomous Play remains the full objective, not decision-256 configuration.
