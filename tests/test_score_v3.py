"""Tests for score-v3: demand-capped production utility + plan-agnostic
complexity. See docs/score_v3_proposal.md for the ratified proposal and
docs/score_v3_calibration.md for the v2-vs-v3 calibration table.
"""

from __future__ import annotations

from fort_gym.bench.eval import metrics, scoring


def test_score_version_is_3() -> None:
    assert scoring.SCORE_VERSION == 3


def test_demand_capped_production_pays_full_rate_up_to_population() -> None:
    """26 chairs produced with population 13: 13 pay full rate (13), the
    remaining 13 pay the 20% surplus rate (2.6) -> 15.6 total paid."""

    baseline_goods = {"chair": 0}
    current_goods = {"chair": 26}

    delta = metrics.utility_progress_delta(
        {},
        {},
        current_goods=current_goods,
        baseline_goods=baseline_goods,
        population=13,
    )

    assert delta["produced_goods_delta"] == 26
    assert delta["demand_capped_production"] == 15.6
    assert delta["utility_progress"] == 15.6


def test_demand_capped_production_without_population_pays_raw() -> None:
    """population=None preserves exact v2 behavior: paid == raw."""

    baseline_goods = {"chair": 0}
    current_goods = {"chair": 26}

    delta = metrics.utility_progress_delta(
        {},
        {},
        current_goods=current_goods,
        baseline_goods=baseline_goods,
        population=None,
    )

    assert delta["produced_goods_delta"] == 26
    assert delta["demand_capped_production"] == 26.0
    assert delta["utility_progress"] == 26.0


def test_demand_capped_production_below_demand_pays_full_rate() -> None:
    """Production at or below fort demand pays the full 1.0 rate, no cap."""

    delta = metrics.utility_progress_delta(
        {},
        {},
        current_goods={"bed": 5},
        baseline_goods={"bed": 0},
        population=13,
    )

    assert delta["produced_goods_delta"] == 5
    assert delta["demand_capped_production"] == 5.0


def test_demand_capped_production_caps_per_orderable_type_independently() -> None:
    """Demand applies per orderable good type, not pooled across types."""

    delta = metrics.utility_progress_delta(
        {},
        {},
        current_goods={"chair": 26, "bed": 26},
        baseline_goods={"chair": 0, "bed": 0},
        population=13,
    )

    assert delta["produced_goods_delta"] == 52
    # Each type independently pays 13 full + 13 * 0.2 surplus = 15.6
    assert delta["demand_capped_production"] == 31.2


def test_demand_zero_population_pays_only_surplus_rate() -> None:
    delta = metrics.utility_progress_delta(
        {},
        {},
        current_goods={"chair": 10},
        baseline_goods={"chair": 0},
        population=0,
    )

    assert delta["produced_goods_delta"] == 10
    assert delta["demand_capped_production"] == 2.0


def test_produced_goods_delta_stays_raw_int_regardless_of_population() -> None:
    """produced_goods_delta is gameplay-proof evidence and must remain the
    raw, uncapped integer count — only demand_capped_production/
    utility_progress are demand-capped."""

    delta = metrics.utility_progress_delta(
        {},
        {},
        current_goods={"chair": 26},
        baseline_goods={"chair": 0},
        population=13,
    )

    assert isinstance(delta["produced_goods_delta"], int)
    assert delta["produced_goods_delta"] == 26


