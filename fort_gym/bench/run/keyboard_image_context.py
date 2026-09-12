"""Prepare a source-bound Docker context without Docker, downloads or game calls."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .keyboard_window_courier import container_path

SCHEMA = "fortgym.keyboard-image-inputs/v1"
CONTEXT_SCHEMA = "fortgym.keyboard-image-context/v1"
PROTOS = frozenset(
    {
        "__init__.py",
        "AdventureControl_pb2.py",
        "BasicApi_pb2.py",
        "Basic_pb2.py",
        "CoreProtocol_pb2.py",
        "DwarfControl_pb2.py",
        "ItemdefInstrument_pb2.py",
        "RemoteFortressReader_pb2.py",
        "ui_sidebar_mode_pb2.py",
    }
)
GENERATED = "fort_gym/bench/env/remote_proto/generated"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(source: Path, *arguments: str) -> str:
    # Neither user Git hooks/config nor a GIT_DIR inherited from the caller may
    # redirect an export. This command can use local file transport only.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_ALLOW_PROTOCOL="file",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(source), *arguments],
        env=environment,
        text=True,
        stderr=subprocess.PIPE,
        timeout=120,
    ).strip()


def resolved(path: Path) -> Path:
    if not path.is_absolute() or path != path.resolve():
        raise ValueError("Image input paths must be resolved absolute paths")
    return path


def validate_inputs(value: dict) -> dict:
    fields = {
        "schema_version",
        "source_revision",
        "base_image",
        "base_reference",
        "project_directory",
        "python_executable",
        "runtime_directory",
        "bindings_source",
        "bindings_sha256",
        "uid",
        "gid",
    }
    if set(value) != fields or value.get("schema_version") != SCHEMA:
        raise ValueError("Image input fields differ")
    for key, pattern in (
        ("source_revision", r"[a-f0-9]{40}"),
        ("base_image", r"sha256:[a-f0-9]{64}"),
        ("base_reference", r"[a-z0-9][a-z0-9._/-]*:[a-z0-9][a-z0-9._-]*"),
    ):
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise ValueError("Image needs an exact source, image ID and literal local tag")
    for key in ("project_directory", "python_executable", "runtime_directory"):
        container_path(value[key])
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value[key]):
            raise ValueError("Use literal container paths without Dockerfile substitutions")
    project = Path(value["project_directory"])
    for key in ("python_executable", "runtime_directory"):
        path = Path(value[key])
        if path == project or project in path.parents or path in project.parents:
            raise ValueError("New source must not overlap base runtime assets")
    for key in ("uid", "gid"):
        if type(value[key]) is not int or not 1 <= value[key] <= 2147483647:
            raise ValueError("The image needs explicit unprivileged numeric UID and GID")
    hashes = value["bindings_sha256"]
    if (
        not isinstance(hashes, dict)
        or set(hashes) != PROTOS
        or any(
            not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            for digest in hashes.values()
        )
    ):
        raise ValueError("Declare all nine generated-binding file digests")
    if not isinstance(value["bindings_source"], str):
        raise ValueError("Bindings need a resolved source directory")
    bindings = resolved(Path(value["bindings_source"]))
    if not bindings.is_dir():
        raise ValueError("Bindings source is missing")
    for name, expected in hashes.items():
        path = bindings / name
        if path.is_symlink() or not path.is_file() or sha256(path) != expected:
            raise ValueError("Generated bindings differ from their declared bytes")
    return value


def verify_source(source: Path, revision: str) -> str:
    resolved(source)
    if git(source, "rev-parse", "HEAD") != revision or git(
        source, "status", "--porcelain", "--untracked-files=all"
    ):
        raise ValueError("Image packaging needs its exact clean committed source")
    if git(source, "rev-parse", "--show-toplevel") != str(source):
        raise ValueError("Source must be the checkout root")
    for row in git(source, "ls-tree", "-r", revision).splitlines():
        if row.split(" ", 1)[0] not in ("100644", "100755"):
            raise ValueError("Image source must not contain submodules or tracked links")
    return git(source, "rev-parse", "HEAD^{tree}")


def dockerfile(config: dict) -> str:
    project, python = config["project_directory"], config["python_executable"]
    owner = f"{config['uid']}:{config['gid']}"
    # Exec-form RUN does not run the game or import host provider credentials.
    probe = (
        "import os,shutil,stat,subprocess; from pathlib import Path; "
        f"assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=={config['source_revision']!r}, 'Source revision differs'; "
        "assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=all']), 'Source checkout is dirty'; "
        f"launchers=[Path({config['runtime_directory']!r})/name for name in ('df','dfhack','dfhack-run')]; "
        # Native isolation reads source assets, then copy2 creates new files owned
        # by the selected UID. A retained source df may be mode 0744 under another
        # UID: requiring source X_OK rejects a valid owner-executable owned copy.
        "invalid=[str(path) for path in launchers if not path.is_file() or not os.access(path,os.R_OK) or not path.stat().st_mode & stat.S_IXUSR]; "
        "assert not invalid, 'Runtime source launchers must be readable and owner-executable: '+','.join(invalid); "
        "assert shutil.which('script'), 'Missing util-linux script'; "
        "from fort_gym.bench.env.remote_proto import ensure_proto_modules; "
        "assert set(ensure_proto_modules())=={'core','fortress'}, 'Required protocol modules are unavailable'; "
        "from scripts.campaign_keyboard_trial import run_trial; "
        "from scripts.campaign_keyboard_native import run_window"
    )
    return "\n".join(
        [
            f"FROM {config['base_reference']}",
            "RUN "
            + json.dumps(
                [
                    python,
                    "-c",
                    f"from pathlib import Path; assert not Path({project!r}).exists(), 'Source destination already exists'",
                ]
            ),
            # A new source location avoids overwriting a base image's retained repo.
            f"COPY --chown={owner} source/ {project}/",
            f"COPY --chown={owner} bindings/ {project}/{GENERATED}/",
            f"USER {owner}",
            f"WORKDIR {project}",
            "ENV FORT_GYM_DISABLE_DOTENV=1 PYTHONDONTWRITEBYTECODE=1 DF_PROTO_ENABLED=1",
            "RUN " + json.dumps([python, "-c", probe]),
            "LABEL org.fortgym.source=" + json.dumps(config["source_revision"]),
            "LABEL org.fortgym.base-image=" + json.dumps(config["base_image"]),
            "ENTRYPOINT " + json.dumps([python]),
            'CMD ["-m", "scripts.campaign_keyboard_native", "--help"]',
            "",
        ]
    )


def inventory(directory: Path) -> dict:
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("Image context contains a link or special file")
        if path.is_file() and path != directory / "context.json":
            files[path.relative_to(directory).as_posix()] = {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "executable": bool(path.stat().st_mode & 0o111),
            }
    return files


def prepare_context(source: Path, inputs: dict, output: Path) -> dict:
    config = validate_inputs(inputs)
    tree = verify_source(source, config["source_revision"])
    resolved(output)
    bindings = Path(config["bindings_source"])
    metadata = Path(git(source, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    if (
        output.exists()
        or not output.parent.is_dir()
        or source == output
        or source in output.parents
        or bindings == output
        or bindings in output.parents
        or output in source.parents
        or output in bindings.parents
        or output == metadata
        or metadata in output.parents
    ):
        raise ValueError(
            "Use a new context outside source, Git metadata and retained binding inputs"
        )
    if shutil.disk_usage(output.parent).free < 1073741824:
        raise ValueError("Image context filesystem is below the 1 GiB floor")
    output.mkdir(mode=0o700)
    exported = output / "source"
    exported.mkdir(mode=0o700)
    git(exported, "init", "--quiet", "--template=")
    git(exported, "config", "core.logAllRefUpdates", "false")
    git(
        exported,
        "fetch",
        "--depth=1",
        "--no-tags",
        "--no-write-fetch-head",
        source.as_uri(),
        config["source_revision"],
    )
    git(exported, "checkout", "--quiet", "--detach", config["source_revision"])
    # Generated runtime dependencies are explicit, separately hashed image
    # inputs. They do not change the committed source identity.
    info = exported / ".git/info"
    info.mkdir(exist_ok=True)
    (info / "exclude").write_text("/" + GENERATED + "/\n")
    copied = output / "bindings"
    copied.mkdir(mode=0o700)
    for name in sorted(PROTOS):
        shutil.copyfile(bindings / name, copied / name)
        if sha256(copied / name) != config["bindings_sha256"][name]:
            raise ValueError("Binding source changed during context preparation")
    if verify_source(exported, config["source_revision"]) != tree:
        raise ValueError("Exported source tree differs")
    verify_source(source, config["source_revision"])
    (output / "Dockerfile").write_text(dockerfile(config))
    (output / ".dockerignore").write_text(
        "*\n!Dockerfile\n!source/\n!source/**\n!bindings/\n!bindings/**\n"
    )
    receipt = {
        "schema_version": CONTEXT_SCHEMA,
        "inputs": config,
        "source_tree": tree,
        "files": inventory(output),
        "docker_contacted": False,
        "base_image_verified": False,
        "image_built": False,
        "native_game_verified": False,
    }
    (output / "context.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return check_context(output, expected_sha256=sha256(output / "context.json"))


def check_context(output: Path, *, expected_sha256: str | None = None) -> dict:
    resolved(output)
    path = output / "context.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Context receipt must be a regular file")
    if expected_sha256 is not None and (
        not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or sha256(path) != expected_sha256
    ):
        raise ValueError("Image context receipt digest differs")
    value = json.loads(path.read_text())
    if value.get("schema_version") != CONTEXT_SCHEMA or value.get("files") != inventory(output):
        raise ValueError("Prepared image context bytes changed")
    # Recheck copied inputs; the originating source machine is not required.
    config = {**value["inputs"], "bindings_source": str(output / "bindings")}
    validate_inputs(config)
    if (
        verify_source(output / "source", config["source_revision"]) != value["source_tree"]
        or (output / "Dockerfile").read_text() != dockerfile(config)
        or (output / "source/.git").is_file()
        or git(output / "source", "remote")
        or (output / "source/.git/objects/info/alternates").exists()
    ):
        raise ValueError("Prepared source is not a standalone exact checkout")
    return value
