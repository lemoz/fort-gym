"""Pure declared-window construction shared by CLI and recorded website."""

from .matched_result_chain import totals


def next_window(
    result: dict,
    result_sha: str,
    chain: list[str],
    template: dict,
    *,
    plan: dict,
    row: dict,
    condition: dict,
) -> dict:
    """Derive the next declared window from an already-validated saved parent."""
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
