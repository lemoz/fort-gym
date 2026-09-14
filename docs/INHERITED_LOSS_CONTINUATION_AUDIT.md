# Ordinary continuation after an audited recovery

The Astra recovery save retains trace cursor 256, but all 288 actual model
responses remain accounted because 32 earlier responses were not saved. The
ordinary window auditor previously equated these two counters and rejected any
loss history, even when it had been retained unchanged from a verified parent.

This correction changes read-only audit code only. Window declarations bind
their prior response and token totals to the parent checkpoint's actual agent
state. Segment audits still reconcile the full usage journal and exact trace
prefix. Accounted responses must equal saved decisions plus the fully recorded
inherited lost decisions, with no new loss or counter reset during the window.

The same validated loss records must appear in the parent and final runner,
segment result, history-before capture and every new trace row. Loss telemetry
must remain unchanged. The span checker still rejects loss by default; its
optional inherited history must be supplied by the verified-parent caller.
Reports expose that history and mark recovered campaigns as interrupted.

Synthetic tests exercise a real failed-save/recovery/continuation chain with
the actual checkpoint and usage-journal implementation. They cover multiple
segments, a final no-response admission pause, incorrect baseline counters,
and erased or altered loss metadata, including self-consistent file digests.
This is test evidence, not a new native reload or new gameplay result.

No controls, prompts, model, budget, save implementation, runtime image or
gameplay strategy are changed. The previous native source remains frozen at
`d22f28d99f4fd103188979e964e148139d3f3efd`. The next native owner must pin this
separate auditor revision and its declaration before launching ordinary play
from the recovered save; it must not repeat the restart or replay lost actions.
