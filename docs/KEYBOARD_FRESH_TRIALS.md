# Independent native-keyboard trials

`scripts.campaign_keyboard_trial` starts a new model-selected campaign from a
verified native starting snapshot. It fills the gap between selecting a model
in configuration and actually giving that model its own fresh campaign.
It does not change the ongoing Astra campaign or turn its continuation windows
into independent comparison attempts.

## Start contract

The caller supplies a complete existing keyboard condition, a fresh-trial JSON
file, a unique campaign ID and output directory, and the verified native snapshot.
The snapshot format is the existing `fortgym.native-save-smoke/v1` receipt with
its `native-snapshot/` directory. `source_snapshot_receipt_sha256` is the SHA256
of that receipt's `result.json`; the receipt also binds every native-save file.
A campaign checkpoint is not silently reinterpreted as this starting format.

The fresh-trial file requires:

- `schema_version`: `fortgym.keyboard-fresh-trial/v1`.
- `original_condition`: the supplied condition's filename.
- `source_snapshot_receipt_sha256`: the actual verified starting receipt digest.
- `steps_per_segment`: 1–64, no larger than the condition's dispatch allowance.
- `initial_memory`: `empty`; `strategy_intervention`: `false`.
- `snapshot_profile`: a supported native-save profile, explicitly declared.
- `runtime_rpc_transport`: `native-rpc` or the historical `cli` transport.

Optional measurement, measurement-timeout and resource-observation fields use the
same existing profiles as continuation windows. `hypothesis` and `notes` are
descriptive metadata. Unknown settings, continuation cursors, restart declarations,
prompt-change declarations and budget extensions are rejected in a fresh trial.
This is one first segment, not a hidden multi-segment or repeated-attempt runner.

The game-side invocation is:

```sh
python -m scripts.campaign_keyboard_trial run \
  --condition /private-experiment/condition.json \
  --trial /private-experiment/trial.json \
  --campaign-id unique-model-and-replicate-id \
  --snapshot /verified-starting-snapshot \
  --source /owned-game-installation \
  --output /new-unique-trial-output \
  --port 5540 \
  --revision EXACT_COMMITTED_REVISION
```

These paths and revision are placeholders, not an executable acceptance command.
Use a clean exact source revision. The outer owner still supplies the isolated
VM/container, game assets and host-side model courier; this CLI does not provision
a VM, hold credentials or bypass subscription admission. The courier reads the
same credential-free `exchange/` protocol and must enforce the condition before
each invocation. Existing resource, spending and teardown requirements apply.

## Fresh memory, preserved history

Only a pristine agent may initialize: no prior campaign ID, usage, memory, pending
events, budget extensions or prompt history. The selected starting prompt is a
`fortgym.keyboard-prompt-origin/v1` entry bound to the source snapshot receipt at
zero usage. It is explicitly an origin, not a fabricated checkpoint or a change
after gameplay. This lets current memory-replacement instructions apply from the
first decision without pretending the model inherited Astra's previous memory.

Historical agents without an origin retain their original prompt behavior.
Existing prompt changes, usage reconciliation, rejection handling and save-loss
history retain their prior semantics. An already-used agent cannot initialize a
new origin. Ordinary checkpoint restore still requires the same model and
configuration and preserves the origin, memory, usage and trace prefix.

After the first segment saves, continue with the existing
`scripts.campaign_keyboard_native run` command and a normal declared continuation
window. Use `segment-0/checkpoint`, its retained usage journal and actual next-step
cursor. Do not launch the fresh-start command again to continue the campaign.

## Outcomes and evidence

The wrapper verifies the loaded starting calendar and display before decisions,
retains source identity, actual initial agent state, model exchange, native
observations, trace, journal, save attempts, checkpoint and runtime cleanup.
Private food measurements remain outside the model's screen-only observations.

A subscription pause before the first dispatch records zero calls and leaves the
source snapshot as the starting point. It does not manufacture checkpoint zero
or a committed game action. A later budget pause preserves a real checkpoint
when one can be verified. An uncertain first response retains its usage and
forensic native snapshot rather than relabeling the trial unused. Failed saves
are not silently retried. Model rejection remains recorded input rejection, not
automatic repair or invented construction success.

## Comparison and acceptance boundary

Use independent IDs and output directories for each model and replicate. Match
the starting snapshot, source revision, controls, observations, prompt/memory
rules, viewport, runtime, save cadence, measurement settings and declared budgets.
Change the intended model/effort factor explicitly. Keep admission pauses,
provider failures and infrastructure failures distinct from game outcomes.

Offline tests exercise Astra, Sol and Terra identities through the real native
worker setup, synthetic exchanges, first save and ordinary continuation. They
also cover rejected input, quota/token pauses, unresolved responses and cleanup
failures. They do not establish model availability, native fresh-start acceptance,
fortress success, repeated comparable performance or a ranking. Those require
actual serial runs and retained receipts. No new native/model run was made for
this implementation milestone, and the website does not advertise one.

Validation for this increment: 143 focused tests and 4199 full-suite tests passed
(10 skipped). Changed-file Ruff and scoped mypy passed for seven implementation
modules. A read-only check of actual checkpoint 903 restored the complete existing
Astra agent state unchanged and rejected fresh-prompt initialization on that used
agent. This was not a fresh native load or a new model invocation.

Separately, a provider-free native diagnostic at the same source revision
subsequently loaded checkpoint 903 in a new game process and restored the normal
campaign loop without stepping it. It verified the paused calendar, actual
120x40 screen, unchanged agent state and byte-identical trace/usage journals,
then shut down the game, container and local VM. The retained checkpoint stayed
unchanged. In the disposable copy, only two DFHack load-log lines were appended;
all 126 other files, including world.sav, matched. See the
[versioned reload receipt](../experiments/evidence/astra_native_keyboard_checkpoint903_reload_20260910.json).
This establishes that checkpoint's fresh reload, not native fresh-start trial
acceptance, model availability, new gameplay or a cross-model comparison.
