# Fort Gym: Year-Two Autonomous Play and Cross-Model Evaluation

Owner-approved goal, September 5, 2026. Status: active implementation.

## Outcome

Build and ship a model-swappable laboratory for autonomous Dwarf Fortress play.
Achieve a functioning fortress through one full elapsed game year into year two,
continue exploring longer campaigns, and make cross-model performance inspectable
on the live website and reproducible from the remote repository.

Year two means the first anniversary of the starting save, not merely a calendar
year rollover. Reaching it is a checkpoint, not an automatic campaign stop. Elapsed
time alone is not proof of a functioning fortress or autonomous gameplay.

## Delivery sequence

1. Preserve and reconcile the working baseline. M1b is complete; do not repeat its
   acceptance campaign without a relevant regression. The environment-layer
   checkout has preserved the M1b implementation on the integration branch. Its origin is a local clone;
   the actual remote is https://github.com/lemoz/fort-gym.git.
2. Track actual game time independently of scores. Expose observed duration,
   first-anniversary progress, missing evidence, and run identity to the website.
3. Implement campaign checkpoints binding the game save, agent memory, configuration,
   action cursor, and trace lineage. Verify interruption and continuation without
   resetting the fort or replaying an already executed action. A preserved save or
   an SSE reconnect alone is not campaign recovery.
4. Make supported model selection configuration-driven. Verify at least two models
   on the same interface before expanding to at least three evaluated models.
5. Iterate inexpensive real-gameplay experiments toward a functioning first-year
   settlement. Classify missing controls, observation defects, provider failures,
   and policy mistakes separately. Change one hypothesis at a time where practical.
6. Continue successful campaigns beyond the first anniversary. Compare models from
   matching starting saves and declared conditions, with repetitions before strong
   claims. Publish inspectable growth, sustainability, adaptation, and cost profiles.

## Completion requirements

- One autonomous functioning fortress after a full elapsed game year; no human
  gameplay rescue or scripted strategy selecting the model's gameplay decisions.
- Persistent campaigns with tested save/resume and explicit budget-limited pause.
- At least three supported models, selected by configuration, with comparable
  experiment records and repeated attempts before strong model-ranking claims.
- Website: active campaigns, recorded gameplay, growth/decline, model/configuration
  identity, outcomes, costs, and evidence links. Verify delivery on the real site.
- Remote repository: reviewed and merged code, tests, setup instructions,
  configurations, and result manifests bound to the code used. Exclude secrets and
  restricted game assets. Local test success is not remote or website delivery.

## Experiment policy

Development experiments may change prompts, observations, memory, and controls.
Comparison experiments freeze those settings; changes create a new comparison
condition rather than rewriting old results. Track elapsed time, population,
production/consumption/reserves, useful infrastructure, recovery, and model usage.
Do not invent a single scalar that substitutes for gameplay outcomes.

Allow in-game mistakes, deaths, and recovery. A failed historical rubric is not an
automatic exploratory-campaign stop. Infrastructure failures and budget pauses are
not fortress collapse. Preserve historical protocols and results unchanged; this
campaign mode does not silently unlock, relaunch, or rescore frozen experiments.

Use inexpensive development calls within existing spending bounds. Record charges,
estimates, and reservations separately. Preserve credentials and infrastructure
isolation. This document does not expand resource authorizations by itself.

## Current checkpoint

- Remote main verified read-only at `82ee3e07859b2813fc4643d02aa034daecea6b18`.
- Environment-layer base: `236d3187c`; preserved M1b work and campaign foundations
  are now published on `codex/year-two-campaigns` (tested candidate `7490c8727`).
- M1b sealed GO: 16/16 gates and 26/26 runtime attempts (see acceptance decision).
- No year-two success, persistent checkpoint recovery, new comparison campaign,
  website deployment, or remote merge is claimed by this planning checkpoint.

## First implementation slice: observed game-time reporting

`fort-gym campaign-report /absolute/path/to/trace.jsonl` reads an existing trace
without modifying it, starting a game, or making model calls. The JSON report
counts actual `tick_advance.ticks_advanced`, checks supplied native calendar
samples, and distinguishes a first anniversary from a calendar rollover.
Missing, duplicated, discontinuous, or malformed samples do not become a false
year-two claim. Partial advances count their observed ticks, not their requested
ticks. Incomplete reports retain observed ticks while leaving total time unknown.

