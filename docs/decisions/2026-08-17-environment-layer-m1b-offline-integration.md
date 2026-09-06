# Environment Layer M1b offline-integration decision

Status: private provider-free offline integration complete on 2026-08-17.

## Decision

**Offline integration and local core: PASS_LOCAL.**

**Full M1b: INCOMPLETE/NO-GO. E1: NOT AUTHORIZED.**

The earlier local architecture blockers are closed and the current uncommitted
snapshot passes its complete sanitized Python 3.11 suite. That does not satisfy
the frozen decision rule. The preserved DF runtime, eight-runtime cohort,
Linux cgroup OOM, private tmpfs ENOSPC, cgroup-BPF network capture, Docker
daemon restart, and real-runtime orphan/cleanup procedures have not run on an
isolated x86-64 Linux host.

The controlling contract is [acceptance.yaml](../../infra/m1b/acceptance.yaml).
The prior [component decision](./2026-08-16-environment-layer-m1b-fault-isolation.md)
and [component evidence](../../experiments/evidence/environment_layer_m1b_fault_isolation_20260816.json)
remain immutable historical records. This pass is recorded separately in the
[offline-integration evidence](../../experiments/evidence/environment_layer_m1b_offline_integration_20260817.json).

## Integrated local core

- `POST /runs` and `/jobs` reserve exact rows and launch external workers
  through the supervised process path. Interactive/global DFHack surfaces fail
  closed for supervised runs.
- The child reports a typed outcome; only the parent records cleanup completion,
  final status, terminal reason, and `ended_at`.
- A durable SQLite event outbox supports cross-process and restart-safe private
  and public SSE cursors.
- A canonical per-run contract binds run ID, nonce, port, seed, image manifest,
  image config, image archive, code, saves, provider policy, environment, and
  co-tenancy.
- Runtime prepare, cleanup, and dead-owner reconciliation are exact-label and
  contract-bound. Process-group recovery preserves foreign canaries.
- Natural startup replacement is bounded and uses a fresh run identity. The
  pinned OCI fallback verifies compressed archive, index, manifest, and config
  digests before use.
- Fault drivers and strict classifiers exist for DF kill, harness kill, OOM,
  ENOSPC, container restart, and daemon restart. They fail closed on incomplete
  or contradictory evidence.
- The 256 MiB OOM target is held before DF launch until its peer is durably
  ready and healthy. ENOSPC uses a constructor-only 16 MiB private tmpfs profile
  and unmounts after runtime/process cleanup but before classification and
  terminalization.
- Provider-free scripted children use an allowlisted environment with dotenv
  disabled. The provider-network seam uses a pinned wrapper and cgroup-BPF
  source contract; launch-intent recovery covers both wrapper-pre-exec and
  inner-exec crash windows.
- The final adversarial review found and closed an ENOSPC
  `terminal_pending`-before-`terminal.json` recovery window. A second review
  confirmed exact `supervisor_lost` terminalization and inner-exec recovery.

## Verification

| Check | Result |
|---|---|
| Complete sanitized Python 3.11 suite | 1,761 passed, 5 live-DFHack skips, 0 failures/errors; 6 loopback nodes isolated |
| Exact isolated loopback nodes | 6 passed |
| Focused M1b suite | 541 passed; 4 loopback nodes isolated |
| Independent final repair audit | 112 passed; no P1/P2 blocker |
| Untracked Python Ruff | Passed |
| Modified tracked Python Ruff F/E9/I | Passed |
| `py_compile` on all modified/untracked Python | Passed |
| `bash -n infra/m1b/runtime_entrypoint.sh` | Passed |
| Provider-network static contract | Passed |
| Acceptance YAML and evidence-index JSON parse | Passed |
| `git diff --check` | Passed |
| Provider calls / provider cost | 0 / $0 |
| Real M1b runtime attempts | 0 |

