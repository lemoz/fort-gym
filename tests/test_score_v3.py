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
