"""Use real local Git exports, but no Docker engine, game or model."""

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from fort_gym.bench.run import keyboard_image_context as image


def commit(source):
    image.git(source, "add", ".")
    image.git(
        source,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Fixture",
    )
    return image.git(source, "rev-parse", "HEAD")


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    image.git(source, "init", "--quiet", "--template=")
    (source / ".gitignore").write_text("private/\n.env\n")
    (source / "public.py").write_text("print('public source')\n")
    (source / "executable.sh").write_text("#!/bin/sh\nexit 0\n")
    (source / "executable.sh").chmod(0o755)
    revision = commit(source)
    private = source / "private"
    private.mkdir()
    (private / "memory.json").write_text('{"private": "not a build input"}')
    (source / ".env").write_text("PRIVATE_TEST_SENTINEL=do-not-copy\n")
    bindings = tmp_path / "bindings"
    bindings.mkdir()
    for name in image.PROTOS:
        (bindings / name).write_text("# Synthetic fixture, not native bindings: " + name + "\n")
    config = {
        "schema_version": image.SCHEMA,
        "source_revision": revision,
        "base_image": "sha256:" + "a" * 64,
        "base_reference": "fixture-game:local-v1",
        "project_directory": "/workspace/fort-gym",
        "python_executable": "/venv/bin/python",
        "runtime_directory": "/opt/df",
        "uid": 501,
        "gid": 20,
        "bindings_source": str(bindings),
        "bindings_sha256": {name: image.sha256(bindings / name) for name in image.PROTOS},
    }
    return source, config, tmp_path / "image-context"


def test_real_export_is_exact_independent_and_excludes_private_inputs(inputs):
    source, config, output = inputs
    result = image.prepare_context(source, config, output)
    receipt_sha = image.sha256(output / "context.json")
    exported = output / "source"
    assert image.git(exported, "rev-parse", "HEAD") == config["source_revision"]
    assert image.git(exported, "rev-list", "--count", "HEAD") == "1"
    assert not image.git(exported, "remote")
    assert not (exported / ".git/objects/info/alternates").exists()
    assert not (exported / "private").exists() and not (exported / ".env").exists()
    assert (exported / "executable.sh").stat().st_mode & 0o111
    assert set(path.name for path in (output / "bindings").iterdir()) == image.PROTOS
    assert result["files"]["Dockerfile"]["sha256"] == image.sha256(output / "Dockerfile")
    assert result["docker_contacted"] is result["image_built"] is False
    source.rename(source.with_name("retained-original"))
    Path(config["bindings_source"]).rename(output.parent / "retained-bindings")
    assert image.check_context(output, expected_sha256=receipt_sha) == result
    assert image.sha256(output / "context.json") == receipt_sha


@pytest.mark.parametrize(
    "relative",
    [
        "source/public.py",
        "bindings/Basic_pb2.py",
        "Dockerfile",
        "source/.git/config",
        "source/.env",
    ],
)
def test_context_rejects_changed_files_or_added_ignored_private_files(inputs, relative):
    source, config, output = inputs
    image.prepare_context(source, config, output)
    (output / relative).write_text("unexpected change\n")
    with pytest.raises(ValueError, match="bytes changed"):
        image.check_context(output)


def test_context_rejects_receipt_rebinding_even_if_the_receipt_is_self_consistent(
    inputs,
):
    source, config, output = inputs
    image.prepare_context(source, config, output)
    receipt = output / "context.json"
    original_sha = image.sha256(receipt)
    value = json.loads(receipt.read_text())
    value["inputs"]["base_image"] = "sha256:" + "b" * 64
    receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="receipt digest"):
        image.check_context(output, expected_sha256=original_sha)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_revision", "main"),
        ("base_image", "game:latest"),
        ("base_reference", "game:tag\nRUN false"),
        ("base_reference", "game"),
        ("project_directory", "/opt/df/project"),
        ("project_directory", "/opt"),
        ("runtime_directory", "/opt/../df"),
        ("python_executable", "/venv/$PYTHON"),
        ("uid", 0),
        ("uid", True),
        ("gid", -1),
        ("bindings_sha256", {}),
    ],
)
def test_ambiguous_inputs_are_rejected_before_output_creation(inputs, field, value):
    source, config, output = inputs
    with pytest.raises(ValueError):
        image.prepare_context(source, {**config, field: value}, output)
    assert not output.exists()


def test_dirty_or_different_source_cannot_be_declared_as_the_original_commit(inputs):
    source, config, output = inputs
    (source / "public.py").write_text("changed source\n")
    with pytest.raises(ValueError, match="clean committed"):
        image.prepare_context(source, config, output)
    commit(source)
    with pytest.raises(ValueError, match="clean committed"):
        image.prepare_context(source, config, output)
    assert not output.exists()


