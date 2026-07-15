"""Download DFHack protobuf definitions and generate python bindings."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import urllib.request

from . import PROTO_VERSION

DEFAULT_VERSION = PROTO_VERSION
REPO_BASE = "https://raw.githubusercontent.com/DFHack/dfhack/{version}/"
CORE_PROTOS = [
    "library/proto/CoreProtocol.proto",
    "library/proto/Basic.proto",
    "library/proto/BasicApi.proto",
]
FORTRESS_PROTOS = [
    "plugins/remotefortressreader/proto/RemoteFortressReader.proto",
    "plugins/remotefortressreader/proto/ItemdefInstrument.proto",
    "plugins/remotefortressreader/proto/DwarfControl.proto",
    "plugins/remotefortressreader/proto/AdventureControl.proto",
    "plugins/remotefortressreader/proto/ui_sidebar_mode.proto",
]


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp:
        dest.write_bytes(resp.read())


def download_protos(version: str, target: Path) -> list[Path]:
    downloaded: list[Path] = []
    base_url = REPO_BASE.format(version=version)
    for rel in CORE_PROTOS + FORTRESS_PROTOS:
        url = base_url + rel
        dest = target / rel
        print(f"Fetching {url}")
        download(url, dest)
        downloaded.append(dest)
    return downloaded


def flatten_protos(proto_paths: Iterable[Path], target: Path) -> list[Path]:
    """Copy downloaded protos into one directory for flat Python module generation."""

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    flattened: list[Path] = []
    for source in proto_paths:
        dest = target / source.name
        shutil.copy2(source, dest)
        flattened.append(dest)
    return flattened


def run_protoc(
    sources_dir: Path, proto_paths: Iterable[Path], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "__init__.py").touch()
    args = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={sources_dir}",
        f"--python_out={output_dir}",
    ] + [p.name for p in proto_paths]
    print("Running:", " ".join(args))
    subprocess.check_call(args, cwd=sources_dir)


def generate_bindings(version: str = DEFAULT_VERSION) -> Path:
    if version != PROTO_VERSION:
        raise ValueError(
            f"DFHack protobuf version must remain pinned to {PROTO_VERSION}, got {version}"
        )
    proto_root = Path(__file__).resolve().parent
    sources_dir = proto_root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    files = download_protos(version, sources_dir)
    flat_sources = flatten_protos(files, proto_root / "_flat_sources")
    generated = proto_root / "generated"
    run_protoc(proto_root / "_flat_sources", flat_sources, generated)
    print("Generated bindings in", generated)
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION, help="DFHack release tag")
    args = parser.parse_args()
    generate_bindings(args.version)


if __name__ == "__main__":  # pragma: no cover - utility entrypoint
    main()
