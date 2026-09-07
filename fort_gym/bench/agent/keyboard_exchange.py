"""Single-use file exchange between an isolated game and a host model transport.

Only declared screen data, model memory, input feedback and decision receipts
cross this boundary. The game needs no network, credentials, or model runtime.
The outer owner transports files; this module never runs Docker or a shell.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from ..env.native_key_catalog import NATIVE_PROFILE
from ..env.screen_observation import TEXT_PROFILE, raw_screen

MAX_BYTES = 2 * 1024 * 1024


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def digest(value: dict) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def publish(path: Path, value: dict) -> None:
    """Atomically publish a complete new file; never overwrite a prior response."""
    data = json_bytes(value)
    if len(data) > MAX_BYTES:
        raise ValueError("Keyboard exchange exceeds its byte limit")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".exchange-") as stream:
        stream.write(data + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
        os.link(stream.name, path)


def read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Keyboard exchange must be a bounded regular file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Keyboard exchange must be an object")
    return value


def validate_request(request: dict) -> None:
    if set(request) != {
        "schema_version",
        "request_id",
        "screen",
        "memory",
        "feedback",
        "control_profile",
        "observation_profile",
        "max_advance_ticks",
    }:
        raise ValueError("Keyboard exchange request fields differ")
    if (
        request["schema_version"] != "fortgym.keyboard-exchange-request/v1"
        or request["control_profile"] != NATIVE_PROFILE
        or request["observation_profile"] != TEXT_PROFILE
        or not isinstance(request["memory"], str)
        or (request["feedback"] is not None and not isinstance(request["feedback"], dict))
        or type(request["max_advance_ticks"]) is not int
        or not 1 <= request["max_advance_ticks"] <= 2500
    ):
        raise ValueError("Keyboard exchange condition is invalid")
    if uuid.UUID(request["request_id"]).hex != request["request_id"]:
        raise ValueError("Keyboard exchange identifier is not canonical")
    raw_screen(request["screen"])


def exchange_decision(
    root: Path,
    screen: dict,
    memory: str,
    feedback: dict | None,
    *,
    max_advance_ticks: int = 2000,
    timeout_seconds: float = 240,
) -> dict:
    if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 600:
        raise ValueError("Invalid exchange deadline")
    identifier = uuid.uuid4().hex
    request = {
        "schema_version": "fortgym.keyboard-exchange-request/v1",
        "request_id": identifier,
        "screen": raw_screen(screen),
        "memory": memory,
        "feedback": feedback,
        "control_profile": NATIVE_PROFILE,
        "observation_profile": TEXT_PROFILE,
        "max_advance_ticks": max_advance_ticks,
    }
    validate_request(request)
    directory = root / identifier
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    publish(directory / "request.json", request)
    deadline = time.monotonic() + timeout_seconds
    response = directory / "response.json"
    while not response.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Keyboard model exchange timed out; outcome is unresolved")
        time.sleep(0.1)
    value = read(response)
    if set(value) != {"request_sha256", "result"} or value["request_sha256"] != digest(request):
        raise ValueError("Keyboard response belongs to a different observation or request")
    if not isinstance(value["result"], dict):
        raise ValueError("Keyboard exchange has no decision receipt")
    return value["result"]
