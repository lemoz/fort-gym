# Campaign status

Verified September 6, 2026. The Year-Two Autonomous Play goal remains active.

The first matched three-model native development comparison is complete. It used
the same digest-bound starting save, frozen code `164ffd0ab5024de22158968bcec3f48a79dbade1`,
and [declared condition](../experiments/campaigns/local_native_packed_comparison_v1.json).
This is one attempt per model, not a ranking or year-two success.

| Model | Responses | Game commands | Native elapsed ticks | Observed result |
| --- | ---: | ---: | ---: | --- |
| Qwen2.5 7B Instruct | 16 | 16 | 1,600 | Repeated an already-enabled labor setting; no completed development. |
| Llama 3.1 8B Instruct | 16 | 16 | 0 | Repeated the same invalid digging command. |
| Mistral 7B Instruct v0.3 | 13 | 12 | 0 | Workshop placements blocked by stale pathfinding cache; a later correction exceeded the request-size limit. |

All three retained seven dwarves and food/drink stock counts of 45/60. Stock
counts do not establish production or sustainability. None completed a workshop,
bed or farm, and none reached the 403,200-tick first anniversary.

Native calls returned 224,746 accounted tokens and $0 metered model API charges.
Nine separate synthetic contract checks used 3,736 tokens; they are not gameplay.
Hardware, electricity and existing-host costs remain unmeasured. These numbers
are not reconciled total project spending or remaining budget.

## What the experiment established

- Model selection works by configuration across three local models. Their actual
  outcomes, counters, checkpoints and source hashes are retained in the
  [published comparison bundle](../experiments/evidence/local_native_packed_comparison_20260906.json).
- Packed history allowed Qwen and Llama to reach 16 requests within the unchanged
  22,000-byte allowance. Their final checkpoints include all 16 committed actions.
- Mistral's cursor-12 checkpoint retains all its committed game commands. Its
  thirteenth response and updated agent/usage state are outside that checkpoint;
  continuation requires reconciliation, not rollback to twelve-response usage.
- All eight copied native runtimes, the local inference server/runner and the
  private tunnel were independently verified stopped. No VM was created. The
  production code, services and paused original fortress were unchanged.

## Harness repair candidate, before longer campaigns

1. Implemented a separately declared simulation-advance policy. The original loop discards
   the model's explicit tick request whenever a command is rejected. Mistral asked
   for 2,000 ticks after each build attempt, but the stale-cache guard rejected the
   command and the loop advanced zero. The new policy honors explicit advancement after
   confirmed preflight/no-write rejections while preserving stops for unknown execution,
   unsafe native receipts and dialogs. Do not invent WAIT actions or tick counts,
   or change the historical condition retroactively.
2. Implemented correction-aware history packing. Mistral's first
   request was 21,636 bytes; adding the grammar correction produced 22,175 bytes.
   Current facts, all corrections, latest results, persistent notes and cumulative
   usage are retained; older history is reduced to fit. An irreducible overflow
   after a response still requires reconciliation, not a silent usage rollback.
3. Next: rerun the affected model under the new condition and look for completed native
   work. Then repeat matched comparisons and expand toward first-year survival.
   Solve retained-runtime disk growth before large numbers of copied segments.

The [repair condition](../experiments/campaigns/local_native_harness_repair_v1.json)
declares `model_requested/v1` and `bounded_history_corrections/v1`. All original
model manifests, request/token/segment bounds and sampling settings are unchanged.
It tests the two repairs together, not their isolated causal contributions.
The clock policy is model-visible and checkpoint-bound. Nine native hooks and
Python preflight branches now distinguish no-write rejections from attempted
mutations; unknown/partial writes get no additional simulation time. No cache flag
is cleared manually, no fallback action is inserted, and old results are unchanged.

Candidate checks: 620 focused campaign, native-helper, clock-lifecycle and memory
tests passed; one Linux-only test skipped. Fifteen of these execute actual Lua
hook control flow against engine doubles, including stale-cache rejections and
failure after a write. They are not native-game acceptance. Focused Ruff and
targeted typing of seven changed modules passed. A native repair-condition run
has not yet been accepted.

## Website and repository

The existing campaign page now supports versioned terminal snapshots even when no
live feed is configured, with profile, command mix, adapter-readiness limitations,
native time, resources, costs and source identity. A broken configured live source
still reports an error instead of pretending old data is current.

[Draft PR #125](https://github.com/lemoz/fort-gym/pull/125) is the integration surface.
The website/reporting code is separate from the frozen native execution revision.
Review, merge, production deployment and real-site acceptance remain open. Local
endpoint and frontend regressions are not browser visual QA or deployed acceptance.

Published-comparison checkpoint checks: 632 focused local regressions passed, one Linux-only
test skipped. The actual published three-model bundle is checked through the
campaign page/feed routes, with measured tick counts, adapter rejection counts,
final checkpoint status and usage retained. Focused Ruff/Black, JavaScript syntax
and targeted typing checks passed; global legacy static-check debt is separate.
