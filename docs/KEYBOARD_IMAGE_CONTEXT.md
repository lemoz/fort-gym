# Source-bound native image context

`python -m scripts.campaign_keyboard_image` prepares a standalone Docker build
context for the [portable owner](KEYBOARD_DOCKER_OWNER.md). It does not contact
Docker, download assets, build an image, start a VM or call a game/model.

This replaces the source-packaging dependency on a dated private operator or
chain of source-update images. A compatible base runtime is still required.
It is not a fresh-machine game installer or a native-acceptance certificate.

## Inputs

Supply a clean committed source checkout and a private JSON file with these
fields. Every placeholder must be replaced with an observed value. Keep the
input JSON outside the checkout or in its ignored artifact area.

```json
{
  "schema_version": "fortgym.keyboard-image-inputs/v1",
  "source_revision": "<40-character committed source revision>",
  "base_image": "sha256:<64-character existing image ID>",
  "base_reference": "<existing-local-image>:<literal-tag>",
  "project_directory": "/workspace/fort-gym",
  "python_executable": "/opt/python/bin/python3.11",
  "runtime_directory": "/opt/dwarf-fortress",
  "bindings_source": "/absolute/host/path/to/verified/generated-bindings",
  "bindings_sha256": {
    "__init__.py": "<sha256>",
    "AdventureControl_pb2.py": "<sha256>",
    "BasicApi_pb2.py": "<sha256>",
    "Basic_pb2.py": "<sha256>",
    "CoreProtocol_pb2.py": "<sha256>",
    "DwarfControl_pb2.py": "<sha256>",
    "ItemdefInstrument_pb2.py": "<sha256>",
    "RemoteFortressReader_pb2.py": "<sha256>",
    "ui_sidebar_mode_pb2.py": "<sha256>"
  },
  "uid": 501,
  "gid": 20
}
```

Use the numeric UID/GID of the host account that will run the portable owner,
not the example values above. The owner uses that account for its bind-mounted
evidence. The image recipe assigns the source and generated dependencies to
the declared account, so Git can verify its own checkout without a global
safe-directory exception. The source destination must not already exist in the
base image and must not overlap its Python or game assets.

The base must provide compatible Linux DF/DFHack assets and shared libraries,
Python 3.11 with the harness dependencies, Git and util-linux `script`. The new
recipe installs nothing. It does not need an older Fort Gym checkout or private
operator in the base. Existing private images may contain such material; do
not redistribute them merely because this new context contains public source.

Bind generated protobuf files to known digests and a compatible native runtime.
A matching file digest proves which bindings were copied, not wire compatibility
with an arbitrary game version. Existing frozen experiment bindings must not be
replaced with newly generated defaults.

## Prepare and check without a Docker engine

Use resolved absolute paths. The new output directory must be outside both the
source checkout and retained binding directory. Its parent must already exist.
Keep it in the owning project's ignored artifacts, not a home-directory root.

```sh
python -m scripts.campaign_keyboard_image prepare \
  --source "$COMMITTED_CHECKOUT" \
  --inputs "$IMAGE_INPUTS" \
  --output "$NEW_IMAGE_CONTEXT"
```

The command exports only the declared commit using local-file Git transport.
It creates an independent shallow repository, with no linked worktree, remote,
alternate object store, user Git hooks or global Git-configuration dependency.
Ignored credentials, game saves and model memory do not enter the new source
export. Tracked links and submodules are rejected instead of following them.
Only the nine declared binding files are copied from their source directory.

`context.json` inventories the exact content and executable bits of all other
context files, including the standalone Git metadata. The preparation command
prints its SHA256. Preserve that digest separately, then recheck the same copy:

```sh
python -m scripts.campaign_keyboard_image check \
  --output "$NEW_IMAGE_CONTEXT" \
  --receipt-sha256 "$CONTEXT_RECEIPT_SHA256"
```

Checking does not require the original source or bindings directory. It rejects
changed files, executable bits, added ignored files and a different receipt.
The receipt's host input paths are excluded from the Docker context by the
generated `.dockerignore`. Do not publish the private context wholesale.

Preparation checks a 1 GiB host free-space floor. This is not a reservation,
an estimate of future build/cache size, a guest-disk measurement or permission
to alter the frozen cohort's storage. A failed preparation leaves its partial
new context for inspection and cannot reuse that directory automatically.

## Building remains an explicit native-setup step

Before building, verify the selected engine, compatible base image, capacity
and execution authority. `prepare` does not verify an image ID: the local tag
must resolve to the declared `base_image` before and after construction. Do not
reuse a mutable tag that someone else is changing, or overwrite an existing
output image tag. Retain both inspections and the build log with the context
receipt; a source-context pass alone cannot substitute for them.

On the selected existing local engine, inspect the base first:

```sh
docker --context "$EXISTING_DOCKER_CONTEXT" image inspect "$BASE_REFERENCE"
```

Verify the exact image ID, Linux architecture, runtime assets and absence of
implicit volumes. Then construct a new local image under a new image tag:

```sh
docker --context "$EXISTING_DOCKER_CONTEXT" build \
  --pull=false --network=none --progress=plain \
  --iidfile "$NEW_IMAGE_ID_FILE" --tag "$NEW_IMAGE_TAG" \
  "$NEW_IMAGE_CONTEXT"
```

The recipe's exec-form Python checks verify the source commit, clean checkout,
readable, owner-executable source game launchers, `script`, binding imports and harness imports.
The launchers need not be executable in place by the selected UID: native
isolation reads them and creates private copies owned by that UID while retaining
their permission bits. For example, a readable `0744` launcher owned by a different
base-image user is valid; a launcher without its owner-execute bit is not. The
recipe neither changes the base files' permissions nor launches the original game.
Each failed prerequisite has a specific error message.
They never invoke a game launcher or run a campaign. The recipe has no download
or package-install commands. `--network=none` applies to build steps, not all
BuildKit metadata resolution; `--pull=false` does not guarantee an offline build.
See [Docker's build documentation](https://docs.docker.com/reference/cli/docker/buildx/build/).
The historical raw-image-ID metadata lookup failure remains a retained failure,
not a reason to silently pull a replacement base.

After the build, inspect the new image and base again. Retain the immutable new
image ID, source/base labels, user, platform and root filesystem layer lineage.
Confirm the base tag still identifies the originally selected image and the new
image's initial layers match that base. Do not report native image acceptance
from the context's unverified `base_image` field or copied labels alone.

Use that actual new image ID, the same source revision and paths, and the
reviewed seccomp selection in the portable owner's runtime-v2 JSON. Keep the
host checkout at the same clean source revision for execution. Actual game
load, binding-wire compatibility, save/continuation and teardown still need
end-to-end verification. Do not substitute this new runtime into a frozen trial.
