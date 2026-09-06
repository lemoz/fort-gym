# Environment Layer M1a feasibility decision

Status: complete for the approved private M1a pass on 2026-08-16.

## Decision

**M1a decision: CONDITIONAL GO to M1b; canonical startup and source
reproducibility remain open.**

The Environment Layer topology is feasible on the tested standard
`e2-standard-16`. Eight concurrent DF containers completed at
98.163635–98.272381 ticks/s against a same-host N=1 baseline of 98.215417
ticks/s. The slowest run retained 99.9473% of baseline throughput. A stronger
two-fort test advanced only fort 1 by 10,078 ticks while fort 2 remained exactly
at its starting tick. Every durable run summary reports zero provider calls and
zero provider cost.

This is not an unconditional pass. Two attempts ended after DFHack printed
ready but never opened its RPC listener: container 6 in the first N=8 attempt
and primary E0 attempt 10. Both exited before a harness run and remain in the
attempt record. Successful replacements prove that eight environments can run;
they do not establish cold-start reliability or erase the failures.

The recommendation is to authorize a bounded M1b implementation and
fault-injection pass only after Chris reviews this packet. This decision does
not itself authorize M1b, paid models, production changes, publication,
deployment, release, E1, or any push/tag operation.

## Scope and tested identity

- Fort-Gym base commit: `236d3187c548b9bc03c4c99829d479d381a008d5`.
- Docker 29.1.3 runtime-reported image ID and OCI manifest digest:
  `sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c`.
- OCI image-config digest:
  `sha256:d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86`.
- Base image:
  `ubuntu@sha256:3b06811b2afd352be909dd088a004166d665dc76d38b13eada33522a9d915c6f`.
- DF `0.47.05` archive SHA-256:
  `ac74a6dbb7d7d9621f430405080322ab50c35f6632352ff2ea923f6dc5affca3`.
- Stock DFHack `0.47.05-r8` archive SHA-256:
  `2eab7ca38a25eb15e6b2f1005a44968d58fae53f618ea9e4a31e1cd74d31926f`.
- Seed tree SHA-256:
  `49ba1de07b62e7afda93b42059b6c566598bb0f4c83d11ae1dfdb78b54cd9ec0`;
  `world.sav` SHA-256:
  `070b10a3f2403e72368290eea0d09396fe06f7912b9babdea7ad26eb0498a87d`.
- Host: Ubuntu `22.04.5`, AMD Rome, 16 vCPU / 8 physical cores, 50 GB
  `pd-balanced`, no service account/scopes, eight-hour auto-delete bound.
- Container: host network, loopback listener, distinct port and server nonce,
  one DF hardware thread, 4 GiB cap, no swap, dropped capabilities,
  no-new-privileges, no restart.
- Harness: one sibling CPU, `env -i`, scripted policy, memory off, provider
  credentials/routes absent.

The roadmap's Spot VM was unavailable: `PREEMPTIBLE_CPUS` was explicitly zero
while `E2_CPUS` was 72. A standard VM was used without requesting more quota.
The exact eight-hour resource maximum was estimated at $4.3836 before small
evidence egress; the observed 1.3355-hour lifecycle was approximately $0.7318
before egress, not a billing invoice.

## First result Chris should see: two independent forts

| Phase | Fort | Port | Map | Year | Tick | Population | Nonce |
|---|---|---:|---:|---:|---:|---:|---|
| Before | 1 | 58001 | loaded | 30 | 16,801 | 7 | `isolation-r01` |
| Before | 2 | 58002 | loaded | 30 | 16,801 | 7 | `isolation-r02` |
| After ten steps on fort 1 only | 1 | 58001 | loaded | 30 | 26,879 | 7 | `isolation-r01` |
| Same instant | 2 | 58002 | loaded | 30 | 16,801 | 7 | `isolation-r02` |

The active DFHack listener was loopback-only, and an external connection to its
port timed out.

## Sizing evidence

CPU columns are peak observed process/container percentages from five-second
samples, not integrated CPU seconds. RSS and Docker working-set accounting are
reported separately because they use different accounting rules.

| Concurrent forts | Accepted | Ticks/s min–max (mean) | Peak container CPU | Peak DF CPU / RSS | Peak harness CPU / RSS | Peak container memory | Writable layer |
|---:|---:|---|---:|---|---|---:|---:|
| 1 | 1/1 | 98.215417 (98.215417) | 62.38% | 75.1% / 703.4 MiB | 62.0% / 57.0 MiB | 664.0 MiB | 10.36 MB |
| 2 | 2/2 | 98.268601–98.294308 (98.281454) | 81.49% | 76.5% / 703.9 MiB | 34.0% / 57.1 MiB | 664.4 MiB | 10.45 MB |
| 4 | 4/4 | 98.220550–98.262848 (98.249186) | 86.80% | 67.8% / 703.6 MiB | 33.0% / 57.3 MiB | 664.1 MiB | 10.40 MB |
| 8 replacement | 8/8 | 98.163635–98.272381 (98.243751) | 83.42% | 77.0% / 706.9 MiB | 36.5% / 57.2 MiB | 667.4 MiB | 10.47 MB |

