# Astra standard-input experiments

Owner approved September 7, 2026. This is the next implementation and research
phase of Year-Two Autonomous Play and Cross-Model Evaluation, not a replacement
for its year-two, multi-model, website, and remote-delivery requirements.

## Goal

Establish how far GPT-6 Astra Medium can independently play and develop a Dwarf
Fortress settlement through standard game controls, using a clear, readable
interface. Preserve optional DFHack shortcuts, measure their effect separately,
and make each run inspectable and reproducible through the website and remote
repository. Target a functioning fortress after a full elapsed game year, then
continue beyond the first anniversary without human gameplay rescue.

## Experimental sequence

1. Connect the existing keyboard executor to the requested subscription-backed
   Astra transport. Capture the full screen and visible selection information.
   Check menu navigation, workshop ordering, digging, and building placement as
   short diagnostics, not an additional historical acceptance ladder.
2. Improve viewport size and readability before introducing extensive custom
   menus. Validate changes against what the playing model actually receives.
   Version the display profile and preserve the previous condition.
3. Run an open-ended fortress attempt. The model chooses its strategy, observes
   outcomes, and can make mistakes and recover. Missing old benchmark milestones
   and individual dwarf deaths are not automatic exploratory-run stop conditions.
4. Once the interface works, compare standard input against standard input plus
   explicit DFHack shortcuts. Start with three paired attempts from matching
   starting saves, with the same observations, memory, display, and declared
   resource budgets. Treat these as preliminary comparisons, not a model ranking.
5. Reuse the stable configuration-driven harness for other models. The parent
   goal still requires at least three evaluated models and repeated evidence.

## Conditions and evidence

- Controls and observations are independent, declared settings. Keyboard input
  does not imply screen-only perception. No privileged-state summary is silently
  included in a condition labelled screen-only.
- Standard input uses native game-interface events. The first standard-input
  experiment cannot silently fall back to direct job insertion or other shortcuts.
- Shortcuts remain available in their separately declared condition. Log each
  action route. Do not conflate UI shorthand with instant completion of work.
- Compare elapsed game time, population, production/consumption/reserves, useful
  completed infrastructure, recovery, model usage, and reported costs. Missing
  evidence stays unknown. Queue acceptance is not completed production.
- Distinguish model decisions, missing controls, observation defects, provider
  failures, infrastructure failures, and budget-limited pauses. Fix harness
  defects between attempts; do not silently rescue or rewrite a comparison run.
- Retain source revision, model and reasoning effort, transport, prompt, memory,
  control profile, observation profile, display dimensions, starting-save identity,
  action/observation records, checkpoint lineage, usage, and termination reason.
- Record actual charges, estimated charges, subscription usage, and reservations
  separately. Existing spending, privacy, infrastructure, and deployment bounds
  still apply. This research goal does not renew an expired GCE authorization.

## Delivery and completion

This phase requires a working Astra standard-input integration, verified readable
observations, recorded autonomous attempts, and an evidence-backed account of
capability and remaining limitations. The website must identify the exact run
condition and expose recorded progress, failures, and usage. Tested implementation,
configurations, documentation, and shareable result manifests belong in the remote
repository. Private native assets remain outside public Git history.

Native gameplay, live website acceptance, and reviewed/merged source delivery are
distinct proof states. Passing an adapter fixture does not complete this phase.

## Start state

The prior Qwen run is stopped and preserved. A synthetic Astra Medium response
verified the subscription connection, not a native gameplay adapter. Implementation
starts on `codex/campaign-codex-subscription`; no new native attempt is claimed here.
The app's existing year-two goal was observed paused at phase start; its pause is
controlled by the user interface, independently of this approved project work.
It was subsequently verified active on September 7. The readable-screen profile
and first synthetic Astra comparison are published in draft PR #137; current
evidence and remaining native work are tracked in [Campaign status](CAMPAIGN_STATUS.md).

## Current native result: checkpoint 711

Window q completed 64 accepted Astra Medium standard-input decisions on source
`167d22945feb9c3fa031408946fcc7503ad5dc39`, using screen text/v1 at 120x40 and
v4 native saving. The verified new checkpoint 711 preserves 49,200 added ticks
and 192,600 retained ticks, 47.8 percent of one full elapsed year. All 12 dwarves
remain alive; installed beds increased five to six, drinks 179 to 337, and food
changed 82 to 56. Food coverage was 64 complete readings and one unknown.
These counts do not establish sustainable production or accessibility.

