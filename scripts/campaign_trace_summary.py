"""Read committed campaign progress with bounded memory, on the host only.

Do not execute diagnostic Python processes inside the memory-limited game
container. Use an exported trace or a host-readable evidence mount. This summary
is not checkpoint verification and never reads game controls or calls a model.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

MAX_LINE_BYTES = 2 * 1024 * 1024


def summarize(path: Path, *, starting_step: int = 0) -> dict:
    """Scan the captured file length one record at a time; ignore a partial tail."""
    if type(starting_step) is not int or starting_step < 0:
        raise ValueError("starting_step must be a nonnegative integer")
    count = ticks = offset = 0
    last_step = None
    last_state: dict = {}
    last_losses: list = []
    incomplete = 0
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        while offset < size:
            line = stream.readline(min(MAX_LINE_BYTES + 1, size - offset))
            if not line:
                raise ValueError("Trace was truncated during the read")
            offset += len(line)
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("Trace record exceeds bounded diagnostic limit")
            if not line.endswith(b"\n"):
                incomplete = len(line)
                break
            row = json.loads(line)
            step = row.get("step") if isinstance(row, dict) else None
            if (
                type(step) is not int
                or step < 0
                or (last_step is not None and step != last_step + 1)
            ):
                raise ValueError("Trace steps are not consecutive nonnegative integers")
            last_step = step
            if step < starting_step:
                continue
            receipt = row.get("tick_advance", {})
            advanced = receipt.get("ticks_advanced") if isinstance(receipt, dict) else None
            if type(advanced) is not int or advanced < 0:
                raise ValueError("Trace lacks nonnegative committed ticks")
            state, losses = row.get("state_after_advance", {}), row.get("discontinuities", [])
            if not isinstance(state, dict) or not isinstance(losses, list):
                raise ValueError("Trace state or loss history is malformed")
            count += 1
            ticks += advanced
            last_state, last_losses = state, losses
    return {
        "schema_version": "fortgym.host-trace-progress/v1",
        "starting_step": starting_step,
        "committed_decisions": count,
        "committed_ticks": ticks,
        "trace_next_step": last_step + 1 if last_step is not None else None,
        "last_population": last_state.get("population"),
        "last_recorded_dead": last_state.get("dead"),
        "last_year": last_state.get("year"),
        "last_year_tick": last_state.get("year_tick"),
        "recorded_loss_count": len(last_losses),
        "captured_file_bytes": size,
        "ignored_incomplete_tail_bytes": incomplete,
        "checkpoint_verified": False,
        "game_calls": 0,
        "model_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--starting-step", type=int, default=0)
    args = parser.parse_args()
    if Path("/.dockerenv").exists():
        parser.error("Run diagnostics on the host, not inside a game container")
    print(json.dumps(summarize(args.trace, starting_step=args.starting_step), sort_keys=True))


if __name__ == "__main__":
    main()
