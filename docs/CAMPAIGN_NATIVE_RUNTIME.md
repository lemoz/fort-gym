# Native campaign runtime

This runtime lets an agent continue the same Dwarf Fortress campaign across
bounded process lifetimes. Select a model and a versioned condition, start from a
digest-bound native save, and retain the game, agent memory, trace, and cumulative
usage together. The controller launches segments serially and verifies teardown
before continuing. It never creates a VM or deploys the website.

The delivery includes source, synthetic tests, experiment configurations and a
read-only reporting path. Native acceptance at this revision, a functioning
fortress after 403,200 elapsed ticks, and repeated comparable runs across at least
three models remain unproven. Existing recorded runs retain their original code
and condition identities; they are not acceptance evidence for this revision.

## Requirements

### Latest native verification, September 6

Source `fad9d80c0a2e7aace8380b47b009db5edaf6bd2e` passed the automatic v3
checkpoint recovery fixture on isolated Colima 0.10.3 / Lima 2.2.0 tooling.
It saved cursor zero at year 30, tick 16801, stopped the first game process,
restored the exact checkpoint in a second process, and executed one fresh
20-tick WAIT. Both cleanup receipts and an independent recovery verifier passed;
the container and VM stopped. A real translated-process probe also confirmed
ownership detection when the executable link could not resolve.
See the [automatic recovery receipt](../experiments/evidence/local_native_automatic_recovery_20260906.json).

This provider-free fixture is not autonomous gameplay or year-two proof.
Synthetic usage is not model consumption; no final checkpoint followed the WAIT.
Global tools, old profiles and historical failure receipts remain unchanged.
The new toolchain's successful boot/reboot does not explain old startup failures.

The next experiment uses the [new local Qwen3.5 condition](../experiments/campaigns/local_native_qwen35_year_two_v1.json):
existing 9B quantized weights, optional thinking disabled, 4,096 output tokens,
and the unchanged digest-bound starting seed, not the fixture's post-WAIT state.
Its first segment started September 6 on the isolated local VM with the existing
local model and an owned loopback tunnel. At 23:17 UTC, six model-selected WAIT
actions had advanced 6,000 native ticks. No completed segment or handoff is
claimed; the running source is still frozen at `fad9d80c0`.
The changed seed, runtime and budgets are declared; this is
not a matched historical comparison. Year-two play and repeated model evaluation
remain open. No production deployment is claimed.

### Runtime prerequisites

- Run the commands from a committed Git checkout with Python 3.11. Install the
  project's dependencies with `python -m pip install -e '.[dev,agent,proto]'`.
  The `scripts.campaign_*` commands require the checkout; they are not standalone
  wheel entry points. `fort-gym campaign-report` is an installed read-only command.
- Native execution requires an existing, compatible Linux DF/DFHack installation
  and its system libraries, `script` utility and matched protobuf bindings.
  Do not regenerate bindings for another DF version or point experiments at a
  production runtime. The launcher copies runtime assets; it does not provision
  or repair the host.
- Use a verified idle, paused starting-save receipt, a new private output
  directory, an unprivileged non-production RPC port range, and enough free disk
  for the copied runtime, all retained saves, logs and the condition's free-space
  floor. Artifacts are ignored by Git. Non-ignored untracked files also prevent
  a native launch, because the recorded commit must describe executed source.
  The launcher subtracts its planned runtime copy and retained checkpoint copies
  before accepting the floor; checking current free space alone is insufficient.
- Hosted calls require the existing project `OPENROUTER_API_KEY` in the calling
  environment. Local calls require an explicit loopback endpoint and a matching
  model digest/server identity. Local runs do not fall back to a hosted provider.
  The model-server launcher is separate from the Linux game runtime; its current
  pinned llama.cpp bundle targets macOS arm64. Its caller owns server teardown.
- Runtime and spending authorization are external to a configuration file.
  Neither example commands nor a per-campaign cap grant that authority.

## Prepare a starting snapshot

For an already authorized, idle, paused **test** runtime, the provider-free
`python -m scripts.campaign_save_smoke --help` command describes snapshot capture.
It preserves the previous on-disk save, requests one native save without advancing
gameplay, and writes an output directory containing `result.json` and
`native-snapshot/`. Bind the campaign to the SHA-256 of that exact `result.json`.
The loader rechecks the receipt, retained save inventory and paused calendar.
A filesystem copy alone is not this receipt.

### Capacity preflight

Before contacting a local model service, publishing a started feed entry, or
launching a copied game, the segment estimates the selected runtime assets,
starting save and planned checkpoint copies. It follows the same source selection
as the copier, excludes old source saves/logs, uses the selected hook overlay,
and counts followed links for each destination copy. A shortage raises a capacity
error without a new runtime directory. The runtime owner repeats the check before
allocation and before copying. Successful runtime receipts retain the numeric
`capacity_preflight` report.

