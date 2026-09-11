"""Project only a declared continuation's new action boundaries for publication."""

from collections.abc import Iterable

from .keyboard_segment_audit import _require


def saved_window_timeline(
    records: Iterable[dict],
    profile: dict,
    window: dict,
    responses: int,
    next_step: int,
) -> tuple[int, list[dict]]:
    """Keep cumulative time while excluding the already-published history slice."""
    cursor, steps, segments, end = (
        window.get(key)
        for key in (
            "continuation_from_next_step",
            "steps_per_segment",
            "max_segments",
            "window_end_decision",
        )
    )
    if not (
        type(cursor) is int
        and cursor > 0
        and type(steps) is int
        and 1 <= steps <= 64
        and type(segments) is int
        and 1 <= segments <= 16
        and type(end) is int
        and end == cursor + steps * segments
        and type(responses) is int
        and 0 <= responses <= steps * segments
        and type(next_step) is int
        and next_step == cursor + responses
    ):
        raise ValueError("Invalid declared publication window or saved cursor")
    prior = window.get("saved_elapsed_ticks_before_window")
    if type(prior) is not int or prior < 0:
        raise ValueError("Invalid previous saved game time")
    points = {}
    for point in profile["timeline"]:
        index = point["boundary_index"]
        _require(
            type(index) is int and index >= 0 and index not in points,
            "Profile has repeated or invalid action boundaries",
        )
        points[index] = point
    elapsed, seen, timeline = 0, 0, []
    for record in records:
        _require(
            type(record["step"]) is int and record["step"] == seen and seen < next_step,
            "Saved trace has missing, repeated or extra decisions",
        )
        ticks = record["tick_advance"]["ticks_advanced"]
        _require(type(ticks) is int and ticks >= 0, "Invalid committed action ticks")
        elapsed += ticks
        seen += 1
        if seen == cursor:
            _require(elapsed == prior, "Previous game time differs from the full trace")
        if seen > cursor:
            _require(seen in points, "Saved action has no observed profile boundary")
            timeline.append(
                {
                    "decision": seen,
                    "campaign_elapsed_ticks": elapsed,
                    "new_elapsed_ticks": elapsed - prior,
                    "accepted": record["execute"].get("accepted"),
                    "metrics": points[seen]["metrics"],
                }
            )
    _require(
        seen == next_step and len(timeline) == responses,
        "Published slice does not match the final saved cursor",
    )
    return elapsed, timeline
