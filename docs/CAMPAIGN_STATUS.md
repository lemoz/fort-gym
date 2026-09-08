# Campaign status

Verified September 8, 2026 UTC. The Year-Two Autonomous Play objective remains
unfinished; work continues toward the same objective. The owner has approved starting the project
work for [Astra standard-input experiments](ASTRA_STANDARD_INPUT_EXPERIMENTS.md).

## Current phase: Astra native play and continuation

Implement Astra Medium on native keyboard controls, verify the actual model-visible
screen, and run autonomous fortress experiments toward year two and beyond. Keep
DFHack shortcuts as an explicit alternative condition. Compare matching starts
and declared observation/display settings, then extend to other models. The new
phase retains website and remote delivery. The first bounded Astra native
keyboard campaign has now completed.

### Latest result: checkpoint 232 recovered and verified in a fresh native process

Forward-only recovery at `41edaca0c37c637e8c34fa81ab96abb202e99078` passed native
acceptance and independent audit. Checkpoint 232 is
`d7c802ba88aa29a418d216d41cdd33df22b678403e5f68b9d508b6b4131059e7`, preserving
49,200 retained ticks, all 248 responses, 8,150,227 campaign tokens and 8,219,231
all-attempt tokens. Full trace/journal bytes, memory and the one inherited loss
boundary are unchanged. No model call, key, requested tick or replay was added.
All native/container/VM teardown passed. No worker is currently live.

Explicit save profile `native_menu_preserving_save/v3` reads menu identity in
separate RPCs immediately before and after saving, with the same native runtime,
calendar and exact screen-object stack. The full identities must match. The
transient inline helper reading stays retained; world-state and copied-save
checks are unchanged. The unit-menu save correction passed its own native test
and fresh reload before recovery. Historical profiles and failures remain intact.

The website source leads with recovery 232 and retains the original failure and
older records. No production deployment or visual acceptance is claimed. Next is
normal Astra Medium/native-keyboard continuation from 232 with explicit v3 saving,
unchanged memory, usage and cumulative limits. Year-two fortress sustainability
and repeated cross-model comparisons remain unproved; this is checkpoint
continuity, not completion of the full goal.

Private acceptance/recovery evidence under the runtime artifact root:
`astra-native-settled-identity-acceptance-v1` and `astra-native-runtime-recovery-v1`.
Public evidence: `experiments/evidence/astra_native_keyboard_runtime_recovery_20260908.json`.

### Previous result: 16 further decisions, then a menu-identity save failure

Window g at `dcc475a42872d35918eaefdc4d3f0a5f5b1203a2` returned 16 accepted
decisions and advanced 2,000 ticks. It stopped at trace cursor 232 / 49,200 retained
ticks on `Native menu identity changed during save`. Independent audit verifies
248 fully accounted responses, 443,672 new tokens, 8,150,227 campaign tokens and
8,219,231 including historical failed deliveries. Charges remain unreported.
At that failure, checkpoint 216 / 47,200 ticks was the latest verified checkpoint.

The runtime's world save changed from the parent and was retained, awaiting
fresh reload verification. The trace and model memory/usage were settled and
unchanged observations bracket the save operation. Its specific changed UI field
is unknown because validation rejected the raw operation receipt before it was
retained. Follow-up diagnostics now retain that unvalidated receipt and read-only
post-failure captures without retrying the save or relaxing the identity check.
All game/container/VM teardown passed. No worker is live; no new model call is
needed to investigate the retained state. Do not rewind or discard the latest
16 decisions and their usage. This is not a recorded fortress collapse.

Private evidence:
`fort_gym/artifacts/native-local-20260906/runtime-v2/astra-native-semantic-continuation-v1`.
The authored latest review is
`experiments/evidence/astra_native_keyboard_menu_identity_review_20260908.json`.

Follow-up diagnostics now verify the newer native save reloads with matching
persistent observations. A reproduced unit-menu save reveals the selection helper
temporarily reports no unit inside the save RPC, while the actual unit-screen
reference, screen pixels, menu stack, world observations and calendar stay
unchanged; a later helper RPC agrees with the direct unit again. Both successful
diagnostics passed independent audit and teardown, using nine menu-only setup
keys each, zero model calls and zero requested ticks. The first fixture failed
before any input on a wrong method name and remains failed. Those diagnostics
led to the separate-RPC identity correction and verified forward recovery above.
Private proof: `astra-native-menu-identity-diagnostic-v2` and `-v3` under the same
runtime artifact root. Public details: `docs/semantic-native-checkpoints.md` and
`experiments/evidence/astra_native_menu_identity_diagnostic_20260908.json` on the
implementation branch.

### Previous result: checkpoint 216 recovered and verified by fresh native reload

Provider-free recovery at `2a158ae19d2bd6dcfdd1a4bb0013e6c8d42ad57f` passed
independent audit and a second native-game reload. Verified checkpoint 216 is
`36142c131e444003dd8dc7616f330800946566ab614d2f7509b32bbda8f4bca3`, retaining
47,200 elapsed ticks, all 232 responses, unchanged model memory and byte-identical
trace/usage journals. Usage remains 7,706,555 campaign tokens and 7,775,559 with
historical failed deliveries. There were zero additional model calls, gameplay
keys, requested ticks or new loss boundaries. All native processes, the container
and the local VM were stopped and verified; subscription charges are unreported.

The cause was a bad pixel-equality check: paused screen tiles changed even between
read-only captures, while menu identity and world observations stayed unchanged.
The explicit `native_menu_preserving_save/v2` profile checks unchanged menu
identity and recorded world state while retaining screen captures and both
digests. Historical v1 remains unchanged. Fresh-load connectivity-to-unknown
changes are accepted only under the observed native pending-reindex flag; no
game tick or reindex command is used to force agreement.

The website source now leads with recovered checkpoint 216, while preserving the
original validation failure and the earlier genuinely lost 2,000-tick branch.
Source `e6376a6a3` is pushed with passing CI; follow-up `dcc475a42` retains successful
private save diagnostics as well as failures. Website/API checks and local HTTP
passed. Preview handoff was queued and requests were observed; no visual QA,
merge or production deployment is claimed. Window g is declared from checkpoint
216 with the new save profile, unchanged Astra Medium/native-keyboard conditions,
memory, all usage and cumulative limits. It adds no budget extension or restart.

Private recovery evidence:
`fort_gym/artifacts/native-local-20260906/runtime-v2/astra-native-settled-recovery-v1`.
Authored public evidence:
`experiments/evidence/astra_native_keyboard_settled_recovery_20260908.json`.

### Previous result: screen validation failure after 16 more decisions

Normal continuation window f executed at `1198ece397eec679c04dcf4e948b2b419bbde956`
with passing exact-source CI. It returned 16 accepted decisions and advanced
1,200 ticks before `Native screen changed during menu-preserving save` stopped
checkpoint validation. Independent audit verifies all 232 model responses,
7,706,555 campaign tokens (7,775,559 including historical failed deliveries),
unchanged original prefixes and complete game/container/VM teardown. New usage
is 722,519 tokens; charges are unreported. No worker is live.

The save was copied before screen equality failed. At this failure, checkpoint
200 / 46,000 ticks was the latest verified boundary, while the retained trace and
newer save reached 47,200 ticks. The subsequent forward recovery above verified
the newer state without another rewind or action replay. Inherited lost-tail
history, model memory and all usage remain intact.

The original failure remains recorded below its subsequent recovery. The
executed failed run lacked exact before/after captures; later provider-free
diagnostics established the invalid pixel invariant described above. No native
save was retried and no failure was reclassified as a successful original run.
Private evidence: `fort_gym/artifacts/native-local-20260906/runtime-v2/astra-native-post-loss-restart-v1`.

### Previous result: saved new branch after explicit loss-aware restart

Window e completed at source `93af69fe4866cf325dcae3a8b4099bc458b6fdfc`, whose
exact-source CI passed. Independent audit confirms 16 new accepted Astra Medium
decisions, 2,000 new retained ticks and verified new-branch checkpoint 200:
`aabb513a50309812f900d9e346807710acb0935f271a200e9df4cda59aef1cdb`.
The retained timeline is 46,000 ticks. All 216 model responses are accounted,
including the original unsaved tail: 6,984,036 campaign tokens, or 7,053,040 with
historical failed deliveries. The new segment used 518,169 tokens. Exact
subscription charges remain unreported. Game/container/VM teardown passed;
no gameplay worker is live at this result.

This restored checkpoint 184 and its memory, explicitly recorded the lost tail,
then let Astra choose new actions. The old 2,000 unsaved ticks remain lost and
their 531,913 tokens remain counted. No historical action was replayed. Overlapping
cursor 200 belongs to a new branch, not recovered old state or an independent
comparison attempt. The discontinuity survives normal resume and evaluation.
The corrected build-menu save/reload diagnostic also passed with zero model calls,
save keys or ticks. Existing isolated VM data capacity increased from 10 to 16 GiB
to preserve evidence; CPU, memory and isolation settings are unchanged.

The website source now leads with the new saved branch while retaining the old
failure separately. Endpoint and JavaScript checks pass, and local HTTP returns
the current record. Preview handoff was queued, not visually inspected. No
production deployment or merge. Evidence is authored operational counters only;
native screens, saves and model content stay private.

Next: normal window f continues from this new checkpoint with all 216-response
usage, model memory and discontinuity intact. No repeated restart or budget
extension. Year-two sustainability and repeated comparisons across three models
remain unproven. Private evidence:
`fort_gym/artifacts/native-local-20260906/runtime-v2/astra-native-save-loss-restart-v1`.

### Previous implementation snapshot: menu-preserving save and failure display

The versioned `native_menu_preserving_save/v1` helper is pushed at `693f1c4cc`,
with passing exact-source CI. It passed actual save and fresh reload from a
nested unit menu and the normal fortress view, preserving the exact screen,
recorded world observations, calendar and menu stack with zero gameplay keys or
ticks. Independent audit verifies both cases and teardown. A third diagnostic
used an invalid test key and stopped before saving; the whole fixture is still
failed, and build-menu coverage is unclaimed. No new model calls were made.

The website source now leads with the checkpoint-200 save failure, separating
the 200-response trace from durable checkpoint 184 and retaining every token.
Endpoint, non-disclosure and JavaScript rendering checks pass; local HTTP passed.
Preview handoff was queued, not visually inspected. No production deployment.
Next: finish the remaining menu diagnostic, explicitly record a loss-aware
attempt boundary, then resume Astra without discarding the unsaved-tail usage.
Private validation: `fort_gym/artifacts/native-local-20260906/runtime-v2/astra-native-save-menu-v4`.

### Historical save failure, before the successful restart above

Latest terminal update: window d stopped after 16 new accepted decisions at
trace cursor 200 / 46,000 elapsed ticks. Its checkpoint failed with
`Native save completion was not observed before timeout`. Independent audit
verifies all responses, 531,913 new tokens, trace/journal prefixes and native,
container and VM teardown. No worker is live. Campaign tokens are 6,465,867;
including historical failed deliveries is 6,534,871, with charges unreported.

Retained native save files still match checkpoint 184, excluding the appended
load log. The newer 2,000 ticks and 16 decisions are retained in trace but their
game state is not resumable. Do not claim checkpoint 200, silently restore 184
while dropping usage, or claim the new state survived. The final UI was
`viewscreen_unitst`; bundled quicksave documentation requires dwarf mode.
A menu-preserving save now passes the affected unit-menu case as described
above. An explicitly recorded attempt/continuation boundary with all usage
retained remains necessary. The courier also saw a container-exit race; no
duplicate response was dispatched.

