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

## Context cost is still open

A provider-free reconstruction of fourteen retained native requests preserved their
current observations, exact model memory and correction messages. None fit the
existing 22,000-byte request bound after adding this grammar, even with all older
history removed. The irreducible sizes ranged from 27,461 to 31,226 bytes. This used
the historical Ollama serializer, not a completed native llama.cpp integration.

Do not enable this profile in a historical condition or simply resume an older
save. The next implementation needs a separately declared modern local transport,
measured token/context handling, verified native request fit and reliable failed-
decision continuation. The larger schema is a measured tradeoff, not a reason to
drop current game facts or pretend a paused campaign is complete.

The website keeps both compatibility diagnostics outside the seven model-performance
rows. Unit, endpoint and frontend test-double checks do not establish deployment,
browser acceptance or gameplay readiness.
