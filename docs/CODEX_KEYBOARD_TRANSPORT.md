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
- `screen_observation.py`: a separately versioned `native_screen_text/v1`
  observation retains readable CP437 rows, every column, color spans, and original
  character-code overrides. It round-trips to every captured raw tile, including
  code-zero blanks and characters whose ASCII approximations lose geometry.
  The original `native_screen_tiles/v1` remains the default and comparison baseline.
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
- `NativeCampaignEnvironment.screen_capture()`: retrieves the real CopyScreen
  tile payload between matching paused fortress/calendar checks, preserving
  dimensions and colors without reading the internal-state observation. This is
  a native adapter path with mocked regression coverage, not a live native test;
  it does not force rendering or prove post-key frame freshness.

The implementation follows [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
for JSON events, stdin prompts, ephemeral sessions, and structured output. Local
flag compatibility was inspected on Codex CLI 0.153.4. The Codex wrapper is part
of the experimental condition, not a bare-model API comparison. Credentials stay
in the local user's existing store and are not installed in public CI.

## Remaining native integration

### Native keyboard candidate

`NativeCampaignEnvironment` now accepts an explicit `native_keyboard/v1` control
profile. Its keyboard path allows actual native dialog/menu events without the
historical INTERACT-only restriction, and rejects direct helper actions. The
default `dfhack_shortcuts/v1` path retains the existing executor and behavior.

`campaign_keyboard.py` prechecks the whole chosen batch against the native key
enum, then dispatches each event once through `campaign_keyboard_v1.lua`. That
hook uses the same `gui.simulateInput` native event route as DFHack's
[`devel/send-key`](https://github.com/DFHack/scripts/blob/0.47.05-r8/devel/send-key.lua).
It verifies runtime, save, calendar and pause under the core lock and restores
pause before releasing it, including for a PAUSE event or thrown input call.
Game time remains a separate `advance_ticks` request; PAUSE is not a wall-clock
run command in this synchronous condition. Partial and unknown dispatches retain
their confirmed prefix and are not replayed or represented as non-execution.

Python/Lua-double tests are not a native execution claim. In particular,
[`CopyScreen`](https://github.com/DFHack/dfhack/blob/0.47.05-r8/plugins/remotefortressreader/remotefortressreader.cpp#L2896)
copies an existing display buffer; a successful input receipt does not prove a
fresh rendered frame, completed work, or a functioning fortress. A short native
diagnostic must verify the visible transitions and clock separately.

1. Supply a freshly refreshed account-allowance and cumulative-run budget guard.
   Every transport request requires an admission callback, but this slice does
   not implement unattended account refresh or claim an atomic subscription
   reservation. Other Codex activity shares the allowance.
2. Add a campaign adapter with checkpointed agent memory and usage that represents
   unknown subscription charges honestly; do not reuse an API-cost zero as proof
   of a free run.
3. Add explicit keyboard and screen-only profiles to the native campaign loop.
   The native adapter exposes the new keyboard profile, but CampaignLoop still
   permits the historical helper action contract. Keyboard `PAUSE`/screen
   transitions need real native validation before unattended execution.
   Do not simply expose KEYSTROKE in the schema and declare this integrated.
4. Verify a larger native viewport and what the model actually receives. Raw tile
   JSON and the lossless readable profile are implemented and tested against
   synthetic captures, but no larger native viewport has been proved. A visually
   rich native map may have different token use from the sparse menu fixture.
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
tile-array prompt establishes a fidelity/cost baseline. See the
[public-safe synthetic receipt](../experiments/evidence/astra_keyboard_synthetic_20260907.json).

A second live call used the same fixture, model, reasoning level, and action
contract with `native_screen_text/v1` and its corresponding profile explanation.
It selected the same key with zero requested ticks, using 15,272 input and 79
output tokens. Input use fell by 17,783 tokens (53.8%) on this fixture. Both calls
were uncached. One trial per condition is not a gameplay comparison or a claim
about dense maps. No native keys were dispatched, and exact dollar cost remains
unknown. The original receipt is unchanged; see the separate
[readable-profile receipt](../experiments/evidence/astra_keyboard_text_synthetic_20260907.json).

Readable-profile tests cover all 256 CP437 codes, 35 deterministic randomized
grids, mixed blank codes, unknown glyphs, highlight colors, malformed encodings,
and 80x25, 120x40, and 160x50 synthetic geometry. These are byte/glyph fidelity
tests, not proof that a model understands all symbols or that the native renderer
supports those larger dimensions.

At the readable-profile slice, 125 focused checks passed, including the native
capture adapter's before/after clock, pause, runtime-identity, and malformed-screen
rejections. Changed-file Ruff and scoped mypy passed. OpenAI Docs informed the
declared input-format comparison; the requested model and reasoning effort were
held fixed rather than introducing a model migration at the same time.
The full-suite run before adding the capture method had 2,174 passes, ten skips,
and the same sandbox-blocked localhost bind; its exact socket test passed with
localhost access. The final capture-method changes are covered by the 125-test
focused rerun above, not retroactively included in that full-suite count.

Validation at the first slice: 92 focused tests passed. The full suite had 2,155
passes, ten skips, and one sandbox-blocked localhost bind; that exact socket test
passed separately with localhost access. Changed-file Ruff and scoped mypy passed.
Repository-wide checks still report ten lint issues and 464 type errors in
existing files; this slice does not claim a clean whole-repository lint/type run.

Retain prompt/schema/events/stderr and result receipts under private project-owned
artifacts. A request intent without a final receipt has unknown dispatch outcome;
it is not permission to replay a potentially billable call.
