# Astra keyboard campaign integration

## Latest result: checkpoint 439, past one quarter of the first year

Window k completed on frozen source `7416f65b2ee464b09963d65733b692bf1a9c03b6`,
returning all 64 decisions: 63 accepted inputs and one invalid input rejected
before dispatch, with zero native keys or ticks. It added 24,000 actual ticks,
reaching 101,000 retained ticks, just over one quarter of a full elapsed year.
Checkpoint 439 is
`69679e980dcf4164c7c0ae264a6044f4bfa8678e081079c7dd62769ccddc34e8`.
Independent save, lineage, rejected-input and clock-receipt reviews passed.
Game/container/VM teardown passed with no OOM kill or resource increase. A fresh
load of this final checkpoint must verify before the next model call.

Seven dwarves remain alive with zero recorded deaths. Completed farms increased
four to five, installed beds three to four, and completed workshops stayed at
three. Existing drink units increased 134 to 162; food stock, production and
consumption remain unverified. These descriptive gains do not prove sustainability.

The model requested 26,000 ticks; 24,000 advanced. Twelve decisions advanced time,
52 did not, and 51 requested zero ticks. One 2,000-tick request was held in the
workshop Add Job menu. Its native receipt independently verifies the unchanged
calendar, no clock dispatch and no timeout. Astra later advanced another 6,000
ticks without a correction key or strategy hint. This exercises the specific
workshop-menu deferral, not the generic clock-unavailable timeout fallback.

All 455 responses and 14,814,687 campaign tokens are retained, with 14,883,691
tokens including historical failed deliveries. New tokens: 1,976,528. Charges are
unreported. Memory, the inherited 2,000-tick loss and all earlier failures remain
intact, with no new restart, replay or budget extension. The campaign page now
separates requested and actual game time, undispatched rejection and outcome
counts. The keyboard-type reporter repair was developed separately, replay-tested
against retained evidence, and integrated only after this runtime stopped.

Record: `experiments/evidence/astra_native_keyboard_workshop_continuation_20260908.json`.
Window l declares another unchanged 64-decision continuation from 439 within the
existing cumulative 1,024-dispatch / 40-million-token allowance. It is prepared,
not yet run. No merge, production deployment, visual acceptance, independent model
comparison or full-goal completion is claimed. Native game and model content stay
private; only authored aggregates are published. The full goal remains active.

## Previous result: model-led play reaches checkpoint 375

Window j completed all 64 new accepted Astra Medium decisions on frozen source
`bc7a23aefef1fcf4f3f9212f1059d0edf17f239c`. It added 11,400 actual native ticks,
reaching 77,000 retained ticks, about 19.1 percent of a full elapsed game year.
Checkpoint 375 is
`aeec46203d3ab51f5ce19c7070e9bcf660f6588dd55751042cb6f560b9e4e75a`.
Independent save/lineage audit and game/container/VM teardown passed. A separate
fresh load of this final checkpoint must pass before the next model invocation.

The private boundary review records seven living dwarves and zero recorded dead
citizens at both ends. Completed farm plots increased from two to four; installed
beds stayed at three and completed workshops at three. Drink units were 132 then
134, without production or consumption attribution. Food stock remains unverified.
Seven decisions advanced game time and 57 requested none. These observations do
not establish sustainability. The v2 metric reader now recognizes only attested
native population and complete drink-unit evidence, using the existing tested
reader repair; it does not change the player's screen-only observation.

All 391 responses are accounted: 12,838,159 campaign tokens and 12,907,163 including
historical failed deliveries. This window used 2,141,205 tokens. Subscription
charges remain unreported. The inherited 2,000-tick lost branch remains explicit;
there was no new loss, replay, memory reset, budget extension or strategy rescue.
Neither clock-deferral branch was exercised, so this completion is not branch
coverage proof. Earlier failures and recoveries remain separate recorded events.

The campaign page leads with this continuation and authored aggregate counts.
Native captures, maps, coordinates, saves and model traces stay private. Endpoint
and frontend tests are not visual acceptance, merge or production deployment.
Published record: `experiments/evidence/astra_native_keyboard_workshop_play_20260908.json`.
Window k declares the next unchanged 64-decision continuation from 375, retaining
the existing cumulative 1,024-dispatch / 40-million-token allowance. Declaration
alone is not a started run. The full year-two and cross-model goal remains active.

## Previous result: normal play through four verified saves

Window h completed on source `bcac94d1b6e51c7f54e25f56661c5a42b0085b2a`.
All 64 new Astra Medium decisions were accepted, adding 14,400 native ticks.
Independent audit verifies four v3 saves at cursors 248, 264, 280 and 296,
ending at 63,600 retained ticks, about 15.8 percent of a full game year.
The last save is `f6f5ae7a888d79ec9dfc1e61e054bde58f0cfc9e8286908bfab02da3d75dbed0`.
The first three saves were loaded by later segments; the final snapshot passed
in-process verification but has not yet had a separate fresh-process reload.

