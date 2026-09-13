# Astra endurance: operation after the first anniversary

Reviewed September 13, 2026. This is a bounded qualitative review, not a model
ranking or a sustainability score. The [source-bound evidence](../experiments/evidence/astra_keyboard_endurance_600_gameplay_review_20260913.json)
separates the saved 517–580 replay from unsaved decisions581–600.

## What is working

Astra is keeping the fortress alive and has demonstrated a useful adjustment to
stalled brewing through ordinary keyboard controls. At decision531 it queued
repeat plant brewing at another still. A new native brewing job at a different
position had an assigned worker, while drink inventory rose from 29 to 54 at that
boundary and reached 104 at decision536. The [public replay](https://fortgym.live/?recording=astra-keyboard-endurance-v1-517-580#watch-root)
shows both the menu action and, at decision533, an assigned brewer alongside the
older inactive brewing job.

This supports a partial recovery, not item-level proof that this one order
produced every observed drink. Later ingredient cancellations and another
brewing attempt remain visible. We have not attributed stock changes to
production, consumption, spoilage or other causes.

| Boundary | Elapsed game ticks | Living / recorded dead | Food / drink | Retained save? |
| --- | ---: | ---: | ---: | --- |
| Decision516 | 345,050 | 19 / 0 | 170 / 29 | Yes |
| Decision580 | 403,050 | 19 / 0 | 73 / 130 | Yes |
| Decision600 | 413,050 | 19 / 0 | 66 / 129 | No, running-window observation |

The first anniversary is 403,200 elapsed ticks. Decisions581–600 provide twenty
post-anniversary observations, but only five actions advanced time, by 10,000
ticks altogether. They are neither twenty independent trials nor twenty equal
time samples. Every native citizen list in this bounded review was complete.
Barrel-making was observed across the twenty boundaries and fishing at two;
these are worker-job observations, not completed-job counts.

## What is still weak

The fortress has nine installed beds, four workshops and three farm plots,
unchanged across the reviewed interval. Food inventory is declining. At
decision600, fifteen of seventeen labor-eligible dwarves were idle.

One older brewing job and five harvest jobs had no assigned worker. The native
helper reported their target tiles in different cached walk groups from checked
citizens. For the older brewing job, this was observed at 63 of the 64 saved
boundaries; the first boundary was explicitly unknown. This is a geometric hint,
not proof of a full path, ingredient access, labor eligibility or the precise
cause of the stall.

The replay also shows planting cancellations saying dimple cup spawn is needed,
while a later kitchen ledger lists five spawn. A ledger count does not establish
that those seeds are available to a particular job. Some world-job lists are
capped at twelve entries; absence from those lists is not evidence that a job
does not exist.

## Assessment and next evidence

The observed fortress is operating, but fragile: its population survives,
supplies remain, some useful work is assigned, and the model can make a
productive-looking adjustment. Productive use of labor and reliable food supply
are weak. There is not yet a verified saved Year-Two endpoint for this campaign.

The next assessment should use the actual checkpoint644 outcome, elapsed time,
food/drink trends, food-related worker activity, connectivity observations and
new development. Do not add a perfect item-flow-accounting requirement before
assessing ordinary fortress operation. Keep rates and accessibility unknown where
they are unmeasured, and do not replace this campaign with a new easier condition.

No hint, gameplay input, model call, runtime change, new VM or website deployment
was made for this review. Native evaluation snapshots stayed separate from
Astra's screen-only observation, and no private model memory or transcript is
included.
