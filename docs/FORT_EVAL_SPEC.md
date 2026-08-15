# Fort-Eval Specification

Status: draft v1.0

Fort Labs is the umbrella research program. Fort-Eval is the benchmark. Fort-Gym is the harness that runs agents, records traces, and computes scores. This document defines the boundary between those three names and the evaluation profiles they may support.

## 1. Scope and terms

Fort-Eval measures an agent's ability to make grounded progress in Dwarf Fortress while preserving a reproducible chain from observation, through action, to observed world change. A score is not a substitute for evidence, legality, or a comparable run configuration.

The benchmark has three named profiles:

| Profile | Interface and control | What it tests | Status |
| --- | --- | --- | --- |
| Easy | Current governed structured state plus bounded, legal semantic DFHack controls | Planning, action selection, causal progress, and evidence discipline | Current |
| Hard | Future fixed-pixel viewport plus primitive human inputs | Active perception, navigation, spatial memory, and z-level reasoning | Future |
| Discovery | Future Hard interface with no documents or web access, bounded cross-episode learner state, and held-out seeds or mechanics | Transfer and discovery under controlled information limits | Future |

The current CopyScreen plus `devel/send-key` path is a UI-control baseline. It is not Hard. Hard requires a fixed-pixel observation and primitive human inputs designed to make perception and navigation part of the task rather than exposing semantic state or semantic controls.

## 2. Interface profiles

### 2.1 Easy: current governed profile

Easy uses the existing governed path. DFHack is a bounded command transport, not a state mutation shortcut. The agent receives current structured state and the legal semantic action surface implemented by Fort-Gym. The current action family includes bounded `DIG`, `BUILD`, `ORDER`, `UNSUSPEND`, `FARM`, `LABOR`, `WAIT`, and allowlisted zero-tick `INTERACT` operations, subject to the repository's validation and provenance rules.

The current agent-visible visual/state surfaces are:

- CopyScreen text at 80 columns by 25 rows.
- A fort minimap with a maximum 34 by 34 tile view.
- Focused access maps with a maximum 17 by 17 tile view per focused level.
- Factual counters and bounded state such as jobs, workshops, citizens, labor, farm, and survival observations as defined by the current encoder and governed hooks.

The 64 by 64 maximum map snapshot is an observer/evidence surface. It may be recorded for replay, audit, and scoring provenance, but it is not automatically model input. A run must state an explicit observation profile if any derived snapshot is admitted to the agent context.

The following are not legal Easy shortcuts:

- Direct creation or mutation of items, wealth, food, drink, dwarves, or score state.
- Instant completion helpers such as `hook/complete_dig_rect.lua` in a scored run.
- Treating accepted commands, queued jobs, or unrelated global deltas as completed agent-owned progress.
- Treating a derived map or spectator rendering as gameplay proof.

The authoritative local references are `docs/DFHack_Governed_Agent.md`, `docs/Actions_Headless_Safety.md`, `docs/score_v5_action_truth.md`, `hook/fort_metrics.lua`, and `hook/map_snapshot.lua`.

### 2.2 Hard: future embodied interface

Hard is a separate future interface. It must provide a fixed-pixel viewport, a fixed capture policy, and primitive human inputs such as directional movement, selection, confirmation, and cancel. It must not inherit semantic `DIG`, `BUILD`, or `ORDER` controls as its action interface.

Hard tasks should predeclare which capabilities are active:

- Active perception: the agent must choose when and where to look, subject to the viewport and observation budget.
- Navigation: the agent must move through the game interface and recover from camera or cursor displacement.
- Spatial memory: useful locations must be remembered across viewport changes and occlusion.
- Z-level reasoning: the task must require understanding vertical access, not merely reading a supplied z-index.

The current CopyScreen/devel-send-key mode can be retained as a named baseline, but it must not be reported as a Hard result. Pixel capture, input primitive set, viewport dimensions, pause semantics, and action timing must be part of the comparability key before Hard ranking begins.

### 2.3 Discovery: future transfer profile

Discovery uses the future Hard interface and adds controlled information limits:

