# DFHack screen checkpoint support

The opt-in `native_menu_preserving_save/v4` profile preserves identified DFHack
screens as well as native game screens. Older profiles retain their original
meaning and existing experiment configurations are unchanged.

Window o failed before requesting a save because a stack entry did not match a
native `viewscreen_*st` type. The exact-version runtime enables the DFHack status
overlay, which can sit beneath the native pets menu. A provider-free diagnostic
on a copy of checkpoint 631 is used to reproduce and verify this path. Native
acceptance is pending; unit tests alone are not save/reload evidence.

V4 retains the same paused save operation and native screen objects. Each stack
entry additionally records its focus, native/DFHack classification and dismissed
state. A base `viewscreen` is eligible only with a nonempty `dfhack/` focus. It
does not accept unknown base screens or dismissed screens. Separate RPC probes
must match the entire original stack, addresses and focus, before and after the
save. The world, calendar, pause state, top-level UI selections and screen size
must remain unchanged. A failed operation is not retried.

This is runner-owned snapshot maintenance, not a model action. It sends no
gameplay keys and adds no orders, resources, labor changes or strategy advice.
Any diagnostic copy is not a new campaign checkpoint and cannot recover window
o's unsaved 21,200 ticks. Resuming checkpoint 631 still needs an explicit recorded
discontinuity preserving all 711 model responses and usage.

Version-matched primary references:

- [DFHack 0.47.05-r8 Lua API](https://docs.dfhack.org/en/0.47.05-r8/docs/dev/Lua%20API.html): screen focus, dismissal and `hideGuard` screen preservation.
- [DFHack 0.47.05-r8 Lua bindings](https://github.com/DFHack/dfhack/blob/0.47.05-r8/library/LuaApi.cpp): `screen_hideGuard` accepts both Lua screen objects and native viewscreen pointers through the screen pointer adapter.
