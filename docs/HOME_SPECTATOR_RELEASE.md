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

## Website-wide recording integration

The user approved the follow-up recommendation on September 11: connect the
remaining website sections to current recordings, distinguish historical research
from current experiments, and repair unavailable evidence navigation.

- Homepage cards, latest-recording summary and secondary captured screens now
  read the same published recording catalog. An empty legacy registry can no
  longer strand these sections on Loading or claim there are no recordings.
- Results shows exploratory recording windows separately from the frozen
  historical G7-v3 dataset. No new ranking, score or comparative claim is added.
- The catalog's metadata is derived from the immutable recordings and checked
  against them. Preview images remain exact native screen subsets.
- Findings is explicitly the July 11 research archive. Its original versioned
  manifest is untouched. Replay links appear only for resolving run records;
  unavailable records link instead to the preserved, verified GitHub report.
- Watch navigation opens the current spectator. The historical viewer remains
  compatible with existing run tokens and includes a clear spectator link.
- Protocol pages distinguish exploratory keyboard play from benchmark profile
  acceptance. No protocol or evaluator definition has changed.

This release starts at `b7b21e333` and is static website assets, tests and
documentation only. It does not publish the development campaign dashboard,
restore missing historical run artifacts, connect a live feed, or launch gameplay.
Deploy with pinned fast-forward and rollback, checking public content and all
original recording hashes. Keep API/game processes, database, untracked files,
and the historical findings manifest unchanged. No service restart is needed.

## Recovered Astra recording

The next static release starts at `42c1320ffa6d46e22a472bd55ab434223ef00811`.
It adds `astra-recovery-225-256` as a separate, newest recording: 32 decisions
and 28,345 saved game ticks, resumed from checkpoint 224 and saved through 256.
There are now four recordings containing 320 captured decision frames across
three models. They are exploratory windows, not four independent trials.

The original failed Astra window and both other models remain byte-for-byte
unchanged. The recovery viewer links to the failed window and explains that its
32 unsaved decisions and 422 ticks were lost. All 288 actual model responses
remain counted. No actions were replayed and uninterrupted play is not claimed.
Native screen captures and explicit action intent are exported only after
rechecking the original provider receipts and independent native-save audit.
No private model memory, provider payload, account data or internal reasoning
is published. The final save has not yet passed a separate fresh-load test.

Catalog cards and the worlds gallery expose the new recording. Secondary
homepage illustrations continue to show distinct models, not two Astra windows.
Tests cover recovery metadata rejection, live/replay transitions, the retained
unsaved-tail warning, exact historical hashes and the new saved tick total.
Deploy as a pinned static-only fast-forward. Preserve the API and game process
identities, database and untracked files; no service restart or gameplay launch.

## Live relay without service changes

The next release starts at `41b10423178c69eb02e91f842a842e0c98209aa4`.
The existing public API has no campaign directory configured. When it reports
`not_connected`, the homepage now checks one sanitized static live derivative.
A connected API remains authoritative; an absent, malformed or expired relay
leaves the recorded viewer available. Explicit recording links never auto-switch.

The bounded observer attaches to one already-running owner, pinned by process
start time, command and directory. It reads completed, hash-bound provider
receipts through the frozen observer at `2778519991899ee3360db1caf6daec29721bbc4a`.
It exports only captured screen tiles, chosen keys and explicit action intent.
An action is labeled chosen, not execution-verified. Provider payloads, private
memory, account details and internal reasoning are not exported.

Authenticated SSH replaces only `web/static/live/watch-active.json`, with a
bounded allowlisted payload, atomic write, freshness check and owner-conflict
guard. Observation errors do not imply the game stopped. A confirmed owner exit
ends the relay; a lost observer expires after 30 seconds. Viewers have no input
path to the game. The live file is an ignored, disposable derivative, not a save
or a replacement for immutable native evidence and audited recordings.

Deploy as a pinned fast-forward, preserving all recordings, API/game process
identities, database and unrelated files. No environment change, service restart,
game launch or infrastructure change is involved. Tests cover fallback selection,
privacy filtering, invalid clocks, stale feeds, owner conflicts, PID reuse,
observation failures and bounded terminal delivery failure. Runtime receipts
must distinguish public HTTP/data verification from browser visual QA.

# Checkpoint 416: Year-Two replay (September 11, 2026)

Adds `astra-year-two-257-416` as the newest homepage recording and first Worlds
card: 160 captured screens and audited actions from decisions 257–416. The four
previous files stay byte-identical. The catalog now has five windows and 480
frames across three models; those windows are not five independent trials.

The new endpoint panel stays explicitly separate from the selected frame.
It shows 429,845 saved elapsed ticks (1.066 years), 13 living citizens, zero
recorded deaths, 12 beds, three workshops, one farm, 43 raw-food units and
389 drinks. Qualitative operating-at-endpoint evidence is not a production
rate, stock-accessibility measurement or repeated model ranking.

Continuation metadata retains checkpoint 256, 32 historical lost decisions,
422 lost ticks and all 448 responses / 11,866,456 tokens. Subscription dollar
charges remain unknown, never zero. Links bind the earlier result and later
fresh-reload record to their separate immutable GitHub commits. The original
result is not rewritten to pretend its later reload was already known.

Frames are generated by the existing audited exporter at
`2778519991899ee3360db1caf6daec29721bbc4a`, using the frozen terminal audit
`beb2760bd0516fcb884420c3fd87a3fbcc4fd54d170857e97d7cdb471d27f743`.
The new recording digest is
`79a42eeb8501fe7669f134670e9ce6c947a5628eeb5e94506973f1afa78f83d9`.
Only captured tiles, explicit intent, keys, acceptance, clocks, population
and the public outcome are exported. No agent memory or provider events.

Release scope is static website assets, documentation and tests only. No
database migration, service restart, game command, model call or new VM.
Use the same exact-head, allowlisted fast-forward deployment and verify
public bytes, historical files, read-only database counts and service identities.

## Selected-workshop action labels (September 12, 2026)

This website-only update starts at `e8e3fb9ae284dd562089d434e0b8e88dc2c8b683`.
The live receiver and replay viewer preserve the explicit `WORKSHOP_JOB` route,
item and quantity, instead of dropping it or presenting an empty keyboard action.
The item/quantity constants come unchanged from the frozen controls study at
`422c915d23bf828371be481d3079a23bbb3e9e94`. Only the public projection is ported;
the running study image, native control implementation, prompt and model settings
are not changed by this website release.

The viewer labels a chosen shortcut as unverified, a rejected shortcut as not
queued, and an audited accepted shortcut as queued work, not finished products.
Malformed quantities, unsupported jobs, mixed keyboard/shortcut actions and
private shortcut fields are rejected. Private agent memory is not published.
Keyboard captures and all sixteen existing recordings stay unchanged. Unit and
in-memory interaction fixtures are website contracts, not model results.

Deploy as an exact-head allowlisted fast-forward. The receiver starts a fresh
Python process for each delivery, so its new projection loads without restarting
the API or game service. The configured API still reports `not_connected` and
the homepage uses the existing static relay. Preserve the active relay's run
identity and non-regressing decisions, all recordings, database counts, service
identities and untracked files. Do not inject synthetic shortcut frames into the
public feed. No new host, dependency change or main-branch merge is included.
