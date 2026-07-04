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

## Reporting format (every gate attempt)

Public URL, run id, commit, score, rubric score + blockers, screen_text count,
gameplay_proof ok-count / step count, and what really changed in-game — the
same fields whether the result is a pass or a failure. Failed attempts get
reported with the same prominence as passes; the Polymarket lesson applies:
winning by swapping in a softer self-graded finish line is losing.
