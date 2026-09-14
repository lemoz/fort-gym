# Native keyboard live status

The existing `/campaigns` page separates a current host observation from recorded
campaign results. `/public/keyboard-active` serves only an allowlisted projection
of `keyboard-active.json` in `FORT_GYM_PUBLIC_CAMPAIGN_DIR`; it never scans private
model or native-game artifacts. Both endpoints disable HTTP caching. Existing
recorded campaign endpoints and their evidence stay unchanged.

`scripts/campaign_keyboard_observe.py` produces this replaceable derivative from
an already running, explicitly identified native operator and its completed host
receipts. It validates the audited startup, source/configuration hashes, request
digests, consecutive receipts, dispatch identity and token reconciliation. The
historical failed-delivery token amount must be explicitly supplied. The observer
does not start, query, control, or stop a game, model, VM or container. A fixed
process start-time/command fingerprint prevents a reused PID from counting as the
original owner. It stops after publishing the original owner's exit.

Example from the separate website worktree, with the existing project Python:

```sh
python -m scripts.campaign_keyboard_observe \
  --run-dir /absolute/path/to/the/owned/run \
  --condition /absolute/path/to/declared-condition.json \
  --window /absolute/path/to/declared-window.json \
  --public-dir /absolute/path/to/project-owned/public-derivatives \
  --owner-pid 12345 \
  --historical-failed-delivery-tokens 69004
```

Paths, PID and historical usage in this example are not reusable authorization or
defaults. Resolve the actual owner and retained usage for each experiment. The
producer requires the audited `preflight.json`, `live-start-review.json`, initial
agent, launch record and operator file already retained by the native window.

## Meaning of the displayed data

- `running` means the declared run controller was alive at the host observation,
  not that the model is currently generating or the game is unpaused.
- `stopped` means that controller ended. Terminal outcome, save and mandatory
  VM/container cleanup still require independent verification.
- After 30 seconds without a new observation, the status becomes `stale` in both
  the API and browser. Failure to fetch hides the live card's old counters.
- Saved ticks and checkpoint cursor remain the audited starting save. Later
  game-time feedback is an **unsaved lower bound**, never silently added to saved
  progress. The first request's potentially retained feedback is excluded. When
  no subsequent feedback exists the value is unknown, not zero.
- New responses/tokens come from completed host receipts. In-flight requests and
  a response whose receipt is not complete are not yet represented. Unknown
  dispatch or incomplete usage prevents fresh publication.
- Charge is unreported, not zero. This subscription-only schema refuses a newly
  reported charge rather than silently discarding it.

The preview polls only while visible and provides a manual refresh. It uses the
existing site's styles, dependencies and read-only data surface. Keep the preview
loopback-only with dotenv, game integration, admin access and model credentials
disabled. Run it separately from the immutable source serving a live native
experiment. No production deployment or model-performance acceptance follows from
this page or its tests.
