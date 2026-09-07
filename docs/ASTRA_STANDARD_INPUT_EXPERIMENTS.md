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
checkpoint/resume and rejection tests pass. Native validation and recovery remain
pending. This is a harness handling issue after a model typo, not evidence of
fortress collapse or completion of the full experimental goal.
