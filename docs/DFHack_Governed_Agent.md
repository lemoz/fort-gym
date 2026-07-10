# DFHack-Governed Fortress Agent

## Goal

The governed path makes DFHack the command transport, not a cheat engine. The
agent issues bounded overseer commands that a human player could issue through
the UI, then the simulation must advance and produce observable state changes.
The UI remains useful for replay and inspection, but it is no longer the primary
control surface for this path.

## Legal Gameplay Boundary

Legal actions:

- Designate bounded dig/channel work, including legal floor-channel access.
- Designate bounded tree-chopping and plant-gathering work.
- Place bounded workshops, farm plots, furniture, walls, and floors that create
  normal construction/jobs.
- Queue bounded manager or workshop production orders and unsuspend jobs.
- Select only crops offered by a completed underground farm plot for each
  requested season, and toggle one whitelisted labor on one citizen.
- Wait for a chosen number of ticks so dwarves can perform the work.
- Send one semantic confirm/cancel/cursor input to an attested paused dialog,
  plus the view-specific topic-meeting finish option proven by attempt 4.

Illegal actions:

- Directly create items, material, food, drink, wealth, or dwarves.
- Instantly complete mining, construction, hauling, or production.
- Teleport units, mutate stocks, or write score state.
- Give mechanical score credit to `dfhack_assisted` debug helpers.

`hook/complete_dig_rect.lua` stays available only for explicit harness debugging.
It must not be treated as legal fortress gameplay.

## Governed Models

Governed mode is gated by model name: `GOVERNED_DFHACK_MODELS` in
`fort_gym/bench/run/model_modes.py`. The runner marks a governed model's structured
`DIG`, `BUILD`, `ORDER`, `UNSUSPEND`, `FARM`, `LABOR`, `WAIT`, and `INTERACT`
actions as `execute.provenance = "dfhack_governed"`. World actions may carry
`gameplay_progress_eligible = true` only through observed state; `INTERACT` is
always false and uses `score_provenance = "dfhack_governed_interaction_only"`.
Other governed per-step metrics carry
`score_provenance = "dfhack_governed_observed_state_action_owned_progress"`
and `score_progress_provenance = "dfhack_governed_action_owned_progress_v2"`.
Older
structured DFHack agents still get `dfhack_assisted` progress zeroed for scalar
scoring (and one accepted assisted action blocks scoreable elapsed time for the
rest of that run).

### `dfhack-governed-scripted` (substrate validation)

The first governed model. It is intentionally scripted (a Python state machine
over the `work` metrics, no LLM) so the runner and evaluator could prove the
command substrate before an LLM policy used the same action surface. Its plan:

1. Dig the starter room.
2. Dig the connector east of the starter room.
3. Dig the workshop room.
4. Place a carpenter workshop in the completed workshop room.
5. Queue small manager orders (bed, door, table, chair, barrel, bin).
6. Wait while dwarves resolve queued jobs.

The substrate is validated: live runs show workshop placement with a real
material item, real created job IDs, tick advancement, and in-game date
progression, all recorded with per-step CopyScreen frames.

### `dfhack-governed-llm` (LLM policy)

The LLM policy on the same legal action surface (`agent/governed_llm.py`).
It uses OpenRouter chat completions (default `z-ai/glm-5.2`, override with
`OPENROUTER_MODEL`) with a single `submit_action` tool restricted to
`DIG`/`BUILD`/`ORDER`/`UNSUSPEND`/`FARM`/`LABOR`/`WAIT`/`INTERACT`. Per step it receives:

- the encoded observation (including the recorded CopyScreen text, a fort
  minimap where `.` is stable floor, `i` is frozen liquid, `,` is a gatherable
  shrub, `s` is a sapling, `p` is loose rock, and `<`/`>`/`X`/`^` are completed
  stairs/ramps, plus bounded access-centered lower-level maps, citizen
  positions, and `work` metrics),
- its own memory context from `MemoryManager` (recent steps, summary, POIs,
  failed attempts, current gameplay plan).

Governed runs use the global-only work observation mode. It preserves factual
job, workshop, labor, and manager-order counters but never invokes or emits the
legacy starter rectangle, two-room plan, connector, workshop-room footprint, or
runner-selected workshop candidate. Every gameplay coordinate comes from the
model's interpretation of observed game state.

