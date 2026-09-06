# Two-fort reliability goal

Status: COMPLETE for the bounded two-fort reliability goal. Real DF-KILL
acceptance passed in batch `m1b-live-20260905-7e4d84d188cc`, with complete
retained diagnostics and independently verified cloud teardown. Full M1b
remains `INCOMPLETE_NO_GO`, deliberately separate from this focused goal.
See [final proof](2026-09-05-two-fort-acceptance-proof.md). Entries below
preserve the chronological investigation and earlier, superseded states.

LATEST AUTHORITY (September 5, 12:18 UTC): operator explicitly directed
continued work without repeated per-VM approval under a USD 250 ceiling.
Current-series prior reservations total USD 40. The remaining USD 210 is
tracked in `fort-gym-m1b-continuation-20260905/daily-ledger`, permitting at
most 26 further USD 8 reservations, one VM active at a time, with mandatory
teardown and independent absence checks after each. All continuations must
reuse that ledger, even when packet-retention rules require another output
root. The existing 20:00 UTC expiry remains. This supersedes the single-VM
renewal below; no further per-VM approval is needed within these bounds.
The scripted diagnostic makes zero paid model calls.

Tick-fix packet manifest:
`843df75d7ab8b02124c7b0e54ac1ec8f5bee75eba22bba5d1af771f7f4fa37d4`.
Two independent builds match; 371 targeted local tests pass. Runtime proof
is pending in the next continuation, not established by packet determinism.

Continuation `c61f4e43207e`: all DF-KILL runtime criteria passed in the raw
gate result: detection 1.241235882 seconds, cleanup 11.672519661 seconds,
target runtime_df_killed without OOM, peer observed at step 5 without
reconnection and later completed step 19. Both attempts committed terminal
evidence. Overall DF-KILL was correctly downgraded to FAIL because the
3,440,341-byte peer trace was truncated at the 2 MiB diagnostic file limit.
Target capture was byte-exact. VM lifecycle completed with independent
instance/disk/address absence proof. Total current-series reservations: USD 48.

Capture fix: only the exact artifacts/trace.jsonl selection receives a 4 MiB
limit. Other files retain 2 MiB and the per-run maximum stays 8 MiB. Complete
3,440,341-byte retention and continued overall-limit enforcement have tests;
93 diagnostic/host tests passed, as did the full 79-test lifecycle suite.
Packet-complete-trace manifest is
`831bbcb6f4890e63bdb5b435eca4e624435e576018a11060518c70e54940ed52`,
with two independently identical builds. Source-tar comparison against the
previously executed packet shows only infra/m1b/diagnostics.py changed; no
files were added/removed. Runtime, seed and dependency archives are identical.

Execution safety blocked launch `7e4d84d188cc` twice before command execution,
including after the above comparison and prior verified destination evidence
were supplied. The rejection requires explicit approval of this packet
transfer to account cdossman91@gmail.com, project scrolller-307201,
zone us-central1-a. Do not use another tool, wrapper or upload route to
circumvent that refusal. No new reservation or VM was created. This is a
platform safety blocker, not exhausted user budget; real-DF verification of
complete diagnostic retention and final goal acceptance remain unproved.

The operator explicitly approved the blocked transfer. Launch 7e4d84d188cc
then began using the exact prepared packet and shared continuation ledger.
The operator also clarified that model calls are permitted if needed while
keeping today's spend below USD 250 and that routine in-scope actions do not
need repeated approval. No model calls are needed or enabled for this
scripted acceptance run; its provider-free packet remains unchanged. All 373
targeted local tests passed with the final trace-capture fix. Do not count
the new run as accepted until its complete evidence and teardown are checked.

September 5 renewal: the operator unblocked the requested one-VM diagnostic
and directed continued work without repeated permission requests within the
approved budget. The renewed execution allocates exactly USD 8 after USD 32
prior reservations, maximum USD 40 under the USD 50 allowance. It uses a new
dated ledger in `fort-gym-m1b-diagnostic-20260905/daily-ledger`, limited to one
reservation; prior ledgers remain unchanged. A conservative hard expiry of
2026-09-05T20:00:00Z and the existing eight-hour maximum are enforced.
The actual agent is `dfhack-governed-scripted`, with zero model calls.

