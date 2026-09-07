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
