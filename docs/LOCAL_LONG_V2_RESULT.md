# Long-v2 native campaign result

Campaign `local-long-v2-qwen35-20260906-a` is terminal. It ran frozen code
`60fd08415b10adfe52a0d275c826669dad843937` with the declared
`local-native-llama-long-v2` condition. It is not a year-two result or a model ranking.

The [audited public bundle](../experiments/evidence/local_native_llama_long_v2_20260906.json)
contains exact conditions, the full 43-boundary public timeline, source hashes,
checkpoint lineage, native measurement limits and teardown receipts.

## Gameplay and failure

- 42 committed commands, 53,500 elapsed native ticks (13.27% of one game year).
- 45 dispatched/returned/accounted responses, 442,693 tokens; no missing returned usage.
- 36 accepted commands and six rejected. A carpenter's workshop completed and
  five beds were manufactured. Zero beds were placed and zero farms completed.
- Seven citizens remained. Food/drink figures in the frozen trace are UI counters,
  not independently fresh inventory or production/consumption measurements.
- The last response returned `finish_reason: length`: all 2,048 completion tokens
  went to reasoning, with no action content. No native command was dispatched
  from that response. This is an output-limit failure, not fortress collapse.

## Continuation and retention

The first segment's final checkpoint covers 32 commands and all 34 responses then
returned. A real second segment successfully resumed that exact checkpoint.
Periodic native/agent/trace/usage checkpoints at cursors 8, 16, 24 and 40 passed
independent verification. The controller's normal handoff is still cursor 32;
its later periodic checkpoint is cursor 40, not the final cursor 42.

Two commands and the final returned response remain beyond the latest periodic
boundary. The last native save at year 30/tick 72809 was retained and its 127-file,
8,681,190-byte inventory verified, but it is forensic evidence rather than a
reconciled agent/trace/usage handoff. Do not automatically resume an older checkpoint.

Both isolated games, their listeners, the temporary model and the reverse tunnel
were independently verified stopped. Production revision and services were unchanged.
Local metered model API charges were zero; existing-host, hardware and electricity
costs remain unmeasured. No new VM, hosted inference, historical deletion or deployment
was part of this run.

## Measurement correction and website

At year 30/tick 67809, a read-only scan counted 46 drink units while the UI counter
still showed 60. The correction is shipped separately in PR #127; this historical
trace is not rewritten or rescored. Manufactured item counts also remain distinct
from completed placed furniture.

The read-only campaign website now selects this deliberately published bundle
alongside ten earlier native records. The real resumed feed previously passed
nine in-process HTTP checks against merged website code `97e4533`; that was not
browser acceptance or a production deployment. The result publication preserves
existing FastAPI/static architecture, explicit failure states and immutable links.

Validation for this main-based result slice: 1,065 full-suite tests passed,
5 skipped; 36 focused website/API tests passed. Changed-file Ruff and mypy pass.
Full-repository Ruff retains ten existing findings and mypy reports 470 errors
in 28 files. Repository-wide lint/type cleanliness is not claimed.

Next experiment work: retain the output-limit failure as a distinct condition;
make fully-accounted no-action output stops checkpointable, and test adequate
reasoning/output allowance without altering these frozen results. Carry the native
stock-source metadata through the campaign observation before the next declared run.
