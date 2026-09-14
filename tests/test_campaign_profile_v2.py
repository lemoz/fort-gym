"""Projection of the native v2 shape observed in the local year-two campaign."""

from copy import deepcopy

import pytest

from fort_gym.bench.eval.campaign_profile import metrics_from_state


def native_v2():
    return {
        "population": 7,
        "stocks": {"food": 45, "drink": 60, "wood": 3, "stone": 0},
        "campaign_observation_quality": {
            "schema_version": "fortgym.campaign-observation-quality/v2",
            "native_population_and_stock_value_types_validated": True,
            "population_source": "active living native citizens",
        },
        "stock_observations": {
            "schema_version": "fortgym.stock-observations/v1",
            "drink": {
                "source": "world.items.other.IN_PLAY DRINK stack_size",
                "complete": True,
                "units": 60,
            },
            "food": {"source": "ui.tasks.food counters", "freshness": "unverified"},
        },
    }


def test_v2_native_population_and_drink_are_reported_without_promoting_ui_estimates():
    state = native_v2()
    original = deepcopy(state)
    metrics = metrics_from_state(state)
    assert metrics["population"] == 7
    assert metrics["drink_stock"] == 60
    assert all(metrics[key] is None for key in ("food_stock", "wood_stock", "stone_stock"))
    assert state == original


def test_v2_confirmed_zero_counts_are_not_unknown():
    state = native_v2()
    state["population"] = state["stocks"]["drink"] = 0
    state["stock_observations"]["drink"]["units"] = 0
    metrics = metrics_from_state(state)
    assert metrics["population"] == metrics["drink_stock"] == 0


@pytest.mark.parametrize("value", [True, False, -1, "7", None])
def test_v2_invalid_population_never_becomes_a_count(value):
    state = native_v2()
    state["population"] = value
    assert metrics_from_state(state)["population"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("source", "ui.tasks.drink"),
        ("complete", False),
        ("complete", 1),
        ("units", None),
        ("units", True),
        ("units", -1),
        ("units", "60"),
        ("units", 61),
    ],
)
def test_v2_incomplete_untyped_or_disagreeing_drink_evidence_is_unknown(key, value):
    state = native_v2()
    state["stock_observations"]["drink"][key] = value
    assert metrics_from_state(state)["drink_stock"] is None
    assert metrics_from_state(state)["population"] == 7


def test_v2_requires_recognized_stock_and_population_provenance():
    state = native_v2()
    state["stock_observations"]["schema_version"] = "unknown"
    state["campaign_observation_quality"]["population_source"] = "UI estimate"
    metrics = metrics_from_state(state)
    assert metrics["drink_stock"] is None and metrics["population"] is None
    state = native_v2()
    state["campaign_observation_quality"]["native_population_and_stock_value_types_validated"] = 1
    metrics = metrics_from_state(state)
    assert metrics["drink_stock"] is None and metrics["population"] is None
