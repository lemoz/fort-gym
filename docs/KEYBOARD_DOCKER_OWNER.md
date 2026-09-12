# Portable keyboard Docker owner

The entry point is python -m scripts.campaign_keyboard_docker. It composes the
existing native runner and subscription courier on an already available local
Docker engine. It supports fresh starts and unchanged own-save continuations
without importing a dated private operator.

Source `40b106b95f483b534a738622e75c4147a1270a96` passed a bounded native
acceptance: Astra made two fresh decisions, saved, reloaded that own save and
made two more decisions. The independent continuity audit is
`a9a193fc539fe7541b48625cde1a00782cb29017f32b9fb92b6d5a059b3e47df`.
All four decisions were paused (zero elapsed game ticks). This proves the
save/resume path, not fortress growth, sustainability or model ranking.
Keep existing frozen trials on their original owner and source.
Do not move the unfinished matched Astra attempt to this entry point to bypass
the known capacity gate.

The [source-context packager](KEYBOARD_IMAGE_CONTEXT.md) prepares an independent
checkout and checksum-bound generated bindings for a new image, without the
dated private build scripts. It does not install a base runtime or execute a
Docker build. Runtime preparation, image building and native acceptance are
separate steps; the acceptance above covers that exact source/image only.

When a declaration pins its original source/image, campaign, condition digest
or prior usage, those bindings are checked. A different runtime cannot silently
reuse a frozen declaration. Condition and declaration files are copied byte-for-byte.

## Required inputs

Use an unprivileged host account and a local Unix-socket Docker context. The
selected image must already exist and contain:

- The exact clean, committed Fort Gym checkout identified below.
- A Python environment with the project and native dependencies installed.
- Compatible Linux Dwarf Fortress and DFHack assets, protocol bindings, shared
  libraries and the script utility needed by the native launcher.
- No implicit Docker data volumes. The owner mounts only its game evidence
  directory, read-only condition files and the read-only starting snapshot/save.

The image must support the host account's numeric UID/GID and a read-only
container root. Native copies, saves and logs go into the mounted game evidence.
Credentials, the host model executable, model transcripts and private courier
output are not mounted into the game. The container has no network, published
ports, extra capabilities or access to the Docker socket.

Declare a runtime JSON file with these exact fields. Replace both placeholders
with the actual reviewed image ID and the commit contained in that image; the
host checkout must be at that same clean commit.

    {
      "schema_version": "fortgym.keyboard-docker-runtime/v2",
      "image": "sha256:<64 hexadecimal characters>",
      "source_revision": "<40 hexadecimal characters>",
      "project_directory": "/workspace/fort-gym",
      "python_executable": "/venv/bin/python",
      "runtime_directory": "/opt/df",
      "cpus": 2,
      "memory_mib": 4096,
      "pids_limit": 512,
      "minimum_host_free_bytes": 1610612736,
      "seccomp_profile": "/absolute/host/path/reviewed-dfhack-seccomp.json",
      "seccomp_sha256": "<64 hexadecimal characters>"
    }

Paths inside the image are explicit settings. The model, prompt, display,
controls and usage ceilings come from the separate versioned condition file.
A model change is a new study condition, not a mid-campaign rewrite of history.

### Native launcher compatibility

