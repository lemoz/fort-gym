"""Receive one bounded public derivative over authenticated SSH, never game input."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from fort_gym.bench.api.watch import FILENAME, MAX_BYTES, project_live

ROOT = Path(__file__).resolve().parents[1]


def receive(root: Path, raw: bytes, *, run_id: str, now: int) -> dict:
    """Replace only the public relay file; reject stale or conflicting senders."""
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", run_id) or len(raw) > MAX_BYTES:
        raise ValueError("Invalid relay identity or payload size")
    value = json.loads(raw)
    public = project_live(value, now=now)
    if public["run_id"] != run_id or public["status"] == "stale":
        raise ValueError("Relay identity or observation time differs")
    public["owner_alive"] = value["owner_alive"]
    encoded = json.dumps(public, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("Projected relay is too large")
    root = root.resolve(strict=True)
    static = root / "web/static"
    if static.resolve(strict=True) != static:
        raise ValueError("Relay static root cannot traverse a symlink")
    folder = static / "live"
    if folder.is_symlink():
        raise ValueError("Relay directory cannot be a symlink")
    folder.mkdir(mode=0o755, exist_ok=True)
    target = folder / FILENAME
    lock_fd = os.open(folder / ".watch-lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_symlink():
            raise ValueError("Relay destination cannot be a symlink")
        if target.exists():
            if not target.is_file() or target.stat().st_size > MAX_BYTES:
                raise ValueError("Invalid existing relay file")
            old = project_live(json.loads(target.read_bytes()), now=now)
            if old["run_id"] != run_id and old["status"] == "running":
                raise ValueError("Another active spectator owns this relay")
            if old["run_id"] == run_id:
                if public["observed_at_unix"] < old["observed_at_unix"]:
                    raise ValueError("Relay observation regressed")
                if old["frame"] and (
                    not public["frame"] or public["frame"]["decision"] < old["frame"]["decision"]
                ):
                    raise ValueError("Relay decision regressed")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".watch-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o644)
            temporary.replace(target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return {
        "published": True,
        "run_id": run_id,
        "status": public["status"],
        "decision": public["frame"]["decision"] if public["frame"] else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    print(json.dumps(receive(ROOT, raw, run_id=args.run_id, now=int(time.time()))))


if __name__ == "__main__":
    main()
