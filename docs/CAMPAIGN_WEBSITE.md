# Campaign website delivery milestone

## Latest recorded result: liaison-dialog failure

The reasoning-budget campaign now has a later terminal result: 83 committed
decisions, 203,339 elapsed ticks and 931,832 accounted tokens across 84 returned
responses. The model requested WAIT while a liaison dialog blocked simulation;
the harness escalated the blocked advance to failure. Nine citizens were alive.
The original first-segment bundle remains immutable. Its registry pointer is
replaced by the newer result for the same campaign ID, keeping 14 recorded rows.

All checkpoints through 80 and the owned runtime teardown were audited. No full
terminal checkpoint exists, so the current result must show checkpoint false,
not inherit the earlier checkpoint true. Furniture item records remain separate
from installed beds; missing measurements and unassessed collapse remain unknown.
See [the result, costs, recovery limits and next repair](LOCAL_REASONING_DIALOG_RESULT.md).
This data publication preserves the existing website layout. It is not a merge,
deployment or browser acceptance claim. Earlier running-status notes are historical.

## Furniture item records in campaign profiles

The profile reader, bounded public feed and profile view now carry four separate
furniture item-record observations: beds, chairs, doors and tables. They are the
legacy `job_metrics.goods` counts of item records in play, not installed totals,
complete inventory, newly produced items, ownership or accessibility. Existing
installed-bed metrics are unchanged. The view shows start/latest/change when
available and preserves unknowns, including a missing terminal observation.
Old published bundles are not rewritten or backfilled with assumed counts.

Sample coverage only says whether each recorded boundary supplied a count. It
does not establish scan completeness. These records do not change production or
consumption verdicts, campaign success, or model rankings.

A read-only projection of the retained first reasoning-budget segment correctly
reported bed item records 0 to 1 with installed beds remaining 0. The source trace
SHA-256 remained
`1feea15774dbceb0bac6fa1c8221fb245e9d77f017c8b87cfd3def019fce57e5`.
This was an offline reporting check, not a new game experiment or replacement
of the original published terminal result. The currently running native source
at `de69c7a467eb0b00becfef03329bac9f58690e35` is unchanged.

The existing FastAPI/static architecture and layout are preserved under the
website-building workflow. Background work skips browser handoff and visual QA;
the standing no-deploy boundary means this source update is not a live release.

Validation: 114 focused profile/feed/catalog/HTTP/captured-data checks passed.
The full local run reported 1,849 passed, 10 skipped and four failures: three
historical-capture equality assertions needed the explicit additive-field
compatibility checks now included in the passing focused run; the loopback-port
test passed separately with local socket access. This is a full run plus
targeted corrections, not a fresh all-green full suite. Changed-file lint,
formatting and JavaScript syntax checks pass. Whole-tree debt remains 10 Ruff
findings and 464 mypy errors in 26 files, with none reported in the three changed
production Python modules.

## Installed furniture and inventory observations

The campaign table and profile now label `completed_beds` as **Installed beds**.
That field counts completed placed furniture, not bed items in inventory. The
saved checkpoint40 observation recorded 11 bed item records and three chair
item records, but no installed beds or chairs. The page links its immutable
source-hashed observation and does not turn that running checkpoint into a
terminal campaign row. The original thirteen older results and first-segment
terminal bundle are unchanged; there are still fourteen recorded campaigns.

The legacy goods scan does not report scan completeness or production
attribution. The observed inventory records are shown with those limits, not
promoted to a complete stock audit, production flow or functioning-fortress
claim. No gameplay setting, native source, checkpoint or model is changed.
Browser preview/visual QA and deployment are not performed in this background
source-only update; the existing FastAPI/static layout is preserved.

Validation: 104 focused website checks passed (103 in the integration checkout),
including the rendered-label test double, HTTP checkpoint note, immutable source
link and evidence/placement distinction. Changed-file Ruff/Black, JavaScript
syntax and diff checks passed. Existing whole-tree lint/type debt is unchanged.

## Latest recorded result, September 7

The first reasoning-budget segment is now registered as the fourteenth recorded
campaign: 32 commands, 76,000 actual ticks, seven living citizens, one completed
workshop, drink inventory 60 to 39, and 325,234 accounted tokens. Its checkpoint
and outer-resource teardown were independently verified. See the
[result and limitations](LOCAL_REASONING_SEGMENT1_RESULT.md).

The historical three-command capture described below is unchanged. HTTP tests
now verify that it cannot roll back this campaign's newer terminal record or
create a duplicate row. The separate original-feed and helper tests retain its
timestamp and unknown metrics. No live game, browser or deployment is started
by serving these versioned records.

The result and HTTP regression are pushed in PR #133 at
`b896ee79a834ca6b673d16a0b087747c756e5568`.
[Exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34080674648)
passed. The local website suite reported 1,841 passed and 10 skipped; its one
sandbox-blocked socket test passed separately on the same head with loopback
access. There were 103 focused website checks and 102 in this integration
checkout. Merge, browser visual acceptance and production deployment remain
separate, unclaimed steps.

## Current real-data compatibility check, September 7

The optional active feed now recognizes the published reasoning-budget condition
and links to its immutable configuration at `ebf470d8364bf326cacd7b9985e6f5438d6d4f49`
only when the canonical configuration SHA-256 matches
`13ec2fdaad2b5e63b6f1e8fc4d57feefd3f66cd307104267d7bc06743cdbb490`.
The remote file and its digest were read back before adding the link.

