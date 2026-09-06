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
