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

## Earlier keyboard controls replay (September 12, 2026)

Publish the audited `controls-p1-keyboard-1-128` recording unchanged, from frozen
v1 source `422c915d23bf828371be481d3079a23bbb3e9e94`. Its SHA-256 is
`db74af4eb5a3c13297c363aecb9cfc0dad028f708edfdb9db9d7cd353a81e6b8`, bound to
audit `9202a9fd406b8d5835fd59a0757478a73ab73faf4e0323b7c3c9885314e009cc`.
The catalog adds a `(v1)` display annotation without changing the recording's
original title or bytes. This is not a corrected-v2 sample or a model ranking.

The 128 captured decisions cover 83,800 elapsed game ticks and a verified
own-save continuation at decision 64. The final save exists but has not had a
separate fresh-reload check. Endpoint measurements are seven dwarves, no recorded
deaths, four installed beds, three workshops, one farm, 58 food and 111 drinks.
Stocks alone do not establish sustainability or a full elapsed year.

Add the replay to the shared catalog, exact captured preview, and Runs gallery.
The homepage and Results consume that catalog without new client code. Preserve
all sixteen earlier recordings and the current v2 live feed. The total becomes
17 recording windows and 1,252 frames. Publish only the exact tested static
assets, tests and documentation; no model/game change, service restart, database
mutation, dependency change, new host or main merge.

## Corrected shortcuts controls replay (September 12, 2026)

Start from public revision `c3278d47427902034622d5a330a5bfa823d7947a`.
Add the audited `controls-v2-p1-shortcuts-1-128` recording unchanged, from
frozen source `5ddf1e6718dab2e8351e8dc24a2afe5071cd2592`. Replay SHA-256:
`9063c997563bd5c00eb3726acfff77088a50877dd66aeb12a95662b46c62d17b`.
Its two-window audit SHA-256 is
`628112a07c1181ce5fca4f94aa706c59579b60d8c867c1ae45983b3bcf179cff`.

The final save retains 68,200 elapsed ticks, seven living dwarves, zero recorded
deaths, seven beds, two workshops, one farm, 39 food and 115 drinks. The original
64-decision save was freshly reloaded for the continuation; the final save has
not had a separate fresh reload. Twelve accepted workshop shortcuts queued 36
jobs, not 36 completed products. The paired keyboard result, sustained production
and a comparative conclusion remain unproven. The actual run used 3,772,495
returned tokens; subscription dollar charges are unreported.

Preserve all seventeen prior recordings and previews, including the original
v1 keyboard bytes and display label. The new total is eighteen windows and
1,380 captured frames. The homepage and Results consume the shared catalog;
the Runs gallery gets the matching captured preview and qualified result text.
The live feed belongs to the new `selected-workshop-v2-p1-keyboard` attempt and
must continue unchanged through this static release. No new viewer, synthetic
frame, dependency, service restart, database mutation, host or main merge.

## Corrected keyboard controls replay (September 12, 2026)

Start from public revision `5887540702b9aeedb656363b4a4cc1988131a197`.
Add `controls-v2-p1-keyboard-1-128` without rewriting its audited bytes. Its
SHA-256 is `280e6193242088f0743a000cc84ace5cefa23b82d4c9877f73abf46597c533f5`,
bound to audit `3302c95c7e3855f5621e60033b1d97b6bd0803f3609cced273233535039a3a5b`
and frozen native source `5ddf1e6718dab2e8351e8dc24a2afe5071cd2592`.

All 128 decisions used the keyboard route, with 669 confirmed key presses.
The final save retains 70,900 elapsed ticks, seven living dwarves, zero recorded
deaths, seven beds, two workshops, one farm, 43 food and 135 drinks. Its own
64-decision save was freshly reloaded; the final save has no separate reload.
The run returned 3,879,799 tokens. Subscription dollar charges are unreported.
Native and VM teardown passed. The redundant VM-stop command returned one
because guest poweroff had already stopped the VM; stopped state and closed
disks were independently rechecked. Original receipts retain that exit code.

This completes the first of three planned matched control pairs on one seed.
Show both individual outcomes, not a ranking or sustainability claim. Preserve
the earlier v1 replay separately. All eighteen older recordings and captured
previews remain unchanged; the catalog now contains nineteen windows and 1,508
captured frames. These windows are not nineteen independent campaigns.

