# M1b fault-isolation and reliability pass

Current engineering checkpoint: [two-fort reliability goal, September 4](../../docs/decisions/2026-09-04-environment-layer-two-fort-reliability.md).
The September 5 focused DF-KILL diagnostic passed with complete retained
evidence and verified teardown. Full M1b remains unproved and is the active
next goal; see [two-fort proof](../../docs/decisions/2026-09-05-two-fort-acceptance-proof.md).

This directory contains the pre-registered, provider-free acceptance contract
for the bounded Environment Layer M1b pass approved on 2026-08-16.

M1b is engineering evidence, not a research result. It does not authorize a
paid model, production access or mutation, publication, deployment, a push or
tag, E1, or any claim about model capability. The runtime remains the private,
checksum-pinned stock archive-seeded DF 0.47.05 plus DFHack 0.47.05-r8 image
from M1a. A clean source build remains a separate release gate.

Runtime identity is recorded at distinct OCI layers. Docker 29.1.3 reported
`sha256:d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c`
as the image `Id`; the retained archive proves that value is its OCI manifest
digest. The manifest points to OCI config digest
`sha256:d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86`.
The compressed and uncompressed archive-byte digests are recorded separately
in `acceptance.yaml`; none of these identifiers is interchangeable. This was
a post-freeze provenance-label correction only and changed no M1b gate,
threshold, attempt bound, or authority boundary.

`acceptance.yaml` is frozen before any M1b fault is injected. Every planned
attempt must enter the append-only journal and reach exactly one terminal
classification after cleanup verification. Failed and replaced attempts remain
first-class evidence.

The contract carries outcome-independent amendments, all recorded before
the affected live procedure ran:

1. the ambiguous image ID was split into the Docker runtime-reported ID, OCI
   manifest digest, OCI config digest, and archive-byte digests;
2. CAP-FAKE's "zero test cap" was clarified to mean zero remaining budget
   after one synthetic response exactly reaches a positive configured cap;
3. the OOM host counter was defined as the global `oom_kill` delta minus the
   target cgroup's `memory.events.local` `oom_kill` delta, while retaining a
   target-local delta of at least one;
4. the operator's dated infrastructure authorities are recorded as separate,
   append-only daily ceilings. The most recently recorded authority permitted
   up to USD 210 on 2026-09-05 America/New_York, expiring at
   2026-09-06T12:00:00Z, with at
   most one disposable VM active at a time and mandatory teardown after every
   attempt. This is the remaining allocation from the renewed USD 250 ceiling
   after prior USD 40 reservations. It permits at most 26 additional
   USD 8 attempts. The operator's subsequent full-M1b goal expands execution
   to the full matrix, preserving the shared ledger, ceiling and expiry.
   Five continuation reservations already total USD 40, or USD 80 including
   the prior baseline. The September 5 ledger remains the cumulative authority
   ledger across midnight; do not initialize a new allowance on September 6.
   The operator explicitly renewed bounded retries through the stated expiry.
   This is a hard ceiling, not a target; M1b stays provider-free.

None changed a gate, threshold, attempt bound, or observed outcome. The fourth
amendment changed only the previously absent infrastructure authority within
the stated ceiling and expiry. The exact text and timing in `acceptance.yaml`
are controlling.

Local Python 3.11 and mock tests can exercise the supervisor, port leases,
attempt ledger, environment firewall, fake cap, terminal ordering, and scoped
orphan selector. Real DF faults, eight-way co-tenancy, and Docker-daemon restart
remain incomplete until they run on an isolated x86-64 Linux host. The Mac is
not an equivalent acceptance host.

The 2026-08-17 offline integration pass closes the earlier local architecture
gaps: API process supervision, parent-only terminal ownership, durable SQLite
events and SSE replay, nonce-bound runtime identity, restart/orphan recovery,
startup replacement, typed fault classification, ENOSPC prelaunch/post-cleanup
sequencing, and the programmatic provider-network control seam are integrated
and locally tested. That is a local engineering result. It does not promote a
fake controller, mock worker, Darwin process test, static BPF check, or local
loopback preflight into a live-runtime gate pass.

The bounded infrastructure authority is valid only through the exact expiry in
`acceptance.yaml`. Provisioning must prove worst-case spend remains below the
ceiling, provider-side auto-deletion must be configured before launch, and all
resources must be deleted and absence-verified after the pass. If any of those
conditions is absent, the decision must be `INCOMPLETE/NO-GO`.

## Packet storage policy

`build_live_packet.py` performs the A/B determinism check inside one CLI
invocation. It builds the second packet under a temporary directory, compares
the two content manifests, writes `<packet>.determinism.json`, and removes the
temporary copy. Do not create permanent `packet-a` and `packet-b` directories
for the same version.

Only two complete packet directories may be retained directly under one run
root. This permits a safe one-version rollover, then the builder fails closed
until an older packet is archived. Completed run evidence and any packet that
must be preserved belong on the external archive, not on the workstation's
internal drive.

The packet includes pinned Linux Docker runtime files for the disposable remote
acceptance host; the builder itself does not start Docker or any local
container. Fort Gym development and runtime execution must use a remote or
hosted environment rather than a local container engine.

Hosted verification environments can set `FORTGYM_M1B_INPUT_PRIMITIVES` to
their mounted copy of the pinned tools. The workstation fallback points to the
checksummed Crucial X10 archive rather than recreating those inputs internally.
