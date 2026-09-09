"""Publish expiring website status from existing host receipts, never game calls."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from fort_gym.bench.agent.keyboard_exchange import digest, read
from fort_gym.bench.api.keyboard_live import SCHEMA, project_status
from fort_gym.bench.run.keyboard_config import load_window


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def owner_identity(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=,command="],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode == 1 and not result.stdout.strip():
        return None
    if result.returncode != 0:
        raise RuntimeError("Could not inspect the declared owner")
    return result.stdout.strip()


def baseline(
    run_dir: Path, condition_path: Path, window_path: Path, historical_tokens: int
) -> dict:
    if type(historical_tokens) is not int or historical_tokens < 0:
        raise ValueError("Historical usage must be explicitly accounted")
    condition, window = load_window(condition_path, window_path)
    preflight = read(run_dir / "preflight.json")
    startup = read(run_dir / "live-start-review.json")
    launch = read(run_dir / "attempt/launch.json")
    initial = read(run_dir / "startup-evidence/agent-before.json")
    if (
        preflight.get("passed") is not True
        or startup.get("passed") is not True
        or startup["source_revision"] != preflight["source_revision"]
        or launch["source_revision"] != preflight["source_revision"]
        or startup["preflight_sha256"] != file_sha(run_dir / "preflight.json")
        or startup["source_sha256"]["agent-before.json"]
        != file_sha(run_dir / "startup-evidence/agent-before.json")
        or launch["operator_sha256"] != file_sha(run_dir / "operator.py")
        or preflight["condition_sha256"] != file_sha(condition_path)
        or preflight["window_sha256"] != file_sha(window_path)
        or initial["usage"]["total_tokens"] != preflight["campaign_tokens"]
        or initial["usage"]["accounted_responses"] != preflight["accounted_responses"]
    ):
        raise ValueError("Live status requires the matching audited startup")
    return {
        "schema_version": SCHEMA,
        "run_id": run_dir.name,
        "model": condition["model"],
        "reasoning_effort": condition["reasoning_effort"],
        "source_revision": preflight["source_revision"],
        "saved_checkpoint_cursor": window["continuation_from_next_step"],
        "saved_elapsed_ticks": preflight["checkpointed_elapsed_ticks"],
        "campaign_responses": preflight["accounted_responses"],
        "campaign_tokens": preflight["campaign_tokens"],
        "historical_failed_delivery_tokens": historical_tokens,
        "window_response_limit": window["steps_per_segment"] * window["max_segments"],
    }


def snapshot(run_dir: Path, base: dict, *, alive: bool, now: int) -> dict:
    entries = []
    for path in (run_dir / "attempt/model").glob("*/summary.json"):
        summary = read(path)
        request, response = (
            read(path.parent / "request.json"),
            read(path.parent / "response.json"),
        )
        if (
            response["request_sha256"] != digest(request)
            or summary["request_id"] != request["request_id"]
        ):
            raise ValueError("Live response does not match its request")
        entries.append((summary, request, response["result"]))
    entries.sort(key=lambda item: item[0]["decision_index"])
    if [row[0]["decision_index"] for row in entries] != list(range(len(entries))):
        raise ValueError("Live receipts are not consecutive")
    calls, tokens, ticks, deferrals = 0, 0, 0, 0
    observed = False
    for summary, request, decision in entries:
        receipt = decision["transport_receipt"]
        if (
            summary["model_dispatched"] is not receipt["dispatched"]
            or summary.get("reported_charge_usd", "missing") is not None
            or receipt.get("reported_charge_usd") is not None
        ):
            raise ValueError(
                "Live status cannot hide changed dispatch or reported charges"
            )
        if summary["model_dispatched"] is True:
            added = summary["total_tokens"]
            if (
                type(added) is not int
                or added < 0
                or decision["transport_receipt"]["total_tokens"] != added
            ):
                raise ValueError("Live usage is incomplete")
            calls += 1
            tokens += added
        elif (
            summary["model_dispatched"] is not False
            or summary["total_tokens"] is not None
        ):
            raise ValueError("Unknown dispatch must not become zero usage")
        # The first request can retain feedback from before this window.
        simulation = (
            (request.get("feedback") or {}).get("simulation")
            if summary["decision_index"] > 0
            else None
        )
        if simulation is not None:
            advanced = simulation["ticks_advanced"]
            if type(advanced) is not int or advanced < 0:
                raise ValueError("Invalid subsequent clock feedback")
            ticks += advanced
            observed = True
            deferrals += simulation.get("deferred") is True
    value = {
        **base,
        "owner_alive": alive,
        "observed_at_unix": now,
        "new_responses": calls,
        "new_tokens": tokens,
        "campaign_responses": base["campaign_responses"] + calls,
        "campaign_tokens": base["campaign_tokens"] + tokens,
        "all_attempt_tokens": base["campaign_tokens"]
        + tokens
        + base["historical_failed_delivery_tokens"],
        "unsaved_ticks_lower_bound": ticks if observed else None,
        "deferrals_observed": deferrals,
        "reported_charge_usd": None,
    }
    project_status(value, now=now)
    return value


def publish_status(root: Path, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "keyboard-active.json"
    if path.is_symlink():
        raise ValueError("Live status target cannot be a symlink")
    # This is a replaceable public derivative, not an immutable experiment record.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=root, prefix=".keyboard-active-", delete=False
    ) as stream:
        json.dump(value, stream, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run-dir", "condition", "window", "public-dir"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--historical-failed-delivery-tokens", type=int, required=True)
    args = parser.parse_args()
    if args.owner_pid <= 1:
        raise ValueError("A specific live owner PID is required")
    original = owner_identity(args.owner_pid)
    expected = " -u " + args.run_dir.name + "/operator.py"
    if original is None or not original.endswith(expected):
        raise ValueError("The declared native-run owner is not active")
    base = baseline(
        args.run_dir,
        args.condition,
        args.window,
        args.historical_failed_delivery_tokens,
    )
    while True:
        alive = owner_identity(args.owner_pid) == original
        value = snapshot(args.run_dir, base, alive=alive, now=int(time.time()))
        publish_status(args.public_dir, value)
        print(
            json.dumps({"owner_alive": alive, "responses": value["new_responses"]}),
            flush=True,
        )
        if not alive:
            return
        time.sleep(10)


if __name__ == "__main__":
    main()
