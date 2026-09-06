# Accounted model-output pauses

Implementation candidate, September 6, 2026. This is a recovery protocol, not a
new gameplay condition or native acceptance result. The historical long-v2
campaign remains terminal and unreconciled beyond its last periodic checkpoint.

## What changes

A llama.cpp response that reaches the declared output-token allowance can end
with no usable action, even though its returned usage is complete. Treating that
case as uncertain native execution prevents a clean save and loses the normal
continuation path. The new runner settles it as
`inference_output_limited_pause` before dispatching any game command.

The adapter requires all existing identity, prompt-count, context and usage
checks, exactly one assistant response with string content and no tool calls,
`finish_reason=length`, and completion tokens equal to the declared output limit.
It retains the original response privately and accounts for every returned token.
Even parseable partial JSON is not executed, repaired or replaced with a WAIT.

The loop independently requires dispatched, returned and accounted response
counts to agree and increase, the native clock and paused viewscreen to remain
unchanged, and the complete usage journal to reconcile. It appends a durable
`accounted_no_action/v1` receipt without advancing the action cursor or trace.
Failure to write that receipt does not become a resumable pause.

## Checkpoint and continuation

`fortgym.campaign-checkpoint/v3` binds the existing native-save inventory, agent,
runner, trace and usage files plus `decision-pauses.jsonl` and the paused native
boundary. Verification checks their digests and the relationships among the
native calendar, final committed trace, action cursor and settled usage receipt.
An output pause before the first move has an empty trace, `next_step=0` and
`last_committed_step=-1`; it does not invent a game action.

Normal committed-action checkpoints continue to use v2. Existing v1/v2 artifacts
retain their meaning. New failed-decision records without the explicit no-action
outcome are not reclassified as clean merely because their token totals happen
to agree.

The controller accepts a v3 handoff only after independently checking the loaded
source, complete checkpoint and usage, lineage, and runtime teardown. It stops
the current invocation at the output pause; it does not retry automatically.
The existing `--resume` path can continue the same frozen campaign with its full
agent memory and cumulative usage. A paused segment still consumes a segment,
and resumed attempts retain the same dispatch, token and segment caps. Changing
the reasoning setting or output allowance requires a separately declared condition.

Timeouts, missing usage, changed identity, changed native clock/pause/viewscreen,
partial native execution, and unverified teardown still require reconciliation.
This protocol does not make an old checkpoint current over later commands.

## Website and proof limits

The public feed and profile preserve the output-pause status. The website labels
it “Paused at the model output limit”, with the existing token/cost fields and
checkpoint/teardown indicators. The pause adds no successful action and is not
classified as fortress collapse. Raw responses, reasoning and private paths stay
out of the public projection.

Regression coverage uses synthetic native/transport doubles, including the real
llama.cpp adapter's exported-state path. It covers pause before and after actions,
resume without replay, repeated pauses exhausting their unchanged segment cap,
receipt tampering/write failure, uncertain boundaries, incomplete usage, and the
public terminal projection. These checks are not real DF save/load acceptance,
live model generation, browser visual QA or a production deployment.

Final focused validation: 247 tests passed and one optional platform test skipped
across the adapter, loop, checkpoint, segment/controller, retention, load-source,
profile and public-feed suites. Ruff passes for all changed Python files; targeted
mypy passes for the nine changed implementation modules. The full integration
tree is not lint/type clean: repository Ruff reports 14 findings outside the
changed files; mypy excluding retained artifact worktrees reports 659 errors in
37 files. This change does not claim to resolve that broader debt.

Next native acceptance must exercise v3 save/load on a new declared execution
revision. The earlier long-v2 result is not rewritten or resumed by this change.
