# Multi-segment displayed-key result export

`export_window_v2.py` adds audited multi-segment continuation support while
preserving the executed `export_window.py` source and all historical result bytes.
It is a read-only exporter, not a game runner, model caller or terminal auditor.

For the new private window-audit schema, it resolves the original checkpoint
from the audit's hash-bound sources, runs the existing frozen whole-window
checkpoint verifier again, reconciles its totals with the terminal audit, and
exports every saved segment. Each segment retains its parent hash, cursor,
tokens, elapsed ticks, metrics and actual subsequent-load flag. The last save
does not gain a fresh-reload claim merely because it was saved.

The public continuation schema remains v1, with additive `checkpoint_segments`
and `audit.saved_checkpoints_verified` fields for multi-segment windows.
Single-segment historical exports retain their old shape. A zero-response
admission pause retains its new saved checkpoint without fabricating activity.

This prepares the decision-96-to-256 result path. It does not publish an outcome
for that still-running experiment, change the active model or game, update the
website, merge main or deploy anything.

## Verification

- 141 displayed-key public-record/export/declaration regression checks passed.
- Two integration checks ran the actual journal/checkpoint verifier over
  deterministic fake-runtime complete and paused two-segment evidence.
  These are not native gameplay acceptance.
- Real prior 32-to-64 and 64-to-96 private audit/evidence replay preserved every
  published JSON value. The 64-to-96 serialization is byte-identical.
  The 32-to-64 published file has two trailing newlines versus one emitted;
  the initial strict byte check caught that difference. Only trailing newline
  count differs, and the historical file was not rewritten.
- The initial integration-test collection error (missing parametrized argument)
  is retained separately; the corrected two-case run passed.
- Changed-file Ruff and whitespace checks passed. No new full-suite or CI claim.

Exporter SHA256:
`59d9a4a2a0948cec3d409ed9885609306c1b8b219a586cf616376e9908cb09c4`

Private integration report SHA256:
`3e8a9f880c462c5725603936f2a6b597d74b3719f064fbc1022de0e4cb3f21a5`

Private historical replay report SHA256:
`bdee36951a06a052befe1d6dbf6b908a3ce68e6efe6ac43b9f441645d54f531e`

Run the CLI with the new terminal audit SHA, exact owner name, and prior public
result name/SHA only after the native owner is terminal and the independent
terminal audit has passed. Preserve and publish all returned checkpoint
segments; a website reader must not collapse them into one final checkpoint.
