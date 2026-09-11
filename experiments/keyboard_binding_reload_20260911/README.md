# Astra displayed-key checkpoint-32 reload

Provider-free acceptance for the unchanged `8b9fffa1d` implementation. Load a
fresh copy of `bindings-20260911-astra-r1` checkpoint 32 and restore the ordinary
campaign loop with its exact agent configuration, prompt origin, memory, latest
usage journal, history and trace. This is not a new independent model attempt.

The executable candidate is `fixture-v2.py`. The initial `fixture.py` is retained:
its preparation test assumed that a fresh runner explicitly stores an empty
`discontinuities` list. The actual fresh checkpoint omits that optional field.
Version 2 uses the same empty-list default as the production resume implementation.
The first preparation run was 9 passed / 1 failed, with no VM or native execution.
No checkpoint or production source was changed to accommodate the test.

Predeclared acceptance:

- The source checkpoint verifies before and after, including every native save file.
- Native loading yields year 30, tick 32,301, paused, with a 120 by 40 screen.
- The native metrics match the original saved boundary: seven citizens, zero
  recorded dead, two completed workshops, one farm, zero completed placed beds,
  50 raw-edible food units and 60 drinks.
- `CampaignLoop.resume` restores decision 32, 15,500 committed elapsed ticks,
  32 accounted responses and 785,690 returned tokens without changing memory,
  configuration, prompt origin, usage, history, last result or discontinuities.
- Displayed-key binding-file verification succeeds; empty input probes send zero
  keys. No model invocation, gameplay action, time advance or native save is allowed.
- Native processes/listener, container and the single local VM are stopped and
  independently audited. The existing CPU2/VM3GiB/disk32GiB limits are unchanged.

Record loaded native menu focus separately from the original build-menu focus.
The save protocol preserves the menu around saving, not necessarily across a
new game process. No menu restoration, selected action, strategy hint or manual
gameplay correction is inserted. Menu equivalence is not an acceptance criterion
and must not be claimed without evidence.

The retained integrated image is reused without a build or network. The original
trial volume is read-only; only a new diagnostic volume and runtime copy are
written. Local owner/evidence live in
`fort_gym/artifacts/native-local-20260906/runtime-v2/keyboard-matched-pilot-v1/keyboard-bindings-astra-r1-reload-v1`.
An executed fixture is immutable; a necessary repair requires another version.
This diagnostic does not prove additional autonomous play or sustainability.

The native run passed. The original independent `review.py` then rejected whole
copied-save byte equality: `events-dfhack.log` gained 304 bytes containing exactly
the WORLD_LOADED and MAP_LOADED lines. All 126 non-log files and the original
127-file checkpoint are unchanged. `review-v2.py` is an explicitly post-hoc,
scoped review of that same run, not a rerun or a relabeling of the strict failure.
Its log classifier requires the original prefix and exactly those two load
events, rejects every other file difference, and records the unequal copied tree.