Only the new recording, shared catalog/preview list, Runs gallery, tests and
this document change. The homepage and Results use the same catalog and viewer.
Preserve the latest live-feed identity, API/game services, database counts and
untracked files. No service restart, new host, game command, model call or main
merge is part of this static release.

## Pair-two keyboard controls replay (September 12, 2026)

Start from public revision `fc6f648ab27dbd39e60139e5995ae3992d232a8e`.
Add the original `controls-v2-p2-keyboard-1-128` recording with SHA-256
`9d15f665d816f9ba53f6b332480bc6017c192bcc8f50d73a208c0e067563c76e`,
bound to audit `ba2df79ae65339ed9681446d530b25c24a4ae5136764cae979b38420bf8ddf14`
and frozen native source `5ddf1e6718dab2e8351e8dc24a2afe5071cd2592`.

All 128 decisions used keyboard controls, with 731 confirmed key presses.
The final save retains 51,900 elapsed ticks, six living dwarves, one recorded
death, seven beds, five workshops, one farm, 61 food and 122 drinks. Native
incident evidence identifies drowning, first observed at decision 86; it does
not establish the exact death time or which model action caused it. The incident
receipt was pushed at `3539c605c3634dea2a7d89e6735a1f2dc2f01af5`.
The own-save continuation at decision 64 passed a fresh reload. The final save
has no separate fresh-reload check. Returned tokens total 3,954,012; subscription
dollar charges remain unreported, not zero.

The guest-poweroff command returned one with only `exit status 255` in its log;
no more specific cause is proven. The subsequent VM-stop command succeeded.
Independent terminal checks verified both VMs stopped, disks closed, unchanged
configurations and inventory. Original evidence retains both return codes.

Preserve the bytes, catalog rows and previews of all nineteen older recordings.
The total becomes twenty recording windows and 1,636 captured frames, not
twenty independent campaigns. The second pair's shortcuts attempt is pending.
No control ranking, sustainable fortress or full elapsed year is claimed.
The homepage and Results share the catalog; Runs adds the native captured card.
Retain the stopped pair-two keyboard feed without presenting it as a live game.
No API/game service restart, database mutation, untracked-file change, new
infrastructure, game input or model call is part of this website release.

## Pair-two shortcut controls replay (September 12, 2026)

Start from public revision `553528797ec140f2f2d50b623897cb3b3cf33811`.
Add the original `controls-v2-p2-shortcuts-1-128` recording with SHA-256
`4890518b7d6c550a49e25a6c134945141a16c136dc9f50721d605ab0f89db1cd`,
bound to audit `29535eb68e81a633675cf983f25674a9855a620e6ab0667590ec11af7b663b8b`
and frozen native source `5ddf1e6718dab2e8351e8dc24a2afe5071cd2592`.
The terminal result digest is
`e6541861299c7d1d39c1650284d92ece65c3e447250fc08aa8bc35aa6780a847`.

The final save retains 49,600 elapsed ticks, seven living dwarves, no recorded
deaths, ten beds, two workshops, two farms, 40 food and 136 drinks. All 128
actions were accepted: 117 keyboard actions sent 675 keys, and eleven workshop
shortcuts queued 43 jobs. Queued jobs are not completed products. Four zero-tick
timeouts remain in the evidence; requested time is not counted as progress.
The attempt freshly reloaded its own decision-64 checkpoint. Its final save
has no separate fresh-reload check. Returned tokens total 4,014,250; subscription
dollar charges are unreported, not zero. Both windows ended with successful
owner, guest-poweroff and VM-stop commands, and stopped VM/closed disk checks.

Preserve all twenty earlier recording files, catalog rows and previews.
The total becomes twenty-one recording windows and 1,764 captured frames,
not twenty-one independent campaigns. Two matched controls pairs are complete;
one pair remains. The visible cards retain the paired keyboard drowning and
do not claim a control ranking, sustainability or a full elapsed game year.
Homepage and Results consume the shared catalog; Runs has the new captured card.
Retain the stopped pair-two shortcut feed without presenting it as a live game.
Full website/player tests, exact-head hosted CI and public HTTPS verification
are required for delivery. No API/game restart, database change, new infrastructure
or additional model call is part of this static release.

