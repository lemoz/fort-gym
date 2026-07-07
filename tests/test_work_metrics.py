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
        "ui_target_floor_removed_delta": 0,
        "ui_target_wall_tiles_delta": 4,
        "ui_designation_progress": 9,
        "ui_completion_progress": 4,
        "ui_excavation_progress": 4,
        "ui_work_progress": 9,
    }


def test_ui_work_progress_delta_counts_floor_excavation() -> None:
    baseline = {
        "target_rect": [88, 83, 177, 102, 97, 177],
        "target_dig_designations": 8,
        "target_floor_tiles": 176,
        "target_wall_tiles": 8,
    }
    current = {
        "target_rect": [88, 83, 177, 102, 97, 177],
        "target_dig_designations": 0,
        "target_floor_tiles": 170,
        "target_wall_tiles": 8,
    }

    delta = metrics.ui_work_progress_delta(current, baseline)

    assert delta == {
        "ui_target_dig_designations_delta": 0,
        "ui_target_floor_tiles_delta": 0,
        "ui_target_floor_removed_delta": 6,
        "ui_target_wall_tiles_delta": 0,
        "ui_designation_progress": 0,
        "ui_completion_progress": 6,
        "ui_excavation_progress": 6,
        "ui_work_progress": 6,
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


def test_utility_progress_delta_counts_orders_and_usable_workshops() -> None:
    baseline = {
        "manager_orders_count": 1,
        "manager_orders_amount_left": 1,
        "carpenter_workshops_planned": 0,
        "carpenter_workshops_usable": 0,
    }
    current = {
        "manager_orders_count": 2,
        "manager_orders_amount_left": 6,
        "carpenter_workshops_planned": 1,
        "carpenter_workshops_usable": 1,
    }

    delta = metrics.utility_progress_delta(
        current,
        baseline,
        current_goods={"bed": 3, "door": 1},
        baseline_goods={"bed": 1, "door": 1},
    )

    # score-v2: queue deltas are observability only; utility pays produced
    # goods (2 new beds) plus workshops that became usable (5)
    assert delta == {
        "manager_orders_delta": 1,
        "manager_order_quantity_delta": 5,
        "carpenter_workshops_planned_delta": 1,
        "carpenter_workshops_usable_delta": 1,
        "carpenter_workshop_task_jobs_delta": 0,
        "carpenter_workshops_delta": 1,
        "produced_goods_delta": 2,
        "demand_capped_production": 2.0,
        "utility_progress": 7.0,
    }


def test_production_progress_delta_counts_usable_workshops() -> None:
    baseline = {"carpenter_workshops_planned": 0, "carpenter_workshops_usable": 0}
    current = {"carpenter_workshops_planned": 1, "carpenter_workshops_usable": 1}

    delta = metrics.production_progress_delta(current, baseline)

    assert delta == {
        "production_workshops_planned_delta": 1,
        "production_workshops_delta": 1,
        "production_task_jobs_delta": 0,
        "production_progress": 5,
    }


def test_planned_workshop_without_usable_proof_does_not_score_production() -> None:
    baseline = {"carpenter_workshops_planned": 0, "carpenter_workshops_usable": 0}
    current = {"carpenter_workshops_planned": 1, "carpenter_workshops_usable": 0}

    utility_delta = metrics.utility_progress_delta(current, baseline)
    production_delta = metrics.production_progress_delta(current, baseline)

    assert utility_delta["carpenter_workshops_planned_delta"] == 1
    assert utility_delta["carpenter_workshops_delta"] == 0
    assert utility_delta["utility_progress"] == 0
    assert production_delta["production_workshops_planned_delta"] == 1
    assert production_delta["production_workshops_delta"] == 0
    assert production_delta["production_progress"] == 0


def test_workshop_task_job_counts_as_usable_production_proof() -> None:
    baseline = {"carpenter_workshop_task_jobs": 0}
    current = {"carpenter_workshop_task_jobs": 1}

    utility_delta = metrics.utility_progress_delta(current, baseline)
    production_delta = metrics.production_progress_delta(current, baseline)

    assert utility_delta["carpenter_workshop_task_jobs_delta"] == 1
    assert utility_delta["carpenter_workshops_delta"] == 1
    # score-v2: a queued task job alone is not utility — nothing was produced
    # and no workshop became usable
    assert utility_delta["utility_progress"] == 0
    assert production_delta["production_task_jobs_delta"] == 1
    assert production_delta["production_workshops_delta"] == 1
    assert production_delta["production_progress"] == 5


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


def test_composite_score_includes_scaled_work_component() -> None:
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


def test_composite_score_includes_scaled_completion_component() -> None:
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


def test_composite_score_includes_scaled_utility_component() -> None:
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


def test_composite_score_includes_scaled_production_component() -> None:
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


def test_composite_score_includes_scaled_complexity_component() -> None:
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


def test_composite_score_makes_first_workshop_item_wealth_visible() -> None:
    components = scoring.score_components({"wealth": 150})

    assert components["wealth_score"] >= 2.0


def test_composite_score_prefers_zero_created_wealth_over_absolute_wealth() -> None:
    components = scoring.score_components({"created_wealth": 0, "wealth": 150})

    assert components["wealth_score"] == 0.0


def test_composite_score_continues_past_previous_caps() -> None:
    target_score = scoring.composite_score(
        {
            "time": scoring.TARGET_SURVIVAL_TICKS,
            "pop": scoring.POP_CAP,
            "drink": scoring.DRINK_THRESHOLD,
            "wealth": scoring.WEALTH_TARGET,
            "work_progress": scoring.TARGET_WORK_PROGRESS,
            "completion_progress": scoring.TARGET_COMPLETION_PROGRESS,
            "utility_progress": scoring.TARGET_UTILITY_PROGRESS,
            "production_progress": scoring.TARGET_PRODUCTION_PROGRESS,
            "complexity_progress": scoring.TARGET_COMPLEXITY_PROGRESS,
        }
    )
    doubled_score = scoring.composite_score(
        {
            "time": scoring.TARGET_SURVIVAL_TICKS * 2,
            "pop": scoring.POP_CAP * 2,
            "drink": scoring.DRINK_THRESHOLD * 2,
            "wealth": scoring.WEALTH_TARGET * 2,
            "work_progress": scoring.TARGET_WORK_PROGRESS * 2,
            "completion_progress": scoring.TARGET_COMPLETION_PROGRESS * 2,
            "utility_progress": scoring.TARGET_UTILITY_PROGRESS * 2,
            "production_progress": scoring.TARGET_PRODUCTION_PROGRESS * 2,
            "complexity_progress": scoring.TARGET_COMPLEXITY_PROGRESS * 2,
        }
    )

    assert target_score == 145.0
    assert doubled_score == 215.0


def test_read_job_metrics_enforces_rect_bounds(monkeypatch) -> None:
    from fort_gym.bench import dfhack_backend

    calls: list[tuple] = []

    def fake_run_lua_file(path, *args, **kwargs):
        calls.append((path, args))
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    assert dfhack_backend.read_job_metrics((0, 0, 0, 40, 0, 0)) == {
        "ok": False,
        "error": "rect_too_large",
    }
    assert dfhack_backend.read_job_metrics((0, 0, 0, 5, 5, 1)) == {
        "ok": False,
        "error": "z_span_not_supported",
    }
    assert not calls

    assert dfhack_backend.read_job_metrics() == {"ok": True}
    assert calls[-1][1] == ()

    assert dfhack_backend.read_job_metrics((0, 0, 7, 5, 5, 7)) == {"ok": True}
    assert calls[-1][1] == ("0", "0", "7", "5", "5", "7")


def test_place_furniture_enforces_kind_and_delegates_locality_to_hook(monkeypatch) -> None:
    from fort_gym.bench import dfhack_backend

    calls: list[tuple] = []

    def fake_run_lua_file(path, *args, **kwargs):
        calls.append((path, args))
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    assert dfhack_backend.place_furniture("Throne", 1, 1, 0) == {
        "ok": False,
        "error": "invalid_kind",
    }
    assert not calls

    placed = dfhack_backend.place_furniture("Bed", 51, 36, 0)
    assert placed == {"ok": True}
    assert calls[-1][1] == ("Bed", "51", "36", "0")


def test_build_construction_invalid_kind(monkeypatch) -> None:
    from fort_gym.bench import dfhack_backend

    calls: list[tuple] = []

    def fake_run_lua_file(path, *args, **kwargs):
        calls.append((path, args))
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    assert dfhack_backend.build_construction("Throne", 1, 1, 0) == {
        "ok": False,
        "error": "invalid_kind",
    }
    assert not calls


def test_build_construction_rejects_too_many_tiles(monkeypatch) -> None:
    from fort_gym.bench import dfhack_backend

    calls: list[tuple] = []

    def fake_run_lua_file(path, *args, **kwargs):
        calls.append((path, args))
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    too_many = dfhack_backend.build_construction("Wall", 0, 0, 0, x2=10, y2=0)
    assert too_many == {"ok": False, "error": "too_many_tiles"}
    assert not calls


def test_build_construction_passes_through_valid_line(monkeypatch) -> None:
    from fort_gym.bench import dfhack_backend

    calls: list[tuple] = []

    def fake_run_lua_file(path, *args, **kwargs):
        calls.append((path, args, kwargs))
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.build_construction("Floor", 5, 5, 1, x2=9, y2=5)
    assert result == {"ok": True}
    assert calls[-1][1] == ("Floor", "5", "5", "1", "9", "5")
    assert calls[-1][2] == {"timeout": 10.0}



def test_utility_progress_ignores_order_spam_without_production() -> None:
    """Regression for the DeepSeek exploit: 91 queued orders, ~nothing made."""
    baseline = {
        "manager_orders_count": 0,
        "manager_orders_amount_left": 0,
        "carpenter_workshops_usable": 1,
    }
    current = {
        "manager_orders_count": 91,
        "manager_orders_amount_left": 180,
        "carpenter_workshops_usable": 1,
    }

    delta = metrics.utility_progress_delta(
        current,
        baseline,
        current_goods={"bed": 2},
        baseline_goods={"bed": 0},
    )

    assert delta["manager_orders_delta"] == 91
    assert delta["produced_goods_delta"] == 2
    assert delta["utility_progress"] == 2


def test_utility_progress_without_goods_data_pays_usable_workshops_only() -> None:
    delta = metrics.utility_progress_delta(
        {"manager_orders_count": 10, "carpenter_workshops_usable": 1},
        {"manager_orders_count": 0, "carpenter_workshops_usable": 0},
    )

    assert delta["produced_goods_delta"] == 0
    assert delta["utility_progress"] == 5