All memory, trace/journal prefixes and the inherited lost branch are preserved.
There are 312 accounted model responses, including the historical branch loss:
10,215,904 campaign tokens and 10,284,908 including failed deliveries. This window
used 2,065,677 tokens; exact subscription charges remain unreported. Game,
container and local VM teardown passed. No gameplay worker is live at this result.
The goal is still year-two autonomous play and repeated model comparisons, not
checkpoint acceptance alone. Detailed gameplay outcomes remain private.

The website now leads with the authored non-content continuation record while
retaining earlier failures and recoveries. No merge, production deployment or
visual acceptance is claimed. Public evidence:
`experiments/evidence/astra_native_keyboard_settled_play_20260908.json`.

The next declared window i keeps the same total bound of 64 new decisions but
uses one 64-decision segment instead of four 16-decision segments. This tests
menu continuity with fewer native-process reloads. Model, prompts, controls,
observations, memory, usage and cumulative limits stay unchanged. It increases
the maximum unsaved tail if the runtime fails and is not a matched causal trial.
The declaration is prepared, not an assertion that a new worker has started.

## Integration

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

## Declared endurance continuation

`campaign_astra_keyboard_endurance_20260907.json` continues the same fortress
from cursor eight. Its initial operating window is four 16-decision segments,
with cumulative limits extended to 256 invocations and eight million returned
tokens. The original eight-decision configuration is not overwritten. A
`fortgym.campaign-budget-extension/v1` record binds the verified source
checkpoint, old/new limits and actual usage at extension. Later checkpoints
preserve this history along with memory, usage and the original journal prefix.
Model, control, observation and tick policies remain unchanged; no strategy or
game-state intervention is part of this extension.

The existing campaign page now includes a separate native-keyboard milestone
section, backed by an explicit allowlist at `/public/keyboard-campaigns`. It
shows cumulative decisions, keys, elapsed ticks, checkpoint coverage and tokens,
with subscription charges labeled unreported. It never scans private artifacts
or inserts unapproved fortress metrics into the older comparison feed. Milestones
are recorded states of one campaign, not rows to sum or a live worker indicator.
Local endpoint and JavaScript tests cover failure states and non-content export;
production deployment and visual acceptance remain separate.

A fresh-account admission denial now settles explicitly without a model or native
dispatch. The runner verifies unchanged agent state and paused game calendar,
retains the denial receipt and unchanged usage, and can checkpoint the last
committed action. Ambiguous transport failures still remain unresolved; they
are not converted into a free or safely retryable decision. No credits or reset
are automatically consumed.

### Completed endurance window

The continuation completed all 64 additional model decisions on frozen source
`fcdd1f662`: 72 cumulative decisions, 357 confirmed key events and 25,000 elapsed
native ticks. All four new checkpoints, at cursors 24, 40, 56 and 72, verified.
An independent retained-evidence audit confirmed native reloads, unchanged original
configuration, the append-only budget extension, memory and complete trace/usage
prefixes. The final game and isolated local VM are stopped.

The continuation retained 2,081,738 tokens. Cumulative campaign usage is 2,318,540;
including the two historical failed delivery attempts, usage is 2,387,544 tokens
across 74 Codex invocations. Displayed credit balance was unchanged. Exact
subscription charges remain unreported. No API fallback, local model server,
cloud VM, credit purchase or reset was used. Approximately 500 MB of private
runtime evidence was retained; nothing was deleted.

This is a useful longer keyboard baseline, not year-two acceptance: elapsed time
is about 6.2 percent of one full game year. The last save covers every committed
decision and permits continuation without resetting usage or replaying actions.
Detailed fortress outcomes remain in private evidence; the website now has a
second explicitly recorded non-content milestone, not an additional model-ranking
row. The versioned operational summary is
`experiments/evidence/astra_native_keyboard_endurance_20260907.json`.

Validation: 2,297 broad-suite passes and ten skips; its one sandbox-denied
localhost test passed separately with socket access. Focused continuation and
pause checks passed 115 tests. Website endpoint/rendering checks passed 39.
Changed-file Ruff and scoped mypy passed. Exact implementation/website head
`03190cc48` passed remote CI. Production deployment and visual acceptance are
not claimed.

Validation: 2,285 broad-suite passes, ten skips, and one sandbox-denied localhost
bind; that exact test and the final keyboard checkpoint selection passed together
with socket access (ten tests). The earlier focused integration selection passed
68 tests. Changed-file Ruff, scoped mypy for three new source modules, and exact
implementation-head CI passed. Existing whole-tree static-check debt is unchanged.
