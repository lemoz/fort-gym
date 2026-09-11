# Checkpoint 416 fresh-load acceptance

This is a provider-free verification of the completed Astra displayed-key
campaign, not another model trial and not additional autonomous gameplay.

The source is the immutable decision-416 checkpoint:
`73f90e9bb9097fe00ed056723c0cc8de36bb0b85b4c0e40878af86d071c7704a`.
Its checkpoint-file SHA256 is
`9de235fa8e7ab30684c2b82424967b5b505b7951f048118f6915d64c2a513ec9`.
Reuse native source `d22f28d99f4fd103188979e964e148139d3f3efd` and the exact
retained image `sha256:32bd022138a4772ed0c0d3a14f94feab8ad4a4cd183a20a8cd098745aedbd10d`.

## Predeclared checks

- Load a disposable copy at native year 31, tick 43,446, paused, with a 120 by 40 screen.
- Restore cursor 416 and 429,845 committed elapsed ticks through ordinary
  `CampaignLoop.resume`, without invoking its decision function.
- Preserve exact saved model configuration, prompt origin, memory, trace,
  usage journal, history, last result and the inherited save-loss record.
  All 448 accounted responses and 11,866,456 returned tokens remain counted.
- Verify 13 living citizens, zero recorded deaths, 12 beds, three workshops,
  one farm, 43 raw-edible food units and 389 drinks. Unknown room, wood and
  stone metrics remain unknown rather than guessed.
- Verify the original native save before and after. All copied non-log save
  files must remain byte-identical. The copied `events-dfhack.log` may append
  exactly the two known WORLD_LOADED and MAP_LOADED entries, with its original
  prefix intact; no other file or log changes are allowed.
- Verify the displayed-key binding digest and two empty-input probes. No model
  call, gameplay key, game-time advance, save request or manual menu restoration
  is permitted.
- Record the loaded menu independently. A saved workshop query menu need not
  survive a new game process; do not claim full menu equivalence.
- Verify owned native-process/listener, container and isolated local-VM cleanup.

## Execution boundary

[checkpoint416_fixture.py](checkpoint416_fixture.py) and
[checkpoint416_review.py](checkpoint416_review.py) are the new executable
fixture and its predeclared audit. Historical checkpoint-32 fixtures and review
failures remain unchanged. The owner binds the fixture and reviewer hashes to
the pushed declaration and refuses repeated execution or existing output.

Use one already-configured local VM at a time, CPU 2 / VM RAM 3 GiB / existing
disk 32 GiB, with no configuration growth, new cloud VM, image build, model,
API fallback, purchase, reset or evidence deletion. Mount the completed window
volume read-only and write a new diagnostic volume only. Reject insufficient
space instead of deleting evidence or growing a disk. Mandatory teardown applies
on success, exception, interruption and timeout.

Local preparation used actual saved agent/loop files with native-reader doubles:
10 tests passed. The strict load-log classifier passed 9 tests, including
unexplained file changes, prefix changes, extra entries and changed ordering.
Selected-file Ruff passed. These checks do not establish native reload success.

Private owner and evidence:
`fort_gym/artifacts/native-local-20260906/runtime-v2/keyboard-matched-pilot-v1/keyboard-bindings-astra-r1-reload-416-v1`.

An executed attempt is immutable. A result will be published separately after
the fresh native load and retained-evidence audit; this declaration is not a
success claim or completion of the full cross-model evaluation goal.
