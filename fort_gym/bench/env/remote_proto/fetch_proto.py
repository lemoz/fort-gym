"""Download DFHack protobuf definitions and generate python bindings."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Iterable

import urllib.request

DEFAULT_VERSION = os.environ.get("DFHACK_VERSION", "52.04-r1")
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


def run_protoc(proto_root: Path, sources_dir: Path, proto_paths: Iterable[Path], output_dir: Path) -> None:
    args = [
        "python",
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={sources_dir}",
        f"--proto_path={sources_dir / 'library' / 'proto'}",
        f"--proto_path={sources_dir / 'plugins' / 'remotefortressreader' / 'proto'}",
        f"--python_out={output_dir}",
    ] + [str(p.relative_to(sources_dir)) for p in proto_paths]
    print("Running:", " ".join(args))
    subprocess.check_call(args, cwd=sources_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION, help="DFHack release tag")
    args = parser.parse_args()

    proto_root = Path(__file__).resolve().parent
    sources_dir = proto_root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    files = download_protos(args.version, sources_dir)
    generated = proto_root / "gen"
    generated.mkdir(parents=True, exist_ok=True)
    run_protoc(proto_root, sources_dir, files, generated)
    print("Generated bindings in", generated)


if __name__ == "__main__":  # pragma: no cover - utility entrypoint
    main()