- No documents, no web retrieval, and no external knowledge tools during an episode.
- A bounded learner state may persist across episodes. Its schema, byte or token budget, reset policy, and write/read events must be logged.
- Seeds and mechanics are split into visible development material and held-out evaluation material.
- The held-out split must remain inaccessible to prompt construction, manual target selection, evaluator tuning, and post-hoc retry selection.

Discovery may describe the interface restriction as `no_docs_no_web`. It must not claim that a model has no pretraining or no prior knowledge unless that claim is independently verifiable. The benchmark measures behavior under the declared interface and split, not the provenance of model weights.

## 3. Observation and spectator firewall

Every run has two separate data planes:

1. **Agent plane:** exactly the observations allowed by the profile and observation subprofile.
2. **Observer plane:** replay, audit, and spectator evidence that may be richer than the agent plane.

The real-world Observer Map may show a richer map, additional context, or evidence overlays for spectators. It must never be included in agent prompts, tool results, hidden state, image batches, memory writes, or automatic retries unless the run's profile explicitly allows that surface. A profile that allows it must name the field, bounds, cadence, and purpose in the manifest.

The trace must preserve enough provenance to answer, for every scored claim:

- what the agent could see;
- what the agent requested;
- which control path executed;
- what native DF state changed; and
- whether the change was eligible for scoring.

The existing `screen_text`, `gameplay_proof`, `map_snapshot`, provenance tags, and rubric blockers are the baseline evidence vocabulary. Missing evidence is an evidence gap, not permission to infer success.

## 4. Knowledge axis

Knowledge is independent of interface difficulty. Every result declares one of these knowledge conditions:

| Knowledge condition | Allowed during the run |
| --- | --- |
| `none` | No documents, corpus retrieval, web retrieval, or external knowledge tool |
| `static_corpus` | A versioned, frozen corpus identified by digest; no network retrieval |
| `live_web` | Network retrieval through a logged, replayable policy and timestamped request record |

The same task and interface may be run at multiple knowledge conditions, but results are not silently pooled. Knowledge condition is a comparability-key field and must be visible in artifacts and leaderboard rows.

## 5. Comparability key

Each run and aggregate cell carries a canonical comparability key. A recommended serialization is:

`forteval/v1|condition=<benchmark_condition_digest>|model_arm=<model_arm_identity_digest>|harness=<fort_gym_commit>|df=<df_version>|evaluator=<evaluator_version>`

The condition digest must include:

- profile, task ID, task version, and objective;
- seed or seed split, including held-out status;
- mechanics and ruleset digest;
- observation and action interface digests;
- max steps, ticks or wall-clock budget, pause/timing policy, and retry policy;
- memory mode and bounded state budget;
- knowledge condition and corpus or web-policy digest;
- Fort-Gym commit, Dwarf Fortress/DFHack versions, and evaluator/score version.

The model-arm identity is a separate run field. It includes the model arm ID,
adapter ID, provider route, resolved provider model ID, prompt identity, and
relevant generation settings. It is used to group policy results inside one
benchmark-condition key; it is not a benchmark-condition comparison field.
In particular, a comparison table should show `model_arm` as the policy being
compared rather than treating each arm as a different task condition. Memory,
vision, knowledge, task, seed, budget, action surface, and score version remain
shared condition fields when the manifest says they are shared.

The legacy direct-Anthropic prohibition remains in force. A manifest may make
an explicit exception for a named arm routed through OpenRouter, such as the
Fort-Eval Fable arm. That exception permits the OpenRouter route only; it does
not enable the direct Anthropic API or the legacy direct-Anthropic adapter.

### 5.1 Easy P1 G7-v5 calibration condition

`experiments/fort_eval_easy_p1_g7_v5.yaml` declares the current P1 calibration
successor on
`seed_region3_fresh` with 200 steps and up to 2,500 ticks per step, for a maximum
of 500,000 ticks. It uses the `outcome-vector-v1+g7-v5` evaluator, no knowledge
access, vision on, and memory off. It is calibration-only.

