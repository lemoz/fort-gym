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

## Terminal native attempt

[Published result and audit](../experiments/evidence/local_native_designation_reference_20260906.json):
the new Qwen14 campaign started from the original digest-bound save at frozen code
`8148f6d55494ad88caf46a780cfbea11d16d6a4a`. Across three segments it returned fifteen
accounted responses, 78,023 tokens and fourteen committed commands advancing 2,800
model-requested native ticks. Twelve committed DIG responses omitted the mode and
used the unchanged default `dig`; two specified `dig`. All fourteen were rejected,
with no completed development. The untouched baseline explicitly returned
`kind=dig` on all sixteen decisions. This formatting difference does not establish
causation or a capability improvement.

All fourteen committed request bodies contain the exact reference prompt (SHA-256
`846034c3ae0ae474f62ce325dd705a26261b204439a3fc2acc052bd7ab8617de`).
The largest request was 21,977 bytes. Eight requests omitted older history, up to
ten rows, while retaining current facts and latest results.

The fifteenth response omitted the required third coordinate in both DIG `area`
and `size`. It was recorded and accounted, never executed. Preserving its grammar
correction and current facts exceeded the declared request bound, so the attempt
stopped before a second correction dispatch. The last verified checkpoint is
cursor 12: the two subsequent commands and fifteenth response are not contained in
a new native/agent/trace/usage checkpoint. All three runtime process groups and
listeners, model-server/runner and tunnel were independently stopped; production
revision, active services and the original paused calendar remained unchanged.

Do not automatically resume the older save or claim that the unused sixteenth
dispatch completes this condition. Reliable failed-decision continuation remains
open. The next model/harness experiment must be separately declared, retaining this
failure and avoiding rankings across unlike conditions. The earlier cursor-6
publication remains in Git history, not an extra campaign. Full CI for the frozen
native revision passed in run `34031851418`; 99 targeted checks passed on the isolated
Linux host. The earlier seven-record publication CI passed in run `34032869590`.
