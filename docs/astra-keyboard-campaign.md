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

## Native result, September 7

The first eight-decision campaign completed on unchanged source `ea3812dd7`:
62 confirmed native key events, 6,000 model-requested elapsed ticks, and verified
native checkpoints at cursors four and eight. The fresh-process continuation
preserved the complete memory, usage and trace prefix, without replaying an old
action. Independent retained-evidence checks passed; the game and VM are stopped.

The campaign retained 236,802 tokens. Two preceding delivery failures retained
another 69,004 tokens, for 305,806 total across ten Codex invocations. Displayed
credit balance was unchanged; exact dollar charges and internal provider dispatch
count remain unreported. No local model server, cloud VM, API fallback, credit
purchase or reset was used. These are early gameplay results, not year-two success.

The first two failures exposed ownership and permission differences in Docker
file copies. The working courier sends JSON to the existing unprivileged game
user, which atomically publishes and reads its own response. It runs a separate
courier read/write check before inference. No permissions or container boundaries
were relaxed. The first segment then completed, but reusing the same local port
failed before the second runtime started. A fresh local port allowed continuation
from its saved checkpoint. Use distinct segment ports and retain terminal
container logs in reusable runtime owners.

See the [non-content outcome record](../experiments/evidence/astra_native_keyboard_outcomes_20260907.json).
No native captures, maps, saves, private prompts or detailed traces are included.
Source and this condition are delivered through draft PR #137; longer campaigns,
website acceptance and repeated three-model comparisons remain open.

Validation: 2,285 broad-suite passes, ten skips, and one sandbox-denied localhost
bind; that exact test and the final keyboard checkpoint selection passed together
with socket access (ten tests). The earlier focused integration selection passed
68 tests. Changed-file Ruff, scoped mypy for three new source modules, and exact
implementation-head CI passed. Existing whole-tree static-check debt is unchanged.
