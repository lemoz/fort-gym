#!/usr/bin/env python3
"""Summarize one provider-free M1a run without altering raw evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    summaries = sorted(args.artifacts.rglob("summary.json"))
    traces = sorted(args.artifacts.rglob("trace.jsonl"))
    if len(summaries) != 1 or len(traces) != 1:
        raise SystemExit(
            f"expected one summary and trace under {args.artifacts}; "
            f"found {len(summaries)} summaries and {len(traces)} traces"
        )

    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    tick_count = 0
    tick_ms = 0
    steps = 0
    action_hashes: list[str] = []
    with traces[0].open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            steps += 1
            tick = row.get("tick_advance") or {}
            tick_count += int(tick.get("ticks_advanced") or 0)
            tick_ms += int(tick.get("elapsed_ms") or 0)
            encoded = json.dumps(
                row.get("action"), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            action_hashes.append(hashlib.sha256(encoded).hexdigest())

    usage = summary.get("usage") or {}
    result = {
        "run_id": summary.get("run_id"),
        "model": summary.get("model"),
        "steps": steps,
        "ticks_advanced": tick_count,
        "tick_elapsed_ms": tick_ms,
        "ticks_per_second": (tick_count * 1000 / tick_ms) if tick_ms else None,
        "provider_calls": usage.get("calls"),
        "provider_cost_usd": usage.get("cost_usd"),
        "action_sequence_sha256": hashlib.sha256(
            "\n".join(action_hashes).encode("ascii")
        ).hexdigest(),
        "summary_sha256": sha256(summaries[0]),
        "trace_sha256": sha256(traces[0]),
        "summary_path": str(summaries[0]),
        "trace_path": str(traces[0]),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

