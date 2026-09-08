# Partial native-action failure and explicit restart

Window r ended after 23 model responses, 22 committed decisions and a clean
691-tick dialogue interruption that the old loop rejected against its pre-input
screen. The later save request remained pending. Checkpoint 711 is still the
last verified save: none of the 6,691 newly observed ticks were saved.

The clock correction in `c12103397` uses the paused post-keyboard boundary.
The restart addition is separate: it permits an explicitly declared loss-aware
restart only when the retained partial-action, usage, failed save, unchanged
native files and terminated runtime evidence all agree. It does not repair the
old trace or replay any model action.

## Evidence and accounting

The declaration retains schema `fortgym.native-save-loss-restart/v1` with an
explicit `failure_kind: partial_interruption_pending_save`. Existing timeout and
pre-save classifications remain unchanged and reject this unsettled source.

- The last committed trace cursor is 733; the additional failed action is not
  silently promoted into a committed row.
- `lost_elapsed_ticks` includes the complete 6,691-tick unsaved tail.
- `lost_uncommitted_ticks: 691` is a subset of that total, not an extra addition.
- `lost_uncommitted_decisions: 1` exposes the response beyond the committed tail.
- All 814 responses and 26,113,503 campaign tokens remain counted. The 69,004
  historical failed-delivery tokens remain separately recorded. Actual dollar
  charges remain unreported, not zero.
- The restart record binds the checkpoint, trace, usage journal, failed segment,
  partial failure, save attempt and terminated runtime by digest.
- Model memory comes from the restored save checkpoint. Restart feedback states
  the loss; it supplies no replacement strategy or gameplay keys.
- A later restart attaches this record to existing history. Merely preparing it
  does not turn the two historical losses into three executed restarts.

## Next declared experiment

`experiments/campaign_astra_keyboard_window_20260908s.json` restores save 711,
retains the 64-decision cadence and existing model, display, observation and save
profiles, and inherits the 1,024-dispatch / 40-million-token ceiling unchanged.
Fresh native load verification and subscription admission remain required.
There is no API fallback, local model, automatic purchase, reset or action replay.
Every owned game/container/VM must be torn down with original evidence retained.

The added synthetic tests cover the partial loss, full usage retention, checkpoint
memory, no replay, subsequent save/resume, cumulative progress, malformed source
evidence, runtime identity, newer saves, and missing provenance. Retained window-r
evidence is also checked read-only before launch. These checks prove restart
preparation, not a successful native run or year-two gameplay. A continuation that
does not encounter the relevant dialogue transition is not native acceptance of
the clock correction by itself. Website failure publication and native acceptance
remain separate work.
