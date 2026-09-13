# Year-Two release candidate: native harness plus published spectator UI

This development candidate combines the existing native harness with the
published spectator website. It does not replace the active experiment, deploy
the combined application, merge main, or alter PR #176.

## Source boundaries

| Component | Exact source |
| --- | --- |
| Native harness and serial continuation coordinator | `4ce541fbe0cc20556744cd381298c31f1fb580a2` |
| Published spectator website and audited recordings | `3016ab690190affd1435e93bf6e3ff2c12370b37` |
| Active campaign's frozen native implementation | `4b526b5636e6f568a4cae1a1227d746d9c6922c3` |

The candidate starts at the coordinator source. Its Python implementation,
DFHack helpers, experiment configurations, execution/export scripts, dependency
configuration, and CI workflow remain unchanged. The private native-production
observer candidate is not included.

The website import contains 32 recordings and 2,600 frames, ending at the
decision-580 save. No recording, screenshot, action, metric, or comparison result
is regenerated. The saved boundary is 403,050 elapsed ticks, just before the
403,200-tick anniversary. Later live progress is separate and is not promoted
into this immutable recording snapshot.

## Compatibility decisions

A direct branch merge conflicts with older runtime changes in the website
branch. This candidate imports only the selected public assets, their tests,
and publication documentation instead of replacing the native implementation.

- Keep all harness-only campaign tracking pages, JavaScript, and tests.
- Retain the existing desktop and mobile Campaigns links on Home and Results.
- Keep the harness's protocol page and supported G7-v3 footer link. The published
  branch's G7-v5 link depends on a different backend calibration catalog.
- Keep the current server-settings fixture in the spectator endpoint test;
  changing only an environment variable does not replace cached settings.
- Keep the newer native exporter's rejected-shortcut evidence handling.
- Import the public pre-action/post-action replay labels, repeated-model
  comparison, shortcut recordings, and endurance recordings unchanged apart
  from the two navigation restorations above.

The Sites compatibility pass informed these decisions: preserve the existing
site architecture and working capabilities. No hosting migration, registration,
deployment, or browser handoff is part of this candidate.

## Verification and release limits

The source manifest records imported asset hashes, retained campaign files, and
the unchanged native Git trees. Integration tests exercise both website and
campaign routes, same-process static assets, supported protocol links, every
recording's HTTP bytes, and explicit disconnected feeds.

The candidate still requires its own complete test run and review. Test results
are development verification, not additional native gameplay or public
acceptance. Main promotion and combined-host deployment have not occurred.
The running coordinator, its frozen source, and its VM remain untouched.
