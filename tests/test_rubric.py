"""Unit tests for fort_gym.bench.eval.rubric's action fingerprinting."""

from __future__ import annotations

from fort_gym.bench.eval.rubric import (
    _action_fingerprint,
    _proof_shows_world_change,
    evaluate_trace_records,
)


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


def test_labor_fingerprint_distinguishes_unit_labor_enable() -> None:
    base = {"type": "LABOR", "params": {"unit_id": 243, "labor": "brewing", "enable": True}}
    other_unit = {"type": "LABOR", "params": {"unit_id": 248, "labor": "brewing", "enable": True}}
    other_labor = {"type": "LABOR", "params": {"unit_id": 243, "labor": "mine", "enable": True}}
    disable = {"type": "LABOR", "params": {"unit_id": 243, "labor": "brewing", "enable": False}}

    fingerprints = {
        _action_fingerprint(base),
        _action_fingerprint(other_unit),
        _action_fingerprint(other_labor),
        _action_fingerprint(disable),
    }

    # unit, labor, and enable each change the bucket
    assert len(fingerprints) == 4
    assert _action_fingerprint(base) == "LABOR:243:brewing:True"


def test_labor_real_flip_is_world_change() -> None:
    proof = {
        "ok": True,
        "changed_tile_count": 0,
        "helper_evidence": {
            "labor_changed": True,
            "labor_before": False,
            "labor_after": True,
        },
    }
    assert _proof_shows_world_change(proof) is True


def test_labor_noop_flip_is_not_world_change() -> None:
    # already-enabled labor re-enabled: before == after, no state flip. The two
    # truthy labor_before/labor_after must NOT count as world change.
    proof = {
        "ok": True,
        "changed_tile_count": 0,
        "helper_evidence": {
            "labor_changed": False,
            "labor_before": True,
            "labor_after": True,
        },
    }
    assert _proof_shows_world_change(proof) is False


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
