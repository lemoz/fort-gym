# Full Environment Layer M1b acceptance: GO

Verified September 5, 2026. Batch `m1b-live-20260905-ca003c13be34`.

## Outcome

All 16 frozen hard gates passed in their prescribed local or isolated Linux
setting. All 26 real-runtime attempts completed, with no missing or incomplete
attempts. The provider-free scripted run made zero paid model calls.

Passed: PORT-1, PORT-2, COLD-RETRY, CO-8, DF-KILL, HARNESS-KILL, OOM, ENOSPC,
CONTAINER-RESTART, DAEMON-RESTART, ORPHAN-1, ORPHAN-2, PROVIDER-ENV, PROVIDER-NET,
CAP-FAKE, and CLEANUP. Local-credit gates remain identified as `PASS_LOCAL`;
they are not represented as real-runtime tests.

The sealed decision is `GO`. Both final cleanup passes, root-broker attestation,
post-seal host cleanup, evidence retrieval, and independent cloud teardown
verification passed. Instance, disk and address absence were independently
observed twice by 2026-09-05T23:48:22Z. The control master, process group,
socket and temporary connection directory are absent. No VM remains active.

## Evidence

Evidence root:
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1b-full-20260905/evidence-ca003c13be34`.

- `lifecycle-receipt.json`: verified GO, root attestation, retrieval and teardown.
- `local-independent-audit.json`: independent retained-evidence checks.
- `retrieved/fortgym-m1b/evidence/m1b-live-20260905-ca003c13be34/control/decision.json`:
  16/16 gates, 26/26 runtime attempts, no incomplete attempts or failure reasons.
- The same control directory's `seal.json`, `evidence-manifest.json`,
  `gate-results.json`, and attempt/batch ledgers bind the result and its evidence.

Independent local verification checked all 139 direct manifest files by size
and SHA-256, plus the canonical acceptance reference retained at
`inputs/acceptance.yaml`. All three seal hash bindings match. All 598 captured
files across 27 gate-return diagnostic records match captured hashes and sizes,
without truncation or changed-during-read flags; capture and terminal presence
checks passed for every record.

Packet manifest SHA-256:
`2ca01d8d8a5aab17394d4a3f9d564a0fa3a66cde8465a3c7549c40120bc1a389`.

Acceptance SHA-256:
`b7b71aad91391c6e22f9fa651f9bf05244c212ce0693e3b3344dca66eed99edf`.

Plan SHA-256:
`d37cad75e7e052ed4463353f0b3138f64143ca1e50337e6ad5eb29cbbca47194`.

## Implementation and verification

The continuation corrected real acceptance defects without weakening the frozen
gate requirements. The last corrections included host-side OOM counter capture
before cgroup removal, exact ENOSPC mount ownership and unmount proof, consistent
disk-full classification through supervisor and manager validation, and excluding
volatile scheduler state from otherwise strict process identity comparisons.
PID reuse, foreign identity, dead processes, missing fault evidence and real
budget-cap violations remain fail-closed.

Final candidate verification: 619 local regression tests passed, plus all 79
cloud-lifecycle regression tests. Two independent packet builds were byte-identical;
manifest entries and relevant production sources matched the tested checkout.

## Scope and spending

This completes the full M1b goal and supersedes earlier incomplete full-matrix
outcomes. The earlier focused two-fort proof remains preserved unchanged.
The runtime is the attested private stock archive, not a claim of a
source-reproducible DF runtime or an exact 200-actual-tick ceiling.

Cumulative reservation is $152 against the existing $250 cap. Reservations are
internal accounting, not charges. Modeled infrastructure usage across the current
nineteen-run series is about $4.14; actual billing is unavailable. The estimate
excludes network egress, taxes, credits, discounts, Codex usage and unrelated
resources; details are in the evidence root's parent `spend-tracking.md`.

No further acceptance runs are needed. No production changes, publication,
push/tag, M2 or E1 work were performed or authorized by this completion.