def test_complexity_progress_plan_agnostic_when_fort_present() -> None:
    """With fort structure facts present, complexity is driven entirely by
    plan-agnostic flood-fill deltas (rooms/enclosed-spaces/constructions),
    not the legacy fixed-plan tile/space fields."""

    baseline_work = {
        "fortress_complexity_floor_tiles": 0,
        "fortress_complexity_wall_tiles": 28,
        "fortress_complexity_spaces_completed": 0,
    }
    current_work = {
        "fortress_complexity_floor_tiles": 28,
        "fortress_complexity_wall_tiles": 0,
        "fortress_complexity_spaces_completed": 2,
    }
    baseline_fort = {"ok": True, "functional_rooms": 0, "enclosed_spaces": 0, "constructions": 0}
    current_fort = {"ok": True, "functional_rooms": 1, "enclosed_spaces": 1, "constructions": 12}

    delta = metrics.complexity_progress_delta(
        current_work,
        baseline_work,
        current_fort=current_fort,
        baseline_fort=baseline_fort,
    )

    # rooms_delta(1)*15 + fort_spaces_delta(1)*5 + min(12,60)*0.5 = 15+5+6 = 26
    assert delta["complexity_rooms_delta"] == 1
    assert delta["complexity_fort_spaces_delta"] == 1
    assert delta["complexity_constructions_delta"] == 12
    assert delta["complexity_progress"] == 26.0
    # legacy fields are still computed for observability...
    assert delta["complexity_floor_tiles_delta"] == 28
    assert delta["complexity_wall_tiles_delta"] == 28
    assert delta["complexity_spaces_delta"] == 2
    # ...but do not feed complexity_progress. If they did, the legacy
    # formula (complexity_tiles_delta=28) + (spaces_delta=2)*5 = 38 would
    # show up instead of 26.
    assert delta["complexity_progress"] != 38.0


def test_complexity_progress_caps_constructions_at_60() -> None:
    baseline_fort = {"ok": True, "functional_rooms": 0, "enclosed_spaces": 0, "constructions": 0}
    current_fort = {"ok": True, "functional_rooms": 0, "enclosed_spaces": 0, "constructions": 200}

    delta = metrics.complexity_progress_delta(
        {}, {}, current_fort=current_fort, baseline_fort=baseline_fort
    )

    assert delta["complexity_constructions_delta"] == 200
    assert delta["complexity_progress"] == 30.0  # min(200, 60) * 0.5


def test_complexity_progress_legacy_fallback_exact_when_fort_absent() -> None:
    """Old traces / mock backend have no fort dict at all: must fall back to
    the exact legacy computation, unchanged output shape."""

    baseline_work = {
        "fortress_complexity_floor_tiles": 0,
        "fortress_complexity_wall_tiles": 28,
        "fortress_complexity_spaces_completed": 0,
    }
    current_work = {
        "fortress_complexity_floor_tiles": 28,
        "fortress_complexity_wall_tiles": 0,
        "fortress_complexity_spaces_completed": 2,
    }

    delta = metrics.complexity_progress_delta(current_work, baseline_work)

    assert delta == {
        "complexity_floor_tiles_delta": 28,
        "complexity_wall_tiles_delta": 28,
        "complexity_spaces_delta": 2,
        "complexity_progress": 38,
    }


def test_complexity_progress_legacy_fallback_when_fort_not_ok() -> None:
    """A fort dict that failed to read (ok=False) must not be treated as
    plan-agnostic data — falls back to legacy computation."""

    baseline_work = {"fortress_complexity_wall_tiles": 28}
    current_work = {"fortress_complexity_floor_tiles": 28}
    baseline_fort = {"ok": False}
    current_fort = {"ok": False}

    delta = metrics.complexity_progress_delta(
        current_work,
        baseline_work,
        current_fort=current_fort,
        baseline_fort=baseline_fort,
    )

    assert "complexity_rooms_delta" not in delta
    assert delta["complexity_progress"] == 28


# --- v3 amendment (2026-07-07, operator-ratified): production reform -------
# First calibration round showed production_score was the dominant
# unreformed Goodhart vector: task-jobs queue churn paid as production
# capacity, uncapped (ad70df06: 320 points; 7f268bcc: 420 points, vs 30-50
# for both G4-passing runs). Amendment: production pays USABLE-workshop
# deltas only, and production_score is bounded at its 10-point weight.


def test_queue_depth_pays_zero_production() -> None:
    """Stacking workshop task jobs (queue depth) earns zero production —
    queueing is a menu action, not production. The delta stays in the
    output for observability only."""

    baseline = {"carpenter_workshops_usable": 1, "carpenter_workshop_task_jobs": 0}
    current = {"carpenter_workshops_usable": 1, "carpenter_workshop_task_jobs": 32}

    delta = metrics.production_progress_delta(current, baseline)

    assert delta["production_task_jobs_delta"] == 32
    assert delta["production_workshops_delta"] == 0
    assert delta["production_progress"] == 0


