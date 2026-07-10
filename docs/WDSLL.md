# WDSLL — What Does Success Look Like

## Success statement (the one metric)

**An LLM policy, issuing only legal governed actions, takes the fixed embark
from fresh seed to a producing fortress — completed rooms, a working workshop,
finished goods — on public, replayable evidence, with zero rubric blockers.**

Everything below exists to make that statement falsifiable. A gate passes only
on the recorded facts in `summary.json` and `trace.jsonl` of public runs at
fortgym.live — never on narrative, screenshots of derived views, or score
alone.

## Non-negotiables (apply to every gate)

- Actions must be provenance-tagged `dfhack_governed`. One `dfhack_assisted`
  action disqualifies the run (the harness already zeroes it — the gate just
  inherits that).
- Every step must carry a recorded CopyScreen `screen_text` frame and a
  per-step `gameplay_proof` object. A claim without its evidence row does not
  count.
- `summary.json.rubric.blockers` must be empty for a gate pass unless the gate
  says otherwise. The rubric is the anti-goodhart backstop: `repetitive_policy`
  and `illegal_or_assisted_progress_seen` fail a run no matter the score.
- No scripted hints, no new gameplay heuristics in the agent, no additions to
  the score matrix to make a gate pass. Widening the *legal action surface* or
  the *observation's factual content* is allowed; steering the policy is not.
- Scores are comparable only on the same seed (`seed_region1_fresh`), same
  `ticks_per_step`, and stated `max_steps`.

## Gate ladder

### G0 — Legal substrate works (PASSED 2026-07-01)
Scripted governed agent places a real workshop and queues real orders through
bounded DFHack commands; simulation resolves them; evidence recorded.
Evidence: run `aaa073004ada410b94121c2b3dc8061f`, score 121.5, 4/4 screen
frames, real material item + created job ids.

### G1 — LLM on the surface (PASSED 2026-07-01, policy quality failed honestly)
`dfhack-governed-llm` completes a public run with all actions governed and all
evidence recorded. Evidence: run `8a9b07cc610f4b61bdd579e688db58dd`
(https://fortgym.live/r/TH9CxITUnWqeVtEwcJvxnmUlyW0Fya7y), score 53.5, rubric
47.25 **with blockers** `repetitive_policy`, `no_real_layout_progress`,
`no_production_surface`. G1 proves plumbing, not play.

### G2 — Parity with the scripted ceiling (PASSED 2026-07-02, 5/5)
Evidence: runs `8a909aa1`, `35fbdee6`, `56c5ac38`, `e043c0fc`, `821a03e4` at
commit `13db60d7d` — scores 195.5–204.7 vs the 121.5 ceiling, rubric
84.8–85.7 vs the ceiling run's 74.1, 28–30/30 proof-backed steps and 30/30
recorded screen frames per run, blockers within the allowed set (run
`e043c0fc`: zero blockers). Policy: build workshop → order → detect wood
starvation → chop trunks → sustain production; dwarves completed workshop
tasks consuming felled logs. Passed under the 2026-07-02 measurement
corrections (see log below), which were operator-approved before the series
ran; the agent itself was unchanged from the failed third series.

On ≥3 of 5 public runs (same seed, ≤30 steps, ≤2000 ticks/step):
- ≥3 steps with `gameplay_proof.ok = true`, at least one of them showing a
  real tile change (`changed_tile_count > 0`) — the mechanism (dig, chop,
  build, or dwarf labor resolving during a wait) is not prescribed,
- a BUILT carpenter workshop exists (construction stage complete — from the
  crew/workshops evidence or `carpenter_workshops_usable ≥ 1`),
- ≥1 order created (`created_job_ids` in a governed step),
- `total_score ≥ 121.5` (the scripted reference on this seed),
- no rubric blockers beyond the ceiling run's own set (currently exactly
  `{no_real_layout_progress}`) — `repetitive_policy`, `no_production_surface`,
  and `illegal_or_assisted_progress_seen` must be absent.

**Kill/iterate rule**: if 0 of 5 pass after two iterations of
observation-surface or prompt fixes (no heuristics, no scripted plans), the
"GLM 5.2 + this loop solves gameplay" hypothesis fails → switch model via
`OPENROUTER_MODEL` and rerun, or accept the finding and stop claiming an LLM
plays. Do not rescue the gate by softening it.

