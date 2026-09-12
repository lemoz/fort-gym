# Year-Two harness: current entry point

This guide describes the integrated native-keyboard harness and public viewer.
Older dated documents retain their original proof states; their references to
"next" or "not yet integrated" do not describe the current experiment queue.
This branch is an integration candidate, not a new native runtime revision used
by the ongoing matched cohort and not a claim of deployment or main merge.

## What is available

- A model-selected native keyboard runner with game checkpoints, agent memory,
  original prompt and cumulative usage preserved across continuation.
- Versioned condition files selecting Astra, Sol or Terra at Medium. The current
  displayed-key cohort fixes one seed, a 120x40 lossless screen-text observation,
  the same control bindings and budgets, and two attempts per model.
- Six audited fresh 64-response results and their own-save continuation windows.
  Read the result index for settled 128-response outcomes; absence of a result
  does not report live status. Three continuations are saved, while both Sol
  starts failed infrastructure gates with their original checkpoints preserved.
  Astra r2 has no 128-response result; the latest known guest capacity shortage
  prevents its launch without changing storage conditions.
- A homepage player, fifteen immutable recording windows, the Worlds gallery,
  comparison tables, and an optional read-only live observer.

These short matched starts are not the earlier exploratory Astra Year-Two run.
The latter's recording is retained separately. Inventories and sampled activity
are not measured production rates or proof of indefinite self-sufficiency.

## Install and inspect without a model or game

Use Python 3.11 and a source checkout. The `scripts` commands run from that
checkout; the private game installation and runtime artifacts are not included.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,agent,proto]'
.venv/bin/python -m scripts.campaign_displayed_key_comparison \
  --index experiments/evidence/keyboard_binding_comparison_20260911_index.json \
  --boundary 64
.venv/bin/python -m scripts.campaign_displayed_key_comparison \
  --index experiments/evidence/keyboard_binding_comparison_20260911_index.json \
  --boundary 128
.venv/bin/python -m scripts.campaign_displayed_key_window \
  --campaign-id bindings-comparison-20260911-astra-r1
```

The comparison reader verifies exact declaration/configuration/result digests.
The final command only describes an own-save continuation. It cannot load the
game, start a VM, make a model call or rerun an existing identity.

To serve the bundled recordings locally:

```sh
.venv/bin/python -m fort_gym.bench.cli api --no-reload
```

Open the printed local URL, then `/`, `/worlds`, or `/results`. With no live
observer, recordings remain usable; the website does not invent an active run.
`FORT_GYM_PUBLIC_CAMPAIGN_DIR` optionally selects a directory containing an
allowlisted observer derivative. Never point it at private model transcripts.

### Verified setup scope

An isolated checkout of `bce580ae30782b258453889283c10f1ccba06a7b`, installed
in a new Python 3.11.15 virtual environment using the commands above, passed
dependency checks, all three model-condition parsers, the comparison/window
commands, and local HTTP checks for twelve recordings containing 928 frames.
The same fresh environment passed 659 focused tests. The local server was
stopped afterward. See the [setup and review record](../experiments/evidence/keyboard_integration_setup_review_176_20260912.json)
for the resolved dependency versions and exact source boundary.

That first check verified the Python tools and bundled viewer, not a fresh game
installation, generated DFHack bindings, browser visual behavior or a portable
native owner. A [separate protocol setup check](../experiments/evidence/keyboard_integration_protocol_setup_176_20260912.json)
then generated all eight bindings for the official `52.04-r1` schema and loaded
them in the same isolated environment, including partial empty-message round trips
for 131 declared message types. The earlier setup receipt and tracked source are
unchanged. The explicit generation command for that tested schema is:

```sh
.venv/bin/python -m fort_gym.bench.env.remote_proto.fetch_proto --version 52.04-r1
```

This proves generation/import, not compatibility with any chosen running game.
Use the schema declared for the target runtime; do not replace an existing
experiment's frozen bindings. These checks made no model calls and launched no
game or VM. The later portable acceptance below is a separate exact-source
runtime check, not a retroactive extension of this setup receipt. Installing
optional provider dependencies does not authorize disabled providers.

## Running a new native experiment

The game-side entry points are `scripts.campaign_keyboard_trial run` for a fresh
start and `scripts.campaign_keyboard_native run` for a continuation. Their
`--help` output lists the required explicit source, snapshot/checkpoint,
condition, output and RPC inputs. The [native runtime guide](CAMPAIGN_NATIVE_RUNTIME.md)
describes compatible game assets and snapshot preparation; the
[binding profile](KEYBOARD_BINDING_PROFILE.md) defines displayed keys and time
advance. A helper shortcut is a different, explicitly labelled condition.

The [matched owner](../experiments/keyboard_binding_comparison_continuations_20260911/README.md)
is the retained operator for this particular cohort. It binds existing private
runtime paths, image, seed and exact frozen source. It is not a portable VM
installer. Its historical example identities must not be launched again.
Fresh-machine native provisioning and a complete portable owner setup have not
been accepted merely by integrating these source files.

A [public Docker owner](KEYBOARD_DOCKER_OWNER.md) now composes fresh starts and
unchanged own-save continuations with explicit image, source and container paths.
Its check command verifies local inputs without contacting Docker or a model;
run uses an already available local engine and owns stopping one container.
The public owner passed a real two-decision Astra fresh run and two-decision
own-save continuation at source `40b106b95f483b534a738622e75c4147a1270a96`.
[The immutable acceptance result](https://github.com/lemoz/fort-gym/blob/7fe87fb6addc031a95f421ef985f139375fe8920/experiments/evidence/keyboard_portable_owner_acceptance_20260912.json)
binds that source/image and reports 95,786 returned tokens. All four decisions
were paused: this proves native save/resume, not new fortress growth. A separate
clean local VM was used, but arbitrary fresh-machine provisioning is not proved.
Newer spectator and cleanup changes do not claim another native acceptance;
the frozen matched cohort must not switch to this new entry point.

For the next image, use [source-bound image packaging](KEYBOARD_IMAGE_CONTEXT.md)
to export the exact clean commit and declared generated bindings. Its standalone
context can be verified without the originating checkout. Preparation is offline;
the compatible base image and actual build/game validation remain separate.

For a new study, declare a new identity and condition; retain its selected model,
input profile, seed, prompt and budget throughout a campaign. The outer owner
supplies a credential-free game exchange, dispatches model requests, records
usage, checks capacity and tears down the game/VM. Existing subscription runs
do not silently use local models, paid API fallbacks, resets or credit purchases.
Unreported subscription dollar charges remain unknown, not zero.

## Result and website publication

Audit the terminal checkpoint, original receipts, actual game clock and teardown
before adding a settled result to the index. Keep failures and pauses visible.
See [comparison reporting](DISPLAYED_KEY_COMPARISON.md) and
[the spectator guide](HOME_SPECTATOR.md). The live feed contains captured screens
and explicit action descriptions, not private model reasoning or hidden memory.
Committing a result, publishing it, and verifying a public replay are separate
delivery steps. Neither a test suite nor a checkpoint alone completes the goal.

Portable-owner outputs can be projected by
`scripts.export_keyboard_docker_recording` and
`scripts.campaign_keyboard_docker_observe`; see
[their commands and proof boundaries](KEYBOARD_DOCKER_OWNER.md#spectator-output).
The [four-decision save/resume replay](https://fortgym.live/?recording=astra-portable-acceptance-1-4#watch-root)
is published separately from the model comparison. Actual portable live follow
still needs verification during the next otherwise-needed game; stopped
capture and synthetic lifecycle tests do not claim live native broadcasting.
