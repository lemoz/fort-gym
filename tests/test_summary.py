from __future__ import annotations

import json
from pathlib import Path

from fort_gym.bench.eval.summary import RunSummary, summarize


def test_summarize_creates_summary(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-1",
            "step": 0,
            "metrics": {"time": 100, "pop": 7, "drink": 25, "food": 40, "wealth": 5000, "dead": 0, "hostiles": False},
            "tick_advance": {"ticks_advanced": 10},
            "events": [
                {
                    "type": "score",
                    "data": {"run_id": "run-1", "step": 0, "value": 5.0, "milestones": [{"k": "DRINK_50", "ts": 100}]},
                }
            ],
        },
        {
            "run_id": "run-1",
            "step": 1,
            "metrics": {"time": 200, "pop": 9, "drink": 10, "food": 35, "wealth": 8000, "dead": 3, "hostiles": True},
            "tick_advance": {"ticks_advanced": 20},
            "events": [
                {
                    "type": "score",
                    "data": {"run_id": "run-1", "step": 1, "value": 6.0, "milestones": [{"k": "HOSTILES", "ts": 200}]},
                }
            ],
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)
    assert isinstance(summary, RunSummary)
    assert summary.run_id == "run-1"
    assert summary.steps == 2
    assert summary.duration_ticks == 30
    assert isinstance(summary.total_score, float)
    assert summary.milestones

    summary_path = trace_path.with_name("summary.json")
    assert summary_path.exists()


def test_summarize_prefers_run_elapsed_ticks(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-2",
            "step": 0,
            "metrics": {
                "time": 16801,
                "run_elapsed_ticks": 0,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
            },
            "tick_advance": {"ticks_advanced": 0},
            "events": [],
        },
        {
            "run_id": "run-2",
            "step": 1,
            "metrics": {
                "time": 17001,
                "run_elapsed_ticks": 200,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
            },
            "tick_advance": {"ticks_advanced": 200},
            "events": [],
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)

    assert summary.duration_ticks == 200
    assert summary.survival_score == 2.5
    assert summary.total_score < 53.5


def test_summarize_blocks_assisted_duration_score(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-assisted",
            "step": 0,
            "metrics": {
                "time": 16801,
                "run_elapsed_ticks": 0,
                "observed_run_elapsed_ticks": 500,
                "score_duration_blocked": True,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
                "work_progress": 0,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "complexity_progress": 0,
            },
            "tick_advance": {"ticks_advanced": 500},
            "events": [],
        }
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)

    assert summary.duration_ticks == 0
    assert summary.survival_score == 0.0
    assert summary.work_progress == 0
    assert summary.total_score == 23.5


def test_summarize_unblocks_duration_after_real_keystroke_progress(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-keystroke",
            "step": 0,
            "metrics": {
                "time": 16801,
                "run_elapsed_ticks": 0,
                "observed_run_elapsed_ticks": 200,
                "score_duration_blocked": True,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
                "work_progress": 0,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "complexity_progress": 0,
            },
            "tick_advance": {"ticks_advanced": 200},
            "events": [],
        },
        {
            "run_id": "run-keystroke",
            "step": 1,
            "metrics": {
                "time": 17001,
                "run_elapsed_ticks": 400,
                "score_duration_blocked": False,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
                "work_progress": 9,
                "designation_progress": 9,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "complexity_progress": 0,
                "ui_work_progress": 9,
                "ui_designation_progress": 9,
                "ui_completion_progress": 6,
                "ui_excavation_progress": 6,
                "ui_target_dig_designations_delta": 9,
                "ui_target_floor_removed_delta": 6,
            },
            "tick_advance": {"ticks_advanced": 200},
            "events": [],
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)

    assert summary.duration_ticks == 400
    assert summary.survival_score == 5.0
    assert summary.work_progress == 9
    assert summary.ui_work_progress == 9
    assert summary.ui_designation_progress == 9
    assert summary.ui_completion_progress == 6
    assert summary.ui_excavation_progress == 6
    assert summary.ui_target_dig_designations_delta == 9
    assert summary.ui_target_floor_removed_delta == 6