This report is a filesystem-block-rounded estimate, not a storage reservation or
a bound on future save, trace or log growth. Checkpoints are estimated at their
starting save size. Existing per-decision and native-snapshot free-space checks
remain in force. The preflight does not lower a declared floor, delete retained
evidence, enlarge disks, provision a host or authorize spending.

New runtimes do not duplicate `data/seed_saves`, `data/save_backups` or
`data/save-quarantine`. These archives are unrelated to the selected campaign
save, which is copied separately into `data/save/campaign-resume`. Their original
contents, old runtime copies, receipts and historical runs remain untouched.

## Start and continue

The following template uses shell variables deliberately: fill them with the
chosen condition, its declared model, an authorized runtime and a verified save.
`CAMPAIGN_OUTPUT` must not exist; its parent must exist. These commands execute
gameplay and can make billable calls when a hosted condition is selected.

```sh
python -m scripts.campaign_run \
  --config "$CAMPAIGN_CONFIG" --model "$CAMPAIGN_MODEL" \
  --campaign-id "$CAMPAIGN_ID" --source "$DF_RUNTIME_SOURCE" \
  --snapshot "$SNAPSHOT_DIRECTORY" --snapshot-sha256 "$SNAPSHOT_RECEIPT_SHA256" \
  --output "$CAMPAIGN_OUTPUT" --segments 1 --port 5501 \
  --public-campaign-dir "$CAMPAIGN_PUBLIC_FEED"
```

For a local condition, also pass `--local-endpoint "$CAMPAIGN_LOCAL_ENDPOINT"`.
The endpoint must be a verified loopback service (or an operator-owned loopback
tunnel); the game launcher does not establish networking or start that service.

Continue the same campaign with the same source, model, condition, code revision,
output directory and first port. Replace the snapshot arguments with `--resume`:

```sh
python -m scripts.campaign_run \
  --config "$CAMPAIGN_CONFIG" --model "$CAMPAIGN_MODEL" \
  --campaign-id "$CAMPAIGN_ID" --source "$DF_RUNTIME_SOURCE" \
  --output "$CAMPAIGN_OUTPUT" --resume --segments 1 --port 5501 \
  --public-campaign-dir "$CAMPAIGN_PUBLIC_FEED"
```

`--segments` limits this invocation, not cumulative campaign usage. Later segments
use successive ports. A file lock prevents concurrent controllers for one output
directory. Native commands with uncertain mutation or unresolved usage are not
silently replayed. A failed segment retains its evidence and requires explicit
reconciliation before continuation.

For new experiments, create a new condition identity when changing prompts,
action schemas, model weights, measurement behavior or budgets. Preserve existing
JSON conditions and recorded results. `endurance_autonomous_v1.json` declares
three hosted model identifiers with the same bounds; configuration support is
not proof of current provider availability or successful gameplay. Frozen local
conditions additionally bind model files, digests, runtime, context and sampling.

## Inspect evidence and costs

- `campaign-run.json` and `controller.jsonl`: campaign identity, continuation
  status, latest verified checkpoint and cumulative reported usage.
- `segments/segment-NNNNNN/campaign/`: trace, dispatch/response usage and failures.
- `checkpoint/`: native save, agent state, retained trace/usage and digest-bound
  manifest. A forensic save without reconciled agent/usage state is not resumable.
- `result.json`, `campaign-segment.json`, `campaign-profile.json`: native load and
  cleanup, segment outcome, checkpoint validity and factual performance profile.
- `python -m scripts.campaign_profile SEGMENT_DIRECTORY` reports an existing
  segment. `fort-gym campaign-report TRACE_JSONL` reports elapsed time without
  starting a model or game. A calendar year rollover is not a full elapsed year;
  403,200 elapsed ticks is a milestone, not automatic viability or success.

Per-campaign dispatch, token and returned-cost counters survive continuation.
A returned-cost threshold is **not** a reservation or reconciled invoice, and the
last response can cross it. Missing usage stays unknown. Zero metered provider
cost for a local model does not mean zero hardware, electricity or host cost.
Aggregate spending must still be tracked outside one campaign's counters.

The v3 campaign loop can save an accounted no-action output-limit response as
`inference_output_limited_pause`; it does not claim fortress collapse. Earlier
loop versions keep their earlier failure/reconciliation semantics. Budget,
invocation and output-limit pauses are distinct from gameplay failure.

## Provider-free v3 restart acceptance fixture

`python -m scripts.campaign_output_pause_smoke --help` describes the separate
no-action recovery fixture. It uses one new runtime asset copy across two serial
native process lifetimes, one retained v3 checkpoint, and no model/provider
client. Its first synthetic response accounts ten fixture tokens but executes no
game command. It saves and tears down, verifies the on-disk save still matches
the checkpoint byte-for-byte, then restarts that same owned runtime and restores
agent/runner/usage state before one fresh 20-tick WAIT fixture.

