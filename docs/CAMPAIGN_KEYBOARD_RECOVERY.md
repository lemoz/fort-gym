# Native keyboard failures and continuation

Standard-input campaigns retain the model's exact response. Unsupported key
names in an otherwise complete response are rejected as a whole: no valid subset,
spelling correction, substitute action, gameplay key or clock command is executed.
The model receives factual rejection feedback and chooses its next response.
The attempted memory update is not applied; fully returned usage is still counted.

Unknown delivery, incomplete usage, malformed response shape, changed native
calendar or uncertain execution remain failures. The rejection path must not
turn a transport failure into a gameplay result.

## Historical interrupted runs

The Python entry points in `fort_gym.bench.run.keyboard_recovery` inspect retained
source evidence and reconcile a separately loaded forensic save forward. They
do not launch a model, replay input, advance gameplay, create a VM or delete files.
Callers own runtime isolation, capacity checks, save loading and teardown.

Two narrowly attested cases are supported:

- A fully delivered keyboard action followed by the original zero-tick build-menu
  clock timeout. The original timeout remains failed; the delivered action is
  never repeated.
- A fully received unsupported-key response that the historical runner treated
  as a fatal decision error. The source must establish complete subscription
  usage, unchanged model memory, no native dispatch and an unchanged paused
  native calendar.

Both cases require the latest parent checkpoint, all committed tail actions,
the original exchange, native save inventory and unchanged evidence byte prefixes.
Recovery creates a new explicitly marked trace row and checkpoint, retaining the
old failure as a failure. A forensic save alone is not a resumable checkpoint.

The second case appends `keyboard_rejection_reconciled/v1` to the original usage
journal. This record binds the original journal hash, response/request, failure
and paused native boundary. It does not edit the historical
`decision_returned: false` entry. Later checkpoint validation verifies the
reconciliation and retains the exact response counters and returned tokens.

## Current evidence boundary

The previously recovered cursor 101 is recorded separately from the newer
interruption at 183 committed decisions / 184 responses. Its latest parent is
181, not permission to discard the two newer actions or rejected response.
The new recovery target is cursor 184 with 44,000 elapsed native ticks and
5,933,954 campaign tokens. Native validation and independent recovery audit now
pass at `c537e3e79`, with exact-source CI passing. The new checkpoint is
`073ac57c4b80227368d5bd6b6367ba4e214fc629dbbaf604c498b24b7a80e642`.
Recovery added no model calls, native keys or ticks, and teardown was verified.
The original journal is retained with one additional reconciliation record.
The separate synthetic-receipt native check passed without campaign calls or
gameplay input; its synthetic usage is excluded. A preceding package-permission
failure stopped before game load and remains retained, not overwritten.
None of these infrastructure results establishes year-two fortress viability.

Focused recovery, rejection, checkpoint, control and loop tests pass (193 tests).
They cover unchanged historical sources, zero native/model dispatch, retained
usage and memory, resumed feedback, and rejected mismatched evidence.
The broader source suite passed 2,435 tests, with ten skips and one locally
excluded socket test that passed separately earlier. Full exact-source CI:
https://github.com/lemoz/fort-gym/actions/runs/34167561354
