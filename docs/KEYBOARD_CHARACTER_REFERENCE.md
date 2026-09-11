# Optional native character-input reference

Status: implemented for a future declared experiment; not enabled in the
existing matched cohort. No gameplay benefit or workshop-job fix is proven.

## What changes

The opt-in prompt profile `native_keyboard_character_reference/v1` retains the
complete `native_keyboard_memory_replacement/v1` instructions and adds a short
generic input reference. Named native command events and literal character events
are distinct. For printable ASCII, the latter use `STRING_A###` with the
three-digit decimal character code: a is 097, A is 065, and 0 is 048.

The reference does not claim that every menu hotkey expects a character event.
It supplies no workshop recipe, build order, selected job, hidden game state,
extra tool, key alias, automatic retry, or automatic time advancement. The agent
still chooses the exact key events, strategy, and requested game time.

Both earlier prompt profiles remain byte-for-byte unchanged for fixed inputs.
The new profile requires `native_keyboard/v2`, whose existing catalog includes
character events. Response grammar, event executor, observations, model choice,
reasoning effort, retained-memory replacement, and subscription accounting are
unchanged. No existing experiment config or result is relabeled.

## Evidence and hypothesis

Read-only inspection of the active Astra repeat-one continuation found that
`CUSTOM_B` left the workshop AddJob view unchanged, while a later scroll and
`SELECT` reached the Job view. This is a candidate input-semantics problem,
not proof that a particular job was queued or that a different character event
would fix that menu.

The matching DFHack 0.47.05-r8 source resolves `simulateInput` string arguments
directly through `df.interface_key`; it does not translate a named event into
physical keyboard input. `Screen::keyToChar` recognizes the STRING_A range and
`Screen::charToKey` maps printable ASCII to that range:

- [gui.lua at fed9f763](https://github.com/DFHack/dfhack/blob/fed9f763c9c9b0f64d45e8d7bec626f492c752fe/library/lua/gui.lua#L21-L54)
- [Screen.cpp at fed9f763](https://github.com/DFHack/dfhack/blob/fed9f763c9c9b0f64d45e8d7bec626f492c752fe/library/modules/Screen.cpp#L433-L455)

Hypothesis: explaining this distinction reduces ineffective inputs caused by
confusing character events with named commands. It may have no effect, or reduce
performance if the model applies character input to menus that expect commands.

## Evaluation path

1. Finish the active continuation without modifying its prompt or runtime.
2. On a disposable copy after the active VM has stopped, compare named-command,
   character, and scroll/select inputs from the same native menu state. Record
   screens, per-key receipts, and native job identity. This is an operator
   diagnostic, not an autonomous gameplay result; never resume its edited save
   as a model-only continuation.
3. If the native result supports the hypothesis, declare separate paired model
   trials from an identical untouched starting save. Keep model, medium effort,
   screen size, memory policy, decision budget, and runtime fixed between arms.
   Bind the prompt profile, source revision, and image identity to each result.
4. Compare ineffective-input repetitions, native simulation progress, actual
   completed work and fortress outcomes, and token usage. Repeat before making
   performance claims. Publish both arms and failures, separate from the original
   cohort.

No runnable trial or image is introduced here. The frozen active image cannot
accept this new profile; a future image and its source binding must be validated
before launch. A saved campaign may use a new profile only with the existing
checkpoint-bound prompt-change declaration, preserving prior history, memory,
and accounted usage. Such a branch is a different condition, not an extension
of the unchanged matched cohort.

## Validation scope

Offline tests freeze earlier prompt bytes, check the new prompt-only delta,
reject incompatible controls before a model call, carry the profile through the
courier for Astra/Sol/Terra at medium effort, preserve literal returned keys, and
exercise fresh-start and explicit checkpoint-change continuity. These tests
cannot establish native menu behavior or model performance.

The prompt is versioned and tested in code following the
[OpenAI prompt-engineering guidance](https://developers.openai.com/api/docs/guides/prompt-engineering).
Only the input reference changes; no model migration or added approval rule is
part of this experiment.
