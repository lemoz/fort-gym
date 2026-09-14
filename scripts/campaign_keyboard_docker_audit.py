"""Write an audit of settled portable-owner saves without controlling the runtime."""

import argparse
import json
from pathlib import Path

from fort_gym.bench.run.keyboard_docker_audit import audit
from fort_gym.bench.run.keyboard_docker_plan import absolute_path
from fort_gym.bench.run.keyboard_docker_recording import sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window",
        nargs=2,
        action="append",
        required=True,
        metavar=("ATTEMPT", "ORIGIN"),
        help="Owner output and its original snapshot/checkpoint",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    windows = [(Path(attempt), Path(origin)) for attempt, origin in args.window]
    output = absolute_path(args.output)
    for attempt, origin in windows:
        for retained in (absolute_path(attempt), absolute_path(origin)):
            if output == retained or retained in output.parents:
                raise ValueError("Audit output must stay outside retained inputs")
    value = audit(windows)
    with output.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "passed": value["passed"],
                "windows": len(value["windows"]),
                "model_responses": value["model_responses"],
                "audit_sha256": sha(output),
                "model_calls": 0,
                "docker_calls": 0,
                "website_published": False,
            }
        )
    )


if __name__ == "__main__":
    main()
