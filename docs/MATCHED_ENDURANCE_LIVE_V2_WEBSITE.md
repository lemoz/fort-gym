# Current longer-window campaign observations

The campaign page separates the active decision-128-to-256 observation from the
six independently audited decision-128 results. The previous 64-to-128 observer
remains available under an Earlier window section; its endpoint and script are
unchanged.

`GET /public/keyboard-cohort-endurance-v2-active` reads the separate bounded
`keyboard-cohort-endurance-v2-active.json` derivative in the existing public
campaign directory. It performs no model, game, VM, database or spending action.
The projection requires the exact own-save parent, model, attempt, native source,
controller, courier and pushed continuation declaration. All six derived window
hashes match the declarations at revision
`4590fc1828365c44c9a4d3be728b4168ded5c514`.

The page displays saved starting ticks separately from new observed ticks, which
are only a lower bound from later feedback. Returned responses and tokens have
separate window and cumulative counters. A live observation never verifies a
new checkpoint, and unreported dollar charges remain unknown rather than zero.
Observations expire after 30 seconds, including when refresh fails. An audited
result link appears only when the corresponding window is registered in the
versioned result chain; a later result does not change the original baseline.

The published Astra attempt 1 decision-256 result now supplies this audited link.
Its stopped observer still reports a stale lower bound of 133,400 cumulative
ticks, while the audited saved result records 135,400. The last action's 2,000
ticks were not available through a subsequent model request. Publication does not
rewrite that observation, set its new-save flag, or move its 51,400-tick /
4,544,237-token decision-128 starting baseline. The saved result is authoritative
for the final outcome; the old live counts remain provisional.

The source and Node contract tests cover all six immutable parents, invalid
identity/counter rejection, file bounds and symlinks, unknown and stale status,
private-field exclusion, unchanged historical routes, and audited-result links.
Synthetic observations in tests are not gameplay evidence.

Delivery remains a GitHub branch/draft PR and a local-only preview. Main merge,
public deployment, browser visual QA, and Year-Two gameplay acceptance are
separate and are not claimed by this change.