The agent maintains its plan and POIs across steps via the action's
`plan_step`/`memory_update` fields and the executed-result feedback loop. The
candidate review contract also carries `last_action_review` and structured
`plan_review` in bounded run-local history, so memory-persistence-off runs can
audit objective continuity. Initial, five-action, two-no-progress, and partial-
mutation checkpoints are factual review triggers only: the model establishes,
continues, or revises its own objective and selects observation evidence. A
voluntary `continue` when no checkpoint is due does not reset the five-action
cadence. Pending order jobs trigger a partial review, while two action-specific
no-progress outcomes trigger a stall review. Review metadata earns no score and
never selects or vetoes a gameplay action. The
evidence validator accepts only immutable `E#` references to a runner-authored
factual allowlist; model-authored history cannot manufacture a new evidence
line. Plan reviews select two IDs backed by distinct lines. A stable type+params
fingerprint makes `retry_same_action` factual, and governed mode retains at
least six action outcomes even if the display-history limit is configured lower.
When no checkpoint is due, the model may submit a minimal `not_due` review or a
voluntary `continue`; only a due `continue`, an establishment, or a revision is
a substantive review.

The agent holds no gameplay heuristics — the model plus the loop must solve
gameplay. Legacy direct callers still degrade malformed model output to a
recorded `WAIT`; governed runs carrying `AGENT PLAN CONTROL` permit up to two
review-contract corrections and then fail before execution instead of advancing
hidden fallback ticks. OpenRouter transport gets three bounded attempts by default,
all within the same paused decision and before any gameplay command or tick.

## Replay Evidence

Every governed step records into `trace.jsonl`:

- `screen_text` — a real CopyScreen frame at that step (the replay UI's
  "DF Screen" mode). This is the recorded gameplay evidence.
- `map_snapshot` — a derived DFHack tile read, shown only under the explicit
  "Map Inspect" label. The general display window is not gameplay proof by
  itself. For model-authored `dig`/`channel`, an additional exact-footprint
  before/immediately-after-paused-write diff establishes run ownership before
  ticks can clear a designation into an assigned job. Designations are audit
  facts and only later native completion of owned tiles feeds scalar
  work/completion. Every unfinished owned coordinate is monitored independently
  of the display/camera window. A completion outside that window is persisted as
  `gameplay_proof.owned_completion_observation` with the model-authored
  coordinate and kind, so scalar progress never outruns its trace evidence.
- `owned_building_completion_observation` — exact building IDs claimed from
  accepted model-authored BUILD results and later matched to native completed
  stages and authored kinds in `job_metrics`. Stage reads must explicitly
  succeed with numeric values and `max_stage > 0`; failed `0/0` reads are not
  completion. Unmatched global workshops, rooms, constructions,
  furniture, goods, and production remain audit-only and cannot raise governed
  utility, production, complexity, or unlock duration.
- `gameplay_proof` — a per-step evidence object containing before/after map
  diffs, productive state deltas, bounded helper facts, and the exact action
  footprint delta. It separates command acceptance, concurrent world changes,
  and action-specific effects. `created_job_ids` prove only that DF accepted an
  order. An order is `pending` while one of those IDs remains in the live job
  list, `progressed` only when its matching output counter moves, and
  `no_progress` when the IDs vanish without output. Output is action-attributed
  only when the pre-action job inventory is complete and contains no older
  matching job; otherwise it is recorded as `unattributed_output`. Truncated
  job-ID evidence produces an unobserved verdict instead of a false failure.
  An unrelated wall or stock change cannot ratify that order. Final
  `gameplay_progress_eligible` fields are set from this post-tick proof, never
  from action type alone.
- `execute.provenance` / `metrics.score_provenance` — the legality tags above.
  Re-summarization rejects any governed score-v5 row that lacks the action-owned
  progress marker or a boolean duration gate instead of falling back to global
  counters. The governed rubric consumes those owned progress fields too;
  global rooms/constructions cannot clear blockers until exact ownership is
  implemented.
