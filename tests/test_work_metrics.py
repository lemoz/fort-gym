from __future__ import annotations

from fort_gym.bench.eval import metrics, scoring


def test_work_progress_delta_counts_target_room_progress() -> None:
    baseline = {
        "target_dig_designations": 0,
        "target_floor_tiles": 2,
        "target_wall_tiles": 23,
        "active_dig_jobs": 0,
    }
    current = {
        "target_dig_designations": 10,
        "target_floor_tiles": 7,
        "target_wall_tiles": 18,
        "active_dig_jobs": 1,
    }

    delta = metrics.work_progress_delta(current, baseline)

    assert delta == {
        "target_dig_designations_delta": 10,
        "target_floor_tiles_delta": 5,
        "target_wall_tiles_delta": 5,
        "active_dig_jobs_delta": 1,
        "designation_progress": 11,
        "completion_progress": 5,
        "work_progress": 11,
    }


def test_utility_progress_delta_counts_orders_and_workshops() -> None:
    baseline = {
        "manager_orders_count": 1,
        "manager_orders_amount_left": 1,
        "carpenter_workshops": 0,
    }
    current = {
        "manager_orders_count": 2,
        "manager_orders_amount_left": 6,
        "carpenter_workshops": 1,
    }

    delta = metrics.utility_progress_delta(current, baseline)

    assert delta == {
        "manager_orders_delta": 1,
        "manager_order_quantity_delta": 5,
        "carpenter_workshops_delta": 1,
        "utility_progress": 10,
    }


def test_utility_action_progress_counts_accepted_safe_actions() -> None:
    order_progress = metrics.utility_action_progress(
        {"type": "ORDER", "params": {"job": "bed", "quantity": 5}},
        {"accepted": True},
    )
    oversized_order_progress = metrics.utility_action_progress(
        {"type": "ORDER", "params": {"job": "bed", "quantity": 50}},
        {"accepted": True},
    )
    build_progress = metrics.utility_action_progress(
        {"type": "BUILD", "params": {"kind": "CarpenterWorkshop"}},
        {"accepted": True},
    )
    rejected_progress = metrics.utility_action_progress(
        {"type": "ORDER", "params": {"job": "bed", "quantity": 5}},
        {"accepted": False},
    )

    assert order_progress == {"utility_action_progress": 5}
    assert oversized_order_progress == {"utility_action_progress": 5}
    assert build_progress == {"utility_action_progress": 5}
    assert rejected_progress == {"utility_action_progress": 0}


def test_composite_score_includes_bounded_work_component() -> None:
    without_work = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
        }
    )
    with_work = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
            "work_progress": scoring.TARGET_WORK_PROGRESS,
        }
    )

    assert with_work - without_work == scoring.WORK_WEIGHT


def test_composite_score_includes_bounded_completion_component() -> None:
    without_completion = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
        }
    )
    with_completion = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
            "completion_progress": scoring.TARGET_COMPLETION_PROGRESS,
        }
    )

    assert with_completion - without_completion == scoring.COMPLETION_WEIGHT


def test_composite_score_includes_bounded_utility_component() -> None:
    without_utility = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
        }
    )
    with_utility = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
            "utility_progress": scoring.TARGET_UTILITY_PROGRESS,
        }
    )

    assert with_utility - without_utility == scoring.UTILITY_WEIGHT