New run summaries persist this data as `campaign_progress`; the existing public
run-summary API exposes it. Older persisted summaries remain unchanged, with no
invented campaign fields. This first slice describes a single run, not a resumed
campaign chain. It explicitly does not assess fortress viability or autonomous
gameplay, and does not change historical score or gate verdicts.

Next: bind campaign checkpoints and run segments, then render the progress and
outcome profile in the website. Public API delivery in local tests is not a live
website deployment. The production health endpoint was reachable during baseline
inspection, but no new code has been deployed.

Verification: 109 focused campaign, summary, public-route, mock-run, and API tests
passed. The new module and tests pass Ruff and Black checks; `git diff --check`
passes. Existing dependency deprecation warnings remain. These are local working
candidate results, not clean-clone or remote results.

Release dependency: the public-summary endpoint used by this slice is itself part
of the preserved uncommitted baseline. Do not publish a partial commit containing
only its new field while omitting that endpoint. Package and test the baseline
before promoting the integrated campaign slice to the remote repository. Keep
existing unrelated changes intact; do not stage the entire worktree blindly.

## Second implementation slice: restartable agent state

The agent interface now declares campaign context and state export/restore.
The governed model adapter implements a JSON checkpoint containing the exact
recent memory window, compressed history, points of interest, plan/reviews,
pending outcome review, model/prompt/configuration identity, cumulative tokens,
response-accounting completeness, and decimal-exact reported model cost. API keys
and transport clients are not serialized. Independent-run memory exports and
usage-reset behavior remain unchanged.

Campaign agents must be initialized with `memory_path=None`: loading or updating
the old globally shared memory file could contaminate independent fortresses.
Set campaign identity before making provider calls. Restoring into an agent that
already accrued usage is rejected rather than silently rolling back that usage.

For the same campaign, segment run IDs no longer reset agent usage or provider
session affinity. Restore into a fresh configured agent, then set the new segment
run context. A pending action in this format is awaiting outcome review, NOT
execution. Resume must never reissue it simply because it appears in the snapshot.
Budget allowances are supplied externally; restoring a checkpoint does not grant
new spending authority. Unsupported agents explicitly declare checkpoint support
unavailable instead of pretending to preserve their state.

