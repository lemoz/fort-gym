"""Explicit job-entry shorthand, independent of screen observation encoding."""

CONTROL_PROFILE = "native_keyboard_selected_workshop_jobs/v1"
PROMPT_PROFILE = "native_keyboard_selected_workshop_jobs_prompt/v1"
ACTION_TYPE = "WORKSHOP_JOB"
ITEMS = ("bed", "door", "table", "chair", "barrel", "bin", "brew")
MAX_QUANTITY = 5
RECEIPT_SCHEMA = "fortgym.selected-workshop-job/v1"

INSTRUCTIONS = """Your controls are displayed keyboard keys through the pinned game bindings.
You may use all the same game menus and keys, plus one explicit WORKSHOP_JOB
shortcut. Navigate with keys to select a completed workshop in the native q
building-query menu first. Then send WORKSHOP_JOB with params {"item":"bed",
"quantity":1}, choosing bed, door, table, chair, barrel, bin, or brew, and a
quantity from 1 to 5. Furniture, barrels and bins require the selected carpenter's
workshop; brew means brewing plants at the selected still. The entire batch must
fit the workshop's ten-job queue. No workshop is found or selected for you.

Use KEYSTROKE with params {"keys":[...]} for normal input, including every other
task. One response chooses one route, never both. Both routes use the same
advance_ticks, intent and memory_update fields. Empty keys request only time.
The shortcut queues normal jobs, not completed products. It supplies no materials,
workers or skills, and does not change labor settings, terrain or other buildings.
The game still needs inputs, labor and time. You may continue to queue these jobs
through the native menus instead. Inspect subsequent screens to verify effects.
No other DFHack build/order shortcuts are available in this condition."""
