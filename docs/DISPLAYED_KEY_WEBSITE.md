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