def test_summarize_tracks_work_progress(tmp_path) -> None:
    trace_path = Path(tmp_path) / "trace.jsonl"
    records = [
        {
            "run_id": "run-work",
            "step": 0,
            "metrics": {
                "time": 100,
                "run_elapsed_ticks": 500,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
                "work_progress": 10,
                "designation_progress": 10,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "complexity_progress": 0,
                "target_dig_designations_delta": 10,
                "target_floor_tiles_delta": 0,
                "target_wall_tiles_delta": 0,
                "active_dig_jobs_delta": 1,
                "utility_action_progress": 0,
                "complexity_floor_tiles_delta": 0,
                "complexity_wall_tiles_delta": 0,
                "complexity_spaces_delta": 0,
                "manager_orders_delta": 0,
                "manager_order_quantity_delta": 0,
                "carpenter_workshops_delta": 0,
                "production_workshops_delta": 0,
                "work": {
                    "target_hidden_tiles": 25,
                    "citizens_total": 7,
                    "miners_total": 1,
                    "citizens_on_target_z": 0,
                    "target_z": 0,
                    "window_z": 177,
                    "fortress_plan_name": "two_room_workshop",
                    "fortress_connector_floor_tiles": 0,
                    "fortress_workshop_room_floor_tiles": 0,
                    "fortress_complexity_floor_tiles": 0,
                    "fortress_complexity_wall_tiles": 28,
                    "fortress_complexity_spaces_completed": 0,
                    "manager_orders_count": 0,
                    "manager_orders_amount_left": 0,
                    "carpenter_workshops": 0,
                },
            },
            "tick_advance": {"ticks_advanced": 500},
            "events": [],
        },
        {
            "run_id": "run-work",
            "step": 1,
            "metrics": {
                "time": 600,
                "run_elapsed_ticks": 1000,
                "pop": 7,
                "drink": 60,
                "food": 45,
                "wealth": 9,
                "dead": 0,
                "hostiles": False,
                "work_progress": 25,
                "designation_progress": 25,
                "completion_progress": 8,
                "utility_progress": 5,
                "production_progress": 5,
                "complexity_progress": 38,
                "target_dig_designations_delta": 25,
                "target_floor_tiles_delta": 8,
                "target_wall_tiles_delta": 8,
                "active_dig_jobs_delta": 1,
                "utility_action_progress": 5,
                "complexity_floor_tiles_delta": 28,
                "complexity_wall_tiles_delta": 28,
                "complexity_spaces_delta": 2,
                "manager_orders_delta": 1,
                "manager_order_quantity_delta": 5,
                "carpenter_workshops_delta": 1,
                "production_workshops_delta": 1,
                "work": {
                    "target_hidden_tiles": 0,
                    "citizens_total": 7,
                    "miners_total": 1,
                    "citizens_on_target_z": 0,
                    "target_z": 0,
                    "window_z": 177,
                    "fortress_plan_name": "two_room_workshop",
                    "fortress_connector_floor_tiles": 3,
                    "fortress_workshop_room_floor_tiles": 25,
                    "fortress_complexity_floor_tiles": 28,
                    "fortress_complexity_wall_tiles": 0,
                    "fortress_complexity_spaces_completed": 2,
                    "manager_orders_count": 1,
                    "manager_orders_amount_left": 5,
                    "carpenter_workshops": 1,
                },
            },
            "tick_advance": {"ticks_advanced": 500},
            "events": [],
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    summary = summarize(trace_path)

    assert summary.work_progress == 25
    assert summary.population_score == 3.5
    assert summary.wealth_score == 0.0
    assert summary.work_score == 10.0
    assert summary.designation_progress == 25
    assert summary.completion_progress == 8
    assert summary.completion_score == 3.2
    assert summary.utility_progress == 5
    assert summary.utility_score == 10.0
    assert summary.production_progress == 5
    assert summary.production_score == 10.0
    assert summary.complexity_progress == 38
    assert summary.complexity_score == 15.0
    assert summary.target_dig_designations_delta == 25
    assert summary.target_floor_tiles_delta == 8
    assert summary.target_wall_tiles_delta == 8
    assert summary.active_dig_jobs_delta == 1
    assert summary.utility_action_progress == 5
    assert summary.complexity_floor_tiles_delta == 28
    assert summary.complexity_wall_tiles_delta == 28
    assert summary.complexity_spaces_delta == 2
    assert summary.manager_orders_delta == 1
    assert summary.manager_order_quantity_delta == 5
    assert summary.carpenter_workshops_delta == 1
    assert summary.production_workshops_delta == 1
    assert summary.manager_orders_count == 1
    assert summary.manager_orders_amount_left == 5
    assert summary.carpenter_workshops == 1
    assert summary.target_hidden_tiles == 25
    assert summary.citizens_total == 7
    assert summary.miners_total == 1
    assert summary.citizens_on_target_z == 0
    assert summary.target_z == 0
    assert summary.window_z == 177
    assert summary.fortress_plan_name == "two_room_workshop"
    assert summary.fortress_connector_floor_tiles == 3
    assert summary.fortress_workshop_room_floor_tiles == 25
    assert summary.fortress_complexity_floor_tiles == 28
    assert summary.fortress_complexity_wall_tiles == 0
    assert summary.fortress_complexity_spaces_completed == 2


def test_rubric_does_not_flag_progress_backed_waits() -> None:
    from fort_gym.bench.eval.rubric import evaluate_trace_records

    records = []
    for step in range(10):
        records.append(
            {
                "step": step,
                "action": {"type": "WAIT", "params": {}},
                "execute": {"accepted": True, "provenance": "dfhack_governed"},
                "metrics": {"pop": 7, "food": 40, "drink": 50},
                "gameplay_proof": {"ok": True, "changed_tile_count": 4},
                "tick_advance": {"ticks_advanced": 1000},
            }
        )

    rubric = evaluate_trace_records(records)

    assert "repetitive_policy" not in rubric["blockers"]
    assert rubric["dimensions"]["anti_repetition"]["score"] == 10.0


def test_rubric_still_flags_repetition_without_state_change() -> None:
    from fort_gym.bench.eval.rubric import evaluate_trace_records

    records = []
    for step in range(10):
        records.append(
            {
                "step": step,
                "action": {"type": "WAIT", "params": {}},
                "execute": {"accepted": True, "provenance": "dfhack_governed"},
                "metrics": {"pop": 7, "food": 40, "drink": 50},
                "gameplay_proof": {"ok": False, "changed_tile_count": 0},
                "tick_advance": {"ticks_advanced": 1000},
            }
        )

    rubric = evaluate_trace_records(records)

    assert "repetitive_policy" in rubric["blockers"]
    assert rubric["dimensions"]["anti_repetition"]["score"] < 5.0


def test_rubric_credits_plan_agnostic_fort_structure() -> None:
    from fort_gym.bench.eval.rubric import evaluate_trace_records

    records = [
        {
            "step": step,
            "action": {"type": "WAIT", "params": {}},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {
                "pop": 7,
                "food": 40,
                "drink": 50,
                "fort_enclosed_spaces": 2,
                "fort_functional_rooms": 2,
                "fort_constructions": 20,
            },
            "gameplay_proof": {"ok": True, "changed_tile_count": 1},
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(6)
    ]

    rubric = evaluate_trace_records(records)

    assert "no_fort_structure" not in rubric["blockers"]
    assert rubric["dimensions"]["shelter_layout"]["score"] >= 9.0
    assert any(
        "fort_functional_rooms=2" in item
        for item in rubric["dimensions"]["shelter_layout"]["evidence"]
    )


def test_rubric_flags_missing_fort_structure() -> None:
    from fort_gym.bench.eval.rubric import evaluate_trace_records

    records = [
        {
            "step": step,
            "action": {"type": "ORDER", "params": {"job": "bed", "quantity": 2}},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {"pop": 7, "food": 40, "drink": 50},
            "gameplay_proof": {"ok": True, "changed_tile_count": 1},
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(6)
    ]

    rubric = evaluate_trace_records(records)

    assert "no_fort_structure" in rubric["blockers"]
    assert rubric["dimensions"]["shelter_layout"]["score"] <= 2.0


def test_rubric_breadth_and_coherence_credit_off_plan_structure() -> None:
    """Rooms built anywhere (not just the retired two_room_workshop rects)
    must earn fortress_breadth and plan_coherence credit via the
    plan-agnostic flood-fill facts (fort_enclosed_spaces / fort_constructions /
    fort_functional_rooms), matching the pattern already used by
    shelter_layout."""
    from fort_gym.bench.eval.rubric import evaluate_trace_records

    records = [
        {
            "step": step,
            "action": {"type": "DIG", "params": {"area": [10, 10, 5], "size": [3, 3, 1]}, "objective": "expand fort"},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {
                "pop": 7,
                "food": 40,
                "drink": 50,
                "work_progress": 10,
                # legacy fixed-plan fields intentionally absent/zero: this
                # room was not built inside the retired two_room_workshop rects
                "fortress_complexity_floor_tiles": 0,
                "fortress_complexity_wall_tiles": 0,
                "fortress_complexity_spaces_completed": 0,
                "complexity_progress": 0,
                # plan-agnostic facts from hook/fort_metrics.lua
                "fort_enclosed_spaces": 1,
                "fort_functional_rooms": 1,
                "fort_constructions": 12,
            },
            "gameplay_proof": {"ok": True, "changed_tile_count": 1},
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(6)
    ]

    rubric = evaluate_trace_records(records)

    breadth = rubric["dimensions"]["fortress_breadth"]
    coherence = rubric["dimensions"]["plan_coherence"]

    assert breadth["score"] > 0.0
    assert any("fort_constructions=12" in item for item in breadth["evidence"])
    assert any("fort_enclosed_spaces=1" in item for item in breadth["evidence"])
    assert not any("complexity_progress" in item for item in breadth["evidence"])

    assert coherence["score"] > 0.0
    assert any("chain=1/" in item for item in coherence["evidence"])


def test_rubric_breadth_and_coherence_ignore_legacy_complexity_fields() -> None:
    """A run that only ever produced legacy fortress_complexity_* signal
    (the retired hardcoded plan) and no plan-agnostic fort_* structure must
    NOT receive fortress_breadth/plan_coherence credit for that legacy
    signal — those two dimensions are now plan-agnostic."""
    from fort_gym.bench.eval.rubric import evaluate_trace_records

    records = [
        {
            "step": step,
            "action": {"type": "ORDER", "params": {"job": "bed", "quantity": 2}},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {
                "pop": 7,
                "food": 40,
                "drink": 50,
                # legacy plan signal only, no fort_* plan-agnostic facts at all
                "fortress_complexity_floor_tiles": 28,
                "fortress_complexity_wall_tiles": 0,
                "fortress_complexity_spaces_completed": 2,
                "complexity_progress": 38,
            },
            "gameplay_proof": {"ok": True, "changed_tile_count": 1},
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(6)
    ]

    rubric = evaluate_trace_records(records)

    breadth = rubric["dimensions"]["fortress_breadth"]
    coherence = rubric["dimensions"]["plan_coherence"]

    assert any("fort_constructions=0" in item for item in breadth["evidence"])
    assert any("fort_enclosed_spaces=0" in item for item in breadth["evidence"])
    assert any("chain=0/" in item for item in coherence["evidence"])


def test_rubric_flags_order_spam_as_repetitive() -> None:
    """Regression for the DeepSeek exploit: queue-only proofs must not
    exempt repeated identical orders from the repetition blocker."""
    from fort_gym.bench.eval.rubric import evaluate_trace_records

    records = [
        {
            "step": step,
            "action": {"type": "ORDER", "params": {"job": "bed", "quantity": 5}},
            "execute": {"accepted": True, "provenance": "dfhack_governed"},
            "metrics": {"pop": 7, "food": 40, "drink": 50},
            "gameplay_proof": {
                "ok": True,
                "changed_tile_count": 0,
                "state_deltas": {},
                "helper_evidence": {"created_job_ids": [step * 2 + 5], "manager_recorded": True},
            },
            "tick_advance": {"ticks_advanced": 1000},
        }
        for step in range(10)
    ]

    rubric = evaluate_trace_records(records)

    assert "repetitive_policy" in rubric["blockers"]


def test_proof_shows_world_change_recognizes_still_workshop_construction() -> None:
    """A real Still built is world change (exempt from the repetition
    tally), same treatment as before/after carpenter workshops -- via the
    generalized before/after_workshops_of_kind fields build_workshop.lua
    now emits for every kind it supports."""
    from fort_gym.bench.eval.rubric import _proof_shows_world_change

    real_still = {
        "changed_tile_count": 0,
        "helper_evidence": {"before_workshops_of_kind": 0, "after_workshops_of_kind": 1},
    }
    assert _proof_shows_world_change(real_still) is True

    no_change = {
        "changed_tile_count": 0,
        "helper_evidence": {"before_workshops_of_kind": 1, "after_workshops_of_kind": 1},
    }
    assert _proof_shows_world_change(no_change) is False


def test_action_fingerprint_distinguishes_still_and_brew() -> None:
    """Fingerprints must not collide Still with CarpenterWorkshop, or brew
    with the carpenter-scoped items -- each is its own repetition bucket."""
    from fort_gym.bench.eval.rubric import _action_fingerprint

    still_build = {"type": "BUILD", "params": {"kind": "Still", "x": 88, "y": 96, "z": 177}}
    carpenter_build = {
        "type": "BUILD",
        "params": {"kind": "CarpenterWorkshop", "x": 88, "y": 96, "z": 177},
    }
    assert _action_fingerprint(still_build) != _action_fingerprint(carpenter_build)

    brew_order = {"type": "ORDER", "params": {"job": "brew", "quantity": 3}}
    bed_order = {"type": "ORDER", "params": {"job": "bed", "quantity": 3}}
    assert _action_fingerprint(brew_order) != _action_fingerprint(bed_order)
