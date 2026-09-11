# Displayed-key Astra pilot publication

This folder contains the read-only exporter for the first independent displayed-key
trial. It derives public metrics and all 32 decision boundaries from the retained
native trace, after checking the exact terminal audit and its source hashes.
It does not run the game, invoke a model, change a checkpoint, or rerun the audit.
Private prompts, provider event bodies and machine paths are not published.

The generated result is `../evidence/keyboard_binding_astra_r1_20260911.json`.
The earlier startup and native diagnostic records remain immutable. This pilot
uses a different control condition from the historical six-attempt cohort.

Run with the project Python environment:

```sh
python experiments/keyboard_binding_results_20260911/export.py
```

The command writes JSON to stdout only. Reproduction needs the preserved private
`keyboard-bindings-astra-r1-v1/attempt` artifacts and frozen keyboard-binding
implementation worktree. Missing or changed evidence fails closed.
