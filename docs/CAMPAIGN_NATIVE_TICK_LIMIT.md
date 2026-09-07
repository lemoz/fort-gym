# Native campaign tick-limit propagation

## Observed defect

The live thinking-v1 campaign at frozen source
`fad9d80c0a2e7aace8380b47b009db5edaf6bd2e` exposed a configuration mismatch.
Its condition and action schema permit up to 2,500 ticks per decision. The
campaign loop passes the model's requested count to `NativeCampaignEnvironment`,
but that adapter did not forward the configured maximum to `DFHackClient.advance`.
The clock controller consequently applied its unchanged 2,000-tick default.

The first seven committed thinking rows each contain a 2,500-tick model request,
a native receipt requesting 2,000 ticks, and 2,000 actual elapsed ticks. Their
total is 14,000 ticks. SHA-256 of those seven original newline-terminated trace
rows: `4e76db45d56ce77efeeb92e25cef7a9a8e8529a4301ed3df3f4750c1cf2b09c8`.
This is a frozen historical prefix, not the terminal result. The completed
[matched pair](LOCAL_THINKING_PAIR_RESULT.md) retained the same cap for all
eighteen thinking commands and reports 36,000 actual elapsed ticks. Raw
messages and game files remain private. The local campaign identifier is
`fort-gym-year-two-qwen35-thinking-v1-a`.

All 32 completed direct-response baseline rows requested and received 1,000
ticks, so that baseline did not hit this hidden cap. Both experiments use the
same frozen code, but model-selected requests experience its cap differently.
Their comparison must disclose this implementation limit. Measured elapsed
ticks remain correct; do not replace them with requested ticks.

## Candidate correction

The campaign worker now gives the declared `max_advance_ticks` to the native
adapter. The adapter validates it within the existing campaign range, rejects
invalid/out-of-bound requests before native access, and forwards the same bound
through the real client to the clock controller. Zero-tick requests remain
paused. Direct adapter callers retain the 2,000-tick default.

No global clock default, historical protocol, model prompt, action policy,
checkpoint, native trace or published outcome is changed. This is propagation
of the already-declared campaign limit, not a higher experiment budget.

Regression checks cover worker configuration propagation, both 2,000 and 2,500
limits, invalid booleans/types/ranges, zero-time behavior, the actual client call
path and its formerly silent default clamp, continuation and clock interruption
behavior. The focused set passed 165 tests with one platform skip. These are
test doubles and source checks, not a corrected native-run acceptance claim.

The completed matched pair remains bound to its original execution source. Do
not rewrite its historical ticks. A later explicitly versioned runtime
must verify 2,500-tick native advancement before using this corrected behavior
for new model experiments. Full year-two gameplay and repeated cross-model
comparison remain open.
