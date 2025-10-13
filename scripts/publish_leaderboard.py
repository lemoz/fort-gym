"""Generate a lightweight leaderboard JSON from stored run summaries."""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path


ARTIFACT_GLOB = "fort_gym/artifacts/*/summary.json"
OUTPUT_PATH = Path("web/leaderboard.json")


def collect_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary_path in glob.glob(ARTIFACT_GLOB):
        run_dir = os.path.basename(os.path.dirname(summary_path))
        try:
            with open(summary_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "run_id": run_dir,
                "reward_cum": data.get("reward_cum", 0),
                "steps": data.get("steps", 0),
                "total_score": data.get("total_score", 0),
                "model": data.get("model"),
                "backend": data.get("backend"),
            }
        )
    rows.sort(key=lambda row: (row.get("reward_cum", 0), row.get("steps", 0)), reverse=True)
    return rows[:100]


def main() -> None:
    rows = collect_rows()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(rows)} rows")


if __name__ == "__main__":  # pragma: no cover - simple script
    main()
