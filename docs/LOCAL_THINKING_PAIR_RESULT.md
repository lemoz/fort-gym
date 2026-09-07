# Matched thinking trial: resource actions, then a checkpointed output pause

The first pair of local year-two campaign segments is complete. These are two
attempts with the same Qwen3.5 9B weights, original seed, frozen game adapter,
context, sampling and budgets. Optional thinking is the sole configuration
difference after descriptive IDs, hypothesis and notes are excluded. This is
exploratory evidence, not a model ranking or a repeated-trial estimate.

| Observed outcome | Thinking off | Thinking on |
| --- | ---: | ---: |
| Committed commands | 32 | 18 |
| Actual elapsed ticks | 32,000 | 36,000 |
| Accepted / rejected commands | 32 / 0 | 13 / 5 |
| Accepted chopping commands | 0 | 2 |
| Completed workshops, placed beds, farms | 0, 0, 0 | 0, 0, 0 |
| Citizens, first to last observation | 7 to 7 | 7 to 7 |
| Measured drink units, first to last | 60 to 53 | 60 to 53 |
| Accounted model responses | 32 | 19 |
| Reported tokens, including paused response | 321,472 | 184,117 |
| Stop reason | One-segment invocation limit | Model output limit |
| Final checkpoint covers all commands and usage | Yes | Yes |

The non-thinking baseline selected only WAIT commands. The thinking trial tried
three workshop commands, all rejected, and four chopping commands, two accepted.
Its other eleven commands were WAITs. The nineteenth response consumed all 4,096
output tokens and returned no action. No game command was dispatched for that
response. The runner recorded its 12,889 tokens, paused at native year 30 tick
52801, and verified a complete checkpoint at decision cursor 18. Periodic
checkpoints at 8 and 16 also verify.

## What this comparison does and does not establish

Thinking coincided with more varied actions and two accepted chopping commands
in this pair. It did not produce completed construction or a demonstrated
self-sustaining fortress. Neither attempt reached one full elapsed year
(403,200 ticks). Matching limits do not mean equal decision counts, tokens or
elapsed game time; these are observed stopping outcomes, not normalized scores.

The frozen adapter had a 2,000-tick internal cap. All eighteen thinking commands
requested 2,500 ticks but actually advanced 2,000 each. Baseline requests were
1,000 ticks and were unaffected. Both attempts used the same code, but this
limitation affected their chosen actions differently. Results report actual
ticks. The separately published propagation fix is not part of either run.

Food, wood and stone stocks remain unknown in the website projection because
their observations lack the required source/freshness evidence. Accepted
chopping is not interchangeable with a validated stock count. Drink stock
changes do not prove production rates. No historical observations were rewritten.

Both game containers, owned model processes, tunnels and the isolated local VM
were verified stopped. No cloud VM or hosted model request was used. Metered
model API charges are $0; hardware, electricity and application costs are unknown.

## Inspectable evidence and next experiment

- [Baseline result](../experiments/evidence/local_native_qwen35_year_two_baseline_20260906.json)
- [Thinking result and checkpoint audit](../experiments/evidence/local_native_qwen35_year_two_thinking_20260907.json)
- [Paired conditions, result digests and outcomes](../experiments/evidence/local_native_qwen35_thinking_comparison_20260907.json)
- Execution revision: `fad9d80c0a2e7aace8380b47b009db5edaf6bd2e`
- Thinking condition publication: `7bc15d160ea251bf1b07eb31615c510ea80a4ff9`
- Offline reporting revision: `5bcbfc9562837379e4a6ba78ad625b4ddef20fc3`

The new reader projects retained native evidence without editing original
reports. The original traces, reasoning and game saves stay private; published
files contain bounded outcome summaries and verification digests.

Next: verify the corrected tick-limit adapter in a separate native fixture,
then predeclare a continuation/output-budget experiment. Increasing output
budget is a hypothesis to test, not proof that construction or sustained play
will improve. Preserve this pair unchanged. Strong comparisons still require
repeated attempts across at least three models, and the full goal still requires
a functioning fortress into year two and beyond plus verified website delivery.