## Pair-three shortcut controls replay (September 12, 2026)

Start from public revision `94425be289a28b3683bf2ce11d83634009839d36`.
Add the original `controls-v2-p3-shortcuts-1-128` recording with SHA-256
`02b139ad1021de3e560d20a2404944121cfc896b5477180c8c3e3a0dde71226a`,
bound to audit `432b19374f5e5c1260adcbd390679feb2e8cf83775e10e1ae56fec875396f106`
and frozen native source `5ddf1e6718dab2e8351e8dc24a2afe5071cd2592`.
The terminal result digest is
`79886cf295d51cdda4cca16702a108c3b8743060e9f055a199393eb7d55f69f4`.

The final save retains 58,200 elapsed ticks, seven living dwarves, no recorded
deaths, seven beds, two workshops, one farm, 56 food and 161 drinks. All 128
actions were accepted: 116 keyboard actions sent 741 keys and twelve workshop
shortcuts queued 49 jobs. Queued jobs are not completed products. Three zero-tick
timeouts and two deferrals remain recorded; requested time is not gameplay.
The attempt freshly reloaded its own decision-64 checkpoint, but the final
save has no separate fresh-reload check. Returned tokens total 3,621,402;
subscription dollar charges remain unreported. Both windows ended with zero
owner/poweroff/VM-stop return codes, stopped VMs and closed disks.

Preserve all twenty-one earlier recordings, catalog rows and previews.
The total becomes twenty-two recording windows and 1,892 captured frames,
not independent campaigns. Five of six controls attempts now have terminal
results; the final keyboard run remains. No control ranking, sustainability
or full-year success is claimed. Homepage and Results share the catalog;
Runs has the new captured card. Keep the sixth attempt's public live feed
unchanged during this release. Full website/player tests, exact-head CI and
public HTTPS checks remain required. No service restart, database mutation,
new infrastructure, main merge, gameplay input or model call is included.

## Final keyboard controls replay (September 12, 2026)

Start from public revision `286e000e36cb21b23bd7dc66ed54494e259eceeb`.
Add the original `controls-v2-p3-keyboard-1-128` recording, SHA-256
`337ca3bd834be6f50c2d09afbd3668228eee69d142e65d632f0b013974cdb337`,
bound to audit `52ecd5c277a001b91de5e1d62e76e5c09567bc001a9a6177fe345de55e9b1f58`
and frozen native source `5ddf1e6718dab2e8351e8dc24a2afe5071cd2592`.
The terminal result digest is
`e21bf87ed2b3efc4305690cf3d7de723c2c9bc6faf4189a98d50751da32786d0`.

The final save retains 46,400 elapsed ticks, seven living dwarves, no recorded
deaths, seven installed beds, three workshops, one farm, 42 food and 122 drinks.
All 128 keyboard actions were accepted, sending 751 keys with no workshop
shortcuts. The native clock advanced 46,400 of 51,600 requested ticks, with no
timeouts and three menu deferrals. All 3,753,509 returned tokens are accounted;
subscription charges are unreported. Its own decision-64 checkpoint was freshly
reloaded. The final save has no separate fresh-reload check. Guest poweroff
returned one with `exit status 255`; the subsequent VM stop returned zero and
independent stopped-VM and closed-disk checks passed. Original logs are retained.

All six controls attempts now have terminal native audits. These are three
paired policy samples on the same seed, not independent worlds, a control
ranking, or sustainable-fortress proof. Keep the existing failure/death evidence.
The shared homepage/Results catalog and Runs card now expose all six replays,
with 23 total recording windows and 2,020 frames across the full site.
Preserve all 22 prior recording files, catalog rows and previews.

Local validation passed 1,305 Python tests with five skips and seven warnings,
plus all 66 Node checks. The earlier full run retained one outdated gallery-count
assertion failure and 1,304 passes; the initial Node run retained four outdated
count assertions before their correction. These were release-test expectations,
not altered replay data. The importer had 36 passing in-memory checks before use.
Exact-head remote CI and public HTTPS verification are separate remaining gates.
Preserve the active endurance campaign's live relay while publishing this static
update. No service restart, database mutation, new infrastructure, main merge or
new model invocation is part of website publication. Browser-only preview/QA is
skipped in this background goal continuation.