All 791 responses and 25,439,454 all-attempt tokens are retained, including both
historical losses totaling 23,200 ticks. Independent save, gameplay, food, clock,
subscription-event usage and teardown audits passed. The outer operator completed
with a retained final container-check warning (exec exit 128, subsequently observed
container exit 0). Its cause is unverified, and the warning remains visible rather
than being relabeled clean. No gameplay rescue, restart or budget extension occurred.

The actual result, warning display and next window r are pushed at
`2e535166fc96633438c19017a52256b45ab36790` in draft PR #137. All 3,359 local tests
passed, and the local page/API matches that exact committed publication. Remote
CI `34286271507` also passed at that exact head; no merge, production deployment or browser visual
acceptance is claimed. Window r subsequently failed after 23 responses: 22 committed
decisions added 6000 ticks, and a dialogue interrupted the next clock request after
691 more ticks. The loop used the pre-keypress overlay as its interruption baseline
instead of the recorded post-input screen. The attempted save did not persist;
checkpoint 711 remains the last verified save, with 6691 observed new ticks unsaved.
All 814 responses, 26113503 campaign tokens and 26182507 all-attempt tokens are
retained. Native load, subscription receipts and full teardown were audited. The
repair at `c12103397c5bc220c0fa3fc32afa5e7758ff7196` passes 123 focused checks and
3375 full-suite tests (10 skipped), with exact-head GitHub CI `34289603394` passing;
native validation and explicit loss-aware
restart support remain open. No restart, replay or new completed-window
claim has been made. See Campaign status for the failure audit and source identity.

## Historical interface result: window h

Latest autonomous continuation, September 8: window h passed four v3 native
saves after all 64 new Astra Medium decisions. Checkpoint 296 retains 63,600
elapsed ticks, about 15.8 percent of one full year. Independent audit verifies
all 312 accounted responses, 10,215,904 campaign tokens and 10,284,908 including
historical failed deliveries. All memory and trace/journal prefixes remain
intact, including the previous lost branch. No new restart or lost progress.
The game/container/VM are stopped. The last save is verified in process; the
next runtime must verify its fresh load before calling the model again.

The website continuation record is authored on source `893b7ff10`; private
gameplay evaluation remains separate from its non-content operational counters.
The next declared window keeps 64 total decisions in one native process rather
than reloading every 16. This tests menu continuity, not a new strategy or model,
and exposes a longer unsaved tail on failure. No budget extension, memory reset,
usage reset or fallback is added. The next window is not started; the full goal
remains unfinished and no merge or production deployment is claimed.

### Earlier interface and campaign results

The combined native keyboard and 120x40 viewport diagnostic passed on September 7
at `0ef33ff70`. It audits the full version-matched catalog, exercises ordinary
menu/pause events, verifies readable captures and an explicit clock step, and
tears down the owned runtime. It does not count as model-selected play. The next
step was Astra's live screen-to-keypress bridge; no further historical gate
ladder was introduced.

The subsequent native campaign completed eight Astra Medium decisions, 62 native
key events and 6,000 elapsed ticks at `ea3812dd7`. Native checkpoints at cursors
four and eight preserve memory, usage and trace across process reload. The model
selected all gameplay. Courier and local-port failures remain documented and
accounted separately; the final continuation did not replay prior actions.
This is early gameplay and integration evidence, not sustained fortress success.
The subsequent endurance window completed 64 more decisions, preserving the same
campaign and cumulative usage through four new native checkpoints. Totals are
72 decisions, 357 confirmed key events and 25,000 elapsed ticks. The native game
and VM are stopped, and an independent audit verifies all checkpoint prefixes
and the explicit budget-extension history. This is about 6.2 percent of a full
game year, not sustained fortress success.

The website implementation now exposes recorded non-content keyboard milestones
and unreported subscription charges; source and website head `03190cc48` passed
remote CI in draft PR #137. The final checkpoint is preserved for continuation.
Production deployment, visual acceptance and matched comparisons remain open.

