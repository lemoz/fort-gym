# Persistent campaign agent foundation

This delivers the agent layer for **Year-Two Autonomous Play and Cross-Model
Evaluation**. The goal remains autonomous functioning play after 403,200 elapsed
native ticks, continuation into year two and beyond, and repeated comparable
experiments across at least three models with inspectable website results.
This library milestone does not prove that gameplay outcome.

## Available in this delivery

`fort_gym.bench.agent.campaign_llm.CampaignLLMAgent` is an explicit Python API.
Select its model with `model_override`; provider and generation settings are
constructor options. It is not registered as a legacy benchmark CLI agent.
The native campaign controller and local-model adapter remain separate work in
[the integration PR](https://github.com/lemoz/fort-gym/pull/125).

The campaign decision profile (`campaign_action/v1`) requires only an action
type, parameters and simulation advance. Planning notes are optional. There is
no mandatory build order, scalar score target, timed plan-review gate, or
scripted replacement action. Invalid grammar gets at most three model-selected
corrections; exhausted corrections and provider failures do not synthesize WAIT.
The native executor still decides whether a command is legal and what happens.

The historical governed agent keeps its prompt, tool schema, decision logic,
outcome memory and review rules. Regression hashes pin those surfaces to main
`3a52860e7b14bf9e3ebd6c268a59f7865f60a651`. Historical experiment configurations,
native controls, scores and results are not rewritten by this delivery.

## Continuation contract

1. Construct a fresh agent with `memory_path=None`, then call
   `set_campaign_context(campaign_id=...)` before inference.
2. At a committed action boundary, `export_campaign_state()` returns JSON-safe
   memory, configuration, pending outcome review and cumulative usage. Recent
   observations are preserved along with compressed memory and planning notes.
3. Restore into a fresh agent using `restore_campaign_state(..., campaign_id=...)`.
   Matching model, endpoint fingerprint, prompt/profile and memory settings are
   required. Segment-specific `set_run_context()` calls retain campaign usage
   and provider affinity instead of resetting them.

The pending action was already selected for execution: it awaits outcome review,
not automatic replay. The caller must bind this snapshot to the corresponding
native save, trace cursor and execution journal before calling the next decision.
An agent snapshot alone cannot certify game execution, reconcile an interrupted
request or restore Dwarf Fortress. The native runner integration is not included.

Snapshots exclude the transport client and API credential fields. They still
contain private observations, model-selected notes and actions. Keep them in
private campaign artifacts; they are not automatically safe public documents.
Restoring validates the full memory before changing live state. An already used
agent cannot restore older usage and roll back its accounting.

## Provider accounting and operational limits

Accounting occurs once when each completion response returns, before action
extraction or choice-envelope rejection. Empty/blocked responses and bounded
transport retries are included. Returned-response count and fully-accounted
response count are distinct. Cost is accumulated as Decimal and preserved as an
exact decimal string in checkpoints; display telemetry also includes floats.

A valid total-token field is accepted. Otherwise both prompt and completion
components must be present and valid, including explicit zero values. One missing
component is unknown, not zero. A known cost can still be recorded when token
usage is incomplete. In opt-in strict mode, unaccounted billable responses or
unverified returned provider/model identity terminate without another dispatch.
Non-strict legacy mode records missing usage without inventing it.

`provider_name` pins OpenRouter routing with fallbacks disabled. Strict mode also
requires that pin and verifies returned generation metadata. It defaults off;
the new campaign policy is not automatically forced into strict hosted mode.

`max_total_tokens` and `max_cost_usd` default to 128,000 and 25 USD, configurable
through constructor options or `OPENROUTER_MAX_TOTAL_TOKENS` and
`OPENROUTER_MAX_COST_USD`. Every initial, retried and degraded request checks the
same cumulative threshold. These checks stop **subsequent** requests after a
threshold is reached; they are not a per-request price reservation or a guarantee
against one-request overshoot. A returned-usage counter also cannot price an
unreturned request, host, electricity or hardware. Campaign orchestration must
enforce the separately authorized aggregate spending and request reservations.
Changing a limit never resets retained usage or grants spending authorization.

`FORT_GYM_DISABLE_DOTENV=1` disables local dotenv loading for isolated tests and
workers. Normal dotenv behavior is unchanged when that switch is absent.

## Verification and remaining work

Focused tests cover memory round trips, next-prompt equivalence, configuration
mismatch and malformed-snapshot rejection, retained spending, profile-specific
grammar, transport retries, provider identity and partial usage. All inference
in these tests is fake; there are no paid model calls or native game mutations.
Historical prompt and normalized syntax-tree checks are separate from gameplay
tests and deliberately exclude the documented transport changes.

The pre-publication full local suite passed 1,159 tests with five skips. A final
additional regression covers partial usage attached to a provider error; such a
response is unaccounted, not declared nonbillable merely because its generation
id and cost are absent. Remote CI validates the final published revision.

The full repository still has legacy static-analysis debt: 10 Ruff findings in
unchanged files and 464 mypy errors across 27 files in this candidate. Targeted
mypy reports three unchanged governed-review errors; new checkpoint, campaign
policy, memory and configuration modules pass targeted typing. No suppressions
were added to hide legacy errors.

Next delivery: the configuration-driven native campaign runner must pair this
agent state with game saves and reconciled action/usage journals, then pass real
interruption/continuation acceptance. Local-model inference and output-limit
recovery must be delivered and accepted on the same code path. Website source
and versioned historical results are already merged separately; production
deployment, real-site acceptance, sustained year-two play and fair repeated model
comparisons remain unproved. Do not merge the whole integration stack as a
substitute for those checks.
