# Campaign website delivery milestone

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
