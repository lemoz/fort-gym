from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fort_gym.bench.env.remote_proto import fetch_proto, runtime_binding_digest


def test_remote_proto_runtime_digest_binds_actual_generated_modules(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "__init__.py").write_text("", encoding="utf-8")
    (generated / "CoreProtocol_pb2.py").write_text("CORE = 1\n", encoding="utf-8")
    fortress = generated / "RemoteFortressReader_pb2.py"
    fortress.write_text("FORTRESS = 1\n", encoding="utf-8")

    first = runtime_binding_digest(generated)
    assert first is not None
    assert len(first) == 64
    assert runtime_binding_digest(generated) == first

    fortress.write_text("FORTRESS = 2\n", encoding="utf-8")
    assert runtime_binding_digest(generated) != first

    fortress.unlink()
    assert runtime_binding_digest(generated) is None


def test_generate_bindings_rejects_unpinned_version() -> None:
    with pytest.raises(ValueError, match="must remain pinned"):
        fetch_proto.generate_bindings("different-version")


def test_flatten_protos_uses_basenames(tmp_path: Path) -> None:
    nested = tmp_path / "sources" / "library" / "proto"
    nested.mkdir(parents=True)
    source = nested / "CoreProtocol.proto"
    source.write_text('syntax = "proto2";\n', encoding="utf-8")

    flattened = fetch_proto.flatten_protos([source], tmp_path / "flat")

    assert flattened == [tmp_path / "flat" / "CoreProtocol.proto"]
    assert flattened[0].read_text(encoding="utf-8") == 'syntax = "proto2";\n'


def test_run_protoc_uses_current_python_and_writes_package(
    tmp_path: Path, monkeypatch
) -> None:
    sources = tmp_path / "flat"
    sources.mkdir()
    proto = sources / "CoreProtocol.proto"
    proto.write_text('syntax = "proto2";\n', encoding="utf-8")
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
