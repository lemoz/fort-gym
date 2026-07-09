#!/usr/bin/env python3
"""Evaluate the ratified G7 gate from durable trace and summary artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from fort_gym.bench.eval.gates import PASS, evaluate_g7
from fort_gym.bench.eval.summary import summarize


def _load_trace(path: Path) -> list[Dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    summary = (
        json.loads(args.summary.read_text(encoding="utf-8"))
        if args.summary
        else summarize(args.trace).model_dump()
    )
    result = evaluate_g7(_load_trace(args.trace), summary)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if args.require_pass and result["status"] != PASS else 0


if __name__ == "__main__":
    raise SystemExit(main())
