# Typed action contract experiment

`local_inference.action_schema: typed_native_parameters/v1` is an opt-in decoder
grammar. Existing conditions omit it and retain `loose_parameters/v1`, unchanged
tool hashes, native parsing and execution. A checkpoint cannot acquire the new
grammar during continuation: the actual tool hash and full local condition are
already part of its identity.

The new grammar has one branch per existing campaign action. DIG requires an
explicit choice of dig, channel, chop or gather. DIG and UNSUSPEND rectangles
require exactly three integer coordinates for both area and size; LABOR exposes a
real boolean. BUILD's optional opposite corner and FARM's optional seasons remain
available. INTERACT still requests zero ticks. This adds no chosen action, game
coordinate, build order or automatic gameplay repair.

Native parsing and legality checks are unchanged. This is a constrained-decoder
contract, not a new native validator or proof that an unconstrained response is
valid. The controller must continue accounting for invalid returned responses.

## Actual local copy test

[Pinned model and receipts](../experiments/evidence/local_qwen35_9b_feasibility_20260906.json)
retain both diagnostic attempts. The local Qwen3.5 9B Q4_K_M model, llama.cpp
b10516, sampling settings, disabled thinking, three supplied examples and their
order were identical. The model-visible schema and decoding grammar changed.

| Decoder contract | Exact copies | Accounted responses | Tokens |
| --- | ---: | ---: | ---: |
| Existing loose parameters | 2 of 3 | 3 | 1,207 |
| Typed native parameters | 3 of 3 | 3 | 5,303 |

The typed response preserved the supplied gather mode, boolean false, coordinates
and requested ticks. Its actual schema hash is
`bb627b6a772969459d08e92cd7b2ee61e254e72a2c95746c631cee89c3214e66`.
All six responses have real usage receipts and the declared model alias/runtime
fingerprint. No native game was loaded or action executed. Both temporary servers
were independently verified stopped. Metered model API charges are zero; operating
costs are unmeasured. One tiny copy check does not establish a general error rate,
causation for earlier autonomous failures or improved fortress management.

## Historical payload limit and new measured transport

A provider-free reconstruction of fourteen retained native requests preserved their
current observations, exact model memory and correction messages. None fit the
existing 22,000-byte request bound after adding this grammar, even with all older
history removed. The irreducible sizes ranged from 27,461 to 31,226 bytes. This used
the historical Ollama serializer, not a completed native llama.cpp integration.

The separate [llama.cpp condition](../experiments/campaigns/local_native_llama_typed_v1.json)
now measures the exact generation body using the pinned server's non-generating
`/v1/chat/completions/input_tokens` endpoint. A 65,536-byte payload ceiling is
independent of the 32,768-token context, 1,024-token output allowance and 512-token
headroom. Returned prompt usage must equal the measured count. Valid returned
usage is accounted before post-response checks can reject a response.

[Actual adapter evidence](../experiments/evidence/local_llama_adapter_20260906.json)
records another three exact copies and 5,303 accounted tokens. Two retained native
input boundaries fit with their current facts and exact memory intact: 5,466 and
7,992 prompt tokens, with no older history omitted. These input checks generated
no actions and made no native RPC calls. They do not supersede the historical
0-of-14 result under the old serializer and smaller byte limit.

The local launcher verifies the pinned release archive, installed members and
weight-file SHA before starting a temporary one-model server. API metadata and
chat-template digests independently guard the active endpoint; they are not a
cryptographic weight-file hash attestation. Model files, raw requests and raw
receipts remain private artifacts, not public repository content.

Do not enable this profile in a historical condition or resume an older model
checkpoint. New native campaigns start from the original digest-bound save.
Generic failed-decision continuation is still unresolved. A larger schema and
successful context checks do not establish useful autonomous gameplay.

Server contract: [pinned llama.cpp documentation](https://github.com/ggml-org/llama.cpp/blob/b10516/tools/server/README.md).

## Separately declared thinking-mode follow-up

[The follow-up condition](../experiments/campaigns/local_native_llama_thinking_v1.json)
enables the same model's thinking mode with a 2,048-token output allowance, eight
maximum dispatches and four-decision segments. The original non-thinking condition
and request serialization remain unchanged. Both modes require a real boolean,
are included in the exact token-count request and are checkpoint-bound. A prior
checkpoint cannot silently switch modes. All returned completion tokens count,
including any reasoning tokens; a truncated response remains a failed response,
not an executable command.

This is a development hypothesis, not evidence that reasoning solves repeated
waits. It keeps the original native starting save, observations, factual control
reference, typed grammar and sampling. The mode, output allowance and execution
bounds differ, so it is not a single-variable ablation or a model ranking. No
additional game instructions, automatic actions or human-selected build order are
introduced. The declared configuration alone does not establish execution.

The [publisher's model card](https://huggingface.co/Qwen/Qwen3.5-9B) documents thinking
and non-thinking modes. Local runtime behavior and native outcomes still require
their own receipts.

The [actual thinking-mode native result](../experiments/evidence/local_native_llama_thinking_20260906.json)
records eight accounted responses, 58,359 tokens and 5,000 native ticks. The model
gathered, attempted chopping, changed commands after two rejections, and increased
observed wood stock from 3 to 12. No construction was initiated. The final cursor-8
checkpoint covers every command and response, and teardown was independently
verified. This is resource acquisition, not completed development or year-two success.

The website keeps compatibility diagnostics separate from its nine native campaign
rows. Unit, endpoint and frontend test-double checks do not establish deployment,
browser acceptance or gameplay success.
