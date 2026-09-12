# Matched displayed-key comparison publication

This release extends public source `08f1b7d31855188bbef2b2ae8aac300a4bc757f0`.
It keeps the existing hosting, backend, live relay and historical benchmark.
No game or model calls are started by the comparison page or recording exporter.

`/results#matched-comparison` displays all six predeclared attempts at the first
64-decision boundary. Missing published evidence is not a failed or unrun attempt.
The snapshot does not claim to show live status. Budget pause, infrastructure
failure and gameplay collapse remain distinct. Null measurements and unreported
subscription dollar charges are not converted to zero. Same decision limits do
not imply equal tokens or native game time. No model ranking is claimed.

The report is the exact output of `scripts.campaign_displayed_key_comparison`
at root repository revision `4c8f3b345206cd0cc5e0f4e70e84acae6910d379`, using
`experiments/evidence/keyboard_binding_comparison_20260911_index.json` and
`--boundary 64`. That reader verifies frozen plan, configuration and public result
digests. The first report contains the reviewed Sol result at immutable revision
`f9645c129e224a467712abcc9bff24dc20bcf955`. Its one reported attempt is not the
older exploratory Astra Year-Two run or the earlier Sol native-action-name trial.

`scripts/export_displayed_key_recording.py` exports the new fresh-trial audit
schema. Run it with the original `--attempt`, clean `--observer` checkout at
`2778519991899ee3360db1caf6daec29721bbc4a`, `--audit-sha256`, `--id` and a new
`--output` path. It checks audit and native trace digests, consecutive coverage,
original request digests, model/effort and response action against the trace.
The frozen observer contributes only the bounded screen/action projection.
This export is not a substitute for the original native/provider terminal audit.
Only captured screens, stated intent, keys, clock and population are published;
private agent memory and provider/account payloads are omitted.

The new Sol replay has 64 frames and 2,900 saved game ticks. Seven citizens live,
with no recorded deaths or completed beds/workshops/farms. The saved supplies are
50 raw-food units and 60 drinks; 1,258,321 returned tokens are recorded. This is
limited measured development, not functioning-fortress success. A fresh final
checkpoint reload is not claimed for this trial.

All five prior recording files remain byte-identical. The catalog and gallery now
contain six windows and 544 frames across three models, not six independent trials.
The new replay is the newest catalog entry; Astra's earlier Year-Two outcome and
reload proof remain inspectable in their original replay.

Release only as a checked fast-forward after tests and public asset verification.
Preserve API/game service identities, database counts, untracked files, live-feed
receiver and old recordings. No service restart or hosting migration is needed.

## First-round update

The next publication extends `dfbb874ec659eea7b09f3344d7aafefb05e4f778` without
replacing any of its six recording files. The source report comes from goal
revision `014f5c3d9ad2152df75c1bc469e64d01960d4c4b`, with three audited results
and all six declared slots still visible. Second attempts without a published
result are not represented as failures or zero progress.

The added replays are `terra-matched-r1-1-64` and `astra-matched-r1-1-64`, each
64 captured decisions exported through the existing pinned observer. Their audit
digests are `a27991556fcffab8287eb535814ecf62ab9c2131cbbf6b891bfd76edaa79ddfe`
and `8fcd53923a28b84763a031f4046b7831b38f0b9a6dfdbdfcf5f4c081f6396cfc`.

Terra retained 4,200 game ticks, seven living citizens, no completed buildings,
51 food and 60 drinks. Astra retained 23,000 ticks, seven living citizens, seven
beds, two workshops, one farm, 50 food and 55 drinks. Neither short attempt
demonstrates sustainability or Year-Two completion. Unknown measurements remain
null. All original clock failures remain in the source evidence.

The catalog has eight recording windows and 672 frames. Astra's new first
attempt is the latest recording, while the live observer still takes priority
unless the viewer explicitly selects a replay. Each of the three published
comparison rows links directly to its own replay and immutable result. The
earlier Year-Two campaign remains separate historical evidence.

## Terra repeat and rejected-command visibility

The next publication extends `09d0c5cb3dd9c35b20246b0a68a16c8ffd543856`.
The source report at `d7944ae7114fcaff185ad880dbb9d1747b390112` includes four
reviewed results and all six declared slots. Terra's second trial is saved at 64
responses, with 1,186,821 tokens, zero game ticks and no completed buildings.
Seven dwarves at unchanged starting time are not evidence of management success.

