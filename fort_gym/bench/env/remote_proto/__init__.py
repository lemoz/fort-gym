"""Helpers for managing DFHack remote protobuf bindings.

Generated code is expected under ``fort_gym.bench.env.remote_proto.generated`` and is
produced via ``make proto``.
"""

from __future__ import annotations

import hashlib
from importlib import import_module
import os
import sys
from pathlib import Path
from typing import Any

PROTO_VERSION = "52.04-r1"
REQUIRED_GENERATED_MODULES = frozenset(
    {"CoreProtocol_pb2.py", "RemoteFortressReader_pb2.py"}
)

# Flag to enable/disable proto loading (useful for local Mac dev without protos)
DF_PROTO_ENABLED = os.getenv("DF_PROTO_ENABLED", "0") == "1"


class ProtoLoadError(RuntimeError):
    """Raised when DFHack protobuf bindings are missing."""


def runtime_binding_digest(generated_dir: Path | None = None) -> str | None:
    """Hash the exact generated Python bindings used by live DFHack RPCs."""

    root = generated_dir or (Path(__file__).resolve().parent / "generated")
    if not root.is_dir():
        return None
    paths = sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and path.is_file()
    )
    if not REQUIRED_GENERATED_MODULES <= {path.name for path in paths}:
        return None
    digest = hashlib.sha256()
    digest.update(b"fort-gym.remote-proto-runtime/v1\0")
    digest.update(PROTO_VERSION.encode("utf-8"))
    digest.update(b"\0")
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def ensure_proto_modules() -> dict[str, Any]:
    """Attempt to import generated protobuf modules and return them.

    If DF_PROTO_ENABLED=0 (default), returns empty dict to allow local development
    without DFHack protobuf bindings. The DFHack backend will fail gracefully.

    Set DF_PROTO_ENABLED=1 to enable full proto support (required for DFHack backend).
    """

    if not DF_PROTO_ENABLED:
        # Skip proto loading for local development
        # DFHack backend will fail gracefully if attempted
        return {}

    generated_dir = Path(__file__).resolve().parent / "generated"
    if generated_dir.is_dir():
        path_str = str(generated_dir)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    try:
        core = import_module(
            "fort_gym.bench.env.remote_proto.generated.CoreProtocol_pb2"
        )
        fortress = import_module(
            "fort_gym.bench.env.remote_proto.generated.RemoteFortressReader_pb2"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime guard
        raise ProtoLoadError(
            "Missing DFHack protobuf bindings. Run `make proto` to download and compile protos."
        ) from exc

    modules = {
        "core": core,
        "fortress": fortress,
    }
    return modules
