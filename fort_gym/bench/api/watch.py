"""Read-only spectator projection. Never connects website viewers to the game."""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

SCHEMA = "fortgym.watch-live/v1"
FILENAME = "watch-active.json"
MAX_BYTES = 2_000_000
FRESH_SECONDS = 30


def integer(value: Any, low: int = 0, high: int = 2**53 - 1) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid spectator number")
    return value


def label(value: Any, limit: int = 160) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("Invalid spectator text")
    return value


def screen_projection(value: dict) -> dict:
    width, height = integer(value["width"], 1, 240), integer(value["height"], 1, 100)
    if value["tile_order"] != "column_major" or len(value["tiles"]) != width * height:
        raise ValueError("Invalid screen geometry")
    runs: list[list[int]] = []
    for tile in value["tiles"]:
        if not isinstance(tile, list) or len(tile) != 3:
            raise ValueError("Invalid screen tile")
        cell = [
            integer(tile[0], 0, 255),
            integer(tile[1], 0, 15),
            integer(tile[2], 0, 15),
        ]
        if runs and runs[-1][1:] == cell:
            runs[-1][0] += 1
        else:
            runs.append([1, *cell])
    return {
        "width": width,
        "height": height,
        "tile_order": "column_major",
        "runs": runs,
    }


def validate_screen(value: dict) -> dict:
    width, height = integer(value["width"], 1, 240), integer(value["height"], 1, 100)
    if value["tile_order"] != "column_major" or len(value["runs"]) > width * height:
        raise ValueError("Invalid compressed screen")
    runs: list[list[int]] = []
    for run in value["runs"]:
        if not isinstance(run, list) or len(run) != 4:
            raise ValueError("Invalid compressed tile")
        runs.append(
            [
                integer(run[0], 1, width * height),
                integer(run[1], 0, 255),
                integer(run[2], 0, 15),
                integer(run[3], 0, 15),
            ]
        )
    if sum(run[0] for run in runs) != width * height:
        raise ValueError("Incomplete screen")
    return {
        "width": width,
        "height": height,
        "tile_order": "column_major",
        "runs": runs,
    }


def action_projection(value: dict | None) -> dict | None:
    if value is None:
        return None
    keys = value["params"]["keys"]
    if (
        value.get("type") != "KEYSTROKE"
        or not isinstance(keys, list)
        or len(keys) > 128
    ):
        raise ValueError("Unsupported spectator action")
    return {
        "intent": label(value["intent"], 2000),
        "keys": [label(key, 100) for key in keys],
        "advance_ticks": integer(value["advance_ticks"], 0, 100000),
    }


def receipt_action(request: dict, result: dict) -> dict:
    """Recover a rejected choice only through the harness's typed receipt check."""
    if result.get("action") is not None:
        return result["action"]
    from ..agent.keyboard_rejection import rejected_receipt
    from ..env.screen_observation import TEXT_PROFILE, encode_screen

    observed = json.dumps(
        encode_screen(request["screen"], TEXT_PROFILE),
        allow_nan=False,
        sort_keys=True,
        ensure_ascii=False,
    )
    return rejected_receipt(
        result,
        screen_sha256=hashlib.sha256(observed.encode()).hexdigest(),
        max_advance_ticks=request["max_advance_ticks"],
        model=request["model"],
        reasoning_effort=request["reasoning_effort"],
        control_profile=request["control_profile"],
    ).action


def project_live(value: dict, *, now: int) -> dict:
    if (
        value.get("schema_version") != SCHEMA
        or type(value.get("owner_alive")) is not bool
    ):
        raise ValueError("Unsupported spectator feed")
    observed = integer(value["observed_at_unix"], 1, now + 5)
    identity = label(value["run_id"], 100)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", identity):
        raise ValueError("Invalid spectator identity")
    frame = value.get("frame")
    public_frame = None
    if frame is not None:
        status = frame.get("action_status")
        if status not in (
            "chosen_not_execution_verified",
            "rejected",
            "awaiting_response",
        ):
            raise ValueError("Invalid live action status")
        action = frame.get("action")
        if (action is None) != (status == "awaiting_response"):
            raise ValueError("Live action status differs from its payload")
        public_action = (
            None
            if action is None
            else action_projection(
                {
                    "type": "KEYSTROKE",
                    "intent": action["intent"],
                    "params": {"keys": action["keys"]},
                    "advance_ticks": action["advance_ticks"],
                }
            )
        )
        public_frame = {
            "decision": integer(frame["decision"], 1),
            "captured_at_unix": integer(frame["captured_at_unix"], 1, now + 5),
            "screen": validate_screen(frame["screen"]),
            "action": public_action,
            "action_status": status,
        }
    return {
        "schema_version": SCHEMA,
        "status": (
            "stale"
            if now - observed > FRESH_SECONDS
            else "running"
            if value["owner_alive"]
            else "stopped"
        ),
        "run_id": identity,
        "model": label(value["model"], 100),
        "observed_at_unix": observed,
        "fresh_for_seconds": FRESH_SECONDS,
        "frame": public_frame,
    }


def live_status(root: Path | None, *, now: int | None = None) -> dict:
    path = root / FILENAME if root is not None else None
    if path is None or not path.exists() and not path.is_symlink():
        return {"schema_version": SCHEMA, "status": "not_connected"}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Spectator feed must be a bounded regular file")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("Spectator feed is too large")
    return project_live(json.loads(data), now=int(time.time()) if now is None else now)
