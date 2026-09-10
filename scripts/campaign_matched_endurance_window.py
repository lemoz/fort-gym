"""Reproduce a saved attempt's lineage and prepare its next endurance window.

Pass --result PATH SHA256 in chronological order: the initial 32-response result,
then each audited continuation. Output is configuration, never launch admission.
"""

import argparse
from pathlib import Path

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_trial_config import load_trial
from fort_gym.bench.run.matched_result_chain import (
    encoded,
    exact_digest,
    totals,
    validate_continuation,
)
from scripts import campaign_matched_window as initial


def _next_window(result: dict, result_sha: str, chain: list[str], template: dict) -> dict:
    plan = read(initial.PLAN / "cohort.json")
    row = next(r for r in plan["execution_order"] if r["campaign_id"] == result["campaign_id"])
    condition, _ = load_trial(initial.PLAN / row["condition"], initial.PLAN / row["trial"])
    cursor, tokens = totals(result)
    targets = [n for n in plan["stages"]["comparison_decision_boundaries"] if n > cursor]
    if not targets or tokens >= condition["max_total_tokens"]:
        raise ValueError("The declared campaign allowance is exhausted; no extension is implied")
    target = targets[0]
    if target > condition["max_dispatches"]:
        raise ValueError("Comparison boundary exceeds the unchanged campaign allowance")
    remaining = target - cursor
    # Preserve the same 64-step save boundaries for every attempt. After an
    # admission pause, finish that segment before scheduling whole segments.
    steps = min(64 - cursor % 64, remaining)
    segments = remaining // 64 if cursor % 64 == 0 and remaining >= 64 else 1
    if not 1 <= segments <= 16:
        raise ValueError("Declared stage exceeds the native segment bound")
    end = cursor + steps * segments
    window = {**template}
    window.update(
        {
            "condition_id": f"{row['campaign_id']}-continue-{cursor}-{end}",
            "continuation_from_next_step": cursor,
            "continuation_checkpoint_sha256": result["checkpoint_sha256"],
            "steps_per_segment": steps,
            "max_segments": segments,
            "source_result_sha256": result_sha,
            "source_audit_sha256": result["audit_sha256"],
            "source_native_revision": result["execution"]["source_revision"],
            "source_image_id": result["execution"]["image_id"],
            "saved_elapsed_ticks_before_window": result["saved_elapsed_ticks"],
            "accounted_responses_before_window": cursor,
            "returned_tokens_before_window": tokens,
            "source_result_chain_sha256": chain,
            "comparison_target_decision": target,
            "window_end_decision": end,
            "window_preparation_profile": "matched_own_save_endurance/v1",
            "hypothesis": (
                "Under unchanged model, input, observation and prompt settings, longer play tests "
                "whether the independently started agent adapts to its current fortress, establishes "
                "observable work and maintains population and supplies. Compare saved outcomes at "
                f"the predeclared decision-{target} boundary without per-model tuning. "
                "A year-two calendar crossing alone is not sustainable-fortress success."
            ),
            "budget_note": (
                f"At most {steps * segments} additional responses, retaining the original per-campaign "
                "1280-dispatch and 40000000-token ceilings. Configuration preparation is not launch "
                "admission, a budget extension or a dollar reservation. Fresh subscription admission "
                "before each call; no API/local fallback or credit/reset purchase; one local VM at a "
                "time with mandatory teardown."
            ),
        }
    )
    return window


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