def test_usable_workshops_pay_bounded_production() -> None:
    """Usable-workshop deltas pay production, but production_score caps at
    its 10-point weight — proven capacity, not an open-ended meter."""

    delta = metrics.production_progress_delta(
        {"carpenter_workshops_usable": 2},
        {"carpenter_workshops_usable": 0},
    )
    assert delta["production_workshops_delta"] == 2
    assert delta["production_progress"] == 10

    at_target = scoring.score_components(
        {"production_progress": scoring.TARGET_PRODUCTION_PROGRESS}
    )
    far_past_target = scoring.score_components({"production_progress": 160})

    assert at_target["production_score"] == scoring.PRODUCTION_WEIGHT
    # 160 was ad70df06's recorded production_progress (score 320.0 under
    # v2's unbounded scaling); bounded, it pays exactly the weight.
    assert far_past_target["production_score"] == scoring.PRODUCTION_WEIGHT


def test_chair_factory_shape_ranks_below_pass_shape() -> None:
    """Matched fixed conditions and matched item volume: a chair-factory
    profile (single-type monoculture beyond demand + task-jobs queue churn
    + minimal structure) must rank below a pass profile (multi-type
    production within demand + real multi-room structure). This locks the
    combined effect of all three v3 levers: demand cap, plan-agnostic
    complexity, and the production amendment."""

    fixed = {
        "duration_ticks": 100000,
        "peak_pop": 7,
        "drink_availability": 1.0,
        "created_wealth": 1000,
    }

    chair_factory_utility = metrics.utility_progress_delta(
        {"carpenter_workshops_usable": 1, "carpenter_workshop_task_jobs": 32},
        {"carpenter_workshops_usable": 0, "carpenter_workshop_task_jobs": 0},
        current_goods={"chair": 26},
        baseline_goods={"chair": 0},
        population=7,
    )
    chair_factory_production = metrics.production_progress_delta(
        {"carpenter_workshops_usable": 1, "carpenter_workshop_task_jobs": 32},
        {"carpenter_workshops_usable": 0, "carpenter_workshop_task_jobs": 0},
    )
    chair_factory_complexity = metrics.complexity_progress_delta(
        {},
        {},
        current_fort={"ok": True, "functional_rooms": 1, "enclosed_spaces": 1, "constructions": 30},
        baseline_fort={"ok": True, "functional_rooms": 0, "enclosed_spaces": 0, "constructions": 0},
    )

    pass_utility = metrics.utility_progress_delta(
        {"carpenter_workshops_usable": 1},
        {"carpenter_workshops_usable": 0},
        current_goods={"bed": 7, "door": 7, "table": 7, "barrel": 5},
        baseline_goods={"bed": 0, "door": 0, "table": 0, "barrel": 0},
        population=7,
    )
    pass_production = metrics.production_progress_delta(
        {"carpenter_workshops_usable": 1},
        {"carpenter_workshops_usable": 0},
    )
    pass_complexity = metrics.complexity_progress_delta(
        {},
        {},
        current_fort={"ok": True, "functional_rooms": 2, "enclosed_spaces": 2, "constructions": 20},
        baseline_fort={"ok": True, "functional_rooms": 0, "enclosed_spaces": 0, "constructions": 0},
    )

    # Same raw item volume either way — the shapes differ, not the effort.
    assert chair_factory_utility["produced_goods_delta"] == 26
    assert pass_utility["produced_goods_delta"] == 26

    chair_factory_total = scoring.composite_score(
        {
            **fixed,
            "utility_progress": chair_factory_utility["utility_progress"],
            "production_progress": chair_factory_production["production_progress"],
            "complexity_progress": chair_factory_complexity["complexity_progress"],
        }
    )
    pass_total = scoring.composite_score(
        {
            **fixed,
            "utility_progress": pass_utility["utility_progress"],
            "production_progress": pass_production["production_progress"],
            "complexity_progress": pass_complexity["complexity_progress"],
        }
    )

    assert chair_factory_total < pass_total