def test_tracked_links_are_not_followed_into_context(inputs):
    source, config, output = inputs
    (source / "link").symlink_to(source / ".env")
    config["source_revision"] = commit(source)
    with pytest.raises(ValueError, match="tracked links"):
        image.prepare_context(source, config, output)
    assert not output.exists()


def test_no_destination_reuse_and_no_writes_into_source_or_bindings(inputs):
    source, config, output = inputs
    image.prepare_context(source, config, output)
    with pytest.raises(ValueError, match="new context"):
        image.prepare_context(source, config, output)
    for path in (source / "private/new", Path(config["bindings_source"]) / "new"):
        with pytest.raises(ValueError, match="new context"):
            image.prepare_context(source, config, path)
        assert not path.exists()


def test_worktree_export_cannot_write_into_its_shared_git_metadata(inputs):
    source, config, _ = inputs
    worktree = source.parent / "linked-worktree"
    image.git(source, "worktree", "add", "--detach", str(worktree), config["source_revision"])
    forbidden = source / ".git/new-context"
    with pytest.raises(ValueError, match="Git metadata"):
        image.prepare_context(worktree, config, forbidden)
    assert not forbidden.exists()


def test_changed_binding_or_host_capacity_prevents_export(inputs, monkeypatch):
    source, config, output = inputs
    monkeypatch.setattr(image.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024))
    with pytest.raises(ValueError, match="floor"):
        image.prepare_context(source, config, output)
    Path(config["bindings_source"], "Basic_pb2.py").write_text("different")
    with pytest.raises(ValueError, match="bindings differ"):
        image.prepare_context(source, config, output)
    assert not output.exists()


def test_image_recipe_has_no_downloads_game_launch_or_private_operator_import(inputs):
    _, config, _ = inputs
    recipe = image.dockerfile(config)
    assert recipe.startswith("FROM fixture-game:local-v1\n")
    assert "COPY --chown=501:20 source/ /workspace/fort-gym/" in recipe
    assert "USER 501:20" in recipe
    assert "DF_PROTO_ENABLED=1" in recipe
    runs = [json.loads(line[4:]) for line in recipe.splitlines() if line.startswith("RUN ")]
    assert len(runs) == 2 and all(row[:2] == ["/venv/bin/python", "-c"] for row in runs)
    assert "assert not Path" in runs[0][2]
    assert "run_window" in runs[1][2] and "run_window(" not in runs[1][2]
    assert all(
        word not in recipe
        for word in ("curl ", "apt-get", "pip install", "local_owner", "source.bundle")
    )


def execute_recipe_probe(inputs, tmp_path, monkeypatch, *, launcher_mode=0o744):
    """Model source launchers owned by another UID but readable for owned copies."""
    import os
    from fort_gym.bench.env import remote_proto

    _, config, _ = inputs
    runtime = tmp_path / "native-assets"
    runtime.mkdir()
    for name in ("df", "dfhack", "dfhack-run"):
        path = runtime / name
        path.write_text("# Synthetic launcher; not executed\n")
        path.chmod(launcher_mode)
    recipe = image.dockerfile({**config, "runtime_directory": str(runtime)})
    probe = [json.loads(row[4:])[2] for row in recipe.splitlines() if row.startswith("RUN ")][1]
    monkeypatch.setattr(
        image.subprocess, "check_output",
        lambda command, **kwargs: config["source_revision"] + "\n" if command[1] == "rev-parse" else b"",
    )
    monkeypatch.setattr(image.shutil, "which", lambda name: "/usr/bin/script")
    monkeypatch.setattr(remote_proto, "ensure_proto_modules", lambda: {"core": object(), "fortress": object()})
    # The selected UID cannot execute these source files in place. prepare_runtime
    # reads them and copy2 creates owner-executable files owned by that selected UID.
    monkeypatch.setattr(os, "access", lambda path, mode: mode == os.R_OK and Path(path).is_file())
    exec(compile(probe, "<image-build-probe>", "exec"), {})


def test_image_probe_accepts_readable_owner_executable_source(inputs, tmp_path, monkeypatch):
    execute_recipe_probe(inputs, tmp_path, monkeypatch)


def test_image_probe_rejects_launcher_without_owner_execute(inputs, tmp_path, monkeypatch):
    with pytest.raises(AssertionError, match="owner-executable"):
        execute_recipe_probe(inputs, tmp_path, monkeypatch, launcher_mode=0o644)


def test_cli_exercises_prepare_and_digest_bound_standalone_check(inputs, monkeypatch, capsys):
    from scripts.campaign_keyboard_image import main

    source, config, output = inputs
    config_file = output.parent / "inputs.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "image",
            "prepare",
            "--source",
            str(source),
            "--inputs",
            str(config_file),
            "--output",
            str(output),
        ],
    )
    main()
    prepared = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "image",
            "check",
            "--output",
            str(output),
            "--receipt-sha256",
            prepared["context_receipt_sha256"],
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out) == prepared
