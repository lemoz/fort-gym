"""Start a temporary self-hosted server with the declared campaign cache profile.

No application update, daemon installation, model download, or inference. The
caller owns the terminal/process lifetime and verifies teardown. Native model
dispatch still independently checks server version and exact model digest.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import socket
from collections.abc import Mapping
from pathlib import Path

from fort_gym.bench.run.campaign_config import LOCAL_SCHEMA, load_segment_config, read_config
from scripts.campaign_segment import write_result

RUNTIME_PROFILES = {
    "standard_f16/v1": {"OLLAMA_FLASH_ATTENTION": "0", "OLLAMA_KV_CACHE_TYPE": "f16"},
    "flash_q8/v1": {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"},
}


def server_environment(
    config: dict, *, cache: Path, port: int, inherited: Mapping[str, str]
) -> dict[str, str]:
    profile = config["local_inference"].get("runtime_profile", "standard_f16/v1")
    if not isinstance(profile, str) or profile not in RUNTIME_PROFILES:
        raise ValueError("Unsupported local server runtime profile")
    if type(port) is not int or not 1024 <= port <= 65535 or port in {5000, 11434}:
        raise ValueError("Use a dedicated unprivileged loopback model port")
    cache = cache.resolve(strict=True)
    if not cache.is_dir():
        raise ValueError("Use an existing verified model cache directory")
    # Preserve application home, but do not inherit provider credentials, proxies,
    # optional server overrides, or global cache relocation settings.
    return {
        **{
            key: inherited[key]
            for key in ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR")
            if key in inherited
        },
        "OLLAMA_HOST": f"127.0.0.1:{port}",
        "OLLAMA_MODELS": str(cache),
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_MAX_QUEUE": "1",
        "OLLAMA_KEEP_ALIVE": "30s",
        "OLLAMA_NOPRUNE": "1",
        # Version 0.5.11 is the actual pre-cloud boundary; do not rely on this flag.
        "OLLAMA_NO_CLOUD": "1",
        **RUNTIME_PROFILES[profile],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--launch-receipt", type=Path, required=True)
    args = parser.parse_args()
    raw = read_config(args.config)
    config = load_segment_config(args.config, raw["models"][0])
    if config["schema_version"] != LOCAL_SCHEMA:
        raise ValueError("Local server requires a self-hosted campaign condition")
    binary = args.binary.resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Local server binary is not an executable file")
    environment = server_environment(
        config, cache=args.model_cache, port=args.port, inherited=os.environ
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    write_result(
        args.launch_receipt,
        {
            "schema_version": "fortgym.local-server-launch/v1",
            "condition_id": config["condition_id"],
            "configuration_file_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "expected_server_version": config["local_inference"]["server_version"],
            "runtime_profile": config["local_inference"].get("runtime_profile", "standard_f16/v1"),
            "server_environment": {
                key: value for key, value in environment.items() if key.startswith("OLLAMA_")
            },
            "scope": "launch declaration, not proof of successful startup or model execution",
        },
    )
    os.execve(str(binary), [str(binary), "serve"], environment)


if __name__ == "__main__":
    main()