A captured public report from the actual native run at `de69c7a46` is retained
as a regression fixture, bound to the original serialized snapshot digest. It
reported three committed commands, 5,500 elapsed ticks and 22,751 accounted
tokens at `2026-09-07T02:16:25.623321+00:00`. This is a historical running-state
observation, not a terminal result or a live connection. It is not registered
among the website's thirteen published terminal records.

HTTP tests combine this report with the thirteen recorded rows, preserve its
timestamp and unknown values, and verify that it becomes stale without turning
into a game loss. JavaScript rendering-helper tests check the exact condition
link, reported-running/stale labels, zero model API charge and unknown operating
costs. This is real-data route/formatting coverage, not browser visual acceptance.

The frozen native producer omits population and drink-stock values in this
running report. This website branch's newer shared metrics reader supports v2
observations in both terminal reports and `CampaignFeed.progress`. Separate
synthetic publisher-to-HTTP tests verify population and drink counts, confirmed
zero values, and loss of incomplete or missing observations without carrying
forward older counts. These tests do not replace the actual captured report or
claim that the frozen producer has been upgraded. The website preserves its
unknowns and does not infer them from another campaign. Future execution must
include the newer reader to emit these values; the active game's source and
condition were not changed.
No website server, browser, hosted Site, production deployment or merge was
started by this check. The existing FastAPI/static implementation is preserved.

## Original separate website milestone

This change delivers the read-only campaign tracking surface independently of
the native campaign implementation in [PR #125](https://github.com/lemoz/fort-gym/pull/125).
It is based directly on main at `82ee3e07859b2813fc4643d02aa034daecea6b18`.
It does not bring the M1b supervisor, VM tooling, campaign runner, model transports,
or calibration changes into main.

## Website behavior

- `/campaigns` presents recorded native attempts, declared experiment conditions,
  action outcomes, sampled fortress metrics, progress, and usage limitations.
- `/public/campaign-feed` includes ten explicitly published terminal campaign
  records. An optional `FORT_GYM_PUBLIC_CAMPAIGN_DIR` connects an existing dedicated
  public feed directory. The API reads and projects that feed; it never starts a
  game, model, process, or VM. With no directory configured, recorded results remain
  available and the response reports that live tracking is not connected.
- `/public/campaign-experiments` exposes the explicitly published development
  probe and its declared model coverage. An unrun model is not a failed model.
- Landing and results navigation link to Campaigns. Existing FastAPI and static
  website architecture is preserved; no hosting migration is introduced.

The active feed must use its dedicated public-directory marker and bounded JSON
snapshots. Do not point the setting at a private run directory. The reader rejects
symlinks and unavailable configured sources, reconstructs allowed nested fields,
and returns a generic HTTP 503 instead of leaking private paths or showing an
empty successful result. Missing measurements remain unknown, zero remains zero,
and stale observations do not claim that a game is currently running or stopped.

## Evidence and provenance

The published evidence files and read-only modules were extracted from integration
revision `60fd08415b10adfe52a0d275c826669dad843937`. The website's source and condition
links retain immutable revisions. Each result retains its original execution
revision and condition fingerprint: the website delivery commit did not execute
those experiments. The recent local-model condition links also have explicit
filename mappings and reject unknown conditions or invalid revision identifiers.

Only explicitly selected public evidence is checked in. Native saves, model
weights, raw prompts, private reasoning, credentials, and private run artifacts
are not part of this milestone. The known timeout is published as an incomplete
attempt with missing returned usage, not hidden or converted into a game loss.

These are development observations, not a model ranking or year-two success.
Three models have early matched attempts, but repeated comparable evaluation is
not yet complete. The short thinking-enabled model produced observed wood growth;
that alone does not establish a functioning fortress. No recorded attempt here
has completed one full elapsed game year. A zero metered-provider charge for local
inference does not imply zero infrastructure, electricity, or hardware cost.

## Validation and release boundary

Local validation on September 6, 2026, with model-provider keys removed from the
test environment, dotenv disabled, and the native adapter disabled:

- Full pytest suite: **1,064 passed, 5 skipped**, with loopback socket access for
  the existing quickstart port-selection test.
- Focused campaign website suite: **35 passed**. This includes HTTP routes,
  evidence selection, unknown-value handling, failure responses, bounded public
  projections, symlink rejection, immutable configuration links, and frontend DOM
  test doubles.
- Targeted project-environment Ruff 0.15.21 and mypy checks passed for all six added Python modules. Targeted
  Ruff also passed for the new website tests; JavaScript syntax checks passed.
- Repository-wide Ruff reports ten findings in unchanged legacy files.
  Repository-wide mypy reports 475 errors across 28 files. Those existing-area
  findings are not silently fixed or represented as a clean repository-wide check.

Run Ruff through the project's Python environment (`python -m ruff`), not an
unrelated global executable. The separately installed Ruff 0.16.1 enables additional
default rules and reports more style findings; it is not the version used for the
ten-finding result above. No rule suppressions or exception-contract changes were
introduced to manufacture a clean global-linter result.

This background goal run did not perform browser visual acceptance or production
deployment. Local source tests, remote CI, merge, deployment, and deployed website
acceptance are separate proof steps. This branch is a bounded delivery candidate;
the overall autonomous year-two and cross-model evaluation goal remains open.

Source review checked the exact main-based diff, read-only route additions,
dedicated-feed and public-record boundaries, data rendered as text, immutable
condition links, source-file equality with the published integration revision,
and isolation from existing runtime behavior. Review corrected the historical
timeout heading to "Published result" so an active newer campaign does not make
the static page falsely label the timeout as the latest attempt. This is an
implementer review with regression coverage, not an independent peer approval.
