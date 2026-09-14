# Read-only rejected-control observer

This worktree is a new observer candidate based on `2778519991899ee3360db1caf6daec29721bbc4a`.
The original pinned observer and live relay remain unchanged until the candidate
is tested and selected for a future relay. Never use this checkout as a native
gameplay source or as a change to the frozen matched comparison protocol.

The original observer predates displayed-key controls. This change backports the
exact `keyboard_rejection.py`, `native_key_catalog.py` and `display_key_catalog.py`
files from the active native source `d22f28d99f4fd103188979e964e148139d3f3efd`.
It passes each request's explicit control profile to the native typed-receipt
parser. Existing native event-name rejections remain supported.

No replacement keys are invented or sent. A rejected response remains rejected,
with its attempted keys and stated intent visible and its private memory omitted.
No game, provider, reset or VM operation is performed by this reader. Publishing
a frame does not prove native execution. The website's recorded-trial exporter
must independently bind the recovered action to the audited native trace.

Validation: 48 focused tests passed, including native-event and displayed-key
rejections, wrong profile/screen/dispatch negatives, and live snapshot projection.
The candidate matched all 64 original Terra r2 actions against its immutable
trace and projected all nine real rejected frames with their original keys and
rejected status. All three backported files match the frozen native source byte
for byte. Selected Ruff and mypy passed. These checks made no game or model calls;
they do not claim the candidate has yet been selected by a live relay.
