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
        "work_progress": 11,
    }


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