The next reusable-runtime window stopped at 100 committed decisions and 29,000
elapsed ticks. Model response 101 encountered a build-menu clock timeout after
its keys were sent. Native state, usage and a cursor-88 checkpoint are retained;
newer actions must not be replayed from that older checkpoint. Teardown and
3,300,796 total tokens including historical failed deliveries independently
verify. A tested correction returns blocked-clock feedback to the model without
choosing gameplay. Native validation and forward-only recovery subsequently passed.
The website now has a separate non-content interruption record; this failure is
not retroactively turned into a successful or budget-limited campaign window.

The native recovery at `914ac0721` verifies checkpoint 101 from the newest state,
with unchanged model memory, responses, usage and 29,000 elapsed ticks. It made
zero model calls, sent zero keys and requested zero ticks. Source bytes and the
original failed clock receipt remain unchanged. Independent audit verifies native
checkpoint lineage and teardown; exact-source CI and 134 focused checks pass.

The declared continuation at `d37a1b42f` has started from that recovered checkpoint,
using six 16-decision segments and the existing cumulative 256-dispatch/eight-million-
token extension. New Astra responses have reached the native game. No new model,
strategy instruction, memory reset or budget extension is introduced. Terminal
gameplay outcome was subsequently an input-rejection interruption: response 184
contained unsupported key names after 183 committed decisions and 44,000 elapsed
ticks. No native input or clock dispatch occurred for the rejected response.
Independent audit verifies five new checkpoints through 181, all usage, and full
game/container/VM teardown. The newest state must be reconciled without rollback.

A correction now records a fully accounted unknown-key response as rejection
feedback, preserving its original content and usage while sending no keys or ticks.
The model chooses its own correction; attempted memory is not applied. Offline
checkpoint/resume and rejection tests pass. Native validation and recovery later
passed at `c537e3e79`, independently verifying checkpoint 184 and original
evidence/usage preservation with no model/key/clock calls. All recovery resources
were stopped. This is a harness handling issue after a model typo, not evidence of
fortress collapse or completion of the full experimental goal.

The next declared window at `6493cba58` resumed from checkpoint 184. Its first
model response recognized the rejected input and changed menu, then chose its
own navigation; two newly accepted responses were confirmed in the native trace.
The window keeps Astra Medium, raw 120x40 screens and 16-decision cadence, while
declaring a larger cumulative 1,024-dispatch / 40-million-token allowance.
Fresh per-call quota admission and no fallback/purchase/reset boundaries remain.
The updated website records interruption 183 and recovery 184, not live activity.
The source is pushed with passing exact-head CI; no merge or production deploy.

That window later stopped after 16 accepted responses because native saving
timed out in a unit screen. Trace cursor 200 records 46,000 elapsed ticks, but
retained game files still match checkpoint 184. Independent audit confirms
trace/usage preservation, all 531,913 new tokens and full teardown. No worker is
live. Campaign usage is 6,465,867 tokens, 6,534,871 including historical failures.
The newer trace is not a resumable native checkpoint. Fix menu-sensitive saving
and explicitly record any discontinuity before another run; never discard usage
or present a rollback as successful continuation.

September 8 continuation update: window h completed through verified checkpoint
296. Window i then returned 15 further responses and advanced 2,000 ticks before
a zero-tick workshop-menu timeout. The latest forensic save was recovered forward
as checkpoint 311, with a second fresh native load and independent audit. All
327 responses, 65,600 ticks, memory and 10,696,954 campaign tokens are preserved;
all-attempt tokens are 10,765,958. The original interruption, an OOM recovery
failure and the earlier 2,000-tick lost branch remain retained, not reclassified.

Clock feedback now covers this exact menu, with a strictly verified zero-tick
fallback for other focuses. A separate narrow memory repair releases redundant
parsed trace copies during saving; the successful provider-free recovery stayed
within unchanged limits. This does not prove memory headroom or year-two play.

