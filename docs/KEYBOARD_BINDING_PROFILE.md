# Displayed-key campaign profile

`native_keyboard_bindings/v1` is a separate selectable campaign input condition.
It is not a reinterpretation of `native_keyboard/v1` or `native_keyboard/v2`.
The direct DFHack helper condition is also unchanged. The new condition schema
is `fortgym.codex-keyboard-condition/v4`; it selects the binding instruction
profile and pins the game's `interface.txt` SHA256. Ordinary checkpoint resume
requires exact configuration equality, including that binding identity.

## Controls

The response shape remains KEYSTROKE with a keys list. Each string is one
displayed character, preserving case, or `SYM:modifier_mask:symbol_name`.
For example, `{"keys":["b"]}` presses b and `{"keys":["SYM:0:Enter"]}` presses
Enter. Modifier bits are Shift=1, Ctrl=2, Alt=4; Ctrl+n is `SYM:2:n`.
Text is separate character presses, not a multi-character key string.

The pinned catalog includes all 223 KEY labels and 182 SYM combinations in the
tested file. It lists key labels only, not workshop or strategy aliases. The
runtime parser resolves each selected label to every matching native event and
submits that complete set in one `gui.simulateInput` call. Separate strings in a
batch are separate presses, with UI cadence between them. No context-sensitive
job choice, repair, fallback, direct order insertion or held-key repeat occurs.
Mouse bindings and general Unicode text translation are not claimed; legacy
extended KEY labels retain the source file's byte-code-like character semantics.

The constructor validates the binding file before model work. The executor
validates all selected keys and their mappings before any input, checks the
file before/after each call, records exact event sets and runtime/calendar
receipts, and never replays an uncertain input. Game time remains a separate
model-requested operation. Acknowledged input is not a completed job.

The pinned file is not an attestation of live rebinding in memory. Changing
in-game key bindings changes the experimental condition and requires a new
declared profile. Physical-device/SDL equivalence has not been established.

## Evidence and next native checks

The [five-arm native diagnostic](https://github.com/lemoz/fort-gym/blob/5d00734edf82606adc7da3d61888c6b891f73d34/experiments/evidence/keyboard_binding_native_diagnostic_20260911.json)
established that b's 41-event set queues ConstructBed, v's 28-event set queues
MakeBarrel, and Enter's eight-event set matches SELECT (MakeShield in that menu).
Original CUSTOM_B queued nothing. Operator-selected copies, no game ticks or
model calls, were used; all game processes and the local VM were shut down.
The complete earlier diagnostic and its failed whole-frame comparison are
preserved. This implementation adds the normal agent/exchange/checkpoint route;
the prototype result alone does not validate that new integration.

Before a model trial, run the integrated environment on a fresh disposable copy:
use displayed keys to enter/leave menus, move the selected cursor, open the
workshop AddJob menu and queue an order, and enter/edit/cancel a workshop name.
Capture actual screens and native state before and after each step. Require no
game-time advancement, no changes to the source save, exact file identity and
complete process/VM teardown. Operator positioning may establish a diagnostic
start, but no positioned copy is eligible as a scored campaign origin.

The prepared `keyboard_bindings_20260911/astra-condition.json` and `astra-trial.json`
declare an independent 32-response trial from the same original snapshot as
the matched pilot. They preserve Astra Medium, screen size, simulation bounds,
memory-replacement semantics, subscription transport and the no-fallback rules.
Only the input profile, its explanatory prompt, schema and condition identity
change. Do not merge these results into the historical matched cohort. Follow
with repeats and other models before making comparative claims.

The instruction update follows [OpenAI's prompt-structure guidance](https://developers.openai.com/api/docs/guides/prompt-engineering#message-formatting-with-markdown-and-xml):
state the control contract clearly and keep the screen/memory as context. It
does not prescribe a build order or change the selected model or its effort.
The [version-matched DFHack API](https://docs.dfhack.org/en/0.47.05-r8/docs/dev/Lua%20API.html#misc)
documents complete-set input. Neither documentation nor synthetic tests are
native gameplay acceptance.