Run `8d68c0e87cb5` was launched with packet manifest
`02eaba7457d509a18a95ede15034ead2a8c0d3d833e8e8e0646704c1186ae5b2`,
verified by two independent builds. All 321 targeted core/packet/security
tests passed; eleven focused fake-cloud lifecycle checks and the separately
rerun authority-projection check passed. Bootstrap and the live outer egress
guard completed. Runtime acceptance and teardown are not yet claimed at
this checkpoint. The older authority narrative below is historical.

Renewed run result: lifecycle completed with independent instance, disk and
address absence verification. The focused gate remained incomplete (two
runtime attempts started, zero acceptance completions). The new diagnostics
finally identify the rejected predicate: all 120 peer samples spanned
monotonic 194.875895990 through 224.733151114; first/last status was running,
PID 4848 remained present, and progress advanced from step 2 to step 4.
After the timeout the peer committed step 5, then received host_gate_failed.
Both manager and supervisor terminal evidence was retained; target ended at
step 3. The old shared roughly 30-second polling window was insufficient
for this real peer to reach the required step, not a missing worker or
non-running registry status. This supersedes the fast-exit hypothesis.

Local fix: M1BFaultDriver now optionally separates peer-state poll attempts
from target-state attempts. Defaults remain unchanged; only the host's
DF-KILL path selects 480 quarter-second polls (119.75 seconds of sleeps),
below the session's 180-second hold. Target detection still has its separate
frozen 10-second requirement, cleanup still requires 30 seconds, and peer
acceptance still requires live running step 5 without reconnection. No gate
or threshold changed. A provider-free delayed-progress regression exercises
the old 29.75-second target cutoff, successful peer observation at 31 seconds,
and bounded failure when progress never arrives. All 230 targeted tests
passed with Ruff; the host source pin was updated. No real-DF rerun of this
fix has occurred, so the goal remains incomplete. Total reservations are
USD 40, not verified billed spend; paid model calls remain zero.

Follow-up audit found that extending peer polling alone is insufficient.
`cleanup_started` precedes the target's pre-cleanup session observer, which
waits for the peer's completed receipt. The actual target journal measures
32.423094178 seconds from cleanup_started to terminal_pending, exceeding
the frozen 30-second bound. Do not move the timing marker or exclude this
wait to manufacture a pass.

The same raw trace exposes the upstream contract violation: acceptance
`run_bounds.max_ticks_per_step` is 200 and the supervised request specifies
200, but the scripted agent emits 1000 and the runner uses agent-requested
ticks instead of enforcing that bound. Peer steps each take approximately
10.2 seconds of recorded tick advancement, explaining why three post-fault
steps exceed the short polling/cleanup envelope. The current parser allows
2000 outside P1 and does not apply the supervised 200-tick limit. Next work
must configure the external scripted agent from its declared step budget
and reject over-budget actions at the supervised runner boundary. Preserve
ordinary agent defaults and the immutable 200-tick acceptance bound. No
additional cloud run was made during this audit.

Tick-bound implementation: DFHackGovernedScriptedAgent now has a validated
ticks_per_step constructor setting, retaining the ordinary 1000 default.
All seven action branches use that setting. The experiment runner constructs
the external scripted worker with the declared run ticks_per_step (200 in
M1b), while ordinary factory routing is unchanged. The supervised scripted
run_once parser independently rejects advance_ticks above the declared
budget before applying or advancing the action. It does not silently clamp
or rewrite an agent's action, nor alter the frozen acceptance contract.

Provider-free coverage confirms valid/invalid constructor bounds, the
external-worker creation path supplying 200, an actual mock-backed supervised
run retaining the rejected 1000-tick action in its trace without tick
advancement, and unchanged ordinary scripted behavior. All 253 targeted
agent/experiment/mock/fault/session/host-runner tests passed with Ruff and
diff checks. The current frozen packet predates this fix; no real-DF claim
or additional reservation is made. Requested-tick enforcement is local
proof, not proof of real DF advancement or sub-30-second target cleanup.

