"""Observe an existing matched owner using host files only; never call the game."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from fort_gym.bench.agent.keyboard_exchange import digest, read, validate_request
from fort_gym.bench.api.keyboard_cohort import PLAN_PATH, PLAN_SHA256, _read
from fort_gym.bench.api.keyboard_cohort_live import FILENAME, SCHEMA, project_status
from scripts.campaign_keyboard_observe import file_sha, owner_identity


def baseline(run_dir: Path, operator: Path, execution: Path) -> dict:
    launch = read(run_dir / "launch.json")
    binding = read(execution)
    plan = _read(PLAN_PATH, PLAN_SHA256)
    if (launch["campaign_id"] != run_dir.name or launch["binding"] != binding
            or binding["operator_sha256"] != file_sha(operator)
            or binding["source_revision"] != launch["source_revision"]
            or binding["seed_receipt_sha256"] != plan["source_snapshot_receipt_sha256"]
            or binding["config_sha256"]["cohort.json"] != PLAN_SHA256):
        raise ValueError("Owner, execution and declared seed must match")
    return {
        "schema_version": SCHEMA, "campaign_id": run_dir.name,
        "model": launch["model"], "reasoning_effort": launch["reasoning_effort"],
        "source_revision": launch["source_revision"],
        "seed_receipt_sha256": binding["seed_receipt_sha256"],
        "execution_binding_sha256": file_sha(execution),
        "data_disk_gib": binding.get("data_disk_gib", 24),
    }


def snapshot(run_dir: Path, base: dict, *, alive: bool, now: int) -> dict:
    entries = []
    claims = {p.parent.name for p in (run_dir / "model").glob("*/claim.json")}
    for path in (run_dir / "model").glob("*/summary.json"):
        summary, request = read(path), read(path.parent / "request.json")
        response = read(path.parent / "response.json")
        validate_request(request)
        if (path.parent.name not in claims
                or path.parent.name != request["request_id"]
                or summary["request_id"] != request["request_id"]
                or response["request_sha256"] != digest(request)
                or request["model"] != base["model"]
                or request["reasoning_effort"] != base["reasoning_effort"]
                or request["prompt_profile"] != "native_keyboard_memory_replacement/v1"
                or (request["screen"]["width"], request["screen"]["height"]) != (120, 40)):
            raise ValueError("Live request and response do not match the trial")
        entries.append((summary, request, response["result"]))
    entries.sort(key=lambda item: item[0]["decision_index"])
    if [e[0]["decision_index"] for e in entries] != list(range(len(entries))):
        raise ValueError("Live receipts are not consecutive")
    calls, tokens, ticks = 0, 0, 0
    observed = False
    for summary, request, result in entries:
        receipt = result["transport_receipt"]
        if (summary["model_dispatched"] is not receipt["dispatched"]
                or summary.get("reported_charge_usd", "missing") is not None
                or receipt.get("reported_charge_usd", "missing") is not None):
            raise ValueError("Unreconciled live usage")
        if summary["model_dispatched"] is True:
            added = summary["total_tokens"]
            if type(added) is not int or added < 0 or receipt["total_tokens"] != added:
                raise ValueError("Incomplete returned usage")
            calls += 1
            tokens += added
        elif summary["model_dispatched"] is not False or summary["total_tokens"] is not None:
            raise ValueError("Unknown dispatch cannot become zero usage")
        if summary["decision_index"] == 0:
            if request["memory"] != "" or request["feedback"] is not None:
                raise ValueError("Independent trial must start with empty agent state")
        else:
            simulation = (request.get("feedback") or {}).get("simulation")
            if simulation is not None:
                advanced = simulation["ticks_advanced"]
                if type(advanced) is not int or advanced < 0:
                    raise ValueError("Invalid clock feedback")
                ticks += advanced
                observed = True
    teardown = None
    if not alive and (run_dir / "result.json").exists():
        terminal = read(run_dir / "result.json")
        if terminal["campaign_id"] != base["campaign_id"]:
            raise ValueError("Terminal report is for another trial")
        teardown = terminal.get("vm_observed_stopped")
    value = {
        **base, "controller_alive": alive, "observed_at_unix": now,
        "responses": calls, "returned_tokens": tokens,
        "unsettled_claims": len(claims) - len(entries),
        "observed_elapsed_ticks_lower_bound": ticks if observed else None,
        "teardown_reported": teardown, "reported_charge_usd": None,
    }
    project_status(value, now=now)
    return value


def publish_status(root: Path, value: dict) -> None:
    """Replace this derivative atomically, without touching original receipts."""
    project_status(value, now=int(time.time()))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / FILENAME
    if target.is_symlink():
        raise ValueError("Live target cannot be a symlink")
    with tempfile.NamedTemporaryFile(mode="w", dir=root, prefix=".matched-live-", delete=False) as f:
        json.dump(value, f, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
        temporary = Path(f.name)
    temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run-dir", "operator", "execution", "public-dir"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--index", type=int, choices=range(6), required=True)
    args = parser.parse_args()
    plan = _read(PLAN_PATH, PLAN_SHA256)
    if args.owner_pid <= 1 or plan["execution_order"][args.index]["campaign_id"] != args.run_dir.name:
        raise ValueError("A specific matching owner is required")
    original = owner_identity(args.owner_pid)
    # Identity includes process start time, so a reused PID never resumes this feed.
    if original is None or not original.endswith(f" -u {args.operator.name} {args.index}"):
        raise ValueError("The declared owner is not active")
    base = baseline(args.run_dir, args.operator, args.execution)
    while True:
        alive = None
        try:
            alive = owner_identity(args.owner_pid) == original
            value = snapshot(args.run_dir, base, alive=alive, now=int(time.time()))
            publish_status(args.public_dir, value)
            print(json.dumps({"controller_alive": alive, "responses": value["responses"]}), flush=True)
            if not alive:
                return
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
            # Read failures do not mean the owner died. Let the previous feed expire.
            print(json.dumps({"observation_error": type(error).__name__}), flush=True)
            if alive is False:
                return
        time.sleep(10)


if __name__ == "__main__":
    main()
