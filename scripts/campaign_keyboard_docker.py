"""Run a declared keyboard attempt using an existing local Docker runtime image.

No daemon, VM, image pull, cloud host or model fallback is started automatically.
Check only validates local files and prints the launch plan; run can make model
calls and owns stopping its one container. Native acceptance remains separate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_docker_owner import run_owner, source_inputs
from fort_gym.bench.run.keyboard_docker_plan import create_arguments, validate_runtime
from scripts.campaign_keyboard_native import verify_source
from scripts.campaign_process import termination_as_interrupt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run"))
    parser.add_argument("--mode", choices=("fresh", "continue"), required=True)
    for key in ("runtime", "condition", "declaration", "origin", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--context", required=True, help="Existing local Docker context")
    parser.add_argument(
        "--docker", type=Path, default=Path(shutil.which("docker") or "/missing/docker")
    )
    parser.add_argument("--model-executable", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    for key, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, key, value.absolute())
    runtime = validate_runtime(read(args.runtime))
    verify_source(runtime["source_revision"])
    if args.command == "check":
        inputs = source_inputs(args)
        command = create_arguments(
            runtime, inputs, args.output, args.origin, "fortgym-" + "0" * 32, "0" * 32, args.port
        )
        result = {
            "schema_version": "fortgym.keyboard-docker-check/v1",
            "passed": True,
            "source_revision": runtime["source_revision"],
            "model": inputs["condition"]["model"],
            "mode": args.mode,
            "response_limit": inputs["limit"],
            "create_arguments": command,
            "local_files_only": True,
            "docker_contacted": False,
            "image_compatibility_verified": False,
            "game_or_model_started": False,
        }
    else:
        with termination_as_interrupt():
            result = run_owner(args)
    print(json.dumps(result, allow_nan=False), flush=True)
    if args.command == "run" and result["status"] != "execution_finished":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
