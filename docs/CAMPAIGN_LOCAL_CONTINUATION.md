# Local year-two continuation

September 7, 2026 UTC. Status: **running from the verified cursor-32 checkpoint**.

The first owner has now completed and its final checkpoint and resource teardown
have been independently audited. Its native cursor is 32, with 76,000 elapsed
ticks and 325,234 accounted tokens. The final checkpoint manifest digest is
`9107218b7c5fea3638e329e631a9e9b1d763457cb7f80092fe3a4679c67824e3`.
The selected operator's read-only prior-owner gate passes; 19 offline tests pass
again. This supersedes the preparation-time missing-receipt observation below.
See [the terminal result](LOCAL_REASONING_SEGMENT1_RESULT.md). The selected
remaining-segments owner started its container at
`2026-09-07T03:46:04.734379218Z`. The segment-two public boundary retains
32 commands, 76,000 elapsed ticks and 325,234 tokens; the new trace starts with
the exact final-checkpoint trace bytes. No new action had committed at that
observation. The original owner handle is live and will be followed without
restart. The older preparation-time observations below are historical.

## Selected continuation: remaining declared segments

The selected local owner now invokes the existing controller once with
`--resume --segments 7`, covering the remaining seven segments of the original
eight-segment envelope. The prior one-segment preparation below is retained
unchanged and is not selected. Do not execute both preparations.

This removes a manual owner launch between every subsequent segment. The frozen
controller already validates each native load, cleanup, checkpoint, cumulative
usage and remaining cap before starting the next segment. It stops at an
output-limit pause or any non-ready state. One game runs at a time; model server,
loopback tunnel, container and isolated local VM remain owned by this invocation
and are torn down when it ends. No model parameters, prompts, conditions,
campaign identity, evidence volume or cumulative budgets change.

The selected operator SHA-256 is
`f0f6676524531227c58e1dfdd94566d2e44d0fb80ce924d180b8d10b283c7218`;
its local test source SHA-256 is
`871b2e7de706ded199209d0c09ff73e0c50d3e37e5ebc1c95239e47862a108c5`.
The container owner name ends in `-remaining`. The attached controller command
has a 7 x 7,500-second bound and the outer owner an additional 1,500 seconds.
The configured 7,200-second per-segment gameplay bound remains unchanged.

Nineteen offline owner tests pass. A new synthetic controller regression runs
one segment followed by all seven remaining segments, retaining all 256 commands
and cumulative usage across eight verified checkpoints and seven continuations.
It confirms
sequential ports and refuses another invocation after the eight-segment cap.
All 80 focused controller/continuation/checkpoint/retention tests pass. Synthetic
fixtures use their own declared save and do not claim the real native seed.
The tested controller source is unchanged from the frozen `de69c7a46` controller.
The actual read-only gate still reports no terminal first-owner receipt, and no
new attempt, model or VM has launched. Audit the first owner's final evidence
and teardown before selecting this continuation for execution.

## Prior one-segment preparation, retained but not selected

The native reasoning-budget campaign is still running its first segment at
`de69c7a467eb0b00becfef03329bac9f58690e35`. Its local first-owner wrapper starts
only a fresh campaign. A separate segment-two wrapper now preserves the exact
running experiment and can continue it after a clean invocation-limited pause.
It does not change or restart the current owner.

## Unchanged execution contract

- Campaign: `fort-gym-year-two-qwen35-reasoning-budget-v1-a`.
- Condition: `local-native-qwen35-year-two-reasoning-budget-v1`, canonical SHA-256
  `13ec2fdaad2b5e63b6f1e8fc4d57feefd3f66cd307104267d7bc06743cdbb490`.
- Image: `sha256:ce56592ad8f8d82e7dcaa7f9d71a28a900669d523f3119278a865129214c85a3`.
- The same evidence volume is mounted at `/evidence`. The controller output
  remains `/evidence/campaign`; its checkpoint, usage and segment history are
  retained rather than copied into a new campaign identity.
- Model arguments, weights, sampling, prompt settings and budgets are identical.
  The controller retains `--port 5503`; it selects port 5504 for segment two.
  Changing the controller's first port would change its continuation identity.
- `--segments 1` bounds the new invocation. It does not reset the eight-segment,
  eight-million-token or 512-dispatch cumulative campaign limits.

The container owner changes to
`fort-gym-year-two-qwen35-reasoning-budget-v1-a-segment-02`. The game-command
argument list is otherwise identical except that initial `--snapshot` and
`--snapshot-sha256` options are replaced by `--resume`. No new image is built,
no action or strategy is injected, and no seed reset is performed.

## Before execution

The existing owner must become terminal. Audit its container/native cleanup,
model and tunnel PIDs, closed listener, stopped VM, copied evidence and final
checkpoint. The new wrapper then rechecks these receipts and current resource
state, the frozen source and condition, the exact previous model arguments,
checkpoint/save/usage hashes, periodic saves, and remaining cumulative budgets.
The existing controller independently rechecks the retained volume at launch.

Only `invocation_limited_pause` following `bounded_segment_complete` is selected
for this prepared continuation. An inference output limit, reconciliation state,
missing final checkpoint or exhausted cap is retained for diagnosis rather than
automatically replayed. A periodic checkpoint alone does not authorize a rewind.

The wrapper owns independent cleanup of its container, model, loopback tunnel
and isolated local VM, and copies evidence before VM shutdown. It introduces no
cloud VM, hosted fallback, production deployment or new spend reservation. Local
model API charges are zero; hardware, energy and application costs are unknown.

## Preparation evidence and limits

The frozen first operator has SHA-256
`8266f19bb3b67a92280e569411193a39c063836f0aeb4ed1f0e7a5ee524b20c1`.
The prepared continuation operator has SHA-256
`301d2cc714c69e8a11a432d2dab30c5176f6a606e2bfd91ce429e8f30fb3908d`.
Its local test source has SHA-256
`11ad4bfc35f58cfeceee7a398c3e2dec2b6f7ee891160012256c77bd80361844`.
Machine-specific operator paths and retained game/model files remain private.
The published gameplay implementation remains the frozen controller and runtime.

Nineteen offline owner tests passed: exact container-command equivalence except
for the declared owner/resume changes, identical model arguments, successful
read-only receipt handling, and missing/changed/unclean-owner rejection. Syntax,
Black and Ruff checks passed. Seventy-nine controller, continuation, checkpoint
and retention tests also passed on the unchanged native worktree.

A read-only probe of the actual previous-owner gate reported not ready because
the original terminal receipt was absent. No new attempt directory, model,
container or VM was created. This is a prepared operator, not native resume
acceptance, additional autonomous ticks, or year-two success.
