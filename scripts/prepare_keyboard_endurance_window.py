"""Write a bounded continuation declaration from a completed portable owner."""

import argparse
import json
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_docker_plan import absolute_path
from fort_gym.bench.run.keyboard_endurance_window import prepare_window


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-attempt", type=Path, required=True)
    parser.add_argument("--previous-origin", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--max-dispatches", type=int, required=True)
    parser.add_argument("--max-total-tokens", type=int, required=True)
    parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = absolute_path(args.output)
    for retained in (args.previous_attempt, args.previous_origin, args.runtime):
        absolute_path(retained)
        if output == retained or retained in output.parents or output in retained.parents:
            raise ValueError("Window output must be separate from retained inputs")
    window, condition, checkpoint = prepare_window(
        args.previous_attempt,
        args.previous_origin,
        read(args.runtime),
        target_budget={
            "max_dispatches": args.max_dispatches,
            "max_total_tokens": args.max_total_tokens,
        },
        steps=args.steps,
    )
    with output.open("x") as stream:
        json.dump(window, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "window": str(output),
                "condition": str(condition),
                "checkpoint": str(checkpoint),
                "next_step": window["continuation_from_next_step"],
                "window_end_decision": window["window_end_decision"],
                "budget_extension": window.get("budget_extension"),
                "model_calls": 0,
                "docker_calls": 0,
                "vm_teardown_verified_now": False,
            }
        )
    )


if __name__ == "__main__":
    main()
