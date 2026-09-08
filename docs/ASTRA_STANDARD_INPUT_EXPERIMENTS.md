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

## Latest interface result

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
boundary. It remains in-flight under the same
owner and mandatory teardown, not a completed window or new audited checkpoint.
The full original goal remains active, with no merge or production deployment.
