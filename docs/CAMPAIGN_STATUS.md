# Campaign status

Verified September 6, 2026. The Year-Two Autonomous Play goal remains active.

Latest: the [factual designation-reference condition](../experiments/evidence/local_native_designation_reference_20260906.json)
stopped at a request-size boundary: **15 accounted responses, 78,023 tokens,
14 committed commands and 2,800 explicitly requested native ticks**. All fourteen
DIG commands were rejected as `tile_not_designatable`; no development completed.
Twelve raw responses omitted `kind` and defaulted to `dig`; two explicitly chose it.
The exact reference and payload hashes were verified in all fourteen committed
requests. The largest was 21,977 bytes; eight requests omitted older history while
preserving current facts and latest results.

The fifteenth response omitted the required third coordinate in both DIG `area`
and `size`. Its grammar correction could not fit alongside current facts, so no
second correction request or native command was dispatched. The latest verified
native/agent/trace/usage checkpoint is **cursor 12, not 14**. Two later committed
commands and the fifteenth response require reconciliation; **do not automatically
resume from the older checkpoint** or report the one unused dispatch as completion.
All three native runtimes/listeners, the model server and tunnel were independently
verified stopped. Production remained unchanged. Execution stayed frozen at
`8148f6d55494ad88caf46a780cfbea11d16d6a4a`.

Only Qwen14 has run this four-model reference condition. This is neither spending
cap exhaustion nor established fortress collapse, a ranking or year-two success.

A separately pinned [Qwen3.5 9B local compatibility check](../experiments/evidence/local_qwen35_9b_feasibility_20260906.json)
returned three accounted responses and 1,207 tokens. WAIT and LABOR copied exactly;
DIG retained coordinates and time but omitted `kind: gather`. No native game was
loaded or command executed, and the temporary server was independently verified
stopped. This is not a modern-model native integration or gameplay result. The
unchanged loose parameter schema remains a concrete hypothesis for a separately
versioned typed-contract test, not an established cause of earlier gameplay choices.

Earlier: [Qwen2.5 14B Q3_K_M](../experiments/evidence/local_native_qwen14_q3_20260906.json)
completed its bounded attempt: **16 responses, 82,782 tokens and 3,200
model-requested native ticks** across three saved segments. All sixteen DIG commands
were rejected as `tile_not_designatable`; no development completed. Twelve commands
changed following rejection. The final cursor-16 checkpoint includes every command,
response and usage record. Native runtimes, local server/runner and tunnel teardown
were independently verified, and production remained unchanged. The frozen native
revision remained `82645015444759f7bcebc048c34ea704930da8f4` throughout continuation.
The dispatch budget is exhausted; this is not collapse or first-year success.
The earlier cursor-6 publication remains in Git history and its separate private
audit, not an additional campaign. All sixteen request payload hashes and current
facts were verified; the largest request was 21,997 bytes.

Earlier: the [native-ground Mistral condition](../experiments/evidence/local_native_workshop_ground_20260906.json)
has completed its bounded attempt: **16 responses, 98,658 tokens and 32,000 native
ticks** across four saved segments. All 16 BUILD commands were rejected (four
stale-cache, two occupied-footprint and ten no-material rejections); no development
completed. The cursor-16 checkpoint includes every response, command and usage
record. Independent teardown verified all four native runtimes/listeners, the
model server/runner and tunnel stopped; production remained unchanged. The model
never chose woodcutting despite visible trees and `wood_usable: 0`. This is the
completed 16-dispatch development condition, not a model ranking, collapse or
year-two success. Its frozen native revision is
`82bcab14b758d6f4624e9080c857a607c2da0b51`. The earlier five-response publication is
preserved in Git history, not counted as an additional campaign.

Earlier: the [Mistral harness-repair run](../experiments/evidence/local_native_harness_repair_20260906.json)
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

The explicit `dfhack_047_ground/v1` workshop condition is now implemented at
`82bcab14b758d6f4624e9080c857a607c2da0b51`; legacy strict-FLOOR behavior remains the
default. A [provider-free native fixture](../experiments/evidence/native_workshop_ground_20260906.json)
verified the complete material/construction path: its strict control rejected
BOULDER/SHRUB terrain, the new policy passed terrain and correctly rejected absent
free material, then native woodcutting supplied logs and a carpenter's workshop
reached stage **3 of 3**. This took **4,010 scripted native ticks**, with zero model
calls, no material injection, no assisted completion and no labor-setting changes.
The final 127-file save inventory and independent process/listener teardown were
verified. Production remained paused at year 30, tick 19,309. This fixture does not
count toward model development, endurance, or rankings, and its save is not reused
as a model campaign starting state.