Full external-worker local check: a real Python CLI subprocess now runs the
scripted agent against MockEnvironment from a serialized experiment config,
with a preassigned SQLite run and a minimal credential-free environment.
Its three trace steps request 200 ticks and advance exactly 200 each, reaching
mock times 200, 400 and 600. Exit is successful while the registry remains
running without ended_at, preserving supervisor-owned terminal/cleanup
semantics. This exercises configuration through CLI, experiment creation,
agent selection, action parsing and tick execution together, not a mocked
run_once callback. All 266 targeted tests passed. It remains mock-environment
evidence, not real DF timing, isolation, teardown or acceptance proof.

Latest authority: at 2026-09-05T02:59:28Z the user approved up to USD 50
tonight. The first USD 8 reservation is retained; the new operational budget
is the remaining USD 42, with at most five additional USD 8 attempts and one
VM active at a time. All continuation attempts share
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1b-diagnostic-20260904-r2/daily-ledger`.
The prior one-VM checkpoint below is historical. Full-matrix execution,
paid models, production changes, publishing and pushes remain unauthorized.

Continuation run `ec4f19f73de5` passed the journal creation window but failed
at ownership inspection: its exact broker reason hash maps to
`container inspection escaped its run binding`. The host fault runner sent
the peer's container-inspect request using the target's binding. A local
regression reproduced that exact rejection against the unchanged root broker.
The fix resolves bindings only for exact container-inspection requests and
limits them to the named target/peer cohort. Mutating commands remain bound
to the target. Other runs and cohorts fail closed. All 252 targeted tests
passed after the routing change. The second VM's lifecycle is complete with
independent absence verification; both attempts remained incomplete.

The corrected continuation packet is `packet-peer-binding`, manifest
`ce848306e22159f5a40ad817cc2752c79a8865594c11b2b6b6f20de803211a25`,
with two byte-identical independent builds. The third VM attempt is
`fe7c3b35f074`, using the same continuation ledger and teardown controls.

Third-run outcome: fault injection reached `action_attempted`; the target
failed at step 3 and the peer independently completed at step 19. The driver
nevertheless timed out awaiting its required live `peer_after` observation.
A fast-exit race was suspected, not established. The fourth run below shows
that it is not a sufficient explanation. Both acceptance attempts remained
incomplete, so no GO was claimed.
The VM was deleted; a timed-out deletion command was followed by resource-not-
found and independent residue-free verification, not treated as a leaked VM.

The next local fix holds the DF-KILL peer at its existing required step 5
until the completed driver receipt is published. The peer must first have a
verified action-bound step-2 release and actual committed step-5 trace.
The hold never grants fault-action authority or changes the minimum progress
criterion. Completion is bound to the session, source contract and completed
driver-journal hash; abort, foreign completion and timeout remain failures.
Ready/released progress receipts are included in diagnostic retention.
All 269 targeted tests passed after implementation, covering normal release,
abort, mismatched completion identity and timeout.

Fourth-run outcome (`03272abc5f78`): the peer committed step 5 and retained
`peer-progress-ready.json`, but the driver still timed out on `peer_after`.
The peer exited only on `FaultSessionAborted: host_gate_failed`; its hold did
not expire. Target and peer ended at steps 3 and 5 respectively, with both
manager and supervisor terminal evidence retained, but zero acceptance-ledger
completions. The VM lifecycle completed with independent residue-free
verification. Its packet manifest is
`e226df88991f689909980f424fd21412487933f457b38bd4aee0b5a9c2a9828f`.

As of 2026-09-05T03:41Z, four attempts reserve USD 32 tonight, not measured
billed spend. Two further USD 8 attempts fit the USD 50 limit, but neither has
been launched. No VM remains active. The existing hard expiry remains
2026-09-05T12:00:00Z. Unused budget does not establish acceptance or require
another speculative retry.

Next diagnostic requirement: preserve the peer probe's observed status,
step, process-presence result and sample timing on timeout. The current
post-gate snapshot cannot establish which predicate failed during polling,
or whether step 5 was reached before the polling window ended. The earlier
statement that the peer was already held throughout that window is not
proved by the retained receipt alone. Do not relax the live-health or
minimum-step criteria to make this pass.

September 5 local continuation: implemented bounded peer-health diagnostics
in the concrete probe, with total sample count and independent copies of its
first and last samples. Each sample records run ID, registry status and step,
harness PID and process-presence result, and host monotonic time. The host
driver includes these diagnostics in a peer-after timeout exception so the
existing retained exception chain exports them. Diagnostics never count as
acceptance evidence or alter the healthy-peer predicates. The host source
pin in the launcher was updated to match the changed integration.

Five new provider-free regressions cover insufficient step, terminal status,
missing harness, the unchanged healthy success case, bounded sample storage,
copy isolation, and timeout propagation. All 228 fault-driver, fault-session,
diagnostic-retention and host-runner tests passed; Ruff and launcher Bash
syntax checks passed. No additional packet, VM, reservation, deployment or
paid model call was made. The live root cause and two-fort acceptance remain
unproved. Existing authority expires at 2026-09-05T12:00:00Z; local work can
continue after expiry, but the unused allowance is not an indefinite renewal.

Instrumented packet follow-up: two independent builds produced identical
manifest `df0306ccf1cf549296ac1502268354f4a3d871d0b54339a189008ac0f4d8da9f`,
retained as `fort-gym-m1b-diagnostic-20260904-r4/packet-health-probe`.
Launch ID `32ea52570094` was refused at 2026-09-05T11:45:17Z by the unchanged
900-second expiry safety margin. The lifecycle receipt explicitly records
zero GCP CLI calls, no create attempt, no reservation and exit code 77.
This is not a fifth VM run. The shared continuation ledger still has three
entries; total tonight reservations remain USD 32 including the first ledger.
No expiry, safety margin or spending rule was relaxed. The retained tar
contains no original peer-progress receipt timestamps, so it cannot resolve
whether step 5 preceded the failed polling window. A new valid infrastructure
window is needed for the prepared instrumented real-DF diagnostic; local
investigation and regression work remain possible without cloud authority.

Additional provider-free narrowing: a new regression uses a real child
process, a real WAL-mode SQLite writer and the probe's actual read-only
connections. It rejects an uncommitted step-5 update, accepts the committed
step while the child is alive, and rejects the same running registry row
after that child is reaped. On macOS only the `/proc/<pid>` existence seam is
translated to `os.kill(pid, 0)`; runtime lifecycle reads remain real fixture
files. This checks committed-read visibility and stale-row rejection, not
Linux `/proc` permissions, real DF timing or the complete supervisor path.
It does not establish the cause of the previous live failure. All 229
targeted tests passed after this test-only addition. The prepared packet's
runtime source is unchanged; the new regression is not in that frozen packet.

## September 4 diagnostic outcome

Run `ef30ebef765f` used exactly one disposable VM and one USD 8 reservation.
The final packet manifest is
`e7e9d8e50e85cdc43e1b6cb6ec6a66b2348c8046bd483cc9dd643b2264565b82`.
Two independent builds had identical manifests; only two packet versions are
retained in the new run root. The full fake-cloud lifecycle suite passed 78
tests before the final date-label adjustment; six focused lifecycle checks
passed afterward. Core/preflight checks passed 201 tests and the additional
fault-driver/diagnostic/local-process checks passed 118 tests.

Both real DF forts reached the durable step-2 barrier. The action-receipt poll
then raised `FaultSessionEvidenceError: fault driver journal file is invalid`.
The journal writer creates its file before obtaining its first append lock;
the poll rejected the legitimate empty initial file as corruption. Unwind
aborted both workers before fault injection. This run therefore does NOT
prove fault isolation: DF-KILL failed and zero of two attempts committed
acceptance-ledger completion. Full M1b remains `INCOMPLETE_NO_GO`.

The new diagnostic retention worked: both run snapshots were captured
byte-exactly, including manager and supervisor terminal records, registry
step/status, and target fault-driver observations. Terminal files exist even
though acceptance-ledger completion failed; these are distinct proof layers.
The exception includes its exact call chain and `wait_for_fault_action` stage.
The sealed evidence was exported and independently broker-validated before
teardown. The lifecycle receipt records successful VM deletion and independent
instance, disk, and address absence checks. Provider calls were zero. The USD 8
is a retained worst-case reservation, not an assertion about invoiced cost.

A regression reproduced the empty-file failure locally. The local fix permits
an empty journal only during action polling, returning pending without release
authority; completed evidence, malformed prefixes, and failed journals remain
strict. This follow-up fix is NOT in the executed packet and has no real-DF
acceptance claim. No second VM will be launched under the consumed renewal.
After the local fix, 249 targeted fault-session, driver, diagnostics, host and
controller tests passed. Ruff's remaining findings in the touched test file
are two pre-existing E731 lambda assignments outside this change.

Follow-up concurrency proof: a test now pauses the actual observation-journal
writer after file creation but before its first append lock. The session
reader sees the zero-byte file and returns pending, without release authority.
After resuming the writer through the six canonical phases, the same reader
returns the exact action-record digest. The test uses real file locking and
journal serialization; only scheduling is controlled. This is local race
coverage, not a substitute for a fresh real-DF fault-isolation run.
The expanded targeted suites passed 250 tests; Ruff passed with only the
pre-existing E731 test-style exemption, and `git diff --check` passed.

Evidence root:
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1b-diagnostic-20260904/evidence-ef30ebef765f`.

