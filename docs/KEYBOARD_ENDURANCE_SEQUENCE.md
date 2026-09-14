# Host-side endurance continuation

This optional coordinator serializes the already-reviewed operators for the
existing `astra-keyboard-endurance-v1` campaign. It does not add game controls,
change the model or prompt, rebuild the native runtime, reset memory or usage,
extend the declared budget, create a VM, or publish a recorded replay.

It is deliberately campaign-specific. The required `run_continue.py` and
`relay.py` are retained in the owning project's
`fort_gym/artifacts/selected-workshop-study-20260912/astra-keyboard-endurance-runtime`
directory. Their exact content hashes are pinned. The runtime worktree must
remain clean at `4b526b5636e6f568a4cae1a1227d746d9c6922c3`; its image is unchanged.
This is not a portable replacement for the general native owner CLI.

## Contract

Start only after the previous native operator has finished, its VM teardown
has settled, and this coordinator's exact revision has passed review and CI.
Never attach it to, interrupt, or restart an already-running native window.

For each completed window the coordinator verifies its operation receipt and
native audit, checks the inherited cumulative accounting, and exports only that
window's new frames. It then invokes the existing continuation operator for at
most 64 further responses. That operator retains current VM/storage/image checks,
per-call subscription admission and mandatory teardown. No paid API fallback,
purchase, reset or new cloud VM is introduced.

The cumulative ceiling remains 1,028 responses and 40,000,000 returned tokens.
An invocation also declares its maximum new windows (1–16); neither a boundary
nor a stopped owner establishes fortress success. A known zero living population
stops sequencing; missing population is not converted into a death count.

The coordinator observes its owned supervisor process rather than using a
short observation timeout to restart gameplay. A failed live-viewer launch does
not terminate the native owner. There is no automatic native retry. On an owner
failure it retains the actual outcome and stops for inspection. A signal stops
only its own supervisor, which performs the existing native teardown.

The live relay publishes captured screens and explicit chosen actions only.
It does not publish private memory or raw model transcripts, and a chosen action
is not described as verified execution. Exported replays still require separate
website validation and publication; the coordinator never claims that delivery.

## Invocation

Use resolved absolute paths to the existing operators, frozen runtime source,
and previous completed operation. The output must be a new direct child of the
operator directory. Do not reuse a consumed output identity.

```sh
python -B -m scripts.campaign_keyboard_endurance_sequence \
  --operator-directory /absolute/existing/operators \
  --runtime-source /absolute/frozen/runtime-worktree \
  --previous-operation /absolute/existing/operators/continuation-132-196-operation/result.json \
  --output /absolute/existing/operators/new-sequence-output \
  --max-windows 13
```

This example is not authorization or a claim that decision196 has completed.
Verify the actual saved cursor before activation. The same owning project stores
the isolated source worktree at `fort_gym/artifacts/worktrees/endurance-sequence`.

`plan.json` pins the exact coordinator/operator/relay bytes. `events.jsonl`
records launch and verified checkpoint boundaries. Per-window owner/relay logs,
native audits, sanitized recordings and `result.json` preserve actual outcomes.
These are evidence, not disposable cache. Original native saves are never edited.

## Verification

The focused offline suite passed 213 tests (two existing deprecation warnings),
including 48 coordinator tests. It covers altered receipts, failed audits,
boundary and budget mismatches, shutdown requirements, interruption, observer
failure, launched-window accounting and cleanup after logging failure. Scoped
Ruff and coordinator mypy passed. The complete local suite passed 5,797 tests
with ten skips and eight existing warnings. Its retained JUnit report has SHA256
`9f2627c35c9e792a597f45537161bc1b7351fcb395db0f3d57ef14d2f52a98ed`.
Repository-wide Ruff (ten diagnostics) and mypy (465 errors in 27 files) remain
at the unchanged native-source baseline; those broader checks are not green.
Exact-head CI and activation results are recorded separately. These offline
checks make no game or model calls, and this document does not claim activation.
