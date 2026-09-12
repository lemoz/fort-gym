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

## Terra own-save continuation

The next static release starts at `c763742f6e45d96c9b82df10a9776ee5bbbcb8fc`.
It adds Terra r1 decisions65-128 as a separate recording, not a fresh replicate.
The terminal audit is `df238f47bfb4171329986f39b82da959cb485f8601e0ac3b6990becf8c8617c0`;
the replay digest is `259ef96059fee1d2ef35e51779fcd27747c7b9c68784579152fbccf848441146`.
The public checkpoint result is bound to commit
`deb53296492a33cf163ca40b8f067bee11ce6308`.

This window adds 116,000 saved ticks to the original 4,200, giving 120,200 total.
Population grows from seven to fifteen with zero recorded deaths and one workshop.
There are still no completed beds or farms, with 36 food and 26 drinks at the end.
Returned tokens total 3,717,561; subscription dollar charges remain unreported.
The parent native reload, original checkpoint preservation and final teardown
are verified. The final checkpoint has not had a separate fresh reload.

The 128-budget comparison retains Sol's infrastructure failure alongside Terra's
saved result. The new Replay link points to the actual 65-128 recording. No outcome
is fabricated for the other four slots. The homepage, results recordings and
Worlds gallery share the twelve-window catalog with 928 captured frames.

The exporter now accepts the separately versioned own-save audit, preserving
original decision offsets and counting only the new window's elapsed time.
It still binds every screen, response and action to the reviewed trace and pinned
observer. A fresh Astra r2 re-export is byte-identical, and all eleven existing
recordings remain unchanged. Native runtime behavior, active observers and
historical benchmark definitions are not changed by this website update.

Validation for this release: 1,269 Python tests passed with five environment skips,
and all 49 Node viewer contracts passed, including continuation scrubbing through
decision128. Selected Ruff and exporter typing checks pass. These checks are not
browser visual QA or public delivery; publication is verified separately.

## Astra own-save continuation

This update extends `900e3eba6acd254ea340ecad0585b883279914ca` using the
source report at `eff32477b54f18d3e1f25c05768cb55813181207`. Astra r1's
immutable result is retained at `4b3617128f773b1a04120a405809731a66570a8c`.
The recording `astra-matched-r1-65-128` has digest
`0f32a0439dafeef5d39dc70702bfbda902bd0e95006fe974744f00fc291a0489`,
bound to terminal audit
`fcb09958a87e5c56c707790fc439375410dd7afb5ba18dbc9a06667deadf830e`.

The original 64-response save continues for another 64 responses and 32,700
actual ticks, reaching 55,700 saved ticks in total. The endpoint has eight beds,
three workshops, two farms, seven living dwarves and no recorded deaths, with
61 food and 83 drinks. Returned tokens total 4,123,021; subscription charges
remain unreported. One blocked-menu clock outcome remains in the source result;
accepted key commands do not prove their intended game outcome. The parent was
loaded natively; the final checkpoint has not had a separate fresh reload.

The 128-budget table now contains three results, including Sol's unchanged
infrastructure failure. Three further outcomes remain unpublished, not zero.
The homepage and gallery share thirteen recording windows and 992 captured
frames. All twelve earlier recordings are byte-identical; the current native
run, observer, exporter and six-result 64-budget report are unchanged. This is
not a new replicate, sustainability proof or robust model ranking.

Validation: 1,270 Python tests passed, with five environment skips and seven
existing warnings, and all 50 Node viewer contracts passed. The new continuation
has its own scrubbing regression and immutable-result link check. The initial
test draft expected fields outside the public report; it was corrected to use
the report's actual schema. A sandbox-denied socket test passed in the full
localhost-enabled rerun. Selected Ruff checks pass. No browser visual QA was
performed; exact public delivery is checked separately.

## Terra repeat continuation and Sol repeat capacity outcome

This update extends `d5ca3e30a77882eea7b01189c1ac7d41fce5bf0f` using the
five-outcome source report at `1647d9b4c210e206769f9300a5006c0340388b56`.
Terra r2's immutable result is at `aa12d891c00ede817b39b72752b37719a4b11e0a`.
The new `terra-matched-r2-65-128` recording has digest
`f8fb441bfd5201d7ac9c38f23a10d942fb7adf3ab02c369c8ebc94b287a657a0`
and terminal audit
`70b7a33f05fa26f9ecfb696e812fb1557fc3faa8e056c037d46b7b5dc6468d55`.

