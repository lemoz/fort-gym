"""Synthetic publication tests; these fixtures are not native-run evidence."""

import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from fort_gym.bench.api.campaign_food_outcomes import PROFILE, food_inventory_outcome
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


@pytest.fixture
def publication():
    return {
        "private_measurement_profile": PROFILE,
        "food_inventory": {
            "schema_version": "fortgym.keyboard-food-inventory-outcome/v1",
            "measurement_profile": PROFILE,
            "independent_private_review_passed": True,
            "historical_food_unknowns_preserved": True,
            "model_requests_remain_screen_only": True,
            "scope": "native_edible_raw_predicate_excluding_drinks",
            "accessibility": "not_assessed",
            "production_and_consumption": "not_measured",
            "sustainability": "not_established",
            "initial_checkpoint_cursor": 503,
            "observed_boundaries": 65,
            "complete_measurements": 65,
            "unknown_measurements": 0,
            "initial_units": 27,
            "final_units": 26,
        },
    }


def test_synthetic_food_projection_does_not_change_historical_unknowns(evidence_root, publication):
    path = evidence_root / "experiments/evidence" / records.CONTINUATIONS[4]
    source = json.loads(path.read_text())
    source.update(publication)
    source["food_inventory"]["items"] = "private-items"
    source["food_inventory"]["raw_error"] = "private-error"
    path.write_text(json.dumps(source))
    rows = records.keyboard_campaign_records(evidence_root)["continuations"]
    assert rows[4]["food_inventory"]["initial_units"] == 27
    assert rows[4]["food_inventory"]["final_units"] == 26
    assert rows[4]["outcome_counts"]["food_stock"] is None
    assert all("food_inventory" not in row for row in rows[:4])
    assert "private-" not in json.dumps(rows)


@pytest.mark.parametrize("initial,final,unknown", [(0, 0, 0), (None, 0, 1), (0, None, 1),
                                                  (None, None, 65)])
def test_unknown_and_zero_are_distinct(publication, initial, final, unknown):
    value = publication["food_inventory"]
    value.update(initial_units=initial, final_units=final,
                 unknown_measurements=unknown, complete_measurements=65 - unknown)
    projected = food_inventory_outcome(publication, 64, 503)
    assert projected["initial_units"] == initial
    assert projected["final_units"] == final
    assert projected["unknown_measurements"] == unknown


@pytest.mark.parametrize("field,value", [
    ("schema_version", "other"), ("measurement_profile", "screen-estimate"),
    ("independent_private_review_passed", 1), ("historical_food_unknowns_preserved", False),
    ("model_requests_remain_screen_only", False), ("scope", "accessible-food"),
    ("accessibility", "verified"), ("production_and_consumption", "measured"),
    ("sustainability", "established"), ("initial_checkpoint_cursor", 567),
    ("observed_boundaries", 64), ("complete_measurements", 64),
    ("unknown_measurements", 1), ("initial_units", True), ("final_units", "27"),
    ("final_units", -1), ("final_units", 2**53), ("initial_units", 27.0),
    ("observed_boundaries", True), ("complete_measurements", None),
    ("unknown_measurements", -1),
])
def test_food_projection_rejects_invented_proof_or_inconsistent_counts(publication, field, value):
    publication["food_inventory"][field] = value
    with pytest.raises(ValueError):
        food_inventory_outcome(publication, 64, 503)


@pytest.mark.parametrize("field", ["initial_units", "final_units", "initial_checkpoint_cursor",
                                  "independent_private_review_passed", "measurement_profile"])
def test_required_fields_cannot_be_implicitly_unknown(publication, field):
    del publication["food_inventory"][field]
    with pytest.raises(ValueError):
        food_inventory_outcome(publication, 64, 503)


@pytest.mark.parametrize("initial,final,complete", [(27, 27, 1), (None, None, 64), (None, 0, 65)])
def test_endpoint_coverage_cannot_exceed_complete_or_unknown_readings(
    publication, initial, final, complete,
):
    publication["food_inventory"].update(initial_units=initial, final_units=final,
                                        complete_measurements=complete,
                                        unknown_measurements=65 - complete)
    with pytest.raises(ValueError):
        food_inventory_outcome(publication, 64, 503)


@pytest.mark.parametrize("value", [None, False, [], "inventory"])
def test_declared_profile_requires_a_food_review(publication, value):
    publication["food_inventory"] = value
    with pytest.raises(ValueError):
        food_inventory_outcome(publication, 64, 503)


@pytest.mark.parametrize("profile", [None, "other", True])
def test_food_review_requires_declared_measurement_profile(publication, profile):
    publication["private_measurement_profile"] = profile
    with pytest.raises(ValueError):
        food_inventory_outcome(publication, 64, 503)


def test_historical_publications_do_not_gain_food_measurements():
    assert food_inventory_outcome({}, 64, 503) is None
    assert all("food_inventory" not in row
               for row in records.keyboard_campaign_records()["continuations"][:5])