Window j at `bc7a23aef` completed from checkpoint 311 with the same 64-decision
single-process bound, Astra Medium, standard input and existing cumulative
1,024-dispatch / 40-million-token allowance. All 64 new decisions committed and
added 11,400 ticks, reaching independently audited checkpoint 375 / 77,000 retained
ticks. All 391 responses and 12,838,159 campaign tokens are preserved; all-attempt
tokens are 12,907,163. Seven dwarves are alive, completed farms increased two to
four, installed beds and workshops remain three each. Food stock, production and
sustainability remain unverified. The private evaluation is not fed to the player.
Seven decisions advanced time and 57 requested none; no clock-feedback branch
was exercised. Teardown passed. The final save still requires its next fresh load.
Authored aggregate publication and unchanged continuation k are pushed at
`7416f65b2ee464b09963d65733b692bf1a9c03b6` in draft PR #137. Local tests and the
private-to-authored count reconciliation passed; exact-head CI `34244374506`
passed 2,777 tests with 100 skips. Window k started under its unique owner;
the first three observed actions committed and added 2,000 ticks, without a
completed-window or new-checkpoint claim.
The same owner subsequently completed its bound and verified teardown.
The source page leads with checkpoint 375 and
before/after counts, retaining older failures, not presenting a live activity feed.
No merge, production deploy, browser visual acceptance or full-goal completion.

Window k completion: checkpoint 439 retains 101,000 ticks after 64 new responses
(63 accepted inputs, one zero-dispatch rejection) and 24,000 actual new ticks.
All 455 responses, 14,814,687 campaign tokens and 14,883,691 all-attempt tokens
are preserved. Seven dwarves remain alive; completed farms increased four to
five, installed beds three to four, and existing drink units 134 to 162. No
sustainability claim. The model requested 26,000 ticks; a verified 2,000-tick
workshop-menu deferral was followed by 6,000 further model-led ticks without an
operator correction. The generic clock-timeout fallback was not exercised.
Independent save, rejection, clock and gameplay reviews and complete teardown
passed. The authored 439 record, clock-count reporting and unchanged continuation
l are pushed at `8caa3e11acc5d19ddea8b28bd917f9659e733d21` in draft PR #137. All
2,883 local tests passed (ten skips); exact-source CI `34249380279` passed 2,793
tests (100 skips). Window l has started on that frozen source; the first nine
observed decisions committed with zero new clock ticks after the native load
boundary. That early in-flight read was later superseded by completion and
verified teardown, recorded below.
The full original goal remains active, with no merge or production deployment.

Window l completion: all 64 new accepted decisions and 14,000 actual ticks reached
independently audited checkpoint 503 / 115,000 retained ticks, about 28.5 percent
of a full elapsed year. The parent 439 save loaded in a fresh native process with
a verified actual 120x40 screen; final 503 awaits its next fresh load. Seven
dwarves remain alive, completed farms/beds/workshops stayed at five/four/three,
and existing drink units increased 162 to 172. Sustainability remains unverified.
Seven decisions advanced time and 57 requested none. No input rejection, menu
deferral or clock-unavailable timeout occurred; no new branch-coverage claim.

All 519 responses, 16,682,250 campaign tokens and 16,751,254 all-attempt tokens
remain accounted. No loss, replay, memory reset, strategy intervention or budget
extension. Historical failures and the inherited 2,000-tick loss remain recorded.
All independent audits and game/container/VM teardown passed. The authored 503
page record and unchanged window m are pushed at `c9b8607cc` in draft PR #137.
Focused tests and static checks passed; the broader suite's only failure was a
localhost sandbox restriction that passed on its scoped rerun. Exact-source CI
`34253088052` passed 2,795 tests with 100 skips. Window m then started on frozen
source `c9b8607cc` from checkpoint 503 with unchanged model, controls, observation,
memory and cumulative limits. Its VM/image/container startup passed and the first
model request reached the host exchange. No completed window or newer audited
checkpoint was claimed at that early observation. Its terminal state follows.
No merge, production deployment, visual acceptance or full-goal completion.

Window m's native game subsequently completed 64 accepted decisions and 7,200
ticks at checkpoint 567 / 122,200 retained ticks (30.3 percent of a full year).
Population grew seven to twelve, with zero recorded citizen deaths. Completed
farms/beds/workshops remained five/four/three; drink units increased 172 to 181.
Four decisions advanced time and 60 requested none. All 583 responses and
18,636,365 campaign tokens remain accounted (18,705,369 including failed attempts).

The outer operator failed during exchange-directory observation after responses
returned, with command exit 137. The cause remains unverified. Independent native
save/lineage, gameplay, clock, usage and teardown audits passed, but the original
outer error is retained and published as a warning, not rewritten as clean success.
There was no new loss, replay, restart, rescue, memory reset or budget extension.

