# Native clock feedback and forward recovery

## Observed failure

Window i ran frozen source `893b7ff10b66d5c51f4fa8513119fcdbbf5f5641` with one
64-decision segment. It returned 15 Astra Medium responses. Fourteen actions
committed, adding 2,000 ticks; action 310 delivered all five keys and then timed
out requesting 2,000 ticks while the workshop Add Job menu remained open. Its
native calendar stayed at year 30, tick 82,401. The paused final state, repause
receipt and complete native input sequence are retained. No requested time is
counted as actual progress.

The failed window retains 65,600 trace ticks and all 327 accounted responses:
10,696,954 campaign tokens, 10,765,958 including failed deliveries. It used
481,050 new tokens. Charges remain unreported. The latest verified campaign
checkpoint at this failure is 296 / 63,600 ticks. A newer forensic native save
was captured successfully with save profile v3, but is not yet a resumable
campaign checkpoint. Native/container/VM teardown and independent audit passed.
The original failure remains a failure, not a fortress-collapse or cadence-result
claim. Public non-content record:
`experiments/evidence/astra_native_keyboard_workshop_timeout_20260908.json`.

## Clock behavior

The existing no-dispatch deferral now also recognizes the observed exact focus
`dwarfmode/QueryBuilding/Some/Workshop/AddJob`. As with the earlier Build Type
case, read-only probes must attest the same paused runtime, save, calendar and
menu before returning feedback. The harness never dismisses a menu or retries
an input for the model.

Other focuses keep the existing clock attempt. A zero-tick timeout can return
the explicit `fortgym.keyboard-clock-unavailable/v1` receipt only when the
original failed operation, complete unchanged calendar, successful repause and
two fresh matching native probes all verify. The failure fields remain intact:
`ok: false`, `timeout: true`, `clock_dispatched: true` and zero actual ticks.
This differs from a menu preflight that never dispatched a clock operation.
The model receives factual time-unavailable feedback and selects its own next
action. No private evaluation data or recommended key is added to its input.

Partial time, missing samples, mismatched native identity, uncertain pause,
deadline errors and unmarked historical timeouts still stop as unresolved
infrastructure failures. No historical receipt is rewritten or retroactively
treated as a successful original action.

## Recovery after an earlier lost branch

The clock-recovery source validator now binds new journal entries to the exact
parent prefix rather than assuming cumulative response count equals trace
cursor. That old assumption is false after an explicitly recorded save-loss
restart. The new v2 recovery plan preserves inherited discontinuities and all
usage; recovery places the same loss history in its new row, runner and next
checkpoint. The original v1 case keeps its schema and historical behavior.

Offline tests exercise an actual fixture restart, a later workshop timeout,
forward recovery and subsequent continuation without replay, model rescue or
discarded usage. The retained native failure also passes the new read-only
source inspection. These checks are not yet proof of native recovery or further
autonomous play; both require their own runtime evidence.
