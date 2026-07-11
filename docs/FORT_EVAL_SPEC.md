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

`forteval/v1|profile=<profile>|task=<task_id>|knowledge=<knowledge>|seed_split=<seed_split>|mechanics=<mechanics_digest>|obs=<observation_digest>|action=<action_digest>|budget=<budget_digest>|model=<model_digest>|prompt=<prompt_digest>|memory=<memory_digest>|harness=<fort_gym_commit>|df=<df_version>|evaluator=<evaluator_version>`

The key must include:

- profile, task ID, task version, and objective;
- seed or seed split, including held-out status;
- mechanics and ruleset digest;
- observation and action interface digests;
- max steps, ticks or wall-clock budget, pause/timing policy, and retry policy;
- model adapter ID, resolved provider model ID if any, system prompt digest, temperature and relevant generation settings;
- memory mode and bounded state budget;
- knowledge condition and corpus or web-policy digest;
- Fort-Gym commit, Dwarf Fortress/DFHack versions, and evaluator/score version.

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

Before any paid arm starts, the operator must approve a per-run and per-cell budget. The harness must stop or quarantine a run on:

- a safety or provenance violation;
- a failed rollback or unknown mutation;
- a contamination signal;
- missing required evidence after the declared retry budget;
- the declared step, tick, wall-clock, or model-call ceiling; or
- a repeated no-progress condition that the pilot has predeclared as a kill threshold.

An infrastructure stop is reported as infrastructure-aborted, not as a policy failure. A policy run that reaches its budget without success is a valid failure when its evidence is complete.

## 9. Provisional versus ranked

### Provisional

Use provisional status for a substrate check, a single run, an unresolved model or price, a changed evaluator, a single seed, an unratified task, a future interface prototype, incomplete evidence, or any run with a declared contamination concern. Provisional results can guide iteration and can be published as findings, but they do not establish a leaderboard order or a model claim.

### Ranked

A ranked cell requires a frozen manifest and comparability key, resolved provenance, complete replayable evidence, no contamination, a stable evaluator version, a declared seed split, and the predeclared replication count. The minimum replication count and confidence procedure belong in the task manifest; they must not be chosen after seeing results. Easy v1 is a fixed-seed pilot and is provisional by default until the staged pilot is ratified.

## 10. Staged pilot

1. **P0, contract and substrate:** validate the YAML, action allowlist, observation firewall, trace fields, evidence predicates, and a known governed scripted control. No model ranking.
2. **P1, Easy pilot:** run the current governed profile on a fixed seed with the declared step/tick budget. Include a legal scripted control and, only after model ID and pricing are resolved, approved policy arms. Report evidence, legality, progress, and cost separately.
3. **P2, Easy generalization:** add held-out seeds and then held-out mechanics. Freeze the evaluator and contamination policy before the window. Promote only cells meeting the ranked rules.
4. **P3, Hard interface validation:** implement fixed-pixel capture and primitive inputs, then test viewport fidelity, input determinism, replay completeness, and spectator firewall before measuring policy capability.
5. **P4, Hard and Discovery:** measure active perception, navigation, memory, and z reasoning. Add Discovery's no-docs/no-web policy and bounded cross-episode learner state only after Hard is stable. Keep transfer claims separate from Easy claims.

The current repository's WDSLL and score documents remain the source of truth for current Fort-Gym gate criteria. This specification adds the cross-profile research boundary; it does not silently change existing score gates.
