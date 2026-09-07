# Astra keyboard campaign integration

The keyboard condition now uses the existing CampaignLoop checkpoint path, not
an independent throwaway gameplay runner. A model callback receives the full
native capture, its retained memory and a small previous-input receipt. Internal
fortress metrics remain private evaluation evidence and are not sent to the
screen-only playing model. The model still chooses all strategy, keys and ticks.

The supplied condition is an initial bounded eight-decision run: two four-step
segments, a native checkpoint between them, and cumulative usage preserved at
resume. This is a first real integration experiment, not year-two acceptance or
a new mandatory benchmark ladder. Its limits can be changed in a future declared
condition; they are not hard-coded gameplay capability restrictions.

The host calls the existing Astra Medium subscription transport. A read-only
app-server account check runs freshly before every invocation, using only
initialize, account/read and account/rateLimits/read. It creates no model turn,
changes no login/configuration, and buys/consumes no credits or resets. A known
quota window at or above the declared threshold stops admission. This is not an
atomic reservation against concurrent account use. Official protocol:
https://learn.chatgpt.com/docs/app-server

Subscription usage stores actual returned tokens and invocation counts with
`total_cost_usd: null` and an explicit unreported-charge basis. It does not reuse
self-hosted zero-cost accounting or invent API prices. The cumulative token limit
stops the next invocation after returned usage reaches it; it cannot reserve an
unknown final response size. Failed or missing receipts remain unresolved.

A single-use, digest-bound file exchange connects the isolated game worker to the
credential-owning host. The game container requires neither network access nor a
local model server. Each response must match the exact request and captured
screen. Files are atomically published without overwriting prior responses.
The native worker validates model/transport/profile identity and native keys;
partial or unknown execution stops without replay or additional clock ticks.

Checkpoint continuation preserves model memory, usage, action cursor and trace
prefix. A fresh runtime must load the checkpoint before the next model decision.
The old governed/shortcut conditions retain their existing accounting and action
contracts. Website publication of the new condition is still separate work.

Native outcome remains unrun until supported by the retained live receipts. No
native captures, maps, saves, private prompts or detailed traces are authorized
for public GitHub export by this implementation.
