# Campaign status

Verified September 6, 2026. The Year-Two Autonomous Play goal remains active.

Local capacity investigation: one isolated Colima VM was created and is now
independently verified stopped. Linux/Rosetta and the retained game image loaded,
but DFHack's launcher failed at `setarch` under the default syscall policy.
A second start failed at VM SSH readiness before the narrow syscall candidate
could execute. There were zero model calls, gameplay commands, new checkpoints,
or cloud resources. The shared host was untouched. This is an infrastructure
failure, not a model/gameplay result. See [local runtime evidence and next
decision](CAMPAIGN_LOCAL_RUNTIME.md). No local native compatibility is claimed.

Latest published candidate: [PR #132](https://github.com/lemoz/fort-gym/pull/132)
contains the one-runtime native output-pause recovery fixture, bounded closed-port
settling correction, and versioned native evidence. Source
`43a53762c0dc819055a532c5fbb4fc4714fc2fa3` is verified on GitHub. The final full
local suite passed **1,862 tests with 10 skipped**; the focused suite passed
115 tests with one skip. Changed-file lint/formatting and targeted typing pass.
[Exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34060041534) passed.
The PR remains open: merge into main requires explicit owner approval at the
tool review boundary. No merge, post-merge CI or deployment is claimed for #132.

Native execution remained frozen at `ade9af102`. The v3 checkpoint saved a
zero-command pause, then restored its agent/runner/usage state in a second native
process and executed one fresh 20-tick WAIT. The original automatic command stopped
at a transient closed-port bind failure before claiming or launching the second
process. After independent teardown/port verification, an explicitly retained
driver completed only that second phase using the unchanged original source.
This proves the native recovery plumbing, not an uninterrupted automatic CLI run.
The later port-wait correction has unit/CI coverage, not a fresh native run.

Both process lifetimes are independently verified stopped and their listener is
closed. Synthetic usage moved from 10 to 20 fixture tokens; actual model calls
and metered model charges were zero. Native time moved from year 30, tick 19309
to tick 19329. This is not autonomous gameplay, a model comparison, or an endurance
handoff; no new final checkpoint was created after the WAIT. The existing host
has about 1.9 MB above its 1 GiB floor, so no further native allocation is planned
there without a viable capacity route. Historical saves/runs are unchanged.
No VM, disk expansion, production deployment or service restart occurred.

Latest merged delivery: [PR #131](https://github.com/lemoz/fort-gym/pull/131)
subtracts planned runtime/checkpoint copies before accepting the declared
free-space floor and omits retained archive folders from NEW runtimes only.
Original saves, archive directories and old runs are unchanged. Source
`53747032d59a14a8794fb70e3ad387d0d2fc84a2` merged as
`5c1de785bd6abdbe1bc9520529c6157e44793c0d`, with identical source/merged trees.
The full local suite passed **1,814 tests with 10 skipped**; a fresh focused
recheck passed 90 tests with one skip. Changed-file Ruff and targeted mypy pass.
[PR CI](https://github.com/lemoz/fort-gym/actions/runs/34057106803) passed;
[post-merge main CI](https://github.com/lemoz/fort-gym/actions/runs/34057329489)
passed. Full-tree lint/type debt remains separately disclosed in the PR.

Read-only host metadata estimated a new runtime at 105,377,792 bytes plus
9,023,488 bytes per retained checkpoint, using a historical save only as a size
proxy. At the observed free space, one checkpoint fit the 1 GiB floor estimate;
four did not. This estimate excludes a new source checkout and future growth;
it does not reserve disk or prove native execution fits. No original archive was
deleted, no runtime started, and no VM, model request or deployment occurred.
The current continuation fixture retains two runtime copies, so it is not made
executable by a one-runtime estimate. A latest-checkpoint restart that reuses one
owned runtime is the next implementation candidate, not implemented acceptance.

Previous merged delivery: [PR #130](https://github.com/lemoz/fort-gym/pull/130)
delivers the native campaign CLI, serial checkpoint continuation, local model
adapters, versioned campaign-only measurement hooks, and launch documentation
from clean main. Its source `ff5944bbd0be9acebee93d38276acd503ff4b597` is verified
on GitHub and merged as `e58ab9a019c86f6fced7216a9e15c9b7b47bee3e`; the source and
merged trees are identical. The full local suite passed **1,800 tests with 10 skipped** and targeted
campaign typing passed for 31 source files. Historical measurement hooks,
benchmark prompts and scoring code remain unchanged. [PR CI](https://github.com/lemoz/fort-gym/actions/runs/34055072007)
and [post-merge main CI](https://github.com/lemoz/fort-gym/actions/runs/34055309145)
both passed. Native acceptance at this revision remains unrun. No production
deployment, new VM or model request was performed for this source delivery.
The broader year-two and matched cross-model gameplay goals remain open.

Previous merged delivery: [PR #129](https://github.com/lemoz/fort-gym/pull/129)
merged persistent agent memory, checkpoint restoration, cumulative provider usage
and the separate exploratory campaign policy. Main at that delivery was
`6a699246976a12b9617407dbf817fc24f3f65886`; reviewed source is
`0fbdc96367384fafd06fc1fb4722e4559d86d0e3`. The final full local suite passed
1,160 tests with five skips, and 77 focused foundation tests passed. Its
[PR CI](https://github.com/lemoz/fort-gym/actions/runs/34052891694) passed.
Post-merge main CI is a separate check. This is a Python agent API delivery,
not the native campaign CLI, production deployment or year-two acceptance.

That extraction preserves main's historical benchmark prompt, schema, and review
logic. It is not merged back wholesale over this integration branch's later
experimental benchmark changes. The newly corrected partial-token accounting
and regression tests are backported here: a missing usage component remains
unknown, and a provider error carrying partial usage is not declared nonbillable.
All 79 focused accounting, checkpoint, policy and replay tests passed on this
backport; changed-file Ruff and `git diff --check` also passed.
The next runtime delivery should build from reviewed main and preserve its
historical-protocol checks, not silently overwrite them with the integration file.

The local checkout now also has an explicit `github` remote targeting
`https://github.com/lemoz/fort-gym.git`; the existing local-clone `origin` is
preserved. The foundation branch selects `github` as its push remote. Explicit
GitHub head verification remains the publication proof.

Remote delivery: the read-only campaign website is now merged separately from the
large integration stack via [PR #126](https://github.com/lemoz/fort-gym/pull/126).
That website milestone merged at `97e4533abe0194b99c463e2fffe8cfcfb9191581`; its reviewed source head
is `f15c47830974c5490b50df5f3f12af40d64aa8da`. Its final full local
suite passed **1,064 tests with 5 skipped**; 35 focused website tests passed.
Ten terminal native records, two read-only evidence endpoints, the campaign page,
and exact condition links are included. VM and gameplay-runner changes remain in
the separate draft [PR #125](https://github.com/lemoz/fort-gym/pull/125).
[Final PR CI](https://github.com/lemoz/fort-gym/actions/runs/34044644492) and
[post-merge main CI](https://github.com/lemoz/fort-gym/actions/runs/34044875137)
both passed. Review was implementer source review, not independent peer approval.
No deployment hooks, environments, or deployment workflow were configured at the
pre-merge check. The production website was not deployed or restarted. Main is
merged back into the integration branch, preserving the immutable evidence links
and avoiding duplicate mobile Campaigns links; 62 reconciliation regressions passed.

Earlier delivery: [PR #127](https://github.com/lemoz/fort-gym/pull/127) merged the
native drink observation correction; [PR #128](https://github.com/lemoz/fort-gym/pull/128)
merged the audited long-v2 result and eleventh recorded website row. Remote main
was `3a52860e7b14bf9e3ebd6c268a59f7865f60a651`. Both PR CIs passed, as did
post-merge inventory-fix CI. The full local suites passed 1,082 and 1,065 tests
respectively, each with five skips. All three website/measurement/result milestones
are merged back into this integration branch. No production deployment occurred.

Latest native result: `local-long-v2-qwen35-20260906-a` stopped at a model output
limit, with **42 commands, 53,500 native ticks, 45 returned/accounted responses
and 442,693 tokens**. Execution remained frozen at `60fd084`. One carpenter's
workshop completed and five beds were manufactured, but none was placed and no
farm completed. Seven citizens remained; year two and sustainability are unproven.
See the [terminal result](LOCAL_LONG_V2_RESULT.md) and its versioned evidence bundle.

The last response spent its 2,048-token output allowance on reasoning and returned
no action. All returned usage is accounted for; this was not a request timeout,
native execution, fortress collapse, or exhaustion of the overall spending cap.
The first segment's cursor-32 handoff was successfully resumed. Periodic checkpoints
8/16/24/40 passed independent verification, but two later commands and the final
response remain beyond cursor 40. The final native save is retained as verified
forensic evidence, not a reconciled agent/trace/usage checkpoint. Do not automatically
resume cursor 32 or 40 over those later records.

Both isolated games, the model and tunnel are independently verified stopped.
Production revision `47c035f` and services are unchanged. Local model API charges
are zero; infrastructure, hardware and electricity costs remain unmeasured. No
new VM, historical deletion or production deployment was performed.

A read-only native inventory scan found 46 drink units while the UI still reported
60. The separately merged reader counts native units with explicit scan quality;
115 observation regressions and read-only native acceptance passed. Historical
observations are unchanged; food remains a freshness-unverified UI estimate, not
a measured production flow. This integration branch now forwards stock source/scan
metadata into the campaign prompt and labels numeric validation separately from
freshness/accessibility; 124 focused integration regressions passed. No new campaign
has used the correction yet.

The integration candidate now checkpoints fully-accounted no-action output stops
with the [v3 recovery protocol](CAMPAIGN_OUTPUT_LIMIT_RECOVERY.md), including a
pause before the first game command. Controller continuation preserves usage and
the action cursor, does not automatically retry, and consumes the unchanged
campaign allowances. Public feed/profile status and the website label distinguish
this pause from gameplay collapse. Synthetic save/load and transport coverage is
not real native acceptance; the historical long-v2 result is unchanged.

Recovery commit `6f5f2a86f4988e7a3311a2f22735848d98b9856c` is pushed and its
GitHub CI passed. Final focused validation passed 247 tests with one skip. The
broader local run had one pinned-M1b-image/current-hook comparison failure outside
that commit, explicitly retained in the [recovery proof limits](CAMPAIGN_OUTPUT_LIMIT_RECOVERY.md).

The [exact-prompt output-budget diagnostic](OUTPUT_BUDGET_DIAGNOSTIC.md) is now
prepared: two local requests comparing 2,048 and 4,096 completion tokens, with
every other serialized field unchanged and zero native actions. It is not run.
The tool reviewer blocked transfer of the private source prompt from the stopped
test host, so no model generation or source copy has occurred.

Next: native acceptance of this recovery path, then an explicitly declared
reasoning/output allowance without enlarging or rewriting the historical
condition. The existing acceptance disk is near its free-space floor; no new
runtime copy, historical deletion, volume expansion or VM has been performed.
The goal remains autonomous sustained play and repeated cross-model evaluation,
not observation tests or another infrastructure acceptance run.

Earlier: the [long local attempt](../experiments/evidence/local_native_llama_long_timeout_20260906.json)
stopped at an inference timeout on request four. **Three returned responses,
21,429 accounted tokens, three committed commands and 1,000 native ticks** are
verified. One dispatched request has no returned usage. Two workshop commands
were rejected (stale pathfinding cache and occupied footprint); one WAIT was
accepted. Population remained seven, food 45, drink 60 and wood three. Nothing
was constructed. This is neither a completed campaign nor fortress collapse.

The failure occurred before the first scheduled cursor-8 checkpoint. Zero periodic
native snapshots were exercised; there is no resumable campaign checkpoint. The
final native save at year 30, tick 20309 is separately retained as forensic evidence:
127 regular files and 8,621,334 bytes, with its inventory independently verified.
It must not be treated as an agent/trace/usage checkpoint or silently replayed.
The copied game, model and tunnel are independently verified stopped. Production
is unchanged. Execution was frozen at `034a0e87a1c283763bd494dab269f3d2a2cac9c0`;
[its CI passed](https://github.com/lemoz/fort-gym/actions/runs/34041391431).
Ten terminal model records are included in website source, not production.

The separately declared [long-v2 condition](../experiments/campaigns/local_native_llama_long_v2.json)
changes only the generation read timeout from 180 to 600 seconds. The local server
was still generating when v1 canceled its fourth request. Keep all gameplay
instructions, weights, sampling, token and dispatch limits unchanged and begin
from the original save. The independent segment deadline remains 7,200 seconds;
v2's declared decision scheduling reserve is 1,944 seconds. These are execution
bounds, not completion estimates. The terminal follow-up is described above;
configuration alone is not native-game evidence.

Earlier: [Qwen3.5 9B with thinking enabled](../experiments/evidence/local_native_llama_thinking_20260906.json)
produced autonomous resource growth: **wood stock increased from 3 to 12**.
Eight accounted responses used **58,359 tokens** and advanced **5,000 native ticks**.
Three gathering commands were accepted, two chopping commands rejected, two changed
chopping commands accepted, and one WAIT accepted. Native receipts report ten shrub
and two tree designations; these are not counts of completed harvests.

The cursor-8 checkpoint covers every response and command across two digest-linked
segments. All measured prompt counts matched returned usage. Every response included
server-separated reasoning, retained privately and included in reported completion
usage. Both copied games, the model and tunnel were independently verified stopped;
production remained unchanged. Execution stayed at
`91ba6df9f79b3a8d43bb4e862e71080258d99910`;
[its CI passed](https://github.com/lemoz/fort-gym/actions/runs/34038331022).

No construction was initiated or completed. Population stayed seven, food 45 and
drink 60. The dispatch cap was reached, not gameplay collapse. This is neither a
functioning-fortress assessment nor causal proof that reasoning mode solves gameplay:
the two short conditions also differ in output and execution bounds. That publication
included nine terminal native model records in the website source. No production deploy,
merge or browser visual acceptance is claimed.

Next: move from resource acquisition to completed production, then endurance.
The separately declared [long local condition](../experiments/campaigns/local_native_llama_long_v1.json)
starts from the original save and allows 32 decisions in one live copied game,
with native/agent/trace/usage checkpoints every eight decisions. Its two-segment,
64-dispatch and 2,000,000-token limits do not enlarge any historical campaign.
The model, gameplay instructions, action reference and sampling are unchanged
from the short thinking condition. Its timeout result is recorded above.

The opt-in `periodic_checkpoints/v1` policy retains a durable checkpoint index
before another decision. Intermediate snapshots share the segment's original
parent; only the final checkpoint is the normal controller handoff. The controller
checks their identities, calendar, usage and retained trace prefixes. A later
unreconciled failure does not make an earlier checkpoint current. Its separately
captured native save is forensic evidence, not permission to replay actions.

The existing acceptance host had 2,453,381,120 bytes free at preflight. New decisions
stop below a declared 1 GiB free-space floor; native snapshot copies also check
their measured size against that floor. These checks are not a filesystem quota
or protection from unrelated disk growth. No historical runtime, private save or
evidence is deleted or moved. Legacy short-run configurations are unchanged.

Earlier: [Qwen3.5 9B with the typed local adapter](../experiments/evidence/local_native_llama_typed_20260906.json)
finished its bounded non-thinking attempt: **16 accounted responses, 142,218 tokens,
16 WAIT commands and 1,600 native ticks**. It initiated no gathering or construction.
Population remained seven, food 45 and drink 60. Two digest-linked checkpoints end
at cursor 16 and cover every response and command. Every committed prompt count
matched returned usage, with current facts and request hashes verified.

Both isolated games, the local model and reverse tunnel were independently verified
stopped. Production revision, services and original paused calendar were unchanged.
Execution was frozen at `f04b3f92bfadf08da92039d373ee1bb62eee6e49`;
[its CI passed](https://github.com/lemoz/fort-gym/actions/runs/34037691409).
This is a dispatch-limited pause, not a model ranking, functioning fortress or first
anniversary. That publication included eight terminal model snapshots in the website source;
no production deployment or browser visual acceptance is claimed.

The separately declared [thinking-mode follow-up](../experiments/campaigns/local_native_llama_thinking_v1.json)
keeps the same weights, observations, control reference and original save while
changing reasoning mode and its explicit execution allowances. Its actual result
is recorded above; unlike short conditions are not model rankings.

Earlier: the [factual designation-reference condition](../experiments/evidence/local_native_designation_reference_20260906.json)
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
[typed-contract follow-up](TYPED_ACTION_CONTRACT.md) copied all three examples exactly
with 5,303 additional accounted tokens. This is not an established cause of earlier
gameplay choices. The larger typed grammar failed a provider-free fit check on all
fourteen historical native requests under their existing 22,000-byte bound, even
after older history was removed. No historical condition was enlarged or resumed.

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

Terminal-result publication `5e595ecd826980b3d25fa57f7cdc5ba96f5fe7af` passed remote
CI run `34034704331`. The subsequent typed-contract implementation and paired
diagnostic passed **531 targeted local tests**, with five native-environment skips;
focused static, formatting, typing and JavaScript syntax checks passed. Its new
publication revision has separate CI and no new native-gameplay acceptance claim.

[Draft PR #125](https://github.com/lemoz/fort-gym/pull/125) is the integration surface.
The website/reporting code is separate from the frozen native execution revision.
Review, merge, production deployment and real-site acceptance remain open. Local
endpoint and frontend regressions are not browser visual QA or deployed acceptance.

Published-comparison checkpoint checks: 632 focused local regressions passed, one Linux-only
test skipped. The actual published three-model bundle is checked through the
campaign page/feed routes, with measured tick counts, adapter rejection counts,
final checkpoint status and usage retained. Focused Ruff/Black, JavaScript syntax
and targeted typing checks passed; global legacy static-check debt is separate.
