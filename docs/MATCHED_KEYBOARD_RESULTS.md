# Matched keyboard pilot results

The `/campaigns` page has a separate **Matched model trials** section and a
read-only `/public/keyboard-cohort` endpoint. It follows the six slots in
`experiments/keyboard_matched_pilot_20260910/cohort.json`, in declared execution
order. The older exploratory Astra campaign remains separate.

## First published window

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
- The Year-Two goal, continuation experiments, remaining model trials and live
  matched-trial publication remain open.

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
