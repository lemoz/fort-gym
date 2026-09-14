# Workshop job-list clock feedback

Development correction only. The six-attempt selected-workshop v2 cohort keeps
its frozen source `5ddf1e6718dab2e8351e8dc24a2afe5071cd2592` and original image.
This revision is not installed in that active cohort.

## Observed issue

In the pair-two shortcut trial, decision 11 queued five beds and requested 2,000
ticks. The original clock receipt retained a zero-tick timeout. Its read-only
native probes agreed on a paused calendar at year 30, tick 20,001, and focus
`dwarfmode/QueryBuilding/Some/Workshop/Job`. The next model decision selected
Escape and space and advanced 2,000 ticks. No operator selected those keys.

The existing menu handler recognizes `Workshop/AddJob` but not `Workshop/Job`.
That leaves the job-list screen waiting through the clock timeout before the
model receives feedback. The original timeout remains a timeout in its evidence.

## Change

Recognize this exact additional focus using the existing read-only, twice-probed
menu-deferral path. It reports zero ticks and a blocked menu to the next model
turn. It does not dismiss the menu, insert a key, change the workshop order,
increase a budget or claim that production completed. Other and unknown focuses
still use the existing clock path. Historical control profiles remain unchanged.

Offline tests cover the exact focus in all current keyboard profiles, neighboring
focuses, legacy profiles and preservation of historical timeout receipts. Existing
clock, modal, checkpoint and continuation tests remain applicable.

Native acceptance on a separately declared post-cohort runtime is still required
before claiming this correction works in the game. Passing tests or recognizing
a recorded focus does not establish that native acceptance.

## Local worktree

Project-owned implementation checkout:
`fort_gym/artifacts/worktrees/workshop-job-clock-feedback`, branch
`codex/workshop-job-clock-feedback`, based on the frozen cohort source above.
No original game artifacts, saves or running source files are modified.
