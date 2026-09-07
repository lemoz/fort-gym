# Reasoning-budget campaign: first completed segment

September 7, 2026 UTC. A bounded segment completed, not a completed fortress.

## Observed result

The autonomous Qwen3.5 9B campaign committed 32 model-selected commands and
advanced the native game by 76,000 ticks, 18.85% of one elapsed game year.
Seven living citizens remained. One workshop completed; no beds or farms
completed. Drink inventory declined from 60 to 39 native units. Food, wood,
stone and final functional-room measurements remain unknown. Food/drink
production and consumption were not measured, so sustainability is unproven.

Of the commands, 25 were accepted and seven rejected: BUILD 1/3, DIG 3/4,
LABOR 1/0, ORDER 1/0 and WAIT 19/0 (accepted/rejected). An accepted production
order does not prove manufactured output. The first completed workshop was
observed after command 14 at 31,000 elapsed ticks; the previously published
progress receipt and its exact retained trace prefix remain unchanged.

All 32 returned model responses ended with `stop`. Independently summing
their prompt and completion token receipts gives **325,234 tokens**, matching
the cumulative agent, segment and controller ledgers. All requested native
tick advances matched the actual advances. Metered model API charges were
**$0**; local hardware, electricity and application costs are not measured.

## Checkpoint and teardown audit

Native saves and bound agent, runner, trace and usage files verified at cursors
8, 16, 24 and 32. The final checkpoint covers all commands and returned usage.
Its manifest SHA-256 is
`9107218b7c5fea3638e329e631a9e9b1d763457cb7f80092fe3a4679c67824e3`;
its payload digest is
`da0a930525210d16bfcf437657159050a1df1713332c73b5dac787b860e43129`.

The original owner exited successfully. Its final container state was exited
with code zero and no OOM. Native cleanup was verified; model and tunnel PIDs
were independently absent, their loopback listener was free, and the isolated
local VM was independently observed stopped. The Docker context was unchanged.
No cloud VM, hosted model fallback or production deployment was used.

## Publication and continuation

The [versioned result](../experiments/evidence/local_native_qwen35_year_two_reasoning_segment1_20260907.json)
has SHA-256
`2ccbe8ef5b7f2f663fdebf688b9bf8faae3362603e508edf9fbf976094ebc731`.
Execution remains frozen at `de69c7a467eb0b00becfef03329bac9f58690e35`.
The independent offline reporter is
`80eea7dc7e0d1b853a6918d4f2e5b639dc081faa`. Its newer native-v2 reader
extracts population and drink measurements from the retained raw observations;
the original producer's public snapshots are not rewritten or backfilled.

This is the fourteenth recorded campaign in the website API. The older
three-command public capture remains immutable and cannot roll back the newer
terminal record. A later matching live continuation can replace that record
without creating another campaign or counting a resumed segment as a new trial.
For later terminal publication, retain this bundle and replace this campaign's
registry pointer with the newest cumulative bundle. Never sum checkpoint prefixes.

The controller stopped at `invocation_limited_pause` after
`bounded_segment_complete`, with seven segments left in the existing envelope.
The separate prepared continuation uses the same campaign, source, model,
condition, evidence volume and cumulative budget. It restores cursor 32,
without seed reset, injected actions or human gameplay rescue.

Year-two play requires 403,200 elapsed ticks plus a functioning autonomous
fortress, not just elapsed time. This attempt has not achieved that. The earlier
thinking-on/off pair used a different runtime; this new reasoning-budget attempt
is exploratory, not a matched causal comparison or model ranking. Repeated
comparable multi-model evaluation remains open. Merge, browser visual acceptance
and production deployment are separate, unclaimed release steps.
