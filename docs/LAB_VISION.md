# Fort Labs Vision

Status: draft v1.0

Fort Labs is a research program for measuring whether agents can understand and act in a changing fortress world. The program is intentionally layered:

- **Fort-Gym** supplies the controlled environment, legal control paths, trace artifacts, replay, and scoring code.
- **Fort-Eval** supplies stable benchmark tasks, interface profiles, contamination rules, and comparison keys.
- **Fort Labs** holds the broader research questions, pilots, findings, and future interface work.

## What the program is trying to learn

The first question is not whether an agent can emit plausible actions. It is whether the agent can connect a bounded observation to a legal action and then to a native, observable world change. Later questions are harder:

1. Can the agent maintain a spatial plan while the world changes?
2. Can it use a restricted viewport and primitive inputs to seek information actively?
3. Can it navigate and remember locations across occlusion and camera movement?
4. Can it reason about vertical access and z-level consequences?
5. Can it discover reusable mechanics across episodes without documents or web retrieval?

These questions are related, but they are not one score. Easy, Hard, and Discovery are separate claims with separate interfaces and contamination controls.

## The product shape

The benchmark should feel like a laboratory instrument rather than a single leaderboard. Every result should let a reviewer inspect:

- the exact interface and knowledge condition;
- the agent's allowed input;
- the action and state provenance;
- the native changes that earned credit;
- the observer-only evidence;
- the cost and stopping reason; and
- the held-out split used for generalization.

This is why the Observer Map is useful but dangerous. Spectators may need a richer real-world view to understand a run. That view must remain on the observer plane. It does not become an unannounced oracle for the agent.

## Company evaluation direction

Fort-Eval is the public flagship, not the limit of the lab. The same method can support private company evaluations where an agent must operate a real workflow, simulator, internal tool, or changing software environment over a long horizon.

The reusable lab process is:

1. define the operational outcome and the evidence that proves it;
2. separate agent-visible state from evaluator and observer state;
3. expose a bounded, auditable action interface;
4. capture every observation, action, native effect, cost, and stop reason;
5. freeze a comparison manifest before the ranked cohort; and
6. publish or privately deliver replayable findings, including failures.

This is a direction for Fort Labs, not a claim that a company-evaluation product or service is already generally available. Dwarf Fortress provides the demanding public proof: a large procedural world, delayed causal effects, spatial and vertical navigation, resource loops, autonomous actors, and no single natural endpoint.

## Near-term direction

Easy is the current anchor. It uses governed structured state and legal semantic DFHack controls, with the existing 80x25 CopyScreen text, bounded 34x34 fort minimap, and focused 17x17 access maps. The 64x64 snapshot is evidence and analysis unless a manifest explicitly admits a bounded derivative to the agent. Easy makes legality and causal measurement concrete before interface difficulty is increased.

Hard is the next instrument, not a relabeling exercise. It needs a fixed-pixel viewport and primitive human inputs. The existing CopyScreen/devel-send-key path remains a useful baseline for UI control, but it does not test the intended Hard combination of perception, navigation, memory, and z-level reasoning.

Discovery comes after Hard is stable. Its restriction is about accessible information during evaluation: no docs, no web, a bounded learner state across episodes, and held-out seeds or mechanics. It must not make an unverifiable claim about model pretraining. A clean statement is: the agent had the declared interface, knowledge channel, memory budget, and held-out split.

The current provisional Easy P1 manifest is
`experiments/fort_eval_easy_p1_g7_v3.yaml`. It freezes G7-v3 on
`seed_region3_fresh` at 200 steps and up to 2,500 ticks per step, with score-v5,
vision on, memory off, and no knowledge access. Its two model arms are compared
inside one shared benchmark condition. The arm name, provider route, resolved
model, prompt, and generation settings identify the policy arm; they are not
alternate benchmark conditions. Valid failures with complete evidence remain
publishable, while infrastructure aborts and invalid evidence remain distinct.

## Design commitments

### Evidence before narrative

A replay is not proof merely because it looks persuasive. A command is not progress merely because it was accepted. Fort Labs should prefer a smaller, inspectable claim over a larger claim that relies on inference.

### Separate axes

Interface difficulty and knowledge access vary independently. `none`, `static_corpus`, and `live_web` are knowledge conditions, not synonyms for Easy, Hard, or Discovery. A result must declare both.

### Honest cost accounting

Model IDs, provider routing, token usage, and prices can drift. The lab records the resolved values when known and marks unresolved values explicitly. It does not invent pricing or silently substitute a model with a similar marketing name.

### Progress must be causal

Fort-Gym's existing governed rules are the right default: score observed, action-owned changes; keep global and derived state visible as audit telemetry; and fail closed when the chain is incomplete. This keeps the benchmark useful for engineering, not just presentation.

### Research and ranking are different states

A pilot can be valuable while remaining provisional. A failed policy run, an infrastructure-aborted run, a contamination invalidation, and an incomplete evidence artifact are different outcomes and should remain different in reports.

## Roadmap

### Stage 0: instrument integrity

Validate the Easy manifest against the current Fort-Gym experiment loader, confirm that the known scripted governed control can run, and verify that observer-only artifacts do not enter the model context. This stage produces no model ranking.

### Stage 1: Easy baseline

Run the frozen Easy P1 G7-v3 pilot with the declared governed model arms and
keep the fixed-seed result provisional. Resolve and record provider model IDs,
routing, usage, and pricing per run. A valid failure is still a publishable
finding; it is not a leaderboard pass.

### Stage 2: Easy generalization

Freeze a held-out seed and mechanic split, then test whether progress and evidence survive beyond the development embark. Keep current WDSLL gates and score-version boundaries intact.

### Stage 3: Hard interface

Build fixed-pixel observation and primitive input capture. Test the interface itself before making capability claims: pixel fidelity, deterministic input playback, bounded capture, pause behavior, trace completeness, and the spectator firewall.

### Stage 4: Hard capability

Predeclare tasks that require active looking, movement, spatial memory, and z-level reasoning. Report each metric family separately so a policy cannot hide a navigation failure inside a construction score.

### Stage 5: Discovery

Freeze the Hard interface, expose no docs or web, cap cross-episode learner state, and evaluate on held-out seeds or mechanics. Report the information boundary and split integrity rather than claiming anything about pretraining.

## Success condition

Fort Labs succeeds when an independent reviewer can reproduce the declared run, see what the agent actually received, distinguish the richer spectator view from the agent view, verify why progress counted, and compare only runs with the same key. Capability improvements are meaningful only after that instrument boundary holds.
