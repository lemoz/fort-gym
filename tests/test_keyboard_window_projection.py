"""Synthetic public slices; no future native campaign result is invented."""

from copy import deepcopy

import pytest

from fort_gym.bench.run.keyboard_window_projection import saved_window_timeline


def fixture(cursor=128, count=128, segments=2):
    window = {
        "continuation_from_next_step": cursor,
        "steps_per_segment": 64,
        "max_segments": segments,
        "window_end_decision": cursor + 64 * segments,
        "saved_elapsed_ticks_before_window": cursor * 100,
    }
    rows = [
        {
            "step": index,
            "tick_advance": {"ticks_advanced": 100},
            "execute": {"accepted": True},
        }
        for index in range(cursor + count)
    ]
    profile = {
        "timeline": [
            {"boundary_index": index + 1, "metrics": {"population": 7}}
            for index in range(cursor + count)
        ]
    }
    return rows, profile, window, count, cursor + count


@pytest.mark.parametrize("count", [0, 1, 63, 64, 65, 127, 128])
def test_new_slice_spans_saved_segments_without_recounting_history(count):
    values = fixture(count=count)
    elapsed, timeline = saved_window_timeline(iter(values[0]), *values[1:])
    assert elapsed == 12800 + count * 100
    assert [point["decision"] for point in timeline] == list(range(129, 129 + count))
    if timeline:
        assert timeline[-1]["new_elapsed_ticks"] == count * 100
        assert timeline[-1]["campaign_elapsed_ticks"] == elapsed


@pytest.mark.parametrize(
    "cursor,segments,count", [(64, 1, 64), (256, 4, 256), (512, 8, 100)]
)
def test_prior_and_later_declared_windows_use_their_own_boundaries(
    cursor, segments, count
):
    elapsed, timeline = saved_window_timeline(*fixture(cursor, count, segments))
    assert len(timeline) == count
    assert timeline[0]["decision"] == cursor + 1
    assert elapsed == (cursor + count) * 100


@pytest.mark.parametrize(
    "count,next_step", [(True, 129), (-1, 127), (129, 257), (1, 128), (0, True)]
)
def test_invalid_usage_cursor_cannot_be_published(count, next_step):
    rows, profile, window, _, _ = fixture(count=1)
    with pytest.raises(ValueError):
        saved_window_timeline(rows, profile, window, count, next_step)


@pytest.mark.parametrize(
    "field,value",
    [
        ("saved_elapsed_ticks_before_window", 12900),
        ("saved_elapsed_ticks_before_window", True),
        ("continuation_from_next_step", 64),
        ("steps_per_segment", 65),
        ("max_segments", True),
        ("max_segments", 17),
        ("window_end_decision", 257),
    ],
)
def test_mismatched_or_unbounded_window_is_rejected(field, value):
    values = list(fixture(count=1))
    values[2][field] = value
    with pytest.raises(ValueError):
        saved_window_timeline(*values)


@pytest.mark.parametrize(
    "mutation",
    [
        "step_gap",
        "step_bool",
        "negative_ticks",
        "bool_ticks",
        "short_trace",
        "extra_trace",
        "missing_profile",
        "duplicate_profile",
    ],
)
def test_saved_trace_and_profile_boundaries_must_be_exact(mutation):
    values = list(deepcopy(fixture(count=1)))
    rows, profile = values[:2]
    if mutation == "step_gap":
        rows[-1]["step"] -= 1
    elif mutation == "step_bool":
        rows[1]["step"] = True
    elif mutation == "negative_ticks":
        rows[-1]["tick_advance"]["ticks_advanced"] = -1
    elif mutation == "bool_ticks":
        rows[-1]["tick_advance"]["ticks_advanced"] = True
    elif mutation == "short_trace":
        rows.pop()
    elif mutation == "extra_trace":
        rows.append({**rows[-1], "step": 129})
    elif mutation == "missing_profile":
        profile["timeline"].pop()
    else:
        profile["timeline"].append(profile["timeline"][-1])
    with pytest.raises(ValueError):
        saved_window_timeline(*values)
