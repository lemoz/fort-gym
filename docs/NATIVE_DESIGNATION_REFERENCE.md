# Native designation reference experiment

This is a model-facing control-documentation experiment, not a change to native
action acceptance or a claim of autonomous success. It is opt-in through
`local_inference.action_reference: native_designations/v1` in
[the declared condition](../experiments/campaigns/local_native_designation_reference_v1.json).

The existing prompt lists the four DIG modes and their parameters, but leaves
their terrain eligibility and different rectangle semantics to native feedback.
The completed Qwen14 baseline made sixteen `dig` attempts against ineligible
surface rectangles. The new reference states that ordinary digging mines eligible natural
walls, channeling accepts eligible wall/floor shapes, woodcutting targets tree
trunks, and plant gathering targets living shrubs. It explains all-or-nothing
dig/channel preflight versus target selection within chop/gather rectangles.

The source of these statements is the installed
[designation adapter](../hook/designate_rect.lua), with glyph meanings from the
[campaign encoder](../fort_gym/bench/env/campaign_encoder.py). Native job completion
is separate from designation; the preserved scripted workshop fixture demonstrates
woodcutting and construction, not model capability.

No coordinates, chosen action, build order, material injection, automatic WAIT,
mandatory planning review or response rewrite is supplied. The action schema,
parser, native controls, request/token/dispatch bounds and model-selected ticks
are unchanged. The condition also declares four exact local model manifests for
future matched attempts; registry coverage is not completed evaluation.

The actual system-prompt bytes are included in the checkpoint configuration hash.
Old conditions keep their original prompt and configuration identity, and old
checkpoints cannot silently acquire the reference. The real cursor-6 Qwen14
configuration hash remains
`27575a309f1c24f80375593b7b23479ee1a8f0982e204458ba4e950923b1f69d`
under the unchanged default policy.

A read-only replay checked 11 already committed requests from the first two
Qwen14 segments. The new reference fit all 11 under the existing 22,000-byte
request limit, with a largest reconstructed request of 21,897 bytes. Older history
was reduced for four requests; current native facts, latest results, exact memory
text and correction messages were preserved. Serializer, response-instruction,
body-fit and action-schema source hashes matched the frozen native implementation.
This is historical prompt-fit evidence only, not a guarantee for future observations
or a model call. Private audit receipts remain under the project artifact directory.

Next: evaluate this reference from the original digest-bound starting save. The
untouched Qwen14 baseline completed its sixteen-dispatch budget, with 82,782 tokens
and 3,200 model-requested native ticks; all sixteen commands were rejected and no
development completed. Do not resume the old campaign under these
new instructions or compare unlike conditions as a model ranking.
