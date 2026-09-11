# Displayed-key binding experiment

Hypothesis: projecting a declared key through the game's own `interface.txt`
and submitting all of its native events in one input call lets an agent use
the displayed hotkey. The current menu, not our translator, chooses the effect.

This is an experimental transport fixture, not yet a new campaign control
profile. The historical profiles, trials and checkpoints remain unchanged.
The parser contains no workshop, job or menu-dependent dispatch logic.

## Predeclared native check

Use five fresh, paused copies of Astra attempt 1's decision-256 checkpoint,
each with the same operator-selected carpenter AddJob menu:

| Arm | Submitted input | Required native outcome |
| --- | --- | --- |
| custom_b | Original CUSTOM_B executor | No new job |
| binding_b | All bindings for character b, one call | One ConstructBed job |
| binding_v | All bindings for character v, one call | One MakeBarrel job |
| native_select | Original SELECT executor | One selected-menu job |
| binding_enter | All bindings for unmodified Enter, one call | Same job and focus as SELECT |

Before comparison requires equal native calendar, selected workshop, focus and
queue, plus every glyph and color in the workshop sidebar (x64..93, y1..38).
Full captures are retained, but map animation outside this predeclared region
is not a whole-frame equality requirement. This does not rewrite the previous
diagnostic's failed whole-frame criterion.

All existing jobs must remain unchanged. Every arm must retain pause at
year30 tick152201, preserve the original checkpoint, and close its native
process and RPC listener. One existing bounded local VM, five sequential games
on distinct local ports 5593..5597, no provider calls or internet in the game
container, no game-time advance or native save, mandatory VM shutdown.
Operator-positioned copies are not eligible for scored campaign continuation.

The exact binding-file SHA256 is
`8176d2bd7a8d96f6bb12feb654519a8361a6f262363b84ec48963be832cb7efd`.
The parser validates all declared events against the version-matched native
catalog and checks the runtime file before and after dispatch. The proprietary
game file is retained only in local evidence, not copied into this repository.

## Limits and implementation

KEY character and SYM modifier records are separate input types; character
case is preserved, bindings deduplicated, and unknown records fail explicitly.
Legacy C1 characters in this file are parsed literally, not claimed to be a
Unicode-to-physical-key translation. Mouse bindings are recognized but are not
dispatched. Repeat policies are recorded, not simulated as held-key repeats.

The [version-matched DFHack API](https://docs.dfhack.org/en/0.47.05-r8/docs/dev/Lua%20API.html#misc)
supports passing a set to `gui.simulateInput`. `event_set.lua` does that once,
validates all events before sending, records both boundaries and restores pause
inside the same suspension lock even if the input function throws.

A pinned file is not proof of the game's live in-memory map after rebinding.
Success in these menus would not prove SDL/physical-device equivalence, text
entry, all navigation, job completion, autonomous improvement or sustainability.
Those are subsequent integration and gameplay checks, not inferred results.
Local hardware, energy and app cost remains unmeasured, not zero.