Still required before real campaign-resume claims: pair the agent state with a
completed native game save and a committed trace cursor, persist campaign lineage,
restore the game in an isolated runtime, and verify the next real action. DFHack
0.47.05-r8 documents [quicksave](https://docs.dfhack.org/en/0.47.05-r8/docs/tools/quicksave.html)
as requesting the native autosave mechanism; issuing that command alone is not
evidence that the save finished. Checkpoint-era usage must also be reconciled with
any later failed-segment charges so rollback never restores an obsolete spend
balance. These requirements remain open, not hidden behind the agent unit tests.

Verification so far: the broader existing governed-agent/memory/supervision set
passed 166 tests before the final fresh-agent/shared-memory guards; subsequent
focused tests cover those guards and next-decision prompt equivalence (113 focused
campaign, memory, summary, and public-route tests passed on the latest candidate).
Full-suite process `26877` completed: 2350 passed, 9 skipped, 7 failed. Six failures
were local socket sandbox restrictions. The seventh detected a new campaign hook
in the frozen M1b hook directory; the read-only probe was moved to the existing
inline Lua transport, leaving the accepted image unchanged. All seven affected
tests passed on the targeted rerun with local socket access. This is a full-suite
result plus targeted corrective verification, not a fresh all-green full run.

## Third implementation slice: native snapshot and checkpoint bundle

`run/campaign_save.py` requests the runtime's native `quicksave`, waits for a
cleared autosave request AND an updated world.sav, verifies the fortress stayed
paused at the same native calendar point, and copies/verifies the complete save
tree. The exact 0.47.05-r8 quicksave source was inspected in the accepted private
runtime image: it schedules its save through a GUI overlay, so command return
alone cannot establish completion. No new hook is added to the frozen image.

`run/campaign_checkpoint.py` binds that save to agent JSON, a committed trace
prefix/cursor, code identity, and an optional parent checkpoint digest. A final
manifest is published only after the files have been written and verified.
Materialization verifies the bundle and copies into a NEW save destination; it
does not overwrite a live fortress or claim that DF has loaded the new copy.

84 focused campaign-time, agent-state, native-save, and bundle tests passed.
These include simulated asynchronous saving, temporary RPC unavailability,
partial traces, modified files, source changes during copy, and refusal to
overwrite an existing save. The later real snapshot proof below supersedes the
initial save-test requirement; native loading and campaign recovery remain open.

Remote preflight: the existing website/API and DFHack services are running.
The deployed revision is `47c035f117f2a8663c2b276160d546c49f47a5da`. The private
SQLite registry query returned no rows/nonterminal runs, and a read-only native
probe found paused `region3` at year 30, tick 19309, with no autosave pending.
Cloud API authentication needs renewal, but the repository-configured Google SSH
key works for this existing host. No new VM, provider call, restart, or native
save has been initiated by these checks.

Publication candidate: `codex/year-two-campaigns` preserves the previously
uncommitted M1b implementation together with these campaign foundations. It also
inherits the existing calibration/design commit stack above remote main, so it
is a work-in-progress integration branch, not a merge-ready isolated campaign PR.
The staged credential scan matched only redaction rules and their fixture, not
credentials; no game assets, keys, or local run artifacts are included.

Repository-wide static checks are not clean: Ruff reported 14 findings in existing
agent/evaluation code and M1b tests; mypy initially reported 662 findings in 40
files, including two new checkpoint annotation issues that were corrected.
Focused campaign modules pass lint and have no remaining mypy diagnostics.
Do not represent this branch as having passed the repository-wide static gates.

## Real native snapshot proof: September 6, 2026 UTC

The clean remote candidate `7490c8727ee148439ff41b301f24ea0f072f111e`
passed all 94 campaign tests. Its provider-free native smoke then completed a
real `quicksave`, verified the copied save tree, and verified the same paused
`region3` boundary before and after: year 30, tick 19309. No gameplay ticks or
provider calls were requested. Both existing production services remained active;
their deployed code was not changed. No VM was created.

The prior on-disk save and completed snapshot are retained privately in
`/home/ubuntu/fort-gym-test/year-two-campaigns/artifacts/native-save-20260906-b/`
on the existing host. `result.json` SHA-256 is
`ca71bfd2032e864cced48e66f20f76827b92b9df2099f03476f2dd43234c2d3d`.
The versioned public evidence manifest is
`experiments/evidence/native_save_smoke_20260906.json`; game assets remain private.

Attempt `native-save-20260906-a` retained its original save and copied snapshot,
but did not produce a success receipt: the final native read hit the legacy
one-second CLI timeout. The implementation now uses a five-second status call
and bounded post-copy read retries without reissuing a save. Its regression test
passed locally and remotely. A separate Linux fixture correction makes simulated
same-size writes update their timestamp explicitly; no production check was weakened.

Two new scratch checkouts were created without modifying existing folders:
`/home/cdossman/fort-gym-test/year-two-campaigns` for the initial remote tests,
and `/home/ubuntu/fort-gym-test/year-two-campaigns` for service-account access to
the game save. The first user's home is not traversable by the service account;
existing permissions were preserved. Runtime evidence belongs to the latter.

Next is an isolated load of the verified copy. The existing game configuration
has `PAUSE_ON_LOAD:YES`; do not restart or replace the production fortress for
this test. Full campaign continuation must also preserve the runner's action
history, measurement baselines, and gameplay bookkeeping outside agent memory,
and reconcile charges accrued after a checkpoint. The current bundle has not yet
proved those properties. Website campaign views, model experiments, review/merge,
and production delivery remain required parts of the active goal.

## Real isolated native load proof: September 6, 2026 UTC

`native-load-20260906-c`, at candidate `3d47392b0`, passed native loading AND
test-process teardown. The copied runtime identified its own path on loopback
port 5501 before receiving `load-save`; the verified snapshot loaded as
`campaign-resume`, paused at year 30 tick 19309, exactly matching the saved
boundary. Its process set was empty and listener closed after teardown. An
independent `ss` check found no test listener, both production services remained
active, and the original `region3` still reported the same paused native clock.

All 19 load tests passed on Linux, including a real separate-session target/peer
cleanup test. The source snapshot, copied runtimes, and failed attempts remain
private in the service-account scratch checkout. The successful `result.json`
digest is `e2ccb7b7c12a4315ad96e666ebdae8edbe0c53b334c0ac0f11b6c3aa73c17207`;
see `experiments/evidence/native_load_smoke_20260906.json` for the versioned record.

The first attempt exposed native CLI color codes and DF's separate PTY session;
its leftover exact test PID was identified and terminated without touching
production. The second proved loading but its immediate listener check raced
shutdown. Both failure receipts remain unchanged. The final implementation strips
native color codes, verifies process identity by runtime path/UID/start time,
and waits for both process and listener disappearance.

Draft PR https://github.com/lemoz/fort-gym/pull/125 contains this work. Its initial
full CI run (`34005045563`, head `72381de9c`) passed. Newer candidate CI runs were
still running at this checkpoint; the initial green run does not cover later code.
No model call or gameplay advance has been made yet. Next: inexpensive model-driven
experiments from isolated saves while completing runner-state continuation and
website delivery. Native load success alone does not complete the active goal.

## First model probe: September 6, 2026 UTC

`dev-glm-flash-20260906-b` used `z-ai/glm-5.3-flash` selected through the
development configuration, in an isolated copy of the retained native save.
It returned three model responses across six dispatches, reporting $0.003462525
and 31,965 tokens. The initial request in each pair rejected disabled reasoning;
the immediate retry returned reported usage. This is response-reported cost,
not reconciled billing, and the three unreturned dispatches are not assumed free.

The gameplay probe failed before executing its first action. All three responses
omitted required DIG parameters and supplied a string instead of a review object.
The game stayed at year 30 tick 19309 with seven observed dwarves. A zero-population
default in the historical terminal summary must not become a campaign collapse
claim. Native teardown passed; the final save and agent state are retained.
See `experiments/evidence/development_glm_flash_20260906.json` for source hashes.

`python -m scripts.campaign_probe_report /absolute/path/to/dev-glm-flash-20260906-b`
derives a read-only, source-hashed assessment from retained experiment, runtime,
and trace files. It separates model action-contract failure, provider failure,
budget-limited pause, unclassified failure, and a bounded worker return. It reports
native boundary time separately from per-action tick evidence and leaves fortress
viability and autonomous success unassessed. It makes no provider calls.

The first attempt A failed on a keyword-only worker initialization contract before
any model call; that defect and a worker-level regression test are committed.
The subsequent Qwen probe was not launched: automated permission review rejected
external game-observation transfer to OpenRouter even after the configured
destination and prompt scope were inspected. Do not work around that rejection.
Local reporting and website implementation remain available work. No additional
budget is requested, and the overall goal remains active.

## Website slice: published campaign experiment evidence

The `/campaigns` page now exposes the retained development probe with its model,
attempt identity, actual native elapsed ticks, last observed population, failure
reason, reported model cost, unreturned dispatch count, and teardown result.
Expandable evidence includes diagnostics, limitations, source hashes, and a link
to the exact configuration at the experiment commit. Home and Results link to it.
The three declared models show their actual published attempt counts; a model
without a published attempt is not presented as a tested model or a zero score.

`/public/campaign-experiments` reads an explicit list of versioned public evidence
files and an allowlist of fields. It does not scan or expose private runtime
directories, game saves, full traces, credentials, or agent memory. Missing or
inconsistent selected evidence returns an unavailable response, not an empty
successful result field. The browser treats missing metrics as unknown and
refresh failures as unavailable, without displaying stale results as current.

This surface intentionally identifies its scope as **published development
probes**, not a live activity feed or a cross-model leaderboard. It preserves the
existing Fort Labs design and FastAPI/GCE architecture; no Sites/Cloudflare
migration was made. The development v1 condition remains frozen for these records;
changed conditions must receive a new version and a distinct comparison grouping.

Local verification: 60 focused campaign-catalog, public-route, landing-page, and
campaign-progress tests passed, including executed JavaScript formatting/rendering,
evidence-detail controls, adversarial text, and network-failure checks using an
in-memory document test double. New modules pass Ruff and JavaScript syntax checks;
the local loopback HTML route returned HTTP 200 and the API returned the retained
aggregate evidence. This is not browser visual QA or production acceptance.
No website deployment, active-campaign integration, year-two success, or complete
campaign recovery is claimed. The goal still requires all of those outcomes.

## Campaign loop and continuation state

`run/campaign_loop.py` adds a separate serial campaign loop instead of treating
the legacy benchmark runner's local variables as recoverable state. It reuses the
existing action parser, governed observation encoder, and factual action-history
builder. It does not add a score gate, automatic anniversary stop, scripted game
strategy, or a gameplay-rescue action. The existing benchmark runner and its
historical protocols retain their behavior.

The loop persists each new decision's usage before action execution, and commits
the action and actual native tick receipt before allowing a checkpoint. A v2
checkpoint binds game files, agent state, trace, runner history/feedback, and the
usage journal. Existing v1 checkpoint verification remains supported, but a v1
bundle cannot resume this loop because it lacks the runner state.

Resume requires an already loaded verified native save in a caller-owned runtime
and the original run's latest usage journal. It checks the native clock, restores
game-era memory and the next action cursor, and retains returned charges from
decisions after an older checkpoint. It does not reissue a pending checkpoint
action. Interrupted decisions, incomplete journals, and unaccounted usage require
reconciliation; they do not become free calls. This is cumulative returned-usage
reconciliation, not invoice verification. Failed or ambiguous execution poisons
the current loop instance until checkpoint recovery instead of allowing a blind
same-cursor retry.

`run/campaign_environment.py` connects this loop to existing native controls. It
checks the expected isolated DF root, verifies paused observations, disables
assisted dig completion, uses the legal executor, and interrupts time advancement
at viewscreen transitions. The outer runtime owner still handles save loading,
process isolation, and teardown. No native G7 event monitor is started or reset:
stock and structure observations are retained, while campaign-scoped production,
consumption, and death-attribution measurement remain to be implemented.

Local verification: 85 focused tests passed; new source passes Ruff and targeted
mypy. The deterministic continuation test obtains identical next prompts, actions,
feedback, agent state, and trace rows to uninterrupted execution. Separate tests
retain later decimal-exact charges while restoring older game-era memory, reject
native-clock mismatch and modified checkpoint files, record partial advances,
and prevent a new action after ambiguous execution. Native-adapter tests exercise
the real legal WAIT executor with an in-memory client, not an actual game.

Still required: load v2 checkpoints through the isolated runtime launcher and
verify continuation against real DF, connect the campaign loop to the executable
model configuration, and complete campaign-scoped measurements and website live
tracking. No new model call, native gameplay run, production deployment, or full
campaign-recovery acceptance is claimed by these local checks. The website commit
`bfd76cae7` passed full CI before this continuation slice was added.

The Linux scratch checkout passed 41 continuation, native-adapter, checkpoint,
and native-save unit tests at `031591ecf`. A subsequent compatibility correction
wraps campaign model events in the existing trace `tool_call` envelope and retains
native screen text for the replay reader. The existing usage extractor now reads
its test response cost correctly; 25 focused continuation tests passed afterward.
These tests run with provider credentials absent and do not launch native gameplay.

## Real native continuation proof: September 6, 2026 UTC

`native-continuation-20260906-d` passed the provider-free restart fixture. The
first process, at `ea13b96102a2bfcb246cd7d0a806ee8d6946f7a2`, advanced from
year 30 tick 19309 to 19319, wrote a complete v2 checkpoint, then advanced to
19339 for the uninterrupted comparison. After verified teardown, a new isolated
process at `2a63c101c4a5c03739e831989a03ab1b83ad55d2` loaded the checkpoint at
19319, restored cursor 1 and agent/history state, and produced the next WAIT-20
decision. It reached 19339 and wrote another verified native checkpoint.

This is deterministic WAIT-fixture infrastructure evidence, not model gameplay.
The comparison and resumed intervals overlap: do not add their ticks into a
50-tick campaign-duration claim. Both phases observed seven dwarves, but that is
not a viability test. No provider call, new VM, production restart, or code deploy
occurred. An independent postcheck found no processes under either copied runtime,
no listeners on 5501/5502, both production services active, and original `region3`
still paused at year 30 tick 19309 with no autosave pending.

The source-hashed record is
[`native_continuation_smoke_20260906.json`](../experiments/evidence/native_continuation_smoke_20260906.json).
Detailed receipts, saves, and failure attempts remain private and unchanged.
Attempts A/B exposed ANSI-colored native tick-deadline acknowledgements; exact
token comparison now strips terminal color sequences, with correct/incorrect-token
regressions. Attempt C completed the first phase but immediately reusing its port
failed the bind preflight. D reused the completed checkpoint on a distinct port.

Local campaign and native-tick regressions passed 221 tests; one Linux-only process
test and one opt-in live-DF test were skipped. The new restart-path checks also
reject reusing a first phase without verified successful teardown. The pushed candidate is on draft PR #125;
its CI was still in progress at this evidence checkpoint, and it is not merged.

Next: connect the bounded model configuration to this checkpointable loop,
preserving dispatch limits across recovery; implement campaign-scoped outcomes;
and extend website tracking. Real model inference remains blocked by the external
observation-transfer permission review already reported above. That does not block
these implementation and provider-free verification tasks. Full model recovery,
the first autonomous year, comparable repeated model runs, and live website
delivery remain required parts of the active goal.

The development adapter now has an explicit opt-in campaign dispatch-accounting
mode. Its checkpoint records dispatched requests separately from returned/accounted
responses and charges. The campaign usage journal reconciles later dispatch counts
when restoring older game-era memory, and the adapter enforces the remaining
dispatch allowance after restoration. Invalid, missing, or regressing counters
are rejected. The original probe mode and its checkpoint shape remain unchanged;
old probe snapshots cannot silently become campaign snapshots with reset counters.
This mode is implemented and locally tested, not exercised against a provider yet.

## Executable bounded campaign segments

`python -m scripts.campaign_segment` connects configuration-driven model selection
to `CampaignLoop` and the verified isolated runtime lifecycle. Its distinct
[`development_continuation_v1.json`](../experiments/campaigns/development_continuation_v1.json)
condition uses the declared inexpensive models and a three-step segment limit.
The eight-dispatch, token, and returned-cost limits are cumulative across resumed
segments. These are small development-test bounds, not the eventual year-two
campaign horizon. The model selects each action's simulation advance.

For a new campaign, supply `--config`, `--model`, `--campaign-id`, a new `--output`,
the existing `--source` game installation, and a digest-bound
`--snapshot` / `--snapshot-sha256`. For continuation, use the same configuration,
model, and campaign identity, another new output directory, and `--checkpoint`
plus the previous segment's latest `campaign/usage.jsonl` as `--latest-usage`.
Select a dedicated non-production `--port`; use a distinct port for an immediate
restart. Neither path modifies the source installation or production registry.
Use the existing authorized credential injection; never put credentials in arguments.

Each segment retains `campaign-segment.json`, the agent state, the durable trace,
decision-usage journal, and dispatch journal. A clean segment end or clean
pre-dispatch budget pause writes a v2 native checkpoint. The result distinguishes
`bounded_segment_complete`, `budget_limited_pause`, `failed`, and `checkpoint_failed`.
It reports new checkpoint verification separately from action completion. A failed
decision/execution does not generate a falsely current checkpoint; the previous
valid checkpoint and latest usage remain the recovery inputs. A timeout still
leaves outer runtime teardown and its receipt to the existing launcher.

Verification uses simulated policy responses and native state: segment completion,
fresh next-action continuation with preserved history, cumulative dispatch caps,
budget pauses without extra decisions, execution failure, checkpoint failure,
foreign campaign rejection, isolated worker arguments, and credential allowlisting.
The command's help, Ruff, and targeted mypy checks pass. This implementation has
not made a provider call or completed a model-driven native segment. It does not
replace the existing published probe or promote its results into this condition.

## Campaign performance profiles

The executable segment candidate `1056940c503b61d364ac8dfe5beadca908e081ba`
passed full remote CI (`34009907355`). Later reporting changes need their own
validation; this green run does not cover them.

Campaign observations now explicitly require valid native population and core
resource counts. The older reader's empty-read fallback remains unchanged for
historical callers, but the campaign path rejects it. A failed native observation
must not become seven dead dwarves or an empty stockpile. Real observed zero counts
are still valid. Campaign states record the native-observation quality version.

`python -m scripts.campaign_profile /absolute/path/to/segment` reads retained
segment/runtime receipts and the canonical campaign trace without modifying them
or making provider calls. New segment commands write `campaign-profile.json` after
the isolated runtime has returned and torn down. The profile includes source-file
hashes, code/configuration/model identity, and the actual teardown result.

The shared profile reports observed start/end/change/minimum/maximum and a timeline
for population, food/drink/wood/stone stocks, detected functional rooms, completed
workshops/beds/farms, and recorded dead citizens. Missing, malformed, legacy
unverified, or truncated measurements remain unknown. If the final observation is
missing, an earlier healthy population is not relabeled as the terminal population.
Native UI food/drink counts are stock observations, not production or consumption;
flow measurement and causal death attribution remain open.

The profile separates committed native time, the latest segment's terminal status,
accepted/rejected commands, changes of command after rejection, cumulative returned
cost and request counts, and unreturned usage. Command acceptance is not finished
work; a changed command is not a successful-adaptation verdict. One elapsed year
does not establish a functioning or autonomous fortress. The latest trace already
contains its checkpoint prefix, so ancestor traces and cumulative costs must not
be added again. Missing origin steps or native calendar fields prevent complete
duration claims.

These are descriptive profiles, not a scalar ranking or a new frozen protocol.
Binding original starting-save identity through the full campaign lineage,
campaign-scoped flow/death measurements, real model experiments, and the website's
active/recorded profile delivery remain open. Private states, agent memory, saves,
and raw paths are not included in the profile's public-shaped aggregate fields.