The DFHack launcher used by the retained native trials calls
`personality(262144)` (`PER_LINUX | ADDR_NO_RANDOMIZE`). Docker's default policy
rejected this during the earlier native compatibility attempt. Runtime schema
v2 therefore explicitly selects a reviewed client-side seccomp JSON file and
its SHA256. The owner preserves its exact bytes, records its digest, and passes
the retained file to Docker. It never uses `seccomp=unconfined` or privileged
execution. Docker reads the profile on the client host; it is not a game mount.
See [Docker's profile documentation](https://docs.docker.com/engine/security/seccomp/).

Use a versioned policy appropriate for the selected engine, with default action
`SCMP_ACT_ERRNO` and the following narrowly scoped rule added to `syscalls`:

    {
      "names": ["personality"],
      "action": "SCMP_ACT_ALLOW",
      "args": [{"index": 0, "value": 262144, "op": "SCMP_CMP_EQ"}]
    }

Keep every other rule unchanged and review the base policy separately. The
owner checks default-deny behavior, a specific launcher allowance and absence
of unconstrained personality allowances. It does not audit every syscall or
assert that a supplied profile is current. In particular, the retained historical
Moby 27 profile is evidence for that frozen environment, not a recommendation
to apply a 2024 policy to a newer engine. This command does not download or
change the host's policy. Its `check` mode also verifies the supplied bytes.

Schema v1 remains readable for older declarations and uses Docker's default
policy. It does not gain a compatibility override silently and is not suitable
for the known launcher on engines whose default denies this call. If a trial
pins `seccomp_sha256`, a different or absent selected profile is rejected.

New owner containers use Docker's init process for child reaping and set the
combined memory/swap limit equal to the declared memory limit. They do not
inherit an undeclared additional swap allowance.

The minimum_host_free_bytes field checks the host output filesystem before an
attempt. It is not a reservation, a guest-disk measurement, a future-growth
guarantee or permission to lower another experiment's floor. The native runner
retains its own copy/checkpoint capacity checks. Provide enough space for both
host evidence and Docker engine storage; this command never grows either.

## Check without executing

All file paths must be resolved absolute paths. The origin is a verified native
snapshot for fresh, or the model's verified settled checkpoint for continue.
A continuation uses that checkpoint's own usage.jsonl; it cannot substitute an
older usage file or another model's memory.

    python -m scripts.campaign_keyboard_docker check \
      --mode fresh \
      --runtime "$RUNTIME_CONFIG" \
      --condition "$CONDITION_FILE" \
      --declaration "$FRESH_TRIAL_FILE" \
      --origin "$STARTING_SNAPSHOT" \
      --campaign-id "$NEW_CAMPAIGN_ID" \
      --output "$NEW_ATTEMPT_DIRECTORY" \
      --context "$EXISTING_DOCKER_CONTEXT" \
      --docker "$DOCKER_EXECUTABLE" \
      --model-executable "$MODEL_COURIER_EXECUTABLE" \
      --port 5540

The check command reads local source/configuration/save data and prints a
container command. It creates no directory and contacts neither Docker nor the
model account. It does not verify image availability, image contents, native
wire compatibility or the ability to execute a game.

## Execute one bounded attempt

After confirming the declared source, image, native compatibility, storage and
execution authority, replace check with run. This can make subscription model
calls. For continuation, select --mode continue, pass the existing checkpoint
as --origin, and use its matching window JSON as --declaration. The output
directory must be new; an existing attempt cannot be reused.

The owner checks the local engine and exact image, then reads current model
allowance before creating a container. Each subsequent model invocation retains
the original fresh admission check. Unknown charges remain unknown. It creates
and starts one nonce-labeled container, serves the finite declared window, and
verifies that exact container has stopped on exit. An uncertain create is
reconciled against its predeclared name and ownership label, never retried.

The native runner separately verifies its source, origin, display, save and
owned game-process cleanup. It receives only the declared model actions. An
execution_finished owner status means the runner reported settled execution
and the owner verified container stop. It is not an independent terminal audit,
proof of fortress viability or a fresh reload of the final checkpoint.

The stopped container is retained with captured metadata and logs. The owner
does not remove containers, images, volumes or original saves. It does not
provision machines, start/stop a Docker-managed VM, pull images, substitute
models or publish website feeds. Storage retirement is a separate scoped action.

## Evidence and limitations

Each attempt separates game/ evidence from private host model/ receipts. It
retains the source/configuration plan, command logs, admission observation,
request/claim/response records, container inspections and owner-result.json.
Docker command stdout is retained in .log and stderr in .stderr.log. Only
stdout is parsed as an ID or JSON; stderr warnings remain inspectable and do
not contaminate the machine result. Nonzero exit codes still fail without a
retry, and the exact container ID and ownership checks remain unchanged.
The courier binds read-only exchange probes to its declared output directory,
including this owner's /fortgym-evidence/native layout. This permits only the
same exact listing and request-readiness probes, not arbitrary commands or
model/input retries. The historical /evidence/astra layout remains supported.
Publish only existing allowlisted observer and audited result/recording
derivatives, never private model data.

Denied admission is a budget pause without container creation. Native, courier
and teardown errors remain failed executions with retained evidence. Known
returned tokens and responses with unknown token counts are separate fields.
These count the new window, not cumulative usage in the native checkpoint.
An uncertain delivery never triggers another inference.

Stopping the owned container allows its 30-second grace period plus reply
overhead. If that command times out or is interrupted, the owner retains the
error and inspects the same container ID once. Verified stop and failed command
remain separate facts: the attempt still fails, and no stop, game input or
model request is retried. If the container is still running or its identity
cannot be verified, cleanup remains explicitly unverified.

Recovery, prompt-change and budget-extension declarations retain their
dedicated launchers and audits. This owner rejects those windows instead of
silently simplifying them. Fresh-machine portability, a live spectator run
with this layout and the remaining source review still need verification.

## Spectator output

The read-only portable adapters use this owner's `owner-plan.json`, `model/`
and `game/native/` layout. They do not call a model, send gameplay inputs,
control Docker, or change saved evidence. Publish only their allowlisted
derivatives, never raw requests, responses, agent memory or transcripts.

Export ordered, completed windows with their exact independent audit:

The current exporter accepts the retained `portable-owner-continuity-audit/v1`
format from the two-VM acceptance setup, including that setup's VM stop fields.
It is not yet a general audit generator for arbitrary single-engine runs. A
versioned, reusable run-audit contract remains to be added; operators must not
invent VM stop assertions or stop an unrelated shared VM to satisfy this format.

    python -m scripts.export_keyboard_docker_recording \
      --attempt /absolute/fresh-output --attempt /absolute/continuation-output \
      --audit /absolute/audit.json --audit-sha256 <exact-audit-sha256> \
      --id example-save-resume --title 'Harness save-and-resume check' \
      --output /absolute/new-recording.json

The write-once recording verifies the audit, native results, checkpoints,
model receipts, executed actions and consecutive own-save offsets. It uses
the existing `fortgym.watch-recording/v1` player format. The captured four
acceptance decisions exercise this export without any new inference.

For an expiring public-format status feed outside the private attempt tree:

    python -m scripts.campaign_keyboard_docker_observe once \
      --attempt /absolute/completed-output --public-dir /absolute/public-feed

`once` requires retained terminal owner and owned-container stop evidence and
always reports a stopped recording. It supports older plans without process
metadata. For a future running owner, replace `once` with `follow`; new plans
record an optional host PID/start/command identity. `follow` must match that
identity before publishing live status, checks it again on each observation,
and reports stopped if it disappears or changes. Missing process-inspection
permission disables follow mode, not gameplay. Observation errors let the last
good feed expire instead of inventing liveness. The adapter is not a relay or
deployment command.

The live feed shows stated intent and chosen keys, explicitly not verified
execution. The audited recording separately verifies execution. Offline
contracts and stopped captured-data export are covered; actual live follow
acceptance awaits the next otherwise-needed native run. Adding spectator
metadata does not extend native acceptance to a newer source revision.