The N=8 minimum exceeded the 89.1 ticks/s gate, and worst degradation versus
N=1 was 0.0527%. Final host state showed 62,938 MiB available memory, no swap,
and 11% boot-disk use. Resource headroom therefore passed for this short
scripted workload.

## Attempt accounting and startup defect

1. `m1a-20260816-04`: N=1/2/4 passed. The first N=8 attempt started containers
   1–5, then container 6 reached DFHack's ready message but timed out before an
   RPC listener. Containers 7–8 and all eight harnesses were never started.
2. `m1a-20260816-05`: a separately labeled N=8 replacement on fresh ports
   passed 8/8.
3. `m1a-20260816-06`: E0 primaries 1–9 passed. Primary 10 repeated the no-RPC
   startup failure and exited 70 after 120 seconds; it was not OOM-killed, no
   conflicting listener existed, and the host had 62,938 MiB available.
4. `m1a-20260816-06r1`: one explicitly labeled engineering replacement passed.
5. `m1a-20260816-07`: the stronger two-fort differential-tick check passed.

The first N=8 failure predates failure-log capture, but its partial seed and
readiness directory is retained. The E0 failure contains the startup log,
container inspect, listener snapshot, exact code/config snapshot, and seed
manifests. Root cause is still unknown. M1b must make startup supervised,
bounded, retryable under a declared rule, and terminally evidenced.

## E0 feasibility result

The ten planned primaries produced nine accepted runs and one infrastructure
abort. One post-failure engineering replacement produced a tenth valid
trajectory. The valid runs used fresh containers, seed copies, artifact trees,
and distinct ports.

For nine valid primaries:

- ticks/s mean 98.243478, sample SD 0.024284, range 98.194495–98.268998;
- actual ticks mean 10,065.67, sample SD 6.34, range 10,056–10,073;
- tick overshoot mean 65.67, sample SD 6.34, range 56–73;
- one seed-tree hash, one `world.sav` hash, one normalized step-zero state hash,
  one action-sequence hash, and zero provider calls/cost;
- nine distinct terminal-state hashes and nine distinct normalized trace
  hashes, with first post-action divergence at step 0.

Including the explicitly labeled replacement gives ten valid engineering
trajectories: ticks/s mean 98.241657 (sample SD 0.023608) and actual ticks mean
10,065.3 (sample SD 6.09). The replacement does not turn the primary cohort
into a clean 10/10 design.

Call this **short-horizon conditional replay dispersion**, not `sigma_world`.
It shows identical reset identity and scripted actions but immediate native
trajectory variation under the exact tested condition. It cannot estimate
across-seed, model, provider, host, long-horizon, or population variance and
must not size E1. A decision-grade E0-R still needs the frozen 100-step
checkpoint/unknown/replacement contract and full artifact schema.

## Gate disposition

| Gate | Status |
|---|---|
| M0A private preservation | PASS — 35,369/35,369 files verified |
| Stock archive-seeded image | PASS for private feasibility |
| Clean pinned source rebuild | OPEN |
| Loopback-only listener and external denial | PASS |
| Distinct ports/nonces/seed copies | PASS |
| Strong two-fort differential tick | PASS |
| N=1/2/4 throughput | PASS |
| Replacement N=8 throughput | PASS — 8/8, all ≥89.1 ticks/s |
| Cold-start reliability | OPEN/FAILED ATTEMPTS — two no-RPC starts |
| E0 primary cohort | INCOMPLETE — 9/10 plus one labeled replacement |
| Provider exclusion | PASS — 0 calls, $0 across 27 summaries |
| Python version support | EXCEPTION — 3.10 with `--ignore-requires-python` |
| Normal cleanup | PASS — zero container/port/cloud residue |
| Fault isolation and recovery | DEFERRED TO M1B |
| Publication/release/E1 authority | NOT GRANTED |

## Conditions for M1b

1. Remove the Python compatibility waiver and reproduce on Python 3.11.
2. Root-cause or safely supervise the intermittent DFHack no-listener start;
   record every retry and preserve every failed attempt.
3. Decide and document clean source rebuild versus archive/binary-seeded release
   identity; do not call the current result source-reproducible.
4. Demonstrate duplicate-port fail-closed behavior, DF/harness kill isolation,
   OOM, ENOSPC, Docker restart/orphan detection, and cleanup under failure.
5. Complete the longer scientific E0-R contract before using replay dispersion
   for power or any public research claim.

## Evidence and cleanup

The private packet is
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1a-feasibility-20260816`.
Its VM-generated manifest covers 665 raw files and has SHA-256
`9a2d8d3f6eec8b3118c50f53a4e01379eb8ea95ec7ea5768221889628c1396a5`.
The exact compressed OCI image archive (`.tar.zst`) is retained at SHA-256
`87d66d26553cb271af1b784405d63ea6b95f3bbe20e9429f05e6412133d1f43a`;
its decompressed tar bytes have SHA-256
`39e4cfce8cc65ca4f4a761fd732cc5d3c2faa8d237b85992dae6da1076f8e756`.
These archive-byte digests bind the saved serialization, while the OCI
manifest digest above binds the config and nine compressed layer blobs.

The VM, boot disk, and ephemeral address were deleted. Exact-name readbacks
returned zero instance, disk, and reserved-address resources. No paid model
ran, production was not mutated, nothing was published or deployed, no branch
or tag was pushed, and M1b was not begun.
