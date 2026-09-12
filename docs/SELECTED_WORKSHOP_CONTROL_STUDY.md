# Astra controls study: selected-workshop job entry

Status: representative native job execution verified; paired gameplay not run.
Historical displayed-key results, the integration candidate, and their runtime
images remain unchanged.

## Question and scope

Does removing repetitive workshop job-menu entry help Astra develop a fortress,
when it still has to navigate, select the right workshop, obtain materials, assign
labor through the game, and advance time?

This is a deliberately narrow first shortcut comparison, not the whole historical
assisted mode. It extends the approved three-pair controls phase in
[the experiment goal](ASTRA_STANDARD_INPUT_EXPERIMENTS.md). It does not replace
longer autonomous Year-Two play or the separate repeated three-model comparison.

## Two conditions

Both use Astra Medium, the same original fresh seed, empty initial memory,
120x40 lossless screen text, pinned displayed-key bindings, replacement memory,
and model-requested advances of at most 2,000 ticks per decision.
The only intervention is the available action route and its necessary instructions:

- Keyboard: `native_keyboard_bindings/v1`, the unchanged v4 contract.
- Keyboard plus job-entry shorthand:
  `native_keyboard_selected_workshop_jobs/v1`, a new v5 condition and exchange.

In the new condition, `KEYSTROKE` still does everything the keyboard baseline can.
`WORKSHOP_JOB` adds one batch of 1–5 bed, door, table, chair, barrel, bin or
plant-brewing jobs at the completed workshop currently selected in the native
building-query menu. The complete batch must fit the ten-job queue.
There is no search for another workshop, manager-order duplicate, free material,
instant production, labor change, terrain edit or automatic recovery key.
Other tasks and job types remain available through normal keyboard menus.

The helper uses the selected native building and the runtime's workshop job
definitions. DFHack documents the selected-building and world-job APIs in its
[version-matched Lua reference](https://docs.dfhack.org/en/0.47.05-r8/docs/dev/Lua%20API.html).
It queues ordinary work with the native item/reagent filters. Workers, input
materials and time are still required. A provider-free check of source `8622618c8`
verified actual bed and plant-brewing execution on a disposable checkpoint copy.
Native completion of the other item types has not been separately exercised.

## Native check and launch correction

The [September 12 native receipt](../experiments/evidence/selected_workshop_native_acceptance_20260912.json)
records two retained attempts. The first stopped on a diagnostic screen-label
comparison before creating jobs. The corrected test reused the same immutable
image and succeeded: actual keyboard selection, wrong-workshop rejection,
one job ID per request, paused dispatch, ordinary material filters, observed
workers and inputs, one completed bed, and 25 units of drink after 2,000 ticks.
The wood log and five-unit plant stack were consumed; the brewing barrel remained.
Both game/VM lifecycles were torn down and the source checkpoint stayed unchanged.
Private position reads guided this scripted test, never an autonomous model.

Pre-launch inspection also found that the native worker omitted the v5 prompt
profile when calling the model exchange. A failing regression reproduced it;
the worker now forwards that declared profile for both fresh and continued play.
The existing native receipt remains bound to its earlier source. Build a new
source-bound image with this wiring correction before the first scored call.

## Planned attempts and budgets

Use the conditions and fresh-trial files in
[`selected_workshop_study_v1`](../experiments/selected_workshop_study_v1/README.md).
Run three paired repetitions, one game at a time, with this declared order:

1. `selected-workshop-v1-p1-keyboard`, then `selected-workshop-v1-p1-shortcuts`.
2. `selected-workshop-v1-p2-shortcuts`, then `selected-workshop-v1-p2-keyboard`.
3. `selected-workshop-v1-p3-keyboard`, then `selected-workshop-v1-p3-shortcuts`.

Every attempt starts from the same snapshot receipt, not a previous attempt's
fortress or memory. These are repeated policy samples on one seed, not independent
worlds. Record all attempts, including infrastructure failures. Never replace a
failed attempt under its old ID or reuse an outcome from the earlier model cohort.

Each attempt saves first at 64 decisions and can continue only from its own
checkpoint to the common 128-decision cap, with 8,000,000 cumulative returned
tokens. Do not extend an individual winner in this comparison. Any later endurance
extension gets a separate declaration and is reported separately.
The 128-decision cap cannot by itself cover a full game year with this tick bound.

Before the first scored call, bind one clean source revision, immutable image,
runtime/VM configuration, snapshot bytes and resource limits in a separate
write-once launch receipt. Use those same resources in all six attempts. If any
condition changes, stop the paired comparison at its existing boundaries and
declare the change rather than hiding it. The earlier Astra-r2-only disk
amendment is not a storage declaration for this study.

No GCE launch, paid API fallback, local model, reset or purchase is implied.
Use the existing subscription transport and fresh allowance checks. Returned
tokens are measured; subscription dollar charges are unreported, not zero.
Stop and tear down the owned game/VM after each attempt.

## What counts as evidence

Compare matched 64- and 128-decision boundaries: saved elapsed ticks, population
and deaths, installed beds/workshops/farms, observed food/drinks, counted tokens,
rejections, clock deferrals, and use of each action route. Also inspect the
decision sequence around workshop selection and job entry. Do not count the
model's intent, a queued job, or a sampled current-job observation as a completed
product or a production/consumption rate.

Show individual paired outcomes before aggregate summaries. Three pairs do not
support a strong universal claim about model ability or all shortcut interfaces.
Both conditions expose the same screen/retained-memory channel; internal
workshop IDs, job IDs and private fortress measurements stay in audit artifacts.
Only the explicit action route and acknowledged queue count are added to the
new condition's prior-action feedback.

## Remaining execution work

1. Build and verify the corrected worker image. The representative native job
   check above is complete; do not relabel it as model play or as new-source proof.
2. Bind the exact runtime/resources and execute the declared paired starts.
   Verify live follow during an otherwise-needed game.
3. Audit own-save continuation, failure categories and teardown; publish the
   qualified results and real recorded screens on the existing website.

The viewer code can label a workshop shortcut separately from keys and completed
products. That support is not a new public recording or a website deployment.