- Governed runs cannot be advanced through the administrative `/step` route.
  It returns HTTP 409 before opening a client so rollback, ownership, duration,
  and trace semantics cannot be bypassed by a second control loop.
- `interaction` — for `INTERACT`, the semantic operation, fixed key, pause and
  viewscreen types, and before/after CopyScreen hashes. It is audit evidence,
  never world-progress evidence.
- `AGENT PLAN CONTROL` / action history — previous factual outcome, stable
  type+params fingerprint, objective, plan step, and review checkpoint. Visible
  topic options map to one bounded `OPTION1`-`OPTION8` input only when the
  corresponding `a -` through `h -` line is present on
  `viewscreen_topicmeetingst`.
- `survival` — run-scoped item-created and eat/drink-history counters plus raw
  death facts; missing or incomplete capture fails G7 evidence closed.

The governed LLM agent also persists its memory (POIs, failed attempts, plan,
summary — not step records) across runs to
`$ARTIFACTS_DIR/governed_llm_memory.json`; override with
`FORT_GYM_GOVERNED_MEMORY_PATH` (set to `off` to disable). Memory is only
meaningful while the seed save stays the same — delete the file when changing
seeds.

Success gates for this whole effort live in `docs/WDSLL.md`.

Governed mode performs no target discovery and supplies no starter, workshop,
room, tree-cluster, or access coordinates. The model chooses every coordinate
from recorded observation evidence. Read-only screen capture does not move the
DF camera/cursor. Traces recorded before screen capture existed show "No
Recorded DF Screen Frame" in replay instead of pretending a derived view is
gameplay. Structured BUILD hooks validate the model's chosen footprint and
reject `FROZEN_LIQUID`, which can look floor-shaped while frozen but thaw into
open air.

## Rubric Evaluation

The scalar score remains useful telemetry, but it is not enough. `summary.json`
includes a deterministic (non-LLM) `rubric` object computed over the last 100
trace rows with dimensions for:

- survival management
- shelter layout
- production economy
- fortress breadth
- responsiveness
- plan coherence
- anti-repetition
- legal evidence

The rubric returns a 0-100 score, per-dimension evidence, blockers, and a short
critique. It is designed to flag exactly the failure mode where score rises while
the fort stays narrow, repetitive, or non-legal.
Queue depth and incomplete workshops remain visible in rubric evidence but earn
no production/coherence points and cannot clear `no_production_surface`.
Responsiveness likewise requires an observed action-specific effect; accepted
commands and elapsed ticks remain evidence but earn no points by themselves.

## Known Limits and Next Steps

Current structural limits of the governed surface:

- No stockpile/zone/assignment/alert helpers are in the governed action tuple.
- Dialog input is deliberately narrow: paused allowlisted viewscreens only,
  eight operations per modal episode, and three unchanged screens terminate.
  `finish_topic_meeting` sends one `OPTION1` only on
  `viewscreen_topicmeetingst`; arbitrary letter keys remain unavailable.
- There is no general stair-designation command. The model can create and
  inspect one-level vertical access with `channel`; the latest accepted channel
  receives action-focused upper/lower maps and local connectivity evidence.
- Workshop placement is limited to Carpenter and Still; orders cover seven
  whitelisted goods/reactions. Mason, smith, kitchen, trade, military, and
  healthcare control are not exposed.
- `hook/work_metrics.lua` still contains legacy `two_room_workshop` plan fields;
  gate structure is measured separately by plan-agnostic `fort_metrics.lua`.
- Memory can persist across runs, but production experiments currently disable
  it because the G5 ablation found the current memory design counterproductive.
- Governed `gameplay_proof` combines bounded tile diffs and observed state
  deltas, but reports them separately from action-specific effect. It reports
  no progress for accepted actions whose intended effect is unobserved,
  including an order whose jobs vanish without output and dialog-only
  `INTERACT`.

The next action helpers should be added only after their legal semantics are
clear:

- bounded stockpile creation
- bounded activity zone creation
- broader administrative controls beyond the existing labor toggle
- richer read-only metadata for messages, announcements, incidents, and POIs

Each helper needs tests showing that it rejects unbounded or illegal state
mutation, and live traces showing that progress came from simulation resolution.
