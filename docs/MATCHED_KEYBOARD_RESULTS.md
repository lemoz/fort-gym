# Matched keyboard pilot results

The `/campaigns` page has a separate **Matched model trials** section and a
read-only `/public/keyboard-cohort` endpoint. It follows the six slots in
`experiments/keyboard_matched_pilot_20260910/cohort.json`, in declared execution
order. The older exploratory Astra campaign remains separate.

## First three published windows

`matched-20260910-astra-r1` completed all 32 decisions and retained 11,200 ticks
from the shared seed. Seven dwarves remained, with one completed workshop, one
farm and no placed beds. The native snapshot reported 50 raw edible units and
60 drink units. All 32 returned responses are accounted for: 1,043,596 tokens.
Subscription charges are unreported, not zero. The final checkpoint's contents
are verified; a fresh reload of this new checkpoint has not yet been tested.

The bounded game and VM were stopped. The guest poweroff command returned 1;
the VM stop command returned 0 and a separate state check confirmed it stopped.
The record retains both observations. Peak observed container memory was
1,237,028,864 bytes against a 1,610,612,736-byte limit, with no recorded limit
events or OOM kills. That short window does not establish long-run headroom.

`matched-20260910-sol-r1` also completed 32 decisions, retaining 2,500 ticks with
seven dwarves, no completed workshop or farm and no placed beds. Its final native
stocks were 50 raw edible units and 60 drinks. All 32 responses and 792,764 tokens
are accounted for. The new checkpoint is verified but has not had a fresh reload.
Native game and VM teardown passed; both shutdown commands returned zero.

The two records share the source revision, image, seed, execution binding,
control/observation/memory profiles, screen size, reasoning effort and response
limit. The endpoint rejects differences in those matched fields. Their observed
outcomes differ, but neither is a repeated model result or proof of sustainability.

`matched-20260910-terra-r1` completed 32 decisions and retained 7,000 ticks.
Seven dwarves remained, with no completed workshops, farms or placed beds.
The final stocks were 50 raw edible food units and 60 drinks. All 859,063 returned
tokens were accounted for. Its checkpoint and game/VM teardown passed the audit;
a fresh reload of this final checkpoint remains untested.

Before Terra attempt 1, the VM data disk increased from 24 to 32 GiB to retain
prior evidence. The amendment was declared before changing storage. Runtime
source/image, common seed, CPU, RAM, container constraints and gameplay settings
did not change. The page labels both storage conditions; it does not compare
wall-clock performance or claim identical host configurations. Only the pinned
amendment and execution binding are accepted, starting at the declared third slot.

## Live matched-trial observations

`/public/keyboard-cohort-active` is separate from the immutable result table and
from the older exploratory campaign's `/public/keyboard-active` feed.
`python -m scripts.campaign_matched_observe` accepts explicit `--run-dir`,
`--operator`, `--execution`, `--public-dir`, `--owner-pid` and cohort `--index`.
It checks the controller's start-time/command identity, launch binding, model
request digests, consecutive receipts and returned usage. It only reads host
receipts and process identity; it never calls the model, game, container or VM.

The replaceable derivative `keyboard-cohort-active.json` contains allowlisted
metadata, response/token counts, unsettled dispatch claims and a game-time lower
bound from subsequent request feedback. It contains no prompt, screen, memory,
private path, PID or account identity. Fresh starts are identified as independent
seed trials, not a fictitious verified checkpoint zero.

Both API and page expire observations after 30 seconds. Failed process inspection
does not mean the game stopped and never triggers a restart. PID reuse ends the
observer for the original controller. A stopped controller is not a collapsed
fortress, and an owner teardown report is not an independent terminal audit.
The page labels all these observations as provisional, never as a verified save.

## Interpretation

- A finished 32-response window is not campaign success. Each trial must continue
  from its own saved game, memory and usage.
- Unpublished slots contain `result: null`. They are not zero scores and do not
  claim that a worker is stopped, running or failed. This endpoint is recorded
  evidence, not the live-worker feed.
- The UI shows saved outcomes and all after-action decision boundaries, preserving
  unknown measurements. Accepted keys do not prove completed intended work.
- Raw food counts do not establish ownership or accessibility. Stock changes and
  repeated current-job samples do not measure production or consumption rates.
- Equal declared settings and two trials per model are a pilot design, not enough
  for strong rankings or generalization to other worlds.
- The Year-Two goal, continuation experiments and remaining repeated model trials
  remain open. These first windows support no strong model ranking.

## Publishing another recorded result

Audit the native checkpoint, canonical trace, actual model event receipts, fresh
start identity and cleanup first. Preserve private prompts, native assets and
unfiltered operator receipts outside tracked public files. Add a bounded public
projection in a separate data commit, then register its exact path, SHA-256 and
commit in `fort_gym/bench/api/keyboard_cohort.py`. A missing, modified, symlinked
or oversized file makes the endpoint unavailable rather than serving unaudited
data. The immutable evidence link resolves to that data commit.

Tests cover the actual recorded values, source/config binding, unpublished slots,
changed-file rejection, route integration, decision history, unknown values and
refresh failure. The UI retains the prior recorded view if a refresh fails and
labels it as such. Existing campaign and admission endpoints are unchanged.

Repository publication is separate from merge and deployment. This change does
not deploy the public website or claim the full campaign goal is complete.
