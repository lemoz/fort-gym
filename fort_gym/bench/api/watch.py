"""Read-only spectator projection. Never connects website viewers to the game."""

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
    if value.get("type") == "WORKSHOP_JOB":
        from ..env.workshop_job_profile import ITEMS, MAX_QUANTITY

        params = value.get("params")
        if (not isinstance(params, dict) or set(params) != {"item", "quantity"}
                or params["item"] not in ITEMS):
            raise ValueError("Unsupported spectator shortcut")
        return {
            "intent": label(value["intent"], 2000), "keys": [],
            "advance_ticks": integer(value["advance_ticks"], 0, 100000),
            "shortcut": {
                "type": "WORKSHOP_JOB", "item": params["item"],
                "quantity": integer(params["quantity"], 1, MAX_QUANTITY),
            },
        }
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
        shortcut = action.get("shortcut") if isinstance(action, dict) else None
        if isinstance(action, dict) and "shortcut" in action and (
            not isinstance(shortcut, dict) or set(shortcut) != {"type", "item", "quantity"}
            or shortcut["type"] != "WORKSHOP_JOB" or action.get("keys") != []
        ):
            raise ValueError("Invalid live shortcut")
        public_action = (
            None
            if action is None
            else action_projection(
                {
                    "type": "WORKSHOP_JOB" if shortcut is not None else "KEYSTROKE",
                    "intent": action["intent"],
                    "params": (
                        {"item": shortcut["item"], "quantity": shortcut["quantity"]}
                        if shortcut is not None else {"keys": action["keys"]}
                    ),
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