The three original logs were already `in_building`; `wood_usable` was zero. The
existing 11x11 model map already showed two trees, including the fixture's tree.
Do not misdiagnose this particular construction sequence as requiring extra map
visibility or new inventory facts. The
[new model condition](../experiments/campaigns/local_native_workshop_ground_v1.json)
keeps observations and other bounds unchanged apart from factual workshop-policy
disclosure, allowing a controlled test of the terrain repair.

Next: address failed-decision continuation and test a newer inexpensive local model
under a separately declared condition. The terminal
[reference experiment](NATIVE_DESIGNATION_REFERENCE.md) must retain its cursor-12
checkpoint and all newer trace/usage evidence; it is not safely resumable as-is.
Keep factual terrain/control documentation, with no chosen action, coordinate,
build order or gameplay rescue. A read-only replay had fit eleven historical
requests, but the actual fifteenth response demonstrated that this did not guarantee
future correction fit. Seek autonomous resource acquisition and completed production
before allocating a longer horizon. Do not silently enlarge an active condition,
discard newer actions, substitute a scripted fixture or mix unlike attempts in rankings.

Local feasibility: the initial Q4_K_M candidate offloaded 45 of 49 layers to GPU.
Two synthetic copy requests returned (766 accounted tokens); its third request
timed out without returned usage and was not retried. That server/runner was stopped.
The separately pinned Q3_K_M candidate offloaded all 49 layers and verified Flash
Attention and Q8_0 cache in actual runner logs. All three synthetic requests returned
(1,182 tokens): two exact copies, one omitted the supplied DIG `kind`. This proves
bounded transport feasibility, not exact format fidelity or autonomous gameplay.
Both synthetic runs have zero metered model API charges; operating costs are
unmeasured and the timed-out request's token count is unknown.
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

The prior full CI run at `d396c456fb30a247925115de762aa45154031f47` passed. The
workshop change passed **685 focused local tests** (one Linux-only skip), including
20 additional Lua control-flow cases, and **142 isolated Linux tests** (20 Lua
cases skipped there). Native fixture success is separate evidence above. Remote
CI for `82bcab14b758d6f4624e9080c857a607c2da0b51` passed in run `34026849553`.

## Website and repository

The existing campaign page now supports versioned terminal snapshots even when no
live feed is configured, with profile, command mix, adapter-readiness limitations,
native time, resources, costs and source identity. A broken configured live source
still reports an error instead of pretending old data is current.

There are now **seven recorded model snapshots**, including the completed bounded
native-ground and Qwen14 baseline campaigns and the request-bound control-reference
campaign with its unsaved-command boundary. The successful
scripted workshop fixture has a separate
adapter-acceptance section and evidence link, never a model-comparison row. The
pre-publication combined local suite passed **702 tests** with one Linux-only skip; targeted
typing, static and JavaScript syntax checks also passed. No browser-only preview
or visual QA was performed in this background goal continuation. Publication CI
for `2a47c74964c6a7fab9938afacc79b5a6309bc15d` passed in run `34027753420`.
Full CI also passed for completed-Mistral publication `3692be5b18c0232560af92966ecef6c46d672463`
(run `34029396944`) and the Qwen native revision (run `34029621187`). The latter
also passed **71 targeted Linux tests**. Native outcomes remain separate from CI.
The earlier six-record publication suite passed **703 local tests**, with one
Linux-only skip. Its full CI passed in run `34030522017` at
`bdaa23042bb47860ae943be462e75f29b1435812`. The reference-control implementation and
expanded local suite passed **719 tests**, with one Linux-only skip, including the
completed-Qwen website record and designation-condition link regressions. Focused
Ruff, Black, typing and JavaScript syntax checks passed. Full remote CI passed for
the reference execution revision in run `34031851418`. The latest seven-record
publication passed **720 focused local tests**, with one Linux-only skip, including
a separate regression for its exact prompt evidence, defaulted designation modes
and unfinished condition. Targeted static, formatting and typing checks passed;
its full publication CI passed in run `34032869590`. The terminal reference update
is a separate publication slice: **515 targeted local tests passed**, five native
environment checks skipped, including endpoint and frontend test-double regressions.
Targeted Ruff, Black and JavaScript syntax checks passed. Fresh remote CI is tracked
on the PR; this local suite is not a native-model acceptance run or browser visual QA.

[Draft PR #125](https://github.com/lemoz/fort-gym/pull/125) is the integration surface.
The website/reporting code is separate from the frozen native execution revision.
Review, merge, production deployment and real-site acceptance remain open. Local
endpoint and frontend regressions are not browser visual QA or deployed acceptance.

Published-comparison checkpoint checks: 632 focused local regressions passed, one Linux-only
test skipped. The actual published three-model bundle is checked through the
campaign page/feed routes, with measured tick counts, adapter rejection counts,
final checkpoint status and usage retained. Focused Ruff/Black, JavaScript syntax
and targeted typing checks passed; global legacy static-check debt is separate.