Renewal checkpoint: the user approved the requested single-VM authorization.
It is recorded at 2026-09-05T02:21:57Z, for September 4 America/New_York,
one USD 8 reservation under the existing USD 250 cap, only the two-fort
diagnostic, mandatory teardown, and a conservatively imposed hard expiry of
September 5 at 12:00 UTC. No second VM or full-matrix execution is authorized.
Independent read-only GCE instance, disk and address queries for the Fort Gym
M1b prefix returned empty before packet construction. The new run root is
`/Users/cdossman/Documents/Open Source Projects/fort-gym-m1b-diagnostic-20260904`.
Historical checkpoints below describe their original authority state.

## Goal

Two real DF forts run independently. An injected failure in one leaves the
other healthy. Both produce complete, independently inspectable run, failure,
and terminal evidence. Mandatory teardown leaves no residue.

This is a smaller diagnostic checkpoint toward M1b, not a replacement for its
frozen sixteen-gate acceptance contract. A two-fort success does not grant M1b
GO, establish a model-capability result, or authorize E1.

## Current implementation checkpoint

- Gate exceptions retain bounded, credential-redacted messages, cause chains,
  stack locations, and execution stages. Traceback locals and source lines are
  not exported. Existing gate-specific failure receipts are not overwritten.
- Named files from exact run control/artifact directories are embedded in
  diagnostic snapshots under the batch evidence root. These include manager
  and supervisor journals/terminals, worker logs, selected runtime receipts,
  fault-driver observations, and exact fault-session participant receipts.
  Worker-future exceptions and registry status/step are retained separately.
