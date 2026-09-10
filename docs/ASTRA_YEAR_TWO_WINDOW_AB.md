# Astra native-keyboard year-two result

Window AB completed all 128 declared decisions and retained 456,582 elapsed
game ticks. This exceeds one full elapsed year (403,200 ticks) by 53,382 ticks.
The agent played through native keyboard controls without human gameplay rescue.
The final save contains 16 living dwarves and zero recorded dead citizens.

The [versioned result](../experiments/evidence/astra_native_keyboard_completed_window_20260910ab.json)
was published in commit `18086313ee34a7df70efe1974f342df882976138`.
The website links to that immutable revision, not the website or runtime branch.
Runtime source remains `3ab9fc4c9f553171206d3d7122402ec4493ef2e6`:
publishing this record did not change the game, prompt or observation conditions.

## Saved progress

| Checkpoint | Retained elapsed ticks | Subsequent fresh reload known at publication |
| --- | ---: | --- |
| 929, starting save | 292,582 | Verified |
| 961 | 340,582 | Verified |
| 993 | 386,582 | Verified |
| 1025 | 410,582 | Verified |
| 1057, final save | 456,582 | Not yet verified |

Checkpoint 993 had crossed the native calendar into year 31 but had not retained
a full elapsed year. Checkpoint 1025 first established the elapsed-year milestone
among these saves. The final native calendar is year 31, tick 70,183.
There were 82 advancing decisions, 46 zero-tick decisions and no clock timeouts.
All four saves, agent memory, trace/usage prefixes and continuation receipts
passed the terminal audit. Game, container and local VM teardown passed.

## What the fortress achieved

At the endpoint it had 13 completed beds (up from 11), eight completed farms,
four workshops, three tables and three chairs. Inventory measured 75 raw-edible
food units with no trader flags and 613 drinks. All 128 after-action food scans
completed; none was substituted with zero because of missing evidence.

The private native citizen-activity audit also contains operating evidence.
Its final sample has two planting jobs, one harvesting job, one fishing job
and 12 citizens without a current job. Across 128 sampled boundaries, planting
appears at 61, harvesting at 10, fishing at 28, eating at 23, drinking at 44,
sleeping at 34 and bed construction at five. These are sampled job-presence
counts, not unique completed jobs or durations; a current job can be waiting,
traveling, interrupted or cancelled.

Taken together, retained survival, constructed beds, retained supplies and
ongoing work support a **post-hoc qualitative assessment that this fortress was
operating at the observed year-two endpoint**. This is one exploratory campaign,
not a preregistered functioning-fortress score or a model ranking. Historical
automatic assessments are not rewritten by this interpretation.

Sustainable self-sufficiency is still unproven. Food ownership/accessibility,
production and consumption rates, and functional room coverage are unmeasured.
There are fewer beds than citizens. Inventory totals and current jobs do not
establish completed production or long-term survival. Resource headroom is also
unproven: peak memory was 1,610,616,832 bytes against a 1,610,612,736-byte limit,
with 11,176 memory-limit events but no OOM events or kills. The peak is retained
as observed, not clamped to the limit.

## Usage and historical failures

The window added 4,608,590 tokens. Cumulative campaign usage is 39,994,420 tokens
across 1,239 returned responses. Including 69,004 historical failed-delivery
tokens, total accounted usage is 40,063,424. Subscription charges are unreported,
not zero dollars. Six historical losses retain at least 48,429 lost ticks plus
an unknown remainder. This window added no rollback or replay.

The 40-million campaign-token threshold checks previously returned usage before
the next dispatch; it cannot cap an in-flight response. This window finished
5,580 campaign tokens below it. Historical failed deliveries are separately
retained in all-attempt totals. These are token accounting scopes, not dollars.

## Evidence and next experiments

The immutable terminal audit SHA256 is
`4008fed9d6fee78132f12f422fe4ff14240c0b7fdaa8801c682ed6c29337deeb`.
It binds native records, actual model receipts, usage, activity samples, all four
checkpoint inventories and cleanup. Its public projection was independently
checked; the original detailed evidence remains in the project-owned artifacts.

Later on September 10, the [separate checkpoint-1057 verification](../experiments/evidence/astra_native_keyboard_checkpoint1057_reload_20260910.json)
reopened the final save and restored its original agent memory, history, usage
and 456,582 retained ticks. It added no gameplay or model calls. The source save
was unchanged; only two load-log lines were appended to its disposable copy.
Full game/container/VM teardown passed. An independent native inventory scan also
verified the corrected brewing reader: 69 units in 34 unassigned plant stacks,
where the old reader reported zero. This is raw inventory, not completed brewing.
The original result and its at-publication reload flags remain unchanged.

Next: run the
[declared six-start matched pilot](KEYBOARD_MATCHED_PILOT.md) across Astra, Sol
and Terra. This exploratory campaign does not substitute for those repeated,
matched trials. Website delivery and native gameplay are separate acceptance
layers; publishing this result is not public deployment or full-goal completion.
