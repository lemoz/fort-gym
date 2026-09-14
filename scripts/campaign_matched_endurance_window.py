"""Reproduce a saved attempt's lineage and prepare its next endurance window.

Pass --result PATH SHA256 in chronological order: the initial 32-response result,
then each audited continuation. Output is configuration, never launch admission.
"""

import argparse
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_trial_config import load_trial
from fort_gym.bench.run.matched_endurance import next_window
from fort_gym.bench.run.matched_result_chain import (
    encoded,
    exact_digest,
    validate_continuation,
)
from scripts import campaign_matched_window as initial


def _next_window(result: dict, result_sha: str, chain: list[str], template: dict) -> dict:
    plan = read(initial.PLAN / "cohort.json")
    row = next(r for r in plan["execution_order"] if r["campaign_id"] == result["campaign_id"])
    condition, _ = load_trial(initial.PLAN / row["condition"], initial.PLAN / row["trial"])
    return next_window(result, result_sha, chain, template, plan=plan, row=row, condition=condition)


def prepare(sources: list[tuple[Path, str]]) -> dict:
    """Return a deterministic next window only after checking the complete chain."""
    try:
        return _prepare(sources)
    except (KeyError, TypeError, StopIteration) as error:
        raise ValueError("Malformed or incomplete continuation lineage") from error


def _prepare(sources: list[tuple[Path, str]]) -> dict:
    if len(sources) < 2:
        raise ValueError("Endurance preparation requires the initial result and a continuation")
    first, first_sha = sources[0]
    window = initial.prepare(first, first_sha)
    parent = read(first)
    row = next(
        r
        for r in read(initial.PLAN / "cohort.json")["execution_order"]
        if r["campaign_id"] == parent["campaign_id"]
    )
    condition, _ = load_trial(initial.PLAN / row["condition"], initial.PLAN / row["trial"])
    chain = [first_sha]
    for path, expected_sha in sources[1:]:
        if not exact_digest(expected_sha) or initial.sha(path) != expected_sha:
            raise ValueError("Continuation result differs from its exact digest")
        if expected_sha in chain:
            raise ValueError("A continuation record cannot be repeated in its own lineage")
        child = read(path)
        validate_continuation(child, parent, window, condition)
        chain.append(expected_sha)
        window = _next_window(child, expected_sha, chain.copy(), window)
        parent = child
    return window


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--result", nargs=2, action="append", required=True, metavar=("PATH", "SHA256")
    )
    args = parser.parse_args()
    value = prepare([(Path(path), digest) for path, digest in args.result])
    print(encoded(value).decode(), end="")


if __name__ == "__main__":
    main()
