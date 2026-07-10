"""Unit tests for fort_gym.bench.eval.rubric's action fingerprinting."""

from __future__ import annotations

from copy import deepcopy

from fort_gym.bench.eval.rubric import (
    _action_fingerprint,
    _proof_shows_world_change,
    _step_progress_flags,
    evaluate_trace_records,
)
from fort_gym.bench.eval.scoring import GOVERNED_SCORE_PROGRESS_PROVENANCE


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


def test_interact_fingerprint_is_operation_specific() -> None:
    assert (
        _action_fingerprint({"type": "INTERACT", "params": {"operation": "confirm"}})
        == "INTERACT:confirm"
    )
    assert _action_fingerprint(
        {"type": "INTERACT", "params": {"operation": "confirm"}}
    ) != _action_fingerprint({"type": "INTERACT", "params": {"operation": "cancel"}})


def test_interact_audit_evidence_is_not_world_change_or_progress() -> None:
    records = [
        {
            "action": {"type": "INTERACT", "params": {"operation": "confirm"}},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {"pop": 7, "food": 40, "drink": 50},
            "gameplay_proof": {
                "ok": True,
                "changed_tile_count": 0,
                "helper_evidence": {
                    "operation": "confirm",
                    "interface_key": "SELECT",
                    "keys_sent": 1,
                },
            },
            "tick_advance": {"ticks_advanced": 0},
        }
        for _ in range(10)
    ]

    proof = records[0]["gameplay_proof"]
    assert _proof_shows_world_change(proof) is False
    assert _step_progress_flags(records) == [False] * 10
    assert "repetitive_policy" in evaluate_trace_records(records)["blockers"]