A separate provider-free probe fresh-loaded 567 and verified 27 native-predicate
food units with agreeing item-vector, stack-size and repeated-scan evidence.
Menu, screen, calendar and world-save files stayed unchanged; no model calls,
keys or ticks were added, and teardown passed. This remains isolated measurement,
not a model-observation change, production count or sustainability verdict.
The authored 567 API/page update passed 150 focused tests and scoped static checks.
Main commit `4e746f0fa` and isolated food-report commit `e15c53cd5` are pushed
with exact remote heads verified; new-head CI is not inferred from prior runs.
Terminal-observation handling and an explicitly declared private food adapter are
now implemented at `567251e7414795d52c87e1450eca146bfb419069`, pushed in open
draft PR #137. Full local production-code testing passed 3,087 tests with ten
skips; two later-added tests passed in the focused rerun. Scoped static checks
passed, without claiming repository-wide typing cleanliness.

Window n completed from checkpoint 567 on that frozen source. All 64 responses
were accepted and all 21,200 requested ticks advanced, reaching independently
audited checkpoint 631 and 143,400 retained ticks. Its first integrated private
food reading was 27 units and its final complete reading was 82; all 65 boundaries
were complete and the final count matched the saved state. Twelve dwarves remained
alive. Completed farms/beds/workshops increased five/four/three to seven/five/four;
drinks changed 181 to 179. This is inventory growth, not production attribution. Actual model
requests retain only screen, memory and factual control feedback; the private
evaluation count does not alter the playing condition. Source-specific CI
`34259573627` subsequently passed; earlier source `4e746f0fa` also passed its CI.
The owner exited successfully without a terminal-observation warning. All retained
evidence audits and teardown passed, and the local VM profile was freshly observed
stopped. All 647 responses and 20,850,223 campaign tokens are accounted, with
20,919,227 all-attempt tokens; historical loss, failed runs and unknown charges
remain explicit. Full-year survival, repeated model comparisons, merged/deployed
website delivery and full-goal completion remain open.

The separately developed API/page food-count projection is pushed and
remote-verified at `1f083183f623e64323960967c669efa51607343b` on
`codex/campaign-food-outcomes-v1`. It displays reviewed endpoint units and
complete/unknown coverage, leaves earlier food unknowns intact and keeps native
inventory distinct from accessibility and sustainability. Full local validation
passed 3,134 tests with ten skips after resolving a sandbox denial of a local
socket test; 163 focused tests and scoped static checks passed. No native result
fixture was published. After n's teardown and audits, the display was integrated
as `1eacaa581` with its real checkpoint-631 result; 166 combined focused tests,
all 3,137 local tests (ten skipped) and scoped static checks passed. Publication
commit `15af09ffeaf5022be0b2b4c91c858b718fbb522a` is pushed and remote-verified in
draft PR #137. Exact-head CI `34265344540` passed. Window o used that frozen source
and unchanged conditions, memory and limits. Its fresh load matched checkpoint
631, but after 64 accepted inputs and 21,200 new ticks the pre-save identity probe
rejected a screen-stack entry before issuing the save request. The entry type
was not recorded; the underlying cause remains unverified. The error label says
malformed JSON, while the raw response is a Lua assertion. Checkpoint 695 does
not exist; the runtime save files still match checkpoint 631 except the event log.

Independent failure and publication audits passed. All 711 responses, 22,819,077
campaign tokens and 22,888,081 all-attempt tokens remain retained. Twelve dwarves
were alive, with unsaved drinks 228 and food 43; 63 food measurements were complete
and two unknown. Teardown was verified. The 21,200 unsaved ticks must not be
silently lost from future restart accounting or counted as saved progress.
Next is a provider-free reproduction and save-path fix, not another model window.
The separate v2 model-selection change is pushed as `99bfde62f`, integrated after
teardown as `ad37b9b32`, and passed 3,181 full-suite tests with ten skipped. No
alternative model was called or evaluated. Combined source and the audited failed
attempt are pushed and remote-verified at `04ee719b3`; exact-head CI `34271339605`
and 214 combined focused tests passed. Documentation clarification `d0f00e225`
records that the local preview at port 8857 was unreachable; the data adapter
still ends at completed checkpoint 631, not the failed attempt. No live website
update, merge or deployment. The full year-two,
repeated-model and website-delivery goal remains active.
