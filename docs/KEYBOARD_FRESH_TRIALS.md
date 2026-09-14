# Independent native-keyboard trials

`scripts.campaign_keyboard_trial` starts a new model-selected campaign from a
verified native starting snapshot. It fills the gap between selecting a model
in configuration and actually giving that model its own fresh campaign.
It does not change the ongoing Astra campaign or turn its continuation windows
into independent comparison attempts.

The [matched pilot](KEYBOARD_MATCHED_PILOT.md) now supplies directly loadable
conditions/trials and six distinct campaign IDs for two starts each of Astra,
Sol and Terra at Medium. It is an experiment declaration, not completed model
evidence; the ongoing Astra fortress is excluded from those fresh-start comparisons.

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
the initial implementation milestone. The later native acceptance below uses
scripted responses and is not advertised as a model campaign on the website.

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

The campaign page now presents that receipt as a later verification beside its
matching saved window, not as another gameplay event. The existing
`/public/keyboard-campaigns` response includes separate `checkpoint_reloads` and
`checkpoint_reload_status` fields. It preserves the original window's
publication-time reload status and all counters. Missing or invalid later
evidence leaves the original campaign history available with an unavailable
verification notice; private fields are not projected.

## Native fresh-start acceptance: scripted, provider-free

At source `f970ba4382cf3b83452ae0ff1f8a240cd9507c1b`, a native fixture exercised
the unmodified fresh-trial CLI and ordinary continuation CLI, including their
real on-disk exchanges. It started from the shared seed with empty memory and
usage, sent one scripted camera-right key, saved checkpoint 1, resumed in a new
game process, sent camera-left, and saved checkpoint 2. A third native process
loaded checkpoint 2 and restored the ordinary loop without stepping. Initial
prompt origin, accumulated memory, trace and usage all passed independent audit.

All three native loads retained the paused year 30 / tick 16801 and actual
120x40 screen. Both keys were confirmed; no game ticks advanced. The seed was
mounted read-only; the existing Astra checkpoint was not mounted. Game, container
and local VM teardown passed and stopped state was independently rechecked.

There were zero provider calls. The two response receipts and 200 ledger tokens
are explicitly synthetic, not Astra usage or performance. The raw production
segment's autonomous flag must not be interpreted as model evidence here.
No fixture record was added to campaign/comparison website data. The existing
Astra fortress remains at checkpoint 903 and 268582 retained elapsed ticks.

The native source had green CI. Memory peaked at 1375010816 bytes under the
1536 MiB container limit, with no limit events or OOM kills; task peak was 16
of 256 and final visible zombies were zero. This short shared-seed diagnostic
does not establish headroom for longer model campaigns. Two audit-only field
assumptions were corrected against the retained receipt schemas; the native
run was not repeated or rewritten.

See the [versioned acceptance receipt](../experiments/evidence/scripted_native_keyboard_fresh_trial_20260910.json).
Private audit SHA256:
`1086e6dae1a0bd794543a5fcaab7602e778564cd5d6f075f00405f5e626c9a95`.
This closes provider-free native fresh-start/save/continuation acceptance. Actual
independent model calls, repeated comparable trials and year-two success remain
unproven and still require the original goal's experimental work.

Publication validation bound the shareable receipt to the exported native
evidence. All 137 focused fresh-start, continuation-launcher and public campaign
record/reload regressions passed. No production harness or website code changed
for this acceptance receipt.