The updated website source includes this newest checkpoint failure separately
from recovery 184, without claiming live activity or production deployment.

Native validation and forward-only recovery passed at `c537e3e79`, with an
independent retained-file audit and passing exact-source CI. New checkpoint 184
preserves 44,000 elapsed ticks, all 184 returned responses, model memory and
5,933,954 campaign tokens (6,002,958 including historical failed deliveries).
Recovery added zero model calls, native keys or game ticks. The original failed
window, response and original usage-journal byte prefix remain unchanged; one
explicit reconciliation record accounts for the historical input rejection.
Native game/container/VM teardown was verified. Checkpoint digest:
`073ac57c4b80227368d5bd6b6367ba4e214fc629dbbaf604c498b24b7a80e642`.

The isolated native rejection diagnostic also passed against a real screen,
using a separately labeled synthetic response with no model/key/clock calls.
Its synthetic usage is excluded. A package-ownership failure preceding the
successful attempt stopped before game load and remains retained separately.

Astra has now resumed from checkpoint 184 at frozen source `6493cba58`, with
[passing exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34168124770).
Its first response acknowledged the rejected input and reloaded menu, then
chose its own navigation. A native trace check verified 186 committed rows,
including two newly accepted model responses. No additional ticks were observed
at that check. The subsequent audited checkpoint failure is described above.

Declared window d allows four 16-decision segments, with a new append-only
cumulative allowance of 1,024 dispatches / 40 million returned tokens. This
is not a charge or dollar reservation. It preserves the model, controls, raw
120x40 display, memory and checkpoint cadence; fresh quota admission precedes
every subscription call and no fallback, purchase or reset is allowed.
The first resumed admission observed 82 percent usage under the 90 percent guard.

The preceding website revision projected interruption 183 and recovered checkpoint 184
ahead of older evidence, without claiming live tracking. Source, non-content
manifests and window configuration are pushed in draft PR #137; no merge or
production deployment. Validation: 2,435 broader source tests, 193 focused
recovery/control checks, and 86 website/window/recovery checks passed. Changed
files pass Ruff and scoped mypy; full-project mypy remains unclaimed.
Private current operator/evidence: `fort_gym/artifacts/native-local-20260906/runtime-v2/astra-native-post-rejection-v1`.

### Previous input-rejection interruption

The post-recovery window executed at `d37a1b42f` and independently verified five
new checkpoints at 117, 133, 149, 165 and 181. It then committed through decision
183 at 44,000 elapsed native ticks. Response 184 contained unsupported key names.
No keys or game ticks from that response were dispatched, but the original
harness treated input validation as fatal. This is not a fortress-collapse result.

Independent audit verifies every completed checkpoint, memory/configuration and
usage prefixes, all six native-process cleanups, container exit and local VM
teardown for that failed window. Two committed actions after checkpoint 181
and the rejected response's usage remain in the latest retained native save and
journals. That forensic save was not itself a resumable checkpoint. Do not rewind to
181 or replay the rejected response as a free model call.

This window returned 83 new model responses and used 2,702,162 tokens. Campaign
usage is 5,933,954; including historical failed deliveries is 6,002,958. The rejected
response's 32,731 tokens are included. Exact subscription charges remain unreported.
The non-content record is `experiments/evidence/astra_native_keyboard_rejection_20260907.json`.

The correction makes a fully accounted, shape-valid response with unsupported keys
an explicit rejection-feedback event. It sends no key, advances no time, applies
no attempted memory update and chooses no substitute action. Astra chooses its
next response. Rejections consume budgets and can checkpoint/resume normally;
uncertain transport or mutation remains a failure. The current focused set passes
166 tests at that earlier correction. Native validation and forward-only recovery
subsequently passed as described above; the original failed window is not relabelled
success. The recorded website now includes this interruption and its recovery,
with no live-status claim. No production deployment or merge has occurred.

### Previous verified recovery and continuation

