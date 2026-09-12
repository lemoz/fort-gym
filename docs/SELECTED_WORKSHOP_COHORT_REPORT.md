# Repeated controls-study reporting

`scripts/summarize_selected_workshop_cohort.py` creates a descriptive JSON
comparison from an explicit study declaration and supplied terminal result
manifests. It reads files and prints to stdout. It does not launch a model or
game, change evidence, access the network, or publish the website.

For the currently completed first pair:

```sh
python scripts/summarize_selected_workshop_cohort.py \
  --study experiments/evidence/selected_workshop_runtime_v2_declaration_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p1_keyboard_128_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p1_shortcuts_128_20260912.json
```

Add another `--result` for each additional terminal attempt when its native
audit has completed. Do not supply a live-progress or checkpoint-64 receipt.
An incompatible, incomplete or duplicate supplied result is an error, not a
silently excluded observation.

The report checks the declared campaign/pair, source revision, image, model,
reasoning effort, condition hash, saved response boundary, token limit, proof
flags, audit/checkpoint hash format and internal action/tick totals. Input file
hashes are retained. These are manifest-consistency checks, not a rerun of the
native audit or proof that a referenced audit file exists. Original native
evidence remains authoritative.

Each complete supplied pair includes keyboard-minus-shortcuts endpoint
differences. Incomplete pairs have no delta. Missing metrics stay `null`;
unreported charges stay unknown, with a separately labeled known subtotal.
Missing result files mean the outcome was not supplied. They do not establish
that an attempt never ran, failed, or was cancelled. Retain and inspect any
separate infrastructure-failure or budget-pause evidence before interpreting
cohort coverage.

This is a within-declaration controls comparison, not a cross-model leaderboard.
It rejects mixed models, efforts or historical cohorts. Equal decision budgets
do not imply equal elapsed ticks, tokens or wall time. Repeated policy samples
on the same seed are not independent worlds. Supplying every declared endpoint
does not prove a winner, sustainable production, Year-Two gameplay, public replay
delivery or the full project goal.

Focused verification:

```sh
python -m pytest -q tests/test_selected_workshop_cohort_summary.py \
  tests/test_selected_workshop_action_summary.py
ruff check scripts/summarize_selected_workshop_cohort.py \
  tests/test_selected_workshop_cohort_summary.py
```

Tests use the retained first pair and clearly local synthetic fixtures for
edge cases. Fixtures are not run evidence and are never written to public
experiment files or the website.
