# Recorded continuation checkpoint chains

The campaign page can preserve all saved checkpoints inside an audited window,
rather than showing only its final save. It distinguishes a reload for the next
segment from a standalone reload test. Only the final checkpoint carries the
window's VM-shutdown evidence.

When a later audited window loads a previous endpoint, its reload note and
evidence link update together. Existing standalone reload records and historical
shutdown warnings are preserved.

The API validates each checkpoint against the original condition, starting save,
parent hash, action rows, cumulative usage, native calendar and saved metrics.
A paused segment with zero new decisions keeps its own checkpoint identity,
including when its decision count equals the previous save's count.

This is preparatory website capability. No synthetic fixture or unfinished
native result is registered. The current recorded campaign still contains
96 decisions and the original checkpoints at 32, 64 and 96. Its serialized
response remains byte-identical to the previous website version.

The existing FastAPI architecture, dependencies, historical endpoints and
local-preview source are preserved. No new site registration, credentials,
public deployment, browser QA or native game inputs are part of this change.
