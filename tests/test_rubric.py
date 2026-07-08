"""Unit tests for fort_gym.bench.eval.rubric's action fingerprinting."""

from __future__ import annotations

from fort_gym.bench.eval.rubric import _action_fingerprint, evaluate_trace_records


def test_dig_fingerprint_is_kind_aware() -> None:
    dig = {"type": "DIG", "params": {"kind": "dig", "area": [1, 2, 3], "size": [4, 4, 1]}}
    channel = {"type": "DIG", "params": {"kind": "channel", "area": [1, 2, 3], "size": [4, 4, 1]}}
    chop = {"type": "DIG", "params": {"kind": "chop", "area": [1, 2, 3], "size": [4, 4, 1]}}
    gather = {"type": "DIG", "params": {"kind": "gather", "area": [1, 2, 3], "size": [4, 4, 1]}}

    fingerprints = {
        _action_fingerprint(dig),
        _action_fingerprint(channel),
        _action_fingerprint(chop),
        _action_fingerprint(gather),
    }

    # Same area/size but different kinds must not collapse into one bucket.
    assert len(fingerprints) == 4


def test_dig_fingerprint_defaults_kind_to_dig_when_missing() -> None:
    no_kind = {"type": "DIG", "params": {"area": [1, 2, 3], "size": [4, 4, 1]}}
    explicit_dig = {"type": "DIG", "params": {"kind": "dig", "area": [1, 2, 3], "size": [4, 4, 1]}}

    assert _action_fingerprint(no_kind) == _action_fingerprint(explicit_dig)


def test_build_fingerprint_distinguishes_rect_extent() -> None:
    small = {
        "type": "BUILD",
        "params": {"kind": "FarmPlot", "x": 90, "y": 95, "z": 177},
    }
    large = {
        "type": "BUILD",
        "params": {"kind": "FarmPlot", "x": 90, "y": 95, "z": 177, "x2": 94, "y2": 99},
    }

    assert _action_fingerprint(small) != _action_fingerprint(large)


def test_build_fingerprint_stable_without_x2_y2() -> None:
    action = {"type": "BUILD", "params": {"kind": "Wall", "x": 5, "y": 5, "z": 1}}
    assert _action_fingerprint(action) == "BUILD:Wall:5:5:1"


def test_rubric_does_not_flag_repetition_across_distinct_dig_kinds() -> None:
    # A no-op dig/gather/channel alternation at the same rect must be treated
    # as three distinct actions (per the dimension's own "repeated identical
    # actions" definition), not merged into one stale fingerprint bucket.
    kinds = ["dig", "gather", "dig", "gather", "channel"]
    records = []
    for step, kind in enumerate(kinds):
        records.append(
            {
                "step": step,
                "action": {
                    "type": "DIG",
                    "params": {"kind": kind, "area": [1, 2, 3], "size": [4, 4, 1]},
                },
                "execute": {"accepted": True, "provenance": "dfhack_governed"},
                "metrics": {"pop": 7, "food": 40, "drink": 50},
                "gameplay_proof": {"ok": False, "changed_tile_count": 0},
                "tick_advance": {"ticks_advanced": 1000},
            }
        )

    rubric = evaluate_trace_records(records)

    # 2/5 for the most common fingerprint (dig or gather) is below the 0.6
    # repetitive_policy blocker threshold.
    assert "repetitive_policy" not in rubric["blockers"]
