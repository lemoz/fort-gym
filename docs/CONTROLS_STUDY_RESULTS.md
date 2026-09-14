# Astra: keyboard input versus workshop shortcuts

The completed v2 study contains three paired repetitions from one starting save.
All six attempts used Astra Medium, empty starting memory, a 120x40 screen and
the same declared 128-response limit. Keyboard mode used normal game controls.
Shortcut mode additionally allowed job insertion into a selected workshop and
included the corresponding instructions. A queued job was not scored as a
completed product. The exact conditions remain in `experiments/selected_workshop_study_v1`;
the v2 declaration binds those unchanged bytes to the repaired courier source.

## Recorded outcomes

| Pair | Controls | Elapsed ticks | Living / recorded dead | Beds / workshops / farms | Raw food / drinks |
| --- | --- | ---: | --- | --- | --- |
| 1 | Keyboard | 70,900 | 7 / 0 | 7 / 2 / 1 | 43 / 135 |
| 1 | Shortcuts | 68,200 | 7 / 0 | 7 / 2 / 1 | 39 / 115 |
| 2 | Keyboard | 51,900 | 6 / 1 | 7 / 5 / 1 | 61 / 122 |
| 2 | Shortcuts | 49,600 | 7 / 0 | 10 / 2 / 2 | 40 / 136 |
| 3 | Keyboard | 46,400 | 7 / 0 | 7 / 3 / 1 | 42 / 122 |
| 3 | Shortcuts | 58,200 | 7 / 0 | 7 / 2 / 1 | 56 / 161 |

Neither condition clearly dominates these endpoints. These are repeated policies
on one seed, not independent worlds or a strong control ranking. Equal response
limits do not imply equal game time or token use. Inventory and sampled work do
not establish production rates, accessible reserves or self-sufficiency. The
short comparison cannot establish Year-Two endurance; that is a separate run.
Combined usage was 22,995,467 returned tokens. Subscription charges are unreported.

## Reproduce the comparison without a game or model

Run from this checkout after the [quickstart installation](YEAR_TWO_QUICKSTART.md).
The command reads only the declared manifests and prints JSON:

```sh
.venv/bin/python -m scripts.summarize_selected_workshop_cohort \
  --study experiments/evidence/selected_workshop_runtime_v2_declaration_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p1_keyboard_128_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p1_shortcuts_128_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p2_keyboard_128_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p2_shortcuts_128_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p3_keyboard_128_20260912.json \
  --result experiments/evidence/selected_workshop_v2_p3_shortcuts_128_20260912.json
```

Output matches `experiments/evidence/selected_workshop_v2_cohort_20260912.json`
byte for byte. Regression checks bind each result to its original replay audit,
control profile, action routes and actual elapsed ticks. Missing results remain
unknown; this summarizer does not perform a new native execution audit. Each
attempt freshly reloaded its own decision-64 save before continuing, but the
final decision-128 saves do not claim another independent reload.

All six replays are available in the public Worlds gallery and homepage selector.
The [paired Results panel](https://fortgym.live/results#controls-comparison) is
also published and included in this checkout. Its table, original downloadable
summary and six replay links have separate
[website delivery evidence](../experiments/evidence/controls_study_website_20260913.json).
The [publication guide](CONTROLS_STUDY_PUBLICATION.md) explains its source bindings.
This later integration changes no native runtime, model, condition, original
result or recording. The main-branch merge remains separate.
