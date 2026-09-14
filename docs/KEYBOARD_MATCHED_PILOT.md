# Matched native-keyboard model pilot

The [cohort plan](../experiments/keyboard_matched_pilot_20260910/cohort.json)
declares six independent campaigns: Astra Medium, Sol Medium and Terra Medium,
two starts per model. This is a configuration-only experiment declaration, not
a completed comparison, automatic scheduler or replacement for the Year-Two goal.
The existing Astra fortress continues independently and is not one of these six
fresh starts. No new model or native run is claimed by these files.

## Question and comparison design

Can the models establish and maintain observable fortress work under the same
standard-input conditions? Measure retained game time, living population and
recorded deaths, completed infrastructure, supply coverage, observed work,
adaptation, usage and stop reasons. Do not tune the prompt or intervene in the
game for one model after seeing its results.

The six campaign IDs and order are explicit. The first block is Astra, Sol,
Terra; the second reverses that order. This modest counterbalancing does not
eliminate time/provider effects. All trials reuse one native world snapshot;
they test repeatability of model-driven play from that world, not generalization
across world seeds. Model sampling and hidden provider revisions are not fixed
by the harness. Two replicates support preliminary observations, not a strong
capability ranking or a statistical significance claim.

Official [Codex model documentation](https://developers.openai.com/codex/models)
lists `gpt-6-astra`, `gpt-5.6-sol` and `gpt-5.6-terra`. Availability still depends
on the account/client and is not established by this plan or offline tests.
All three explicitly use Medium, retaining the owner's Astra choice and making
model identity the intended varying factor. There is no paid API or local-model
fallback. Subscription usage is recorded; an unreported charge remains unknown.

## Matching conditions

Each condition/trial pair is directly readable by the existing
`scripts.campaign_keyboard_trial` CLI. The files declare native keyboard v2,
screen-text v1 at 120x40, model-requested advancement capped at 2000 ticks per
decision, replacement memory v1, fresh empty memory/usage, and identical native
RPC, save, private food measurement and resource observation profiles. The
initial segment is 32 responses, with the same timeouts and admission threshold.

Use the exact shared starting snapshot receipt
`eaf5fa5a40014719e6c313f33497740e536a8faa1c90a84c4e09dcc380ac0595`.
This is the source exercised by the existing
[provider-free native fresh-start acceptance](../experiments/evidence/scripted_native_keyboard_fresh_trial_20260910.json),
not Astra's developed checkpoint 1025. Verify its full file inventory again at
launch and mount the retained seed read-only. Never turn the synthetic acceptance
responses into model results.

Before the first actual launch, bind one clean, committed, tested remote source
revision and built image, plus the cohort/config digests, in the retained launch
receipt. Every later trial must use those same execution identities. This plan
does not claim its source policy is a new runtime enforcement mechanism: the
existing owner/preflight and result audits must check it. A runtime or measurement
change between trials requires a new declared cohort, not an invisible repair to
the matching condition. The brewing-input correction passed its
[provider-free native inventory acceptance](CAMPAIGN_PRODUCTION_INPUTS.md#verification-and-native-acceptance)
on source `1bc49b9675b1c82ad502bbd6d8461c9cdbf077e9`; source/image binding at actual
pilot launch is still required.

Only one game and one existing owned local VM may run at a time. Match the
2-CPU/3-GiB VM, 2-CPU/1536-MiB networkless container and 256-task limit. Each bounded
owner tears down before another begins. These declarations grant no new GCE,
deployment, reset, purchase or spending authority.

## Start small, retain the path to endurance

The first-stage ceiling is 32 returned responses per attempt, 192 across all six.
That stage cannot establish year-two performance: even 32 maximum advances would
be only 64000 ticks. After the initial integration/outcome review, continue each
attempt from its own verified save with its own memory and cumulative usage.
Do not rerun the fresh-start CLI or inherit another model's authored history.

Each campaign declares the same cumulative ceiling of 1280 dispatches and
40000000 tokens. This is not an instruction to launch them all immediately and
is not a dollar reservation. Ordinary continuation windows still declare each
bounded segment. Compare at equal decision boundaries as listed in the plan,
report actual tokens alongside decisions, and treat exhausted allowance as a
budget-limited outcome. Fixed decision and token ceilings do not imply equal
compute, latency, dollars or realized simulation time.

If extension is warranted, declare the same changed bounds for a new comparison
condition and preserve the original censored outcomes. Do not selectively extend
the apparently strongest model and describe the results as budget-matched.
Reaching 403200 retained ticks is an endurance milestone, not automatic proof
of a functioning or sustainable fortress; continue into year two and assess the
operating evidence. The full goal also requires repeated evaluations and verified
website/remote delivery.

## Inspectable results and failure handling

Retain actual source/model/effort, starting snapshot, prompt origin, screenshots
or screen captures, actions/feedback, memory, checkpoint lineage, usage, native
metrics, resource observations and final cleanup. Publish only the selected
shareable result manifest and public projections, not private saves or prompts.

Keep game collapse, rejected controls, uncertain model delivery, provider failure,
infrastructure failure and admission/budget pauses separate. Preserve each failed
attempt under its original campaign ID; a replacement attempt is additional
evidence, not an overwrite. A no-dispatch pause is not a failed model trial.
Unseen production, ownership/accessibility, unknown costs and lost elapsed time
must not become favorable zeroes or unsupported success claims.

The current campaign website's recorded data is unchanged. Actual pilot records
and their matched-cohort comparison view still need implementation/acceptance
after native runs; this declaration does not mark that surface delivered.