- Snapshots are returned as ordinary gate/cleanup evidence references, so the
  existing controller hashes them into its manifest and seal and the existing
  cloud archive collector includes their actual contents. Export occurs at
  gate return and again at final batch cleanup. No recursive source-directory,
  raw database, environment, or save-tree copy was added.
- Reads refuse symlinks, linked ancestors, hardlinks and non-regular files.
  Per-file/per-run byte bounds, read changes, redaction, truncation and missing
  files are explicit. `capture_ok` means the existing selected files were read
  exactly, not that missing files existed or that the run passed. Terminal
  presence is recorded separately. Incomplete capture cannot promote a gate.
- A regression reproduced the manager's pre-binding startup window: the
  manager publishes an active unbound owner before constructing its contract,
  but the evidence reader rejected this legitimate intermediate state. The
  reader now returns pending only for an otherwise valid active owner with all
  identity fields unset and no durable attempt/container/terminal evidence.
  Contradictory or post-start unbound identities still fail closed.

This is a demonstrated local startup defect, NOT a retrospective diagnosis of
the August 29 cloud failures. The missing original diagnostics prevent that
causal attribution.

## Local evidence and checks

`tests/test_m1b_local_process_integration.py` now starts two actual Fort Gym CLI
worker processes using the mock backend, pauses both after child creation,
kills the target, verifies the peer remains alive, resumes it to successful
completion, and checks both parent/supervisor terminal and cleanup records.
It exports snapshots to an archive, removes only the test-owned temporary
runtime trees, and reads both records back from the archive. This is process
and export evidence, not a real-DF or Linux fault-isolation pass.

