from __future__ import annotations

import sys
from pathlib import Path

from fort_gym.bench.env.remote_proto import fetch_proto


def test_flatten_protos_uses_basenames(tmp_path: Path) -> None:
    nested = tmp_path / "sources" / "library" / "proto"
    nested.mkdir(parents=True)
    source = nested / "CoreProtocol.proto"
    source.write_text("syntax = \"proto2\";\n", encoding="utf-8")

    flattened = fetch_proto.flatten_protos([source], tmp_path / "flat")

    assert flattened == [tmp_path / "flat" / "CoreProtocol.proto"]
    assert flattened[0].read_text(encoding="utf-8") == "syntax = \"proto2\";\n"


def test_run_protoc_uses_current_python_and_writes_package(tmp_path: Path, monkeypatch) -> None:
    sources = tmp_path / "flat"
    sources.mkdir()
    proto = sources / "CoreProtocol.proto"
    proto.write_text("syntax = \"proto2\";\n", encoding="utf-8")
    output = tmp_path / "generated"
    calls = []

    def fake_check_call(args, cwd):
        calls.append((args, cwd))

    monkeypatch.setattr(fetch_proto.subprocess, "check_call", fake_check_call)

    fetch_proto.run_protoc(sources, [proto], output)

    args, cwd = calls[0]
    assert args[0] == sys.executable
    assert f"--python_out={output}" in args
    assert args[-1] == "CoreProtocol.proto"
    assert cwd == sources
    assert (output / "__init__.py").is_file()
