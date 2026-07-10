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
- Workshop utility and production credit require
  `getBuildStage() >= getMaxBuildStage()`.
- Created order job IDs are acceptance evidence only. Per-step gameplay proof
  reports the created IDs, their post-tick survivors, and the matching output
  counter separately. Older matching jobs make output attribution ambiguous;
  bounded job-list truncation or a missing output counter is explicit and fails
  closed to unobserved.
- The deterministic rubric keeps manager orders and planned workshops as
  evidence but gives production/coherence credit and clears
  `no_production_surface` only for completed workshop capacity or observed
  production.
- Rubric responsiveness requires an action-specific effect. Acceptance, ticks,
  and concurrent unrelated state changes are uncredited evidence.
- Coefficients and the G7 scalar threshold remain unchanged at 150.

Every score-v5 trace row carries its score version at the record, metrics, and
score-event boundaries. Re-summarization fails closed when rows are
unversioned, empty, malformed, internally inconsistent, non-integer,
mixed-version, or from a different evaluator version; historical runs must use
the summary artifact produced by their original scoring era.

This is a measurement boundary, so v4 and v5 scores are not comparable. Public
leaderboards already partition by score version and seed. Attempt 19 remains a
v4 control; the first matched rerun after deployment is score-v5.