`tests/test_live_acceptance.py` verifies that a failed gate's diagnostic bytes
are included in the real controller seal, remain valid after source teardown,
and invalidate verification if the retained snapshot is modified.

Focused suites also cover loader identity contradictions, diagnostic redaction
and filesystem boundaries, worker exception retention, partial-export errors,
local eight-worker integration, and existing cleanup/authority accounting.
The live runner source pin was updated; authority dates, spending bounds,
frozen gates, thresholds, and acceptance/plan digests were not changed.

Verification at this checkpoint: 362 supervisor/loader/controller/diagnostic
and local-process tests passed; 34 source/packet tests passed (10 heavyweight
retained-input checks deliberately not selected); four focused lifecycle
tests passed. Total: 400 distinct targeted tests. Ruff passed on the touched
Python surfaces with the host runner's existing post-bootstrap import pattern
exempted (`E402`); `git diff --check` and Bash syntax validation passed.

## Remaining work

Follow-up implementation: the host runner now accepts the literal
`--two-fort-diagnostic` switch. Its adapter runs only the existing DF-KILL
target/peer procedure. It retains the full frozen gate order, records every
unselected live gate as `diagnostic_not_selected`, and retains all cleanup
passes. The controller integration test proves exactly two runtime attempts,
no non-runtime contender, thirty-two cleanup passes, sealed selection
receipts, and overall `INCOMPLETE_NO_GO` even when the selected case passes.
The cloud lifecycle launcher now forwards this switch and rejects a focused
outcome that claims full GO, starts more than two runtime attempts, or starts
any non-runtime attempt. Duplicate switches fail before cloud activity;
expired authorization remains rejected in both modes. The launcher still
performs teardown after refusing an out-of-scope outcome.

The focused controller test also replays its actual attempt and batch ledgers
through the independent root broker, then validates its final documents,
manifest artifacts, and decision binding without bypassing those checks.
This is provider-free fixture evidence, not root-service execution or real-DF
acceptance. Five focused launcher lifecycle checks passed, including the
default mode and expired-authority paths.

Source-packet preflight: all 44 existing packet/input tests passed against the
retained inputs, including the OCI archive and hook layer, seed, generated
protocol identities, offline wheelhouse, and signed Docker runtime. A new
source-only assembly test confirms all selected source files pass the real
copy and integrity checks, including diagnostic retention, the startup-reader
fix, and both focused-mode entry points. It does not create a launch packet.
A separate regression checks that exact authority expiry refuses packet
creation before reading runtime inputs or creating any output.

The real packet builder enforces the expired dated authorization itself.
No clock override or authority change was applied to a real build. The retained
August 29 run root also already contains its two allowed packets; those
historical files remain untouched. A new packet requires valid dated authority
and a project-owned output location within the retention rules.

1. Prepare and verify the focused two-fort Linux diagnostic execution path
   using the same ownership, provider exclusion, spend and teardown controls.
   Preserve its diagnostic status separately from full M1b acceptance.
2. Build/check a new exact source packet. Do not reuse the August 29 packet as
   if it contained these changes.
3. Under valid infrastructure authorization, prove independent real-DF
   progress, target failure classification, unaffected peer progress, complete
   exported terminal evidence, and zero residue.
4. Only then rerun the unchanged full M1b matrix before considering M2/E1.

The August 29 one-VM authorization expired August 30 at 12:00 UTC. This local
checkpoint neither renews that authority nor launches any cloud resource.
No paid model call, production change, deployment, push, or publication was
performed. The goal remains open until the real two-fort proof exists.

This document is the durable decision/checkpoint record. Test scratch and
archives are reproducible and remain in pytest-owned temporary directories;
the historical acceptance artifacts are not modified.
