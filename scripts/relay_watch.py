"""Relay sanitized decisions for one existing owner; never starts a game or model."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


def process_identity(pid: int) -> dict | None:
    """An observation error is not evidence that the owner stopped."""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=,command="],
        text=True,
        capture_output=True,
        timeout=5,
    )
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return None
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Owner identity observation failed")
    cwd = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        text=True,
        capture_output=True,
        timeout=5,
    )
    paths = [line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")]
    if cwd.returncode != 0 or len(paths) != 1:
        raise RuntimeError("Owner directory observation failed")
    return {"start_and_command": result.stdout.strip(), "cwd": paths[0]}


def load_observer(source: Path, revision: str):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if head != revision or subprocess.check_output(["git", "status", "--porcelain"], cwd=source):
        raise ValueError("Observer source is not the pinned clean checkout")
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location(
        "retained_watch_observer", source / "scripts/campaign_watch_observe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ssh_command(binding: dict) -> list[str]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*@[A-Za-z0-9.-]+", binding["destination"]):
        raise ValueError("Invalid relay SSH destination")
    remote = (
        "cd "
        + shlex.quote(binding["remote_root"])
        + " && "
        + shlex.join(
            ["python3", "-m", "scripts.receive_watch_relay", "--run-id", binding["run_id"]]
        )
    )
    return [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "-i",
        binding["identity_file"],
        binding["destination"],
        remote,
    ]


def send(binding: dict, value: dict) -> dict:
    result = subprocess.run(
        ssh_command(binding),
        input=json.dumps(value, allow_nan=False),
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    receipt = json.loads(result.stdout)
    expected = value["frame"]["decision"] if value["frame"] else None
    if (
        receipt.get("published") is not True
        or receipt.get("run_id") != binding["run_id"]
        or receipt.get("decision") != expected
    ):
        raise ValueError("Public relay did not acknowledge this exact observation")
    return receipt


def run(binding: dict, *, maximum_seconds: int) -> None:
    if binding.get("schema_version") != "fortgym.watch-relay-binding/v1":
        raise ValueError("Unsupported relay binding")
    if type(binding["owner_pid"]) is not int or binding["owner_pid"] < 1:
        raise ValueError("Invalid owner PID")
    attempt = Path(binding["attempt"]).resolve(strict=True)
    if Path(binding["owner_identity"]["cwd"]).resolve() != attempt.parent:
        raise ValueError("Owner process is not bound to the attempt directory")
    if process_identity(binding["owner_pid"]) != binding["owner_identity"]:
        raise ValueError("The bound owner is not running")
    observer = load_observer(Path(binding["source_checkout"]), binding["source_revision"])
    base = {key: binding[key] for key in ("run_id", "model", "saved_checkpoint_cursor")}
    deadline, last = time.monotonic() + maximum_seconds, None
    dead_observed, terminal_failures = False, 0
    while time.monotonic() < deadline:
        try:
            identity = process_identity(binding["owner_pid"])
            alive = identity == binding["owner_identity"]
            dead_observed = not alive
            value = observer.snapshot(attempt, base, alive=alive, now=int(time.time()))
            observer.publish(Path(binding["local_public_directory"]), value)
            receipt = send(binding, value)
            state = receipt["status"], receipt["decision"]
            if state != last:
                print(json.dumps(receipt), flush=True)
                last = state
            if not alive:
                return
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as error:
            # Leave the last observation to expire. Never restart or signal the owner.
            print(json.dumps({"relay_warning": type(error).__name__}), flush=True)
            if dead_observed:
                terminal_failures += 1
                if terminal_failures >= 3:
                    print(
                        json.dumps(
                            {
                                "relay_ended": "owner_stopped_delivery_unavailable",
                                "last_observation_will_expire": True,
                            }
                        ),
                        flush=True,
                    )
                    return
        time.sleep(5)
    print(
        json.dumps({"relay_ended": "bounded_lifetime", "last_observation_will_expire": True}),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--maximum-seconds", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.maximum_seconds <= 60000:
        parser.error("maximum-seconds must be between 1 and 60000")
    run(json.loads(args.binding.read_text()), maximum_seconds=args.maximum_seconds)


if __name__ == "__main__":
    main()
