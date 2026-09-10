# Matched endurance windows

The original cohort declares comparison boundaries at 32, 64, 128, 256, 512,
1024 and 1280 decisions. A 64-decision result is an intermediate checkpoint,
not the goal. We are testing whether unchanged autonomous agents can develop
their forts, maintain population and supplies, survive a full elapsed year,
and continue into year two. Calendar time, supplies and current-job samples
alone do not prove sustainable production or model superiority.

## From an audited save to its next window

`scripts.campaign_matched_endurance_window` takes the full chronological chain
of public records and exact SHA-256 digests. It reproduces the original 32-to-64
declaration, checks each successor against its own parent and the exact window
bytes, and emits the next configuration on stdout. It never starts a VM, calls
a provider, reads private state, changes a save or admits spending.

For example, from this checkout:

```sh
python -m scripts.campaign_matched_endurance_window \
  --result experiments/evidence/keyboard_matched_astra_r1_20260910.json \
    59e3fe7a4a3edddcf6a6d1264c748237868b87f71a345d66e2c72c4c183906a1 \
  --result experiments/evidence/keyboard_matched_astra_r1_continuation_32_64_20260910.json \
    2c8abe1f7135d94ed27aea51e18ebc59e0599205caf3f268f4480b0e377f3d29
```

This reproduces `experiments/keyboard_matched_endurance_20260910/astra_r1-64-128.json`.
Pass each later audited public continuation as another `--result PATH SHA256`.
Later results must retain the same continuation schema, aggregate the entire
declared window's new responses/ticks/tokens, and include every saved decision
boundary. They must bind their actual declaration commit, window digest and
unchanged native source/image/storage execution binding. A new owner and auditor
must produce that evidence; a synthetic unit fixture cannot stand in for it.

The next planned stages use 64-decision save segments: one segment to128, two
to256, four to512, eight to1024 and four to1280. After an admission pause inside
a segment, the next configuration finishes only that segment before scheduling
whole segments again. This preserves the same save and comparison boundaries
across attempts rather than introducing more frequent saves for one model.

The generator checks own campaign/model/replicate identity, original condition,
parent checkpoint and public-result digest, exact reproduced declaration bytes,
fresh source-load and memory-preservation claims, cumulative usage and clocks,
saved observations, cleanup and teardown. It rejects missing/reordered/borrowed
records, altered controls, unaccounted usage, rescue, new save loss and changed
cost reporting. A verified budget-limited pause is resumable. Provider or native
failures must first be reconciled and recorded, never relabeled as gameplay
collapse or silently restarted. Charges remain unreported, not zero.

## Execution prerequisites still required

The current private `operator_continue_v3.py` and its auditor own only32-to64.
They remain frozen. Do not pass these longer configurations to that owner.
Implement and test a separately versioned owner/auditor for the next stage;
verify the complete six-attempt input packet before launching that stage in
the same order. Every actual launch must bind its clean remote native/declaration
revisions and passing CI, full private checkpoint inventory, unchanged own
memory/configuration/prompt and complete trace/usage prefixes. It must verify
the native load, use a fresh subscription allowance check per call, and perform
mandatory teardown. One existing local VM, unchanged resource bounds, no cloud
VM, no API/local-model fallback and no credit/reset purchase remain in force.

The final save is verified by its inventory and terminal audit; a later fresh
native load is a separate proof. Public-record validation does not replace
private native, request/response, memory, usage or teardown audits. No new game
time is claimed by preparing configurations, passing tests or pushing this code.

All historical records, initial declarations, live observer and running website
source are unchanged. The new configurations live in the isolated
`campaign-matched-endurance-windows` worktree under the existing project's
`fort_gym/artifacts/worktrees`, on `codex/campaign-matched-endurance-windows`.
This is an observed worktree path, not a canonical-project relocation.

## Verification scope

Tests use the four real audited input chains and byte-compare their generated
64-to128 configurations. Synthetic fixtures explicitly exercise later stages,
uneven and zero-response pauses, exhausted allowances and malformed lineage.
Those fixtures prove configuration behavior, not future gameplay results.
No native runner, prompt, condition, provider transport, website route or
dependency is changed by this implementation.
