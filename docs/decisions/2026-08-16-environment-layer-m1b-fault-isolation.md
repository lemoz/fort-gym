# Environment Layer M1b fault-isolation decision

Status: bounded private M1b pass complete on 2026-08-16.

## Decision

**Local components: CONDITIONAL GO for further offline integration work.**

**Local-core acceptance: NO-GO. Full M1b: INCOMPLETE/NO-GO.**

The component work is useful and tested, but it is not yet one coherent
process-per-run system. The API still launches `run_once` in daemon threads,
does not call `ProcessSupervisor`, and keeps the DFHack job clamp at one. The
child registry and parent supervisor can also publish conflicting terminal
truths because registry terminalization can occur before parent process,
container, listener, and lease cleanup.

No real DF/DFHack M1b runtime was executed. The preserved image was loaded
locally for identity inspection but was never started. No paid model or
provider endpoint was called, no production system was accessed or mutated,
no cloud infrastructure was created, nothing was published or deployed, no
branch or tag was pushed, and E1 was not begun.

## What this pass established

- A pure-standard-library process supervisor with durable attempt journals,
  process-group TERM/KILL/reap, cleanup-before-parent-terminal ordering,
  trace finalization, host-wide port leases, and bounded environment and
  co-tenancy evidence.
- An actual 32-supervisor race for one loopback port: one completed winner,
  31 durable lease conflicts, and no losing child process.
- A worker-safe `RunRegistry(recover_interrupted=False)` role and exact
  preassigned external run-ID/config matching across eight fields.
- Eight concurrent real OS worker processes using the mock backend, one shared
  SQLite database, exact preassigned IDs, distinct artifacts, no public shares,
  and zero provider calls/cost. This is engineering evidence only, not CO-8.
- Private-by-default `POST /runs`; publication now requires explicit
  `publish=true`, and calibration publication is rejected before creation.
- An opt-in native DFHack RPC Lua path with fail-closed errors and no CLI
  fallback. Compatibility with the live pinned DFHack 0.47.05-r8 runtime is
  still unproved.
- A central in-process OpenRouter pre-dispatch gate. Strict mode requires a
  provider pin, sends one-provider order with fallbacks disabled, accounts
  each returned response, and blocks the next fake dispatch once either
  positive cap is reached.
- `FORT_GYM_DISABLE_DOTENV=1`, plus provider-variable stripping for scripted
  children.

The final measurement-code digest is
`be4db9de66ce3ceb69053fefe17b156535151f2e930d2266c5925133947302a9`.
This re-locks G7-v5; no paid G7-v5 pair may run without recalibration and
review.

## Verification

| Check | Result |
|---|---|
| Sanitized Python 3.11 regression selection | 208 passed, 8 warnings |
| Loopback supervisor suite | 18 passed |
| Total independently rerun in final pass | 226 passed |
| Local eight-process mock integration | Passed inside the 208-test selection |
| Provider calls / provider cost | 0 / $0 |
| `py_compile` on changed M1b Python surfaces | Passed |
| `git diff --check` | Passed |
| Ruff F/E9/I on new and core M1b surfaces | Passed |
| Broader touched-file Ruff delta | No new findings; the same six baseline findings remain in four legacy files |

JUnit evidence is retained in the private packet at
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1b-fault-isolation-20260816`.

## Frozen gate disposition

| Gate | Disposition | Evidence boundary |
|---|---|---|
| PORT-1 | PASS, local component | Exact 32-way local supervisor race |
| PORT-2 | NOT RUN | Needs a live peer runtime/listener and nonce check |
| COLD-RETRY | NOT RUN | No preserved-runtime startup attempt |
| CO-8 | NOT RUN | Eight mock OS workers are explicitly non-equivalent |
| DF-KILL | NOT RUN | No real DF process |
| HARNESS-KILL | NOT CREDITED | Synthetic descendant process-group cleanup only |
| OOM | NOT RUN | Needs isolated Linux cgroup evidence |
| ENOSPC | NOT RUN | Needs isolated run workspace and separate control evidence |
| CONTAINER-RESTART | NOT RUN | No container was started |
| DAEMON-RESTART | NOT RUN | Needs an external Linux host controller |
| ORPHAN-1 | NOT CREDITED | Local descendant cleanup is not scoped container reconciliation |
| ORPHAN-2 | NOT RUN | No durable supervisor-restart reconciliation exists |
| PROVIDER-ENV | NOT CREDITED | Environment and dotenv controls passed separately, not the exact combined child procedure |
| PROVIDER-NET | NOT RUN | Needs isolated Linux connect capture |
| CAP-FAKE | NOT CREDITED | Substantive second-dispatch block passed, but the frozen zero-cap procedure conflicts with positive-cap validation and was not run end to end |
| CLEANUP | NOT CREDITED | Synthetic callback ordering only; no real runtime residue audit |

The frozen decision rule therefore requires `INCOMPLETE/NO-GO`.

## Blocking integration findings

1. `POST /runs` and `/jobs` do not use `ProcessSupervisor`; screenshots and
   step/admin surfaces still use global runtime state.
2. `run_once` may mark a registry run terminal and return normally even for a
   failed run. The CLI can therefore exit zero while the parent supervisor
   records `completed`, before parent-owned cleanup is reflected.
3. API startup recovery marks all unfinished `running` rows terminal without
   reconciling a surviving external worker or supervisor journal.
4. Provider policy is not propagated from a supervisor spec into `run_once`;
   strict supervision defaults off, and resolved provider/model telemetry is
   not validated before every possible retry.
5. There is no canonical per-run runtime/environment builder, claim nonce,
   container/port/save identity binding, Docker reconciliation layer, or
   control-plane evidence path outside the faulted workspace.
6. Cross-process events remain process-local, so SSE relay/restart behavior is
   not integrated.

## Recommendation and next authority gate

Continue only with a bounded local integration package that gives the parent
supervisor sole terminal ownership, wires the API to an external worker,
creates a canonical child environment and nonce-bound runtime identity, and
adds durable cross-process event relay and restart reconciliation.

After those P0 contradictions pass end to end, the remaining frozen gates
still require an isolated x86-64 Linux host. No such host may be created until
Chris separately approves an explicit M1b infrastructure ceiling. Do not
begin E1.
