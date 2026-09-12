"""Export a saved displayed-key trial or own-save window with a pinned observer.

This is a publication tool, not a native acceptance verifier. It requires the
original successful terminal audit and checks its source bindings again.
"""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

OBSERVER_REVISION = "7cd3b96763998abfd99ed623630d658320a27918"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recorded_action(watch: Any, request: dict, result: dict, row: dict) -> dict:
    """Publish an original typed choice, including a proven rejected response."""
    action = watch.receipt_action(request, result)
    if action != row["action"]:
        raise ValueError("Model choice and native trace differ")
    if result.get("action") is None:
        execution, clock = row["execute"], row["tick_advance"]
        native = execution["result"]
        if not (
            row["record_origin"] == "model_input_rejection/v1"
            and execution["accepted"] is False
            and execution["validation_rejected"] is True
            and native["native_action_dispatched"] is False
            and native["command_mutation"] == "not_attempted"
            and type(native["keys_sent"]) is type(native["keys_confirmed"]) is int
            and native["keys_sent"] == native["keys_confirmed"] == 0
            and type(clock["ticks_advanced"]) is int
            and clock["ticks_advanced"] == 0
            and clock["clock_dispatched"] is False
            and clock["start_year"] == clock["end_year"] == row["state_after_advance"]["year"]
            and clock["start_tick"] == clock["end_tick"] == row["state_after_advance"]["year_tick"]
        ):
            raise ValueError("Rejected choice lacks a zero-dispatch native record")
    elif row["execute"]["accepted"] is not True:
        raise ValueError("Accepted model choice lacks an accepted native record")
    return action


def reviewed_window(audit: dict[str, Any]) -> tuple[int, int, int, str]:
    """Keep original decision offsets and count only this window's elapsed time."""
    if not (
        audit["passed"] is True
        and audit["status"] == "completed"
        and audit["native_cleanup_verified"] is True
        and audit["vm_teardown_verified"] is True
        and audit["human_gameplay_rescue"] is False
    ):
        raise ValueError("A saved, reviewed and torn-down window is required")
    schema = audit["schema_version"]
    end = audit["responses"]
    if schema == "fortgym.private-binding-trial-terminal-review/v1":
        first, elapsed, profile = 0, audit["saved_elapsed_ticks"], audit["control_profile"]
    elif schema == "fortgym.private-matched-window-terminal-review/v1":
        first, elapsed = audit["first_step"], audit["new_saved_elapsed_ticks"]
        profile = "native_keyboard_bindings/v1"
        if not (
            type(first) is type(audit["new_responses"]) is type(audit["next_step"]) is int
            and first == audit["new_responses"] == 64
            and audit["next_step"] == end == 128
            and audit["source_checkpoint_fresh_load_verified"] is True
            and type(elapsed) is int
            and type(audit["saved_elapsed_ticks"]) is int
            and audit["saved_elapsed_ticks"] >= elapsed
        ):
            raise ValueError("Continuation must preserve its reviewed 64-to-128 boundary")
    else:
        raise ValueError("Unsupported recording audit")
    if type(end) is not int or end <= first or type(elapsed) is not int or elapsed < 0:
        raise ValueError("Invalid recorded response or clock boundary")
    return first, end, elapsed, profile


def export(attempt: Path, observer: Path, audit_sha: str, identity: str) -> dict[str, Any]:
    audit_path = attempt / "terminal-review.json"
    if sha(audit_path) != audit_sha:
        raise ValueError("Audit digest differs")
    audit = read(audit_path)
    first, end, elapsed, control_profile = reviewed_window(audit)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=observer, text=True
    ).strip()
    if revision != OBSERVER_REVISION or subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=observer
    ):
        raise ValueError("Observer source is not clean and pinned")
    if any(name == "fort_gym" or name.startswith("fort_gym.") for name in sys.modules):
        raise ValueError("Recording export requires a fresh standalone process")
    # Rejection parsing uses only this pinned observer's native receipt readers.
    # Never mix the public server's package with the frozen evidence parser.
    sys.path.insert(0, str(observer))
    spec = importlib.util.spec_from_file_location(
        "fort_gym.bench.api.watch", observer / "fort_gym/bench/api/watch.py"
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
        len(rows) != end
        or len(entries) != end - first
        or [index for index, _ in entries] != list(range(end - first))
        or [row["step"] for row in rows] != list(range(end))
        or len(audit["receipt_reviews"]) != end - first
    ):
        raise ValueError("Saved window boundary and receipt coverage differ")
    frames = []
    for (index, folder), row, receipt in zip(
        entries, rows[first:], audit["receipt_reviews"], strict=True
    ):
        request, response, summary = [
            read(folder / (name + ".json")) for name in ("request", "response", "summary")
        ]
        request_sha = hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest()
        if (
            request_sha != receipt["request_sha256"]
            or request_sha != response["request_sha256"]
            or receipt["decision_index"] != index
            or request["model"] != audit["model"]
            or request["reasoning_effort"] != audit["reasoning_effort"]
            or request["control_profile"] != control_profile
            or summary["request_id"] != request["request_id"]
        ):
            raise ValueError("Screen, model receipt and native trace differ")
        action = recorded_action(watch, request, response["result"], row)
        clock, after = row["tick_advance"], row["state_after_advance"]
        frames.append(
            {
                "decision": first + index + 1,
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
    if sum(frame["after"]["ticks_advanced"] for frame in frames) != elapsed:
        raise ValueError("Saved elapsed ticks differ")
    return {
        "schema_version": "fortgym.watch-recording/v1",
        "id": identity,
        "title": audit["model"] + " · matched trial " + str(audit["replicate"]),
        "model": audit["model"],
        "control_profile": control_profile,
        "first_decision": first + 1,
        "last_decision": end,
        "saved_through_decision": end,
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
