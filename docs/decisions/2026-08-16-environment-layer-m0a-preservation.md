# Environment Layer M0A preservation decision

Status: complete for the approved local, read-only preservation pass on
2026-08-16. This is not full M0 closeout.

## Decision

Preserve the complete production evidence and source state before M1a, then
test the pristine stock DF `0.47.05` + DFHack `0.47.05-r8` archives as the
first private image candidate. Keep the exact-production binary-seeded runtime
as a separately labeled fallback.

Do not apply `infra/ansible/files/dfhack-core-autoboot.patch` in M1a. It is a
second-stage delta against a later 50.12 experiment and applies to neither
surviving source tree. Official `0.47.05-r8` already starts its TCP listener,
reads `DFHACK_PORT`, and defaults to loopback when `allow_remote` is false.
M1a must prove that behavior at runtime and stop on any non-loopback listener.

## Preservation proof

The private packet is at
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m0a-preservation-20260816`.
Its null-safe recursive manifest contains 35,369 file records and has SHA-256
`797571ff2a2467816b51650e5878ead1e9597e71765b6bdf45e19c24db5e0fd6`.

The packet includes:

- the complete 11,627-file calibration checkout and all raw attempts;
- all three seed trees and their full-tree hashes;
- both immutable historical paid-run directories;
- both surviving DFHack source trees, including Git/submodule object stores,
  dirty and untracked state, and the local-only 50.12 commit;
- pristine DF/DFHack archives, runtime overlays, non-secret service units, and
  a complete Fort-Gym branch bundle.

Two preservation qualifications are explicit. The binary-seeded runtime copy
retains its 9,730-byte historical `errorlog.txt`; it is evidence, not a clean
release input. Also, the preserved 0.47.05 `depends/libzip/.git` contains its
original absolute `/opt/dfhack/...` gitdir. Its object store is present, but
that checkout is not relocatable without a later, separately reviewed repair.

Detailed hashes and source identities are in
`experiments/evidence/environment_layer_m0a_preservation_20260816.json`.

## Corrected assumptions

The design's “source vanished” premise is disproven. `/opt/dfhack` is stock
`0.47.05-r8` at `fed9f763c9c9b0f64d45e8d7bec626f492c752fe` with dirty
submodule/build state; `/opt/dfhack-src` is a dirty 50.12 experimental tree at
`3b8bf517abed26a821bb81b5de7d06e6d0b0c0b0`. The installed core binaries
match the pristine archives. Source preservation is therefore complete, while
a reproducible source rebuild remains a separate full-M0 question.

## Boundaries retained

No production file, save, service, process, or run was changed. No tag was
created; no branch was pushed; nothing was fetched into or deployed to
production; nothing was published. Secret environment files were excluded.

An initial remote Git status touched only optional Git lock/directory metadata
in the calibration checkout. Local inspection later refreshed only the copied
source indexes; the exact unchanged remote indexes were copied back, and final
checksum-mode rsync comparisons showed no file differences. These are audit
metadata effects, not source or evidence changes.

A later verification refreshed the copied 50.12 index once more despite
optional Git locks being disabled. It was restored byte-for-byte from the
unchanged production index at SHA-256
`deef6f50877ff1f8031e922384c8dbbf09513859332d045c49bf33cbdce7629b`;
the private recursive manifest then verified all 35,369 records.

## Full-M0 work deliberately not claimed

- A third/off-machine durable copy beyond production and this Mac.
- A source rebuild proof or final release-image decision.
- Reviewed-tip tags and branch push.
- Ansible URL correction and the `df_version` provenance erratum.

Those actions require their own authorization or later milestone work.
