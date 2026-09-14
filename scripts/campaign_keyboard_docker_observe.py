"""Publish expiring portable-owner spectator frames; never call Docker or models."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from fort_gym.bench.run.keyboard_docker_watch import (
    baseline, public_summary, snapshot, terminal, validate_output,
)
from fort_gym.bench.run.keyboard_owner_process import process_identity
from scripts.campaign_watch_observe import publish


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("once", "follow"))
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--public-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_output(args.attempt, args.public_dir)
    base = baseline(args.attempt)
    if args.mode == "once":
        terminal(args.attempt, base)
        value = snapshot(args.attempt, base, alive=False, now=int(time.time()))
        publish(args.public_dir, value)
        print(public_summary(value))
        return
    owner = base["plan"].get("owner_process")
    if (not isinstance(owner, dict) or not isinstance(owner.get("identity"), str)
            or process_identity(owner["pid"]) != owner["identity"]):
        raise ValueError("Follow requires the matching live process bound by the owner")
    while True:
        alive = None
        try:
            alive = process_identity(owner["pid"]) == owner["identity"]
            value = snapshot(args.attempt, base, alive=alive, now=int(time.time()))
            publish(args.public_dir, value)
            print(public_summary(value), flush=True)
            if not alive:
                return
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
            # An observation failure is not proof the owner stopped. Let the last
            # good public frame expire instead of inventing current liveness.
            print(json.dumps({"observation_error": type(error).__name__}), flush=True)
            if alive is False:
                return
        time.sleep(10)


if __name__ == "__main__":
    main()