### G3 — Production proof (finished goods, not queues) (PASSED 2026-07-02)
Evidence: run `e25f90eedb7d4a3cb7a36ce863d3ed5e` at commit `4c72e8da1`
(https://fortgym.live/r/LEI7BPnbzyDNMtNHR5D3ei-NuzThm3js) — bed count 0 → 19
within one run (seed reset gives a clean zero baseline), all from the run's
own accepted orders; workshop-consumption state deltas on 2 steps; score
197.48, rubric 86.5, zero blockers, 30/30 recorded frames. Passed on the
item-delta branch of the OR (created_wealth = 0, engine-stale as documented).

A public run where a queued order **completes**:
- ≥1 step whose `gameplay_proof` state deltas show workshop consumption
  (`carpenter_workshop_completed_tasks` / `wood_consumed_by_workshop`), and
- at least one of (operator-selected OR-form, 2026-07-02): (a)
  `created_wealth > 0`, or (b) the in-play item count of a good type the run
  actually ordered (`created_job_ids`) increases from the run's first
  observation to its last (`crew.goods` deltas).

Queued-but-never-built (the pre-chop failure mode) explicitly does not pass.

### G4 — Horizon (a fortress, not a demo)
One public run, ≥50,000 ticks:
- population ≥ starting 7 with zero casualty spike,
- ≥2 workshop orders completed (finished-goods deltas, per G3 evidence),
- **≥2 enclosed functional rooms detected plan-agnostically**
  (`fort_functional_rooms ≥ 2` — e.g. a bedroom and a production room, each
  fully bounded by walls, buildings, or doors; measured by `fort_metrics.lua`
  from map state, no plan rectangles),
- rubric ≥ 70 with no `no_fort_structure`, `repetitive_policy`,
  `no_production_surface`, or legality blockers,
- score strictly greater than any ≤10-step run on the same seed (long play
  must beat short play, or time isn't being used).

Note: this bar is deliberately higher than anything achieved to date — the
record 60-step probe (236.68) fails it with zero enclosed rooms. Passing G4
requires the agent to actually build shelter with the construction surface.

First score-v2 attempt (2026-07-03, run `08135b67`, GLM 5.2 pinned,
memory-off, 100 steps, honest-incentive prompt): FAIL — 36 constructions,
zero enclosures, score 123.54 (v2 scale), rubric 67.05. Two notes: the
truthful prompt shifted effort visibly toward walls and away from production
(6 goods vs 30+ under v1 incentives), and v2's utility deflation lowers the
rubric's production_economy inputs — the rubric ≥70 threshold was calibrated
on v1-scale inputs and should be reviewed (operator decision) before it is
treated as the binding criterion; this attempt failed the rooms criterion
regardless. Closed-loop wall geometry remains the frontier across every
model and configuration tested.

Minimap attempt (2026-07-03, run `96d5e024`, GLM 5.2, memory-off, 100
steps, commit `cba50525`): FAIL — the observation now renders an ASCII
minimap of the fort with coordinate rulers and the explicit hollow-ring
rule, and the agent still built a solid 3×4 wall block with the interior
filled (30 constructions, zero enclosures, 29 wall actions including
repeated retries on its own already-walled tiles). Combined with the nine
prior attempts across three models, two score versions, and both memory
configs, the evidence supports a strong claim: **maintaining a
hollow-ring spatial invariant during incremental construction is beyond
the reliable capability of the text-only models tested, even with
rendered 2D views** — GPT-5.5 achieved it exactly once (attempt #1). G4
stands as an honest open frontier; the remaining untested cheap lever is
the minimap on GPT-5.5, the only model with a demonstrated ring.

### G5 — Memory pays rent (remembers and improves) (ATTEMPTED 2026-07-03: FAILED, inverted result)
Evidence: 5-run memory-ON series (`3f3cdfdf`…`fca3f6c2`) vs 5-run memory-OFF
control (`69d45ae8`…`1644cce7`), identical config, fresh slate each arm.
Memory-ON rubric declined 90.4 → 82.6 (required: non-decreasing, +15);
the control outperformed it — 3/5 fresh-slate runs built a functional room
while memory-ON runs degenerated into unfocused wall-spam (66–94
constructions, zero enclosures). Verdict: memory as currently implemented
(failure tallies + persistent plan) is actively counterproductive for this
policy. The gate stands unmodified — it did its job by isolating the effect;
passing it requires a redesigned memory (e.g. causal lessons and successes,
not failure counts), not a softer criterion.
With persistent memory ON (`governed_llm_memory.json`) and the same seed:
a 5-run series, identical config and prompts, where run-over-run rubric score
is non-decreasing and the 5th run beats the 1st by ≥15 rubric points or
reaches G2 when run 1 did not. Control: the same 5-run series with memory OFF
shows no such trend. This isolates memory as the cause.

### G6 — Generalization (no hardcoded plan)
Prerequisite RESOLVED 2026-07-02: `fort_metrics.lua` provides plan-agnostic
structure detection (enclosed spaces, functional rooms, constructions) that
works on any seed; G4's criteria run entirely on it. Remaining plan-scoped
surfaces (the `work_metrics.lua` target rects that anchor governed target
discovery and some score components) still assume the default embark — those
must be generalized or made optional before G6. Then: a fresh seed/embark the
agent has never seen, reaching G4-level structure. This is the gate that
separates "solved one map" from "plays Dwarf Fortress."

### G7 — The fort lives: a self-sufficient year (RATIFIED 2026-07-09)
Status: RATIFIED at the 2026-07-09 operator window; attempt 1 FAILED, while
attempts 2 through 6 ended in infrastructure-aborted FAILs with no full-year
policy verdict. All six are recorded below. The criteria remain unchanged. All three
activation preconditions hold: (a) score-v3 ratified and landed; (b) G6 attempted
(7 runs, 2 models — frontier documented in the escalation log); (c) the
survival primitives exist, adversarially reviewed and live-validated:
gather (DIG kind), FarmPlot (BUILD kind), Still + brew ORDER
(CustomReaction fix #63), FARM crop selection (#64, agent-controlled per
operator directive), and LABOR assignment (#65). Kitchen/meal orders were
deferred (optional in the proposal; not required for the drink/food loop).
Pre-declared scalar bar for attempt 1 (set before launch, per the gate
protocol): score-v3 >= 150 — the best corrected 100k-tick region3 run
scored 152.39, and a fort that lives a full year must at least match the
best quarter-year camp — and rubric >= 70 with zero blockers (the
standing clean bar). Attempt 1 ran as GLM-5V, max_steps 450,
ticks_per_step 1000, seed_region3_fresh (the unseen-map frontier, water
hazard and all); its public failure record is below.

Rationale: every gate to date ran inside DF's benign opening — starting
stocks, no threats, nothing that punishes idleness. The endurance probe
showed the wall: food drained 45->31 with nothing replenishing it; every
fort ever built here eventually dies of thirst with no enemy required.
G7 is the first gate where the game itself pushes back, and it is
monoculture-proof by construction: survival is a portfolio problem.

Criteria (one run, plan-agnostic, score-v3, memory per standing config):
- **Duration**: >= 403,200 elapsed ticks (one full in-game year).
- **The loop closes**: food AND drink produced in-run (from the run's own
  farms/brewing, evidenced by production deltas — same evidence class as
  G3's beds) each exceed the run's consumption of that resource; embark
  stock cannot carry the year.
- **Nobody dies of neglect** (kill rule): zero deaths from starvation,
  dehydration, or tantrum spiral. One such death fails the run outright —
  no partial credit.
- **A settlement, not a camp**: population >= 15 at year end (migrant
  waves survived), >= 3 functional rooms, installed beds >= population/3.
- **No degeneracy**: rubric clean of repetitive_policy /
  no_production_surface / no_fort_structure / legality blockers; scalar
  bar to be set from the score-v3 calibration table before the first
  attempt (pre-declared, like every gate).

Evidence: unchanged — recorded frames, per-step gameplay_proof, provenance
gating, public replay. Beyond G7 the ladder continues to G8 — depth
(multi-z fortress: stairs, underground rooms — the next spatial-reasoning
escalation past the hollow ring), and the open-source flywheel: a standing
public leaderboard where any model attempts the ladder.

## Measurement mechanics (all already exist unless noted)

| Fact | Where it lives |
|---|---|
| Action legality | `execute.provenance` per trace record |
| Screen evidence | `screen_text` per trace record (replay "DF Screen") |
| Per-step real change | `gameplay_proof` (keystroke + governed) — tile diffs, helper evidence, state deltas |
| Progress facts | `summary.json` fields (`completion_progress`, `carpenter_workshops_usable`, `manager_orders_count`, ...) |
| Anti-goodhart | `summary.json.rubric` blockers |
| Public verifiability | run URL `https://fortgym.live/r/{token}` + `/export/trace` |

Gaps to close as gates need them: order-completion milestone facts for G3
(milestones.py currently only has POP_10/DRINK_50/HOSTILES), plan-agnostic
metrics for G6.

## Spec corrections log

Corrections fix measurement against verified reality; they never soften a
gate. Each entry states what changed and the evidence that forced it.

- **2026-07-01 — G2 criteria corrected after live-state diagnosis.** Original
  G2 required `completion_progress > 0` and "rubric blockers empty". Read-only
  inspection of the live save showed (a) the plan rects sit on **surface
  terrain** — mostly open floor and shrub tiles, ~3 diggable walls — so the
  hardcoded room-completion metric cannot move there, and (b) the scripted
  ceiling run itself scores `completion_progress = 0` and carries the
  `no_real_layout_progress` blocker. A parity gate the reference run fails as
  written is a measurement bug. Replaced with: real DIG-driven tile change in
  `gameplay_proof`, and "no blockers beyond the ceiling run's own set". The
  same diagnosis found the `carpenter_workshops_usable` metric is rect-scoped
  and missed a fully built workshop at (98,96,177) — the workshop criterion
  now accepts global built-workshop evidence.

- **2026-07-02 — G2 measurement corrected (operator-approved) after the
  third series.** Final series scored 204.7–206.7 vs the 121.5 ceiling with
  30/30 proof-backed steps per run, yet failed 0/5 on two criteria. (a) The
  `repetitive_policy` blocker fired on 22/30 WAIT steps even though every one
  showed real state change (wood accumulating, workshop tasks completing) —
  the rubric's own critique text defines the failure as repetition "without
  state change", but the implementation never checked state change. The
  rubric now counts only no-progress steps toward the repetition ratio
  (`_step_progress_flags` in `eval/rubric.py`); identical no-op spam still
  fires the blocker (locked by test). (b) The G2 criterion "a DIG whose tile
  diff shows wall→floor change" over-prescribed the mechanism on a surface
  embark where the fort thrives without mining; corrected to "at least one
  proof-backed step with a real tile change of any governed kind". Both
  changes were approved by the operator before any re-run; the prior 0/5
  results stand as recorded.

- **2026-07-02 — G3 wealth clause made an OR with item-count evidence
  (operator-selected).** DF's `ui.tasks.wealth` counters never recalculate on
  this headless build: live inspection showed `furniture = 0` and
  `total = 9` while 19 agent-produced beds existed in the world. The operator
  chose the OR-form (wealth or item deltas) over replacing the clause,
  keeping the wealth path alive if an engine-side recalculation trigger is
  ever found. Item counts come from the read-only `crew.goods` observability
  added at commit `4c72e8da1`.

- **2026-07-02 — G4 rebuilt on plan-agnostic structure (operator-directed
  Option B: "hardcoded plans aren't the way").** The 60-step probe
  (`d09ae07d`, score 236.68) showed G4-as-written failed only on criteria
  bound to the hardcoded `two_room_workshop` plan: "zero blockers"
  (`no_real_layout_progress` fires structurally on this surface seed, ceiling
  run included) and "≥2 completed spaces" (the plan metric cannot complete on
  shrub-contaminated surface rects). Rather than correct within the plan-
  scoped metrics, the operator chose to replace them: `fort_metrics.lua` now
  detects enclosed spaces and functional rooms by flood-fill from player
  buildings on any seed (validated live: open-plain fort honestly reads 0;
  a legally wall-constructed room reads 1 production room). The rubric's
  shelter dimension and blocker (`no_fort_structure`, replacing
  `no_real_layout_progress`) run on the new facts; scalar score components
  are unchanged this cycle. G4's bar is RAISED, not lowered — no run to date
  passes it. A construction action (BUILD kind=Wall/Floor) was added so the
  requirement is achievable through legal play.

- **2026-07-02 — fort_metrics detector fix after G4 attempt #1 (run
  `b8e07f4a`, FAIL 5/6).** The agent autonomously built a wall ring (steps
  20–23), and furnished the enclosed room so completely (door, two beds, a
  table in a 2×2 interior) that no free floor remained — and the flood-fill
  defined rooms by free floor, so the room vanished from detection at step
  32. Detector corrected: bed/table/chair tiles count as room interior and
  valid flood seeds; walls, doors, and workshops still seal. Validated
  against the live save: the agent's furnished bedroom reads as 1 functional
  room. Gate criteria unchanged — the attempt still fails honestly at 1
  functional room vs the required 2.

- **2026-07-03 — MODEL ATTRIBUTION CORRECTED for every governed run to
  date.** During the G4 model-swap attempt, the per-step usage events
  revealed the serving model was `openai/gpt-5.5`, not the repo-default
  `z-ai/glm-5.2`: `/etc/fort-gym.env` on the deployment carries an
  `OPENROUTER_MODEL` override, and systemd `EnvironmentFile` also overrides
  drop-ins (which silently defeated the DeepSeek swap). Audit confirmed
  gpt-5.5 served the G2 pass series, the G3 pass, all G4 attempts, and both
  G5 arms. All recorded evidence (scores, rooms, traces, frames) is
  unaffected; only the model credited changes — every "GLM 5.2" behavioral
  claim in earlier entries should read "GPT-5.5". Fix: pinned registry
  variants (`dfhack-governed-llm-glm52` / `-deepseek-v4` / `-gpt55`) whose
  names declare the model and are immune to env drift; future gate attempts
  must use pinned names, and model attribution must be verified from trace
  usage events, never inferred from config.

- **2026-07-03 — KNOWN SCORE DEFECT (unfixed, operator decision pending):
  utility_progress is exploitable by order spam.** The pinned three-model
  comparison (100 steps, memory-off, identical surface) produced three
  distinct strategies: GPT-5.5 (`21bd75dd`, 349.77) satisficed — one room,
  then production hoarding; GLM 5.2 (`4d380449`, 354.68) built the most
  walls (56) but never closed an enclosure; DeepSeek V4 Pro (`e57ff8e2`,
  686.81) reward-hacked — 91 consecutive bed orders pumped the open-ended
  `utility_progress` queue-depth metric to 301 (utility_score 602) while
  producing almost nothing and building nothing. The G4 gate correctly
  failed all three (rooms criterion held), and the rubric partially resisted
  (77.4) — but the scalar score and public leaderboard now rank a hollow run
  first, and the progress-aware repetition blocker has a blind spot: steps
  whose only "progress" is the pumped metric count as progress-backed and
  escape the repetition tally. Fixing either (capping/queue-completion-
  gating utility, or hardening the repetition check) is a score-matrix
  change and per the non-negotiables requires operator approval before any
  gate re-run under changed scoring.

- **2026-07-03 — SCORE-V2 BOUNDARY (operator-approved).** In response to the
  order-spam exploit: `utility_progress` now pays only completed production
  (in-play item-count deltas of orderable goods) plus workshops that became
  usable; order/queue deltas remain recorded but earn nothing. The rubric's
  repetition exemption no longer accepts queue-only proofs (created_job_ids
  without tile changes, state deltas, designations, or new buildings) as
  world change — the 10×-identical-order trace now trips `repetitive_policy`
  (locked by test). `summary.json` carries `score_version: 2`; every run
  before commit `967d9e688` is score-v1 and scores are not comparable
  across the boundary. Also operator-approved: the system prompt now
  truthfully discloses the three evaluation surfaces (scalar score, rubric
  including enclosed-room shelter, long-horizon room goals) — replacing a
  factually wrong claim that the score paid for "dug rooms".

- **2026-07-04 — VISION EXPERIMENT (operator-directed): the hollow-ring
  failure is primarily a modality problem.** The fort minimap is now also
  rendered as a PNG and attached for vision models (PR #27/#28/#29/#31–#33;
  three provider quirks — forced tool_choice, mandatory reasoning, token
  starvation, prose-JSON answers — handled with trace-attributed
  degradations; three Kimi runs voided as call failures, not results).
  Results (100 steps, memory-off, score-v2): GLM-5V-turbo (`0cffcd6d`,
  131.19) built **1 enclosed functional room** — first ring in the GLM
  family after ~10 text attempts; Kimi K2.7-code (`91928e29`, 69.01) also
  closed **1 ring** but never started its economy; MiniMax-M3 (`83ff5d61`,
  63.95, valid calls) managed neither — the control showing vision doesn't
  create capability. Two of three vision arms achieved what one text run in
  ~15 ever did. G4 still unpassed (nobody has economy + two rooms at once);
  the strongest untested candidate is GPT-5.5-vision — best text economy on
  record, now with eyes.

- **2026-07-04 — LEGACY PLAN DECOUPLED from the governed observation and
  action surface (operator-directed follow-through on Option B).** Forensics
  on the GLM-5V run (`0cffcd6d`) showed the model finished its room by step
  40, then spent 52 of its remaining 60 actions on single-tile BUILD:Floor
  with intents like "continuing workshop room floor completion (22/25
  done)" — chasing the retired `two_room_workshop` plan, whose progress
  counters ("Target room: floors=X/25", "Fortress plan:
  workshop_room_floors=X/25, completed_spaces=X/2", "Plan rects") the
  observation still displayed. Under score-v2 those tiles pay nothing and
  no gate asks for them: the observation was stating a false objective.
  Removed. Second leftover: CarpenterWorkshop/furniture placement was
  still hard-rejected outside the legacy plan rects (`outside_work_rect`),
  meaning a second enclosed room built outside them could never be
  furnished into a *functional* room — an invisible wall directly against
  the plan-agnostic G4 rooms criterion. Placement legality now uses the
  same rule Wall/Floor constructions already had: within 24 Chebyshev
  tiles of any existing player building or citizen (`too_far_from_fort`,
  enforced in the hooks). Gates, scoring, and rubric are untouched; this
  changes only what the agent is told and what the bounded primitives
  legally reach. Prompt wording updated to match. An adversarial review of
  the diff caught one bug before it shipped: the workshop-site discovery
  radius (35) exceeded the new locality gate (24), so the observation could
  have called a site legal that the hook would reject — radius capped at 24
  and the observation line now says "candidate", claiming only what is
  verified (open 3x3 floor). Known remaining plan-shaped surfaces, left
  deliberately: `work_metrics.lua` still computes the legacy-rect fields
  (consumed by the scripted reference agent, which is a plan-walker by
  design, and by hint discovery — non-binding); and the rubric's
  `fortress_breadth`/`plan_coherence` dimensions still pay
  `complexity_progress`/`completed_spaces` from the legacy rects, which now
  under-credits plan-agnostic building — fixing that is a scoring-matrix
  change and awaits operator approval.

- **2026-07-05 — G4 vision series run 1 (post-decoupling): FAIL 3/6, and it
  exposed the next invisible fact.** Run `24042365` (GLM-5V pinned, 100
  steps, memory-off, commit `cc0a33ec1`, score-v2 112.87, rubric 68.74 with
  ZERO blockers, 100/100 screen frames,
  `fortgym.live/r/T37FoZzcriyNd6OHH-0CTo-1G6giqMt3`): ticks 100,404 PASS,
  population 7/7 PASS, produced goods (2 beds + 3 doors) PASS; rooms 0/2
  FAIL, rubric<70 FAIL, score<=121.5 FAIL. The plan-decoupling worked — no
  floor-spam, no plan-chasing — and the agent spent the whole run trying to
  close its perimeter, but 58 of 81 wall actions failed: 41 tiles
  `already_wall`, 18 `tile_occupied_by_building` — its OWN queued walls.
  Root cause: a queued wall is a Construction-type *building* until a dwarf
  builds it, and the minimap only drew `world.constructions` (built), so
  pending walls rendered as open floor. The agent re-placed walls it had
  already ordered and could not tell phantom gaps from real ones. Wood was
  never the constraint (80 logs throughout). Correction (operator-approved,
  PR #38): pending constructions render as `x` on the minimap (text and
  PNG), legends and prompt explain "already ordered — do not re-place,
  advance time", and the Fort structure line counts
  `queued_constructions`. Display only: an unbuilt wall never seals a room,
  so the enclosure flood-fill boundary is untouched (locked by test). Also
  merged in the window (PR #36): `POST /jobs` parallelism clamps to 1 for
  the dfhack backend — concurrent workers were racing the single live save.

- **2026-07-05 — G4 vision series run 2: FAIL 5/6 — the best G4 result to
  date, and the queued-wall correction validated live.** Run `0a1be1c5`
  (GLM-5V pinned, 100 steps, memory-off, post-PR-#38,
  `fortgym.live/r/VCjkMbEg91DAbbk6pFZUTP94GvX3qClH`): score 125.24 > 121.5
  PASS, rubric 75.74 with zero blockers PASS, ticks 99,868 PASS, population
  7/7 PASS, produced goods 4 beds + 4 doors + 4 tables (richest GLM economy
  recorded) PASS — fails ONLY functional_rooms >= 2, with 1 enclosed
  functional room. The `x` glyph rendered from step 14; room #1 closed at
  step 16 (vs step 40 in the best prior run; run 1 never closed one), and
  post-room wall placements wasted on phantom gaps fell from 58 to 4 — the
  invisible-pending-walls hypothesis is confirmed by before/after behavior.
  The newly exposed frontier: the agent tried to furnish a second space for
  the rest of the run and 40 furniture installs failed with a bare
  `construct_failed`; it correctly diagnosed a suspended ConstructBuilding
  job wedged at (101,98,177) from the jobs observability but has no legal
  action to unsuspend it (a player would use the q-menu). Corrections
  queued: per-tile furniture placement reasons (PR #40, error-visibility
  only); an UNSUSPEND action is a legal-surface widening awaiting operator
  decision.

- **2026-07-05 — G4 vision series run 3: FAIL 4/6, and the suspended-job
  wedge is confirmed as the frontier.** Run `5a406c21` (GLM-5V pinned, 100
  steps, memory-off, post-PR-#40,
  `fortgym.live/r/ujtHjQhGMkmpRt_z1ooTRoVJS_Us18US`): score 112.45 (<=121.5
  FAIL), rubric 73.55 zero blockers PASS, ticks 100,351 PASS, population 7/7
  PASS, 4 beds + 3 doors PASS, 1 functional room (FAIL rooms>=2). The run
  ended with the SECOND room one wall from enclosure: steps 92-99 the agent
  waited on "the final queued wall at (100,97)", correctly named the
  suspended ConstructBuilding job blocking it, attempted the only legal
  workaround (re-placing — rejected, tile occupied), and ran out of steps.
  Suspended jobs were visible in 84/100 steps. Series verdict (3 runs,
  post-decoupling): 3/6, 5/6, 4/6 — two runs reached exactly one-room-short,
  and both were blocked by suspended construction jobs the agent can
  diagnose but not legally clear. PR #40's per-tile furniture reasons
  worked as intended (tile_not_open_floor/tile_occupied_by_building now
  visible). The prepared correction: UNSUSPEND, a bounded legal-gameplay
  primitive (q-menu equivalent: flips job.flags.suspend in a <=10x10 rect,
  dwarves still perform the work, provenance-gated in both governed and
  assisted sets, proof via unsuspended/suspended_found counts) — draft PR
  #41, a legal-action-surface widening held for operator merge.

- **2026-07-07 — SCORE-V3 RATIFIED AND IMPLEMENTED (operator-approved).**
  Per `docs/score_v3_proposal.md`: demand-capped production
  (`utility_progress` pays full rate per orderable-good type up to fort
  demand/population, 20% surplus beyond it — `produced_goods_delta` keeps
  paying the raw uncapped count for gameplay-proof consumers), plan-agnostic
  complexity (`complexity_progress` pays from flood-fill
  functional_rooms/enclosed_spaces/constructions when fort data is present,
  falling back to the exact legacy tile/space computation on old traces or
  the mock backend), and the rubric-half `fortress_breadth`/`plan_coherence`
  dims from `feat/rubric-plan-agnostic` (already CI-green on main) — all
  landed together as one version boundary, `score_version: 3`. Boundary
  discipline: every prior run stays v1/v2 and is not comparable across this
  boundary. Calibration table: `docs/score_v3_calibration.md` (also in the
  PR body for branch `feat/score-v3`) — validation gate passes exactly
  (|Δv2| = 0.0) on all 9 score_version>=2 runs checked, confirming the
  reconstruction is faithful, but the ratified acceptance check (chair
  factory + DeepSeek exploit must both score below both G4-passing runs
  under v3) **FAILS for the chair-factory run** (`ad70df06`: v3 = 508.06,
  both G4-passing runs score 180.33/207.58) because of `production_score`
  (paying uncapped for `production_workshops_delta`), a component neither
  v3 change touches — the same pattern independently shows up on a second
  sampled run (`7f268bcc`, production_score 420.0). This is reported, not
  silently tuned around: the PR is held for operator review of the
  calibration table before any merge or gate re-run under v3.

- **2026-07-07 — SCORE-V3 PRODUCTION AMENDMENT (operator-ratified, second
  calibration round).** In response to round 1's finding, the operator
  ratified amending production within the v3 boundary:
  `production_workshops_delta` now pays usable-workshop deltas ONLY —
  task-jobs queue depth drops out of the payment entirely (v2's
  "queueing is a menu action" doctrine, now applied to production) though
  it stays recorded for observability — and `production_score` is bounded
  at its 10-point weight (proven capacity, not an open-ended queue-depth
  meter). Round-2 calibration (`docs/score_v3_calibration.md`, commit
  `77adc8720`): validation gate again passes exactly (|Δv2| = 0.0 on all
  9 score_version-2 runs, now with true-v2 production formulas frozen
  inline in the rescorer); the queue-churn runs deflate correctly
  (`7f268bcc` 497.56 -> 104.54; `ad70df06` production_score 320 -> 10).
  Acceptance verdict: the DeepSeek arm passes (78.81, below both G4
  passes), but **the chair-factory arm still fails by 10.48 points**
  (`ad70df06` v3 = 198.06 vs the better G4 pass at 187.58) — no longer
  from any exploit vector, but from honest diversified production volume
  over its 2.5x step horizon (250 vs 100 steps; per-type demand caps
  across six good types leave ~78 full-rate units reachable) plus
  open-ended utility/wealth scaling. Per the ratified stop-and-report
  rule, no further coefficient was touched: whether to accept the gap
  (the comparability clause already forbids cross-horizon score
  comparisons for gates), cap utility volume, bound wealth, or normalize
  by steps is an operator decision. Every audited adjacent path
  (`utility_action_progress`, keystroke completed-task crediting) was
  found bounded or completion-gated — not the same bug — and left
  untouched. PR remains HELD; prior runs stay v1/v2, not comparable.

- **2026-07-05 — G4 PASSED. First pass in project history, 6/6 criteria.**
  Run `2f58fd37` (GLM-5V pinned `dfhack-governed-llm-glm5v`, 100 steps,
  memory-off, commit `893394920`, score-v2,
  `fortgym.live/r/qw8S-Wmf53DYLESSrgCWGvLPvY2n0IuH`): score 158.68 > 121.5;
  rubric 78.42 with zero blockers; 100,466 ticks; population 7/7 held; 10
  beds + 3 doors produced from the run's own orders; **2 enclosed spaces, 2
  functional rooms** (flood-fill detected, room 1 at step 30, room 2 at
  step 63), 75 constructions — record construction volume with record
  precision. Evidence: 100/100 recorded screen frames, 46/100 proof-backed
  steps, 100/100 steps `dfhack_governed` provenance. Attribution: 200/200
  tool_call events record `z-ai/glm-5v-turbo` as the requested model via
  the pinned variant; this trace format carries no provider usage-token
  fields, so attribution rests on request-side event evidence (noted per
  the attribution rule). Honest causal note: UNSUSPEND (merged that
  morning, PR #41) was used twice, late, and found nothing to unsuspend —
  the suspended-job wedge simply did not recur this run. The pass is
  attributable to the accumulated observation-truth corrections (legacy
  plan decoupled #35, queued walls visible #38, per-tile placement reasons
  #40) plus the vision modality, not to the new primitive. One pass is
  existence, not reliability: the G4 ladder rung is cleared, and the
  natural follow-ups are a repeatability series on this seed and G6
  generalization (a `seed_region2_fresh` save already exists on the VM).

- **2026-07-06 — PRE-DECLARED PROTOCOL: G4 repeatability series + 250-step
  endurance probe (operator-approved before launch).** (a) Repeatability:
  four additional runs (#5-#8 of the lineage), GLM-5V pinned, 100 steps,
  memory-off, score-v2, config unchanged from the passing run `2f58fd37`;
  all four run to completion regardless of outcome; the reported number is
  the pass rate over the five-run lineage. Honest footnote: runs #5-#8
  execute on post-PR-#44/#46 code where the proof window follows the fort,
  so proof-backed step counts (and via the repetition check, possibly
  rubric) are not strictly comparable to run #4's 46/100 — the change was
  operator-approved measurement truth (walls built off-window now count as
  evidence) and is disclosed here in advance. (b) Endurance probe: ONE run,
  same config, 250 steps x 1000 ticks. A probe, not a gate. Pre-declared
  questions, each answered from the run's own trace at step 100 vs step
  250: functional_rooms strictly greater at 250 than at 100 (structure
  compounds); produced-goods diversity >= 4 types by 250; no
  repetitive_policy or no_production_surface blocker at end; final score
  >= 1.25x the step-100 score (the extra horizon is used, not idled).
  Purpose: measure whether the policy compounds or satisfices past
  passing-level structure — either answer is a finding and gets reported
  with the same prominence.

- **2026-07-06 — RESULTS: repeatability 2/5, and the endurance probe found
  the next incentive gap.** Repeatability series (runs #5-#8, 100 steps,
  config identical to the pass): run #5 `01a57454` **PASSED 6/6** (second
  pass in history); #6 `d06cc571`, #7 `7f268bcc`, #8 `71ffc569` failed.
  **Lineage pass rate: 2/5 (40%)** — G4 is real but unreliable; the
  bottleneck remains second-room completion variance. Endurance probe run
  #9 `ad70df06` (250 steps, 198,042 ticks, score 515.44, rubric 68.61 zero
  blockers, pop 7->13 with ALL migrants surviving, 250/250 frames, 500/500
  events `z-ai/glm-5v-turbo`,
  `fortgym.live/r/8ACitgQEErsR8fdjTRMb59CrTm4D6k1q`). Pre-declared
  answers: (a) structure compounds — **NO**: 1 functional room at step 98,
  still 1 at step 249; (b) goods diversity >= 4 — YES (5 types); (c) no
  degeneration blockers — YES; (d) score >= 1.25x step-100 — YES, 5.35x
  (93.59 -> 500.8). Verdict: **the policy satisfices structurally and
  compounds economically in a degenerate direction** — after closing room
  1 it spent ~150 steps as a chair factory (111 BUILD:Chair actions, 10
  chair orders, 26 chairs produced for 13 dwarves). Not an illegal-progress
  exploit (every good is real, produced world-change) but
  Goodhart-by-monoculture: score-v2 pays real production linearly with no
  diminishing returns, so the optimal long-horizon policy is to mass-produce
  the cheapest item rather than build. Evidence for the pending score-v3
  decision (plan-agnostic complexity + per-type diminishing returns are now
  both on the table, one operator-approved boundary). The rubric held
  partial ground: 68.61 stays under the 70 gate bar.

- **2026-07-07 — G6 SEED: region2 condemned, region3 created and validated
  (reproducible procedure).** The Dec-2025 `seed_region2_fresh` save is
  corrupt in a hazardous way: merely PRESENT in `data/save/`, it SIGABRTs
  DF 0.47.05 during the boot-time world scan (before DFHack initializes) —
  it caused a full platform outage on 2026-07-07 when staged for
  validation (an unattended package upgrade was the initial suspect;
  the DF binary links none of the upgraded packages — quarantining the
  save restored boot immediately). It now lives OUTSIDE the save dir at
  `data/save-quarantine/region2`; never copy it back. Replacement:
  `seed_region3_fresh`, created via a fully documented, reproducible
  procedure — headless worldgen `-gen 3 20260707 "POCKET REGION"` (fixed
  seed; run under a pty — the ncurses build aborts without one), embark
  driven through the same DFHack keystroke transport the benchmark uses,
  site selected by instrument survey (Heavily forested, thick vegetation,
  brook, NO aquifer; 166 tree trunks across six 30x30 sample rects;
  diggable rock; 7 citizens at z=161 vs region1's z=177), immediate
  DFHack `quicksave`, then frozen read-only in `seed_saves/`. Boot
  validation passed with region3 present — the exact check region2
  fails. All benchmark instruments (fort_metrics flood-fill, crew survey,
  minimap) ran unmodified on the new embark with honest zeros. Runs can
  now target it per-run: `POST /runs` accepts `seed_save`/`runtime_save`
  (name-validated), recorded in run provenance — no deployment-config
  change needed to attempt G6.

- **2026-07-07 — PRE-DECLARED PROTOCOL: G6 generalization attempt
  (operator-ratified before launch).** One public run per attempt on
  `seed_region3_fresh` — an embark no agent has ever seen — GLM-5V pinned,
  100 steps x 1000 ticks, memory-off (region1 memories would be false on
  region3 regardless), score-v3, seed targeted per-run via the new
  `seed_save`/`runtime_save` request fields (PR #51). PASS = G4-level
  structure on the unseen map: >=50,000 elapsed ticks; population >=7 held
  with zero casualty spike; >=2 workshop orders completed
  (finished-goods deltas); `fort_functional_rooms >= 2` (flood-fill);
  rubric >= 70 with no `no_fort_structure` / `repetitive_policy` /
  `no_production_surface` / legality blockers. **Ratified adaptation: the
  G4 score-vs-ceiling clause does not port** — region1's 121.5 ceiling
  comes from a scripted reference agent hardcoded to region1 coordinates,
  and porting a plan-walker to set a region3 ceiling would rebuild
  exactly the hardcoded-plan machinery this project removed; the scalar
  is recorded for the run but carries no pass/fail weight at G6. Failures
  get the standing forensics -> surface-correction -> retry discipline
  (corrections operator-approved as always), up to three attempts before
  an escalation decision. Every attempt reported at full prominence.

- **2026-07-07 — G6 attempt 1: FAIL 2/5, and the unseen map exposed two
  measurement lies in one run.** Run `769f5034` (GLM-5V, 100 steps,
  memory-off, score-v3, seed_region3_fresh via per-run selection —
  provenance recorded correctly on first production use;
  `fortgym.live/r/cQKTXD8xnEUNV9COJIvXR9zB7Mg3F59M`): ticks 100,384 PASS;
  orders completed (7 beds) PASS; population 6/7 FAIL; rooms 0/2 FAIL;
  rubric 69.06 (just under 70) with zero blockers FAIL. Forensics: (a)
  **wood blindness** — region3's spawn is a clearing; zero tree trunks
  were visible anywhere in the agent's observation window all run
  (region1's spawn happened to have trees in-frame, masking this for the
  entire campaign). The agent chopped blind near its base (3 attempts),
  wood peaked at 6, walls died `no_building_material` x13, and 25 bed
  installs failed with nothing produced to install. Correction: a bounded
  read-only Nearby-trees scan (40 tiles around the citizens, top-3
  clusters with coordinates) joins the observation — factual content, no
  strategy. (b) **the dead metric was a hardcoded constant** — gamelog
  records "kut, Jeweler has been found dead, drowned" (the brook), the
  population criterion caught it honestly (6<7), but `state.dead = 0` was
  literal in the state reader since day one; the casualty-spike check has
  never measured anything. Correction: count the civ's dead dwarves for
  real (isDwarf + isDead). Both corrections held for the operator window;
  attempt 2 of 3 follows per the pre-declared protocol.

- **2026-07-08 — G6 attempt 2: FAIL 3/5, and the third invisible fact of
  the campaign surfaced.** Run `55c39cdd` (config per protocol, post
  attempt-1 corrections;
  `fortgym.live/r/twSeylYz5Z6Mb5Mh11pIR20DpW5Yxrtg`): ticks PASS,
  population 7/7 PASS (no deaths — the new dead metric live), orders
  completed PASS (2 beds), rooms 0/2 FAIL, rubric 69.56 FAIL (second
  consecutive just-under-70; the parked v2/v3 rubric-bar review now bites
  G6 directly). The attempt-1 corrections verifiably worked: the
  Nearby-trees line reported real clusters and early chops raised wood
  3->11 by step 10. Then the instrument lied by omission again: at step 8
  the agent placed 10 wall segments at once and **each pending
  construction immediately claimed a log — 10 of 11 logs locked — while
  the stocks line kept reading "Wood: 11" for the remaining 90 steps.**
  22 further wall attempts failed no_building_material against
  apparently-full stock; end-state item flags confirm the mechanism
  (constructions consume their claimed logs on completion). Correction
  (operator window): stocks now report USABLE counts — items not claimed
  by jobs or locked in (pending) buildings, the same filter the build
  hooks apply — rendered as "Wood: 11 (1 usable, rest locked in
  jobs/buildings)", with the claim mechanic stated factually in the
  prompt. Residual honest note: the agent also under-harvested (3 chops,
  never at the reported far clusters) — that part is policy, not
  instrument, and stands as a genuine G6 finding-in-progress: on wood-rich
  region1 logistics was free; on region3 it is the game.

- **2026-07-08 — G6 attempt 3: FAIL 3/5. CAMPAIGN CONCLUDES 0/3 — recorded
  at full prominence, with the correction ladder's effect measured.** Run
  `19f692b8` (`fortgym.live/r/OnonN6SkMid42X4NRAHYBnzYFYwhh5-g`): ticks
  PASS; orders completed PASS; **rubric 70.88 clean PASS — the first
  region3 run over the bar** (trajectory across attempts: 69.06 -> 69.56
  -> 70.88); rooms 0/2 FAIL; population 5/7 FAIL (two more drownings —
  the brook has now killed three dwarves in three runs; region1 never had
  an accessible water hazard). The wood economy is SOLVED: one chop at a
  Nearby-trees cluster produced 112 logs by step 25 (attempt 1 peaked at
  6) — the attempt-1 correction alone cracked logistics. Honest defect
  disclosure: the attempt-2 usable-stocks correction NEVER REACHED the
  agent in attempt 3 — the StateReader field whitelist silently dropped
  `wood_usable`/`stone_usable` between the state script and the encoder
  (verified: `usable: None` in every step's observation). The correction
  was approved, shipped, tested at both ends, and lost in the pipe; the
  completion fix is a one-line whitelist addition with an end-to-end
  test, held for the next window. G6 verdict: **the frontier on unseen
  terrain is not geometry alone — it is logistics (solved by factual
  observation), environmental hazard (drownings, unsolved: no legal
  action addresses water safety short of walls), and ring-closing under
  those pressures (0 enclosures in 3 runs at up to 112 logs available).**
  Escalation options to the operator per protocol: (a) GPT-5.5-vision on
  region3 (~$10) — separates policy strength from environment difficulty;
  (b) amended protocol: complete the usable-stocks pipeline + further
  GLM-5V attempts; (c) accept-and-document G6 as the open frontier and
  proceed to the G7 primitives window. **Operator selected (2026-07-08): a
  hybrid of (a)+(b)** — one GPT-5.5-vision run and one corrected-instrument
  GLM-5V run on region3, both under the standing G6 criteria, after the
  usable-stocks pipeline completion (PR #59) deployed.

- **2026-07-08 — G6 ESCALATION (operator-selected hybrid): both runs FAIL,
  and both build the first enclosed rooms ever seen on the unseen map.**
  (a) Corrected-instrument GLM-5V, run `c8e46054`
  (`fortgym.live/r/CHt5-Grk_uBqX7kj23MyGU3vh512qEh3`): FAIL 3/5 — but
  **1 enclosed functional room** (rooms on region3 across five GLM runs:
  0, 0, 0, then 1 with the full correction stack finally end-to-end),
  rubric 77.51 clean, best GLM region3 economy (5 beds + 2 doors, 25
  constructions); failed rooms>=2 and population 6/7 (another drowning —
  the brook's fourth victim). (b) GPT-5.5-vision, run `36f9f78f`
  (`fortgym.live/r/ayENDjV5v5K35Mblffz3I53mEGsA3sOW`): **FAIL 4/5,
  missing ONLY rooms>=2** — the strongest region3 run recorded: rubric
  83.44 clean, population 7/7 held, 74 constructions, 5 goods types, 1
  functional room. Interpretation: the escalation question is answered —
  region3 is NOT impassable; with a truthful instrument both models now
  close rings on unseen terrain, and the frontier is the same
  "second room" wall that G4 had on region1 before it fell. The
  environment is genuinely harder (drownings, logistics) but tractable.
  GPT-5.5-vision's 4/5-missing-only-rooms exactly matches the profile
  that preceded the G4 pass. Next escalation decision to the operator;
  no further runs until chosen.

- **2026-07-08 — G6 escalation round 2 (operator-selected): GPT-5.5-vision
  FAIL 3/5 — and the time-budget hypothesis is refuted.** Run `3f4c99eb`
  (`fortgym.live/r/aeWp5OHHyhrjJA2b5BUZSJ33eNo5MJq3`): rubric 77.94
  clean, 55 constructions, 1 functional room, population 6/7 (a fifth
  brook drowning), weaker economy than round 1 — a regression on the
  rooms-adjacent profile. Decisive timing fact: with the corrected
  instrument, room #1 now lands at steps 13-27 on region3 (gpt55v r1:
  13, glm5v att4: 23, gpt55v r2: 27) — as fast as region1's best — so
  the models have 70+ remaining steps and still never build a second
  room. The frontier is not time budget or logistics: it is
  second-room construction on unseen terrain, plus water safety (5
  drownings in 7 region3 runs; region1 had zero accessible water).
  Campaign totals: 7 region3 runs, 2 models, 5 instrument corrections,
  rooms column 0,0,0,1,1,1,1. G6 stands unpassed and precisely mapped;
  further attempts remain open at future windows (cheaper under
  multi-instance, or with new models). The ladder proceeds to the G7
  primitives window.

- **2026-07-08 — G7 primitives LIVE-VALIDATED on the runtime fort; two
  engine-mechanics corrections found and one fixed in this change.** After
  the operator window merged the reviewed primitives (#53/#54/#56 + drink
  scoring), all three were exercised on the live region3 runtime fort
  (safe to mutate: runtime resets from the frozen seed at the next run).
  What was proven end-to-end:
  - **gather**: a 30x30 gather rect designated 74 shrubs (822 non-shrub
    tiles honestly skipped); the job manager generated 73 GatherPlants
    jobs; the herbalist collected continuously (plants in play 3 → 24+;
    "Endok Oslankosh has become a Herbalist" in the game log). The rect
    also surfaced 4 shrubs *already designated* plus ~40 inert dig flags
    on floor tiles — the live footprint of the pre-#53 bug (unconditional
    designation writes), left by earlier runs. New dig calls on the same
    surface designate zero tiles.
  - **FarmPlot**: constructed to stage 3/3 by a dwarf. **Confirmed gap:
    `plant_id` stays [-1,-1,-1,-1] — constructBuilding never selects
    crops, so an unamended farm plot will never be planted.** This was
    the review's note-only question; it is now a measured fact. Crop
    selection is a follow-up primitive amendment (operator decision:
    default-crop-at-placement mirroring the player's b-p flow, vs. a
    separate action).
  - **Still + brew**: `df.workshop_type.Still` resolves and the Still was
    dwarf-built to stage 3/3. **Correction (fixed here):
    `df.job_type.BrewDrink` does not exist on 0.47.05** — ORDER job=brew
    always returned `unsupported_job_type`; the Still's real job list
    offers `CustomReaction` entries and brewing is the
    `BREW_DRINK_FROM_PLANT` reaction. With the corrected job creation
    (validated first via a probe using the hook's exact idiom), a brew
    executed on the live fort: one gathered plant + one empty barrel →
    a 19-unit drink stack, observed by the new drink counter (7 → 8).
    `order_make.lua` now matches reaction-backed items on
    `job_fields.reaction_name` and records `reaction_name` on the
    manager-order fallback; prompt/encoder text updated to stop naming
    the nonexistent job type.
  - **Labor contention (observation, no code change)**: the brew job sat
    unexecuted for 19k+ ticks because the only brewing-enabled dwarf was
    also the herbalist, saturated by gather jobs. It executed within 6k
    ticks of a validation probe enabling the brewing labor on an idle
    dwarf (disclosed intervention, runtime fort only). Labor coverage is
    outside the governed action surface; G7 runs can starve on it. Left
    open for the G7 gate discussion.
  - **Environmental note**: during validation — with zero agent actions —
    the fort's fisherdwarf drowned in the brook ("Edem Lekkivish, Fish
    Cleaner has been found dead, drowned"), the sixth drowning observed
    on region3. The water hazard is environmental, not agent-induced,
    strengthening the G6 water-safety finding. A migrant wave also
    arrived (population 6 → 9), confirming the runtime fort ticks
    normally under external advancement.

- **2026-07-08 — FARM + LABOR primitives: built, adversarially reviewed,
  live-validated; G7 proposed for final ratification.** Operator directives:
  crop selection must be agent-controlled ("We should not bound it. Enable
  the tool and agent control"), labors get observation AND a primitive now,
  G7 ratification approved once the surface is complete.
  - **Mechanism probed before code**: setting `plant_id[summer]=RADISH` on
    the live plot made a dwarf haul and plant the seed within ~5k ticks.
    The brew fix (#63) was verified through the deployed governed hook
    (`created_job_ids` at the Still).
  - **FARM** (`feat/farm-crop-control`): params building_id/crop/seasons;
    per-season before/after plant_id evidence, season_not_growable skips,
    seeds_on_hand informational. Review (3 lenses) found 4: stale
    docstrings; FARM skip reasons never rendered to the agent (the
    int-only Last-Action whitelist dropped them — same class as the
    StateReader regression); and the surface/subterranean rejection gate
    was built on one unverified biome flag — **removed entirely**: crop
    eligibility stays with the engine, the primitive never fabricates a
    rejection reason. 527 tests.
  - **LABOR** (`feat/labor-primitive`): params unit_id/labor/enable over a
    10-labor whitelist; per-citizen id+labors+current-job observation.
    Review found a **major**: alternating enable/disable on one
    (unit,labor) pair farmed world-change credit and permanently escaped
    the repetition blocker. Fixed: only the first real flip per target
    credits progress in the rubric window; repeat toggles fall to the
    stale tally; fingerprint drops the direction so oscillation collapses
    into one bucket; churn test proves repetitive_policy now fires. 530
    tests.
  - **Live battery (runtime fort)**: FARM set-all/single-season/no-op/
    season-gate/bad-token/bad-building/clear all honest; LABOR enable/
    disable/no-op/unit_not_found/not_a_citizen/unsupported_labor all
    honest. **Live enum audit caught `BUILD_BUILDING` absent on 0.47.05**
    (the implementer's flagged risk) — real name `BUILD_CONSTRUCTION`,
    fixed and re-verified with a real flip. Seeds observation truthful:
    RADISH/POTATO/BLUEBERRY surface, six cavern crops subterranean,
    seasons per raw flags. Farm-plot crops line renders cleared seasons
    as "-".
  - **G7 "The fort lives" — proposed for final ratification at the next
    window.** With #63 merged and FARM/LABOR held, the loop
    gather → farm → brew → drink is closed with every link proven on the
    live fort. Open risk carried into the gate honestly: labor contention
    (observed brew starvation) is now agent-solvable via LABOR; water
    safety remains unmitigated (6 environmental drownings on region3).

- **2026-07-09 — G7 attempt 1: FAIL. The run proved the seven-action
  surface can compose real work, then exposed a missing dialog action and
  a fail-open runner.** Run `f6a87f6afb6241c082a6a015c361d755`
  ([replay](https://fortgym.live/r/GbccbSS-d6bADihKEosLgx6788yhoaqx)),
  commit `4804ee00c`, trace-attributed model `z-ai/glm-5v-turbo`,
  `seed_region3_fresh`, score-v3. The operator stopped it after the game
  became trapped on the Mountainhomes liaison meeting; terminal status is
  `stopped`, with 274 governed gameplay rows plus one terminal row.
  Evidence is complete for the gameplay rows: 274/274 `screen_text`,
  274/274 `gameplay_proof`, 274/274 `dfhack_governed` provenance; 125
  proof rows report real progress. The run made 273 model calls using
  2,013,504 tokens.

  Predicate verdict: duration **FAIL** (199,691/403,200 ticks); food/drink
  loop **FAIL** (food 45->19, drink 60->0, no food-production proof, no
  sustained brewing); neglect-death rule **UNKNOWN and therefore cannot
  pass** (one death is observed at step 27, but the trace has no cause);
  population **PASS** (15); functional rooms **FAIL** (0/3); installed-bed
  rule **UNKNOWN** (14 bed buildings are observed, but the current field
  includes both installed and still-being-installed furniture; required 5);
  scalar **PASS** (209.44 >= 150); rubric **FAIL** (63.79 < 70, blockers
  empty). Overall G7 is an unambiguous **FAIL** independently on duration,
  survival loop, and rooms.

  What happened in-game: the policy used all seven action types, produced
  real furniture and goods, survived a migrant wave, built one farm plot,
  and placed two Stills. Neither Still reached construction stage 1; the
  farm selected plump helmets for all seasons and recorded no food
  production; the fort ended with 26 constructions and zero enclosures.
  At step 198 the liaison dialog opened after 915 of the requested 1000
  ticks. The next 75 steps advanced zero ticks at `217225` while the model
  continued issuing actions (mostly BUILD/UNSUSPEND/WAIT) against an
  unchanged screen.

  Failure split: (a) **substrate** — governed play has no bounded legal
  confirm/cancel/dialog action, though a human player would answer the
  meeting while paused; (b) **runtime** — zero-tick timeouts did not stop
  future model calls and cooperative cancellation took additional rows to
  become durable; (c) **policy** — late brewing response, an incompatible
  crop choice, repeated failed construction recovery, and no enclosed
  rooms. The next attempt is prohibited until the substrate and runtime
  failures are corrected and live-validated. Policy failures stand; they
  are not repaired with gameplay heuristics. The evaluator must also gain
  completed-stage furniture evidence before it can clear the installed-bed
  predicate.

- **2026-07-09 — G7 attempt 2 run-integrity candidate implemented and
  isolated-live-validated; not yet production-deployed.** The governed surface
  now has eight actions. `INTERACT` accepts one semantic operation
  (`confirm/cancel/up/down/left/right`), requires an explicit strict integer
  `advance_ticks: 0`, and dispatches exactly one fixed DF interface key only
  when the game is paused on an allowlisted interactive viewscreen. It carries
  governed provenance but never earns gameplay-progress credit. One modal
  episode is capped at eight operations; three unchanged screens terminate it,
  while modal exit or positive ticks reset the episode.

  The runner now terminates a zero-progress timeout before another policy call,
  records partial tick advancement as degraded rather than lost, checks
  cancellation after pause/decision/execute/advance, and durably writes a
  terminal trace reason before the registry status. A run-scoped DFHack ledger
  records food/drink item creation, per-citizen eat/drink history, and immediate
  death facts; `job_metrics.lua` separately reports completed-stage furniture.
  `scripts/evaluate_g7.py` deterministically evaluates all ratified G7
  predicates and returns UNKNOWN when evidence is incomplete.

  Review hardening made four evidence/lifecycle boundaries explicit: the Lua
  citizen predicate returns one boolean (so animals, visitors, and enemies
  cannot enter the ledger); elapsed duration is summed from trace
  `ticks_advanced` and must agree with any positive summary value; zero deaths
  pass only with complete evidence from the same run; and a transactional
  `pending -> running` claim must succeed before a worker can touch the trace or
  global ledger. Regression coverage includes forged summaries, stale and
  incomplete death ledgers, and duplicate workers attempting the same run id.

  Isolated live smoke `live-g7-interact-smoke2` ran the candidate from `/tmp`
  against the actual stopped liaison screen, outside the production registry.
  One `confirm` sent exactly one `SELECT`, advanced 0 ticks, stayed paused,
  changed the CopyScreen hash, and exited `viewscreen_textviewerst` to
  `viewscreen_dwarfmodest`; validation, governed provenance, and no-progress
  credit checks all passed. Candidate ledger smoke `g7-candidate-live-smoke`
  then passed start/read/stop validation on deployed DF `0.47.05-r8` at game
  tick `217225`, with complete flags, the expected run id, zero errors, and no
  tick advancement. The complete local suite passes (`607 passed, 4 skipped`),
  and the stricter evaluator reproduces attempt 1's failure from its permanent
  trace (including exact 199,691-tick trace/summary agreement). These prove
  candidate runtime compatibility, not deployment. Attempt 2 remains
  prohibited until the candidate is committed, deployed in an explicit
  operator window, and the deployed smoke passes.

- **2026-07-09 — G7 attempt 2: INFRASTRUCTURE ABORT / FAIL; no policy
  verdict.** Run `c7d1ec905bc14d59a2d320da8f6169a1`
  ([replay](https://fortgym.live/r/tAoONBlHKNhYTS_4mjUJ8deS7-b5ypGc)),
  commit `311f82963`, trace-attributed model `z-ai/glm-5v-turbo`, fresh
  `seed_region3_fresh`, memory off, score-v3. The seed copy initially remained
  at DF's title screen because `runtime_save=current` is a staging alias and DF
  canonicalized the copied world back to `region3`; the operator loaded that
  exact copied save as a disclosed setup correction before any model call or
  game tick.

  Deployment verification before launch confirmed the exact merged tree and
  healthy public/API services, re-verified the earlier positive liaison trace
  with the deployed verifier, and proved a live main-map `INTERACT` attempt was
  rejected before sending a key. The liaison had already been dismissed, so a
  second positive live input was not fabricated merely to make the smoke green.

  The policy then completed 11 governed rows and 11,042 real trace ticks. It
  built a Carpenter workshop, produced two beds, placed and planted a FarmPlot,
  built a Still, queued brewing, and designated plant gathering. Population
  remained 7 and stocks remained food 45 / drink 60; rubric was 79.92 with
  `no_fort_structure`, scalar score 73.68. Eleven OpenRouter calls used 58,686
  prompt and 3,928 completion tokens. This early gameplay is evidence, but not
  a G7 success.

  At step 8 the first gathered non-farm plant exposed a ledger return-contract
  bug: `item_on_completed_farm_plot()` returned one boolean while its caller
  unpacked `(classification_succeeded, on_farm)`. The ledger therefore set
  `flow_evidence_complete=false` permanently, making a truthful G7 pass
  impossible. The operator stopped at step 10; the final row durably records
  `stop_requested_after_advance`, and callbacks detached. G7 fails independently
  on duration and rooms, while food/drink evidence is UNKNOWN. This is an
  infrastructure failure, not a favorable policy reinterpretation.

  Follow-up candidate fixes now return both farm-classification values and
  resolve DF's canonical save folder by matching the copied seed's `world.sav`,
  failing closed on no or multiple matches. The complete suite passes (`613
  passed, 4 skipped`). Isolated live
  proof on the stopped disposable runtime observed one gathered plant with
  `nonfarm_plants_created_in_run=1`, complete flow evidence, and zero errors;
  a second live reset loaded the fresh region3 fortress through the `current`
  alias without manual intervention. Attempt 3 was prohibited until this
  follow-up is reviewed, merged, deployed, and re-smoked.

- **2026-07-09 — G7 attempt 3: INFRASTRUCTURE ABORT / FAIL; no policy
  verdict.** Run `622dac1c396c454d90e070bb8b669905`
  ([replay](https://fortgym.live/r/i7wIFrZC_7xXlTJmQaXTRfWnWPMAxxeO)), deployed
  SHA `62030af8e3ed656e501f50e49c10968a932479a5`, trace-attributed model
  `z-ai/glm-5v-turbo` via OpenRouter, Anthropic disabled, memory off. The run
  produced 46 durable rows and 46,160 trace ticks; the summary reports 45,155
  because it excludes the final stop row. Token use was 305,552 prompt and
  15,421 completion. Actions were BUILD 33, DIG 1, FARM 1, ORDER 6, WAIT 5.

  Real play included building a Carpenter workshop, producing and placing doors,
  chopping trees, completing 18 construction tiles, reaching a peak of two
  functional rooms and three enclosed spaces, building a Still, and
  building a FarmPlot with a selected crop. Population was 7, food 45, drink 60,
  and deaths were zero. At step 40, `build_workshop.lua` reused material item
  `765` already installed in the Carpenter workshop because it did not reject
  `item.flags.in_building`. The Still reused the same item, and the Carpenter
  workshop disappeared without agent deconstruction. This violated player
  parity and invalidated the run.

  The operator requested stop at API step 44; the final durable row is step 45
  and status is `stopped`. Ledger evidence remained complete, but its DF callback
  remained active after terminal status because optional Gemini analysis ran
  before outer `finally` cleanup. The operator detached the ledger callback and
  restarted only the API to cancel the analyzer; the replay persisted. Summary
  scalar 102.38 and rubric 92.54 with
  `blockers=[]` are explicitly not a pass: the action primitive violated player
  parity, and the run missed G7 duration, production, and rooms.

  Follow-up candidate now rejects `item.flags.in_building`, durably stages a
  terminal reason before cleanup, and publishes terminal status only after
  verified pause/evidence detach/client close and durable summary persistence.
  Stop intent and cleanup proof survive API restarts; unverified cleanup becomes
  an infrastructure failure and skips optional analysis. The complete suite
  passes (626 passed, 4 skipped). An isolated live smoke first failed closed on the
  seed's in-building wagon material; after legal tree chopping, Carpenter used
  item `776`, Still used item `771`, and both completed workshops remained in
  the world. Independent review then closed five lifecycle gaps; PR #69 merged
  and deployed as `808f25d6942b89844768c78b80911646dbb0d5b0`. A deployed
  boundary smoke observed the registry remain `running` until the ledger was
  inactive, cleanup and summary were durable, and final status became
  `stopped`. Attempt 4 then launched from that exact SHA.

- **2026-07-09 — G7 attempt 4: INFRASTRUCTURE ABORT / FAIL; no policy
  verdict.** Run `45659da07fb749f9b5ebe9c55dd1eb91`
  ([replay](https://fortgym.live/r/4Gn9v9WaPf_i4qhGJFQs9bo9d8y_GSBo)),
  deployed SHA `808f25d6942b89844768c78b80911646dbb0d5b0`,
  trace-attributed model `z-ai/glm-5v-turbo` via OpenRouter, Anthropic disabled,
  memory off. The declared 450-step run failed closed after 208 durable rows
  and 202,737 trace ticks with terminal code
  `interaction_unchanged_screen_loop`. Cleanup completed, the run ledger is
  inactive, and `summary.json` was durable before status `failed`. All 208 rows
  contain screen text, gameplay proof, and governed provenance; 130 proof rows
  report real state change. The 208 model calls used 1,520,316 prompt and 66,213
  completion tokens. Actions were BUILD 85, DIG 5, FARM 2, INTERACT 4, LABOR 2,
  ORDER 20, UNSUSPEND 27, and WAIT 63.

  Deterministic G7 verdict: duration **FAIL** (202,737/403,200); food/drink loop
  **FAIL** (food produced 0 vs consumed 35, drink produced 0 vs consumed 60,
  final food 16 and drink 0); neglect-death rule **UNKNOWN** (one observed
  drowning has complete death-record capture but no mapped cause enum);
  population **FAIL** (13/15); functional rooms **FAIL** (0/3); installed beds
  **FAIL** (1/5 completed); rubric **FAIL** (68.86/70, no blockers); scalar
  **PASS** (score-v3 180.56). Overall G7 is **FAIL** independently of the
  infrastructure invalidation.

  Real play included a completed Carpenter workshop; final in-play goods of five
  beds, five doors, five tables, five chairs, five bins, and 29 barrels; 40
  construction tiles; three
  completed door installations and one completed bed installation; a completed
  one-tile farm plot configured for plump helmets in all seasons; a migrant wave
  from 6 to 13 citizens; and one drowning. The Still remained stage 0/3, 35 wall
  jobs plus the Still job remained pending, no room became enclosed or
  functional, and no food or drink was produced.

  Two command-boundary defects permanently invalidate a policy verdict. First,
  the placement hooks selected the nearest material by coordinate distance but
  never required shared engine walk connectivity. A post-terminal read-only
  candidate probe against the still-loaded run classified **36/36
  ConstructBuilding jobs as walk-group disconnected**: zero connected, zero
  unknown. Sample job 82 targeted `(89,102,161)` but reserved item 777 at
  `(90,105,160)`; no citizen shared a walk group with both job and item. The
  deployed hook also accepted non-floor terrain and completed construction tiles
  because DFHack's direct `constructBuilding` API performs fewer player-menu
  legality checks. Second, four `ORDER job=brew` actions returned `ok=true` with no built
  Still; the fallback recorded manager entries, called a missing `orders`
  script, and returned `processed=false` rather than rejecting the action. No
  brew job existed.

  The terminal dialog exposed a third bounded-surface gap. After a liaison
  screen transitioned to `viewscreen_topicmeetingst`, the visible command was
  `a - Finish peeking in on conversation`; `confirm` sent `SELECT`, which did
  nothing three times and correctly tripped the unchanged-screen guard. A
  post-terminal live probe proved DF's semantic `OPTION1` exits that exact
  screen while the game remains paused and tick 220,247 does not advance.

  Follow-up candidate now requires dry, visible FLOOR targets and one living
  citizen whose current DF walk group includes both target and selected item
  across walls, workshops, and furniture; applies DF's `isBuildMat()` predicate
  and item flags; rejects completed construction tiles; verifies the resulting
  job is linked to the selected item; and exposes per-job
  `connected`/`disconnected`/`unknown` walk-group evidence to the model. This is
  a connectivity snapshot, not a guarantee of haul assignment or completion.
  ORDER now fails unless a completed matching workshop exists and real workshop
  jobs are linked. `finish_topic_meeting` maps to one `OPTION1` only on
  `viewscreen_topicmeetingst` with the exact option visible; an unchanged result
  is recorded as `interaction_no_effect`, not success. Final review also made
  wet furniture, removal-marked workshops, partial rectangles, and rollback
  failures explicit non-successes.

  The final isolated fresh-seed repetition passed against DF 0.47.05. Immediately
  after load, Wall and Still failed closed with `path_cache_stale`; 129 real
  ticks rebuilt DF's path data. They then rejected the wagon's in-building logs
  with `no_building_material`, while brew rejected
  `required_workshop_unavailable`. After one legal chop and 1,000 real ticks,
  Wall selected connected item 768 at `(91,100,161)`; the read-only observation
  reported `walk_group_connectivity=connected`, and a dwarf completed the wall
  at `(90,102,161)` in the next 1,004 ticks. Still then selected connected item
  772 at `(92,101,161)`, reported `connected`, and a dwarf completed workshop 2
  to stage 3/3 in 1,007 ticks. Only then did quantity-two brew create exactly
  two concrete `CustomReaction` jobs 6 and 8. The manager-order count remained 0
  before and after, proving the direct jobs were not duplicated by a latent
  manager order. Two post-smoke boundary probes also passed: a five-tile mixed
  rectangle placed three legal jobs but returned `ok=false`,
  `partial_placement`, and both rejected tile reasons; a completed Still marked
  for removal rejected another brew order with `required_workshop_unavailable`.
  Local verification is 634 passed, 4 skipped; targeted Ruff, compileall, and
  live Lua parsing passed.

- **2026-07-09/10 — G7 attempt 5: INFRASTRUCTURE-ABORTED FAIL; policy
  behavior also failed every survival objective reached before the abort.**
  Independent Sol and Terra audits found seven release blockers; each was fixed,
  and final Sol review reported no remaining deployment blocker. PR #70 passed
  GitHub CI, merged, and deployed as
  `e012e704b7a45cd509034700c3524801217130ef`. The production API and DFHack
  services stayed healthy. A deployed fresh-seed repetition again failed closed
  on stale path data, wagon logs, and pre-Still brew; then dwarves completed a
  connected wall and Still over real ticks, after which quantity-two brew linked
  exactly jobs 6 and 8 while manager-order count stayed zero. Deployed probes
  also returned `partial_placement` for a mixed rectangle and rejected a
  removal-marked Still.

  Attempt 5 run `680a938aabd84764953dd01c0ccf1c7f`
  ([live replay](https://fortgym.live/r/88uZqRulANyNG_e7t7c6KFlEOYRvHZdz))
  launched from that SHA for at most 450 steps on fresh `seed_region3_fresh`, with
  `dfhack-governed-llm-glm5v` (`z-ai/glm-5v-turbo` through OpenRouter), memory
  persistence off, Anthropic disabled, score-v3, and 1,000 default ticks per
  step. It terminated failed after 210 rows at step 209. The terminal code was
  `interaction_unchanged_screen_loop`: a second
  `viewscreen_topicmeetingst` variant visibly offered only `a - Begin
  discussion`; the deployed `finish_topic_meeting` operation correctly
  rejected that different text, while two cursor-down inputs and `confirm`
  left the screen unchanged. Cleanup completed before failed status and the G7
  evidence ledger is inactive with the final run-scoped record intact.

  Deterministic G7 verdict: duration **FAIL** (201,556/403,200 ticks); food and
  drink loop **FAIL** (food 0 produced/38 consumed, drink 0/60, final stocks
  food 7 and drink 0); neglect death **UNKNOWN** (one drowning record lacks
  factual cause evidence and is not falsely cleared); population **FAIL**
  (13/15); functional rooms **FAIL** (1/3); installed beds **PASS** (5/5);
  rubric **PASS** (70.72, no blockers); scalar **PASS** (score-v3 178.59).
  Evidence completeness failed because 210 gameplay rows contain 208 executed
  governed proof/screen rows; the validation-rejected dialog attempt did not
  mutate the game. Overall G7 is **FAIL** independently of the inflated scalar.

  Real DF changes were substantial but not self-sustaining: population rose
  from 7 to 13, dwarves completed a Carpenter's Workshop, 15 constructions,
  five beds, four doors, five tables, and six chairs, but the fort had only one
  malformed one-tile functional room, no FarmPlot, no Still, and zero food or
  drink production. From steps 145-194, 30 of 38 BUILD attempts were rejected
  on occupied/non-floor coordinates already represented in observation facts.
  At drink zero the model continued furniture production; an accepted chair
  order helped score-v3 jump even though survival worsened. The scalar remains
  telemetry, not the verdict.

  Post-terminal candidate proof sent one `OPTION1` only after re-reading the
  exact `a - Begin discussion` screen; DF changed to
  `viewscreen_topicmeeting_takerequestsst`. PR #72 now preserves factual
  governed action history and PR #73 requires BUILD-footprint grounding. The
  next candidate adds visible `topic_option_a` through `topic_option_h`
  operations plus an agent-authored review contract: every decision reviews
  the factual previous outcome, and initial/periodic/stalled/partial checkpoints
  establish, continue, or revise the model's own objective using observation-
  grounded evidence. The candidate restricts evidence to runner-authored lines,
  requires two distinct immutable `E#` plan references, binds retry claims to a
  stable type+params fingerprint, preserves a six-entry minimum review horizon,
  and retries transient OpenRouter transport before gameplay. Reviews receive
  no score and choose no gameplay action.
  A no-execution GLM-5V shadow on attempt 5's terminal observation passed the
  final hardened contract on its first response (10,774 prompt and 405
  completion tokens), selected `topic_option_a`, cited immutable `E#`
  references to the exact prior outcome plus real paused/dialog facts, and
  advanced zero ticks because no command was executed. Local verification is
  679 passed, 4 skipped, plus changed-file
  Ruff, compileall, and `git diff --check`. This is candidate evidence, not a
  deployed fix or G7 pass.

- **2026-07-10 — PR #74 deployed; G7 attempt 6: INFRASTRUCTURE-ABORTED FAIL
  at the non-due review boundary.** PR #74 passed CI, merged, and deployed as
  `4e1caf7ad2bca04eaf1a7af1e3558806c8e1a973`. A two-step fresh-seed smoke,
  run `133d8784f35f4a40981ac33fcd5985e8`
  ([replay](https://fortgym.live/r/7KeEU1H-U6JW01ijhbYOFMnVRocx3tNU)),
  completed with two durable factual review rows, 2,000 real ticks, merged-SHA
  provenance, and verified cleanup. Both workshop commands failed honestly on
  `path_cache_stale` then `no_building_material`; no structure or production
  credit is claimed.

  Attempt 6 run `e8d67282a0864b189a4dea6a1bec9d6a`
  ([replay](https://fortgym.live/r/0-WRs-CBBA7BXEx6bw5d8g1AG22irdiL))
  reset the same fresh seed for 450 declared steps but failed closed at step 1
  after only 1,005 ticks. Step 0's initial review was valid; the workshop BUILD
  rejected `path_cache_stale`. On step 1, GLM-5V first omitted the non-due plan
  reason, then corrected to a factual `continue` review that the
  runtime unnecessarily required to be `not_due`. No second gameplay command
  executed. Cleanup completed before failed status. This is an infrastructure
  abort with no policy verdict.

  The follow-up remains inside the agent loop: `not_due` may omit its reason,
  unchanged objectives may voluntarily use `continue`, two bounded review
  corrections are available before fail-closed termination, and an exhausted
  decision persists terminal code `agent_decide_error`. A no-execution shadow
  on attempt 6's exact failed observation passed on the first GLM-5V response
  (6,218 prompt and 435 completion tokens), selected the same legal workshop
  retry, and advanced zero ticks. Follow-up verification is 682 passed, 4
  skipped, with changed-file Ruff, compileall, `git diff --check`, and a focused
  Luna audit reporting no deployment blocker.

- **2026-07-10 — G7 attempt 7: INFRASTRUCTURE-ABORTED FAIL after genuine early
  production progress.** PR #75 passed CI, merged, and deployed as
  `b38c40a255db62ae52c940f81883c8097e7ac273`. Attempt 7 run
  `82e5c2e18f6847f1bc251158e273f53e`
  ([live replay](https://fortgym.live/r/5dk997_GsCm1IJoKzGL_cLy8On3U7Hxz))
  used the pinned GLM-5V OpenRouter policy, memory off, Anthropic disabled, and
  the fresh region3 seed. It failed before gameplay at step 17 after 17 durable
  gameplay rows and 17,064 real ticks. All 17 rows have governed provenance,
  screen text, and gameplay proof, with `gameplay_proof.ok` on 15/17 gameplay
  rows. The gameplay rows used 30 model calls, 274,003 prompt tokens, and
  13,713 completion tokens. Including the three rejected terminal submissions,
  whole-run use was 33 calls, 309,891 prompt tokens, and 15,238 completion
  tokens.

  The policy made genuine but incomplete progress: it chopped trees, completed
  a Carpenter's Workshop and Still through dwarf labor, produced two beds, one
  door, four barrels (finishing with 19), and 50 units of run-scoped drink, with
  no deaths. It had not yet placed furniture, enclosed a room, or built a
  FarmPlot. The deterministic
  G7 verdict is FAIL: duration 17,064/403,200, food production 0, population
  7/15, functional rooms 0/3, installed beds 0/3, and scalar 91.99/150; drink
  production, neglect deaths, evidence, and rubric 80.39 with no blockers pass.
  Because the run ended at the model-review boundary, this is an infrastructure
  abort rather than a long-horizon policy verdict.

  The terminal sequence exposed a concrete retry-context defect. Three model
  submissions were rejected in turn for missing `plan_review.objective`, an
  incorrect `retry_same_action`, and an incorrect previous verdict. The retry
  loop had discarded each rejected payload and returned only the first detected
  error, forcing the model to reconstruct rather than correct its response. The
  candidate keeps the three-submission fail-closed limit and every factual
  validator, but returns the exact rejected payload, all currently detectable
  violations, and the authoritative control values on each correction. A
  no-execution shadow on attempt 7's exact terminal observation passed on its
  first GLM-5V response (9,675 prompt and 512 completion tokens), chose a legal
  FarmPlot at `(91,108,161)`, and advanced zero ticks. Local verification is
  688 passed, 4 skipped, plus changed-file Ruff, compileall, and
  `git diff --check`; deployment proof remains candidate work.

- **2026-07-10 — G7 attempt 8: INFRASTRUCTURE-ABORTED FAIL after real room
  construction work.** PR #77 passed CI, merged, and deployed as
  `9f9cdffc96449ad57f672c037bd12f057b6a4247`; the intermediate PR #76 merge was
  never deployed. A four-step fresh-seed smoke on the deployed SHA completed
  with verified cleanup, repaired a two-error review response in one bounded
  correction, chopped trees, and completed a Carpenter's Workshop through real
  dwarf labor.

  Attempt 8 run `89c7ac68126541888140f6754a50f6f1`
  ([live replay](https://fortgym.live/r/cJWntNq83M0zo-n1NJT6vw7huU8OVur6))
  then launched for 450 steps with the pinned GLM-5V OpenRouter policy, memory
  off, Anthropic disabled, and the fresh region3 seed. It failed before gameplay
  at step 22 after 22 durable gameplay rows and 21,193 real ticks. Evidence is
  complete: all 22 rows have governed provenance, screen text, and gameplay
  proof; `gameplay_proof.ok` is 17/22. Whole-run model use, including the three
  terminal submissions, was 36 calls, 387,446 prompt tokens, and 17,287
  completion tokens.

  The policy made genuine structural progress: it completed a Carpenter's
  Workshop, produced three beds and one door, adapted from rejected workshop
  placement by chopping trees, and completed 24 construction tiles. It detected
  a shrub obstruction, designated it for gathering, recognized a separate
  pebble tile as unusable for the wall helper, revised its objective, and began
  using doors as an alternate enclosure strategy. It still had zero FarmPlots,
  Stills, installed furniture, enclosed spaces, functional rooms, or food/drink
  production; drink consumption was 5 and no dwarf died. Deterministic G7 is
  FAIL: duration 21,193/403,200, population 7/15, rooms 0/3, installed beds 0/3,
  scalar 86.97/150, and both production loops fail; evidence, neglect deaths,
  and rubric 82.80 with no blockers pass.

  The terminal failure was output truncation, not a game-state decision. Each
  of the three GLM-5V responses used exactly the configured 512 completion
  tokens; two ended without `submit_action`, and the third ended with an
  incomplete `plan_review`. A no-execution shadow on the exact failed
  observation with a 1,024-token budget passed on its first response, used 830
  completion tokens, chose a legal bed installation, and advanced zero ticks.
  The follow-up pins only the GLM-5V governed variant to 1,024 tokens; the
  factual contract, correction count, legal action surface, and scoring remain
  unchanged. Local verification is 689 passed, 4 skipped, plus changed-file
  Ruff, compileall, and `git diff --check`.

- **2026-07-10 — G7 attempt 9: INFRASTRUCTURE-ABORTED FAIL after the strongest
  reviewed-plan start.** PR #78 passed CI, merged, and deployed as
  `efea8c86dabf6bae81cd2a8c294c195d6fac1706`. Its four-step fresh-seed smoke
  completed with verified cleanup; two bounded correction responses used 620
  and 669 completion tokens, proving the deployed 1,024-token headroom crossed
  the old ceiling before a legal reviewed workshop action executed.

  Attempt 9 run `4d25c36795eb489faf3c51bec496ae34`
  ([live replay](https://fortgym.live/r/7Ov5ifRPfJ1l2s5mgUI666YmsOlVZYPN))
  launched for 450 steps with pinned GLM-5V, memory off, Anthropic disabled, and
  the fresh region3 seed. It failed before gameplay at step 33 after 33 durable
  gameplay rows and 33,135 real ticks. All rows have governed provenance,
  screen text, and gameplay proof; `gameplay_proof.ok` is 24/33. Whole-run model
  use was 38 calls, 459,547 prompt tokens, and 23,254 completion tokens; the
  maximum response used 951 tokens without truncation.

  This was the strongest reviewed-plan opening: the first ten commands executed
  without a full rejection, completing a Carpenter's Workshop, producing and
  installing one bed, one door, and one table, then starting a wall ring. The
  policy recognized persistent shrub obstructions, gathered and waited, switched
  to an alternate wall route, completed 20 construction tiles, then revised
  toward brewing. It tested multiple Still footprints, designated the only shrub
  across a ten-tile strip, observed the gather stall, and explicitly pivoted
  away from shrub-dependent actions at step 32. It still had zero FarmPlots,
  Stills, enclosed spaces, functional rooms, or food/drink production; drink
  consumption was 7 and no dwarf died.

  Deterministic G7 is FAIL: duration 33,135/403,200, population 7/15, rooms 0/3,
  installed beds 1/3, scalar 81.66/150, and both production loops fail;
  evidence, neglect deaths, and rubric 75.75 with no blockers pass. The terminal
  responses were complete but contradicted their own plan metadata: they changed
  the objective while using `decision=continue`. The unchanged validator
  correctly rejected all three. The correction prompt had stated the rule but
  not the one required decision for the submitted objective identity.

  The follow-up correction context now reports the submitted objective, whether
  it exactly matches the authoritative prior objective, the submitted decision,
  and the required decision (`revise` or `not_due/continue`). It does not select
  an objective or action. A no-execution shadow on attempt 9's exact terminal
  observation then passed after one correction: GLM-5V chose
  `decision=revise`, ordered a chair from the proven workshop, and advanced zero
  ticks. Local verification is 690 passed, 4 skipped, plus changed-file Ruff,
  compileall, and `git diff --check`; deployment proof remains candidate work.

## Reporting format (every gate attempt)

Public URL, run id, commit, score, rubric score + blockers, screen_text count,
gameplay_proof ok-count / step count, and what really changed in-game — the
same fields whether the result is a pass or a failure. Failed attempts get
reported with the same prominence as passes; the Polymarket lesson applies:
winning by swapping in a softer self-graded finish line is losing.