*2026-08-15 note (supersedes the earlier "cannot launch until the owned-room and
authoritative-death sensors pass live DFHack validation" precondition):* those
sensors passed live DFHack validation on 2026-07-21 at fort_gym commit
`a8de39d03da48da32110776bf84ddfcbcb2ccefc`, across three provider-free
scenarios recorded in `experiments/evidence/EVIDENCE_INDEX.json`. The evidence
bundle is `experiments/evidence/fort_eval_easy_p1_g7_v5_live_calibration.json`,
sha256 `f41f1a80b63cdc0e323cf57dc914a28fc613cf183905e29828ede298baf59598`
(manifest_semantic_sha256 `b85957669eb02668f965f103e42b1feaf88cdad7ecc8e45fc5eb2b78d8269cc6`,
measurement_code_sha256 `261a1fba89ce1a320a3248a37cbee26b37971ef6c2240705d6bdce51088c9b4c`,
remote_proto_runtime_sha256 `9d7949fe3f7ef3497d145dff6cc921c13a3cf088cd1ff68ef58b5047a013570f`;
33/33 required regression node IDs green). The campaign was provider-free
(`dfhack-governed-scripted`, `usage.calls==0`), so validity and provenance are
UNKNOWN by design: it establishes measurement fidelity only and makes no claim
about policy capability. Launch is therefore no longer gated on sensor
validation but on (a) the reviewed `P1_MEASUREMENT_CALIBRATION_COMPLETE` unlock,
still `False` in `fort_gym/bench/eval/fort_eval_easy_p1.py`, and (b) Chris's
explicit spend approval. See
`docs/decisions/2026-07-21-g7v5-calibration-independent-review.md`.

G7-v5 requires at least one exact owned crop-assigned operational farm, one
exact owned completed Still, and exact governed completed brew output; zero authoritatively classified
preventable deaths, three final owned accessible layout rooms, and three exact
owned completed beds for the fixed initial seven-dwarf cohort. Room credit
requires final exact geometry with majority owned excavation, majority owned
boundary construction, or an owned completed boundary door, plus native citizen
path accessibility. Functional-room classification remains diagnostic and must
be satisfied by the exact owned touching building recipe.

*Calibration-only brewable-input fixture (2026-07-21).*
`hook/calibration_seed_brew_inputs.lua` (code `34b00ade2`, tests `f629cb7fd`,
boolean-walkable fix `a8de39d03`) places a bounded `LIMIT=8`
`MUSHROOM_HELMET_PLUMP` `PLANT` item set off-farm, adjacent to a COMPLETED
Still. It fires exactly once, at step 32, and only in the
`owned_layout_and_provisioning` measurement-calibration scenario; it is
disclosed in both the trace and the summary under
`measurement_calibration_fixture`. It seeds brew INPUTS and never DRINK items,
so brew credit still derives only from DRINK-item deltas under order-job
attribution — there is no contamination path into the outcome vector, and the
outcome vector above is unchanged by it. It is **not** a legal Easy shortcut
under §2.1 and never runs in a scored or paid run; it exists solely to make the
governed brew-output sensor observable while calibrating measurement. The
kill-fixture precedent is commit `3119806b2`. Its necessity was established the
hard way: the prior run `calib-g7v5-owned-20260720a` failed with brew 0 from
input starvation (`brewable_plant_units=0` all run; one late qty-1 brew order
lost the eat-vs-brew race). That run is superseded and its artifacts remain
VM-only. Plan edit `67b798b80` additionally added standing brew orders and a
second brewer.

Missing or truncated evidence produces an unknown validity state, never a
synthesized zero. This guarantee holds for the deterministic evaluator/gate
layer. In addition, the task_verdict fix ensures that the top-level verdict is
gated on the validity-gated G7 status: if validity or provenance is unknown,
the summary cannot show task_verdict=pass, and unknown is never coerced to
fail. Elapsed simulation ticks, absolute population, peak layout,
cache rate, score-v5, final reserves, and run-scoped production/consumption totals remain
diagnostics. The scalar action/outcome rubric is retired for G7-v5; full-trace behavior rates are reported without a numeric
composite. G7-v3 and G7-v4 remain frozen under their original criteria for
historical replay and are not launchable.

*(2026-07-21)* The verdict guarantee above is now live-confirmed rather than
merely asserted. The verdict fix (commit `557e5d6fb`) makes `p1_task_verdict`
return the validity-gated `g7.status`, and all three provider-free calibration
runs persisted `task_verdict=unknown` while `gameplay_outcome` stayed honestly
visible — including `calib-g7v5-owned-20260721a`, whose gameplay outcome was a
pass. The `sensor_dropout` scenario likewise produced
`owned_room_lower_bound_proven=false` and an unknown rooms criterion; it was
never coerced to fail.

The two model-arm identities are `dfhack-governed-llm-fable5` and
`dfhack-governed-llm-gpt56-sol`; both use maximum reasoning and a 128,000-token
completion limit. The manifest declares no numeric expenditure cap, but usage,
provider routing, and per-run pricing state must still be recorded.

Eligibility asymmetry in the completed G7-v3 pair: Fable was public-ELIGIBLE
while Sol was INELIGIBLE (frozen cached-token requirement unsatisfied). Because
the two arms did not satisfy the same eligibility gate, the G7-v3 Fable/Sol
pair is descriptive-only and must not be treated as a ranked or publishable
comparison.

Runs with different keys may be compared descriptively, but they must not share one ranked table or one aggregate mean.

## 6. Contamination policy

The benchmark owner must keep development, calibration, and held-out evaluation assets separate.

- A seed, mechanic, target layout, prompt hint, or evaluator rule used to tune an agent is development material.
- Held-out seeds and mechanics are frozen before a ranked evaluation window and are not exposed through docs, web, logs, screenshots, replay URLs, or error messages that reveal the answer.
- Static corpora require a content digest and a manifest of allowed files. Live web requires request logs and a declared domain policy.
- Human inspection may use the Observer Map only for audit. Human inspection must not alter the agent input, memory, action choice, retry choice, or score.
- A detected contamination invalidates the affected run or cell. It is not repaired by deleting a prompt, hiding a log, or rerunning until a favorable result appears.

The no-pretraining statement is intentionally out of scope. Report interface access, knowledge access, split integrity, and contamination findings instead.

## 7. Metrics

Primary metrics must be declared before the run. Fort-Eval should report at least:

- **Task success:** predeclared objective predicates over native DF state.
- **Owned progress:** action-attributed, evidence-backed state change; command acceptance alone is not progress.
- **Legality:** provenance, rejected or illegal actions, debug-helper use, rollback failures, and rubric blockers.
- **Evidence completeness:** valid screen frames, gameplay-proof rows, state read completeness, and replayability.
- **Efficiency:** steps, ticks, wall-clock time, model calls, input actions, and cost when pricing is resolved.
- **Perception and navigation:** view actions, novel area coverage, revisits, recovery from occlusion, and navigation errors for Hard.
- **Spatial and vertical reasoning:** held-out layout predicates, remembered landmark accuracy, z-level task success, and unnecessary level changes.
- **Generalization:** success by held-out seed and mechanic family, never only the pooled mean.

Composite scores may remain useful for local progress, but a high scalar score cannot clear legality, evidence, contamination, or task-success blockers. Score versions are part of the comparability key and are not retroactively mixed.

## 8. Cost and kill policy

Pricing is recorded only when the provider, model ID, token accounting, currency, and price schedule are resolved. Unknown pricing is represented as unknown; it is never estimated from a guessed model name. The manifest must preserve request counts and provider usage where available so cost can be backfilled without rerunning.

Before any paid arm starts, the manifest must make the expenditure policy
explicit. A manifest may declare no numeric expenditure cap for a provisional
pilot, as P1 does; that declaration does not waive usage logging, pricing
recording, provenance checks, or the stop conditions below. The harness must
stop or quarantine a run on:

- a safety or provenance violation;
- a failed rollback or unknown mutation;
- a contamination signal;
- missing required evidence after the declared retry budget;
- the declared step, tick, wall-clock, or model-call ceiling; or
- a repeated no-progress condition that the pilot has predeclared as a kill threshold.

An infrastructure stop is reported as infrastructure-aborted, not as a policy failure. A policy run that reaches its budget without success is a valid failure when its evidence is complete.

## 9. Provisional versus ranked

### Provisional

Use provisional status for a substrate check, a single run, an unresolved model or price, a changed evaluator, a single seed, an unratified task, a future interface prototype, incomplete evidence, or any run with a declared contamination concern. Provisional results can guide iteration and can be published as findings, but they do not establish a leaderboard order or a model claim. A valid policy failure with complete, contamination-free evidence is publishable under the manifest; publication does not turn it into a pass or a ranked result.

### Ranked

A ranked cell requires a frozen manifest and comparability key, resolved provenance, complete replayable evidence, no contamination, a stable evaluator version, a declared seed split, and the predeclared replication count. The minimum replication count and confidence procedure belong in the task manifest; they must not be chosen after seeing results. Easy v1 is a fixed-seed pilot and is provisional by default until the staged pilot is ratified.

## 10. Staged pilot

1. **P0, contract and substrate:** validate the YAML, action allowlist, observation firewall, trace fields, evidence predicates, and a known governed scripted control. No model ranking.
2. **P1, Easy pilot:** validate G7-v5 owned-room geometry, native accessibility, exact building IDs, partial construction attribution, delayed output attribution, and authoritative death evidence in live DFHack before permitting a paid run. **Status (2026-08-15): this validation step is COMPLETE-pending-review** — executed 2026-07-21 at commit `a8de39d03`, three provider-free scenarios, bundle sha256 `f41f1a80…`, independent scientific-validity review APPROVE with 0 blocking findings; the `P1_MEASUREMENT_CALIBRATION_COMPLETE` unlock has NOT been executed. Then run the exact `fort_eval_easy_p1_g7_v5.yaml` condition on `seed_region3_fresh`. Compare the two declared model-arm identities only inside the shared condition key. Report the gameplay outcome, evaluation validity, provenance completeness, terminal class, provider usage, pricing state, and diagnostics separately. Historical G7-v3 and G7-v4 results retain their original evaluators.

   *Note (2026-07-19):* The Fable/Sol comparison under frozen G7-v3 is COMPLETE
   and recorded; both runs FAILED G7-v3. The upcoming G7-v5 comparison is the
   next, approval-gated step and has not yet launched.

   *Note (2026-08-15):* the 2026-07-19 note remains literally true of the PAID
   two-arm G7-v5 comparison, which is still unlaunched and approval-gated. It is
   not the whole G7-v5 record: a provider-free G7-v5 **measurement calibration**
   campaign has since run to terminal with a committed evidence bundle
   (sha256 `f41f1a80…`). Calibration is a measurement event, not a gate attempt
   and not a paid comparison.

3. **P2, Easy generalization:** add held-out seeds and then held-out mechanics. Freeze the evaluator and contamination policy before the window. Promote only cells meeting the ranked rules.
4. **P3, Hard interface validation:** implement fixed-pixel capture and primitive inputs, then test viewport fidelity, input determinism, replay completeness, and spectator firewall before measuring policy capability.
5. **P4, Hard and Discovery:** measure active perception, navigation, memory, and z reasoning. Add Discovery's no-docs/no-web policy and bounded cross-episode learner state only after Hard is stable. Keep transfer claims separate from Easy claims.

The current repository's WDSLL and score documents remain the source of truth for historical Fort-Gym scoring. G7-v5 is an explicit, versioned non-scalar evaluator change; score-v5 remains available only as a diagnostic for this protocol.

### Results: G7-v3 Fable/Sol pilot (completed)

Two runs were executed under frozen G7-v3 on `seed_region3_fresh`, 200 steps
each:

- **Fable** (`dfhack-governed-llm-fable5`): run `a55b2c2cbef54825bc7784bdb8e51855`,
  cost $56.14648677, public-ELIGIBLE, 0 deaths, FAILED G7-v3.
- **Sol** (`dfhack-governed-llm-gpt56-sol`): run `cb997beed6d94a3680f2637556cc529d`,
  cost $36.54745875, INELIGIBLE (frozen cached-token requirement unsatisfied),
  10 deaths, FAILED G7-v3.

Descriptive finding: Fable was safer and more risk-aware; Sol was more capable
and productive but collapse-prone. Because Sol was ineligible, this pair is NOT
a publishable comparable pair and does not establish a ranked order.
