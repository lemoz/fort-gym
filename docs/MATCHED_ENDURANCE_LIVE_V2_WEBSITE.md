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

The source and Node contract tests cover all six immutable parents, invalid
identity/counter rejection, file bounds and symlinks, unknown and stale status,
private-field exclusion, unchanged historical routes, and audited-result links.
Synthetic observations in tests are not gameplay evidence.

Delivery remains a GitHub branch/draft PR and a local-only preview. Main merge,
public deployment, browser visual QA, and Year-Two gameplay acceptance are
separate and are not claimed by this change.