Its 64 additional responses advance 108,000 ticks from its own unchanged
64-response save. Seven dwarves remain alive with no recorded deaths, but
there are no completed beds, workshops or farms. Food and drinks end at 36
and 26. Returned tokens total 2,339,683; subscription charges are unreported.
Elapsed time is not measured fortress development or sustainability proof.
The parent loaded natively, while the final save has no separate fresh reload.

Sol r2's continuation failed its declared guest-capacity floor before any
game container, model call or gameplay input. Its reviewed result remains
at `1b366a2ebb896866fe1c3d170f20a4b916de7609`, preserving the original
64-response save, 10,400 ticks and 1,221,506 tokens. The failure gets an
evidence link, not an invented replay. Astra r2 remains unpublished at 128.

The 128-budget report now has three saved outcomes and two infrastructure
failures. The shared catalog has fourteen windows and 1,056 captured frames.
All thirteen older recordings and the six-outcome 64-budget report remain
byte-identical. The exporter, native runtime and stopped observer are not
changed. These windows are not fourteen independent trials or a robust ranking.

Validation: 1,272 Python tests passed with five environment skips and eight
dependency/deprecation warnings, plus all 51 Node player/gallery contracts.
Selected Ruff checks and diff checks passed. Browser visual QA was not performed.
Exact public delivery remains a separately verified release step.

## Portable harness save-and-resume recording

The portable Docker owner acceptance is now available as
`astra-portable-acceptance-1-4`. Its four paused Astra decisions span a verified
two-decision save and own-save continuation. Zero game ticks elapsed. This is
a harness check, not a matched trial, fortress-growth result or sustainability
claim. The recording digest is
`4737508d32fd1a6e27c2c78e1636ec7fb8de91eaca622cd38f8a7d3ab398ddf1`;
the native source is `40b106b95f483b534a738622e75c4147a1270a96`, with audit
`a9a193fc539fe7541b48625cde1a00782cb29017f32b9fb92b6d5a059b3e47df`.
Its immutable result is at
[the acceptance manifest](https://github.com/lemoz/fort-gym/blob/7fe87fb6addc031a95f421ef985f139375fe8920/experiments/evidence/keyboard_portable_owner_acceptance_20260912.json).

The existing player and preview format are reused. This recording is appended
after all fourteen existing recordings; the homepage default remains Terra's
matched repeat continuation. The catalog has fifteen windows and 1,060 frames.
Both comparison reports and all older recordings remain byte-identical. The
stopped live relay, API, game services and database are outside this static
update. No new game or model calls were needed. Live follow acceptance for
the portable owner remains separate from this completed recording.

Validation: 1,273 Python tests passed with five skips and seven existing
warnings, and all 52 Node player/gallery contracts passed, including scrubbing
all four new decisions. Scoped Ruff and diff checks pass. The sandbox initially
denied one localhost socket test; the complete localhost-enabled rerun passed.
Browser visual QA was not performed; public delivery is verified separately.

## Astra repeat completes the declared 128-decision comparison

The source report at `41afc03fe871517a0f6a21b40dba31aeb410b81c` now contains
all six outcomes: four saved continuations and two unchanged Sol infrastructure
failures. The subsequent source test correction changes no report bytes.
Astra repeat 2 saved 50,400 total ticks, seven living citizens, zero recorded
deaths, seven beds, three workshops and one farm. Food is 42 and drinks are 121.
The complete attempt accounts for 3,483,445 tokens; dollar charges remain null.
The original save and all model/keyboard receipts reconcile, and native/VM
teardown passed. A separate fresh load of the new final save is not claimed.

The new `astra-matched-r2-65-128` replay retains 64 captured decisions and
41,200 new ticks. Its digest is
`5bdeb2650b4562c3327c7a699ae4e88458052155c507546c138c63a02a809215`, bound to
terminal audit `31dceaeea4f5b20f98b08bca0b029233ae0419fd1c8d8a8302afb6704f7325f7`.
It becomes the latest replay on the homepage and links from Results and Worlds.
The gallery has sixteen windows and 1,124 frames; all fifteen earlier recordings
and the six-outcome 64-decision report remain byte-identical.

Only Astra repeat 2's continuation is labelled with the declared 32-to-40 GiB
storage amendment. Model, prompt, controls, CPU and RAM were unchanged; storage
conditions were not identical across these windows. Infrastructure failures stay
visible. This small cohort does not establish a strong model ranking, and stock
snapshots do not establish production rates or sustainable operation. The
comparison script/style URLs are versioned so returning visitors load the labels.
This section describes the release contents; public acceptance is recorded separately.
