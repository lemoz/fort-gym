"""Export a minimal public screen/action replay from explicitly selected native evidence."""

import argparse
import hashlib
import json
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api.watch import (
    action_projection,
    receipt_action,
    screen_projection,
)


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def export(
    attempt: Path, audit_path: Path, expected_sha: str, *, identity: str, title: str
) -> dict:
    audit_bytes = audit_path.read_bytes()
    if hashlib.sha256(audit_bytes).hexdigest() != expected_sha:
        raise ValueError("Audit digest differs")
    audit = json.loads(audit_bytes)
    failure = audit.get("failure_classification_verified") is True
    if not (audit.get("passed") is True or failure):
        raise ValueError("A completed review is required")
    first = audit["first_step"]
    saved = (
        audit["last_saved_responses"]
        if failure
        else first + len(audit["receipt_reviews"])
    )
    trace_path = max(
        attempt.glob(
            "evidence/*/segment-*/"
            + ("loop" if failure else "checkpoint")
            + "/trace.jsonl"
        ),
        key=lambda path: int(path.parts[-3].split("-")[-1]),
    )
    trace_bytes = trace_path.read_bytes()
    relative = trace_path.relative_to(attempt).as_posix()
    expected_traces = [
        sha
        for name, sha in audit["sources"].items()
        if name == relative or name.endswith("/" + relative)
    ]
    if expected_traces != [hashlib.sha256(trace_bytes).hexdigest()]:
        raise ValueError("Recorded trace differs from the reviewed source")
    rows = [json.loads(line) for line in trace_bytes.splitlines() if line.strip()]
    by_step = {row["step"]: row for row in rows}
    entries = [
        (read(path)["decision_index"], path.parent)
        for path in attempt.glob("model/*/summary.json")
    ]
    entries.sort()
    if [index for index, _ in entries] != list(range(len(entries))):
        raise ValueError("Recording receipts must be consecutive")
    frames = []
    for index, folder in entries:
        request, response, summary = [
            read(folder / (name + ".json"))
            for name in ("request", "response", "summary")
        ]
        row = by_step[first + index]
        model_action = receipt_action(request, response["result"])
        receipt = audit["receipt_reviews"][index]
        if (
            response["request_sha256"] != digest(request)
            or receipt["request_sha256"] != digest(request)
            or receipt["decision_index"] != index
            or summary["request_id"] != request["request_id"]
            or model_action != row["action"]
        ):
            raise ValueError("Recorded screen, receipt and action do not match")
        clock = row["tick_advance"]
        after = row["state_after_advance"]
        frames.append(
            {
                "decision": first + index + 1,
                "screen": screen_projection(request["screen"]),
                "action": action_projection(row["action"]),
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
    if len(frames) != len(audit["receipt_reviews"]):
        raise ValueError("Recording does not cover the reviewed receipts")
    return {
        "schema_version": "fortgym.watch-recording/v1",
        "id": identity,
        "title": title,
        "model": request["model"],
        "control_profile": request["control_profile"],
        "first_decision": first + 1,
        "last_decision": frames[-1]["decision"],
        "saved_through_decision": saved,
        "audit_sha256": expected_sha,
        "source_revision": audit["source_revision"],
        "recording_status": "checkpoint_failure" if failure else "saved",
        "frames": frames,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    # stdout permits the caller to choose a reviewed publication destination.
    print(
        json.dumps(
            export(
                args.attempt,
                args.audit,
                args.audit_sha256,
                identity=args.id,
                title=args.title,
            ),
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