The immutable private packet is at
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1b-offline-integration-20260817`.

One full-suite order dependency surfaced during verification. A provider-network
test left a monkeypatched artifact-root setting cached after teardown, so later
public-result tests wrote and read replay traces through different roots. A
module-scoped before/after cache fixture closed the leak without changing
production code; the complete suite then passed.

## Frozen gate disposition

| Gate | Disposition | Evidence boundary |
|---|---|---|
| PORT-1 | PASS_LOCAL | Exact 32-contender host-wide lease race: 1 winner, 31 conflicts, no loser child |
| PORT-2 | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Real loopback peer stays responsive, but it is not the preserved DF runtime |
| COLD-RETRY | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Bounded policy/controller replacement path only |
| CO-8 | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Eight real OS mock workers with shared SQLite are not eight DF runtimes |
| DF-KILL | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Driver/classifier only; no real DF process killed |
| HARNESS-KILL | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Local process-group recovery only |
| OOM | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Held pre-readiness protocol and evidence validator only; no Linux cgroup OOM |
| ENOSPC | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Full fake lifecycle and crash recovery only; no mounted 16 MiB target tmpfs fault |
| CONTAINER-RESTART | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Driver/controller contract only |
| DAEMON-RESTART | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | External-host-driver contract only |
| ORPHAN-1 | PASS_LOCAL_SUBPROCEDURE; real half open | Exact local process/fake-container cleanup, foreign canary, idempotence |
| ORPHAN-2 | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Actual local manager SIGKILL and process-group recovery, not isolated DF/Linux resources |
| PROVIDER-ENV | PASS_LOCAL | Exact poisoned parent plus poisoned dotenv child procedure |
| PROVIDER-NET | ENGINEERING_PREFLIGHT_PASS; LIVE NOT RUN | Source/static/fake controller pass; no privileged Linux BPF load or connect capture |
| CAP-FAKE | PASS_LOCAL | Exact amended positive-cap exhaustion, durable typed failure, no second fake call |
| CLEANUP | ENGINEERING_PREFLIGHT_PASS; full gate open | Local double-audit/order/residue only; every live case has not run |

Only `PORT-1`, `PROVIDER-ENV`, and `CAP-FAKE` earn complete frozen local-gate
credit. `ORPHAN-1` earns only its local subprocedure. Every other result remains
an engineering preflight, not a live gate pass.

## Runtime and measurement locks

The retained archive reverified as:

- compressed OCI archive SHA-256: `87d66d26553cb271af1b784405d63ea6b95f3bbe20e9429f05e6412133d1f43a`
- uncompressed tar SHA-256: `39e4cfce8cc65ca4f4a761fd732cc5d3c2faa8d237b85992dae6da1076f8e756`
- OCI manifest SHA-256: `d6403fc04f2231a75c2a4ca4379b393fddd08d9034df07dd4ff9a8d46a15068c`
- OCI config SHA-256: `d90811a39d5edd7c0a61d9adbbe4251cbfc345df52f5fa48ba174ce8992b8a86`

Docker Desktop is arm64. The pinned image is not currently loaded and no M1b
container exists. The archive was not loaded and no container was started in
this pass.

The final P1 measurement-code digest is
`5bdcd821ddb7c916ddef96572bde06ca9600ead486db6b32ca39cde9332dd937`.
G7-v5 remains re-locked: no paid pair may run without recalibration and review.

The OOM amendment is a measurement definition, not a relaxed threshold. Linux
records an intended memory-cgroup OOM kill in the global `oom_kill` VM event;
`memory.events.local` supplies the non-hierarchical target-cgroup event. The
contract therefore requires target-local `oom_kill >= 1` and unexplained host
delta `global - target_local == 0`. See the Linux
[OOM implementation](https://github.com/torvalds/linux/blob/master/mm/oom_kill.c)
and [cgroup v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).

## Authority boundary and next gate

This pass made no provider request, spent $0, accessed no production system,
created no cloud resource, loaded or ran no preserved image, published or
deployed nothing, pushed no branch or tag, and did not begin E1.

All authorized no-spend M1b engineering work is exhausted. The smallest next
authorization is an explicit infrastructure ceiling for one isolated x86-64
Linux M1b acceptance host and the frozen provider-free live matrix. Until that
is separately approved and every hard gate passes with immutable evidence,
the decision remains `INCOMPLETE/NO-GO`.
