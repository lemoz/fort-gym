# Displayed-key campaign website

The campaign page presents Astra's original 32-decision pilot and its audited
two own-save continuations as **one 96-decision campaign**, not three independent trials.
This control condition remains separate from the historical six-attempt model
cohort. The page retains the existing layout, original endpoint and archived
evidence; no game controls, models, deployment settings or dependencies change.

`GET /public/keyboard-binding-campaign` assembles only registered, SHA-pinned
public records. It does not scan private game artifacts or infer active runs.
The 96-decision result has 59,500 elapsed ticks, 2,567,162 returned tokens,
seven living dwarves, zero recorded dead, five completed placed beds, three
workshops, one farm, food 58 and drinks 121. Functional-room measurement is
unavailable at the latest save and displayed as Unknown. Every one of its 96 decision rows is
inspectable, with intended action, confirmed keys, requested/actual elapsed
ticks, state measurements and tokens. Intent is not proof of success.

The save history identifies the original decision-32 checkpoint's separate
fresh reload as verified. That reload preserved game/agent state but returned
to the default menu and appended two DFHack load-log lines in the disposable
copy; the initial strict equality failure remains in its linked evidence.
The decision-64 and decision-96 checkpoints have verified saves, but **no
separate post-run fresh reload**. The decision-64 guest poweroff SSH warning
remains attached to that checkpoint, alongside its successful VM stop and
independent stopped check. Decision 96 has a clean shutdown; it does not erase
the earlier warning. Each continuation is linked to its exact source result
and checkpoint. Both continuation windows preserve all model-condition fields.

The latest-window summary shows three menu-blocked time-advance attempts.
Decisions 74, 78 and 91 advanced zero ticks; each following decision advanced
time. Requested and actual ticks remain separate in the full history.
The page reports completed workshops as well as beds and stock changes, without
claiming that an intended action or a stock increase proves a production rate.

The original `GET /public/keyboard-binding-results` response and all historical
cohort endpoints remain unchanged. The old result data and old frontend asset
remain available. The new frontend preserves safe text rendering, unknown
values, bounded refresh requests and a last-loaded-result warning on failures.
It explicitly reports one attempt, unreported dollar charges and unproven
sustainability. Static recorded results must not be described as live gameplay.

Sources, copied byte-for-byte:

- [Decision-96 continuation](../experiments/evidence/keyboard_binding_astra_r1_continuation_64_96_20260911.json),
  SHA `2b49a0e15e8d9dc80dfd4af3b020a83b58bc94eb29e50ed4fcba1f96f043986e`,
  published at `45e162e371250b382a2a840b7afac75b58bedc91`.

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

Validation: the full offline suite passed 5,001 tests with 10 skipped; 27 focused
API, chain-integrity and DOM-test-double checks passed. The first focused attempt retained one test assertion that omitted the
space between the functional-room label and value; the corrected assertion
matches the test double's rendered text. No historical or native evidence changed.
Changed-file Ruff and JavaScript syntax passed. Same-environment baseline
comparison retained the same 10 repository-wide Ruff findings and 465 mypy
errors in 27 files, with no added findings in the changed module. Existing static
debt is not reported as clean. Python formatting uses Ruff at line length 100;
Black is unavailable in the selected environment. Actual before/after HTTP
acceptance is recorded separately when this tested version replaces the local preview.
