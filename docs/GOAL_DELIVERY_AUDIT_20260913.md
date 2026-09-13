# Year-Two goal: delivery audit

This checks the original [Year-Two goal](YEAR_TWO_CAMPAIGNS.md) and its
[standard-input phase](ASTRA_STANDARD_INPUT_EXPERIMENTS.md). It does not replace
their requirements or declare the entire goal complete.

## What the evidence establishes

| Requirement | Current evidence | Qualification or remaining work |
| --- | --- | --- |
| Autonomous play into Year Two | Final endurance checkpoint 1028 retains 765,895 elapsed ticks, 19 living dwarves and completed infrastructure; no human gameplay rescue. | The assessment is operating at the declared boundary with production gaps. This is 1.90 elapsed years, not two complete years or demonstrated self-sufficiency. |
| Persistent campaigns | Checkpoint lineage preserves game state, memory, history, usage and action cursor. The final checkpoint has a separate successful native reload. | Keep the save-only receipt and failed first reload comparison unchanged; the later successful reload is separate evidence. |
| Configuration-driven model comparison | Sol Medium, Terra Medium and Astra Medium each have two attempts under declared native-keyboard conditions. Offline commands reproduce both published comparison reports. | The 128-response extension has two Sol infrastructure failures and a declared storage difference. No strong model ranking is justified. |
| Standard input versus optional shortcuts | Three paired Astra Medium attempts from one starting save, with all six terminal 128-response results and original replay records. The aggregate and six replay links are now public on Results. | These are preliminary, single-seed comparisons. Queue insertion is not completed production. |
| Public inspection | The verified public snapshot contains 39 recordings, 3,048 frames, seven saved endpoints, model comparisons, paired-controls outcomes and source-linked evidence. The live feed correctly reports the completed run as stopped. | The paired-controls panel still needs consolidation into the combined release. No currently running game is claimed. |
| Usage and costs | Result records retain returned-token counts and unknown reported charges explicitly. | Subscription usage is not a measured dollar charge. Unknown charges must not become zero-dollar claims. |
| Remote delivery | The combined candidate and evidence are pushed to draft PR #186, with testing tied to individual heads. | Reviewed and merged delivery remains an original requirement. Main has not been merged; a draft branch is not that outcome. |

## Gap closed by this audit

The completed paired-controls study was available on the experiment branch, but
the combined checkout lacked its read-only comparison command, declaration,
six terminal results and aggregate summary. Commit
`26edd37c0f5946bfb4f0a98d30ae432d8d590e7f` on
`codex/year-two-release-outcomes` now includes those ten original files unchanged,
plus a source manifest, replay-binding tests and a guide linked from the current
quickstart. The comparison reproduces the original summary byte for byte.

The exact candidate passed 175 focused checks and the full local suite: 5,946
passed, ten skipped and 58 warnings. Scoped Ruff passed. The existing environment
does not include Black, so no successful Black check is claimed. Exact-head
hosted CI passed 5,783 tests with 173 skips and 58 warnings. The
[release-review receipt](../experiments/evidence/controls_study_release_review_20260913.json)
binds these results to the exact candidate and original evidence hashes.

The increment changes no native runtime, condition, original capture, website
asset or dependency. It makes no model calls and starts no game or VM. Its
source manifest is `experiments/evidence/controls_study_release_source_20260913.json`
in the combined checkout. This integration is not a new native experiment.

## Next work

1. Consolidate the published paired-controls Results panel into the combined
   candidate, retaining navigation compatibility and keeping evidence immutable.
2. Verify the exact combined release and finish its remaining source review.
3. Finish the remaining review and merged-delivery requirement through the
   permitted workflow. Do not retry or bypass the previously denied main merge.

No additional native gameplay window is part of this audit. Extending gameplay
would be a new experiment, not a substitute for closing the delivery gaps above.

## Source records

- [Final save](../experiments/evidence/astra_keyboard_endurance_1028_save_20260913.json)
- [Separate native reload](../experiments/evidence/astra_keyboard_endurance_1028_reload_20260913.json)
- [Final gameplay assessment](../experiments/evidence/astra_keyboard_endurance_1028_gameplay_review_20260913.json)
- [Public final replay acceptance](../experiments/evidence/astra_keyboard_endurance_1028_website_20260913.json)
- [Public paired-controls comparison acceptance](../experiments/evidence/controls_study_website_20260913.json)
- [Previous combined-release review](../experiments/evidence/year_two_release_checkpoint1028_review_20260913.json)
- [Paired-controls declaration](../experiments/evidence/selected_workshop_runtime_v2_declaration_20260912.json)
- [Paired-controls summary](../experiments/evidence/selected_workshop_v2_cohort_20260912.json)

The final native save was revalidated read-only in this audit against its original
history and hashes. Public HTTPS verification also passed again for the retained
website assets, all recordings and source references. That is not a new browser
visual review, fresh service-identity inspection or deployment.

The later paired-controls publication is a distinct static-only delivery at
`2cdfee3131d3792b5cde8c6fadaeef742940f12e`. Its own local and hosted suites each
passed 1,336 tests with five skips and seven warnings. Public HTTPS verified the
table, unchanged original summary, nine source files and all six linked replays.
That deployment freshly checked and preserved service identities, database counts,
host-local files, existing comparison assets and the stopped live feed. It did
not perform browser visual QA or change the native harness. The site retains its
existing architecture and styling; no replacement Sites project was created.
