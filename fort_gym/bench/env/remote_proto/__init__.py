"""Helpers for managing DFHack remote protobuf bindings.

Generated code is expected under ``fort_gym.bench.env.remote_proto.generated`` and is
produced via ``make proto``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

PROTO_VERSION = "52.04-r1"


class ProtoLoadError(RuntimeError):
    """Raised when DFHack protobuf bindings are missing."""


def ensure_proto_modules() -> dict[str, Any]:
    """Attempt to import generated protobuf modules and return them."""

    try:
        core = import_module("fort_gym.bench.env.remote_proto.generated.CoreProtocol_pb2")
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