def test_agent_review_metadata_receives_no_rubric_credit() -> None:
    records = [
        {
            "step": step,
            "action": {
                "type": "WAIT",
                "params": {},
                "objective": "Observe the current work queue.",
                "plan_step": "Wait for one bounded interval.",
                "advance_ticks": 1000,
            },
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {"pop": 7, "food": 40, "drink": 50},
            "gameplay_proof": {"ok": False, "changed_tile_count": 0},
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(6)
    ]
    reviewed = deepcopy(records)
    for step, record in enumerate(reviewed):
        record["action"]["last_action_review"] = {
            "previous_step": step - 1,
            "verdict": "no_progress",
            "evidence": ["changed=none"],
            "retry_same_action": False,
            "lesson": "No tracked world state changed.",
        }
        record["action"]["plan_review"] = {
            "request_id": f"{step}:periodic_5",
            "decision": "continue",
            "objective": "Observe the current work queue.",
            "evidence": ["changed=none"],
            "reason": "Keep observing.",
            "next_step": "Wait for one bounded interval.",
        }

    assert evaluate_trace_records(reviewed) == evaluate_trace_records(records)


def test_queue_and_incomplete_workshop_do_not_satisfy_production_rubric() -> None:
    records = [
        {
            "step": step,
            "action": {"type": "ORDER", "params": {"job": "bed", "quantity": 5}},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {
                "pop": 7,
                "food": 40,
                "drink": 50,
                "work": {
                    "carpenter_workshops": 1,
                    "carpenter_workshops_usable": 0,
                    "manager_orders_count": 10,
                },
                "manager_orders_delta": 10,
            },
            "gameplay_proof": {"ok": False, "changed_tile_count": 0},
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(6)
    ]

    rubric = evaluate_trace_records(records)

    assert rubric["dimensions"]["production_economy"]["score"] == 0
    assert rubric["dimensions"]["responsiveness"]["score"] == 0
    assert "manager_orders_uncredited=10" in rubric["dimensions"]["production_economy"]["evidence"]
    assert "no_production_surface" in rubric["blockers"]

    completed = deepcopy(records)
    for record in completed:
        record["metrics"]["work"]["carpenter_workshops_usable"] = 1
    completed_rubric = evaluate_trace_records(completed)
    assert completed_rubric["dimensions"]["production_economy"]["score"] == 2
    assert "no_production_surface" not in completed_rubric["blockers"]


def test_explicit_action_attribution_beats_unrelated_metric_changes() -> None:
    records = [
        {
            "step": step,
            "action": {"type": "ORDER", "params": {"job": "brew", "quantity": 3}},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {
                "pop": 7,
                "food": 40,
                "drink": 50,
                # A different construction completed during this tick window.
                "complexity_progress": step + 1,
            },
            "gameplay_proof": {
                "ok": False,
                "action_effect_observed": False,
                "concurrent_world_state_changed": True,
                "changed_tile_count": 1,
            },
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(8)
    ]

    assert _step_progress_flags(records) == [False] * 8
    rubric = evaluate_trace_records(records)
    assert rubric["dimensions"]["responsiveness"]["score"] == 0
    assert "repetitive_policy" in rubric["blockers"]


def test_governed_action_truth_rubric_keeps_global_progress_audit_only() -> None:
    records = [
        {
            "step": step,
            "action": {"type": "WAIT", "params": {}, "advance_ticks": 1000},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {
                "score_progress_provenance": GOVERNED_SCORE_PROGRESS_PROVENANCE,
                "pop": 7,
                "food": 40,
                "drink": 50,
                "work_progress": 99,
                "completion_progress": 99,
                "utility_progress": 99,
                "production_progress": 99,
                "complexity_progress": 99,
                "governed_owned_work_progress": 0,
                "governed_owned_designation_progress": 0,
                "governed_owned_completion_progress": 0,
                "governed_owned_utility_progress": 0,
                "governed_owned_production_progress": 0,
                "governed_owned_complexity_progress": 0,
                "governed_owned_completed_carpenter_workshops": 0,
                "carpenter_workshops_usable": 1,
                "fort_enclosed_spaces": 2,
                "fort_functional_rooms": 2,
                "fort_constructions": 20,
                "work": {
                    "carpenter_workshops": 1,
                    "carpenter_workshops_usable": 1,
                    "fortress_complexity_spaces_completed": 2,
                },
            },
            "gameplay_proof": {
                "ok": False,
                "action_effect_observed": False,
                "concurrent_world_state_changed": True,
                "changed_tile_count": 5,
            },
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(5)
    ]

    rubric = evaluate_trace_records(records)

    assert rubric["progress_provenance"] == GOVERNED_SCORE_PROGRESS_PROVENANCE
    assert rubric["dimensions"]["shelter_layout"]["score"] == 0
    assert rubric["dimensions"]["production_economy"]["score"] == 0
    assert rubric["dimensions"]["responsiveness"]["score"] == 0
    assert "no_fort_structure" in rubric["blockers"]
    assert "no_production_surface" in rubric["blockers"]
    assert "no_broader_fort_layout" in rubric["blockers"]


def test_placement_and_chop_helper_counts_are_world_change() -> None:
    for helper_evidence in ({"placed_count": 1}, {"trees_designated": 4}):
        proof = {
            "ok": True,
            "changed_tile_count": 0,
            "state_deltas": {},
            "helper_evidence": helper_evidence,
        }
        assert _proof_shows_world_change(proof) is True


def _labor_record(step: int, *, unit_id: int, labor: str, enable: bool) -> dict:
    """A governed LABOR step whose flip genuinely changes real labor state."""
    return {
        "step": step,
        "action": {
            "type": "LABOR",
            "params": {"unit_id": unit_id, "labor": labor, "enable": enable},
        },
        "execute": {"accepted": True, "provenance": "dfhack_governed"},
        "metrics": {"pop": 7, "food": 40, "drink": 50},
        "gameplay_proof": {
            "ok": True,
            "changed_tile_count": 0,
            "helper_evidence": {
                "labor_changed": True,
                "labor_before": not enable,
                "labor_after": enable,
            },
        },
        "tick_advance": {"ticks_advanced": 1000},
    }


def test_labor_fingerprint_distinguishes_unit_and_labor_not_enable() -> None:
    base = {"type": "LABOR", "params": {"unit_id": 243, "labor": "brewing", "enable": True}}
    other_unit = {"type": "LABOR", "params": {"unit_id": 248, "labor": "brewing", "enable": True}}
    other_labor = {"type": "LABOR", "params": {"unit_id": 243, "labor": "mine", "enable": True}}
    disable = {"type": "LABOR", "params": {"unit_id": 243, "labor": "brewing", "enable": False}}

    # unit and labor change the bucket; enable direction deliberately does not, so
    # an enable/disable oscillation on one (unit, labor) collapses into one stale
    # fingerprint instead of splitting ~50/50 and slipping under the blocker.
    assert _action_fingerprint(base) == "LABOR:243:brewing"
    assert _action_fingerprint(base) == _action_fingerprint(disable)
    assert (
        len(
            {
                _action_fingerprint(base),
                _action_fingerprint(other_unit),
                _action_fingerprint(other_labor),
            }
        )
        == 3
    )


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


def test_labor_first_flip_credits_progress_then_repeats_do_not() -> None:
    # Alternating enable/disable on one dwarf's labor flips real state every step,
    # but only the first flip of the (unit, labor) target earns progress; every
    # later toggle of the same pair must fall through to the repetition tally.
    records = [
        _labor_record(step, unit_id=243, labor="mining", enable=(step % 2 == 0))
        for step in range(8)
    ]

    flags = _step_progress_flags(records)

    assert flags[0] is True
    assert all(flag is False for flag in flags[1:])


def test_labor_target_dedup_is_per_unit_labor_pair() -> None:
    # A distinct (unit, labor) target earns its own first-flip credit; only the
    # repeats of an already-credited pair are demoted to non-progress.
    records = [
        _labor_record(0, unit_id=243, labor="mining", enable=True),
        _labor_record(1, unit_id=243, labor="mining", enable=False),  # repeat pair
        _labor_record(2, unit_id=248, labor="mining", enable=True),  # new unit
        _labor_record(3, unit_id=243, labor="brewing", enable=True),  # new labor
        _labor_record(4, unit_id=243, labor="mining", enable=True),  # repeat pair
    ]

    assert _step_progress_flags(records) == [True, False, True, True, False]


def test_labor_alternating_churn_triggers_repetitive_policy_blocker() -> None:
    # The exploit the lens names: churn enable/disable on a single (unit, labor)
    # to emit a real flip every step. Post-fix this must pin anti_repetition low
    # and fire the repetitive_policy blocker instead of scoring 10/10.
    records = [
        _labor_record(step, unit_id=243, labor="mining", enable=(step % 2 == 0))
        for step in range(10)
    ]

    rubric = evaluate_trace_records(records)

    # 9/10 repeats share one collapsed LABOR fingerprint -> above the 0.6 blocker.
    assert "repetitive_policy" in rubric["blockers"]
    assert rubric["dimensions"]["anti_repetition"]["score"] < 5.0


def test_farm_fingerprint_distinguishes_target_crop_and_seasons() -> None:
    # Distinct plot, crop, or season set => distinct repetition buckets.
    base = {"type": "FARM", "params": {"building_id": 34, "crop": "RADISH", "seasons": ["summer"]}}
    other_plot = {
        "type": "FARM",
        "params": {"building_id": 35, "crop": "RADISH", "seasons": ["summer"]},
    }
    other_crop = {
        "type": "FARM",
        "params": {"building_id": 34, "crop": "POTATO", "seasons": ["summer"]},
    }
    other_seasons = {
        "type": "FARM",
        "params": {"building_id": 34, "crop": "RADISH", "seasons": ["spring"]},
    }
    fingerprints = {
        _action_fingerprint(base),
        _action_fingerprint(other_plot),
        _action_fingerprint(other_crop),
        _action_fingerprint(other_seasons),
    }
    assert len(fingerprints) == 4


def test_farm_fingerprint_is_season_order_invariant() -> None:
    a = {
        "type": "FARM",
        "params": {"building_id": 34, "crop": "RADISH", "seasons": ["summer", "spring"]},
    }
    b = {
        "type": "FARM",
        "params": {"building_id": 34, "crop": "RADISH", "seasons": ["spring", "summer"]},
    }
    assert _action_fingerprint(a) == _action_fingerprint(b)


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
