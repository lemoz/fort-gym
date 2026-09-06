#!/usr/bin/env python3
"""Print a counterfactual v4 and calibration-v5 report for a run trace.

Public summary wrappers are accepted, but compact summaries remain visibly
incomplete rather than having omitted raw fields synthesized.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fort_gym.bench.eval.measurement_replay import replay_measurements


def _records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument(
        "--compact",
        action="store_true",
        help="print only comparison, coverage, gate, and behavior outcomes",
    )
    args = parser.parse_args()
    summary_path = args.summary or args.trace.with_name("summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report = replay_measurements(_records(args.trace), summary)
    if args.compact:
        report = {
            "summary_source": report["summary_source"],
            "comparison_status": report["comparison_status"],
            "comparison_incomplete_reasons": report["comparison_incomplete_reasons"],
            "sensor_coverage": report["sensor_coverage"],
            "counterfactual_g7_v4_status": report["counterfactual_g7_v4"].get("status"),
            "counterfactual_g7_v4_input_complete": report[
                "counterfactual_g7_v4_input_complete"
            ],
            "calibration_g7_v5_status": report["calibration_g7_v5"].get("status"),
            "calibration_gameplay_outcome": report["calibration_g7_v5"].get(
                "gameplay_outcome"
            ),
            "calibration_evaluation_validity": report["calibration_g7_v5"].get(
                "evaluation_validity"
            ),
            "behavior_v2": report["calibration_behavior_v2"],
            "historical_rubric_score": report["historical_rubric_v1"].get(
                "rubric_score"
            ),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
