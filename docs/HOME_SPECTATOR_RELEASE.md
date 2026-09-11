# Website-only spectator release

User approved publishing the homepage on September 11, 2026. This release starts
at the observed public server revision `47c035f117f2a8663c2b276160d546c49f47a5da`.
It does not deploy the broader unpublished campaign/runtime stack.

The player, compressed recordings and Node interaction tests are from reviewed
PR #165, head `2778519991899ee3360db1caf6daec29721bbc4a` (remote CI passed).
Three recordings cover 288 decisions: Astra 97–256, Sol r1 65–128, Terra r2
65–128. Astra 225–256 is labeled as an unsaved observed tail after checkpoint 224.
Screens are native pre-action tile captures; action intents are explicit model
outputs, not internal reasoning; population and elapsed ticks are after-action
data. Rejected input stays rejected. Different control conditions are not a ranking.

Only the following production surfaces change:

- The homepage gains the tested viewer, keeping its existing layout elsewhere.
- Links use the existing `/worlds` page because the campaign-page release is not
  part of this narrow deployment.
- Static player modules, style and three allowlisted recordings are added.
- `/public/watch-active` reads a bounded public derivative from the optional
  `FORT_GYM_PUBLIC_CAMPAIGN_DIR` environment setting. No setting or feed is
  installed by this release, so it initially returns `not_connected`.
- The endpoint retains the tested public projection but omits the exporter and
  native-model receipt helpers; neither a model nor DFHack is imported or called.

No game services, harness code, model settings, credentials, run database, saved
games, server-local files, dependency versions or infrastructure configuration are
changed. The existing public server's DFHack service was already active; it must
not be restarted or stopped as part of this website release. The local campaign
VM remains stopped. The optional broadcasting observer from #165 stays in the
development lane until a future eligible run verifies it.

Deploy the pinned website-only branch by fast-forwarding the existing clean
tracked checkout and restarting only `fort-gym-api`. Retain the previous commit
for rollback; do not use hard reset, clean, provisioning or VM-deploy recipes.
Before restart, verify there are no active API runs. The server has limited free
disk space; transfer only the narrow branch and do not copy local experiment data.

Verify public health, homepage marker, script/style MIME types, recording content
hashes, no-connected-broadcast status and unchanged DFHack service identity after
release. HTTP/contract verification is distinct from browser visual QA or native
live-session acceptance. Preserve a scoped release receipt alongside these docs.

## Runs-page correction

The first homepage release left `/worlds` connected only to the empty legacy
`/public/worlds` registry. A successful HTTP response was not evidence that
visitors could find the newly published recordings.

This correction gives `/worlds` three permanent recording cards and small native
screen previews. The previews are exact first-frame subsets of the existing
hash-verified recordings, not illustrative images. Links select the matching
recording in the homepage player, even when a live feed is available. The
original searchable archive remains below, with an explicit separate empty
state; an empty or failing registry cannot blank the recent recordings.

The original 288 frames and save boundaries are unchanged. Tests cover preview
provenance, matching links, CP437 rendering, failed previews, empty/unavailable
registry responses and deep-link selection without automatic live takeover.
Future recording publications must update the gallery and preview subset with
the catalog; the catalog-consistency test prevents incomplete releases.

This follow-up changes static website assets, tests and this document only.
Fast-forward the pinned release branch from `84bdc44`, verify actual gallery
content and asset hashes over public HTTPS, and preserve both API and game
process identities. No service restart or database mutation is necessary.
