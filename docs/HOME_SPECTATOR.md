# Homepage spectator

The existing Fort Labs homepage now begins with a read-only screen/action player.
It uses the existing FastAPI server, theme and static asset route. No additional
frontend dependencies or game connections are required.

## Recorded mode

The initial curated set contains 288 captured native screens:

| Recording | Decisions | Save boundary | Condition |
| --- | --- | --- | --- |
| Astra | 97–256 | 224; 225–256 are an unsaved observed tail | Displayed-key bindings |
| Sol, replicate 1 | 65–128 | 128 | Native keyboard interface events |
| Terra, replicate 2 | 65–128 | 128 | Native keyboard interface events |

These are recent windows, not complete embark-to-finish campaigns. Different
conditions must not be interpreted as a matched ranking. Astra's final save
failed; the recorded tail does not imply a recovered checkpoint or game collapse.

Screens are the exact pre-action tile grids sent to the model, rendered with
CP437 glyphs and a classic 16-color palette. They are not PNG screenshots or
generated illustrations. The displayed action is the model's explicit `intent`
and key sequence. Population and elapsed ticks are labeled as after-action data.
Rejected input is visible but never represented as executed input. There is no
interpolation between captured screens and no full-world or offscreen terrain claim.

Controls: play/pause, 1×/2×/4× decision playback, previous/next, an accessible
decision scrubber, recent-move selection, and enlarged horizontal screen scrolling.
Repeated game ticks retain separate model decisions. Switching recordings stops
playback. Loading failures do not erase a previously loaded recording.

The catalog lives at `web/static/recordings/catalog.json`. Its recording and audit
digests identify the included derivatives and reviews. The exporter at
`scripts/export_home_recording.py` requires an explicitly selected private attempt,
audit, and expected audit digest. It verifies consecutive receipts and matches
each screen's request hash and action to the reviewed trace. The public files
contain only the allowed screen/action/time/population fields, not prompts, model
memory, provider event bodies, credentials, or local paths. Typed keyboard rejection
receipts recover an invalid model choice without manufacturing a replacement.

## Live mode

`GET /public/watch-active` reads only the bounded regular file `watch-active.json`
in the existing `FORT_GYM_PUBLIC_CAMPAIGN_DIR`. It never scans private attempts,
opens a DFHack socket, dispatches a model call, or sends game input. Responses are
`no-store`; absent, stopped, unavailable and expired observers are distinct states.

For the next eligible native-keyboard run, add `--publish-watch` to the existing
`scripts.campaign_keyboard_observe` invocation. All its normal audited-startup,
explicit owner PID and receipt checks remain mandatory. The optional publisher
creates an atomic, allowlisted derivative from the latest completed model exchange
alongside the existing counters. It reuses that observer's process-identity check
and stops with its owner. Do not retrofit or edit a frozen executed runtime.

The homepage polls the derivative every 10 seconds while visible. An observation
expires after 30 seconds without an observer heartbeat, including on a failed
refresh. The viewer shows the screen capture time separately: an active controller
does not mean the model has produced a new decision. This is sampled decision
coverage, not continuous video or streaming internal reasoning. Live keys are
explicitly *chosen, not execution verified*; typed rejection remains a rejection.

On initial load a fresh broadcast takes precedence over the default recording.
Choosing a recording or inspecting an earlier live decision disables automatic
following until “Jump to live” is selected. Up to 128 observed live decisions are
retained in the browser tab only. Losing the broadcast returns to recorded mode.
There is no guarantee of complete live history; permanent replay requires a later
evidence export. A server with no configured derivative serves recordings normally.

## Verification and delivery boundaries

Python tests cover endpoint behavior, expiry, bounded file handling, public-field
projection, receipt binding and bundled evidence. Node tests decode every retained
screen and exercise controls and disconnect behavior with an in-memory DOM, without
a browser or game session. Test fixtures are never installed in the public live feed.

The local preview is separate from the existing campaign preview. Browser visual
QA and a real active-session broadcast acceptance are still pending. This change
does not start a campaign, merge to main, or publish the public website. Existing
experiment sources and saves remain untouched.

Local verification on September 11, 2026:

- Final focused homepage, observer and landing-page tests: 43 passed, including
  four Node contract tests (full CP437 coverage, all 288 recordings, controls,
  failed/out-of-order loads and live expiry).
- Regression run before the final hardening: 5,079 passed, 10 skipped, one
  localhost bind test blocked by the sandbox. That exact test passed with local
  port access. The final hardening was rerun through the focused suite.
- Changed Python files pass Ruff. Repository-wide Ruff has 10 existing findings;
  mypy has 465 existing errors in 27 files, matching the parent worktree.
- Local homepage responded HTTP 200. Browser visual QA was not requested and
  was not performed. The spectator projection also read the retained latest
  Astra exchange as stopped, decision 256, with a 120×40 screen; this derivative
  was not installed as a live broadcast.
