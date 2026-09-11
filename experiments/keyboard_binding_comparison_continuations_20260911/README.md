# Matched displayed-key own-save continuations

These are deterministic continuation configurations for the unchanged six-attempt
cohort declared at `61fcca7177d8b66ddd7e12e4be0ab53bda5ffd5b`.
They do not change the frozen fresh-start plan or claim a new run has launched.

Prepare a saved attempt with:

```sh
.venv/bin/python -m scripts.campaign_displayed_key_window \
  --campaign-id bindings-comparison-20260911-sol-r1
```

The source-linked comparison reader verifies the selected public result, model,
replicate, seed, native source, image, configuration digests and exact saved
64-response boundary. Preparation additionally requires the original cohort and
all six configuration digests, settled usage and unchanged campaign ceilings.
It emits one 64-response own-save window ending at 128, preserving the same prompt,
memory, usage, controls, observations, measurement profiles and save procedure.
No restart, prompt change, budget extension or model-specific adjustment is added.

The Sol and Terra r1 files are derived from their already published saved results.
Other attempts receive configurations only after their own settled results exist.
Incomplete/failed first attempts remain in the comparison; they are not silently
restarted or treated as successful checkpoints by this preparation function.

Before running, the owner still must verify the actual private checkpoint and
usage prefix, source/image/condition identity, fresh account headroom, one-VM
capacity and native reload. It must keep receipts and tear down the VM. A prepared
configuration or offline agent-state restoration is not native gameplay, a fresh
game reload, paid-spend admission, or completion of the broader Year-Two goal.
Finish the predeclared fresh-attempt sequence before starting this next comparison
stage. The existing native runner accepts these windows. The bounded host owner
and terminal export are integrated below; native execution still needs validation.

## Reusable state and courier checks

`continuation_state.py` now replaces the one-off offline Sol check for this stage:

```sh
.venv/bin/python experiments/keyboard_binding_comparison_continuations_20260911/continuation_state.py \
  --window experiments/keyboard_binding_comparison_continuations_20260911/terra-r1-window-64-128.json
```

It uses a separate process for the public preparation reader so its package does
not mix with the frozen native checkout. The actual checkpoint files, parent
terminal audit, saved agent configuration, memory, prompt, usage and history all
verify before it emits an allowlisted offline receipt. Both real Sol and Terra
saves passed, retaining 1,258,321 and 1,589,877 tokens respectively.

`window_courier.py` wraps the existing bounded native courier. Before the first
model invocation it checks the exact restored agent, trace/usage prefixes,
previous-action feedback, native clock and saved fortress metrics. The current
screen may differ because the game can reload into its default menu; the guard
does not navigate or repair that menu. The frozen courier retains its full memory
chain and per-call subscription checks after the initial gate.

The loaded-state gate has synthetic contract coverage, including all six slots
and rejection before dispatch on a mismatch. It has not yet run in a new native
continuation. These two modules do not own a VM; the outer lifecycle below does.

## Bounded execution and terminal export

`local_owner.py` binds a window to its own parent evidence volume and a distinct
unused output volume. `local_lifecycle.py` mounts the parent read-only, retains
each cleanup outcome, and always attempts teardown of the owned VM. It does not
delete retained evidence, grow storage, create a cloud VM, reset allowance or use
a paid fallback. An unchanged original save is checked again at shutdown.

Supply the exact pushed owner revision and its successful CI run:

```sh
.venv/bin/python experiments/keyboard_binding_comparison_continuations_20260911/local_owner.py \
  --window experiments/keyboard_binding_comparison_continuations_20260911/sol-r1-window-64-128.json \
  --declaration-revision REVIEWED_OWNER_SHA --ci-run PASSED_CI_RUN --preflight
```

The owner refuses continuation until all six predeclared fresh attempts have
reported outcomes. A complete first-attempt report does not make a failed save
eligible: the selected parent must independently pass its own-save checks.
Remove `--preflight` only for the declared window. Each identity is write-once.

After the owner exits, `terminal_review.py --window WINDOW --declaration-revision
REVIEWED_OWNER_SHA` reconciles the native checkpoint chain, first-load gate,
model memory, provider receipts, key execution, measured clocks and teardown.
A controller exit alone remains `terminal_pending_audit`, not accepted gameplay.

`publish_result.py --audit AUDIT --audit-sha256 AUDIT_SHA --window WINDOW --output
NEW_RESULT_JSON` emits only allowlisted facts under `experiments/evidence`.
Commit that immutable result before recording its digest/revision in the
comparison index. Website publication is a separate verified step. Neither a
saved result nor its export infers fortress success, production rates or rankings.

Pre-launch allowance denials and infrastructure failures retain their private
owner result but cannot pass the settled-save auditor. Preserve and explicitly
classify them in the comparison; do not rerun the same identity or label them as
saved. Their public failure projection is not supplied by this settled exporter.

Validation so far covers synthetic lifecycle/audit/export contracts and offline
specification against the real Sol and Terra saves. No new 64-to-128 native
window or fresh final-save reload is claimed by these implementation checks.
