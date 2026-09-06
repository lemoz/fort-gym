"""Launch a verified temporary local llama.cpp server; caller owns teardown.

No download, global install, daemon, hosted credential or inference is performed.
This launcher currently supports the pinned b10516 macOS arm64 release bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import socket
import subprocess
import tarfile
from pathlib import Path
from typing import IO

from fort_gym.bench.agent.campaign_llama_identity import BUILD, TRANSPORT
from fort_gym.bench.run.campaign_config import load_segment_config
from scripts.campaign_segment import write_result

ARCHIVE_NAME = "llama-b10516-bin-macos-arm64.tar.gz"
ARCHIVE_SHA256 = "ee3324327d621026ae80c24031670e65fa62a0b23a3a027dbe2f65f240affd30"


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stream_digest(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def verify_runtime(runtime: Path) -> Path:
    """Verify the official archive and every installed member before execution."""
    runtime = runtime.resolve(strict=True)
    archive_path = runtime / ARCHIVE_NAME
    if file_digest(archive_path) != ARCHIVE_SHA256:
        raise ValueError("Local llama.cpp archive digest differs from the pinned release")
    with tarfile.open(archive_path) as archive:
        for member in archive:
            relative = Path(member.name).relative_to("llama-b10516")
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Runtime archive member escapes its installation")
            target = runtime / relative
            if member.isdir():
                if not target.is_dir() or target.is_symlink():
                    raise ValueError("Runtime directory differs from the verified archive")
            elif member.issym():
                if not target.is_symlink() or os.readlink(target) != member.linkname:
                    raise ValueError("Runtime symlink differs from the verified archive")
                target.resolve(strict=True).relative_to(runtime)
            else:
                expected = archive.extractfile(member) if member.isfile() else None
                if expected is None or not target.is_file() or target.is_symlink():
                    raise ValueError("Runtime file differs from the verified archive")
                if file_digest(target) != stream_digest(expected):
                    raise ValueError("Runtime file digest differs from the verified archive")
    binary = runtime / "llama-server"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Verified runtime has no executable llama-server")
    return binary


def launch_arguments(config: dict, model: str, binary: Path, weights: Path, port: int) -> list[str]:
    local = config["local_inference"]
    if local["transport"] != TRANSPORT or local["runtime_profile"] != "flash_q8/v1":
        raise ValueError("This launcher requires its pinned llama.cpp Flash/Q8 condition")
    if type(port) is not int or not 1024 <= port <= 65535 or port in {5000, 11434}:
        raise ValueError("Use a dedicated unprivileged loopback model port")
    if weights.name != local["model_files"][model]:
        raise ValueError("Selected model filename differs from the condition")
    return [
        str(binary),
        "--model",
        str(weights),
        "--alias",
        model,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(local["context_tokens"]),
        "--parallel",
        "1",
        "--n-gpu-layers",
        "99",
        "--flash-attn",
        "on",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--offline",
        "--no-context-shift",
        "--no-webui",
        "--no-agent",
        "--no-ui-mcp-proxy",
        "--no-models-autoload",
        "--no-slots",
        "--reasoning-format",
        "deepseek",
        "--cors-origins",
        f"http://127.0.0.1:{port}",
        "--no-cors-credentials",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--launch-receipt", type=Path, required=True)
    args = parser.parse_args()
    config = load_segment_config(args.config, args.model)
    weights = args.model_file.resolve(strict=True)
    binary = verify_runtime(args.runtime_dir)
    arguments = launch_arguments(config, args.model, binary, weights, args.port)
    expected_digest = config["local_inference"]["model_digests"][args.model]
    if not weights.is_file() or file_digest(weights) != expected_digest:
        raise ValueError("Model file digest differs from the declared condition")
    environment = {
        key: os.environ[key]
        for key in ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR")
        if key in os.environ
    }
    version = subprocess.check_output(
        [str(binary), "--version"], env=environment, text=True, stderr=subprocess.STDOUT
    )
    if "build 10516, commit b95502ba9" not in version:
        raise ValueError("Runtime version differs from the pinned build")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    write_result(
        args.launch_receipt,
        {
            "schema_version": "fortgym.local-llama-server-launch/v1",
            "scope": "verified_files_and_launch_declaration_not_successful_start_or_gameplay",
            "condition_id": config["condition_id"],
            "configuration_file_sha256": file_digest(args.config),
            "runtime_archive_sha256": ARCHIVE_SHA256,
            "installed_archive_members_verified": True,
            "binary_sha256": file_digest(binary),
            "expected_build": BUILD,
            "model_file_sha256": expected_digest,
            "model_bytes": weights.stat().st_size,
            "arguments": arguments,
            "inherited_environment_keys": sorted(environment),
            "provider_credentials_and_tool_overrides_not_inherited": True,
        },
    )
    os.chdir(binary.parent)
    os.execve(str(binary), arguments, environment)


if __name__ == "__main__":
    main()
