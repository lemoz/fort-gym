# score-v5 action-effect truth boundary

## Why the version changed

G7 attempt 19 exposed two remaining scalar paths where command activity could
look like completed fortress progress:

- an accepted `ORDER` or workshop `BUILD` received immediate
  `utility_action_progress`, before any item or completed workshop existed;
- `hook/work_metrics.lua` called a Carpenter workshop usable when it had a task
  job, rather than when its construction stage was complete.

The trace demonstrated the failure directly: repeated brew jobs were linked,
then disappeared with no additional drink production, while unrelated work and
queue churn moved the displayed score.

## score-v5 semantics

- `utility_action_progress` remains in trace/summary schemas for compatibility
  but always pays zero.
- Governed workshop utility and production credit require both the exact
  `building_id` returned by the model-authored BUILD and a later
  `job_metrics.workshops[]` row for that same ID and authored workshop kind with
  `stage_read_ok=true`, numeric native stage values, `max_stage > 0`, and
  `getBuildStage() >= getMaxBuildStage()`. A failed read, `0/0` default, or
  globally completed workshop that
  is not in the run's ownership ledger is audit telemetry and earns zero.
- Created order job IDs and global item/drink deltas are audit evidence only.
  Per-step gameplay proof
  reports the created IDs, their post-tick survivors, and the matching output
  counter separately. Older matching jobs make output attribution ambiguous;
  bounded job-list truncation or a missing output counter is explicit and fails
  closed to unobserved. ORDER output does not currently feed the governed
  scalar or duration gate because DF exposes no exact output-to-job ownership
  link on this surface.
- The deterministic rubric keeps manager orders and planned workshops as
  evidence but gives production/coherence credit and clears
  `no_production_surface` only for completed workshop capacity or observed
  production.
- Rubric responsiveness requires an action-specific effect. Acceptance, ticks,
  and concurrent unrelated state changes are uncredited evidence.
- Governed work/completion uses an action-owned excavation ledger. The exact
  model-authored `dig`/`channel` footprint is snapshotted before and immediately
  after the paused native write, before any requested ticks can convert the
  designation into a job. A new designation establishes ownership but pays zero scalar credit;
  work/completion rises only when an owned tile is observed as a stable native
  dig floor or channel ramp top, including completion during later `WAIT`
  turns and outside the current camera window. Global active-job and legacy
  target counters remain observability only. Newly completed owned coordinates
  are recorded in `gameplay_proof.owned_completion_observation`; an off-camera
  completion therefore has explicit trace evidence instead of relying on a
  display-window diff.
- Governed non-excavation scoring uses a second exact-ID ledger. Carpenter
  workshops, Stills, and FarmPlots are claimed only from accepted BUILD results
  that return `ok=true` and a concrete `building_id`; completion is recognized
  only when native job metrics report that same ID and kind built. Completed owned
  Carpenter workshops feed the existing utility/production capacity terms.
  Stills and FarmPlots can unlock duration as durable owned structures but do
  not receive Carpenter-only scalar capacity credit. Global goods, rooms,
  enclosed spaces, constructions, furniture counts, and unmatched buildings
  remain separately recorded as `observed_global_*` facts and earn zero
  governed utility/production/complexity until exact causal evidence exists.
- Governed scoreable duration stays blocked until the run has a durable effect:
  an owned native excavation completion, an exact-ID owned completed structure,
  or a native crop assignment on a completed farm. A
  queued placement, designation, labor toggle,
  unsuspend, accepted order, global output delta, or unrelated `WAIT` change
  cannot unlock elapsed
  score. This prevents idle or command-only fresh-seed activity from
  manufacturing a survival trajectory.
- Governed models have one scoring/control path. The administrative `/step`
  endpoint rejects them with HTTP 409 before constructing a DFHack client;
  only the serialized runner may mutate, advance, trace, or score such a run.
- Any explicit rollback failure is a zero-tick terminal. Helpers emit
  `rollback_verified`; the runner also treats top-level or per-target
  `error=rollback_failed` as unverified so a missing flag cannot bypass
  quarantine.
- Coefficients and the G7 scalar threshold remain unchanged at 150.

Every score-v5 trace row carries its score version at the record, metrics, and
score-event boundaries. Re-summarization fails closed when rows are
unversioned, empty, malformed, internally inconsistent, non-integer,
mixed-version, or from a different evaluator version; historical runs must use
the summary artifact produced by their original scoring era. A governed row
without `dfhack_governed_action_owned_progress_v2` is rejected rather than
falling back to raw global work, completion, utility, production, or complexity
values. Every governed row must also carry an actual boolean
`score_duration_blocked`; missing strings, numbers, or nulls are rejected rather
than interpreted as unblocked.

The deterministic rubric follows the same marker. Governed dimensions and
blockers consume only `governed_owned_*` progress and exact completed-Carpenter
evidence. Global rooms, constructions, workshops, goods, and fort-space values
remain audit telemetry; they cannot pay or clear blockers. Because exact
construction/room ownership is not yet implemented, governed complexity and
room credit intentionally fail closed to zero. A generic world change during
`WAIT` is concurrent evidence only; exact owned completions are promoted later
by the runner.

This is a measurement boundary, so v4 and v5 scores are not comparable. Public
leaderboards already partition by score version and seed. Attempt 19 remains a
v4 control. Production remains score-v4 while this candidate is reviewed; no
local or public v5 artifact existed while the boundary was finalized. The first
matched rerun after deployment will be score-v5.
