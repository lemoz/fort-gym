# Astra keyboard decision transport

First implementation slice for the September 7 standard-input experiment goal.
This is not yet connected to native campaign execution or the website.

## Implemented

- `standard_input.py`: independently versioned keyboard-only action schema and
  validation. Reuses native interface keys and the existing 100-key batch limit;
  rejects direct DFHack shortcuts without substituting another action.
- Screen capture validation retains actual width/height and every character,
  foreground, and background tile. A screen-only condition excludes unrelated
  internal-state fields. Larger synthetic grids are supported, not proof that the
  native headless viewport has been resized.
- `codex_transport.py`: exactly one ephemeral, structured-output `codex exec`
  invocation, pinned to `gpt-6-astra` / `medium` with ChatGPT authentication. No
  inherited API credentials, user config, external tools, or automatic retry.
  This means no harness retry; internal HTTP attempts remain Codex wrapper
  behavior and are not independently counted by this adapter.
- `codex_protocol.py`: retains returned usage even on rejection, distinguishes one
  exact pre-turn disabled-Code-Mode diagnostic from tool calls and errors, and
  rejects malformed or incomplete turns. Subscription charges remain unknown when
  the CLI does not report them; token usage is not converted into fake dollar cost.
- `keyboard_decision.py`: connects a declared captured screen and agent-owned
  memory to the transport, validates the response, and retains a decision receipt.
  It never sends keys to the game by itself.

The implementation follows [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
for JSON events, stdin prompts, ephemeral sessions, and structured output. Local
flag compatibility was inspected on Codex CLI 0.153.4. The Codex wrapper is part
of the experimental condition, not a bare-model API comparison. Credentials stay
in the local user's existing store and are not installed in public CI.

## Remaining native integration

1. Supply a freshly refreshed account-allowance and cumulative-run budget guard.
   Every transport request requires an admission callback, but this slice does
   not implement unattended account refresh or claim an atomic subscription
   reservation. Other Codex activity shares the allowance.
2. Add a campaign adapter with checkpointed agent memory and usage that represents
   unknown subscription charges honestly; do not reuse an API-cost zero as proof
   of a free run.
3. Add explicit keyboard and screen-only profiles to the native campaign loop.
   Currently dialog handling permits `INTERACT`, and keyboard `PAUSE`/screen
   transitions need verified tick and pause receipts before unattended execution.
   Do not simply expose KEYSTROKE in the schema and declare this integrated.
4. Verify a larger native viewport and what the model actually receives. The
   current decision slice uses full tile JSON, a fidelity baseline whose token
   cost should be measured before long runs; readable text/frames can be a newly
   versioned observation profile.
5. Run short native diagnostics, then autonomous play and matched shortcut trials.
   Update website result conditions and public-safe records after native evidence.

## Validation

Focused pytest coverage exercises the transport, keyboard contract, captured-grid
integrity, decision bridge, and existing keyboard/native environment behavior.
Tests use synthetic observations and mocked subprocess events; they do not call a
model or start a fortress. Replaying the earlier retained connection-smoke events
through the new decoder accepts its valid response and retains 10,414 tokens plus
the exact startup diagnostic. The original receipt is preserved unchanged.

One new live subscription call used a synthetic 80x25 workshop menu through the
new screen-to-decision path. Astra returned `KEYSTROKE` / `BUILDJOB_ADD` with zero
requested ticks. No keys were sent to DF. Its 33,055 input and 63 output tokens
were retained; account credit balance and rounded used-percent readings were
unchanged before/after. This is not exact per-call dollar attribution. The large
tile-array prompt establishes a fidelity/cost baseline; compact observations
should be tested before a long campaign. See the
[public-safe synthetic receipt](../experiments/evidence/astra_keyboard_synthetic_20260907.json).

Validation at the first slice: 92 focused tests passed. The full suite had 2,155
passes, ten skips, and one sandbox-blocked localhost bind; that exact socket test
passed separately with localhost access. Changed-file Ruff and scoped mypy passed.
Repository-wide checks still report ten lint issues and 464 type errors in
existing files; this slice does not claim a clean whole-repository lint/type run.

Retain prompt/schema/events/stderr and result receipts under private project-owned
artifacts. A request intent without a final receipt has unknown dispatch outcome;
it is not permission to replay a potentially billable call.
