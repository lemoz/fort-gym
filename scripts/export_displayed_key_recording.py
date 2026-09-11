"""Export a saved fresh displayed-key trial with a pinned read-only observer.

This is a publication tool, not a native acceptance verifier. It requires the
original successful terminal audit and checks its source bindings again.
"""

import argparse
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

OBSERVER_REVISION = "2778519991899ee3360db1caf6daec29721bbc4a"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(attempt: Path, observer: Path, audit_sha: str, identity: str) -> dict[str, Any]:
    audit_path = attempt / "terminal-review.json"
    if sha(audit_path) != audit_sha:
        raise ValueError("Audit digest differs")
    audit = read(audit_path)
    if not (
        audit["schema_version"] == "fortgym.private-binding-trial-terminal-review/v1"
        and audit["passed"] is True
        and audit["status"] == "completed"
        and audit["native_cleanup_verified"] is True
        and audit["vm_teardown_verified"] is True
        and audit["human_gameplay_rescue"] is False
    ):
        raise ValueError("A saved, reviewed and torn-down fresh trial is required")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=observer, text=True
    ).strip()
    if revision != OBSERVER_REVISION or subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=observer
    ):
        raise ValueError("Observer source is not clean and pinned")
    # Load only the frozen, stdlib-only projection module. No game/provider imports.
    spec = importlib.util.spec_from_file_location(
        "frozen_watch", observer / "fort_gym/bench/api/watch.py"
    )
    assert spec is not None and spec.loader is not None
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    trace_path = attempt / "evidence/astra/segment-0/checkpoint/trace.jsonl"
    suffix = "/" + trace_path.relative_to(attempt).as_posix()
    expected = [value for key, value in audit["sources"].items() if key.endswith(suffix)]
    if expected != [sha(trace_path)]:
        raise ValueError("Saved trace differs from audit")
    rows = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    entries = sorted(
        (read(path)["decision_index"], path.parent) for path in attempt.glob("model/*/summary.json")
    )
    if (
        len(rows) != audit["responses"]
        or len(entries) != len(rows)
        or [index for index, _ in entries] != list(range(len(rows)))
        or [row["step"] for row in rows] != list(range(len(rows)))
        or len(audit["receipt_reviews"]) != len(rows)
    ):
        raise ValueError("Fresh saved boundary and receipt coverage differ")
    frames = []
    for (index, folder), row, receipt in zip(entries, rows, audit["receipt_reviews"], strict=True):
        request, response, summary = [
            read(folder / (name + ".json")) for name in ("request", "response", "summary")
        ]
        request_sha = hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest()
        action = response["result"].get("action")
        if (
            request_sha != receipt["request_sha256"]
            or request_sha != response["request_sha256"]
            or receipt["decision_index"] != index
            or request["model"] != audit["model"]
            or request["reasoning_effort"] != audit["reasoning_effort"]
            or summary["request_id"] != request["request_id"]
            or action != row["action"]
        ):
            raise ValueError("Screen, model receipt and native trace differ")
        if action is None:
            raise ValueError("This exporter supports accepted typed receipts only")
        clock, after = row["tick_advance"], row["state_after_advance"]
        frames.append(
            {
                "decision": index + 1,
                "screen": watch.screen_projection(request["screen"]),
                "action": watch.action_projection(action),
                "accepted": row["execute"]["accepted"],
                "before": {"year": clock["start_year"], "tick": clock["start_tick"]},
                "after": {
                    "year": after["year"],
                    "tick": after["year_tick"],
                    "population": after["population"],
                    "ticks_advanced": clock["ticks_advanced"],
                },
            }
        )
    if sum(frame["after"]["ticks_advanced"] for frame in frames) != audit["saved_elapsed_ticks"]:
        raise ValueError("Saved elapsed ticks differ")
    return {
        "schema_version": "fortgym.watch-recording/v1",
        "id": identity,
        "title": audit["model"] + " · matched trial " + str(audit["replicate"]),
        "model": audit["model"],
        "control_profile": audit["control_profile"],
        "first_decision": 1,
        "last_decision": len(frames),
        "saved_through_decision": len(frames),
        "audit_sha256": audit_sha,
        "source_revision": audit["source_revision"],
        "recording_status": "saved",
        "frames": frames,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = export(args.attempt, args.observer, args.audit_sha256, args.id)
    raw = (
        json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()
    with args.output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"frames": len(value["frames"]), "sha256": sha(args.output)}))


if __name__ == "__main__":
    main()