The shared launcher checks the paused native calendar and tears down the exact
owned process group/runtime members. Restart additionally requires the prior
receipt digest, matching source revision, successful teardown, no live runtime
members, a free non-production port, regular owned paths and exact save bytes.
An exclusive lock serializes callers and a durable single-use claim prevents a
second attempt, including after a failed launch. No file is deleted or replaced
to restore a checkpoint; a changed save is rejected, not rolled back.
If the previous endpoint is closed but temporarily not bindable, restart waits
up to 90 seconds before claiming or launching anything. This retries only local
port probes, not game/model operations. A live listener, unknown connectivity,
owned live process or any other bind error is rejected immediately.

The first preflight includes one checkpoint and the growth allowance above the
declared floor. Restart reserves no space and checks the floor plus that allowance
again. Defaults are a 1 GiB floor and a 1 MiB growth allowance; estimates are not
guarantees against future growth or other writers. Source checkout/object storage
must already be accounted for before execution.

The fixture produces synthetic usage counters explicitly labeled
`synthetic_fixture_only`, not actual model token consumption. It does not diagnose
a real model's output limit or prove autonomous play. The resumed endpoint has no
new final checkpoint and must not be presented as an endurance handoff. This
candidate still requires actual native acceptance; unit tests use game doubles.
It does not change the historical two-runtime continuation fixture or add runtime
reuse/retention to the campaign controller. Long campaigns still require a
separate storage lifecycle. The command does not provision a host or grant
runtime/deployment authority.

Native observation, September 6: [the v3 recovery fixture evidence](../experiments/evidence/native_output_pause_recovery_20260906.json)
records successful saving, process teardown, exact-state loading and fresh
20-tick execution at source `ade9af102`. The original automatic command stopped
before the second process because its closed port was temporarily not bindable.
An explicitly retained operator driver completed only the second phase using the
same frozen implementation and verified checkpoint. Both process lifetimes have
independently verified teardown. Synthetic usage progressed from 10 to 20 fixture
tokens, not actual model consumption. The new bounded port-wait correction is
unit-tested but has not passed a fresh native automatic-command run. Do not
reclassify this result as an uninterrupted CLI pass, model run or year-two proof.

Later local observation: [the native harness checkpoint receipt](../experiments/evidence/local_native_harness_checkpoint_20260906.json)
records source `43a53762c` running under Linux/amd64 translation on the Mac.
A private derived image supplied pinned Python 3.11, the retained provider-free
wheelhouse and verified generated bindings. A fresh paused seed save succeeded,
then the first fixture process loaded it and created a valid v3 checkpoint at
cursor zero, year 30/tick 16801. No game action or model call occurred.

The automatic CLI failed during first-process cleanup: the scanner found no
owned PIDs but the listener remained open. Its container then exited, the outer
operator stopped both containers and the VM, and private evidence was retained.
A follow-up process diagnostic did not run because VM SSH startup timed out;
successful prior reboots are not a guarantee of reliable subsequent startup.

The scanner now evaluates `cwd` and `exe` independently, preserving a valid
ownership match when the other link is unavailable. Same-UID, exact runtime-path,
terminal-process and PID-start-time checks remain. Two regressions failed before
this correction and pass afterward; a third rejects two unresolved links. The
precise translated process links were not captured, so this correction still
requires native confirmation rather than claiming it explains the observed leak.
The first checkpoint must not be resumed by rewriting its failed cleanup receipt.

## Website and historical compatibility

Pass a private feed directory to the runner and configure the existing API's
`FORT_GYM_PUBLIC_CAMPAIGN_DIR` to that same directory. The existing `/campaigns`
page and `/public/campaign-feed` expose the allowlisted projection, not prompts,
credentials, filesystem paths or saves. Missing/stale feeds stay distinguishable
from an active run. Changing source does not deploy or restart the website.

Campaign-only `campaign_fort_metrics_v1.lua` and `campaign_job_metrics_v1.lua`
provide richer structure and crew observations. Historical `fort_metrics.lua`
and `job_metrics.lua`, benchmark prompts and decision/review rules remain pinned
and unchanged. Legacy workshop placement defaults to `strict_floor/v1`; the
versioned native ground policy must be selected explicitly by a condition.
No assisted digging, inventory injection or strategy selection is added by the
campaign adapter. Food/drink flow measurement remains unavailable until it has
a campaign-scoped native measurement lifecycle.

Public profiles are descriptive evidence. A valid ranking still needs matched
starting saves, conditions, code, model identity and budgets, repeated attempts,
and demonstrated functioning-fortress outcomes, not elapsed time alone.
