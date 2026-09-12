# Year-Two integration candidate

This candidate joins the tested native harness, published viewer and current
matched-comparison tooling on main's ancestry. It is isolated from all executing
game, model courier and observer checkouts. It is not a new experimental condition
and has not been used to replace a running cohort's frozen source or image.

## Source boundaries

| Component | Retained source |
| --- | --- |
| Main ancestry | `f1aa05f429c189b67891cf2629e8e00329222aca` |
| Native harness | `d22f28d99f4fd103188979e964e148139d3f3efd` |
| Native merge | `72f732546f1b6fa48a8074c582b8562f2592b92c`; tree exactly `2cf88a83406d01954de3ea1ad550caa293f87f2a`, identical to frozen native source |
| Published viewer | Eleven feature commits from `84bdc44c3` through `c763742f6e45d96c9b82df10a9776ee5bbbcb8fc`, then Terra own-save replay `900e3eba6acd254ea340ecad0585b883279914ca`, with cherry-pick provenance |
| Inherited-loss audit | `bb8516aa6a27d6ba92bee39f9769adcfb7095d6c` |
| Rejected-choice observer and exporters | `7cd3b96763998abfd99ed623630d658320a27918` |
| Matched comparison, own-save tools and public records | 61 source files copied byte-for-byte from `727514096d8ec4fde22e4a0f47b5f7bf1bd5bd4e` |
| Terra own-save result and index | `deb53296492a33cf163ca40b8f067bee11ce6308` and `293b4ca8ee1262d3bf5e7a029130b6cf16ecd300`, with cherry-pick provenance |

The broad website and goal branches include unrelated historical calibration,
provider and environment-layer work. Those branches were not merged wholesale.
Existing main campaign navigation is retained alongside the homepage spectator.
All twelve recording payloads are unchanged from the published viewer source.
The integrated API reads its live-feed directory through the same settings
object as the other campaign endpoints. Observer tests follow the current split
between player and data-loading helper and the twelve-window catalog.

The matched source snapshot contains six first-boundary outcomes, Sol's
128-budget startup failure and Terra's saved 128-response continuation.
Later results on the goal branch must be integrated
as separate immutable updates; this snapshot does not claim live queue status.
The old owner README files are retained unchanged because they describe frozen
execution sources. Start with [the current entry point](YEAR_TWO_QUICKSTART.md)
instead of treating a dated historical note as a launch instruction.

## Validation

The initial integration head `5cedb5e91e0405e3b2ae0065c9a230a7ff02db88`
passed CI run `34666311317`. Its displayed-key delta and binding dispatch paths
received a partial source review with 198 focused tests passing. This is not a
full review or a main-merge decision. The following full-suite counts describe
that original candidate; the Terra update is validated separately below.

- Native/main ancestry merge alone: 5,056 tests passed, ten skipped.
- Native plus current viewer and observer: 5,164 passed, ten skipped; one
  sandbox-denied socket test then passed separately with localhost access.
- Combined candidate including all 61 exact-source files and current guide:
  5,398 passed, ten skipped, seven dependency/deprecation warnings, with
  localhost access enabled for the existing socket test.
- All 48 Node player, gallery and comparison contracts passed.
- The source comparison reader reproduces both bundled website tables exactly
  as JSON, with six outcomes at 64 decisions and one at the 128-decision budget.
- Selected changed Python files pass Ruff. The native parent has ten existing
  repository-wide Ruff findings and 465 mypy errors in 27 files; these are not
  represented as passing whole-repository static checks.

This is source and regression evidence, not a new native gameplay acceptance,
clean-machine provisioning test, public deployment, independent review decision
or main merge. The full Year-Two goal remains active. Private runtime assets,
save files, model memory, provider transcripts and account material are excluded.

## Terra own-save update validation

The integrated Terra result, index, replay, current catalog tests and guide pass
5,420 Python tests (ten skips and seven existing warnings) and all 49 Node
contracts. The comparison CLI exactly reproduces the bundled six-result64 and
two-result128 reports. Preparing Astra's window still reproduces the original
declared JSON without launching anything.

The verified public release and partial review records are copied byte-for-byte
from goal-branch commit `1fcc81bda`. The original native runtime, all previous
recordings and active observer source are unchanged. Exact-head CI `34667725373`
passed for `bce580ae30782b258453889283c10f1ccba06a7b`; the remaining integration
review is still required before main merge.

## Isolated Python setup and additional source review

The [setup/review record](../experiments/evidence/keyboard_integration_setup_review_176_20260912.json)
binds an isolated checkout and new Python 3.11.15 environment to that same head.
Installation and dependency checks passed. Comparison reports matched the
bundled tables, all three declared model conditions loaded, and the local CLI
served twelve byte-verified recordings with 928 frames. Without an observer,
the public endpoint correctly reported no connected session. The local server
was stopped after verification.

All 659 focused tests passed in the fresh environment, with three existing
dependency/deprecation warnings. The record adds full-source review hashes for
sixteen measurement, accounting, historical-result and observer modules, plus
explicit API/Lua deltas and the screen-only observation boundary. This is a
partial implementer review, not independent approval or review of every changed
file. Generated protocol bindings and fresh-machine native provisioning remain
unverified; no game, VM or model was launched for these checks.
