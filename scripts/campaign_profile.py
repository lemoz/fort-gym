"""Read one retained campaign segment into a source-hashed performance profile.

No game process, provider call, source mutation, or automatic publication occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from fort_gym.bench.eval.campaign_profile import campaign_profile


def report_segment(root: Path) -> dict:
    segment_path, runtime_path = root / "campaign-segment.json", root / "result.json"
    sources = {}

    def read(path: Path) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Campaign profile inputs must be regular files")
        data = path.read_bytes()
        sources[str(path.relative_to(root))] = hashlib.sha256(data).hexdigest()
        return data

    segment = json.loads(read(segment_path))
    runtime = json.loads(read(runtime_path))
    if (
        not isinstance(segment, dict)
        or not isinstance(runtime, dict)
        or not isinstance(segment.get("configuration"), dict)
        or not isinstance(segment.get("code_revision"), str)
        or re.fullmatch(r"[a-f0-9]{40}", segment["code_revision"]) is None
        or any(
            not isinstance(segment.get(key), str) or not segment[key]
            for key in ("segment_id", "model", "condition_id")
        )
        or segment.get("schema_version") != "fortgym.campaign-segment/v1"
        or runtime.get("schema_version") != "fortgym.isolated-experiment-runtime/v1"
        or runtime.get("code_revision") != segment.get("code_revision")
        or not isinstance(segment.get("campaign_id"), str)
        or not segment["campaign_id"]
    ):
        raise ValueError("Campaign segment and isolated runtime identity do not match")
    trace_path = root / "campaign/trace.jsonl"
    rows = []
    if trace_path.exists():
        rows = [json.loads(line) for line in read(trace_path).splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("Campaign trace rows must be objects")
    status = segment.get("status")
    report = campaign_profile(
        rows,
        campaign_id=segment["campaign_id"],
        status=status if isinstance(status, str) else "unknown",
        usage=segment.get("usage"),
        initial_state=segment.get("native_start"),
        terminal_state=segment.get("native_final"),
    )
    report.update(
        segment_id=segment["segment_id"],
        model=segment["model"],
        condition_id=segment["condition_id"],
        configuration_sha256=hashlib.sha256(
            json.dumps(segment["configuration"], sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        code_revision=segment["code_revision"],
        runtime={
            key: runtime.get(key) if type(runtime.get(key)) is bool else None
            for key in ("native_load_verified", "cleanup_verified")
        },
        new_checkpoint_verified=segment.get("new_checkpoint_verified") is True,
        comparison_rankings_available=False,
        source_sha256=sources,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(report_segment(args.artifact_directory), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
