# Local Qwen3.5 thinking comparison

Status: both attempts ended with verified teardown and complete checkpoints.
The thinking trial paused after eighteen commands and 36,000 ticks when its
nineteenth response exhausted the declared output allowance without an action.
All nineteen responses and 184,117 tokens are accounted for. It attempted three
rejected BUILDs, two accepted and two rejected chopping commands, and eleven WAITs.
Seven citizens and 53 drink units remained; no workshop, placed bed or farm was
completed. See the [terminal paired result](LOCAL_THINKING_PAIR_RESULT.md) and
its versioned manifests. Neither attempt reached year two.

The [clock correction](CAMPAIGN_NATIVE_TICK_LIMIT.md) now has separate native
acceptance at `eca52a53021c8889ee9e63882f2184084590d391`; neither model trial used
that correction. The [next local output-budget diagnostic](LOCAL_YEAR_TWO_OUTPUT_REPLAY.md)
is declared separately. It does not resume or rewrite either campaign; consult
[campaign status](CAMPAIGN_STATUS.md) for its current execution state.

The [baseline result](https://github.com/lemoz/fort-gym/blob/5bcbfc9562837379e4a6ba78ad625b4ddef20fc3/docs/LOCAL_YEAR_TWO_BASELINE_RESULT.md)
records 32 model-selected WAITs, 32,000 ticks, seven citizens, 53 native drink
units and no completed development. All 321,472 reported tokens reconcile.
Periodic checkpoints 8/16/24 and final checkpoint 32 independently verify.
The baseline controller is paused at its invocation limit, not collapsed.

The completed thinking operator was a separate one-use launch with SHA-256
`5db1c2515c0784019784e791cadeaae945cf24873660b2db0aa1d17ab2ebd854`.
It requires the baseline teardown receipts, rechecks stopped VM profiles and the
loopback listener, verifies all pinned identities, and owns cleanup. There are
no cloud VMs, hosted model calls, gameplay coaching or production deployment.

The first seven thinking decisions also exposed an inherited clock cap: the
model requested 2,500 ticks each, but the frozen adapter requested and received
2,000 from the native controller. Baseline requests were 1,000 and did not hit
that cap. [The observed limit and candidate correction](CAMPAIGN_NATIVE_TICK_LIMIT.md)
are documented separately. Preserve both original runtimes and
report actual elapsed ticks; the correction is not installed in either run.

## Observed reason for the experiment

The [first twelve committed baseline actions](../experiments/evidence/local_native_qwen35_prefix12_20260906.json)
were all model-selected WAITs. They advanced 12,000 native ticks, consumed 106,661
reported model tokens, and returned normally with 94–138 completion tokens each,
well below the 4,096-token allowance. The actual packed requests preserved current
calendar, population, work, crew and fort facts. There were no native digging or
construction jobs at those sampled decisions. This is the historical prefix
that motivated preregistration, not the final outcome.

The observation motivates testing the model's optional thinking mode. It does not
establish the cause of repeated waiting. Do not change the baseline's prompts,
actions, memory, seed, budgets or runtime to rescue it.

## Preregistered matched follow-up (completed, preserve unchanged)

Use [direct-response v1](../experiments/campaigns/local_native_qwen35_year_two_v1.json)
and [thinking v1](../experiments/campaigns/local_native_qwen35_year_two_thinking_v1.json).
Only `local_inference.enable_thinking` differs after excluding descriptive
experiment identity, hypothesis and notes; the regression test enforces this.

Both runs use the same Qwen3.5 9B quantized file and digest, context, sampling seed,
temperature, schema, native seed, output allowance, checkpoint policy and cumulative
campaign budgets. Keep execution at `fad9d80c0a2e7aace8380b47b009db5edaf6bd2e` and
the same private derived image used by the baseline. The later configuration
publication revision is not the executed-code revision.

Start a NEW campaign from the unchanged digest-bound seed, not a baseline
checkpoint. Compare the first bounded segment of up to 32 model decisions,
including any earlier failure or pause. The 4,096 output-token ceiling includes
thinking; do not silently raise it after an output-limit response.

Report actual native development, action outcomes, elapsed ticks, population,
native drink units, checkpoint/cleanup integrity, accounted tokens and output-limit
pauses. A changed action mix alone is not a functioning fortress. Preserve original
traces and usage; reporting-code corrections must identify a separate revision.

One matched pair is exploratory. Repeat attempts and three-model comparison before
strong claims. The overall requirement remains a functioning autonomous fortress
after 403,200 elapsed ticks, continuation into year two, and verified website and
remote delivery.