Forward-only native recovery passed at `914ac0721`, with
[passing exact-source CI](https://github.com/lemoz/fort-gym/actions/runs/34162604769).
An independent audit verifies a new resumable checkpoint at cursor 101, preserving
the latest native save, model memory, all 101 responses, 29,000 elapsed ticks and
3,231,792 campaign tokens. Recovery made zero model calls, sent zero keys and
requested zero ticks. It retains the original failed clock receipt and source
bytes unchanged; the earlier failed window remains failed. Native game, container
and VM teardown verified for recovery. The checkpoint hash is
`a412590ef8d1a663ad1f177b5a109dd5fc6551725d11d02f6a375d8c2f3981f3`.

The clock correction also passed a separate native diagnostic: ordinary clock
advance produced 100 ticks; the observed blocking build menu returned a verified
zero-tick deferral without clock dispatch or a recovery key. This diagnostic is
not campaign progress. Recovery code has 134 focused passing tests.

Source `d37a1b42f` and the non-content recovery manifest are pushed in draft
[PR #137](https://github.com/lemoz/fort-gym/pull/137). The declared continuation
`campaign_astra_keyboard_window_20260907c.json` has started from checkpoint 101
and delivered new Astra responses to the game. It allows six 16-decision segments,
preserving Astra Medium, subscription transport, native keyboard v2, raw 120x40
screen, model-selected strategy, memory and the existing cumulative 256-dispatch/
eight-million-token extension. No new extension or human gameplay rescue. The
window subsequently stopped as described above; the recorded
website remains explicitly non-live. Private owner and evidence are under
`fort_gym/artifacts/native-local-20260906/runtime-v2/astra-native-post-recovery-v1`.

Year-two viability, sustained production, repeated comparable model results,
reviewed merge, production deployment and visual acceptance remain unclaimed.

### Historical reusable-runtime interruption

The same fortress ran on the public reusable keyboard command and host courier
at source `a004c490f`, pushed in draft PR #137 with
[passing exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34158366994).
The declared window allows up to 128 additional decisions from cursor 72,
in eight 16-decision segments, within the existing 256-dispatch/eight-million-token
cumulative extension. No new extension, strategy instruction, memory reset,
observation change, API fallback or local model was introduced.

The window stopped on a native clock timeout after 100 committed decisions and
101 returned model responses, at 29,000 committed elapsed ticks. The failed request
sent three confirmed keys and then advanced zero ticks while a native build menu
remained open. This is an infrastructure interruption, not a fortress-collapse
or budget-limit result. Independent audit verifies both native-process cleanups,
container exit and local VM teardown for that interrupted window.

At interruption, the last verified checkpoint was cursor 88, with 12 newer committed decisions and
the failed action retained in a forensic native save and journals. That save is
not itself a resumable checkpoint. It required reconciliation without replaying the action
or replacing newer state with cursor 88. Original configuration, budget extension,
memory handoffs and trace/usage prefixes remain intact.

This continuation used 913,252 model tokens. Campaign usage is 3,231,792; including
historical failed deliveries gives 3,300,796. Exact subscription charges remain
unreported, not zero. The website implementation now presents the interruption
separately from the older completed milestones and names the recovery boundary.
Its non-content manifest is
`experiments/evidence/astra_native_keyboard_interruption_20260907.json`.

Validation of the reusable path: 96 focused tests, 2,326 broad-suite passes,
ten skips, and the one sandbox-denied socket test passed separately with socket
access. Changed-file Ruff and scoped mypy for all four new source modules passed.
The build-menu correction returns a verified zero-tick deferral to the model
without selecting a recovery key or invoking the clock. Offline regression tests
cover checkpoint continuation, strict native boundaries and failure retention.
Native validation and forward-only reconciliation subsequently passed as above. The original
failed run is not reclassified. Production deployment and visual acceptance
remain unclaimed.

### Last completed endurance result

The same Astra campaign now covers 72 model-selected decisions, 357 confirmed
native key events and 25,000 elapsed ticks, about 6.2 percent of a full game year.
Source `fcdd1f662` completed four more 16-decision segments from the verified
cursor-eight checkpoint. New checkpoints at 24, 40, 56 and 72 independently verify.
Original configuration, memory and complete trace/usage prefixes are preserved;
the larger cumulative budget is an explicit append-only extension, not a reset.
The native game and isolated local VM are stopped. The run ended at its declared
segment window, not from fortress collapse, a model failure or an account limit.

The new continuation used 2,081,738 tokens. Campaign usage is 2,318,540; retaining
the historical failed deliveries gives 2,387,544 tokens across 74 invocations.
Displayed credit balance was unchanged, while exact subscription dollar charges
remain unreported. No local model, API fallback, cloud VM, credit purchase or
reset was used. Approximately 500 MB of additional private run evidence is retained.

The existing website now includes a separate recorded keyboard-milestone section,
with explicit unknown subscription charges and an allowlisted non-content
endpoint. It does not publish private native captures or claim live-worker status.
Implementation and website head `03190cc48` is pushed in draft
[PR #137](https://github.com/lemoz/fort-gym/pull/137), with
[passing CI](https://github.com/lemoz/fort-gym/actions/runs/34155673083).
The new versioned milestone is
`experiments/evidence/astra_native_keyboard_endurance_20260907.json`.
Local HTTP and JavaScript checks passed; production deployment and visual
acceptance remain unclaimed.

Next: continue the preserved fortress and evaluate useful development and
sustainability, reduce duplicated runtime/courier setup, and run the declared
matched control-condition comparisons. No human gameplay rescue was used.
Year-two viability, repeated comparable three-model results, reviewed merge and
production website acceptance remain required. The full app goal remains active.

### Initial eight-decision result

At implementation `ea3812dd7`, Astra Medium made eight model-selected decisions
through the readable 120x40 screen and native keyboard v2 condition: 62 confirmed
key events and 6,000 elapsed ticks. It inspected status, selected stair and room
designations, and chose when to advance simulation. There were no helper build or
order actions, model fallbacks, or human-selected gameplay moves. Input acceptance
does not independently prove all desired construction or excavation outcomes.

Native checkpoints at cursors four and eight verify. A fresh-process continuation
preserved model memory, cumulative usage, action cursor and the full trace prefix,
without replaying prior actions. Independent retained-evidence verification passed.
The original seed is unchanged and every owned game/container/local VM is stopped.

The campaign used 236,802 tokens. Two earlier delivery failures used 69,004 more:
305,806 total across ten Codex invocations. Displayed credit balance was unchanged;
exact dollar charges remain unreported, not zero. Fresh account quota checks now
run automatically before each model invocation. No local model server, GCE, API
fallback, credit purchase or reset was used.

The delivery failures were isolated to Docker ownership/private-file permissions;
publication now runs as the existing game user and is checked before inference.
The first segment subsequently succeeded, but its next runtime hit port-reuse
`EADDRINUSE` before launch. Resuming the same verified checkpoint on a fresh
local port completed the remaining four decisions. Failed attempts remain failed;
their usage was not discarded. The port correction was infrastructure recovery,
not gameplay rescue.

Source is pushed in draft [PR #137](https://github.com/lemoz/fort-gym/pull/137);
the non-content outcome publication is `4bbd3c81c`. Exact implementation-head
[CI passed](https://github.com/lemoz/fort-gym/actions/runs/34152583644).
The broad suite passed 2,285 tests with ten skips and one sandbox-denied socket
bind; that test and final keyboard checkpoint checks passed with socket access.
Detailed native captures, saves, prompts and traces remain private.

Next: longer declared autonomous play, reusable runtime/courier packaging and
website tracking of the new condition and unknown subscription charges. The
eight-decision integration condition ended at its declared bound; its final
checkpoint remains preserved. Year-two viability, repeated comparable
three-model results, reviewed merge and production website acceptance are not
claimed. The full goal remains active.

### Earlier native interface diagnostic

Native keyboard and viewport acceptance passed at implementation `0ef33ff70`.
The source and public-safe operational summary are on `10816dfad` in draft
[PR #137](https://github.com/lemoz/fort-gym/pull/137), stacked on the frozen native
producer in #136. This includes the earlier subscription transport, raw/lossless
readable observations and native capture path, plus a version-matched keyboard
profile and owned text-terminal sizing. Historical v1 conditions stay unchanged.

The native audit confirmed all 1,613 advertised v2 key names. The actual captured
viewport is 120x40, not just a requested setting. Eight menu/pause inputs were
confirmed with zero elapsed game time; the separate 100-tick request advanced
exactly 100 ticks. Readable captures round-trip to the original tiles and colors.
The source seed is unchanged, and runtime/container/local-VM teardown is verified.
No model call, local model server or cloud VM was used. This was a scripted
interface diagnostic, not Astra choosing moves or completed fortress work.

Three earlier diagnostics remain failed: a menu-label expectation, a clipped-menu
expectation, and the old catalog's unsupported `PAUSE` name. The new v2 catalog
uses the actual `D_PAUSE` name and includes full native building/workshop keys.
The output schema stays within provider enum limits while the prompt, parser and
executor share the complete version-matched catalog.

Latest focused checks: 128 passed, one Linux-only skip. The broad suite passed
2,254 tests with ten skips and one sandbox-denied localhost bind; that exact test
passed separately with socket access. Changed-file Ruff and scoped mypy passed.
The preceding `28630e226` head passed remote CI. Implementation-head
[CI run](https://github.com/lemoz/fort-gym/actions/runs/34150898638) passed;
documentation/publication-head CI is running in the PR. Existing whole-tree static
check debt is not claimed fixed. Detailed native evidence remains local; only
non-content operational outcomes are published.

One live synthetic 80x25 workshop-menu call returned `KEYSTROKE` / `BUILDJOB_ADD`.
It consumed 33,055 input and 63 output tokens; no key was executed in DF. Account
credit balance and rounded usage readings were unchanged before/after, while an
exact dollar charge remains unreported. Raw tile JSON is a costly fidelity
baseline. The exact earlier startup
diagnostic is now classified separately; the original smoke receipt is unchanged.

The same sparse synthetic menu through `native_screen_text/v1` returned the same
key with 15,272 input and 79 output tokens, a 53.8% input reduction in one matched
trial per condition. Every original glyph code and color can be reconstructed;
tests include all CP437 codes, highlight spans, and larger synthetic grids. The
second call also left displayed credit balance unchanged; exact dollar cost is
unreported. Neither call dispatched game keys or proves gameplay competence.

That earlier diagnostic's next step was the live keyboard campaign, now verified
above. General post-key frame
freshness, workshop ordering, placed buildings and completed digging still require
gameplay evidence; the successful menu check does not prove them. No merge or
website deployment is claimed by #137.

## Historical: requested GPT-6 Astra Medium subscription migration

The owner requested `gpt-6-astra` with reasoning effort `medium`, using their
ChatGPT subscription instead of local Qwen inference or separately billed API
calls. The Qwen inspection campaign was operator-cancelled for that model change.
Its evidence was copied successfully; the game container, model server, tunnel
and local VM were verified stopped. This is not a gameplay-collapse verdict.
The preserved campaign controller requires tail reconciliation and must not be
treated as a lossless latest-state continuation.

The installed Codex CLI is authenticated with ChatGPT. A synthetic request with
the exact requested model and effort returned a valid structured response, with
token telemetry and no API credential inherited. Its CLI diagnostic reported the
deliberately disabled Code Mode host; the stricter all-clean smoke receipt remains
false. No game action was sent to Astra, and no captured native data was exported.
This verifies a subscription connection, not a completed campaign adapter.

Next implementation is on `codex/campaign-codex-subscription`: integrate the
subscription transport, declare the Codex wrapper as part of the experimental
condition, preserve action/memory/usage accounting, and enforce an included-usage
guard before dispatch. ChatGPT sign-in is not unlimited or unmetered; usage is
shared and paid credits can apply after included limits. No API fallback or
automatic credit purchase is intended. The native Astra run remains unstarted.

The historical running observations below are superseded by this cancellation.
The full year-two, model-comparison, remote and live-website goal remains active.

## Historical: fresh autonomous inspection campaign running

The [declared fresh campaign invocation](../experiments/evidence/local_native_qwen35_inspection_declaration_20260907.json)
has launched on the existing isolated local runtime. Its owner session and game
container were both verified running. The local model has chosen genuine VIEW
actions; this is now model execution, not another provider-free fixture. This is
a point-in-time running observation, not a terminal campaign or fortress result.
Two bounded segments have now completed, and the controller automatically
continued into the third segment without operator intervention. The second
segment ended at its declared time-slice boundary, not a gameplay failure or
exhaustion of the campaign's cumulative budget. Independent read-only audits
verified the native save inventory, checkpoint-bound files, loaded-source
identity, action cursor and reconciled cumulative usage. Prior periodic and
completed-segment histories remain exact trace and usage prefixes after both
handoffs, with unchanged agent configuration.

The first handoff's new model-selected action started at the saved native
calendar and advanced from there; old actions were not replayed. The second
segment's terminal native-load and cleanup receipts now verify, and its exact
native runtime has no remaining live processes. The third segment's runtime is
live and its journals preserve the second segment's complete prefix. Its first
new model-selected command now starts at the saved calendar with verified native
time advancement. The command's rejection remains a gameplay outcome, not a
failed handoff or a successful action. The auditor issued no game command or restore.
Detailed audit and native evidence remain local. The third segment's terminal
runtime receipt and the outer owner's teardown are not yet complete or claimed.

The producer remains frozen at `48d9ed6d94a598b44c4cfbe10a0df4badcb189ad` in
[PR #136](https://github.com/lemoz/fort-gym/pull/136), whose
[exact-head CI passed](https://github.com/lemoz/fort-gym/actions/runs/34100915461).
The invocation keeps all eight declared segment opportunities and existing
token/action bounds, serial checkpoint continuation and mandatory owned teardown.
No human gameplay action, model fallback, new cloud VM or live code change has
been introduced. The original seed is used, not a rollback of the failed prior
campaign. The live owner's teardown is not yet due or claimed complete.

The tracker condition-link, VIEW reporting and command-retry outcomes are pushed in
[PR #133](https://github.com/lemoz/fort-gym/pull/133) at
`17fa187c1c631ab7ee8f4f9e7dcc994d8493ce33`. It links the exact authored
configuration only when its canonical digest matches; it imports no live capture
or result row. The offline reporter now categorizes VIEW correctly instead of
UNKNOWN, with an explicit map-inspection label in the existing tracker. It also
reports accepted, rejected-again and unknown outcomes for exact-command retries
across intervening actions. Acceptance is not proof of recovery. These observer
changes do not change the running producer or reconstruct missing old evidence;
older retry aggregates remain absent and display `not recorded`.
All 132 focused checks pass, including synthetic source-to-HTTP delivery,
count-only projection and preservation of historical snapshots. Local read-only
native checks corroborated the observer without modifying or exporting evidence.
[Exact-head website CI](https://github.com/lemoz/fort-gym/actions/runs/34114394752)
passed with 1,841 tests passed and 60 skipped. Existing whole-tree static-check
debt remains. This is remote source delivery, not a merge or website deployment.

These current observations supersede the unrun/no-live-owner statements in the
historical sections below. Detailed native payloads remain local. Year-two
viability, autonomous dialog recovery, comparable repeated three-model results
and the website release remain unproven. The full goal remains active.

## Earlier: native map inspection and selection continuation verified

The separately declared provider-free native fixture has passed with the
unchanged map implementation at `bbe58f9485d7ed42f288b9fa27f4d932159d9c01`.
It verifies model-interface region/z selection, hidden-tile handling, invalid-view
feedback and selection persistence through a native checkpoint, stopped game
process and fresh-process reload. These actions were scripted, not model choices.
An independent audit verified retained checkpoint/trace/usage/seed integrity and
native/container/local-VM teardown. No model calls or cloud VM were used.

Both earlier fixture failures remain failed. Their diagnostic showed rendered
glyph changes in a no-action control read. The corrected fixture checks explicit
native invariants and keeps rendering changes as diagnostics; byte-identical UI
rendering is not claimed. The production reader did not need a code change.

Authored source, declarations and a non-content
[operational test summary](../experiments/evidence/local_native_map_inspection_outcomes_20260907.json)
are published remotely. Detailed native payload export was rejected
and remains local; no captured maps, screens, coordinates, saves or traces are in
that summary. No new model comparison row, fortress success, merge or deployment
is claimed. The next model condition is a fresh Qwen3.5 run with the inspection
profile pair and unchanged existing inference/segment budgets, not a rollback of
the prior campaign. It is published in [PR #136](https://github.com/lemoz/fort-gym/pull/136)
at `48d9ed6d9` and is not run. The final focused selection passes 100 checks.
The full suite had 2,087 passed, 10 skipped and one sandbox-denied socket test;
that exact socket case passed separately. New publication-head CI is pending.
No map implementation was cherry-picked into this integration branch.

## Latest: model-controlled terrain inspection pushed

[PR #136](https://github.com/lemoz/fort-gym/pull/136) adds the opt-in pair
`campaign_action/v2` and `campaign_state/v3`. Models can select an in-map
rectangle and z-level with VIEW at zero ticks. The terrain-only view remains
alongside the fort overview and survives checkpoint continuation and accounted
output pauses. Hidden tiles are checked before their detail is read; failed
requests retain the prior selection. No location or action is chosen for the
model. Inconsistent native map receipts are classified as runtime failures,
with already-returned native tick receipts retained.

The implementation is on `codex/campaign-map-inspection` at
`bbe58f9485d7ed42f288b9fa27f4d932159d9c01`, stacked on PR #135. It is not
cherry-picked into this integration branch. See the
[inspection contract](https://github.com/lemoz/fort-gym/blob/bbe58f9485d7ed42f288b9fa27f4d932159d9c01/docs/CAMPAIGN_MAP_INSPECTION.md).
All 299 focused checks pass, including 83 inspection tests and 23 that execute
the Lua reader against engine doubles. The full suite had 2,083 passed,
10 skipped and one sandbox-denied socket test; the exact socket test passed
separately. Changed-file checks and scoped mypy pass. Whole-tree findings remain
10 Ruff errors and 464 mypy errors in 26 files.
[Exact-head implementation CI passed](https://github.com/lemoz/fort-gym/actions/runs/34097397778).

The subsequent native acceptance above supersedes the original unrun status.
No real model has used this profile yet. Historical conditions, saves, results
and fixture verdicts are unchanged. No new comparison row, year-two result,
merge or deployment is claimed.

## Latest: opt-in elapsed campaign observations pushed

[PR #135](https://github.com/lemoz/fort-gym/pull/135) adds
`campaign_state/v2`: the model sees campaign elapsed ticks and elapsed years from
the loop's committed native receipts, separate from the world's calendar year.
The clock survives checkpoint continuation, remains unchanged on zero-tick
actions and stays unknown when full-prefix evidence is unavailable. Existing v1
conditions and representative observation bytes remain unchanged. See
[the clock contract and hypothesis](CAMPAIGN_CLOCK.md).

The implementation is pushed at `47fc2b9a924cc402453581b3aa707d838d4a3604`
and integrated in this branch at `d1c915b8b6527817b22fd6c44b3f31105a30d8c5`.
All 82 final focused checks pass in both checkouts, including 30 clock-specific
tests and the mocked local-transport output-pause/restore path. The preceding
full run had 1,999 passed, 10 skipped and one sandbox-denied socket test; that
exact socket test passed separately. The final additional transport test is in
the 30/82 selections. Changed-file checks and scoped mypy pass. Existing
whole-tree lint/type findings remain.
[Exact-head CI passed](https://github.com/lemoz/fort-gym/actions/runs/34094906822)
for the clock implementation above.

The native dialog evidence publication is now pushed in PR #134 at
`5f5700a704ed8402bb6e1a4a9a9609e3f8750e72`, with
[successful exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34094126489).
Its original fixture-failed verdict and narrower component evidence stay intact.
No model/native attempt has used the clock profile; no new comparison row or
year-two result exists. The next gameplay-interface task is model-controlled,
read-only map pan/z inspection, followed by a newly declared experiment using
the improved interface. Nothing here merges or deploys the pending website/runtime PRs.

## Latest: terminal liaison-dialog failure, owner torn down

The separately declared native dialog fixture has now run once. Its original
overall result remains **failed**: the final assertion demanded all 100 requested
ticks, while native time advanced 19 ticks and cleanly interrupted for the next
meeting dialog. The seven-step retained trace verifies a natural liaison dialog,
zero-dispatch rejection of WAIT on it, visible next-decision feedback and one
explicit scripted confirm. The campaign loop itself did not fail. The meeting
was not completed and no model chose these actions. See the
[native stage result](../experiments/evidence/local_native_dialog_feedback_20260907.json)
and [scope explanation](CAMPAIGN_DIALOG_FEEDBACK.md#native-fixture-evidence-september-7).
All 164 focused regression checks pass in both integration and repair checkouts.
The read-only audit reverified original checkpoint files, stopped VM and free
model listener. No provider calls or new autonomous campaign were made.

The campaign stopped at 83 committed decisions and 203,339 elapsed native ticks.
After a clean interruption for a liaison meeting, the model requested WAIT on
the paused dialog. The clock advanced zero ticks and returned
`interrupt_baseline_invalid`; the harness escalated that choice to a terminal
failure. Nine citizens were alive. This is not established fortress collapse.

All 84 returned responses reconcile to 931,832 cumulative tokens, including the
last uncommitted decision. Metered model charges were $0; hardware, energy and app
costs remain unknown. Checkpoints through 80 verified, but no complete terminal
save exists. Restoring 80 would roll back three committed decisions, not provide
lossless continuation. The model/tunnel/container/local VM are stopped and owned
teardown was independently audited.

The [terminal result and next repair](LOCAL_REASONING_DIALOG_RESULT.md) replace
the earlier website registry entry for this same campaign, keeping 14 recorded
rows and preserving all historical bundles. No new trial, merge, deployment,
browser acceptance or year-two success is claimed. The nonfatal dialog-feedback
repair is now pushed in [PR #134](https://github.com/lemoz/fort-gym/pull/134),
stacked on the still-unmerged native PR #132. Its source is
`af97265ccc9983aa1356d6627457686ed6394b86`; the original experiment worktree
remains clean at `de69c7a467eb0b00becfef03329bac9f58690e35`.

The repair returns a definite zero-tick rejection for a non-INTERACT command on a
known paused dialog, then lets the model choose its next action. It does not
auto-dismiss the dialog or alter historical measurements. Validation: 162 focused
integration checks passed; the native-branch full suite had 1,968 passed, 10
skipped and one sandbox-denied socket test, which passed separately with socket
access. Changed-file checks and scoped mypy passed; existing whole-tree lint/type
debt remains. [Repair CI](https://github.com/lemoz/fort-gym/actions/runs/34091698430)
completed successfully for that exact source revision. A subsequent evidence/test
publication must receive its own exact-head CI check.

The terminal website result is pushed at
`db4556fe1744e432f8e0c619dcc44e1e065f27b1`, with 115 focused checks and
[successful exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34091043621).
Next is improving model-visible campaign context and assessing model-controlled
map inspection before another gameplay attempt. Native dialog-stage validation
has run with the limited result above; autonomous meeting recovery is still
unproven. No model/game/VM owner is live.
Earlier live-status paragraphs below are historical and superseded by this section.

## Latest: automatic continuation through checkpoint 64

The same controller completed segment two, verified native game-process cleanup,
restored checkpoint 64 and committed the first action of segment three without
manual gameplay intervention. The checkpoint covers 156,000 elapsed ticks and
683,802 tokens from 64 returned responses, independently summed from their native
response records. Its save, agent, runner, trace, usage and parent hashes verify.
The next accepted WAIT advanced from native tick 172,801 to 175,301: 65 committed
decisions and 158,500 elapsed ticks, with the exact checkpoint trace preserved.
See the [automatic handoff receipt](../experiments/evidence/local_native_qwen35_year_two_auto_handoff_20260907.json).

At checkpoint 64 there were nine living citizens, 12 native drink units, one
completed workshop, no installed beds and no completed farms. The item scan
observed 11 bed and five chair records, with scan completeness unreported.
Population growth is observed, not attributed to model skill. Production flow,
sustainability and a functioning first-year fortress remain unproven.

The outer owner is still running, so its container/model/tunnel/VM teardown is
not claimed. This is the same campaign, not another trial or terminal website
row. The frozen execution source and configuration are unchanged. Earlier
observations below are historical; this section supersedes their current-state
claims without rewriting the original evidence.

Website reporting is pushed at `4dc0f3b68eac5d73043b0858866d5755af434561`
with 114 focused checks passing in both checkouts and successful
[exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34084335261).
It separates furniture item records from installed beds. No merge or deployment
has occurred, and the frozen active producer has not been hot-patched.

## Continued checkpoint: furniture items versus installed furniture

Checkpoint 40 verified its native save, agent/runner/trace/usage files and parent
link to checkpoint 32. It covers 96,000 elapsed ticks and 412,664 accounted
tokens. The owner remains live; no second-segment terminal outcome is claimed.
The [fixed checkpoint observation](../experiments/evidence/local_native_qwen35_year_two_checkpoint40_20260907.json)
records seven citizens, 33 native drink units, 11 bed item records and three
chair item records. The initial item scans recorded zero beds/chairs; checkpoint
32 recorded one bed. None of those furniture items is installed.

The `completed_beds` field measures completed placements, not inventory. Its
zero value must not hide the observed furniture item progress. The goods scan
does not publish inventory completeness or production attribution; keep those
limits explicit and do not convert its item counts into measured production
flows. The frozen native source and model remain unchanged.

The website reporting correction is pushed in PR #133 at
`d31290d631bc156adcbb920bb6571b75857cf80b`. It labels the metric Installed beds
and shows the fixed checkpoint observation without adding a terminal campaign
row. All 104 focused website checks passed (103 in this integration checkout),
as did changed-file Ruff/Black, JavaScript syntax and diff checks. The new
[exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34082302731)
is running at this observation. No merge, browser visual QA or deployment is
claimed. The prior source's full-suite result does not substitute for this CI.

## First reasoning-budget segment completed and audited

First post-restore gameplay is now verified at the public boundary
`2026-09-07T03:50:45.006612+00:00`: 34 commands, 81,000 elapsed ticks and
345,982 accounted tokens. The model issued an accepted ORDER at step 32 and
WAIT at step 33, advancing continuously from native tick 92,801 to 97,801.
The exact first-segment trace is retained as a prefix. See the immutable
[continuation observation](../experiments/evidence/local_native_qwen35_year_two_continuation_start_20260907.json).
The second segment and its owner remain active; no second-segment final save or
teardown is claimed. This is real native continuation, not a synthetic test.

The original owner exited successfully with 32 commands, 76,000 actual elapsed
ticks and 325,234 accounted tokens. All 32 returned responses ended normally.
Checkpoints at 8, 16, 24 and 32 verified; the final save covers every command and
all returned usage. Native cleanup, stopped container, absent model/tunnel
processes, closed listener and stopped local VM were independently checked.

The retained observations show seven living citizens, one completed workshop,
drink units declining from 60 to 39, and no completed beds or farms. Food/drink
flow and a functioning fortress are not established. The earlier workshop
progress receipt remains immutable. The terminal result is registered as the
fourteenth recorded campaign; older live snapshots cannot roll it back.
See [the result and limitations](LOCAL_REASONING_SEGMENT1_RESULT.md).

The separate seven-segment continuation is now running. Its container started
at `2026-09-07T03:46:04.734379218Z`; the segment-two public boundary at
`2026-09-07T03:46:17.485341+00:00` retained cursor 32, 76,000 ticks and 325,234
tokens. The new trace retains the exact first-segment checkpoint prefix.
No new committed action was observed at this check; the original owner handle
is live. Nineteen offline owner tests and the prior-owner receipt gate passed.
The frozen `de69c7a46` source, exact model/condition and cumulative budgets are
unchanged. This is a continuation of the same campaign, not another trial.

Website-focused validation: 103 tests passed; the corresponding integration
selection passed 102. Changed-file Ruff, Black and JavaScript syntax checks
passed. The broader website suite finished with 1,841 passed, 10 skipped and one
sandbox-denied socket test; the exact test passed separately with local socket
access on the same source. The public result is pushed on PR #133 at
`b896ee79a834ca6b673d16a0b087747c756e5568`, with successful
[exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34080674648).
Existing website-wide lint/type debt remains: 10 Ruff findings and
464 mypy errors in 26 files. The root-wide mypy invocation also encounters
duplicate modules in ignored runtime artifacts; neither is a new pass claim.
No browser visual acceptance, merge or production deployment is claimed.

## Latest: native workshop completed; continuation owner prepared

The running campaign reported one completed workshop after fourteen commands
and 31,000 actual ticks at `2026-09-07T02:50:13.872621+00:00`. Direct inspection
of the same committed prefix confirms a complete native building scan and a
successfully read, built workshop at year 30, tick 47,801. The exact fourteen-row
prefix digest and public observation are in the
[progress receipt](../experiments/evidence/local_native_qwen35_year_two_reasoning_progress_20260907.json).
This is not a terminal website row, manufacturing proof or a functioning
fortress. Beds and farms remain zero; unavailable room, population and stock
measurements remain unknown. No human gameplay rescue or live source change
occurred. The owner continues with its original bounds.

A later report at `2026-09-07T02:56:39.697258+00:00` had seventeen commands,
38,500 ticks, the same one completed workshop and all seventeen returned
responses / 151,758 tokens accounted. The cursor-sixteen periodic checkpoint
also passed independent verification. Its payload SHA-256 is
`215e3de582db4821ed7c5263596f06526769d8360d7d6181331df1a208cca2a7`, and its
manifest file SHA-256 is
`fe5a2e195cf67de0d9a602d467ab8dc039812af291132bd393ad1fc2a8f0af00`.
The fourteen-command workshop receipt remains an unchanged historical prefix.

At `2026-09-07T03:15:32.201663+00:00`, the public report had twenty-five commands,
58,500 ticks, one completed workshop, no completed beds or farms, and all
twenty-five responses / 246,537 tokens accounted. The cursor-twenty-four periodic
checkpoint independently verified, with payload SHA-256
`7a6c2f57bbb4b54855b13588877aa7a8653e019eeba0888ead1dd94a81cf4a1a`
and manifest file SHA-256
`b694e5253f6240dd235e04d828a2ccbbf92c444648a0e99746e1a0b6afd103c2`.
The owner was still live; no final segment or teardown result is implied.

The selected [local continuation wrapper](CAMPAIGN_LOCAL_CONTINUATION.md) is
prepared to invoke all seven remaining declared segments serially, using the
same image, condition, model arguments and evidence volume. The earlier
one-segment preparation is preserved but not selected. Nineteen offline wrapper
checks and 80 focused controller/checkpoint tests passed, including a synthetic
first-plus-seven run with 256 cumulative commands and refusal of a ninth segment.
The existing eight-segment/token/dispatch caps are not increased. Its actual
read-only preflight correctly finds no terminal receipt yet. It has not launched;
the current owner and final checkpoint/teardown audit come first.
The progress receipt passes its calendar/count consistency checks, and all 34
record/catalog tests pass without registering a running snapshot as a terminal
website result.

## Website fix pushed and first live checkpoint verified

The active-feed configuration link and real public-capture regression are pushed
on [PR #133](https://github.com/lemoz/fort-gym/pull/133) at
`80eea7dc7e0d1b853a6918d4f2e5b639dc081faa`. The captured report is historical, not
an extra terminal record or a live connection. The website retains thirteen
recorded rows. The focused suite passed 109 tests on that website branch and
108 tests on this integration branch. The latter includes the same link fix and
synthetic v2 publisher-to-HTTP coverage. Those checks verify native population
and drink counts, confirmed zero values, and clearing of unknown observations.
They do not retroactively repair the frozen runtime's older reports.

The website head `80eea7dc7` passed
[exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34076778796).
Its complete local suite had 1,840 passes, ten skips and one sandbox-blocked
loopback-bind test, which passed separately on the same head with socket access.
Changed-file Ruff/Black and diff checks passed; existing full-tree lint/type
debt remains. The preceding configuration-link head also passed its own CI.
No merge, browser visual acceptance or production deployment is claimed.

The native owner and container remain live at unchanged source `de69c7a46`.
Its public report at `2026-09-07T02:33:47.356960+00:00` records eight committed
commands, 16,000 ticks and all eight returned responses / 65,709 tokens accounted.
The cursor-eight periodic checkpoint independently passed the existing verifier,
including its saved game, agent, runner, trace and usage file digests. Its native
calendar is year 30, tick 32,801, from the immutable tick-16,801 seed. Manifest
payload SHA-256 is `319f2c008814a9e5fced59df1b09be6acbc2abe6cdf4a053a04e58a62ca8b013`;
manifest file SHA-256 is `de9c12fc57de3476fff0f9747d6d7b5359b395af4b880fc5494bd47112fee591`.
The checkpoint covers two accepted WAITs, two accepted DIGs, three rejected
BUILDs and one rejected DIG. Acceptance is not proof of completed work: the
report still has zero completed rooms, workshops, beds and farms. The public
population and drink fields remain unknown under the frozen producer. Its
`checkpoint_verified: false` refers to the not-yet-created final checkpoint;
it does not describe this independently verified periodic save.

This is progress evidence, not a terminal result or one-year success. There are
$0 metered model API charges and unknown hardware/energy/application costs.
The owner continues unchanged and remains responsible for final teardown.

## Reasoning-budget acceptance passed; fresh native campaign running

The [single-request reasoning-budget acceptance](CAMPAIGN_REASONING_BUDGET.md)
returned one complete `DIG` action with 8,793 input plus 2,210 completion tokens,
all 11,003 accounted. Native legality and utility were not checked. Its owned
worker and model PIDs are absent, the listener is closed, and its original source
is unchanged. The [versioned receipt](../experiments/evidence/local_year_two_reasoning_budget_20260907.json)
is pushed on [PR #132](https://github.com/lemoz/fort-gym/pull/132) at
`de69c7a467eb0b00becfef03329bac9f58690e35`; 19 focused result/configuration tests
passed on that documentation/evidence-only follow-up. The executable code is
unchanged from `ebf470d8364bf326cacd7b9985e6f5438d6d4f49`, whose exact-head CI passed.

The fresh native campaign `fort-gym-year-two-qwen35-reasoning-budget-v1-a` is now
running its first bounded segment from the original immutable year-30/tick-16801
seed. Its container and controller were observed running at source
`de69c7a467eb0b00becfef03329bac9f58690e35`, with the first model decision in flight
and no committed action yet at that observation. The derived native image is
`sha256:ce56592ad8f8d82e7dcaa7f9d71a28a900669d523f3119278a865129214c85a3`.
The one-use owner has SHA-256
`8266f19bb3b67a92280e569411193a39c063836f0aeb4ed1f0e7a5ee524b20c1`.

This is a new campaign, not a replay action or rescue of the old pair. It uses
the separately native-verified tick-limit correction and the declared 2,048-token
reasoning budget within 4,096 total output tokens. One segment allows up to 32
decisions and 7,200 seconds, with periodic checkpoints every eight actions and
the original cumulative campaign bounds. Follow the live owner; do not restart,
change its source or mutate its condition. The owner must stop its own container,
model, tunnel and isolated local VM. No cloud VM, hosted model, production change,
functioning fortress or completed segment is claimed.

## Completed output-allowance replay

The [exact local output replay](LOCAL_YEAR_TWO_OUTPUT_REPLAY.md) has finished.
The 4,096-token case reproduced the accounted no-action output limit. The
8,192-token case failed after 600.06 seconds without a returned response while
the server was still generating. Its actual token usage is unknown; 12,889
accounted tokens cover only the first case. No retry or gameplay action occurred.
The owned worker/model PIDs are absent, the listener is closed, and the private
source is unchanged. The [versioned result](../experiments/evidence/local_year_two_output_budget_20260907.json)
preserves that incomplete comparison, with $0 metered model charges and unknown
hardware/energy costs.

The terminal output-replay evidence and optional reasoning-budget implementation
are pushed to [PR #132](https://github.com/lemoz/fort-gym/pull/132) at
`ebf470d8364bf326cacd7b9985e6f5438d6d4f49`. The focused suite passed 195 tests.
The full suite had 1,916 passes, ten skips and one sandbox-blocked loopback test;
that exact test passed separately with local socket access. Changed-file
Ruff/Black, targeted typing and diff checks pass. Full-tree lint/type debt remains.
[Exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34074628994) passed
for `ebf470d83`. The [evidence-only follow-up CI](https://github.com/lemoz/fort-gym/actions/runs/34075255210)
passed at `de69c7a46`; no merge or deployment is claimed.

## Native clock correction verified

The [native clock acceptance](CAMPAIGN_NATIVE_TICK_LIMIT.md) passed at frozen
source `eca52a53021c8889ee9e63882f2184084590d391`: exactly 2,000 default ticks,
then exactly 2,500 declared ticks, with matching native receipts and observed
calendars. Invalid and zero-tick requests preserved paused boundaries. The owned
native process, listener, container and isolated VM are stopped. No model was
called by that fixture, and its 4,500 scripted ticks do not count as agent play.

The receipt and [new output-budget diagnostic](LOCAL_YEAR_TWO_OUTPUT_REPLAY.md)
are published in [PR #132](https://github.com/lemoz/fort-gym/pull/132) at
`9e82dbc8e494390a5a3a8e3a46a5438aed6fd2ab`. Its 113 focused tests passed; the full
suite had 1,901 passes, ten skips and one sandbox-blocked loopback test, which
passed separately with socket access. Changed-file checks and targeted typing
pass; existing full-tree lint/type debt remains.

The completed diagnostic used two declared requests from the retained
thinking-v1 pause. Offline serialization reproduced the source request exactly;
only `max_tokens` changed for the second request, under a combined 29,874-token
input/output envelope. Its terminal outcome is above; the source and one-use
operator remain frozen.

## Completed matched pair: fully covered pause checkpoints

The [matched-pair result](LOCAL_THINKING_PAIR_RESULT.md) and its website surface
are delivered on [PR #133](https://github.com/lemoz/fort-gym/pull/133), source
`fc64d2b62e8aac095b088fd957098e2829bf0c34`. The paired manifest is bound to both
exact result bundles and their normalized launched configurations. The website
now exposes thirteen recorded campaign rows and a direct comparison explanation.
Its 95 focused tests passed, including the published row, immutable condition
links, full returned-response accounting and the asymmetric native tick cap.
[Exact-head GitHub CI](https://github.com/lemoz/fort-gym/actions/runs/34071894579)
passed for `fc64d2b62e8aac095b088fd957098e2829bf0c34`. PR #133 remains open;
merge and production deployment are not claimed.
The complete local website suite had 1,833 passes, ten skips and one
sandbox-blocked loopback-bind test; that exact test passed separately with
socket access. Changed-file Ruff/Black, targeted typing, JavaScript syntax and
diff checks passed. Full-tree checks retain ten Ruff findings and typing debt.

The [direct-response baseline result](LOCAL_YEAR_TWO_BASELINE_RESULT.md) is now
published in [PR #133](https://github.com/lemoz/fort-gym/pull/133) at
`5bcbfc9562837379e4a6ba78ad625b4ddef20fc3`. All 32 model-selected commands were
WAITs, advancing 32,000 native ticks. Seven citizens remained; native drink stock
changed from 60 to 53 units, with no completed rooms, workshops, beds or farms.
All 32 responses and 321,472 reported tokens reconcile. Periodic checkpoints
8/16/24 and final cursor 32 independently verify. The container, owned model,
tunnel and local VM were verified stopped. This is a fully checkpointed
invocation-limited pause, not year-two success or fortress collapse.

The [matched thinking comparison](CAMPAIGN_THINKING_COMPARISON.md) ended at an
output-limit pause after eighteen commands and 36,000 actual ticks: three
rejected BUILDs, two accepted and two rejected chopping commands, and eleven
WAITs. Seven citizens remained, with 53 drink units and no completed workshop,
placed bed or farm. Its nineteenth response used all 4,096 output tokens and
returned no action. All nineteen responses and 184,117 tokens reconcile. The
final cursor-18 checkpoint covers the entire action and usage tail; periodic
checkpoints 8 and 16 also verify. The owned game, model, tunnel and local VM are
stopped. This is a checkpointed inference pause, not collapse or year-two success.

The trial used the same original seed, Qwen3.5 9B weights, context, sampling,
native image, budgets and frozen source `fad9d80c0` as the baseline. Optional
thinking was the only configuration difference after descriptive metadata.
There was no human gameplay rescue. One pair is exploratory, not a ranking.

An audit found an inherited 2,000-tick native cap when this trial requested
2,500 ticks. [The candidate propagation fix](CAMPAIGN_NATIVE_TICK_LIMIT.md) is
published at `eca52a53021c8889ee9e63882f2184084590d391` in PR #132. Its 165 focused
tests passed with one skip, followed by the separate native verification above.
The matched pair kept its frozen runtime, and all results use actual elapsed
ticks. Do not rewrite this pair or silently resume it under changed conditions.

The baseline website record uses offline reporting revision
`73ae9c3c792127f5cd5f61b62ff6f32ce5b54049`; the thinking record uses
`5bcbfc9562837379e4a6ba78ad625b4ddef20fc3`. Execution and original reports remain
unchanged. The baseline publication passed 85 focused tests; the full suite had
1,830 passes, ten skips and one sandbox-blocked loopback test, which passed
separately with socket access. Changed-file checks and targeted typing passed.
Full-tree lint/type debt remains. Exact-head CI is tracked separately from these
local checks. PRs #132 and #133 remain open; no merge or production deployment
is claimed.

Metered model API charges for both completed attempts were $0, with no hosted
provider calls or cloud VMs. Hardware, electricity and application costs remain
unmeasured. The goal still requires a functioning fortress after 403,200 elapsed
ticks, continued year-two play, repeated comparison across at least three models,
and verified website and remote delivery. The preserved
[twelve-action prefix](../experiments/evidence/local_native_qwen35_prefix12_20260906.json)
remains a historical prefix, not a terminal record.

The preceding provider-free automatic recovery fixture passed at the same
execution source. It verified a zero-command checkpoint, stopped the first game,
restored a second game, executed a fresh 20-tick WAIT and verified cleanup.
See the [recovery receipt](../experiments/evidence/local_native_automatic_recovery_20260906.json).
That fixture used no model calls and does not count as autonomous gameplay.

## Earlier observations

Latest local native attempt: source `43a53762c` captured a fresh paused seed and
created an independently verified v3 checkpoint at cursor zero (year 30, tick
16801). Automatic recovery stopped at first-process cleanup: no PIDs were
identified by the scanner, but the listener was still live. Container-level
teardown and VM stop completed. A subsequent diagnostic failed at VM SSH startup
before creating a container. This is intermittent local infrastructure, not a
model outcome. The independent `cwd`/`exe` ownership correction has focused
regressions; native confirmation remains open. See the
[execution receipt](../experiments/evidence/local_native_harness_checkpoint_20260906.json).
No model calls, autonomous gameplay or year-two progress occurred.

The cleanup correction is source `fad9d80c0a2e7aace8380b47b009db5edaf6bd2e`
on the existing [PR #132](https://github.com/lemoz/fort-gym/pull/132). Its 73 focused
tests passed with one Linux-only skip. The full suite had 1,864 passes, ten skips
and one sandbox-blocked loopback test; that sole test passed separately with
local socket access. Changed-file Ruff/Black and targeted typing passed.
Full-tree checks still report ten Ruff issues and 464 typing errors in 26 files;
the changed runtime script passes targeted typing. Exact-revision GitHub CI is
a separate check; earlier green CI below does not cover this correction.
Native execution remains frozen at `43a53762c`; the new correction is not yet
native-confirmed. No PR merge or production deployment occurred.

Local native compatibility is now verified on the isolated `fort-gym-native-b`
profile: the retained DFHack image loaded with the narrow syscall allowance,
then the same VM rebooted after guest-initiated shutdown and automatically
loaded the fortress again. The earlier failed profile and evidence are retained.
Both test VMs and Hermes were observed stopped after the experiment. There were
zero model calls, gameplay commands, new campaign checkpoints or cloud resources.
The shared host was untouched. The subsequent recovery attempt is recorded above;
VM reboot is not campaign continuation. See
[local runtime evidence and next decision](CAMPAIGN_LOCAL_RUNTIME.md).

Earlier published candidate: [PR #132](https://github.com/lemoz/fort-gym/pull/132)
contains the one-runtime native output-pause recovery fixture, bounded closed-port
settling correction, and versioned native evidence. Source
`43a53762c0dc819055a532c5fbb4fc4714fc2fa3` is verified on GitHub. The final full
local suite passed **1,862 tests with 10 skipped**; the focused suite passed
115 tests with one skip. Changed-file lint/formatting and targeted typing pass.
[Exact-head CI](https://github.com/lemoz/fort-gym/actions/runs/34060041534) passed.
The PR remains open: merge into main requires explicit owner approval at the
tool review boundary. No merge, post-merge CI or deployment is claimed for #132.

Native execution remained frozen at `ade9af102`. The v3 checkpoint saved a
zero-command pause, then restored its agent/runner/usage state in a second native
process and executed one fresh 20-tick WAIT. The original automatic command stopped
at a transient closed-port bind failure before claiming or launching the second
process. After independent teardown/port verification, an explicitly retained
driver completed only that second phase using the unchanged original source.
This proves the native recovery plumbing, not an uninterrupted automatic CLI run.
The later port-wait correction has unit/CI coverage, not a fresh native run.

Both process lifetimes are independently verified stopped and their listener is
closed. Synthetic usage moved from 10 to 20 fixture tokens; actual model calls
and metered model charges were zero. Native time moved from year 30, tick 19309
to tick 19329. This is not autonomous gameplay, a model comparison, or an endurance
handoff; no new final checkpoint was created after the WAIT. The existing host
has about 1.9 MB above its 1 GiB floor, so no further native allocation is planned
there without a viable capacity route. Historical saves/runs are unchanged.
No VM, disk expansion, production deployment or service restart occurred.

Latest merged delivery: [PR #131](https://github.com/lemoz/fort-gym/pull/131)
subtracts planned runtime/checkpoint copies before accepting the declared
free-space floor and omits retained archive folders from NEW runtimes only.
Original saves, archive directories and old runs are unchanged. Source
`53747032d59a14a8794fb70e3ad387d0d2fc84a2` merged as
`5c1de785bd6abdbe1bc9520529c6157e44793c0d`, with identical source/merged trees.
The full local suite passed **1,814 tests with 10 skipped**; a fresh focused
recheck passed 90 tests with one skip. Changed-file Ruff and targeted mypy pass.
[PR CI](https://github.com/lemoz/fort-gym/actions/runs/34057106803) passed;
[post-merge main CI](https://github.com/lemoz/fort-gym/actions/runs/34057329489)
passed. Full-tree lint/type debt remains separately disclosed in the PR.

Read-only host metadata estimated a new runtime at 105,377,792 bytes plus
9,023,488 bytes per retained checkpoint, using a historical save only as a size
proxy. At the observed free space, one checkpoint fit the 1 GiB floor estimate;
four did not. This estimate excludes a new source checkout and future growth;
it does not reserve disk or prove native execution fits. No original archive was
deleted, no runtime started, and no VM, model request or deployment occurred.
The current continuation fixture retains two runtime copies, so it is not made
executable by a one-runtime estimate. A latest-checkpoint restart that reuses one
owned runtime is the next implementation candidate, not implemented acceptance.

Previous merged delivery: [PR #130](https://github.com/lemoz/fort-gym/pull/130)
delivers the native campaign CLI, serial checkpoint continuation, local model
adapters, versioned campaign-only measurement hooks, and launch documentation
from clean main. Its source `ff5944bbd0be9acebee93d38276acd503ff4b597` is verified
on GitHub and merged as `e58ab9a019c86f6fced7216a9e15c9b7b47bee3e`; the source and
merged trees are identical. The full local suite passed **1,800 tests with 10 skipped** and targeted
campaign typing passed for 31 source files. Historical measurement hooks,
benchmark prompts and scoring code remain unchanged. [PR CI](https://github.com/lemoz/fort-gym/actions/runs/34055072007)
and [post-merge main CI](https://github.com/lemoz/fort-gym/actions/runs/34055309145)
both passed. Native acceptance at this revision remains unrun. No production
deployment, new VM or model request was performed for this source delivery.
The broader year-two and matched cross-model gameplay goals remain open.

Previous merged delivery: [PR #129](https://github.com/lemoz/fort-gym/pull/129)
merged persistent agent memory, checkpoint restoration, cumulative provider usage
and the separate exploratory campaign policy. Main at that delivery was
`6a699246976a12b9617407dbf817fc24f3f65886`; reviewed source is
`0fbdc96367384fafd06fc1fb4722e4559d86d0e3`. The final full local suite passed
1,160 tests with five skips, and 77 focused foundation tests passed. Its
[PR CI](https://github.com/lemoz/fort-gym/actions/runs/34052891694) passed.
Post-merge main CI is a separate check. This is a Python agent API delivery,
not the native campaign CLI, production deployment or year-two acceptance.

That extraction preserves main's historical benchmark prompt, schema, and review
logic. It is not merged back wholesale over this integration branch's later
experimental benchmark changes. The newly corrected partial-token accounting
and regression tests are backported here: a missing usage component remains
unknown, and a provider error carrying partial usage is not declared nonbillable.
All 79 focused accounting, checkpoint, policy and replay tests passed on this
backport; changed-file Ruff and `git diff --check` also passed.
The next runtime delivery should build from reviewed main and preserve its
historical-protocol checks, not silently overwrite them with the integration file.

The local checkout now also has an explicit `github` remote targeting
`https://github.com/lemoz/fort-gym.git`; the existing local-clone `origin` is
preserved. The foundation branch selects `github` as its push remote. Explicit
GitHub head verification remains the publication proof.

Remote delivery: the read-only campaign website is now merged separately from the
large integration stack via [PR #126](https://github.com/lemoz/fort-gym/pull/126).
That website milestone merged at `97e4533abe0194b99c463e2fffe8cfcfb9191581`; its reviewed source head
is `f15c47830974c5490b50df5f3f12af40d64aa8da`. Its final full local
suite passed **1,064 tests with 5 skipped**; 35 focused website tests passed.
Ten terminal native records, two read-only evidence endpoints, the campaign page,
and exact condition links are included. VM and gameplay-runner changes remain in
the separate draft [PR #125](https://github.com/lemoz/fort-gym/pull/125).
[Final PR CI](https://github.com/lemoz/fort-gym/actions/runs/34044644492) and
[post-merge main CI](https://github.com/lemoz/fort-gym/actions/runs/34044875137)
both passed. Review was implementer source review, not independent peer approval.
No deployment hooks, environments, or deployment workflow were configured at the
pre-merge check. The production website was not deployed or restarted. Main is
merged back into the integration branch, preserving the immutable evidence links
and avoiding duplicate mobile Campaigns links; 62 reconciliation regressions passed.

Earlier delivery: [PR #127](https://github.com/lemoz/fort-gym/pull/127) merged the
native drink observation correction; [PR #128](https://github.com/lemoz/fort-gym/pull/128)
merged the audited long-v2 result and eleventh recorded website row. Remote main
was `3a52860e7b14bf9e3ebd6c268a59f7865f60a651`. Both PR CIs passed, as did
post-merge inventory-fix CI. The full local suites passed 1,082 and 1,065 tests
respectively, each with five skips. All three website/measurement/result milestones
are merged back into this integration branch. No production deployment occurred.

Latest native result: `local-long-v2-qwen35-20260906-a` stopped at a model output
limit, with **42 commands, 53,500 native ticks, 45 returned/accounted responses
and 442,693 tokens**. Execution remained frozen at `60fd084`. One carpenter's
workshop completed and five beds were manufactured, but none was placed and no
farm completed. Seven citizens remained; year two and sustainability are unproven.
See the [terminal result](LOCAL_LONG_V2_RESULT.md) and its versioned evidence bundle.

The last response spent its 2,048-token output allowance on reasoning and returned
no action. All returned usage is accounted for; this was not a request timeout,
native execution, fortress collapse, or exhaustion of the overall spending cap.
The first segment's cursor-32 handoff was successfully resumed. Periodic checkpoints
8/16/24/40 passed independent verification, but two later commands and the final
response remain beyond cursor 40. The final native save is retained as verified
forensic evidence, not a reconciled agent/trace/usage checkpoint. Do not automatically
resume cursor 32 or 40 over those later records.

Both isolated games, the model and tunnel are independently verified stopped.
Production revision `47c035f` and services are unchanged. Local model API charges
are zero; infrastructure, hardware and electricity costs remain unmeasured. No
new VM, historical deletion or production deployment was performed.

A read-only native inventory scan found 46 drink units while the UI still reported
60. The separately merged reader counts native units with explicit scan quality;
115 observation regressions and read-only native acceptance passed. Historical
observations are unchanged; food remains a freshness-unverified UI estimate, not
a measured production flow. This integration branch now forwards stock source/scan
metadata into the campaign prompt and labels numeric validation separately from
freshness/accessibility; 124 focused integration regressions passed. No new campaign
has used the correction yet.

The integration candidate now checkpoints fully-accounted no-action output stops
with the [v3 recovery protocol](CAMPAIGN_OUTPUT_LIMIT_RECOVERY.md), including a
pause before the first game command. Controller continuation preserves usage and
the action cursor, does not automatically retry, and consumes the unchanged
campaign allowances. Public feed/profile status and the website label distinguish
this pause from gameplay collapse. Synthetic save/load and transport coverage is
not real native acceptance; the historical long-v2 result is unchanged.

Recovery commit `6f5f2a86f4988e7a3311a2f22735848d98b9856c` is pushed and its
GitHub CI passed. Final focused validation passed 247 tests with one skip. The
broader local run had one pinned-M1b-image/current-hook comparison failure outside
that commit, explicitly retained in the [recovery proof limits](CAMPAIGN_OUTPUT_LIMIT_RECOVERY.md).

The [exact-prompt output-budget diagnostic](OUTPUT_BUDGET_DIAGNOSTIC.md) is now
prepared: two local requests comparing 2,048 and 4,096 completion tokens, with
every other serialized field unchanged and zero native actions. It is not run.
The tool reviewer blocked transfer of the private source prompt from the stopped
test host, so no model generation or source copy has occurred.

Next: native acceptance of this recovery path, then an explicitly declared
reasoning/output allowance without enlarging or rewriting the historical
condition. The existing acceptance disk is near its free-space floor; no new
runtime copy, historical deletion, volume expansion or VM has been performed.
The goal remains autonomous sustained play and repeated cross-model evaluation,
not observation tests or another infrastructure acceptance run.

Earlier: the [long local attempt](../experiments/evidence/local_native_llama_long_timeout_20260906.json)
stopped at an inference timeout on request four. **Three returned responses,
21,429 accounted tokens, three committed commands and 1,000 native ticks** are
verified. One dispatched request has no returned usage. Two workshop commands
were rejected (stale pathfinding cache and occupied footprint); one WAIT was
accepted. Population remained seven, food 45, drink 60 and wood three. Nothing
was constructed. This is neither a completed campaign nor fortress collapse.

The failure occurred before the first scheduled cursor-8 checkpoint. Zero periodic
native snapshots were exercised; there is no resumable campaign checkpoint. The
final native save at year 30, tick 20309 is separately retained as forensic evidence:
127 regular files and 8,621,334 bytes, with its inventory independently verified.
It must not be treated as an agent/trace/usage checkpoint or silently replayed.
The copied game, model and tunnel are independently verified stopped. Production
is unchanged. Execution was frozen at `034a0e87a1c283763bd494dab269f3d2a2cac9c0`;
[its CI passed](https://github.com/lemoz/fort-gym/actions/runs/34041391431).
Ten terminal model records are included in website source, not production.

The separately declared [long-v2 condition](../experiments/campaigns/local_native_llama_long_v2.json)
changes only the generation read timeout from 180 to 600 seconds. The local server
was still generating when v1 canceled its fourth request. Keep all gameplay
instructions, weights, sampling, token and dispatch limits unchanged and begin
from the original save. The independent segment deadline remains 7,200 seconds;
v2's declared decision scheduling reserve is 1,944 seconds. These are execution
bounds, not completion estimates. The terminal follow-up is described above;
configuration alone is not native-game evidence.

Earlier: [Qwen3.5 9B with thinking enabled](../experiments/evidence/local_native_llama_thinking_20260906.json)
produced autonomous resource growth: **wood stock increased from 3 to 12**.
Eight accounted responses used **58,359 tokens** and advanced **5,000 native ticks**.
Three gathering commands were accepted, two chopping commands rejected, two changed
chopping commands accepted, and one WAIT accepted. Native receipts report ten shrub
and two tree designations; these are not counts of completed harvests.

The cursor-8 checkpoint covers every response and command across two digest-linked
segments. All measured prompt counts matched returned usage. Every response included
server-separated reasoning, retained privately and included in reported completion
usage. Both copied games, the model and tunnel were independently verified stopped;
production remained unchanged. Execution stayed at
`91ba6df9f79b3a8d43bb4e862e71080258d99910`;
[its CI passed](https://github.com/lemoz/fort-gym/actions/runs/34038331022).

No construction was initiated or completed. Population stayed seven, food 45 and
drink 60. The dispatch cap was reached, not gameplay collapse. This is neither a
functioning-fortress assessment nor causal proof that reasoning mode solves gameplay:
the two short conditions also differ in output and execution bounds. That publication
included nine terminal native model records in the website source. No production deploy,
merge or browser visual acceptance is claimed.

Next: move from resource acquisition to completed production, then endurance.
The separately declared [long local condition](../experiments/campaigns/local_native_llama_long_v1.json)
starts from the original save and allows 32 decisions in one live copied game,
with native/agent/trace/usage checkpoints every eight decisions. Its two-segment,
64-dispatch and 2,000,000-token limits do not enlarge any historical campaign.
The model, gameplay instructions, action reference and sampling are unchanged
from the short thinking condition. Its timeout result is recorded above.

The opt-in `periodic_checkpoints/v1` policy retains a durable checkpoint index
before another decision. Intermediate snapshots share the segment's original
parent; only the final checkpoint is the normal controller handoff. The controller
checks their identities, calendar, usage and retained trace prefixes. A later
unreconciled failure does not make an earlier checkpoint current. Its separately
captured native save is forensic evidence, not permission to replay actions.

The existing acceptance host had 2,453,381,120 bytes free at preflight. New decisions
stop below a declared 1 GiB free-space floor; native snapshot copies also check
their measured size against that floor. These checks are not a filesystem quota
or protection from unrelated disk growth. No historical runtime, private save or
evidence is deleted or moved. Legacy short-run configurations are unchanged.

Earlier: [Qwen3.5 9B with the typed local adapter](../experiments/evidence/local_native_llama_typed_20260906.json)
finished its bounded non-thinking attempt: **16 accounted responses, 142,218 tokens,
16 WAIT commands and 1,600 native ticks**. It initiated no gathering or construction.
Population remained seven, food 45 and drink 60. Two digest-linked checkpoints end
at cursor 16 and cover every response and command. Every committed prompt count
matched returned usage, with current facts and request hashes verified.

Both isolated games, the local model and reverse tunnel were independently verified
stopped. Production revision, services and original paused calendar were unchanged.
Execution was frozen at `f04b3f92bfadf08da92039d373ee1bb62eee6e49`;
[its CI passed](https://github.com/lemoz/fort-gym/actions/runs/34037691409).
This is a dispatch-limited pause, not a model ranking, functioning fortress or first
anniversary. That publication included eight terminal model snapshots in the website source;
no production deployment or browser visual acceptance is claimed.

The separately declared [thinking-mode follow-up](../experiments/campaigns/local_native_llama_thinking_v1.json)
keeps the same weights, observations, control reference and original save while
changing reasoning mode and its explicit execution allowances. Its actual result
is recorded above; unlike short conditions are not model rankings.

Earlier: the [factual designation-reference condition](../experiments/evidence/local_native_designation_reference_20260906.json)
stopped at a request-size boundary: **15 accounted responses, 78,023 tokens,
14 committed commands and 2,800 explicitly requested native ticks**. All fourteen
DIG commands were rejected as `tile_not_designatable`; no development completed.
Twelve raw responses omitted `kind` and defaulted to `dig`; two explicitly chose it.
The exact reference and payload hashes were verified in all fourteen committed
requests. The largest was 21,977 bytes; eight requests omitted older history while
preserving current facts and latest results.

The fifteenth response omitted the required third coordinate in both DIG `area`
and `size`. Its grammar correction could not fit alongside current facts, so no
second correction request or native command was dispatched. The latest verified
native/agent/trace/usage checkpoint is **cursor 12, not 14**. Two later committed
commands and the fifteenth response require reconciliation; **do not automatically
resume from the older checkpoint** or report the one unused dispatch as completion.
All three native runtimes/listeners, the model server and tunnel were independently
verified stopped. Production remained unchanged. Execution stayed frozen at
`8148f6d55494ad88caf46a780cfbea11d16d6a4a`.

Only Qwen14 has run this four-model reference condition. This is neither spending
cap exhaustion nor established fortress collapse, a ranking or year-two success.

A separately pinned [Qwen3.5 9B local compatibility check](../experiments/evidence/local_qwen35_9b_feasibility_20260906.json)
returned three accounted responses and 1,207 tokens. WAIT and LABOR copied exactly;
DIG retained coordinates and time but omitted `kind: gather`. No native game was
loaded or command executed, and the temporary server was independently verified
stopped. This is not a modern-model native integration or gameplay result. The
[typed-contract follow-up](TYPED_ACTION_CONTRACT.md) copied all three examples exactly
with 5,303 additional accounted tokens. This is not an established cause of earlier
gameplay choices. The larger typed grammar failed a provider-free fit check on all
fourteen historical native requests under their existing 22,000-byte bound, even
after older history was removed. No historical condition was enlarged or resumed.

Earlier: [Qwen2.5 14B Q3_K_M](../experiments/evidence/local_native_qwen14_q3_20260906.json)
completed its bounded attempt: **16 responses, 82,782 tokens and 3,200
model-requested native ticks** across three saved segments. All sixteen DIG commands
were rejected as `tile_not_designatable`; no development completed. Twelve commands
changed following rejection. The final cursor-16 checkpoint includes every command,
response and usage record. Native runtimes, local server/runner and tunnel teardown
were independently verified, and production remained unchanged. The frozen native
revision remained `82645015444759f7bcebc048c34ea704930da8f4` throughout continuation.
The dispatch budget is exhausted; this is not collapse or first-year success.
The earlier cursor-6 publication remains in Git history and its separate private
audit, not an additional campaign. All sixteen request payload hashes and current
facts were verified; the largest request was 21,997 bytes.

Earlier: the [native-ground Mistral condition](../experiments/evidence/local_native_workshop_ground_20260906.json)
has completed its bounded attempt: **16 responses, 98,658 tokens and 32,000 native
ticks** across four saved segments. All 16 BUILD commands were rejected (four
stale-cache, two occupied-footprint and ten no-material rejections); no development
completed. The cursor-16 checkpoint includes every response, command and usage
record. Independent teardown verified all four native runtimes/listeners, the
model server/runner and tunnel stopped; production remained unchanged. The model
never chose woodcutting despite visible trees and `wood_usable: 0`. This is the
completed 16-dispatch development condition, not a model ranking, collapse or
year-two success. Its frozen native revision is
`82bcab14b758d6f4624e9080c857a607c2da0b51`. The earlier five-response publication is
preserved in Git history, not counted as an additional campaign.

Earlier: the [Mistral harness-repair run](../experiments/evidence/local_native_harness_repair_20260906.json)
finished at **28,000 native elapsed ticks**, with 16/16 returned and accounted
requests, 96,919 tokens and $0 metered model API charges. Four checkpoints retain
all 16 committed commands and usage. All four copied runtimes/listeners, the local
model server/runner and the temporary tunnel were independently verified stopped.
The production revision/services and original paused fortress remain unchanged.

This is clock and continuation progress, **not fortress-development success**:
all 14 BUILD commands and two INTERACT commands were rejected. Seven dwarves and
food/drink stocks of 45/60 remain; completed workshops, beds and farms remain zero.
The 28,000 ticks were all explicitly requested by the model, following 14 attested
no-write rejections. There were no fallback actions or human gameplay rescue.

The first matched three-model native development comparison is complete. It used
the same digest-bound starting save, frozen code `164ffd0ab5024de22158968bcec3f48a79dbade1`,
and [declared condition](../experiments/campaigns/local_native_packed_comparison_v1.json).
This is one attempt per model, not a ranking or year-two success.

| Model | Responses | Game commands | Native elapsed ticks | Observed result |
| --- | ---: | ---: | ---: | --- |
| Qwen2.5 7B Instruct | 16 | 16 | 1,600 | Repeated an already-enabled labor setting; no completed development. |
| Llama 3.1 8B Instruct | 16 | 16 | 0 | Repeated the same invalid digging command. |
| Mistral 7B Instruct v0.3 | 13 | 12 | 0 | Workshop placements blocked by stale pathfinding cache; a later correction exceeded the request-size limit. |

All three retained seven dwarves and food/drink stock counts of 45/60. Stock
counts do not establish production or sustainability. None completed a workshop,
bed or farm, and none reached the 403,200-tick first anniversary.

Native calls returned 224,746 accounted tokens and $0 metered model API charges.
Nine separate synthetic contract checks used 3,736 tokens; they are not gameplay.
Hardware, electricity and existing-host costs remain unmeasured. These numbers
are not reconciled total project spending or remaining budget.

## What the experiment established

- Model selection works by configuration across three local models. Their actual
  outcomes, counters, checkpoints and source hashes are retained in the
  [published comparison bundle](../experiments/evidence/local_native_packed_comparison_20260906.json).
- Packed history allowed Qwen and Llama to reach 16 requests within the unchanged
  22,000-byte allowance. Their final checkpoints include all 16 committed actions.
- Mistral's cursor-12 checkpoint retains all its committed game commands. Its
  thirteenth response and updated agent/usage state are outside that checkpoint;
  continuation requires reconciliation, not rollback to twelve-response usage.
- All eight copied native runtimes, the local inference server/runner and the
  private tunnel were independently verified stopped. No VM was created. The
  production code, services and paused original fortress were unchanged.

## Harness repairs and native findings

1. Implemented a separately declared simulation-advance policy. The original loop discards
   the model's explicit tick request whenever a command is rejected. Mistral asked
   for 2,000 ticks after each build attempt, but the stale-cache guard rejected the
   command and the loop advanced zero. The new policy honors explicit advancement after
   confirmed preflight/no-write rejections while preserving stops for unknown execution,
   unsafe native receipts and dialogs. Do not invent WAIT actions or tick counts,
   or change the historical condition retroactively.
2. Implemented correction-aware history packing. Mistral's first
   request was 21,636 bytes; adding the grammar correction produced 22,175 bytes.
   Current facts, all corrections, latest results, persistent notes and cumulative
   usage are retained; older history is reduced to fit. An irreducible overflow
   after a response still requires reconciliation, not a silent usage rollback.
3. The affected model has now completed its new bounded condition at native code
   `75cc9318f09cf79f66789f83321e76ffe08b146d`. All 16 request hashes and their current
   facts/latest results were verified; the largest request was 21,879 bytes. It
   needed no grammar-correction retry in this run. Separately, the historical
   failed correction reconstructs to 21,912 bytes with the repair, preserving the
   current facts, exact correction, latest result and persistent notes.

The [repair condition](../experiments/campaigns/local_native_harness_repair_v1.json)
declares `model_requested/v1` and `bounded_history_corrections/v1`. All original
model manifests, request/token/segment bounds and sampling settings are unchanged.
It tests the two repairs together, not their isolated causal contributions.
The clock policy is model-visible and checkpoint-bound. Nine native hooks and
Python preflight branches now distinguish no-write rejections from attempted
mutations; unknown/partial writes get no additional simulation time. No cache flag
is cleared manually, no fallback action is inserted, and old results are unchanged.

The run exposed a remaining terrain restriction: the harness requires strict
FLOOR tiles, while the installed DFHack 0.47.05-r8 Quickfort generic rule also
permits BOULDER, PEBBLES, TWIG, SAPLING and SHRUB. Four rejected commands contain
eight failed tiles split evenly between BOULDER and SHRUB. The source hash and
rule locations are retained in the new bundle. This is not proof those complete
footprints had available materials or met every other placement condition.

The explicit `dfhack_047_ground/v1` workshop condition is now implemented at
`82bcab14b758d6f4624e9080c857a607c2da0b51`; legacy strict-FLOOR behavior remains the
default. A [provider-free native fixture](../experiments/evidence/native_workshop_ground_20260906.json)
verified the complete material/construction path: its strict control rejected
BOULDER/SHRUB terrain, the new policy passed terrain and correctly rejected absent
free material, then native woodcutting supplied logs and a carpenter's workshop
reached stage **3 of 3**. This took **4,010 scripted native ticks**, with zero model
calls, no material injection, no assisted completion and no labor-setting changes.
The final 127-file save inventory and independent process/listener teardown were
verified. Production remained paused at year 30, tick 19,309. This fixture does not
count toward model development, endurance, or rankings, and its save is not reused
as a model campaign starting state.

The three original logs were already `in_building`; `wood_usable` was zero. The
existing 11x11 model map already showed two trees, including the fixture's tree.
Do not misdiagnose this particular construction sequence as requiring extra map
visibility or new inventory facts. The
[new model condition](../experiments/campaigns/local_native_workshop_ground_v1.json)
keeps observations and other bounds unchanged apart from factual workshop-policy
disclosure, allowing a controlled test of the terrain repair.

Next: address failed-decision continuation and test a newer inexpensive local model
under a separately declared condition. The terminal
[reference experiment](NATIVE_DESIGNATION_REFERENCE.md) must retain its cursor-12
checkpoint and all newer trace/usage evidence; it is not safely resumable as-is.
Keep factual terrain/control documentation, with no chosen action, coordinate,
build order or gameplay rescue. A read-only replay had fit eleven historical
requests, but the actual fifteenth response demonstrated that this did not guarantee
future correction fit. Seek autonomous resource acquisition and completed production
before allocating a longer horizon. Do not silently enlarge an active condition,
discard newer actions, substitute a scripted fixture or mix unlike attempts in rankings.

Local feasibility: the initial Q4_K_M candidate offloaded 45 of 49 layers to GPU.
Two synthetic copy requests returned (766 accounted tokens); its third request
timed out without returned usage and was not retried. That server/runner was stopped.
The separately pinned Q3_K_M candidate offloaded all 49 layers and verified Flash
Attention and Q8_0 cache in actual runner logs. All three synthetic requests returned
(1,182 tokens): two exact copies, one omitted the supplied DIG `kind`. This proves
bounded transport feasibility, not exact format fidelity or autonomous gameplay.
Both synthetic runs have zero metered model API charges; operating costs are
unmeasured and the timed-out request's token count is unknown.
Retained runtime copies currently cost about 335 MB per segment versus about
9 MB for its checkpoint. Use a bounded continuous-runtime/retention design before
large endurance campaigns; no historical evidence has been deleted.

Repair checks: 620 focused campaign/helper/clock/memory tests passed locally and
188 passed on the isolated Linux host. Its 15 Lua-only tests were skipped because
no Lua interpreter is installed there; all 15 executed locally against engine
doubles. Full CI at the native revision passed 2,697 tests but failed three older
exact-receipt assertions in work-metric tests. Those assertions now check the new
no-write field; the final expanded local suite passed **651 tests**, with one
Linux-only skip, including the actual four recorded campaigns through the page
and feed. Focused static/typing and JavaScript syntax checks passed. Fresh remote
CI verification is tracked on the PR.
These test results do not substitute for native construction or website acceptance.

The prior full CI run at `d396c456fb30a247925115de762aa45154031f47` passed. The
workshop change passed **685 focused local tests** (one Linux-only skip), including
20 additional Lua control-flow cases, and **142 isolated Linux tests** (20 Lua
cases skipped there). Native fixture success is separate evidence above. Remote
CI for `82bcab14b758d6f4624e9080c857a607c2da0b51` passed in run `34026849553`.

## Website and repository

The existing campaign page now supports versioned terminal snapshots even when no
live feed is configured, with profile, command mix, adapter-readiness limitations,
native time, resources, costs and source identity. A broken configured live source
still reports an error instead of pretending old data is current.

There are now **seven recorded model snapshots**, including the completed bounded
native-ground and Qwen14 baseline campaigns and the request-bound control-reference
campaign with its unsaved-command boundary. The successful
scripted workshop fixture has a separate
adapter-acceptance section and evidence link, never a model-comparison row. The
pre-publication combined local suite passed **702 tests** with one Linux-only skip; targeted
typing, static and JavaScript syntax checks also passed. No browser-only preview
or visual QA was performed in this background goal continuation. Publication CI
for `2a47c74964c6a7fab9938afacc79b5a6309bc15d` passed in run `34027753420`.
Full CI also passed for completed-Mistral publication `3692be5b18c0232560af92966ecef6c46d672463`
(run `34029396944`) and the Qwen native revision (run `34029621187`). The latter
also passed **71 targeted Linux tests**. Native outcomes remain separate from CI.
The earlier six-record publication suite passed **703 local tests**, with one
Linux-only skip. Its full CI passed in run `34030522017` at
`bdaa23042bb47860ae943be462e75f29b1435812`. The reference-control implementation and
expanded local suite passed **719 tests**, with one Linux-only skip, including the
completed-Qwen website record and designation-condition link regressions. Focused
Ruff, Black, typing and JavaScript syntax checks passed. Full remote CI passed for
the reference execution revision in run `34031851418`. The latest seven-record
publication passed **720 focused local tests**, with one Linux-only skip, including
a separate regression for its exact prompt evidence, defaulted designation modes
and unfinished condition. Targeted static, formatting and typing checks passed;
its full publication CI passed in run `34032869590`. The terminal reference update
is a separate publication slice: **515 targeted local tests passed**, five native
environment checks skipped, including endpoint and frontend test-double regressions.
Targeted Ruff, Black and JavaScript syntax checks passed. Fresh remote CI is tracked
on the PR; this local suite is not a native-model acceptance run or browser visual QA.

Terminal-result publication `5e595ecd826980b3d25fa57f7cdc5ba96f5fe7af` passed remote
CI run `34034704331`. The subsequent typed-contract implementation and paired
diagnostic passed **531 targeted local tests**, with five native-environment skips;
focused static, formatting, typing and JavaScript syntax checks passed. Its new
publication revision has separate CI and no new native-gameplay acceptance claim.

[Draft PR #125](https://github.com/lemoz/fort-gym/pull/125) is the integration surface.
The website/reporting code is separate from the frozen native execution revision.
Review, merge, production deployment and real-site acceptance remain open. Local
endpoint and frontend regressions are not browser visual QA or deployed acceptance.

Published-comparison checkpoint checks: 632 focused local regressions passed, one Linux-only
test skipped. The actual published three-model bundle is checked through the
campaign page/feed routes, with measured tick counts, adapter rejection counts,
final checkpoint status and usage retained. Focused Ruff/Black, JavaScript syntax
and targeted typing checks passed; global legacy static-check debt is separate.
