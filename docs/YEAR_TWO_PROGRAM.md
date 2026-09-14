# Year-Two Autonomous Play and Cross-Model Evaluation

This is the current research program. The owner-approved September 7 direction
is to test how far agents can play and develop a Dwarf Fortress settlement,
starting with Astra Medium on standard game controls. The historical governed
benchmark remains a separate, versioned comparison track. Its gates do not
replace this program's objective or restrict exploratory native-keyboard play.

## What completion means

- A configuration-driven harness can select supported models and declared
  control, observation, display, memory and budget settings without rewriting
  game policy for each model.
- Game saves, agent memory, trace and cumulative usage survive process boundaries
  and resume reliably. Failures retain their original evidence and losses.
- At least one autonomous fortress remains functioning after 403,200 elapsed
  native ticks, then continues into year two and beyond without human gameplay
  rescue. Reaching the calendar threshold alone is not a sustainability result.
- At least three models have been evaluated under declared comparable conditions,
  with repeated attempts before strong capability or ranking claims.
- The website exposes active runs, recorded outcomes and meaningful comparisons,
  including endurance, population, sustainability, development, adaptation, usage
  and cost. Tested source, configurations, documentation and shareable result
  manifests are delivered to the remote repository.

These are joint requirements. Passing tests, publishing a dashboard, completing
a bounded window or demonstrating one checkpoint reload does not finish them.

## Controls and observations

The current [Astra condition](../experiments/campaign_astra_keyboard_memory_contract_20260909.json)
uses `native_keyboard/v2`, `native_screen_text/v1`, a 120x40 capture, model-authored
replacement memory and GPT-6 Astra at Medium reasoning. Its subscription-backed
host courier returns interface events; the native game processes the keys and
the requested simulation interval. A zero-tick decision may still place a job,
change a setting or designate work, so zero time is not synonymous with failure.

The model chooses strategy and can make mistakes and recover. Missing an older
benchmark milestone or losing an individual dwarf is not an automatic exploratory
stop condition. Distinguish actual gameplay collapse from a failed control,
observation defect, provider failure, infrastructure interruption or budget pause.

Keep DFHack shortcuts as a separately declared alternative. Standard-input runs
must not silently receive direct job insertion or instant completion. A shortcut
is not inherently disallowed in every future condition; its use and effect must
be visible, and it cannot be mixed into an unassisted result. Do not reinterpret
the historical governed benchmark's provenance or scores.

Controls, observations and display are independent settings. A larger viewport
or modified menu is an experiment to version and verify against what the model
actually receives, not a hidden mid-run assistance change. The current private
food/resource measurements evaluate the run; they are not extra model perception.

## Current evidence, September 9

The [completed window-x record](../experiments/evidence/astra_native_keyboard_completed_window_20260909x.json)
contains checkpoint 839: 216,582 saved elapsed ticks, 53.7% of the first year,
12 living dwarves, zero recorded deaths, 420 drinks, eight completed farms,
eight beds and four workshops. It retains 1,021 model responses and all prior
usage/loss history. The raw-edible count is 259, including 210 trader-flagged
units; it is not a count of accessible fortress-owned food. Production and
consumption are not established by an inventory increase.

[Window y](../experiments/campaign_astra_keyboard_window_20260909y.json) declares
two serial 32-decision segments from that checkpoint. Its configuration is not a
completed-run result. The running owner's source remains frozen until teardown;
later repository documentation commits do not change the executed revision.

Model selection is implemented and has
[offline coverage](../tests/test_keyboard_model_selection.py), including exact
selection in conditions, transport receipts and restored checkpoints. Those tests
are not three native model evaluations or proof of provider availability.
Year-two success, repeated native comparisons and production website delivery
remain unproven. Local HTTP acceptance, remote branch publication, PR merge and
production deployment must be reported separately.

## Experimental path

1. Continue Astra's own fortress management through verified saves. Check whether
   development and food/drink supply support a functioning fortress through the
   first anniversary; do not end the research when one numeric threshold passes.
2. Repair demonstrated harness defects between attempts or declared continuations.
   Preserve the original failed outcome and account for discarded or unknown game
   time. Never replay an uncertain model invocation or insert a gameplay rescue.
3. Test readability changes only under a new declared display/observation condition.
   Then compare standard input with standard input plus explicit shortcuts, starting
   with three paired attempts from matching saves, observations, memory and budgets.
   These are preliminary control comparisons, not a model ranking.
4. Reuse the stable harness for at least three supported models, with repeated
   comparable starts and declared conditions. A model switch midway through an
   existing model's authored history is not automatically a matched comparison.
   The [matched pilot declaration](KEYBOARD_MATCHED_PILOT.md) supplies six fresh
   starts across Astra, Sol and Terra; actual native results remain outstanding.
5. Publish the recorded outcomes and comparison limits on the website and keep
   the reviewed remote source and manifests synchronized with actual experiments.

Report saved elapsed time, observed-but-unsaved time and unknown losses separately.
Measure completed infrastructure rather than accepted queues. Report food/drink
inventory coverage, ownership/accessibility limitations, and production/consumption
evidence explicitly. Keep model intent and successful key dispatch distinct from
a verified world effect. Do not hide failed attempts behind aggregate scores.

Runtime windows and cumulative dispatch/token limits are operational bounds, not
success predicates or dollar charges. Preserve cumulative usage when extending
a checkpoint-bound allowance. Actual charges, estimates, subscription usage and
reservations are separate facts; an unreported charge is not zero. Operate within
existing spending/infrastructure authority without repeatedly asking for routine
approval. Neither this document nor a config renews expired GCE authorization or
overrides a standing no-deploy restriction.

## Code and historical references

- Current keyboard runner: [campaign_keyboard_native.py](../scripts/campaign_keyboard_native.py),
  [host courier](../fort_gym/bench/agent/keyboard_courier.py), and
  [read-only live observer](../scripts/campaign_keyboard_observe.py).
- [Recovery contract](CAMPAIGN_KEYBOARD_RECOVERY.md) and
  [campaign outcome profiles](../fort_gym/bench/eval/campaign_profile.py).
- [Additional campaign runtime](CAMPAIGN_NATIVE_RUNTIME.md) and
  [website delivery](CAMPAIGN_WEBSITE.md), whose dated milestones are historical
  snapshots, not proof that the current full objective has completed.
- [Historical governed WDSLL](WDSLL.md) and
  [governed experimentation plan](EXPERIMENTATION_PLAN.md). Preserve their original
  gates, conditions and results when running or interpreting that benchmark.
