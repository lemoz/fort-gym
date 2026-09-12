# Portable keyboard Docker owner

The entry point is python -m scripts.campaign_keyboard_docker. It composes the
existing native runner and subscription courier on an already available local
Docker engine. It supports fresh starts and unchanged own-save continuations
without importing a dated private operator.

This implementation has offline regression coverage, not fresh native
acceptance. Keep existing frozen trials on their original owner and source.
Do not move the unfinished matched Astra attempt to this entry point to bypass
the known capacity gate.

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
      "schema_version": "fortgym.keyboard-docker-runtime/v1",
      "image": "sha256:<64 hexadecimal characters>",
      "source_revision": "<40 hexadecimal characters>",
      "project_directory": "/workspace/fort-gym",
      "python_executable": "/venv/bin/python",
      "runtime_directory": "/opt/df",
      "cpus": 2,
      "memory_mib": 4096,
      "pids_limit": 512,
      "minimum_host_free_bytes": 1610612736
    }

Paths inside the image are explicit settings. The model, prompt, display,
controls and usage ceilings come from the separate versioned condition file.
A model change is a new study condition, not a mid-campaign rewrite of history.

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
Publish only existing allowlisted observer and audited result/recording
derivatives, never private model data.

Denied admission is a budget pause without container creation. Native, courier
and teardown errors remain failed executions with retained evidence. Known
returned tokens and responses with unknown token counts are separate fields.
These count the new window, not cumulative usage in the native checkpoint.
An uncertain delivery never triggers another inference.

Recovery, prompt-change and budget-extension declarations retain their
dedicated launchers and audits. This owner rejects those windows instead of
silently simplifying them. Fresh-machine image construction, actual native
wire compatibility, end-to-end container acceptance, live-observer wiring for
this layout and the remaining source review still need verification.
