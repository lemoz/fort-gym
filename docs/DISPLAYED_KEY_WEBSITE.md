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
