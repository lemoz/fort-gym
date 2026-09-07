# Declared reasoning budget experiment

Status: implementation and condition prepared; no real-model acceptance or
gameplay result is claimed for this new condition.

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

Next execution: one separately owned local request from the already retained
thinking-v1 pause, with its source unchanged and no action execution. If the
transport returns a complete accounted action, begin a new native campaign
from the original seed using the native-verified tick-cap correction. The old
pair ran before that correction, so it is not a strict one-variable gameplay
comparison against this new run. Retain any diagnostic failure without retry.

The year-two success criteria, full campaign envelope, actual-versus-unknown
cost reporting and repeated multi-model requirements remain unchanged.
