# Declared reasoning budget experiment

## Recorded model acceptance

The [single-request result](../experiments/evidence/local_year_two_reasoning_budget_20260907.json)
returned a complete, syntactically valid `DIG` action with `finish_reason=stop`:
8,793 input plus 2,210 completion tokens, all 11,003 tokens accounted, in
278.74 seconds. Its serialized request differs from the original only by the
2,048-token reasoning-budget field. Separate reasoning-token usage was not
returned, so exact sampler enforcement is not independently measured here.

The owned worker/model PIDs are absent, the listener is closed, and the original
source is unchanged. No game was loaded and the returned action was not executed.
This is model transport acceptance, not native legality, useful development,
year-two success or a repeated-model ranking. The comparison has differing
cache histories and is not a cold-cache timing benchmark.

Next: start the declared fresh native campaign from the original seed using a
frozen implementation with the verified tick-cap correction. Preserve the
completed historical pair and do not execute this replay's action in their saves.

## Predeclared experiment

The completed thinking-v1 campaign stopped because response nineteen used all
4,096 output tokens without an action. Its exact 4,096-token replay reproduced
that output-limit pause. The separate 8,192-token case retains its declared
limits; do not change or restart it to obtain a favorable comparison.

The pinned llama.cpp implementation accepts `reasoning_budget_tokens` on the
chat request and passes it to its reasoning sampler when the template supplies
thinking end tags. This is supported by the
[pinned request conversion](https://github.com/ggml-org/llama.cpp/blob/b95502ba9/tools/server/server-common.cpp)
and [runtime options](https://github.com/ggml-org/llama.cpp/blob/b95502ba9/tools/server/README.md).
It ends the thinking portion when the declared budget is reached; it does not
prove the subsequent action will be valid, legal or useful.

The [new condition](../experiments/campaigns/local_native_qwen35_year_two_reasoning_budget_v1.json)
allocates 2,048 reasoning tokens within the unchanged 4,096-token total output
allowance. It does not inject a custom message or change the gameplay prompt.
The remaining allowance also covers delimiters, not only action JSON. Check
the real response before claiming runtime compatibility, then test actual
fortress development and long-run endurance, not merely syntactic success.

The optional field is validated as a real integer from zero through one less
than the total output allowance, with thinking enabled and the pinned llama.cpp
transport. Conditions without it keep their exact serialized request bytes.
The same body is used for token preflight and generation. Full condition
identity in checkpoints prevents silently adding this setting on continuation.

The predeclared execution was one separately owned local request from the retained
thinking-v1 pause, with its source unchanged and no action execution. Once the
transport returns a complete accounted action, begin a new native campaign
from the original seed using the native-verified tick-cap correction. The old
pair ran before that correction, so it is not a strict one-variable gameplay
comparison against this new run. Retain any diagnostic failure without retry.

The year-two success criteria, full campaign envelope, actual-versus-unknown
cost reporting and repeated multi-model requirements remain unchanged.
