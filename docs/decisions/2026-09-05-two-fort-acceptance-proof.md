# Bounded two-fort acceptance: PASS

Verified September 5, 2026. Batch `m1b-live-20260905-7e4d84d188cc`.

## Outcome and limits

Two real seeded DF runtimes operated in separate containers, with distinct
run IDs, RPC ports, nonces, host PIDs, harness PIDs and run workspaces.
After both durably reached step 2, the fault driver killed only the target
DF process with signal 9. All six frozen DF-KILL criteria passed:

- Target classification: `runtime_df_killed`; OOM false.
- Detection: 1.261223605 seconds; cleanup: 11.583652092 seconds.
- Peer remained healthy through step 5 without reconnecting, then completed
  all 20 steps (0 through 19).
- Both attempts committed manager and supervisor terminal evidence.
- Double cleanup audits passed for both runs; foreign canaries were untouched.

This completes the focused reliability goal, not full M1b acceptance. The
sealed full-matrix decision remains `INCOMPLETE_NO_GO` because other runtime
gates were intentionally not selected. The runtime is the attested private
stock archive, not a claimed source-reproducible build. Requests were for
200 ticks; actual DF sampling can overshoot (observed examples 205 and 207),
so this is not proof of an exact 200-actual-tick ceiling.

## Independently retained evidence

Evidence root:
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1b-continuation-20260905/evidence-7e4d84d188cc`.

Within `retrieved/fortgym-m1b/evidence/m1b-live-20260905-7e4d84d188cc`:

- `control/gate-results.json`: DF-KILL status `PASS`.
- `gates/DF-KILL/gate-result.json`: measured facts, fault identity and terminal proofs.
- `gates/DF-KILL/diagnostics/gate-return/`: target and peer diagnostic records,
  including embedded original file content and hashes.
- `control/evidence-manifest.json` and `control/seal.json`: evidence bindings.

Independent local audit verified all 64 manifest files by size and SHA-256.
The additional contract reference resolves to retained `inputs/acceptance.yaml`
and matches its 25,490-byte size and frozen SHA. Seal hashes for the decision,
manifest and gate-results also match.

All 51 captured files (26 peer, 25 target) have byte-exact content, matching
SHA-256 and byte counts, with no truncation, redaction or changed-during-read
flags. Both records report `capture_ok` and `terminal_evidence_present` true.
Manager journals, manager terminals and attempt journals independently match
the terminal-proof hashes. Peer trace is 3,440,345 bytes and parses as all
20 sequential steps; target trace is 469,533 bytes and preserves steps 0–2
before the injected failure. Optional files for paths that did not execute
are marked missing; the killed target does not produce a normal summary.
Failure and immutable terminal evidence are retained instead.

The trace-retention fix allows 4 MiB only for the artifact trace, preserving
2 MiB limits for ordinary files and the 8 MiB total per run. The preceding
run passed runtime criteria but correctly failed incomplete trace capture;
it is not counted as this acceptance proof.

## Teardown and spending

`lifecycle-receipt.json` reports lifecycle complete, sealed host outcome,
root-broker attestation and post-seal cleanup verified. Independent cloud
absence checks show no instance, disk or address residue. The first deletion
command timed out; the second reported the instance already absent. The
absence checks, not those command return codes, establish teardown.

This continuation ledger contains two $8 reservations ($16), plus $40 in
prior current-series reservations: $56 reserved against the $250 ceiling.
Reservations are conservative accounting, not a billing statement. This
scripted test used no paid model calls. No production change, push or
publication was performed. Existing expiry and budget remain unchanged;
completion does not create a new spending authorization.

Packet manifest SHA-256:
`831bbcb6f4890e63bdb5b435eca4e624435e576018a11060518c70e54940ed52`.