The exporter now uses the separate observer candidate
`7cd3b96763998abfd99ed623630d658320a27918`, whose native typed-rejection parser and
displayed-key catalog exactly match the frozen gameplay source. It reconstructs
rejected choices using the original screen and declared control profile, binds
them to the audited trace, verifies zero key/clock dispatch and publishes only
the existing allowlisted frame fields. Run it in a fresh standalone process to
keep the evidence parser separate from the public server package. No transport
or game operation is invoked by these read-only imports.

`terra-matched-r2-1-64` contains all 64 frames, including the nine rejected choices
at decisions 3, 4, 8, 23, 25, 46, 51, 62 and 63. Its digest is
`d34f451723a40ef11c2cb966b2c568702e44489163b51e79721bffb15aeaeeb1`.
The catalog and gallery contain nine windows and 736 frames. The new recording
is available from the homepage and its comparison row. Original recordings stay
unchanged; re-exporting all three first attempts with this parser reproduced
their existing bytes exactly. Updating the exporter does not switch the active
Sol r2 relay, restart services or change any game protocol.

## Sol second-attempt update

This publication extends `d4a3745b70ecf7fc78835c435aca73d4e4aaaa25`.
The report at `4f4c5a33024b7c3fc2b487dd4d8197c46a477ef2` includes five
reviewed results in the same six declared slots. Astra r2 has no published final
result yet; the comparison snapshot does not infer its live state.

The added `sol-matched-r2-1-64` replay contains 64 original frames with digest
`30b1aeced4a62c8882aa77004784d3057f84768c8b778c147b0adcc25f517152`.
Its own terminal audit is
`c75b838d06e69b63145023851d3bfb419c68620e620bcca25dc46860a55a102a`.
Sol retained 10,400 actual game ticks, 1,221,506 tokens and seven living citizens,
with no completed beds, workshops or farms. Food and drink stocks remained 50
and 60. Nine clock timeouts remain in immutable source evidence; the replay
shows actual elapsed time, not the larger requested total. These short runs do
not establish a sustainable fortress or a model ranking.

All nine older recordings remain byte-identical. The gallery has ten windows
and 800 captured decisions, not ten independent trials. Homepage live priority,
manual replay selection, service identities and the active Astra r2 relay remain
unchanged. A source update is not public delivery until the exact release passes
existing-host and external HTTPS checks.

## Complete fresh cohort and continuation budgets

This update extends `6452fc2345c2eb99beab6485d367a203007a34e0` using the
source index at `99121512af7ab3bb9d960076fae5554795432e30`. The default
64-decision report now includes all six audited fresh attempts. The independent
128-decision report includes Sol r1's startup infrastructure failure, with its
unchanged parent checkpoint at 64 responses, 2,900 ticks and 1,258,321 tokens.
There were no new provider calls or gameplay decisions in that failed window.
Its failure review remains linked; no repaired continuation is inferred.

The results page offers the two predeclared decision budgets and changes the
download link with the selection. Responses and saved state remain distinct
from the chosen budget. Missing outcomes remain unknown. The selected budget is
validated against each report, and a late response for an older selection cannot
replace the current table or clear it with a stale error. Only actual published
recordings receive replay links; no 128-decision replay is invented.

The added `astra-matched-r2-1-64` recording has 64 original frames with digest
`79ea8da55449f58aca9b9d6a98cd37db56b825d228bff10c6211961a9f2bfc30`.
It is bound to terminal audit
`6e255c110250f65c1daf0b94482c2e2ae53af3335991a09258178802fd89bea4`.
The saved outcome is three workshops, no placed beds or farm plots, seven living
citizens, no recorded deaths, 9,200 game ticks and 1,549,386 tokens. Food and drink
stocks remained 50 and 60. All requested time advanced without clock errors,
but 59 of 64 responses requested no time advance.

All ten earlier recording files remain byte-identical. The gallery contains
eleven windows and 864 captured decisions, not eleven independent trials.
These early outcomes do not establish sustainability or a robust model ranking.
The update preserves existing hosting, services, live-observer priority, manual
replay selection and older Year-Two/recovery evidence.

Validation: 1,248 Python tests passed with five skips and seven warnings, plus
44 Node interaction tests. Selected Ruff checks and the recording exporter's
type check passed. The first sandboxed full run blocked one local socket test;
the complete unrestricted rerun above passed without source changes. Browser
visual QA was not performed. Public delivery remains a separate exact-revision
check, not a consequence of these local tests.
