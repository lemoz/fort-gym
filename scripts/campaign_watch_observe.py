"""Sanitize native model exchange for the spectator feed; no game or provider calls."""

import json
import os
import tempfile
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api.watch import (
    FILENAME,
    SCHEMA,
    action_projection,
    project_live,
    receipt_action,
    screen_projection,
)


def snapshot(attempt: Path, base: dict, *, alive: bool, now: int) -> dict:
    entries = []
    for path in attempt.glob("model/*/summary.json"):
        summary = json.loads(path.read_text())
        entries.append((summary["decision_index"], path.parent, summary["request_id"]))
    entries.sort()
    if [index for index, _, _ in entries] != list(range(len(entries))):
        raise ValueError("Spectator receipts are not consecutive")
    frame = None
    if entries:
        index, folder, request_id = entries[-1]
        request = json.loads((folder / "request.json").read_text())
        response = json.loads((folder / "response.json").read_text())
        if (
            response["request_sha256"] != digest(request)
            or request["model"] != base["model"]
            or request["request_id"] != request_id
        ):
            raise ValueError("Spectator response does not match its request")
        frame = {
            "decision": base["saved_checkpoint_cursor"] + index + 1,
            "captured_at_unix": int((folder / "request.json").stat().st_mtime),
            "screen": screen_projection(request["screen"]),
            "action": action_projection(receipt_action(request, response["result"])),
            "action_status": "chosen_not_execution_verified"
            if response["result"]["action_grammar_valid"]
            else "rejected",
        }
    value = {
        "schema_version": SCHEMA,
        "owner_alive": alive,
        "observed_at_unix": now,
        "run_id": base["run_id"],
        "model": base["model"],
        "frame": frame,
    }
    public = project_live(value, now=now)
    return {**public, "owner_alive": alive}


def publish(root: Path, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / FILENAME
    if target.is_symlink():
        raise ValueError("Spectator destination cannot be a symlink")
    # Only this replaceable, public derivative is rewritten.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=root, prefix=".watch-", delete=False
    ) as stream:
        json.dump(value, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    temporary.replace(target)
