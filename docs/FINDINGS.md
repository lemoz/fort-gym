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
observation corrections; G7 is ratified and its first nine attempts failed,
with attempts 2 through 9 infrastructure aborts and no policy verdict.

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
- **Scoring is version-stamped.** `score_version` 1 → 2 → 3 → 4 → 5 are hard boundaries;
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

### 2.13 G7 attempt 9: strong early play exposed an objective/decision ambiguity

Attempt 9, run `4d25c36795eb489faf3c51bec496ae34`
([replay](https://fortgym.live/r/7Ov5ifRPfJ1l2s5mgUI666YmsOlVZYPN)),
validated the output-headroom fix and produced the strongest reviewed-plan
opening so far. The policy completed a Carpenter's Workshop, made and installed
a bed, door, and table, and built 20 construction tiles. It reasoned about
persistent shrub obstructions, abandoned one wall route, and eventually pivoted
away from repeated gather/wait attempts. No response truncated; one reached 951
tokens.

The fort still had zero enclosed rooms, farms, Stills, or food/drink production.
At step 33 the model repeatedly changed its objective while labeling the plan
decision `continue`. The validator correctly failed closed, but its correction
context did not state the required decision as a concrete fact. The fix keeps
strict objective identity and the three-submission limit: report whether the
submitted objective matches the prior objective and state the corresponding
required decision. On the exact no-execution shadow, that clarification produced
a valid `revise` response after one correction.

### 2.14 G7 attempt 10: seasonal ice was being presented as permanent floor

Attempt 10, run `32dc68d1faaa4c10bdd717c0477f4df5`
([replay](https://fortgym.live/r/F7cxVSNhegOQRnnlWmX_pn3s_0ICVVsU)),
ran 101 gameplay advances before an operator diagnostic stop. It built a real
Carpenter's Workshop, three beds, one door, 16 construction tiles, and a Still.
The Still completed at stage 3/3 on nine `FROZEN_LIQUID` floor-shape tiles, then
seasonal thaw changed them to air/ramp and removed the building. The observation
had called those tiles stable `.` floor, so the model retried the vanished site.
Score-v4 corrects this measurement boundary: ice is a separate `i` category,
never receives stable floor/room credit, and every structured BUILD rejects it.
Workshop discovery now shares BUILD's liquid, locality, path, and reachability
preflight and republishes a fingerprinted candidate after every action.

### 2.15 G7 attempt 11: truthful sites enabled play, then spatial truth lagged

Attempt 11, run `beaf1a3f0c99478bb504bdd8f004e2ec`
([replay](https://fortgym.live/r/SFFx5jWKPJxYYywMVIpXuw4d3vwRePna)),
was stopped after 51 gameplay advances once a policy failure persisted. It
completed both production workshops, produced three beds and three doors, built
a FarmPlot, gathered plants, created brew jobs, and made 50 constructions with
proof records on all 51 gameplay rows and no death. Productive-change proof
passed on 44/51 rows; the other seven truthfully recorded rejected BUILDs.
Unlike attempts 6-9, it crossed every review boundary without an infrastructure
abort.

It still produced zero food/drink, installed no furniture, and enclosed no
space. Three factual defects mattered. The embark Wagon occupied nine tiles that
the agent minimap rendered as `.`, FARM wrote transient crop slots on a stage-0
plot that DF cleared when construction completed, and the room explanation did
not explicitly say that a solid W mass encloses nothing. The next correction
marks every otherwise-unclassified building footprint as occupied `o`, rejects
FARM until the plot reaches maximum construction stage, and defines a room as a
one-tile-thick hollow ring around untouched passable interior.

### 2.16 G7 attempt 12: GLM-5.2 required its documented tool transport

PR #81 deployed the attempt-11 corrections and passed a four-row fresh-seed
smoke. The first observation showed all nine Wagon tiles as `o`; a live probe
then proved crop selection rejects at FarmPlot stage 0/3, accepts at 3/3, and
persists across another 1,007 ticks.

Attempt 12, run `6834a9ee41d54b629d88a56913a123dd`
([replay](https://fortgym.live/r/fu-pA7GAYbvq8nfe0-VdlH7LRdLLKI1Q)),
tested pinned GLM-5.2 but failed before gameplay. Three forced `submit_action`
calls returned partial argument objects and the review contract correctly
refused to execute them. An exact-state no-execution comparison found that the
provider's documented `tool_choice=auto` returned the complete governed schema;
JSON mode returned a type-invalid field. The follow-up changes transport only,
leaving governance and gameplay controls intact.

### 2.17 G7 attempt 13: automatic tool selection was a false positive

PR #82 deployed the exact-state `tool_choice=auto` result, but attempt 13 run
`74ac5d02872548d8971a54159bf17446`
([replay](https://fortgym.live/r/93gd9qD8DVw3VnmM77-3TWA-jwIshzI6))
failed before gameplay. Its three calls returned no tool, a partial object, then
malformed nested fields. Giving automatic calls 1,024 output tokens still
failed 3/3 on the exact state, disproving output headroom as the fix.

JSON-object transport with an explicit field/type reminder passed the same
observation 3/3 at the normal 512-token cap, each on its first call. This is
transport evidence only: the unchanged validator accepted the model-authored
actions, but no game action executed during the probe. Attempt 14 must provide
the policy verdict.

### 2.18 G7 attempt 14: JSON transport reached gameplay, then hit its cap

PR #83 deployed JSON-object transport and attempt 14 run
`af3b1c0609934afeab2c401c78351ef8`
([replay](https://fortgym.live/r/ZdSulSc9wjLoAgThfzFovsNao66JobGy))
executed 25 governed gameplay rows and 25,073 ticks. It made a Carpenter's
Workshop, three beds, three doors, seven gathered plants, and 14 construction
records. It made no Still, FarmPlot, sustainable production, installed
furniture, or enclosed room. Geometry and target preflight remained recurring
policy failures despite a truthful minimap and rejection evidence.

The terminal row was transport, not policy: a parseable response failed review,
then two corrections exhausted the 512-token cap before completing JSON. The
exact terminal state passed JSON mode 3/3 at 1,024 tokens, first call each; one
valid response needed 536 tokens. The follow-up raises only pinned GLM-5.2's
output ceiling so attempt 15 can test the unresolved gameplay policy.

### 2.19 G7 attempt 15: output headroom held; evidence correction was ambiguous

PR #84 deployed 1,024-token JSON output headroom for pinned GLM-5.2. Attempt 15,
run `3a1c362b5d1e45dabf5fdee123ba21e5`
([replay](https://fortgym.live/r/HR2tNr4QPUFquhPlh1WaoB0b5xS9QpeZ)),
executed 24 governed gameplay rows and 24,094 ticks. All 24 rows retained screen
text, governed provenance, and DFHack proof. The agent built complete Carpenter
and Still workshops, produced three beds, five doors, two tables, and three
chairs, made 18 constructions, and queued brew jobs. It adapted from an initial
brew rejection by building the required Still. Geometry remained weak: three
wall segments partly collided with occupied tiles, only one production space
was observed, no furniture was installed, and no FarmPlot was built. Brew jobs
disappeared without production; final run flow was food 0 produced / 0 consumed
and drink 0 produced / 7 consumed.

Deterministic gate-v2 is FAIL. Evidence and neglect-death criteria pass; 24,094
of 403,200 required ticks, population 7/15, functional rooms 1/3, installed beds
0/3, and score-v4 109.75/150 fail. Rubric 90.93 with zero blockers passes. The
terminal failure is separate: three GLM responses were complete, parseable JSON
at 366, 406, and 488 completion tokens, but all violated the review contract.
The first had a wrong request id and invalid evidence; both corrections retained
invalid `plan_review.evidence`.

The retry path described required E-ids as "observation-grounded excerpts" and
did not repeat the allowed factual catalog near the correction. The candidate
uses E-id terminology consistently, includes exact allowed IDs and lines in
each retry, and rejects duplicate plan evidence even when review is not due. It
does not auto-fill, de-duplicate, or select evidence for the model. An exact
attempt-15 terminal-state no-execution probe, seeded with a deliberately invalid
payload, recovered on the first live GLM correction with `E14` and `E20` in 276
completion tokens.

### 2.20 G7 attempt 16: evidence retry recovered; unfocused corrections later truncated

PR #85 deployed the exact evidence catalog and consistent E-id terminology.
Attempt 16, run `1b1218635a1647ba96d83189c1095bd4`
([replay](https://fortgym.live/r/S9_rAjwEV9CtCZaC6z4R0yOHP_vuPiUb)),
executed 32 governed gameplay rows and 32,127 ticks. All 32 gameplay rows have
screen text, governed provenance, and DFHack proof. It crossed the previous
step-24 terminal and recovered from a real step-25 review error on its first
correction before executing gameplay.

Policy quality still failed. The agent completed a Carpenter workshop, produced
three beds, three doors, and two tables, and made 22 constructions, but enclosed
no space and installed no furniture. It repeatedly designated the same shrub,
called accepted designations progress despite zero changed tiles, then retried
the blocked wall. It built no Still or FarmPlot and produced zero food and drink
while seven drinks were consumed. Deterministic gate-v2 is FAIL: evidence,
neglect-death, and rubric 82.75 with zero blockers pass; duration 32,127/403,200,
population 7/15, rooms 0/3, beds 0/3, sustainable production, and score-v4
92.04/150 fail.

The terminal row exposed a different correction defect. Its initial 504-token
JSON parsed but used `decision=revise` without changing the objective. Although
that error did not involve evidence, the correction repeated the complete
24-line evidence catalog; both correction responses then exhausted the
1,024-token cap and became non-JSON. The candidate includes that catalog only
when an evidence error is present and states the exact required decision repair.
An exact terminal-state no-execution probe recovered at the unchanged cap in one
257-token correction. Separately, the trace proved that submitted
`advance_ticks=1500` was silently clamped to 1,000 by the external DFHack helper;
the candidate aligns that helper with the action schema's existing 2,000-tick
maximum so the model actually chooses its turn duration.

### 2.21 G7 attempt 17: control fixes held; legacy UI advice serialized the policy

PR #86 deployed focused review corrections and aligned the DFHack tick helper
with the action schema's 2,000-tick maximum. Attempt 17, run
`5ab033b5f9fc4d94817ec6a183c1352c`
([replay](https://fortgym.live/r/sUHqPDy822vChqPuXQmZhnw5QVbuQBOT)),
crossed the prior step-32 terminal and remained live until it was deliberately
stopped at step 40 after a stable policy loop was proven. The first model action
requested 1,500 ticks and the helper advanced 1,507; later requests likewise
retained the model-selected duration. Review correction no longer terminated
the run.

The resulting gameplay was legal but ineffective. The trace contains 41 action
rows: six BUILD, ten DIG, five ORDER, and twenty WAIT. The agent completed one
Carpenter workshop, produced three beds and four doors, and made 19
constructions. It installed no furniture, enclosed no room, built no Still or
FarmPlot, and produced zero food or drink while consuming seven food and 18
drinks. Score-v4 reached 90.76 and the deterministic rubric reached 82.19 with
zero blockers, but those telemetry values do not satisfy G7.

The run exposed an observation-policy contradiction rather than a missing game
control. At step 39, with five of seven citizens idle, the governed observation
said not to switch away from ten queued carpenter tasks and to prefer an
empty-key wait or `D_JOBLIST`. Those are legacy keystroke-agent instructions;
the direct governed agent can issue another legal overseer command while the
carpenter works. A second encoder sentence told the model to wall both `.` and
`,` border gaps even though BUILD accepts only stable `.` floor. The model also
described `(88,100)` while submitting a gather rectangle on `y=94` at step 10,
and described `(89,94)` while submitting `(88,94)` at step 36.

The run was manually stopped to avoid spending the remaining 410 decisions on
the known loop. Its interrupted final row leaves 40 complete screen/proof
records for 41 action rows and makes the trace duration disagree with the
summary, so deterministic gate-v2 correctly fails evidence as well as duration,
production, population, rooms, beds, and scalar score. The follow-up remains
inside the agent loop: governed observations describe real parallel labor
capacity instead of menu navigation, the model must compare survival, shelter,
production, idle labor, queues, and stalls at due reviews, coordinate prose must
match submitted params, and BUILD guidance consistently reserves non-`.` glyphs
as invalid targets. The harness still chooses no objective, coordinate, or
gameplay action. Local verification is 165 focused tests and 723 full-suite
tests passed, 5 live-only skipped, with Ruff, compileall, and `git diff --check`
clean. Independent Terra review found and then verified fixes for two remaining
shared-encoder leaks; its final review reported no concrete blocker.

### 2.22 G7 attempt 18: parallel play produced drink; spatial perception still failed

PR #87 deployed the governed-only observation correction as
`4ab899dfa74b366f4d862626ae4cacdbaa6a374c`. Attempt 18, run
`78dd47ecda9f451a87d64560b9c79adc`
([replay](https://fortgym.live/r/t87w_HCV17O8bNaHl7GcN5uFuNhjmAF-)),
used fresh `seed_region3_fresh`, OpenRouter `z-ai/glm-5.2`, memory off, and a
450-step budget. It crossed every earlier transport and review terminal. The
model used legal parallel work: Carpenter and Still jobs progressed alongside
new commands, a completed FarmPlot was configured only after stage 3/3, and the
agent abandoned several failed coordinates instead of waiting on one queue.

This was the first G7 run with a real positive production loop. The Still
produced 90 drinks while 19 were consumed. The agent also completed a Carpenter
workshop, a Still, one FarmPlot, three beds, three doors, three tables, 18
barrels, and at least 32 construction records. It issued 24 BUILD, 11 DIG, two
FARM, two LABOR, ten ORDER, three UNSUSPEND, and 17 WAIT actions. The 97 model
calls used 1,409,050 prompt and 46,280 completion tokens.

The run was stopped after 69 action rows because its remaining failures were
stable. Sixty-eight rows have complete screen/proof records; the interrupted
last row and manual stop produce a duration mismatch (83,059 trace ticks versus
81,857 summary ticks). Food production remained zero while six food were
consumed, population fell to six after one drowning, and no furniture was
installed. Despite 32 durable constructions, the agent enclosed zero spaces and
created zero functional rooms. Score-v4 106.33 and rubric 84.13 with zero
blockers are telemetry; deterministic G7 fails evidence, duration, food/drink,
population, rooms, beds, and scalar score.

The decisive policy error was spatial. The text model repeatedly called
non-floor targets verified, confused a room border with its interior, and later
filled complete interior rows while describing them as border rows. The
observation also collapsed `SHRUB`, `SAPLING`, `BOULDER`, and `PEBBLES` into
`,` even though only a true shrub can be gathered; five identical gather
attempts targeted one blocked row. Finally, DF exposed the dead unit's direct
`drowning=true` flag while leaving `death_cause=-1`, so both evidence hooks
reported an unknown cause and the observation withheld the record details.

The attempt-19 candidate changes factual perception, not strategy. It preserves
the unknown cause when the authoritative enum is unset while exposing the raw
drowning condition and bounded death-record details; the minimap separates
gatherable shrubs from saplings and loose rock. The next fresh-seed run uses the
existing `dfhack-governed-llm-glm5v` alias (OpenRouter
`z-ai/glm-5v-turbo`), which receives a PNG of the same trace-recorded minimap.
No planner, room template, coordinate, action, or score credit is added.

### 2.23 G7 attempt 19: real play, then operator-contaminated and invalidated

Attempt 19, run `e75981445d9a4b0786ed7b1b81afb499`
([replay](https://fortgym.live/r/or01cSujoIE17kNnOVianwx1_SeEGhM8)),
ran the deployed score-v4 commit
`21b2b7dc31a24ddb8d6cdf13fa40f592e1908c83` on fresh
`seed_region3_fresh` with OpenRouter `z-ai/glm-5v-turbo`, memory off, and a
450-step budget. The policy made real game changes before the incident: it
escaped liaison dialogs, reached population 17, recorded 112 constructions,
completed a Still and a surface FarmPlot, selected subterranean plump helmets
for that surface plot, and produced 25 drinks. It never established food
production. Food and drink both later reached zero, six citizens died, and the
policy repeatedly queued brew orders while native observations showed zero
brewable plants.

This run has no valid terminal policy verdict. While validating a candidate
stair-designation hook, the operator targeted `(99,101,161)`, expecting the
Still's footprint to make the probe fail closed. The candidate instead applied
three one-tile stair designations under the building. The exact designation was
immediately cleared and a stop was requested, but an external mutation had
already occurred. The run is therefore **CONTAMINATED / INVALID**, regardless
of whether the mutation affected later state. This also proved that the
candidate's occupancy guard was unsafe and that mutation probes must never run
against an active scored run.

The stopped artifact ended at step 290 with scalar score 155.16. A diagnostic
gate-v2 evaluation reported 291 gameplay rows but only 290 screen/proof rows,
321,997 summary ticks versus 323,204 trace ticks, food production 0 versus 35
consumed, drink production 25 versus 85 consumed, final food/drink 0/0, one
functional room, three installed beds, six deaths with unknown causes,
population 16, rubric 76.56 with zero blockers, and 353 model calls using
6,299,908 tokens. Those values are retained only as incident diagnostics; they
are not an official G7 result. The pre-incident resource collapse independently
shows that the policy had already failed the survival objective, and the scalar
and rubric pass-shaped values again demonstrate why neither is the verdict.

The next run is gated on disposable-save proof. The smallest candidate is a
visible, legal floor-capable channel action whose designation, DigChannel job,
completed top/lower geometry, walk connectivity, citizen traversal, and
underground farm loop are all observed from native DF state. Governed runs must
also lose runner-selected starter/workshop coordinates, and farm controls must
reject tiles and crops that the native game would not offer. No long scored run
resumes until those controls pass without hidden-map reads or forced
completion.

### 2.24 Disposable access/farm proof: native channel-to-harvest loop passed

The attempt-20 control candidate was validated against DFHack 0.47.05 on a
disposable `seed_region3_fresh` reset, outside the run registry and with no
active scored run. This is control proof, not a policy result. Read-only
candidate `work_metrics`, `job_metrics`, and `fort_metrics` hooks first executed
successfully against the real VM. Global work mode emitted actual jobs,
workshops, labors, and orders while omitting every legacy starter/connector/
workshop-room field.

The exact attempt-19 incident coordinate was replayed before the reset. A
channel request at the Still center `(99,101,161)` failed with
`occupied_by_building`, `newly_designated=0`, and the tile designation remained
`No`. The existing surface FarmPlot likewise rejected subterranean plump
helmets with `surface_crop_options_unverified`; all four existing crop slots
remained unchanged. These are negative no-op regressions only, not gameplay.

On the fresh disposable save, `channel` at visible floor `(90,90,161)` returned
`newly_designated=1`. After 21 ticks the action-focused observer reported one
pending channel designation. After another 205 ticks DF had cleared the tile
designation into assigned native `DigChannel` job `2` at the same coordinate;
the observer initially missed that linked-list job, which exposed and fixed a
numeric-enum/list traversal bug in both focused and global work metrics. After
1,207 more ticks the job was gone and the same coordinate had
`RAMP_TOP` at z=161 over `RAMP` at z=160. Native
`dfhack.maps.canWalkBetween` returned true, so the focus status was
`connected` with one completed geometry pair and one native-connected pair.

The proof then designated ordinary `Dig` work below. Citizen `243` was observed
at `(91,90,160)` performing an assigned Dig job, proving physical traversal,
not merely compatible glyphs. A one-tile FarmPlot at `(92,90,160)` passed the
native-soil guard, created a normal construction job, and reached stage 3/3.
Its observation listed native underground crop options per season. A spring
`GRASS_TAIL_PIG` request failed as `crop_not_offered` with all slots still -1;
`MUSHROOM_HELMET_PLUMP` was offered in all four seasons and changed all four
slots to raw index 172. DF then created assigned `PlantSeeds` job `8` at the
plot.

No growth or harvest was accelerated. The simulation advanced in ordinary
2,000-tick turns until the planted seed's native growth counter matured. The
run-scoped evidence ledger, started before maturity, ended at tick 54,497 with
`food_produced_in_run=2`, `nonfarm_plants_created_in_run=0`, complete flow
evidence, and no deaths; DF had already created a new PlantSeeds job for the
next cycle. The ledger was stopped and the runtime reset again from pristine
`seed_region3_fresh`. Final reset attestation was population 7, farm plots 0,
and evidence active false.

This closes the control-semantic uncertainty for the smallest depth slice. It
does not show that the model will choose these actions. The remaining question
for attempt 20 is policy: with no runner-selected geometry, can the agent infer
and execute the same native loop while also building shelter and maintaining
survival?

### 2.25 Independent pre-deploy review hardened ownership and local proof

The first independent review of the attempt-20 candidate found six deploy
blockers. The candidate now fails governed startup when the harness-only
`FORT_GYM_DFHACK_COMPLETE_DIG=1` flag is present and also disables that path in
the executor. Channel designation rejects the DFHack 0.47.05 native material
exclusions, commits rectangles transactionally, and rereads every designation.
Farm crop selection likewise rereads all four native season slots and rolls all
of them back on a write/readback mismatch.

The observation no longer emits fort-wide completed-access coordinates or
runner-computed tree-cluster centroids. Nearby-tree scanning checks visibility
and reports only a count; target coordinates must come from visible maps.
Replay snapshots previously retained tiletype/material fields after labeling a
tile hidden, those fields are now omitted before any hidden-tile inspection.
Since DFHack 0.47.05 does not expose `Maps::canStepBetween` to Lua, channel
completion
mirrors that version's ordinary diagonal-ramp predicate locally, then requires
native `canWalkBetween` for the exact lower-ramp/adjacent-upper endpoints and a
citizen. An unrelated staircase elsewhere cannot satisfy the focused proof.

Score-v5 now treats accepted excavation designations as ownership evidence, not
scalar progress. Only a model-owned tile later observed as a native completed
dig floor or channel ramp top raises governed work/completion; raw global jobs
and plan-era counters are audit-only. Summarization keys off that explicit
provenance, so raw global values cannot re-inflate the scalar. No v5 artifact
existed locally or publicly before this boundary was finalized.

At that first-pass point the pre-deploy candidate had 763 passing tests and
5 live-only skips; Ruff, compileall, and diff checks passed. On the pristine VM,
a candidate channel request over wagon tile `(95,97,161)` rejected
`occupied_by_building`; its designation and block flag remained unchanged. A
hidden z=160 snapshot contained only coordinates, `hidden=true`, `category`,
and `?`, with no tiletype, shape, material, designation, or building data.

The complete disposable matrix was then repeated. Channel `(90,90,161)` moved
from one designation to native assigned `DigChannel` job 2, then to
`RAMP_TOP/RAMP` with one local-step pair and one native-connected pair. Citizen
243 was observed at `(91,90,160)` doing assigned `Dig` job 4. A stage-3/3
FarmPlot at `(92,90,160)` rejected spring pig tails without changing its four
slots, then transactionally read back plump helmets as raw 172 in all four
slots. Native `PlantSeeds` job 6 was assigned. A ledger started before planting
and ordinary 2,000-tick turns ended at tick 54,684 with
`food_produced_in_run=1`, `nonfarm_plants_created_in_run=0`, complete flow/death
evidence, and zero deaths; job 25 was already replanting and seed stock had
moved from five to four. The ledger was stopped and the VM reset; final
attestation was population 7, farm plots 0, seed stock restored to five, and
evidence inactive. Fresh independent re-review remains required before deploy.

### 2.26 Second review closed excavation and hook gaps but left two scoring paths

A fresh Sol review correctly returned **DO NOT DEPLOY** after the first
hardening pass. It found that ownership was still derived only after requested
ticks, so DF could clear a designation into an assigned job before the runner
recorded it; later completion checks followed the camera window instead of all
owned coordinates. It also found that a designation could unlock accumulated
duration score, governed summary could fall back to raw global progress,
`/step` still constructed a permissive executor, and channel focus could adopt
an already-designated no-op.

The runner now snapshots the exact footprint before and immediately after the
paused helper write, records only newly observed designation/completion tiles,
and monitors unfinished ownership in bounded coordinate buckets independent of
the replay window. Newly completed owned coordinates and kinds are persisted in
`gameplay_proof.owned_completion_observation`, so off-camera scalar progress has
matching trace evidence. Focus is one newly owned channel tile, not the submitted
rectangle. Designation, labor, unsuspend, accepted order, and unrelated wait
changes cannot unlock elapsed score. Every governed v5 trace row must carry
`dfhack_governed_action_owned_excavation_v1`; re-summarization otherwise raises
instead of accepting raw work/completion. At this intermediate point `/step`
disabled assisted completion for every model, but it still retained a separate
raw scoring loop. Section 2.27 records the later review that found this was not
a sufficient governed boundary.

The same review caught three Lua truth gaps. DFHack 0.47.05 `findAtTile` returns
early when occupancy is zero, so dig and farm collision checks now scan
`world.buildings.all` footprints directly. Chop/gather now use full
preflight/commit/readback/verified rollback, and any helper response with
`rollback_verified=false` terminates the run before ticks advance. Hidden room
floods now check hidden state before tiletype/material and treat hidden tiles as
leaks; the global `citizens_below` field is gone. Finally,
`crop_options_complete=true` now requires successful seed and plant scans plus
no 12-item truncation; partial lists are withheld.

The affected regression suite passed 384 tests; the final full suite passed 773
with 5 live-only skips, and changed Python passed Ruff and compileall.
Disposable execution against DFHack 0.47.05 proved both wagon-tile collision
rejections, one real chop and
one real gather transactional designation, hidden-snapshot opacity, legal
channel designation, and read-only job/fort hook execution. The VM was reset
from `seed_region3_fresh`; final attestation was farms 0, the channel target
undesignated, and evidence inactive. This evidence repairs the candidate; it is
not a deployment claim.

### 2.27 Third review closed the alternate runner and global non-excavation score

A fresh Terra review correctly returned **DO NOT DEPLOY** on the revised
candidate. First, the administrative `/step` endpoint still accepted governed
models, advanced DF, and scored raw global state outside the serialized runner's
ownership, rollback, duration, and trace rules. Disabling its assisted dig
helper did not make that alternate loop governed. Second, the core runner
replaced global work/completion with owned excavation but continued paying
global utility, production, and complexity; an unrelated completed workshop,
room, construction, or produced item could therefore raise the scalar and
unlock accumulated duration.

The candidate now centralizes governed model classification in
`run/model_modes.py` and returns HTTP 409 from `/step` before creating context
or a DFHack client. Governed runs have one mutation/advance/scoring path. The
serialized runner also keeps an exact non-excavation ownership ledger: accepted
CarpenterWorkshop, Still, and FarmPlot BUILDs must return a concrete
`building_id`, and completion is recognized only when native `job_metrics`
reports that same ID and authored kind at completed build stage. Only exact-ID completed owned
Carpenter workshops feed the existing utility/production capacity terms;
complexity is zero until equally exact causal evidence exists. Global goods,
output, workshop, room, enclosed-space, construction, and furniture changes are
retained as `observed_global_*` audit facts but cannot pay governed scalar
progress or unlock duration. ORDER lifecycle/output remains audit evidence only
because the current surface does not link one produced item to one exact order
job.

Governed summary now requires
`dfhack_governed_action_owned_progress_v2` and replaces all six progress inputs
with owned fields. Regression proof covers pre-client `/step` rejection,
unrelated global progress remaining zero with duration blocked, exact-ID
workshop completion earning capacity only after native readback, and summary
reaggregation refusing global fallback. The focused suite passed 149 tests; the
full suite passed 779 with 5 live-only skips. Changed Python is Ruff-clean and
compileall passes. This remains candidate evidence pending the final independent
verdict, merge, exact-SHA deployment, and boundary smoke.

### 2.28 Sol Ultra review closed four deeper fail-open paths

The final broad pre-deploy review returned **DO NOT DEPLOY** with four further
P1 findings. Native workshop/farm stage reads initialized to `0/0` and ignored
`pcall` failure, so failed telemetry could emit `built=true`. Workshop,
furniture, and construction helpers could report `error=rollback_failed`
without `rollback_verified=false`, bypassing the runner's zero-tick quarantine.
Summary reaggregation treated a missing or non-boolean
`score_duration_blocked` as unblocked. Finally, the deterministic rubric still
paid global workshops, rooms, constructions, and WAIT-time world changes even
though the scalar had switched to owned fields.

The candidate now emits `stage_read_ok` only after successful numeric native
stage reads with `max_stage > 0`; `built` is false otherwise. The runner
independently requires that attestation, internally consistent stage values,
the exact owned building ID, and matching workshop kind. All mutating building
helpers emit `rollback_verified`, while the runner also recognizes top-level or
nested `rollback_failed` errors and advances zero ticks. Reaggregation requires
an actual boolean duration gate on every governed action-truth row. The rubric
selects `governed_owned_*` work, completion, utility, production, complexity,
and completed-Carpenter fields whenever the v2 ownership marker is present;
global rooms and constructions remain visible in traces but cannot pay or clear
governed blockers. A WAIT-time world change is concurrent evidence only unless
the runner later matches it to an owned excavation or building completion.

Regression coverage includes false `built=true` with failed `0/0` stage reads,
explicit rollback failure without the flag, missing/string/integer duration
gates, unrelated global workshop/room/construction changes in both scalar and
rubric, delayed exact-ID completion, and owned WAIT completion. The affected
suite passed 256 tests; the full suite passed 786 with 5 live-only skips.
Changed Python is Ruff-clean, compileall passes, and `git diff --check` is
clean. Candidate copies of all four changed Lua hooks parsed on production
DFHack 0.47.05, and the read-only `job_metrics` hook executed with `ok=true` on
the pristine save (farms 0, workshops 0). Sol Ultra re-reviewed only its four
findings, independently reproduced 256 focused and 786 full-suite passes, found
no remaining issue, and returned **DEPLOY**. PR #90 subsequently passed CI,
merged, and deployed at exact SHA
`f2cc864c9f36f4d847223da50bd70d143b5a3a07`. Production now runs score-v5 with
the v2 ownership provenance. Section 2.29 records scored Attempt 20.

### 2.29 Attempt 20 proved exact workshop ownership and exposed a drifting minimap

Attempt 20, run `f8ebc607402f4756838df19aecb75cc7`
([replay](https://fortgym.live/r/IKqmVcZUvy_n5kGowOSfNUcGQdNZrfVa)),
ran the deployed PR #90 merge SHA on fresh `seed_region3_fresh` with OpenRouter
`z-ai/glm-5v-turbo`, vision enabled, memory disabled, and a 450-step budget.
The operator stopped it after the early trace appeared saturated; the stop
raced with the runner, and the final rows showed that the policy had just
recovered. The artifact therefore remains a valid short diagnostic but is not
a full-horizon policy verdict.

The policy performed real gameplay. It felled a tree, gathered three shrubs,
completed one surface FarmPlot, then legally placed Carpenter workshop `#2` at
`(89,98,161)`. Two ordinary UNSUSPEND turns allowed native construction to
reach its final stage, after which the policy queued five barrel jobs. Score-v5
correctly attributed only the exact completed owned Carpenter ID: utility and
production became 5 each, while designation, the accepted ORDER, global goods,
rooms, and constructions paid no governed credit.

Deterministic G7 failed at 27,879/403,200 ticks with food production/consumption
0/0, drink production/consumption 0/7, population 7, no installed beds, no
functional rooms, score-v5 72.70, and rubric 58.25 with
`no_fort_structure` and `no_broader_fort_layout`. Evidence passed: all 24
executed gameplay rows carried screen text, gameplay proof, governed v2
provenance, and one attributed OpenRouter model; 4/24 proof records had
`ok=true`. No neglect deaths occurred. Thirty-six calls used 501,578 total
tokens.

The expensive early correction loop came from the observation, not missing
DFHack control. The minimap's anchor list reused the room classifier, which
only retained beds, tables, chairs, doors, and workshops. It therefore ignored
the starting wagon, the new FarmPlot, and every other occupied building type.
When the fishing dwarf moved to `(24,8)`, the citizen bbox pulled the bounded
map to `(20,4)` and cropped the actual fort near `(92,97)` out of view. The
policy alternated coordinates from that displaced map with prior fort
coordinates, producing repeated `tile_not_open_floor` and
`too_far_from_fort` rejections before it recovered.

The narrow candidate keeps the solution inside the agent loop. The factual
minimap now anchors to every visible player-building footprint and falls back
to visible citizens only when no visible building exists. A rejected 3x3
workshop reports the absolute first failing tile and categorical reason through
the existing `Failed tiles` observation. Neither change searches for a
placement, suggests a coordinate,
chooses an action, or changes scoring. Terra review rejected the first draft
because hidden buildings and markers could still influence the map origin. The
revised hook visibility-gates anchors, citizen markers, constructions, and the
renderer; re-review found the P1 closed and returned DEPLOY.

### 2.30 Attempt 21 reached real underground farming, but only after survival was lost

Attempt 21, run `eecdd0e5d0924f9a984c96d702f09d59`
([replay](https://fortgym.live/r/JBVG-tn9pxYcd_MJMMICYhXr7WqTK0gx)),
ran deployed PR #91 merge SHA
`ae15fcfb282dbb084dc7574f1242ed97a7ec2051` on fresh
`seed_region3_fresh` with OpenRouter `z-ai/glm-5v-turbo`, vision enabled,
memory disabled, score-v5, and a 450-step budget. It retained 296 governed
rows, 295 screen/proof records, 55 `gameplay_proof.ok=true` records, and 296
governed-provenance rows. Four hundred five model calls used 7,992,508 total
tokens.

The stable minimap was enough for genuinely deeper play. The policy completed
a Carpenter workshop, surface FarmPlot, two beds, one door, and 26
constructions. After many failed surface DIG attempts it independently chose
channel at step 169, completed a connected native ramp by step 196, and
excavated 27 owned lower-level tiles. Its first lower FarmPlot was correctly
reported light/outside. It then built subterranean FarmPlots `#21` and `#23`,
selected native-offered `MUSHROOM_HELMET_PLUMP` for all seasons, completed
Still `#22`, enabled additional farmers, and observed native planting and
harvest. Run-scoped food production reached 3. This is the first scored G7
artifact to demonstrate model-discovered vertical access, a real
crop-configured subterranean farm, and a completed Still in one uninterrupted
policy run.

It was not sustainable play. The policy needed 235 steps to reach the first
valid underground plot, repeatedly submitted accepted zero-target gather/chop
actions, confused pending channels with completed access, mixed ramps and
hidden cells into atomic dig rectangles, and spent materials on malformed room
geometry. The first tiny harvests were eaten immediately. Population peaked at
22, then final stocks reached food 0 and drink 0 while the death ledger rose to
11 records with unknown causes. Final flow was food 3 produced/54 consumed and
drink 0/60; no functional room was completed.

Deterministic G7 is FAIL. Summary duration 318,470 disagrees with the final
stop-after-advance trace at 319,673, both below 403,200. Population 15 passed;
food/drink, three rooms, five beds, rubric 59.62 with
`no_broader_fort_layout`, and score-v5 90.30 all failed. Neglect is UNKNOWN
because causes were not captured for all deaths. The stop left 296 gameplay
rows but only 295 screen/proof rows, so evidence failed closed too.

The resulting candidate remains an agent-observation change, not an external
planner. It makes minimap index-to-x conversion explicit, reinforces the native
channel and underground-farm lifecycle already present in observations, and
returns bounded factual non-target samples for chop/gather. Hidden samples
never disclose tile shape/type. A stopped-save production-runtime probe proved
one visible `not_tree` sample and one hidden-only `hidden_unexplored` sample
with both tiles and the building count unchanged.

### 2.31 Attempt 22 front-loaded the fort, then exposed a missing legal UI exit

Attempt 22, run `e83950a358e745c4ad3f0796e4c9c8bb`
([replay](https://fortgym.live/r/Ly6r_18HCyz-MdmJw8Zr_AmHybpjtKiX)),
ran deployed SHA `73700c5d588859c8c8ebfd1623895b59e1f87b6b` on fresh
`seed_region3_fresh` with OpenRouter `z-ai/glm-5v-turbo`, vision enabled,
memory disabled, score-v5, and a 450-step budget. It retained 156 governed rows;
all 156 had screen text, gameplay proof, and governed provenance, with 51
`gameplay_proof.ok=true` rows. Two hundred ten model calls used 4,228,125 prompt
and 151,504 completion tokens.

This was the strongest opening yet. The model completed a native connected
channel by step 3, lower excavation by step 8, Carpenter workshop `#1` by step
21, and Still `#2` by step 30. It placed subterranean FarmPlot `#3` at step 42;
the plot first reached stage 3 at step 45, and step 46 selected plump helmets in
every season. Native brewing
produced 75 drink, planting produced five food units, and the first migrant wave
raised population from 7 to 15 at step 88. Three beds were installed. The final
fort had 56 constructions, two enclosed production spaces, and two functional
rooms. No dwarf died, and the complete run-scoped death ledger recorded zero
neglect deaths.

The fort was not yet sustainable. At 200,252 trace ticks, food flow was 5
produced/36 consumed and drink was 75/81; final stocks were food 15 and drink
54. Deterministic G7 gate-v2 passed evidence, population, and neglect deaths.
It failed duration, both resource flows, functional rooms 2/3, installed beds
3/5, rubric 59.38 with `no_broader_fort_layout`, and score-v5 93.31/150.

The terminal failure was a missing legal control, not a simulated action. A
real liaison sequence repeatedly interrupted tick advances. At step 154 one
bounded INTERACT moved from `viewscreen_topicmeeting_takerequestsst` to
`viewscreen_storesst`, the native Wealth/Stocks screen. The encoder classified
that screen as low-confidence unknown, its governed instruction was omitted,
and `viewscreen_storesst` was absent from the INTERACT allowlist even though the
existing `cancel` operation maps to one legal `LEAVESCREEN` key. The model
incorrectly called the screen non-blocking, submitted BUILD at an already-built
wall tile, and requested 1,200 ticks. The BUILD was rejected `already_wall` and
zero ticks advanced, so the runner correctly terminated
`tick_timeout_zero_progress` rather than inventing progress.

The narrow correction is control plumbing, not a planner: classify the attested
Stores screen as blocking, allow exactly zero-tick `INTERACT cancel`, reject any
other Stores-screen action before execution or time advancement, and wait for a
fresh observation. Coordinate selection and all fortress strategy remain with
the model. Separately, the next observation candidate surfaces compact G7
planning facts but fails closed on invalid survival scope and never claims a
terminal verdict.

PRs #94 and #95 passed CI, merged, and deployed together at exact SHA
`506ce6986029c5885ecb26074fa45ac55d47c541`. Production DF was still paused on
the real terminal `viewscreen_storesst`, so the deployed boundary could be
tested without reconstruction. It classified the screen `stores/high`, rejected
the old step-155 BUILD before execution, and sent exactly one zero-tick
`LEAVESCREEN`. DF returned to `viewscreen_topicmeeting_takerequestsst`; tick
217,563 was unchanged. Fresh-seed Attempt 23 then launched on that exact SHA
([replay](https://fortgym.live/r/uGx2o874VECGSlqciDUrbQxo-JrbkQ41)).

### 2.32 Attempt 23 built two real rooms, then sealed its farm and lost drink

Attempt 23, run `94ea15d9c6c141da9540ced2a216493e`
([replay](https://fortgym.live/r/uGx2o874VECGSlqciDUrbQxo-JrbkQ41)),
ran deployed SHA `506ce6986029c5885ecb26074fa45ac55d47c541` on fresh
`seed_region3_fresh` with OpenRouter `z-ai/glm-5v-turbo`, vision enabled,
memory disabled, score-v5, and a 450-step budget. It retained 126 governed rows;
125 had screen/proof records, 59 proofs had `ok=true`, and all 126 retained
governed provenance. One hundred sixty-two model calls used 3,389,252 total
tokens.

The opening was real and useful. The policy completed connected channel access
at step 2, excavated 43 owned tiles, completed a subterranean FarmPlot and set
plump helmets in every season, felled trees, built a Carpenter workshop,
produced and installed furniture, and constructed 14 walls. Those actions
created two enclosed functional rooms. A surface Still eventually completed at
step 114, population peaked at 11, and run-owned farming produced three food
units. No drink was produced.

The run was stopped at step 125 after drink reached zero and dwarf `#249` died
with a thirst timer of 75,000. Deterministic G7 is FAIL: trace duration
185,487/403,200, food flow 3/31, drink flow 0/60, population 10/15, functional
rooms 2/3, installed beds 1/4, rubric 65.97 with
`no_broader_fort_layout`, and score-v5 115.39/150. The death cause enum was
unavailable, so neglect remains UNKNOWN. The stop-after-advance final row also
left summary duration at 184,483 and one fewer screen/proof record, correctly
failing evidence closed.

The trace isolated two observation gaps rather than missing gameplay powers.
The 3x3 workshop preflight returned only its first invalid tile, so repeated
Still attempts learned one cell at a time. Later, completed walls sealed the
FarmPlot while its door remained inside the room instead of in the boundary.
The agent saw an unassigned PlantSeeds job and idle farmers but not the native
walk-group fact. A stopped-save read found 10 citizens checked, zero connected
to `(95,95,160)`, and zero unknown.

PR #97 now returns every invalid tile in the submitted workshop footprint while
remaining atomic and hidden-safe. PR #98 adds cached possible job-target
walk-group connectivity to sampled jobs. It reports geometry only and does not
select a repair, labor, target, or strategy. Both passed CI and independent
review and deployed at exact SHA `e0d51ef1d7a37c3f09606340a1d3bc0a1e914a23`.
A deployed invalid-Still probe returned five factual failures with unchanged
building count, pause state, year, and tick.

### 2.33 Attempt 24 exposed a fail-open tick-controller return

Attempt 24, run `0d3dad764c9640af8d8bd6f67be1dcf1`
([replay](https://fortgym.live/r/64584CWkX3eWm6TOwJST1_t4mgpGB-6Q)),
started from fresh `seed_region3_fresh` on exact deployed SHA
`e0d51ef1d7a37c3f09606340a1d3bc0a1e914a23`. The step-0 observation was a
paused native map at year 30, tick 16,801. The policy submitted an invalid
surface DIG, which designated no tiles and changed no map state, then requested
1,000 ticks.

The first tick read after the runner enabled DFHack `nopause` exceeded its
bound. The old function returned before entering its cleanup `finally`, recorded
zero ticks, and left `nopause` active. Terminal cleanup then treated successful
pause command submission as verification even though the game remained
unpaused. A direct read found tick 54,248 and `pause_state=false`; another normal
pause request remained ineffective at tick 57,460. Explicitly disabling
`nopause` and setting pause contained the game at tick 58,122 with
`pause_state=true`. This is an infrastructure abort with no policy or G7 signal.

The corrective slice puts every tick-read exit after `nopause` under one
fail-closed cleanup path. Cleanup must both disable `nopause` and independently
read `pause_state=true`; unknown or false state makes the advance and terminal
cleanup fail. The serialized runner performs the same attestation before the
first agent observation, and the administrative `/step` exception path uses the
same bounded repause. Regression coverage reproduces the post-`nopause` read
failure, false pause attestation, disable failure, and endpoint exception path.
PR #99 deployed that repair. A live smoke then exposed truthful undercounting:
the first stable pause tick could advance beyond the last in-loop read. PR #100
made the verified post-pause read authoritative. Both deployed at exact SHA
`005fdccd79993b1dd3a0451eae43a61fdc1a9dd3`; a final live probe advanced from
58,140 to the reported and independently stable tick 58,161, with two subsequent
`pause_state=true` reads.

### 2.34 Attempt 25 made real early goods, then died on duplicated prose

Attempt 25, run `9162ea4247c04fd4a64f3b0dcf502cf9`
([replay](https://fortgym.live/r/dBYI_DISuN6iXv6WjFzTs-7Gq7-ahf00)),
ran exact deployed SHA `005fdccd79993b1dd3a0451eae43a61fdc1a9dd3` on fresh
`seed_region3_fresh` with OpenRouter `z-ai/glm-5v-turbo`, vision enabled,
memory disabled, score-v5, a 450-step budget, and at most 2,000 ticks per turn.
It retained 72 gameplay rows, all with screen text, gameplay proof, and governed
provenance. Eighty-nine model calls used 1,678,144 prompt and 63,712 completion
tokens. The verified pause lifecycle held for every gameplay step.

The policy completed two channel accesses, eight action-owned excavation
completions, a usable Carpenter workshop, and five beds in stock. It gathered
two surface plants, but neither created a usable drink loop. No furniture was
installed, no room or farm completed, and no Still completed. Final population
was seven, food 44, drink 33, and wood four; no dwarf died.

Deterministic gate-v2 is FAIL. Duration was 86,062/403,200 ticks, food flow was
0 produced/13 consumed, drink flow 0/27, population 7/15, functional rooms 0/3,
installed beds 0/3, rubric 54.1 retained `no_broader_fort_layout`, and score-v5
was 82.1/150. Evidence and zero-neglect-death predicates passed.

The terminal happened before step 72 gameplay. The model proposed the same
objective in `objective` and `plan_review.objective`, but both copies were longer
than the 160-character schema cap. Two correction calls repeated that sole
error, so the governed contract failed closed. This is an infrastructure-aborted
G7 FAIL after real early gameplay, not evidence that the long policy exhausted
its 450 turns.

The trace exposed a second factual boundary error. The policy spent roughly 20
Still-footprint attempts around native shrubs, dead shrubs, boulders, and the
wagon. Stopped-save reads showed three repeatedly designated tiles were
`ShrubDead`; no gather job was created despite substantial real time. The old
gather hook classified every SHRUB-shaped tile as eligible and could return
`ok=true` with no target. The corrective candidate rejects dead shrubs as
`dead_shrub_ungatherable`, rejects all-empty gather rectangles as
`no_gatherable_shrubs`, and teaches the model that only a live shrub can be
cleared by gather. Separately, schema-boundary normalization shortens only when
the two duplicated objective strings are identical; conflicting objectives
still enter bounded correction and fail closed. Neither change chooses a plan,
action, coordinate, or gameplay target.

PR #101 passed 829 local tests, GitHub CI, and an independent focused review,
then merged and deployed at exact SHA
`a8f696ac17a4a8205306b327a284f78ea74ae9bf`. Production targeted tests and API
health passed. On the paused Attempt 25 save, `(87,94,161)` read as
`ShrubDead`; the deployed gather returned `ok=false`,
`no_gatherable_shrubs`, and `dead_shrub_ungatherable`. Tick remained 102,863,
pause remained true, and the full tile/designation snapshot was unchanged.
Fresh-seed Attempt 26 then launched on that exact SHA as run
`57095606c09d454c9f3fae8bb37fb0dd`
([replay](https://fortgym.live/r/ke3Mv0MUTO7fSpuJmLJpUVH-Gn6d_IqD)).

### 2.35 Attempt 26 reached a real farm, but only after 51 lower-dig turns

Attempt 26 retained 150 governed gameplay rows on deployed SHA
`a8f696ac17a4a8205306b327a284f78ea74ae9bf`; every row has screen text,
gameplay proof, and governed provenance. The OpenRouter `z-ai/glm-5v-turbo`
policy used 173 calls, 3,224,654 prompt tokens, and 115,523 completion tokens.

The model completed a Carpenter workshop, made and installed a bed, completed
a Still, produced 25 drink, and built a connected channel to a lower level. It
then spent steps 77 through 127 extending that lower excavation. After two
rejected dig targets it revised the plan, built a 3x3 subterranean FarmPlot at
step 128, selected plump helmets for every season, and let the native planting
jobs complete. The crop did not mature before the operator stopped the run.
Final population was nine, all dwarves survived, and the fort had 29
constructions, one installed bed, one door, and two installed tables.

Deterministic gate-v2 is FAIL: duration 206,901/403,200 ticks, food flow 0
produced/38 consumed, drink flow 25/71, final food/drink 18/15, population 9/15,
installed beds 1/3, rubric 69.91 with `no_broader_fort_layout`, and score-v5
117.07/150. Evidence and zero-neglect-death predicates pass. This is a real
policy-diagnostic failure, not a simulated score result.

The stopped save invalidated the reported room. Deployed `fort_metrics.lua`
returned one bedroom whose bounds and only interior tile were
`(92,99,161)..(92,99,161)`, containing one bed and one boundary door. The
candidate minimum-interior rule returned zero rooms on the identical save.
Gate-v3 also rejects the old final row's missing fort-observation attestation,
so its room branch is UNKNOWN rather than accepting the stale summary value.
On the same paused save, candidate chop over the real underground farm returned
`no_choppable_trees` with zero writes. The nine designation cells, tick 223,702,
and pause state were identical before and after.

The run also exposed pure wall-time loss in the control loop. Four liaison
viewscreens paused simulation after 277, 15, 20, and 74 ticks, but each WAIT
blocked for the full 300-second timeout before the model could inspect and
legally handle the dialog. A strategy-neutral candidate makes governed tick
polling interruptible on an observed paused viewscreen transition. It preserves
the actual tick delta and fail-closed repause evidence and leaves every UI
choice to the next model turn.

### 2.36 Attempt 27 made a larger real fort, but contaminated citizenship evidence stopped the run

Attempt 27, run `4eded56b1d224fbab47d336df7c521f6`
([replay](https://fortgym.live/r/eMtR2Bp3-kmp2JQ5MI2lLT_ANdyuR9qV)), is an
**OPERATOR-STOPPED POLICY-DIAGNOSTIC FAIL**. It retained 225 real governed
gameplay rows with screen text and governed provenance. The only model was
OpenRouter `z-ai/glm-5v-turbo`; 300 calls used 6,306,577 prompt and 218,336
completion tokens (6,524,913 total). No Anthropic model was used.

The run made meaningful legal DF gameplay progress: a connected channel/ramp and
lower excavation, a Carpenter workshop and Still, six installed beds, three
doors, three tables, two chairs, and nine constructions. Population reached 17
and the fort had three functional rooms. Three farm plots were placed. Plot #28
at `(93,98,160)` was genuinely subterranean, set to plump helmets, received a
real PlantSeeds job, and completed planting. The modal controller also held its
contract: at step 174 it requested 1,200 ticks, stopped after 712 on
`dwarfmodest -> textviewerst`, and repaused; it rejected the wrong
`finish_topic_meeting`, corrected it with a zero-tick cancel, later handled
`topicmeetingst` with zero-tick `finish_topic_meeting`, and handled liaison
request/agreement/farewell screens with early stop and repause without safety
errors.

The operator stopped at step 225 after preserving artifacts because the active
ledger falsely admitted same-civ merchants as fortress citizens. That made death
and consumption evidence irreparably contaminated. Deterministic G7-v3 is FAIL:
duration 246,752/403,200 ticks; evidence passes with 225 gameplay rows and
governed provenance/screen text; food 6 produced/44 consumed/final 9 and drink
75 produced/113 consumed/final 29 fail sustainability; rooms 3, beds 6, and
population 17 pass; neglect deaths are UNKNOWN, with no confirmed
fortress-citizen death; rubric 67.39 retains `no_broader_fort_layout`; and scalar
142.47 is below 150. The terminal reason was `stop_requested_after_agent_decide`.
Neither the scalar nor the real construction changes make this a G7 success.

The policy errors are distinct from the evidence defect. After native planting
completed, it repeatedly treated `plant_seed_jobs=0` as a path blockage. After
reaching `functional_rooms=3/3`, it continued wall-building and regressed; the
`same_objective_stalled_2` signal allowed continuation instead of a real pivot.
LABOR also targeted a child because citizenship and work eligibility were
conflated. PR #109 merged raw farm contained-item evidence, PR #110 merged
governed objective completion and hard stall transitions, and PR #111 merged
own-group G7 citizen/consumption/death evidence with fail-closed predicate
errors. The next experiment is not yet started: deploy that reviewed contract
with the labor-eligibility correction, then launch fresh Attempt 28.

## 3. Limitations

- **A single passing embark family.** Every pass (G0–G4) is on
  `seed_region1_fresh`; G6 is the first move off it, and it stands at zero
  passes in seven region3 attempts. "Plays Dwarf Fortress" is not yet
  demonstrated — "solved one map" is.
- **Small n.** The reliability claim rests on a five-run lineage; the endurance
  result on one probe; the G6 verdict on seven runs; G7 on 25 failed attempts
  plus one invalidated attempt.
  These are findings, not distributions.
- **One policy family for most results.** GLM-5V-turbo produced the G4 passes
  and most of the G6 campaign; GPT-5.5 served the earlier G2/G3 passes.
  Cross-model generality is thin — two GPT-5.5-vision escalation runs are the
  only cross-family data points on the unseen map.
- **G6 is unpassed; G7 attempts 1 through 18 and 20 through 26 failed, and attempt 19
  is invalid.**
  Attempts 2 through 9 and
  12 through 16 were infrastructure aborts, although attempts 14 through 16
  contain policy-bearing gameplay rows; attempts 10, 11, 17, and 18 are policy
  diagnostics. Attempts 17 and 18 were manually stopped after their loops were
  decisive. Attempt 19 was stopped and invalidated after an operator's
  candidate-hook probe mutated its live save. Attempt 20 was deliberately
  stopped at the 24-row diagnostic boundary just after it completed a real
  Carpenter workshop; it is a valid short G7 FAIL, not a long-horizon policy
  verdict. Attempt 21 was stopped after 296 rows when its late farm recovery
  could no longer reverse 11 deaths or cumulative food/drink deficits; it is a
  long policy diagnostic with an incomplete final stop row. Attempt 22 reached
  the milestones much earlier and kept all 15 dwarves alive, but failed resource
  flow, structure, duration, rubric, and scalar requirements before a missing
  Stores-screen exit caused a zero-tick infrastructure abort. Attempt 23 built
  two real rooms and a Still, but sealed its farm and reached drink zero before
  the production loop started. Attempt 24 aborted at step 0 when a tick-read
  timeout bypassed repause; it produced no policy evidence. Score-v5 is
  deployed and active. Attempt 25 made a real Carpenter workshop and five beds,
  but repeated dead-shrub footprint attempts and then terminated before step 72
  gameplay on identical overlong objective fields. It is an infrastructure-aborted
  short G7 FAIL, not a long-horizon verdict. Attempt 26 built a connected lower
  farm and completed planting with all dwarves alive, but reached that phase
  after 51 lower-dig turns and stopped at half-year duration before any harvest;
  its sole reported room was a one-tile false positive. Attempt 27 made a larger
  fort with a completed subterranean planting job, but its active-ledger
  citizenship bug contaminated consumption and death evidence, so it remains an
  operator-stopped policy-diagnostic FAIL. The
  chair-factory calibration gap (§2.4) remains part of score-v3's historical
  record.
  Attempt 1 demonstrated why the scalar is telemetry rather than the verdict:
  score 209.44 passed its bar while the fort failed survival and structure.

## 4. What's next

- **Attempt 27 proved the direct-action loop can grow a real fort through a
  completed subterranean planting job, workshops, rooms, furniture, and
  migration without operator gameplay.** The next boundary is truthful
  own-group citizenship, consumption, and death evidence, plus policy fixes for
  post-planting diagnosis, hard stalls, and labor eligibility. Deploy the
  reviewed contract with that labor correction, then launch fresh Attempt 28;
  Attempt 28 does not exist yet.
- **Attempt 23 proved the corrected loop can independently transition from
  excavation to farming, workshops, furniture, and two functional rooms.** Its
  decisive blockers were incomplete native feedback for rejected 3x3
  footprints and missing job-target connectivity after the farm was sealed.
  Both factual changes are deployed without strategy or target selection.
  Attempt 24 then exposed the fail-open tick-controller return now repaired by
  PRs #99 and #100.
- **G6 remains open**: the best unseen-map run reached 4/5 and missed only its
  second functional room. G7 now tests whether stable spatial observation lets
  the corrected direct-action loop sustain production and structure for a year.
- **G8 — depth**: a multi-z fortress (stairs, underground rooms), the next
  spatial-reasoning escalation after the hollow ring is actually demonstrated.
- **The open-source flywheel**: a standing public leaderboard where any model
  attempts the ladder, every run replayable at `fortgym.live/r/<token>`.
