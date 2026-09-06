# Local Qwen3.5 thinking comparison

Status: follow-up condition declared, not executed. The direct-response baseline
is still running; its first segment must finish and its owned resources must be
verified stopped before the follow-up starts.

## Observed reason for the experiment

The [first twelve committed baseline actions](../experiments/evidence/local_native_qwen35_prefix12_20260906.json)
were all model-selected WAITs. They advanced 12,000 native ticks, consumed 106,661
reported model tokens, and returned normally with 94–138 completion tokens each,
well below the 4,096-token allowance. The actual packed requests preserved current
calendar, population, work, crew and fort facts. There were no native digging or
construction jobs at those sampled decisions. This is a prefix of an ongoing
experiment, not its final outcome.

The observation motivates testing the model's optional thinking mode. It does not
establish the cause of repeated waiting. Do not change the baseline's prompts,
actions, memory, seed, budgets or runtime to rescue it.

## Matched follow-up

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
