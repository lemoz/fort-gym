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

### G7 — The fort lives: a self-sufficient year (PROPOSED 2026-07-06, not yet ratified)
Status: operator direction approved; gate NOT active until (a) score-v3 is
ratified and landed (docs/score_v3_proposal.md), (b) G6 has been attempted,
and (c) the survival primitives exist — each a bounded, player-parity,
operator-approved action-surface addition in the tradition of furniture,
Wall/Floor, and UNSUSPEND: farm-plot placement, plant-gathering
designation, a Still workshop with brew orders, and (optional, decide at
implementation) kitchen/meal orders.

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
  visible). The prepared correction: UNSUSPEND, a bounded player-parity
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

## Reporting format (every gate attempt)

Public URL, run id, commit, score, rubric score + blockers, screen_text count,
gameplay_proof ok-count / step count, and what really changed in-game — the
same fields whether the result is a pass or a failure. Failed attempts get
reported with the same prominence as passes; the Polymarket lesson applies:
winning by swapping in a softer self-graded finish line is losing.
