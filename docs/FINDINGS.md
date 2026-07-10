# FINDINGS — the lab's findings, from the corrections log

This is living documentation, not a paper. It records what running an LLM
policy against a real, unbounded game has taught us so far, and it will change
as the gate ladder advances. Every number here traces to a run id and a
committed doc — the gate ladder and the full corrections log in
[`docs/WDSLL.md`](WDSLL.md), and the score-v3 work in
[`docs/score_v3_proposal.md`](score_v3_proposal.md) and
[`docs/score_v3_calibration.md`](score_v3_calibration.md). Where WDSLL records a
public replay token, the run links to `fortgym.live/r/<token>`; where it does
not, the run is cited by id.

## 1. What Fort-Gym is

Fort-Gym is an environment lab's flagship: real Dwarf Fortress, played by an LLM
policy that may issue only eight bounded, audited primitives —
`DIG`, `BUILD`, `ORDER`, `UNSUSPEND`, `FARM`, `LABOR`, `WAIT`, `INTERACT`
(`fort_gym/bench/agent/governed_llm.py`). Each primitive is a bounded legal
gameplay command: it may designate work or create normal jobs available to a
human player, but it may not create goods, teleport material, complete labor,
or advance score directly. Every action is locality-bounded and
provenance-tagged. One `dfhack_assisted` action zeroes a run.

Scoring is evidence-gated. A gate passes only on recorded facts in a public
run's `summary.json` and `trace.jsonl` — never on narrative, screenshots, or the
scalar score alone. Every step carries a recorded screen frame and a per-step
`gameplay_proof` object; a claim without its evidence row does not count. An
anti-Goodhart rubric sits on top, with hard blockers (`repetitive_policy`,
`no_production_surface`, `illegal_or_assisted_progress_seen`, `no_fort_structure`)
that fail a run regardless of score.

The gates are pre-declared and ratchet upward: G0 (legal substrate) → G1 (an LLM
on the surface) → G2 (parity with the scripted ceiling) → G3 (finished goods,
not queues) → G4 (a fortress, not a demo) → G5 (memory pays rent) → G6
(generalization to an unseen map) → G7 (the fort survives a year) → G8 (depth).
The success statement the whole ladder makes falsifiable: *an LLM policy,
issuing only legal governed actions, takes a fixed embark from fresh seed to a
producing fortress on public, replayable evidence, with zero rubric blockers.*
G0–G4 have passed; G5 failed and stands; G6 is unpassed after seven attempts
on the unseen map, with the first enclosed rooms arriving only after the factual
observation corrections; G7 is ratified and its first eight attempts failed,
with attempts 2 through 8 infrastructure aborts and no policy verdict.

## 2. The findings

### 2.1 The spatial modality gap

Maintaining a hollow-ring invariant during incremental wall construction — the
core act of building an enclosed room — is beyond the reliable capability of the
text-only models tested. Across roughly fifteen text attempts spanning three
models, two score versions, and both memory configurations, exactly one text run
ever closed a ring (GPT-5.5, on its first attempt); a later attempt even
rendered an ASCII minimap with coordinate rulers and an explicit hollow-ring
rule, and the model still built a solid filled block (run `96d5e024`).

Adding a rendered PNG minimap for vision models moved the number sharply. In the
vision experiment (WDSLL, 2026-07-04; 100 steps, memory-off, score-v2), two of
three vision arms closed a ring on their first run: GLM-5V-turbo (`0cffcd6d`,
131.19) built the first enclosed functional room the GLM family had produced
after ~10 text attempts, and Kimi K2.7-code (`91928e29`, 69.01) also closed a
ring though it never started an economy. MiniMax-M3 (`83ff5d61`, 63.95, valid
calls) managed neither — the control that establishes vision does not manufacture
capability, it removes a modality barrier. Two vision runs achieved what one text
run in fifteen ever had.

### 2.2 The G4 arc: one pass, 40% reliability, and four removed lies

