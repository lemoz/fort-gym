# Saved outcomes in the replay player

The existing player previously exposed outcome and evidence links only for the
older exploratory recording carrying legacy `campaign` metadata. The newer
endurance recordings deliberately remained byte-identical to their native
exports, leaving that panel hidden even after a verified Year-Two save.

`web/static/saved-outcomes.json` supplies separate, reviewed projections for
checkpoints 644, 708 and 772. It pins the recording hash, native audit, checkpoint,
model/control/source identity, native clock, cumulative usage, metrics and
published result/review links. Those links are bound to repository revision
`7d60e87c77ba31a4881d69b429c63566a7876ae4` for the first two endpoints. The new
checkpoint772 entry pins `e1b4e76c3f48e87fa3222b4e425ff6fa9d4492c6` and preserves
both earlier entries. The result receipts include actual
fresh reload verification; the separate gameplay reviews support the qualified
operating-but-fragile assessments. Charges remain unreported, not zero.

The panel always describes the end of the selected recorded window, not the
currently scrubbed frame. Recorded actions and their before/after observations
are unchanged. Live and live-history modes hide saved outcomes. Failed metadata
fetches or invalid recording bindings leave playback available with an explicit
unavailable note. Legacy outcome and lost-window recovery behavior is retained.

## Evidence and scope

- Checkpoint644: 423,050 elapsed ticks, 19 living dwarves, 0 recorded deaths,
  66 food and 112 drinks, 19,259,777 returned tokens.
- Checkpoint708: 447,050 elapsed ticks, 18 living dwarves, 1 recorded death,
  75 food and 93 drinks, 20,492,446 returned tokens.
- Checkpoint772: 496,250 elapsed ticks, 18 living dwarves, 1 recorded death,
  134 food and 143 drinks, 22,152,718 returned tokens, and a fifth workshop.
- All retain nine beds and three farms. Assigned worker jobs
  and stock totals are not completed-production measurements or proof of
  indefinite self-sufficiency. These are windows of one campaign, not repeats.

All 34 prior recordings, catalog rows, previews and native source bytes stay
unchanged; the new recording brings the total to 35. Tests pin the old row and
outcome subsets and every recording, check endpoint/clock
bindings and safe links, exercise missing/invalid/delayed metadata, retain
rejected input, and switch between recorded and live views using the real player.
Contract tests do not claim browser visual QA or a new native-game acceptance.

The isolated development worktree is
`fort_gym/artifacts/worktrees/replay-saved-outcomes`, based on public revision
`284fb8206c7685d27aafe8969b303134fc02682a`. This static-only update preserves
the existing hosting architecture. It changes no game controls, model calls,
services, database, credentials, runtime image or main branch. In this background
continuation, browser-only preview and handoff are skipped. Local tests, hosted
CI and public delivery are recorded separately.
