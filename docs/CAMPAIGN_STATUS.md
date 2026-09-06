# Campaign status

Verified September 6, 2026. The Year-Two Autonomous Play goal remains active.

Latest: the [Mistral harness-repair run](../experiments/evidence/local_native_harness_repair_20260906.json)
finished at **28,000 native elapsed ticks**, with 16/16 returned and accounted
requests, 96,919 tokens and $0 metered model API charges. Four checkpoints retain
all 16 committed commands and usage. All four copied runtimes/listeners, the local
model server/runner and the temporary tunnel were independently verified stopped.
The production revision/services and original paused fortress remain unchanged.

This is clock and continuation progress, **not fortress-development success**:
all 14 BUILD commands and two INTERACT commands were rejected. Seven dwarves and
food/drink stocks of 45/60 remain; completed workshops, beds and farms remain zero.
The 28,000 ticks were all explicitly requested by the model, following 14 attested
no-write rejections. There were no fallback actions or human gameplay rescue.

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

## Harness repairs and native findings

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
3. The affected model has now completed its new bounded condition at native code
   `75cc9318f09cf79f66789f83321e76ffe08b146d`. All 16 request hashes and their current
   facts/latest results were verified; the largest request was 21,879 bytes. It
   needed no grammar-correction retry in this run. Separately, the historical
   failed correction reconstructs to 21,912 bytes with the repair, preserving the
   current facts, exact correction, latest result and persistent notes.

The [repair condition](../experiments/campaigns/local_native_harness_repair_v1.json)
declares `model_requested/v1` and `bounded_history_corrections/v1`. All original
model manifests, request/token/segment bounds and sampling settings are unchanged.
It tests the two repairs together, not their isolated causal contributions.
The clock policy is model-visible and checkpoint-bound. Nine native hooks and
Python preflight branches now distinguish no-write rejections from attempted
mutations; unknown/partial writes get no additional simulation time. No cache flag
is cleared manually, no fallback action is inserted, and old results are unchanged.

The run exposed a remaining terrain restriction: the harness requires strict
FLOOR tiles, while the installed DFHack 0.47.05-r8 Quickfort generic rule also
permits BOULDER, PEBBLES, TWIG, SAPLING and SHRUB. Four rejected commands contain
eight failed tiles split evenly between BOULDER and SHRUB. The source hash and
rule locations are retained in the new bundle. This is not proof those complete
footprints had available materials or met every other placement condition.

Next: align campaign placement with ordinary native rules under a separately
declared condition, and verify native construction/material behavior. Then seek
completed production, repeat matched model attempts, and expand the time horizon.
Retained runtime copies currently cost about 335 MB per segment versus about
9 MB for its checkpoint. Use a bounded continuous-runtime/retention design before
large endurance campaigns; no historical evidence has been deleted.

Repair checks: 620 focused campaign/helper/clock/memory tests passed locally and
188 passed on the isolated Linux host. Its 15 Lua-only tests were skipped because
no Lua interpreter is installed there; all 15 executed locally against engine
doubles. Full CI at the native revision passed 2,697 tests but failed three older
exact-receipt assertions in work-metric tests. Those assertions now check the new
no-write field; the final expanded local suite passed **651 tests**, with one
Linux-only skip, including the actual four recorded campaigns through the page
and feed. Focused static/typing and JavaScript syntax checks passed. Fresh remote
CI verification is tracked on the PR.
These test results do not substitute for native construction or website acceptance.

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
