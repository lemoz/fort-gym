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


def test_ui_work_progress_delta_counts_fixed_rect_progress() -> None:
    baseline = {
        "target_rect": [100, 100, 177, 114, 114, 177],
        "target_dig_designations": 0,
        "target_floor_tiles": 0,
        "target_wall_tiles": 225,
    }
    current = {
        "target_rect": [100, 100, 177, 114, 114, 177],
        "target_dig_designations": 9,
        "target_floor_tiles": 4,
        "target_wall_tiles": 221,
    }

    delta = metrics.ui_work_progress_delta(current, baseline)

    assert delta == {
        "ui_target_dig_designations_delta": 9,
        "ui_target_floor_tiles_delta": 4,
        "ui_target_wall_tiles_delta": 4,
        "ui_designation_progress": 9,
        "ui_completion_progress": 4,
        "ui_work_progress": 9,
    }


def test_ui_work_progress_delta_rejects_changed_rect() -> None:
    baseline = {
        "target_rect": [100, 100, 177, 114, 114, 177],
        "target_dig_designations": 0,
    }
    current = {
        "target_rect": [101, 100, 177, 115, 114, 177],
        "target_dig_designations": 9,
    }

    delta = metrics.ui_work_progress_delta(current, baseline)

    assert delta["ui_work_progress"] == 0
    assert delta["ui_target_dig_designations_delta"] == 0


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


def test_production_progress_delta_counts_workshop_placements() -> None:
    baseline = {"carpenter_workshops": 0}
    current = {"carpenter_workshops": 1}

    delta = metrics.production_progress_delta(current, baseline)

    assert delta == {
        "production_workshops_delta": 1,
        "production_progress": 5,
    }


def test_complexity_progress_delta_counts_second_room_shape() -> None:
    baseline = {
        "fortress_complexity_floor_tiles": 0,
        "fortress_complexity_wall_tiles": 28,
        "fortress_complexity_spaces_completed": 0,
    }
    current = {
        "fortress_complexity_floor_tiles": 28,
        "fortress_complexity_wall_tiles": 0,
        "fortress_complexity_spaces_completed": 2,
    }

    delta = metrics.complexity_progress_delta(current, baseline)

    assert delta == {
        "complexity_floor_tiles_delta": 28,
        "complexity_wall_tiles_delta": 28,
        "complexity_spaces_delta": 2,
        "complexity_progress": 38,
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


def test_composite_score_includes_bounded_production_component() -> None:
    without_production = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
        }
    )
    with_production = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
            "production_progress": scoring.TARGET_PRODUCTION_PROGRESS,
        }
    )

    assert with_production - without_production == scoring.PRODUCTION_WEIGHT


def test_composite_score_includes_bounded_complexity_component() -> None:
    without_complexity = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
        }
    )
    with_complexity = scoring.composite_score(
        {
            "duration_ticks": 0,
            "peak_pop": 0,
            "drink_availability": 0,
            "created_wealth": 0,
            "complexity_progress": scoring.TARGET_COMPLEXITY_PROGRESS,
        }
    )

    assert with_complexity - without_complexity == scoring.COMPLEXITY_WEIGHT