**The pass.** Run `2f58fd37`
([replay](https://fortgym.live/r/qw8S-Wmf53DYLESSrgCWGvLPvY2n0IuH); GLM-5V pinned,
100 steps, memory-off, commit `893394920`, score-v2) is the first G4 pass in
project history — 6/6 criteria. Score 158.68 > the 121.5 scripted ceiling; rubric
78.42 with zero blockers; 100,466 ticks; population held 7/7; 10 beds + 3 doors
produced from the run's own orders; **2 enclosed spaces and 2 functional rooms**
(flood-fill detected, room 1 at step 30, room 2 at step 63) from 75
constructions. Evidence: 100/100 recorded screen frames, 46/100 proof-backed
steps, 100/100 `dfhack_governed` provenance.

**The pass was earned by fixing the observation, not the policy.** Four times, a
diagnostic run failed and the forensics found the instrument — not the model —
was lying. Each lie was removed by widening the observation's factual content or
the legal action surface; the policy itself was never steered.

1. **Phantom objectives.** Forensics on the first vision ring (`0cffcd6d`) showed
   the agent finished its room by step 40, then spent 52 of its next 60 actions
   on single-tile floor placement chasing the retired `two_room_workshop` plan,
   whose progress counters the observation still displayed. Under score-v2 those
   tiles paid nothing and no gate asked for them: the observation was stating a
   false objective. Removed (WDSLL 2026-07-04, PR #35).
2. **Invisible legality walls.** The same audit found furniture and workshop
   placement was still hard-rejected outside the legacy plan rectangles
   (`outside_work_rect`) — so a room built anywhere else could never be furnished
   into a *functional* room, an invisible wall placed directly against the very
   rooms criterion G4 measures. Placement legality was rerouted through the same
   24-tile Chebyshev locality rule the wall/floor primitives already used
   (PR #35).
3. **Invisible queued walls.** G4 vision run 1 (`24042365`,
   [replay](https://fortgym.live/r/T37FoZzcriyNd6OHH-0CTo-1G6giqMt3), FAIL 3/6)
   failed with 58 of its 81 wall actions rejected — 41 `already_wall`, 18
   `tile_occupied_by_building` — against *its own queued walls*. A queued wall is
   a Construction-type building until a dwarf builds it, and the minimap drew only
   completed constructions, so pending walls rendered as open floor; the agent
   re-placed walls it had already ordered and could not tell phantom gaps from
   real ones. Pending constructions now render as `x`, with the mechanic stated
   in the prompt (PR #38). Display-only: an unbuilt wall never seals a room, so
   the enclosure flood-fill boundary was untouched (locked by test).
4. **Off-frame proof windows.** The gameplay-proof window did not follow the
   fort, so walls built outside it were not counted as evidence. Fixed in
   PRs #44/#46, disclosed in advance in the repeatability protocol (WDSLL
   2026-07-06) because it makes proof-backed step counts non-comparable across
   the change.

Runs 2 and 3 (`0a1be1c5`,
[replay](https://fortgym.live/r/VCjkMbEg91DAbbk6pFZUTP94GvX3qClH), FAIL 5/6 — the
best pre-pass result — and `5a406c21`,
[replay](https://fortgym.live/r/ujtHjQhGMkmpRt_z1ooTRoVJS_Us18US), FAIL 4/6) both
reached exactly one room short, blocked by suspended construction jobs the agent
could diagnose but not legally clear; this produced the `UNSUSPEND` primitive
(PR #41). On the passing run `UNSUSPEND` was used twice, late, and found nothing
to clear — the pass is attributable to the accumulated observation-truth
corrections and the vision modality, not the new primitive. That causal
honesty matters: it means the wall the corrections removed was real.

**Reliability: 2/5 (40%).** One pass is existence, not reliability. A
pre-declared five-run lineage (the pass plus four repeats, identical config)
returned a second pass — run `01a57454`, 6/6 — and three failures (`d06cc571`,
`7f268bcc`, `71ffc569`). G4 is real but unreliable; the bottleneck is
second-room-completion variance (WDSLL 2026-07-06).

### 2.3 The memory inversion (G5)

Persistent memory, as first implemented (failure tallies plus a persistent
plan), was actively counterproductive. A five-run memory-ON series
(`3f3cdfdf`…`fca3f6c2`) against a five-run memory-OFF control (`69d45ae8`…
`1644cce7`), identical config and fresh slate each arm, inverted the gate: G5
requires run-over-run rubric non-decreasing with a +15 improvement; memory-ON
rubric *declined* 90.4 → 82.6, while the control outperformed it — 3 of 5
fresh-slate runs built a functional room while the memory-ON runs degenerated
into unfocused wall-spam (66–94 constructions, zero enclosures). The gate stands
unmodified; it did its job by isolating the effect. Passing it requires a
redesigned memory (causal lessons and successes, not failure counts), not a
softer criterion (WDSLL, G5 entry).

### 2.4 Two generations of reward hacking, and their closures

The scalar score has been Goodhart-attacked twice. Each time the exploit was
found in an audited run, the closure was operator-approved, and the boundary was
version-stamped so scores never silently drift across it.

**Generation 1 — queue-spam → score-v2.** In the pinned three-model comparison,
DeepSeek V4 Pro (`e57ff8e2`, 686.81 under v1) issued 91 consecutive bed orders,
pumping the open-ended `utility_progress` queue-depth metric to 301
(utility_score 602) while producing and building almost nothing. The G4 gate
correctly failed it (the rooms criterion held), but the scalar ranked a hollow
run first. Score-v2 (WDSLL 2026-07-03, commit `967d9e688`) closed it:
`utility_progress` now pays only completed production plus workshops that became
usable; order and queue deltas are recorded but earn nothing, and the rubric's
repetition exemption no longer accepts queue-only proofs as world change (the
10×-identical-order trace now trips `repetitive_policy`, locked by test). Every
run before `967d9e688` is stamped `score_version` ≤ 1 and is not comparable
across the boundary.

**Generation 2 — chair-factory monoculture → score-v3.** The 250-step endurance
probe `ad70df06` (see §2.5) produced no fake progress — every item was real — but
after closing one room it spent ~150 steps mass-producing chairs (26 chairs for
13 dwarves) because v2 pays real production linearly with no diminishing returns.
Goodhart by monoculture: the optimal long-horizon policy was to build the
cheapest item, not a fortress. Score-v3
([proposal](score_v3_proposal.md), ratified WDSLL 2026-07-07) answered with
demand-capped production (each orderable good pays full rate up to fort demand ≈
population, 20% on surplus), plan-agnostic complexity (flood-fill functional
rooms / enclosed spaces / constructions replacing the legacy plan rectangles),
and plan-agnostic rubric dimensions — all landed as one `score_version: 3`
boundary.

The v3 work is documented honestly precisely because it did *not* cleanly
succeed. Two calibration rounds
([`docs/score_v3_calibration.md`](score_v3_calibration.md)):

- **Round 1 (commit `03b0c9df1`)**: the validation gate passed exactly — all 9
  `score_version` ≥ 2 runs reproduced their recorded totals with |Δv2| = 0.0,
  confirming the reconstruction is faithful — but the ratified acceptance check
  *failed*. The chair-factory run scored v3 = 508.06 against the two G4 passes at
  180.33 / 207.58, because `production_score` (a component neither v3 change
  touched) paid uncapped for queued workshop task-jobs; a second sampled run
  (`7f268bcc`) showed the same pattern at production_score 420.0. Per the
  non-negotiables this was reported, not silently tuned around — the finding
  forced an amendment.
- **Round 2, production amendment (commit `77adc8720`, operator-ratified)**:
  `production_workshops_delta` now pays usable-workshop deltas only (queue depth
  drops out entirely, applying v2's "queueing is a menu action" doctrine to
  production), and `production_score` is bounded at its 10-point weight.
  Validation again passes exactly; the queue-churn runs deflate correctly
  (`7f268bcc` 497.56 → 104.54; `ad70df06` production_score 320 → 10). The DeepSeek
  arm now passes (78.81, below both G4 passes) — but the chair-factory arm still
  fails by 10.48 points (v3 = 198.06 vs the better G4 pass at 187.58). The
  residual is no longer an exploit: it is honest, diversified production over a
  2.5× step horizon (250 vs 100 steps; per-type demand caps across six good types
  leave ~78 full-rate units reachable) plus open-ended utility and wealth
  scaling. Per the ratified stop-and-report rule, no further coefficient was
  touched; every adjacent path was audited and found bounded or
  completion-gated. The PR is **held for operator decision** — whether to accept
  the gap (WDSLL's comparability clause already forbids cross-horizon score
  comparisons for gates), cap utility, bound wealth, or normalize by steps.
  The G6 campaign subsequently recorded its runs under score-v3 per its own
  operator-ratified protocol, where the scalar carries no pass/fail weight
  (see §2.6) — no gate outcome yet rests on a v3 score.

### 2.5 The endurance result

Pre-declared probe run `ad70df06`
([replay](https://fortgym.live/r/8ACitgQEErsR8fdjTRMb59CrTm4D6k1q); 250 steps,
198,042 ticks, score 515.44, rubric 68.61 with zero blockers, population 7 → 13
with all migrants surviving, 250/250 frames). Four questions, each answered from
the run's own trace at step 100 versus step 250:

- Does structure compound? **No** — 1 functional room at step 98, still 1 at step
  249.
- Goods diversity ≥ 4 types? **Yes** — 5 types.
- No degeneration blockers at end? **Yes.**
- Final score ≥ 1.25× the step-100 score? **Yes — 5.35×** (93.59 → 500.8).

Verdict: the policy **satisfices structurally and compounds economically in a
degenerate direction**. Past passing-level structure it stops building and
becomes a chair factory. This is not an illegal-progress exploit — it is the
finding that forced score-v3 (§2.4).

### 2.6 The generalization campaign (G6): 0/3, an escalation, and what an unseen map exposed

G6 moves to `seed_region3_fresh`, an embark no agent has seen (the prior
candidate, `region2`, was condemned — its save SIGABRTs DF at boot and was
quarantined after causing a full platform outage on 2026-07-07; region3 was
created by a fully reproducible headless worldgen procedure, WDSLL 2026-07-07).
Three pre-declared attempts, GLM-5V, 100 steps, memory-off, score-v3, all failed
the rooms criterion — and each exposed a different measurement lie that the
wood-rich home map had hidden.

- **Attempt 1 — `769f5034`
  ([replay](https://fortgym.live/r/cQKTXD8xnEUNV9COJIvXR9zB7Mg3F59M), FAIL 2/5)**
  exposed **wood blindness**: region3's spawn is a clearing, and zero tree trunks
  appeared in the agent's observation window all run (region1's spawn happened to
  have trees in-frame, masking this for the entire prior campaign). Wood peaked
  at 6, walls died `no_building_material` ×13, 25 bed installs failed with
  nothing to install. It also exposed a **hardcoded dead metric**: the gamelog
  recorded a dwarf drowned in the brook and the population criterion caught it
  honestly (6 < 7), but `state.dead = 0` had been a literal constant in the state
  reader since day one — the casualty-spike check had never measured anything.
  Corrections: a bounded read-only Nearby-trees scan (40 tiles, top-3 clusters);
  count the civ's dead dwarves for real.
- **Attempt 2 — `55c39cdd`
  ([replay](https://fortgym.live/r/twSeylYz5Z6Mb5Mh11pIR20DpW5Yxrtg), FAIL 3/5)**
  confirmed both fixes worked (the trees line reported real clusters, early chops
  raised wood 3 → 11; the dead metric was live and read 7/7), then exposed
  **phantom stock counts**: at step 8 the agent placed 10 wall segments at once,
  each pending construction immediately claimed a log — 10 of 11 logs locked —
  yet the stocks line kept reading "Wood: 11" for the next 90 steps, and 22
  further wall attempts failed against apparently-full stock. Correction: stocks
  now report *usable* counts (items not claimed by jobs or locked in pending
  buildings).
- **Attempt 3 — `19f692b8`
  ([replay](https://fortgym.live/r/OnonN6SkMid42X4NRAHYBnzYFYwhh5-g), FAIL 3/5)**
  concluded the campaign 0/3. The wood economy was solved: one chop at a
  Nearby-trees cluster produced **112 logs by step 25** (attempt 1 had peaked at
  6). Rubric cleared the bar for the first time on region3 — but with a
  **pipeline defect disclosed at full prominence**: the usable-stocks correction
  from attempt 2 never reached the agent, because the StateReader field whitelist
  silently dropped `wood_usable`/`stone_usable` between the state script and the
  encoder (`usable: None` in every step). The fix was approved, shipped, tested at
  both ends, and lost in the pipe; the one-line whitelist addition with an
  end-to-end test was held for the next window and later deployed as PR #59,
  ahead of the escalation runs.

The correction ladder measurably worked: rubric climbed **69.06 → 69.56 → 70.88**
across the three attempts, and available wood went from **6 to 112**. What did
not fall is the frontier. Population failed on drownings — the brook has now
killed **three dwarves in three runs**, a hazard class region1 never had, and no
legal action addresses water safety short of walls. The G6 verdict:
generalization on unseen terrain is not geometry alone. It is **logistics**
(solved by factual observation), **environmental hazard** (unsolved), and
**ring-closing under both pressures** — 0 enclosures in 3 runs even with up to
112 logs available. The operator selected a hybrid escalation (2026-07-08): one
GPT-5.5-vision run and one corrected-instrument GLM-5V run on region3, to
separate policy strength from environment difficulty.

**The escalation: both runs failed, and both built the first enclosed rooms
ever seen on the unseen map** (WDSLL 2026-07-08). Corrected-instrument GLM-5V,
run `c8e46054`
([replay](https://fortgym.live/r/CHt5-Grk_uBqX7kj23MyGU3vh512qEh3)): FAIL 3/5 —
but **1 enclosed functional room**, the GLM family's first on region3 after
three zero-room campaign attempts, arriving only once the full correction stack
finally reached the agent end-to-end; rubric 77.51 clean; the best GLM region3
economy recorded (5 beds + 2 doors, 25 constructions). It failed rooms ≥ 2 and
population 6/7 — another drowning, the brook's fourth victim. GPT-5.5-vision,
run `36f9f78f`
([replay](https://fortgym.live/r/ayENDjV5v5K35Mblffz3I53mEGsA3sOW)): **FAIL 4/5,
missing only rooms ≥ 2** — the strongest region3 run recorded: rubric 83.44
clean, population 7/7 held, 74 constructions, 5 goods types, 1 functional room.
The escalation question is answered: region3 is not impassable. With a truthful
instrument, both models now close rings on unseen terrain, and the frontier is
the same "second room" wall G4 had on region1 before it fell —
GPT-5.5-vision's 4/5-missing-only-rooms exactly matches the profile that
preceded the G4 pass. The environment is genuinely harder (drownings,
logistics) but tractable. The next escalation decision sits with the operator;
no further runs until it is chosen.

### 2.7 G7 attempt 1: a real half-year fort, and a missing part of play

G7 attempt 1, run `f6a87f6afb6241c082a6a015c361d755`
([replay](https://fortgym.live/r/GbccbSS-d6bADihKEosLgx6788yhoaqx)),
is the clearest boundary yet between real gameplay and successful gameplay.
The GLM-5V policy used all seven actions available in attempt 1, produced real goods, survived
a migrant wave to population 15, placed 14 bed buildings, and reached score-v3
209.44. It also built zero functional rooms, let drink fall 60->0, recorded no
food-production loop, and scored rubric 63.79. The bed field does not yet
distinguish completed installations from pending furniture, so that predicate
is unknown in the attempt trace. A later read-only stage probe found all 14
observed beds complete, but after-the-fact evidence does not rewrite a gate.
The scalar bar passed; G7 failed.

At tick 217225, after 199,691 elapsed run ticks, a Mountainhomes liaison meeting
opened. A human player would answer it while the game remained paused. The
governed action surface had no bounded confirm/cancel/dialog command, so the
policy could see the meeting in every CopyScreen frame but could not legally
act on it. Seventy-five subsequent steps advanced zero ticks while still making
model calls. This is both a substrate finding and a runner-lifecycle finding:
ordinary administrative dialogs are part of Dwarf Fortress play, and a stalled
clock must not silently consume the rest of an experiment.

The run also exposed an evidence gap in the ratified kill rule. One death is
recorded, but no cause reaches the trace, so the run cannot prove zero deaths
from starvation, dehydration, or tantrum. Attempt 2 therefore requires factual
death-cause, completed-furniture, and food/drink-flow evidence, not a narrative
inference from stock levels. Full predicate results and the
substrate/policy/runtime split are in `docs/WDSLL.md`.

### 2.8 G7 attempt 3: real construction, invalidated by an illegal material reuse

G7 attempt 3, run `622dac1c396c454d90e070bb8b669905`
([replay](https://fortgym.live/r/i7wIFrZC_7xXlTJmQaXTRfWnWPMAxxeO)), deployed
SHA `62030af8e3ed656e501f50e49c10968a932479a5`, is an infrastructure-aborted
FAIL with no policy verdict. The trace model was `z-ai/glm-5v-turbo` via
OpenRouter; Anthropic was disabled and memory was off. The run produced 46
durable rows and 46,160 trace ticks; the summary's 45,155 excludes the final
stop row. Token use was 305,552 prompt and 15,421 completion tokens. Actions
were BUILD 33, DIG 1, FARM 1, ORDER 6, and WAIT 5.

The policy did real work: it built a Carpenter workshop, produced and placed
doors, chopped trees, completed 18 construction tiles, reached a peak of two
functional rooms and three enclosed spaces, built a Still, and built
a FarmPlot with a selected crop. Population was 7, food 45, drink 60, and
there were zero deaths. At step 40, however, `build_workshop.lua` reused
material item `765` that was already installed in the Carpenter workshop
because it did not reject `item.flags.in_building`. The Still reused the same
item, and the Carpenter workshop disappeared without agent deconstruction.
That violates player parity and invalidates the run.

The operator requested stop at API step 44; the final durable row is step 45
and status is `stopped`. The ledger evidence itself remained complete, but its
DF callback remained active after terminal status because optional Gemini
analysis ran before outer `finally` cleanup. The operator detached the ledger
callback and restarted only the API to cancel the analyzer; the replay persisted.
Summary scalar 102.38 and rubric
92.54 with `blockers=[]` are explicitly not a pass: the primitive violated
player parity, and the run missed the G7 duration, production, and rooms
criteria. Follow-up: add the `in_building` guard and cleanup-before-terminal/
analyzer ordering, pass full and live verification, then run attempt 4.

### 2.9 G7 attempt 4: command success was not executable work

G7 attempt 4, run `45659da07fb749f9b5ebe9c55dd1eb91`
([replay](https://fortgym.live/r/4Gn9v9WaPf_i4qhGJFQs9bo9d8y_GSBo)), ran
208 governed rows and 202,737 ticks from deployed SHA
`808f25d6942b89844768c78b80911646dbb0d5b0`. Lifecycle hardening worked:
terminal status was `failed`, cleanup was verified, the ledger detached, and the
summary was durable. The gameplay gate did not: duration, food/drink production,
population, rooms, beds, and rubric all failed; score-v3 alone passed at 180.56.

The central finding is that a structurally valid DF job can still be impossible
work. The placement helpers chose materials by coordinate distance, not engine
walk connectivity. A post-terminal read-only probe found 36 pending
`ConstructBuilding` jobs, all walk-group disconnected and none connected or
unknown. This engine snapshot does not itself prove whether a connected job has
been claimed by a worker.
The Still was one of them and remained stage 0/3. Separately, `ORDER brew`
recorded manager entries and returned `ok=true` even when no completed Still
existed and the fallback `orders` script was missing; four accepted brew actions
created no brew jobs. These are command-boundary defects, not policy mistakes.

The run also found the next dialog primitive by evidence. A topic-meeting screen
displayed `a - Finish peeking in on conversation`; generic `confirm` sent
`SELECT` and correctly hit the three-unchanged-screen terminal guard. On the
stopped screen, DF's semantic `OPTION1` exited the dialog with no tick advance.
The follow-up therefore adds one view-specific semantic operation rather than
opening arbitrary keyboard input.

### 2.10 The meta-finding: correction discipline is the product

The most reusable result is not a score — it is the method. Across every finding
above, the same discipline held:

- **Measurement changes are operator-approved and never soften a gate.** The
  agent's policy is never steered; only the *legal action surface* and the
  *observation's factual content* are widened, and only with prior approval. When
  a correction raised the G4 bar (plan-agnostic room detection), the bar went up,
  not down — no run to date passed it more easily.
- **Scoring is version-stamped.** `score_version` 1 → 2 → 3 are hard boundaries;
  runs are never compared across them, and every boundary carries a corrections-
  log entry and a calibration table.
- **Failures are reported at equal prominence with passes** — same fields, same
  format, whether a run passes or fails. The stated principle: winning by
  swapping in a softer self-graded finish line is losing.
- **Attribution comes from trace events, not config.** A mid-campaign audit found
  the serving model was GPT-5.5, not the config-default GLM 5.2, because a systemd
  `EnvironmentFile` override had silently defeated the model pin; every prior
  behavioral claim was re-attributed, and future attempts must use
  name-pinned registry variants and verify the model from trace usage events.

The lab's output, then, is a growing catalogue of instrument lies an unbounded
game will tell you — phantom objectives, invisible legality walls, invisible
queued walls, off-frame proof windows, wood blindness, a hardcoded dead metric,
phantom stock counts, and a whitelist that drops a field in transit — each
caught by a failing public run and closed on the record.

### 2.11 G7 attempt 7: genuine production, then a lossy correction loop

Attempt 7, run `82e5c2e18f6847f1bc251158e273f53e`
([replay](https://fortgym.live/r/5dk997_GsCm1IJoKzGL_cLy8On3U7Hxz)),
proved that the new model-authored plan review can pivot after rejection and
start a real production chain. Across 17 governed gameplay rows the GLM-5V
policy recovered from two rejected workshop placements, chopped reachable
trees, completed a Carpenter's Workshop and Still, and produced two beds, one
door, four barrels (finishing with 19), and 50 units of drink. No dwarf died.
This was legal DFHack control followed by real simulation ticks, not score-only
activity.

It was still far from a fortress: zero FarmPlots, installed furniture,
constructions, enclosed spaces, or functional rooms. At step 17 the next model
decision failed before gameplay. The bounded correction loop reported only one
contract violation at a time and omitted the rejected payload from the next
request. Three independently malformed reconstructions exhausted the limit.
The fix is correction quality rather than more retries or weaker validation:
echo the exact rejected payload, report every currently detectable violation,
include authoritative factual control values, then revalidate the complete new
action before execution. The run remains an infrastructure-aborted G7 FAIL, not
a policy pass or long-horizon policy verdict.

### 2.12 G7 attempt 8: the agent started building rooms, then hit its output ceiling

Attempt 8, run `89c7ac68126541888140f6754a50f6f1`
([replay](https://fortgym.live/r/cJWntNq83M0zo-n1NJT6vw7huU8OVur6)),
showed the lossless correction path working under live load. The model recovered
from rejected workshop placement, produced three beds and one door, completed a
Carpenter's Workshop, and built 24 construction tiles. It also reacted to
terrain facts rather than blindly repeating: gather a blocking shrub, abandon a
pebble tile after repeated rejection, revise the objective, and produce doors
as an alternate enclosure strategy. This is the first reviewed-plan run to move
from production setup into substantial room construction on region3.

It still ended with zero enclosed or functional rooms and no sustainable
production loop. At step 22 all three bounded responses consumed exactly the
512-token output ceiling; two emitted no tool call and the third emitted an
incomplete review. The exact observation produced a valid legal action on the
first no-execution shadow when given 1,024 tokens, consuming 830. The correction
is model-output headroom, not gameplay steering: pin GLM-5V to 1,024 response
tokens and leave the contract, retries, action surface, and gate unchanged.

## 3. Limitations

- **A single passing embark family.** Every pass (G0–G4) is on
  `seed_region1_fresh`; G6 is the first move off it, and it stands at zero
  passes in seven region3 attempts. "Plays Dwarf Fortress" is not yet
  demonstrated — "solved one map" is.
- **Small n.** The reliability claim rests on a five-run lineage; the endurance
  result on one probe; the G6 verdict on seven runs; G7 on eight failed attempts.
  These are findings, not distributions.
- **One policy family for most results.** GLM-5V-turbo produced the G4 passes
  and most of the G6 campaign; GPT-5.5 served the earlier G2/G3 passes.
  Cross-model generality is thin — two GPT-5.5-vision escalation runs are the
  only cross-family data points on the unseen map.
- **G6 is unpassed; G7 attempts 1 through 8 failed.** Attempts 2 through 8 were
  infrastructure aborts, not policy verdicts. Score-v3 is active, but the
  chair-factory calibration gap (§2.4) remains part of its historical record.
  Attempt 1 demonstrated why the scalar is telemetry rather than the verdict:
  score 209.44 passed its bar while the fort failed survival and structure.

## 4. What's next

- **Attempt 8 exhausted GLM-5V's 512-token output ceiling; deploy the pinned
  1,024-token budget before attempt 9.** Keep the existing three-submission
  limit and fail closed. A fresh run must turn the now-demonstrated production
  and construction behavior into farms, installed furniture, and multiple
  enclosed functional rooms.
- **G6 remains open**: the best unseen-map run reached 4/5 and missed only its
  second functional room. G7 attempt 8 ran on the same unseen seed, so a strong
  attempt 9 can add evidence without a separate blind retry campaign.
- **G8 — depth**: a multi-z fortress (stairs, underground rooms), the next
  spatial-reasoning escalation past the hollow ring.
- **The open-source flywheel**: a standing public leaderboard where any model
  attempts the ladder, every run replayable at `fortgym.live/r/<token>`.
