# Selected-workshop host courier repair

September 12, 2026. This is a source repair, not a replacement gameplay result,
new runtime declaration, main merge or successful native shortcuts run.

The frozen controls-study source `422c915d23bf828371be481d3079a23bbb3e9e94`
completed pair-one keyboard at 128 decisions. Its first shortcuts attempt loaded
the original seed but failed at the first decision exchange. Native/container
cleanup and local VM teardown completed. Keep both original outcomes and their
immutable source/image, request, response, save and teardown evidence.

## Cause and correction

`keyboard_courier.answer_request` validated the v5 condition and exchange, but
forwarded `prompt_profile` to the decision builder only for v3 and v4. The
builder therefore received its legacy default with workshop controls and raised
`Workshop shortcuts require their declared instructions` before calling the
model transport. The failed exchange retained `dispatched: null` and unknown
tokens; those original fields are not retrospectively rewritten to zero.

The production change adds v5 to that existing forwarding condition. It changes
no instruction text, model, observation, game controls, resources, budgets or
earlier-version behavior. No retry, fallback or permissive validation is added.

Four regression cases exercise the actual courier, prompt builder, transport
decoder and retained receipt, replacing only the provider process with an
offline fixture. They cover keyboard and workshop actions with both empty and
retained memory, exact prompt/model identity, usage and one-shot request claims.
All four failed before the correction. The focused suite passes 217 tests,
including historical prompt, binding, owner and courier behavior. Changed-file
Ruff and diff checks pass. The full local run reports 5,693 passed, ten skipped
and one failure: the sandbox denied the unchanged localhost-port test's bind.
That exact test passes when rerun with bind permission. The original full-run
failure remains retained; this is not represented as a single all-green run.
Exact-head hosted validation is separate and not yet claimed.

## Next experimental boundary

Do not run more v1 attempts on the known-broken host or replace its failed ID.
The source correction lives on a separate branch, leaving the frozen worktree
unchanged. Declare and bind the corrected runtime revision before additional
scored attempts; do not silently combine changed-source samples as the original
six-attempt cohort. Preserve the successful keyboard sample as v1 evidence.
The original full Year-Two and cross-model goal remains active.
