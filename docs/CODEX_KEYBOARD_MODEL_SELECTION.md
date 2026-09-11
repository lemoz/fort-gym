# Explicit model selection for native keyboard campaigns

The subscription keyboard path now accepts a declared model and reasoning effort
under `fortgym.codex-keyboard-condition/v2`. This is configuration support, not
evidence that another model has played successfully or is available to this
account. Historical v1 conditions keep their original meaning; the ongoing Astra
campaign retains its own declared condition and checkpoint history.

## Condition contract

Create a separate condition from the existing keyboard condition, retain all
control, observation, display, timeout, admission and budget fields, and explicitly
change these identity fields. This fragment is illustrative, not a runnable run:

```json
{
  "schema_version": "fortgym.codex-keyboard-condition/v2",
  "condition_id": "separate-declared-trial",
  "model": "gpt-5.6-sol",
  "reasoning_effort": "medium"
}
```

v1 remains strictly Astra Medium. v2 validates literal `gpt-*` model identifiers
and explicit reasoning-effort names; this validation is not a model catalog or
proof that every model supports every effort. Unsupported pairs must fail without
a replacement model, local inference, API fallback, credit purchase or usage reset.

The model and effort travel through a v2 exchange request, its digest, the host
courier, the CLI invocation and retained request/result receipts. A mismatched
condition fails before dispatch. The native agent checks returned receipt identity
before executing input and still counts returned usage when identity fails.
Receipts describe the model **requested** from Codex, not an independently
provider-attested resolved model identity.

Checkpoint configuration contains the selected pair. Resume requires exact
configuration equality, including model, effort, controls and original limits;
an explicit existing budget-extension record is separate. Switching models means
a new declared trial, not resuming an Astra checkpoint as another model. Existing
v1 checkpoint and receipt schemas retain their historical meaning.

## Evidence and next acceptance

Offline tests exercise Astra, Sol and Terra identifiers through the real courier
and transport code with synthetic process responses, plus checkpoint continuation,
rejected input, mismatch handling and native-worker wiring. They do not make model
calls, attest account access, measure gameplay quality, or establish a comparison.

Before a cross-model result is published, each model needs an actual bounded run,
retained dispatch and usage evidence, and a declared comparable starting save,
controls, observation, display, budgets and intervention policy. Use separate
campaign identities and repeated attempts before making performance claims.
Subscription dollar charges remain unknown when the transport does not report them.

Independent starts now have a separate game-side CLI documented in
[Independent native-keyboard trials](KEYBOARD_FRESH_TRIALS.md). It starts each
model with empty memory from a verified snapshot, then uses ordinary checkpoint
continuation. This closes a configuration-to-startup gap, not the live comparative
evaluation requirement. Never switch models by rewriting an Astra checkpoint.

## CLI sources

Model selection uses the documented non-interactive `codex exec --model` option:
[OpenAI model selection](https://learn.chatgpt.com/docs/models).
Reasoning effort is passed as a one-run `-c model_reasoning_effort` setting:
[OpenAI CLI configuration overrides](https://learn.chatgpt.com/docs/config-file/config-advanced).
The installed CLI help was also checked. No global account configuration is edited.
