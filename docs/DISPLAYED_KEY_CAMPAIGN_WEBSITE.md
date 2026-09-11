# Displayed-key campaign website

The campaign page presents Astra's original 32-decision pilot and its audited
own-save continuation as **one 64-decision campaign**, not two independent trials.
This control condition remains separate from the historical six-attempt model
cohort. The page retains the existing layout, original endpoint and archived
evidence; no game controls, models, deployment settings or dependencies change.

`GET /public/keyboard-binding-campaign` assembles only registered, SHA-pinned
public records. It does not scan private game artifacts or infer active runs.
The 64-decision result has 29,500 elapsed ticks, 1,583,026 returned tokens,
seven living dwarves, zero recorded dead, four completed placed beds, two
workshops, one farm, food40 and drinks103. Every one of its 64 decision rows is
inspectable, with intended action, confirmed keys, requested/actual elapsed
ticks, state measurements and tokens. Intent is not proof of success.

The save history identifies the original decision-32 checkpoint's separate
fresh reload as verified. That reload preserved game/agent state but returned
to the default menu and appended two DFHack load-log lines in the disposable
copy; the initial strict equality failure remains in its linked evidence.
The decision-64 checkpoint has a verified save, but **no separate post-run
fresh reload**. Its guest poweroff SSH warning remains disclosed alongside the
successful VM stop and independent stopped check.

The original `GET /public/keyboard-binding-results` response and all historical
cohort endpoints remain unchanged. The old result data and old frontend asset
remain available. The new frontend preserves safe text rendering, unknown
values, bounded refresh requests and a last-loaded-result warning on failures.
It explicitly reports one attempt, unreported dollar charges and unproven
sustainability. Static recorded results must not be described as live gameplay.

Sources, copied byte-for-byte:

- [Decision-64 continuation](../experiments/evidence/keyboard_binding_astra_r1_continuation_32_64_20260911.json),
  SHA `5f86a754fbb979a567c14a236250ccd518c171db79e598ae9adaa4745db9d8e4`,
  published at `fac32010f483959ed2c28d358ec358c1d9ab20fc`.
- [Decision-32 reload](../experiments/evidence/keyboard_binding_astra_r1_reload_20260911.json),
  SHA `291bee15debe7c47d606221b61e99ce8eef0415233480042a4fa0720c5d39458`,
  published at `242fa861227fd725a839909f04e7a6203cd0f20a`.

TestClient and lightweight JavaScript DOM regression tests are not browser
visual/layout acceptance. The native gameplay and VM teardown evidence precede
this website work; website checks add no gameplay, Year-Two success or ranking.
This development branch does not imply main merge or public deployment.

Validation for this website update: the full offline suite passed 4,992 tests
with 10 skipped. Changed-file Ruff, JavaScript syntax and the real-record
TestClient/DOM regression checks passed. A same-environment baseline comparison
retained the same 10 repository-wide Ruff findings and 465 mypy errors in 27
files (identical diagnostics after accounting for shifted line numbers); the
new API module has no added type findings. Existing static debt is not reported
as clean. Public Python files use Ruff formatting at line length 100 because
Black is unavailable in the selected environment/offline cache.
