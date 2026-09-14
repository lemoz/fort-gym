# Continuing the matched displayed-key trials

The existing native runner can resume a saved campaign under the original model,
prompt, control bindings and cumulative budget. The new preparation command emits
that runner's configuration for the matched decision64-to128 stage:

```sh
.venv/bin/python -m scripts.campaign_displayed_key_window \
  --campaign-id bindings-comparison-20260911-sol-r1
```

The command reads the explicit public result index through the shared bounded,
digest-checked reader. It verifies the exact frozen cohort and six configuration
digests, selects the requested model/replicate, and requires a settled 64-response
save with retained usage below the original campaign ceilings. It binds the next
window to that attempt's checkpoint, terminal audit, native revision, image,
condition and trial. The original observation, measurement and save profiles are
copied without overrides; memory and usage are not reset. A changed index during
preparation is rejected instead of mixing two generations of evidence.

Missing, failed or paused first results stay in the comparison. This command does
not restart them or certify their checkpoints. It has no VM/provider transport,
does not acquire launch admission, and does not supply gameplay strategies.

The emitted [Sol window](../experiments/keyboard_binding_comparison_continuations_20260911/sol-r1-window-64-128.json)
was checked against its actual private checkpoint using the frozen native
implementation. Every bound save file verified; its saved agent state restored
offline without modifying memory, usage, prompt or budget history. The native
parser accepts one64-response segment; all1,258,321 prior tokens and2,900 saved
ticks remain accounted. The [offline receipt](../experiments/evidence/keyboard_binding_comparison_sol_r1_window_readiness_20260911.json)
explicitly distinguishes this from loading a fresh game or playing a continuation.

The current fresh-attempt sequence still comes first. Before64-to128 execution,
complete the reusable bounded host owner and terminal-publication path, pin them,
check the real parent files and current runtime capacity, then verify the native
load before the first model call. Keep one local VM/game at a time, fresh per-call
subscription checks and mandatory teardown. Do not alter the already-running
Terra attempt or the frozen fresh-start declaration to integrate this preparation.

Full delivery still requires repeated three-model native outcomes, own-save
continuations, website result updates and the remaining harness integration.
